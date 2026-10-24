#!/usr/bin/env python3
"""Check a plan's `Dispatch:` fields against its dependency graph and `Scope:` sets.

Why this exists: a task's dispatch field is a directive — `executing-plans` hands every
`Dispatch: YES` task to a subagent as soon as its stage opens. The field is authored by
hand, and nothing else reads it back against the facts that make it true or false: whether
the task waits on a sibling, and whether it shares a file with another dispatched task.
A YES that is wrong on either count is not caught by any gate — the subagent simply
runs early, or two subagents edit one file. The master-plan register has the same
failure one level up: an entry marked `Parallel: YES` whose own gate reads a sibling's
output cannot really run in its own session.

FAIL classes (stderr `FAIL: <file>: <CLASS>: <detail>`, exit 1):

    YES-SAME-STAGE-DEP      a YES task whose `Depends on` names a task in its own stage.
                            Before --cutover it is a note: plans dated earlier use the
                            field under looser conventions, and resuming one must not fail
    YES-SHARED-SCOPE        two YES tasks in one stage whose `Scope:` share a path
    YES-NO-SCOPE            a YES task with no `Scope:` — nothing shows it is disjoint.
                            Only in plans dated on or after --cutover (or undated): the
                            rule comes with `Dispatch:`, and plans dated earlier
                            omit `Scope:` on single-artifact tasks by design
    STAGE-CYCLE             the stage-level `**Depends on:**` graph has a cycle
    MASTER-YES-SIBLING-DEP  a register entry marked `Parallel: YES` whose `**Gate:**`
                            block reads a sibling sub-plan its `Depends on` chain never
                            reaches — an undeclared dependency. Depending on a sibling is
                            not one: `Depends on` orders the register, and fan-out after a
                            shared prerequisite is the legal shape (master-plans.md). Nor
                            is naming a descendant in a hedged line ("can consume" — a
                            forward reference; unhedged it is a cycle), or text inside
                            an HTML comment (an amendment annotation). A heuristic over
                            prose: a gate narrating an earlier sibling can still trip it

Notes (stdout `note: <file>: …`, never change the exit code):

    retired spelling  a task-level `Parallel:` in a plan dated on or after --cutover
    could be YES      a NO task with no same-stage dependency whose `Scope:` is disjoint
                      from every sibling's (only when every sibling declares one — a
                      sibling without a Scope could touch anything)

Both spellings of the task field are read: `Dispatch:` (current) and `Parallel:`
(retired). A master register's `Parallel:` is a different field — a recommendation
about sessions — and keeps its name, so it never earns the note.

A master plan (`# Master Plan:` heading or a `-master-plan.md` name) is checked at the
register level, then each sub-plan its register links (`- **Plan:** ./x.md`, resolved
against the master's own directory) gets the task-level checks. Nothing else is read.

Exit: 0 clean (notes allowed), 1 any FAIL, 2 a plan or linked sub-plan cannot be read.
2 takes priority when both apply; every FAIL line is still printed.
Stdlib only.
"""
import argparse
import pathlib
import re
import sys

# The cutover date: a plan dated on or after it uses the `Dispatch:` spelling, and a plan
# dated earlier may use the retired task-level `Parallel:` spelling.
DEFAULT_CUTOVER = "2026-09-23"

FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEDGE_RE = re.compile(r"\b(can|could|will|may|might|would|able to)\b", re.I)
HEADING_RE = re.compile(r"^(#{1,6})\s")
STAGE_RE = re.compile(r"^##\s+Stage\s+(\d+)\b")
TASK_RE = re.compile(r"^###\s+Task\s+(\d+)\.(\d+)\b")
SUBPLAN_RE = re.compile(r"^###\s+Sub-plan\s+0*(\d+)\b")
FIELD_RE = re.compile(r"^\s*(?:[-*]\s+)?\*\*(?P<k>[A-Za-z][A-Za-z -]*?)(?::\*\*|\*\*:)\s*(?P<v>.*)$")
INLINE_FIELD_RE = re.compile(r"\*\*[A-Za-z][A-Za-z -]*?(?::\*\*|\*\*:)")
GATE_MARK_RE = re.compile(r"^\s*\*\*Gate:?\*\*:?\s*$")
DATE_RE = re.compile(r"^\s*(?:\*\*)?Date:?(?:\*\*)?:?\s*(\d{4}-\d{2}-\d{2})")
NAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

TASK_LIST_RE = re.compile(
    r"\bTasks?\s+(\d+\.\d+(?:\s*(?:,|and|&|–|—|-|to)\s*(?:Tasks?\s+)?\d+\.\d+)*)")
BARE_TASK_LIST_RE = re.compile(r"^\s*(\d+\.\d+(?:\s*(?:,|and|&|–|—|-|to)\s*\d+\.\d+)*)")
STAGE_LIST_RE = re.compile(r"\bStages?\s+(\d+(?:\s*(?:,|and|&|\+|/|–|—|-|to)\s*\d+)*)\b")
FOREIGN_STAGE_RE = re.compile(r"\bSub-plans?\s+\d+(?:'s)?\s*(?:\(\s*)?Stages?\s+\d+")
SUBPLAN_LIST_RE = re.compile(r"\bSub-plans?\s+0*(\d+(?:\s*(?:,|and|&|\+)\s*0*\d+)*)\b")
PATH_EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]*$")


def _read(path):
    """Every file this script reads goes through here (the test spies on it)."""
    return pathlib.Path(path).read_text(encoding="utf-8", errors="replace")


def _unfenced(text):
    """Lines of `text` with fenced-code content blanked — a plan quoting a template
    inside a fence must not be read as its own tasks."""
    out, in_fence = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


def _fields(lines):
    """Bold `**Key:**` fields in a block, with indented continuation lines appended."""
    fields, last = {}, None
    for line in lines:
        m = FIELD_RE.match(line)
        if m:
            last = m.group("k").strip().lower()
            # `**Depends on:** Stage 1. **Blocks:** Stage 3, 4.` — one line, two fields.
            value = INLINE_FIELD_RE.split(m.group("v"), 1)[0]
            fields.setdefault(last, value.strip())
            continue
        if last and line[:1].isspace() and line.strip() and not line.lstrip().startswith("-"):
            fields[last] = fields[last] + " " + line.strip()
        else:
            last = None
    return fields


def _is_none(value):
    return re.match(r"^\W*none\b", value, re.I) is not None


def first_word(value):
    m = re.match(r"^[\s`*_]*([A-Za-z]+)", value or "")
    return m.group(1).upper() if m else ""


def _expand(nums):
    """'3.1–3.4, 3.6' → ['3.1','3.2','3.3','3.4','3.6'] (ranges within one stage)."""
    out = []
    parts = re.split(r"\s*(,|and|&|to|–|—|-)\s*", nums)
    prev_range = False
    for p in parts:
        p = re.sub(r"^Tasks?\s+", "", p.strip())
        if p in ("–", "—", "-", "to"):
            prev_range = True
            continue
        if not re.fullmatch(r"\d+\.\d+", p):
            continue
        if prev_range and out:
            a_s, a_t = map(int, out[-1].split("."))
            b_s, b_t = map(int, p.split("."))
            if a_s == b_s and a_t < b_t:
                out.extend(f"{a_s}.{t}" for t in range(a_t + 1, b_t))
        out.append(p)
        prev_range = False
    return out


def task_refs(value):
    if not value or _is_none(value):
        return []
    refs = []
    for m in TASK_LIST_RE.finditer(value):
        refs.extend(_expand(m.group(1)))
    if not refs:
        m = BARE_TASK_LIST_RE.match(value)
        if m:
            refs.extend(_expand(m.group(1)))
    return refs


def _num_list(s):
    return [int(n) for n in re.findall(r"\d+", s)]


def stage_refs(value):
    if not value or _is_none(value):
        return []
    # The dependency list is the first clause. Parentheticals and later sentences are
    # prose about it — e.g. "(the schema lands before Stage 3 …)", "**Stage 4 only
    # reorders work.**" — and read as edges they invent cycles.
    value = re.sub(r"\([^()]*\)", " ", value)
    value = re.split(r"\*\*|\.\s|\.$|;", value, 1)[0]
    value = FOREIGN_STAGE_RE.sub(" ", value)
    refs = []
    for m in STAGE_LIST_RE.finditer(value):
        text = re.sub(r"(\d+)\s*(?:–|—|-|to)\s*(\d+)",
                      lambda r: ",".join(map(str, range(int(r.group(1)), int(r.group(2)) + 1))),
                      m.group(1))
        refs.extend(_num_list(text))
    return refs


def subplan_refs(value):
    refs = []
    for m in SUBPLAN_LIST_RE.finditer(value or ""):
        refs.extend(_num_list(m.group(1)))
    return refs


def scope_tokens(value):
    """Backticked path tokens of a `Scope:` value. A backticked token inside a
    parenthetical is prose about the path before it (`(§ `## Checklist`)`), not a path."""
    toks, depth, i, n = [], 0, 0, len(value or "")
    while i < n:
        c = value[i]
        if c == "`":
            j = value.find("`", i + 1)
            if j < 0:
                break
            tok = value[i + 1:j].strip()
            if depth == 0 and _pathlike(tok):
                toks.append(tok)
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")" and depth:
            depth -= 1
        i += 1
    return toks


def _pathlike(tok):
    if not tok or any(ch.isspace() for ch in tok) or tok.startswith("-"):
        return False
    return "/" in tok or PATH_EXT_RE.search(tok) is not None


def _norm(p):
    p = p.strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def paths_overlap(a, b):
    """Equal; or the shorter is a whole-component suffix of the longer (a bare filename,
    or a partial path); or one is an explicit directory (`dir/`) containing the other."""
    a_dir, b_dir = a.endswith("/"), b.endswith("/")
    a, b = _norm(a).rstrip("/"), _norm(b).rstrip("/")
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    if long_.endswith("/" + short):
        return True
    if a_dir and b.startswith(a + "/"):
        return True
    if b_dir and a.startswith(b + "/"):
        return True
    return False


def plan_date(path, lines):
    for line in lines[:40]:
        m = DATE_RE.match(line)
        if m:
            return m.group(1)
    m = NAME_DATE_RE.match(path.name)
    return m.group(1) if m else None


def parse_plan(lines):
    """Stages {n: {'deps': [..]}} and tasks [{id, stage, fields}] in document order."""
    stages, tasks = {}, []
    stage, block, kind, cur = None, [], None, None

    def flush():
        if kind == "stage" and stage is not None:
            f = _fields(block)
            stages[stage]["deps"] = stage_refs(f.get("depends on", ""))
        elif kind == "task" and cur is not None:
            cur["fields"] = _fields(block)
            tasks.append(cur)

    for line in lines:
        h = HEADING_RE.match(line)
        if h:
            flush()
            block, kind, cur = [], None, None
            sm = STAGE_RE.match(line)
            tm = TASK_RE.match(line)
            if sm:
                stage = int(sm.group(1))
                stages.setdefault(stage, {"deps": []})
                kind = "stage"
            elif tm:
                cur = {"id": f"{tm.group(1)}.{tm.group(2)}", "stage": int(tm.group(1))}
                kind = "task"
            continue
        block.append(line)
    flush()
    return stages, tasks


def _cycle(stages):
    # A stage naming itself (e.g. "Stage 4 gate + user says proceed with Stage 4") is prose,
    # not an edge; a real cycle needs two stages.
    graph = {s: [d for d in v["deps"] if d in stages and d != s] for s, v in stages.items()}
    color, stack = {}, []

    def dfs(s):
        color[s] = 1
        stack.append(s)
        for d in graph[s]:
            if color.get(d) == 1:
                return stack[stack.index(d):] + [d]
            if not color.get(d):
                found = dfs(d)
                if found:
                    return found
        stack.pop()
        color[s] = 2
        return None

    for s in sorted(graph):
        if not color.get(s):
            found = dfs(s)
            if found:
                return found
    return None


def check_tasks(path, lines, cutover, fails, notes):
    stages, tasks = parse_plan(lines)
    name = path.name
    date = plan_date(path, lines)
    new_rules = date is None or date >= cutover

    cyc = _cycle(stages)
    if cyc:
        fails.append((name, "STAGE-CYCLE",
                      " → ".join(f"Stage {s}" for s in cyc)
                      + " — no stage in the loop can open"))

    old = []
    for t in tasks:
        f = t["fields"]
        if "dispatch" in f:
            t["value"] = first_word(f["dispatch"])
        elif "parallel" in f:
            t["value"] = first_word(f["parallel"])
            old.append(t["id"])
        else:
            t["value"] = ""
        t["deps"] = task_refs(f.get("depends on", ""))
        t["has_scope"] = "scope" in f
        t["scope"] = scope_tokens(f.get("scope", ""))

    by_stage = {}
    for t in tasks:
        by_stage.setdefault(t["stage"], []).append(t)

    for s, group in by_stage.items():
        ids = {t["id"] for t in group}
        for t in group:
            same = [d for d in t["deps"] if d != t["id"] and d.split(".")[0] == str(s)]
            t["same_deps"] = same
            if t["value"] != "YES":
                continue
            if same:
                detail = (f"Task {t['id']} is YES but depends on "
                          + ", ".join(f"Task {d}" for d in same)
                          + " in its own stage"
                          + ("" if all(d in ids for d in same) else " (not found)"))
                if new_rules:
                    fails.append((name, "YES-SAME-STAGE-DEP", detail))
                else:
                    notes.append((name, f"YES-SAME-STAGE-DEP (advisory, plan dated before "
                                        f"cutover {cutover}): {detail}"))
            if not t["has_scope"] and new_rules:
                fails.append((name, "YES-NO-SCOPE",
                              f"Task {t['id']} is YES with no Scope: — nothing shows it "
                              f"is disjoint from its siblings"))
        yes = [t for t in group if t["value"] == "YES"]
        for i, a in enumerate(yes):
            for b in yes[i + 1:]:
                shared = sorted({f"{x} ~ {y}" if x != y else x
                                 for x in a["scope"] for y in b["scope"]
                                 if paths_overlap(x, y)})
                if shared:
                    fails.append((name, "YES-SHARED-SCOPE",
                                  f"Task {a['id']} and Task {b['id']} are both YES and "
                                  f"share {', '.join(shared)}"))
        for t in group:
            if t["value"] != "NO" or t["same_deps"] or not t["scope"]:
                continue
            sibs = [o for o in group if o is not t]
            if not sibs or any(not o["scope"] for o in sibs):
                continue
            if any(paths_overlap(x, y) for o in sibs for x in t["scope"] for y in o["scope"]):
                continue
            notes.append((name, f"Task {t['id']} could be YES — no same-stage dependency "
                                f"and its Scope: is disjoint from every sibling"))

    if old and date and date >= cutover:
        notes.append((name, f"Task {', '.join(old)}: Parallel: is the retired spelling — "
                            f"use Dispatch: (plan dated {date}, cutover {cutover})"))


def _gate_block(lines):
    out, inside = [], False
    for line in lines:
        if GATE_MARK_RE.match(line):
            inside = True
            continue
        if not inside:
            continue
        if not line.strip() or line[:1].isspace() or re.match(r"^\s*[-*]\s+\[", line):
            out.append(line)
            continue
        inside = False
    return "\n".join(out)


def register(lines):
    entries, cur, block = [], None, []
    for line in lines + ["# end"]:
        if HEADING_RE.match(line):
            if cur is not None:
                cur["fields"] = _fields(block)
                cur["gate"] = _gate_block(block)
                entries.append(cur)
            cur, block = None, []
            m = SUBPLAN_RE.match(line)
            if m:
                cur = {"n": int(m.group(1))}
            continue
        if cur is not None:
            block.append(line)
    return entries


def plan_link(value):
    m = re.search(r"\]\(([^)\s]+\.md)\)", value or "")
    if m:
        return m.group(1)
    m = re.search(r"([^\s`()\[\]]+\.md)\b", value or "")
    return m.group(1) if m else None


def is_master(path, lines):
    if path.name.endswith("-master-plan.md"):
        return True
    for line in lines:
        if line.startswith("# "):
            return line.startswith("# Master Plan:")
    return False


def check_master(path, lines, fails):
    """Register checks; returns the linked sub-plan paths, resolved against the
    master's own directory."""
    name, subs = path.name, []
    entries = register(lines)
    deps = {}
    for e in entries:
        v = e["fields"].get("depends on", "")
        deps[e["n"]] = set() if _is_none(v) else {k for k in subplan_refs(v) if k != e["n"]}

    def ancestors(n):
        seen, todo = set(), list(deps.get(n, ()))
        while todo:
            k = todo.pop()
            if k not in seen:
                seen.add(k)
                todo.extend(deps.get(k, ()))
        return seen

    for e in entries:
        f, n = e["fields"], e["n"]
        if first_word(f.get("parallel", "")) == "YES":
            # An HTML comment in a gate block is an amendment annotation, not a check:
            # e.g. "AMENDED at Sub-plan 1's close-out" names when, not what the gate reads.
            # So is the `*(amended … was: …)*` note preflight-checks.md requires — its
            # narrative (e.g. "the final gate (Sub-plan 3 below)") is history, not a wait-on.
            gate = re.sub(r"<!--.*?-->", " ", e["gate"], flags=re.S)
            # Backticked spans are consumed whole, as in validate-gate-checks.py.
            gate = re.sub(r"\*\(amended\b(?:`[^`]*`|[^`])*?\)\*", " ", gate, flags=re.S | re.I)
            # A descendant (a sibling whose chain reaches n) named in a HEDGED line is a
            # forward reference (e.g. "Sub-plan 3 can consume …"). Named unhedged (e.g.
            # "Sub-plan 3's suite has passed") it is a wait-on — a cycle — and stays a FAIL.
            descendants = {k for k in deps if n in ancestors(k)}
            forward = set()
            for gline in gate.splitlines():
                if HEDGE_RE.search(gline):
                    forward |= set(subplan_refs(gline)) & descendants
            undeclared = sorted({k for k in subplan_refs(gate) if k != n}
                                - ancestors(n) - forward)
            if undeclared:
                fails.append((name, "MASTER-YES-SIBLING-DEP",
                              f"Sub-plan {n} is Parallel: YES but its Gate: reads "
                              + ", ".join(f"Sub-plan {k}" for k in undeclared)
                              + ", which its Depends on chain never reaches — an "
                                "undeclared dependency; it cannot finish in its own session"))
        link = plan_link(f.get("plan", ""))
        if link:
            subs.append((n, path.parent / link))
    return subs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="validate-dispatch",
                                 description="Check Dispatch:/Parallel: fields against "
                                             "dependencies and Scope: sets.")
    ap.add_argument("plans", nargs="+", type=pathlib.Path)
    ap.add_argument("--cutover", default=DEFAULT_CUTOVER, metavar="YYYY-MM-DD",
                    help="a task-level Parallel: in a plan dated on or after this earns "
                         f"the retired-spelling note (default {DEFAULT_CUTOVER})")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.cutover):
        ap.error(f"--cutover must be YYYY-MM-DD, got {args.cutover!r}")

    fails, notes, errors, seen = [], [], [], set()

    def load(p, why=""):
        try:
            return _unfenced(_read(p))
        except (OSError, UnicodeError) as exc:
            errors.append(f"error: cannot read {p}{why}: {exc.strerror or exc}")
            return None

    for path in args.plans:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        lines = load(path)
        if lines is None:
            continue
        if is_master(path, lines):
            for n, sub in check_master(path, lines, fails):
                skey = sub.resolve()
                if skey in seen:
                    continue
                seen.add(skey)
                sub_lines = load(sub, f" (Sub-plan {n} of {path.name})")
                if sub_lines is not None:
                    check_tasks(sub, sub_lines, args.cutover, fails, notes)
        else:
            check_tasks(path, lines, args.cutover, fails, notes)

    for name, msg in notes:
        print(f"note: {name}: {msg}")
    for name, cls, detail in fails:
        print(f"FAIL: {name}: {cls}: {detail}", file=sys.stderr)
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        return 2
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
