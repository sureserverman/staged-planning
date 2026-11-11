#!/usr/bin/env python3
"""Structure suite for owner decisions — run directly (CI convention):

    python3 core/skills/planning-projects/tests/test-owner-decisions-contract.py

PROSE contract, not behavior. Planning asks the questions execution would stop for and
records the answers in the plan's `## Owner decisions`; execution reads them before it
asks. What it pins:

  1. references/owner-decisions.md names every bullet of § Safety rails and § Stop
     conditions of every executing-plans trunk (core, and each host override found by
     glob) by its opening words, each classed `ask while planning` or `stays a stop`.
  2. The Standard, Light and master templates carry a `## Owner decisions` section whose
     example bullets are not checkboxes.
  3. The Standard and Light checklists carry the owner-decisions item, and the Light
     list's stated count matches its items, as does every planning-projects trunk.
  4. Every planning-projects trunk carries, under § Phase -1, `### Ask execution's
     questions now`, naming the catalog, the batched round and the record; its
     one-at-a-time rule defers execution questions to that round; its reference map
     routes to the catalog.
  5. Every executing-plans trunk reads the record before it asks (§ Stop conditions),
     takes a destructive command's confirmation from an entry naming it (§ Safety rails);
     every close-out.md copy carries out a recorded merge at step 10; every
     stage-gate.md copy's ACTION NEEDED section checks the record first.
  6. An entry applies only when every qualifier of its `applies to:` holds — stated in
     § Stop conditions and the catalog, cited by close-out step 10 and § ACTION NEEDED;
     `init` runs on the run's branch.
  7. Every place the executor matches an entry runs `owner-decision.py match` and acts
     only on what it lists; a destructive command passes --require-command.
  8. The catalog's record names `owner-decision.py check` and the place words it reads;
     both checklist items run it.
  9. In every executing-plans SKILL.md, close-out.md, stage-gate.md and preflight-checks.md
     copy, each paragraph or bullet naming an owner decision names `match` (a property,
     so a site nobody listed fails too).

Why: a trunk that gains a stop the catalog does not name is a stop planning never asks
about, and the run halts on it mid-stage.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
PP = os.path.join(SKILLS, "planning-projects")
REF = os.path.join(PP, "references")


def repo_root():
    """The source tree's root when this runs from core/, else None (a built copy)."""
    d = SKILLS
    for _ in range(4):
        d = os.path.dirname(d)
        if os.path.isdir(os.path.join(d, "hosts")) and os.path.isdir(os.path.join(d, "core")):
            return d
    return None


ROOT = repo_root()

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(text, heading):
    """The body under the first heading line equal to `heading`, to the next heading of
    the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    out, inside = [], False
    for line in text.splitlines():
        m = re.match(r"^(#+)\s", line)
        if inside and m and len(m.group(1)) <= level:
            break
        if inside:
            out.append(line)
        elif line.strip() == heading:
            inside = True
    return "\n".join(out)


def trunks(skill):
    """Every trunk of `skill`: the one beside this suite, and each host override."""
    found = [os.path.join(SKILLS, skill, "SKILL.md")]
    if ROOT is not None:
        found += sorted(glob.glob(os.path.join(ROOT, "hosts", "*", "overrides", "skills", skill, "SKILL.md")))
    return [p for p in found if os.path.isfile(p)]


def rel(path):
    return os.path.relpath(path, ROOT) if ROOT else path


def plain(s):
    return re.sub(r"[*`]", "", s).strip()


def opening_words(bullet):
    """A bullet's name: its bold lead when it has one, else its first four words."""
    m = re.match(r"^\*\*(.+?)\*\*", bullet)
    if m:
        return plain(m.group(1)).rstrip(".")
    return " ".join(plain(bullet).split()[:4])


def bullets(body):
    return [line[2:] for line in body.splitlines() if line.startswith("- ")]


def catalog_rows():
    body = section(read(os.path.join(REF, "owner-decisions.md")),
                   "### Where the executor stops: its Safety rails and Stop conditions")
    rows = []
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and line.startswith("|") and not set(cells[0]) <= {"-"}:
            rows.append((plain(cells[0]), cells[1]))
    return rows[1:]   # the header row


def part1_catalog_names_every_stop():
    present = os.path.isfile(os.path.join(REF, "owner-decisions.md"))
    check("1 references/owner-decisions.md exists", present, "missing")
    if not present:
        return
    rows = catalog_rows()
    check("1 the catalog has rows", len(rows) >= 10, f"{len(rows)} rows")
    classes = {c for _, c in rows}
    check("1 every catalog row is classed ask-while-planning or stays-a-stop",
          classes <= {"ask while planning", "stays a stop"}, f"{classes}")
    found = trunks("executing-plans")
    check("1 every executing-plans trunk is found", len(found) >= (4 if ROOT else 1), f"{found}")
    for path in found:
        text = read(path)
        for name in ("## Safety rails", "## Stop conditions"):
            items = bullets(section(text, name))
            check(f"1 {rel(path)} {name} has bullets", len(items) > 0)
            for b in items:
                key = opening_words(b)
                hit = [c for r, c in rows if r.startswith(key)]
                check(f"1 {rel(path)} {name}: the catalog names `{key}`", len(hit) == 1,
                      f"{len(hit)} catalog rows open with it")


def part2_templates_carry_the_section():
    for name in ("plan-document-template.md", "light-plan-format.md", "master-plan-format.md"):
        text = read(os.path.join(REF, name))
        body = section(text, "## Owner decisions")
        lines = [l for l in body.split("```")[0].splitlines() if l.strip()]
        check(f"2 {name}: the section holds only one-line entries (owner-decision.py reads nothing else)",
              lines and all(l.startswith("- **OD-") or l.startswith("- none — ") for l in lines), lines[:3])
        check(f"2 {name} carries a `## Owner decisions` section", body.strip() != "", "missing")
        check(f"2 {name}: its example bullets are not checkboxes",
              "**OD-1**" in body and not re.search(r"(?m)^\s*- \[[ x~]\]", body), body[:200])


def part3_checklists_carry_the_item():
    text = read(os.path.join(REF, "authoring-checklist.md"))
    for name in ("## Checklist — Standard plans", "## Checklist — Light plans"):
        body = section(text, name)
        check(f"3 {name} carries the owner-decisions item",
              re.search(r"(?m)^- \[ \] .*`## Owner decisions`", body) is not None, "missing")
    light = section(text, "## Checklist — Light plans")
    words = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13}
    m = re.search(r"verify only\s+these\s+(\w+)", light)
    stated = words.get(m.group(1)) if m else None
    items = len(re.findall(r"(?m)^- \[ \] ", light))
    check("3 the Light list's stated count matches its items", stated == items,
          f"stated {m.group(1) if m else None}, items {items}")
    for path in trunks("planning-projects"):
        m = re.search(r"verify only the (\w+) Light items", read(path))
        check(f"3 {rel(path)} states the same Light count",
              m is not None and words.get(m.group(1)) == items, f"{m.group(1) if m else None} vs {items}")


def part4_planning_asks_the_round():
    found = trunks("planning-projects")
    check("4 every planning-projects trunk is found", len(found) >= (2 if ROOT else 1), f"{found}")
    for path in found:
        text = read(path)
        phase = section(text, "## Phase -1 — Clarification")
        body = section(phase, "### Ask execution's questions now")
        check(f"4 {rel(path)} § Phase -1 carries `### Ask execution's questions now`",
              body.strip() != "", "missing")
        for needle in ("references/owner-decisions.md", "one batched round", "## Owner decisions"):
            check(f"4 {rel(path)}: the section names {needle}", needle in body, "missing")
        check(f"4 {rel(path)}: the reference map routes to the catalog",
              re.search(r"(?m)^\| `references/owner-decisions\.md` \|", section(text, "## Reference map")) is not None,
              "no row")


# sha256 of `### Ask execution's questions now` as the 2026-11-10 trim found it (commit
# 1d6eaaf). A digest rather than a `git show` of that commit, so the check runs in a
# shallow clone; a deliberate edit to the section updates this line with it.
ASK_NOW_SHA256 = "7c25bc8d9bb672101dc3e2fd64d6e09e1c2d5dc0ba3317419023c128c6a9ffe3"
ASK_NOW = "### Ask execution's questions now"
PHASE_1 = "## Phase -1 — Clarification"
PHASE_1_RULES = ("ask only what would change the plan and the repo cannot answer",
                 "state an inferred answer as an assumption",
                 "batch the questions in the host's question tool")


def raw_section(text, heading):
    """The heading line and its body, byte for byte, to the next heading of the same or a
    higher level or a `---` rule, whichever comes first."""
    level = len(heading) - len(heading.lstrip("#"))
    m = re.search(r"(?m)^" + re.escape(heading) + r"\n", text)
    if not m:
        return ""
    end = re.compile(r"(?m)^(?:#{1,%d}\s|---$)" % level).search(text, m.end())
    return text[m.start():end.start() if end else len(text)]


def part4b_phase_minus_1_is_one_paragraph():
    """Catches: Phase -1 growing back into a method tutorial, or asking one question at a
    time. The rule is one paragraph above `### Ask execution's questions now`, which is the
    only subsection left and is never touched by the trim. Pinned on the source trunk; a
    host fork follows it through the build check."""
    path = os.path.join(PP, "SKILL.md")
    text = read(path)
    phase = raw_section(text, PHASE_1)
    # From the heading to `### Ask execution's questions now`, less a host's own `### On
    # <host>:` insert (a built Codex copy carries one there).
    head = phase.split("\n" + ASK_NOW + "\n", 1)[0]
    head = re.sub(r"(?ms)^### On [^\n]*:.*", "", head)
    size = len(head.encode("utf-8"))
    check(f"4b {rel(path)}: Phase -1 above `{ASK_NOW}` is at most 900 bytes", size <= 900, f"{size} B")
    flat = " ".join(plain(head).split()).lower()
    for rule in PHASE_1_RULES:
        check(f"4b {rel(path)}: Phase -1 says to {rule}", rule in flat, "missing")
    check(f"4b {rel(path)}: Phase -1 no longer says `One question at a time`",
          "one question at a time" not in flat, "still there")
    if ROOT is not None:
        subs = re.findall(r"(?m)^### .*$", phase)
        check(f"4b {rel(path)}: `{ASK_NOW}` is Phase -1's only subsection", subs == [ASK_NOW], f"{subs}")
        import hashlib
        now = raw_section(text, ASK_NOW)
        digest = hashlib.sha256(now.encode("utf-8")).hexdigest()
        check(f"4b {rel(path)}: `{ASK_NOW}` is byte-identical to the section the trim found",
              now != "" and digest == ASK_NOW_SHA256, f"sha256 {digest[:12]}…, {len(now)} B")
    # Every marker the classification table pins for Phase -1 or a heading under it (the
    # removed ones included, so a row left naming deleted text fails here).
    table = read(os.path.join(REF, "extraction-classification.md"))
    names = {"Phase -1 — Clarification", "When to ask", "How to ask", "When NOT to ask"}
    names |= {s[4:] for s in re.findall(r"(?m)^### .*$", phase)}
    markers = section(table, "## Retention markers")
    rows = []
    for line in markers.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 2 and cells[0] in names:
            rows.append(cells)
    check("4b the classification table pins Phase -1 markers", len(rows) >= 1, "none")
    for sec, marker in rows:
        check(f"4b marker `{marker}` ({sec}) is in Phase -1 of the trunk", marker in phase, "missing")


def copies(skill, rel_path):
    """`rel_path` under `skill` beside this suite, and each host override of it."""
    found = [os.path.join(SKILLS, skill, rel_path)]
    if ROOT is not None:
        found += sorted(glob.glob(os.path.join(ROOT, "hosts", "*", "overrides", "skills", skill, rel_path)))
    return [p for p in found if os.path.isfile(p)]


def section_starting(text, prefix):
    """The body under the first heading line that starts with `prefix`."""
    for line in text.splitlines():
        if line.startswith(prefix):
            return section(text, line.strip())
    return ""


def part5_execution_reads_the_answers():
    found = trunks("executing-plans")
    for path in found:
        text = read(path)
        stops = " ".join(section(text, "## Stop conditions").split())
        check(f"5 {rel(path)} § Stop conditions reads `## Owner decisions` before asking",
              "## Owner decisions" in stops and "`OD-N`" in stops, "missing")
        for needle in ("A case no entry names stops", "An entry covers only the case it names, never a wider one",
                       "`ask at execution` is no answer"):
            check(f"5 {rel(path)} § Stop conditions keeps the narrow reading: {needle!r}",
                  needle in stops, "missing")
        rails = bullets(section(text, "## Safety rails"))
        for lead, needle in (("**Destructive commands**", "even if the plan (a task, gate check or close-out step) says to"),
                             ("**Destructive commands**", "an owner decision naming that command"),
                             ("**Secrets**", "unless an owner decision names it"),
                             ("**Shared infrastructure**", "an owner decision naming the stage")):
            hit = [b for b in rails if b.startswith(lead)]
            check(f"5 {rel(path)} § Safety rails {lead}: {needle!r}",
                  len(hit) == 1 and needle in hit[0], hit[:1])
        closing = section_starting(text, "## Phase Close-out")
        check(f"5 {rel(path)} § Phase Close-out keeps the merge confirmation",
              "**Do not merge without explicit confirmation**" in closing, closing[:160])
    outs = copies("executing-plans", "references/close-out.md")
    check("5 every close-out.md copy is found", len(outs) >= (4 if ROOT else 1), f"{outs}")
    for path in outs:
        m = re.search(r"(?ms)^10\. (.*?)(?=^\d+\. |^\S|\Z)", read(path))
        step = m.group(1) if m else ""
        check(f"5 {rel(path)} step 10 carries out the recorded merge before offering one",
              step.startswith("Carry out the merge") and "## Owner decisions" in step, step[:160])
        check(f"5 {rel(path)} step 10 keeps the merge confirmation",
              "Do not merge without explicit confirmation" in step, step[-160:])
        # Catches: a recorded branch deletion run before `finish`, which the run's owner
        # (its branch) then refuses — the close-out cannot record itself finished.
        check(f"5 {rel(path)} step 10 runs `plan-state.py finish` before it leaves the run's branch",
              re.search(r"`plan-state\.py finish`[^.]*before[^.]*branch", " ".join(step.split())) is not None,
              step[:200])
    gates = copies("executing-plans", "references/stage-gate.md")
    check("5 every stage-gate.md copy is found", len(gates) >= (4 if ROOT else 1), f"{gates}")
    for path in gates:
        body = section_starting(read(path), "## ACTION NEEDED")
        first = body.strip().split("\n\n")[0] if body.strip() else ""
        check(f"5 {rel(path)} § ACTION NEEDED checks the owner decisions first",
              "## Owner decisions" in first, first[:160])


STRICT = "every qualifier of its `applies to:` holds"


def part6_an_entry_is_never_stretched_to_fit():
    """Catches: an entry scoped to a stage, task or command the case does not match — or
    the plan does not have — read as covering it (a Stage-2 merge entry applied to a
    one-stage plan's merge). Each place an executor matches an entry carries or cites the
    one strict rule; and `init` waits for the run's branch, which owns the run."""
    for path in trunks("executing-plans"):
        text = read(path)
        stops = " ".join(section(text, "## Stop conditions").split())
        check(f"6 {rel(path)} § Stop conditions: an entry applies only when {STRICT}",
              STRICT in stops and "never reinterpret it to fit" in stops, "missing")
        prog = " ".join(section_starting(text, "## Progress state file").split())
        check(f"6 {rel(path)} § Progress state file: `init` runs on the run's branch",
              re.search(r"Call `init` when Preflight starts[^.]*on the run's branch", prog) is not None, prog[:200])
    for path in copies("executing-plans", "references/close-out.md"):
        m = re.search(r"(?ms)^10\. (.*?)(?=^\d+\. |^\S|\Z)", read(path))
        step = " ".join((m.group(1) if m else "").split())
        check(f"6 {rel(path)} step 10 acts only on an entry where {STRICT}", STRICT in step, step[:200])
    for path in copies("executing-plans", "references/stage-gate.md"):
        body = section_starting(read(path), "## ACTION NEEDED")
        first = " ".join((body.strip().split("\n\n")[0] if body.strip() else "").split())
        check(f"6 {rel(path)} § ACTION NEEDED settles only where {STRICT}", STRICT in first, first[:200])
    for path in copies("executing-plans", "references/progress-state-file.md"):
        rows = [l for l in read(path).splitlines() if l.startswith("| Preflight starts") and "| `init` |" in l]
        check(f"6 {rel(path)}: the `init` row runs on the run's branch",
              len(rows) == 1 and "on the run's branch" in rows[0], rows[:1])
    # Not section(): the record's example block holds a `## Owner decisions` line.
    m = re.search(r"(?ms)^## The record\n(.*?)^## How to ask", read(os.path.join(REF, "owner-decisions.md")))
    record = " ".join((m.group(1) if m else "").split())
    check("6 owner-decisions.md § The record: an unmatched qualifier means the entry does not apply",
          STRICT in record and "never reinterpret" in record, "missing")


MATCH = "owner-decision.py match"


def part7_the_script_decides():
    """Catches: an ask point where the executor still reads `applies to:` itself. Prose
    alone let a Stage-2 entry decide a one-stage plan's merge twice after the rule was
    tightened; each place the executor matches an entry must run the script and act only
    on what it lists."""
    for path in trunks("executing-plans"):
        text = read(path)
        stops = " ".join(section(text, "## Stop conditions").split())
        check(f"7 {rel(path)} § Stop conditions: act only on an entry `{MATCH}` lists",
              MATCH in stops and "lists" in stops, "missing")
        # Catches M1: an executor that checks one command and runs another.
        check(f"7 {rel(path)} § Stop conditions: run exactly the command passed to --command",
              "exactly the command" in stops, "missing")
        secrets = [b for b in bullets(section(text, "## Safety rails")) if b.startswith("**Secrets**")]
        check(f"7 {rel(path)} § Safety rails: a secret's mechanism runs `{MATCH} --at stage --stage N`",
              len(secrets) == 1 and f"{MATCH} --at stage --stage N" in secrets[0], secrets[:1])
        rails = [b for b in bullets(section(text, "## Safety rails")) if b.startswith("**Destructive commands**")]
        check(f"7 {rel(path)} § Safety rails: a destructive command runs `{MATCH}` with --require-command",
              len(rails) == 1 and MATCH in rails[0] and "--require-command" in rails[0], rails[:1])
    for path in copies("executing-plans", "references/close-out.md"):
        m = re.search(r"(?ms)^10\. (.*?)(?=^\d+\. |^\S|\Z)", read(path))
        step = " ".join((m.group(1) if m else "").split())
        check(f"7 {rel(path)} step 10 runs `{MATCH}` at close-out", MATCH in step and "--at closeout" in step, step[:200])
        # Catches I1: a merge step settled by an entry that names no command.
        check(f"7 {rel(path)} step 10 passes --require-command", "--require-command" in step, step[:200])
    for path in copies("executing-plans", "references/stage-gate.md"):
        body = section_starting(read(path), "## ACTION NEEDED")
        first = " ".join((body.strip().split("\n\n")[0] if body.strip() else "").split())
        check(f"7 {rel(path)} § ACTION NEEDED settles a decision only by `{MATCH}`", MATCH in first, first[:200])


CHECK = "owner-decision.py check"


def part8_the_author_checks():
    """Catches: an author writing `applies to:` in words the script cannot place, so every
    entry is refused at execution and the batched round bought nothing — or an entry naming
    a stage the plan lacks reaching the executor at all."""
    m = re.search(r"(?ms)^## The record\n(.*?)^## How to ask", read(os.path.join(REF, "owner-decisions.md")))
    record = " ".join((m.group(1) if m else "").split())
    check(f"8 owner-decisions.md § The record names `{CHECK}`", CHECK in record, "missing")
    for rule in ("every code span there is a command", "never combine", "deny by default",
                 "one physical line", "nothing else in the section", "exact text",
                 "plain printable text", "voids the section", "not against an author"):
        check(f"8 owner-decisions.md § The record states the grammar: {rule!r}", rule in record, "missing")
    for word in ("`Preflight`", "`close-out`", "`Stage N`", "`Task N.M`", "`Sub-plan N`", "backticked command"):
        check(f"8 owner-decisions.md § The record names the place word {word}", word in record, "missing")
    text = read(os.path.join(REF, "authoring-checklist.md"))
    for name in ("## Checklist — Standard plans", "## Checklist — Light plans"):
        items = [l for l in section(text, name).splitlines() if l.startswith("- [ ] ") and "## Owner decisions" in l]
        check(f"8 {name}: the owner-decisions item runs `{CHECK}`",
              len(items) == 1 and CHECK in items[0], items[:1])


def units(text):
    """Paragraphs and bullets (with their continuation lines), outside code fences.
    Lines inside a fence are kept as one unit per fence, so a diagram's sentence is whole."""
    out, cur = [], []
    for line in text.splitlines():
        starts = re.match(r"^\s*(?:[-*+]|\d+[.)])\s", line) or line.startswith("|")
        if not line.strip() or (starts and cur):
            if cur:
                out.append(" ".join(cur))
            cur = [] if not line.strip() else [line.strip()]
            continue
        cur.append(line.strip().lstrip("│ "))
    if cur:
        out.append(" ".join(cur))
    return out


def part9_no_owner_decision_settles_without_match():
    """Catches I2's class (absence-shaped): a sentence that lets an owner decision settle
    a confirmation — the merge, a secret, a stage, the remote — without running the
    script, so the executor reads the entry itself again. Asserted as a property of every
    unit that mentions an owner decision, not as a list of the sites found."""
    for rel_path in ("SKILL.md", "references/close-out.md", "references/stage-gate.md",
                     "references/preflight-checks.md"):
        for path in copies("executing-plans", rel_path):
            for u in units(read(path)):
                if not re.search(r"owner decision|Owner decisions", u, re.I) or u.startswith("|"):
                    continue
                check(f"9 {rel(path)}: a unit naming an owner decision names `match` — {u[:70]!r}",
                      "match" in u, u[:240])


def main():
    part1_catalog_names_every_stop()
    part2_templates_carry_the_section()
    part3_checklists_carry_the_item()
    part4_planning_asks_the_round()
    part4b_phase_minus_1_is_one_paragraph()
    part5_execution_reads_the_answers()
    part6_an_entry_is_never_stretched_to_fit()
    part7_the_script_decides()
    part8_the_author_checks()
    part9_no_owner_decision_settles_without_match()
    if FAILED:
        print(f"\n{len(FAILED)} failure(s)")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
