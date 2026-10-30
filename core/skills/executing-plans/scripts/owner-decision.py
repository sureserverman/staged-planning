#!/usr/bin/env python3
"""owner-decision.py — whether a plan's `## Owner decisions` entry applies to the case
the executor is at. The executor acts on an entry only when this lists it, and then runs
exactly the command it passed as --command.

    owner-decision.py match --plan P [--at preflight|stage|closeout]
                            [--stage N] [--task N.M] [--command C] [--require-command] [--json]
    owner-decision.py check P

THE CASE comes from the run state while a run of P is in flight: the state of the
worktree the command runs in, else of the one other worktree of the repo running P, read
as the hooks read it (phase preflight, task or gate at its stage, closeout). --at, --stage
and --task may then be left out; one that disagrees with the state is refused (exit 1), so
a what-if `--task 1.1` at Task 1.2 lists nothing. The run opens a stage with a `transition`
naming the stage and no task, so an ask as Stage N opens is not judged at the last gate. A
run at another phase (blocked, handoff) is at no case to match (exit 1); this worktree's
state that cannot be read, or runs of P in two other worktrees, refuse (exit 2). With no
run of P in flight (planning time, no state, a finished run, a state for another plan) the
arguments are the case, and --at is required.

WHY A SCRIPT. An executor reading `applies to:` itself stretches an entry to the case in
front of it: "the Stage 2 close-out merge offer only" was applied to a one-stage plan's
merge in 3 of 3 runs, twice after the prose said not to.

WHY A STRICT FORMAT. A reader that keeps what it understands and skips the rest passes
whatever it skipped. Two rounds of reading Markdown leniently each left a gap: a
sub-bullet, a heading, a comment, a paragraph or a second marker that changed an entry's
meaning without the reader seeing it. So the section has a fixed shape, and anything
outside it refuses every entry; nothing is interpreted.

THE SECTION holds only these lines; any other line (a heading, a note, a comment, a fence,
an indented or continued line) means no entry in it is read:

  - **OD-N** — <decision> — owner, YYYY-MM-DD: "<words>" — applies to: <places>
  - **OD-N** — <decision> — ask at execution — applies to: <places>
  - none — the catalog triggered no question (swept YYYY-MM-DD)
  (blank lines)

Each entry is one physical line, starting at column 0. The owner's words come before
`applies to:`, exactly in that form, outside any `*(…)*` note; `ask at execution`, anywhere
in the entry, is no answer. A section line is plain printable text (ASCII and the two
dashes); outside code spans an entry holds no `<`, `>`, `~`, `%`, `&` or backslash, and no adjacent or
unbalanced backticks. Lines split only at real line breaks. Raw HTML, an HTML comment or
an Obsidian `%%` comment or a `$$` math block anywhere up to the section's end voids the
section. A fence closes only on the same character, at least as long, with nothing but
spaces or tabs after it; a backtick run whose rest holds a backtick is inline code.

WHAT THIS GUARDS AGAINST: careless writing and careless reading of an entry — a stretched
scope, a restriction left where the reader does not look, a command that is almost the one
approved. Keeping every line plain text means what the script reads is what a person sees.
It does not make a plan safe against an author deliberately crafting it to deceive. `applies to:` appears
once, last, and may hold only:

  Preflight | close-out | Stage N      one position (they never combine)
  Task N.M                             within that stage, or alone (a task implies one)
  Sub-plan N                           in a master's entry: the sub-plan it binds
  `a command`                          every code span; --command must equal one exactly
  and  only  the  at  in  of  on       connectors; punctuation , ; . ( ) * - and dashes

A command matches only as the same characters (outer spaces aside): `rm -rf '*'` is not
`rm -rf *`, and `git merge x` is not `git merge --no-edit x`. `--command` refuses an
entry naming no command, so a command is covered only by an entry naming it;
`--require-command` (a destructive command, every close-out merge step) says so explicitly.

A sub-plan also reads its master's section (its `Master:` backlink). A master entry
applies to a sub-plan only when it names that `Sub-plan N`; its Stage and Task names then
refer to that sub-plan.

`match` exits 0 when at least one entry applies, 1 when none does (ask the owner), 2 on a
usage error or an unreadable plan (ask the owner too). `check` reports every line and every
entry that `match` would refuse at every case, each with its line, and a plan with no
section: exit 1 when there is one, else 0; 2 when the plan cannot be read.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[3] / "lib"
# The hooks' state reader (owned v2 snapshot and legacy file), at <plugin root>/hooks/.
_CLASSIFY = Path(__file__).resolve().parents[3] / "hooks" / "plan_continue_classify.py"
_spec = importlib.util.spec_from_file_location("staged_planning_plan_parser", _LIB / "plan_parser.py")
pu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pu)

# The staleness probe: a stale plugin-cache copy says so before it decides an owner's
# answer under yesterday's rules (as stage-brief.py and plan-flip-audit.py do).
_STALE = _LIB / "staleness.py"


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass


SECTION = re.compile(r"^##[ \t]+Owner decisions[ \t]*$")
H2 = re.compile(r"^##(?!#)[ \t]")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
# What the script reads must be what a reader sees: a section line holds printable ASCII
# and the two dashes the format uses, nothing that renders as something else.
PLAIN = re.compile(r"^[\x20-\x7e\u2013\u2014]*$")
MARKUP = re.compile(r"[<>~%\\&]")
HTML_START = re.compile(r"^ {0,3}<|<!--|-->|%%|\$\$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ENTRY = re.compile(r"^- \*\*(OD-\d+)\*\* — \S")
NONE = re.compile(r"^- none — the catalog triggered no question \(swept \d{4}-\d{2}-\d{2}\)\s*$")
STAGE_HEAD = re.compile(r"^##[ \t]+Stage[ \t]+0*(\d+)\b", re.I)
TASK_HEAD = re.compile(r"^#{2,5}[ \t]+Task[ \t]+(\d+\.\d+)\b", re.I)
NOTE = re.compile(r"\*\([^)]*(?:\([^)]*\)[^)]*)*\)\*")
OWNER = re.compile(r"\bowner,\s*\d{4}-\d{2}-\d{2}:\s*\"[^\"]+\"")
DECLINED = re.compile(r"\bask\s+at\s+execution\b", re.I)
MARKER = re.compile(r"\bapplies to:", re.I)
SPAN = re.compile(r"`([^`]*)`")
PLACE = re.compile(r"\bPreflight\b|\bclose-?out\b|\bStage\s+0*(\d+)\b|\bTask\s+(\d+\.\d+)\b"
                   r"|\bSub-plan\s+0*(\d+)\b", re.I)
WORD = re.compile(r"[^\s,;.()\-–—:*]+")
CONNECTORS = {"and", "only", "the", "at", "in", "of", "on"}
AT = ("preflight", "stage", "closeout")


class Unreadable(Exception):
    pass


def split_lines(text):
    """Lines as Markdown splits them: at \\n, \\r\\n and \\r only (str.splitlines also
    splits at form feed, U+2028 and others, where a renderer shows one line)."""
    lines = LINE_BREAK.split(text)
    return lines[:-1] if lines and lines[-1] == "" else lines


def read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError as e:
        raise Unreadable(f"cannot read {path}: {e.strerror}")


def outside_fences(text):
    """[(line number, line)] of the lines outside code fences. A fence closes only on the
    same character, at least as long (CommonMark), so a nested fence cannot end one."""
    out, opened = [], None
    for n, line in enumerate(split_lines(text), 1):
        m = FENCE.match(line)
        # A backtick fence's info string holds no backtick (CommonMark): "```x```" at a
        # line start is inline code, not a fence.
        if m and m.group(1)[0] == "`" and "`" in line[m.end():]:
            m = None
        if opened is None:
            if m:
                opened = m.group(1)
                continue
            out.append((n, line))
        elif m and m.group(1)[0] == opened[0] and len(m.group(1)) >= len(opened) \
                and re.fullmatch(r"[ \t]*", line[m.end():]):
            opened = None
    return out


def section(text):
    """(found, [(line number, line)], [(line number, why)]) for `## Owner decisions`.
    Every line of the section is returned (fences inside it included, read as text), so
    nothing between the heading and the next `##` goes unseen."""
    lines = split_lines(text)
    starts = [n for n, line in outside_fences(text) if SECTION.match(line)]
    if not starts:
        return False, [], []
    bad = [(n, "a second `## Owner decisions` section") for n in starts[1:]]
    body = []
    for n in range(starts[0] + 1, len(lines) + 1):
        line = lines[n - 1]
        if H2.match(line) and not SECTION.match(line):
            break
        body.append((n, line))
    end = body[-1][0] if body else starts[0]
    # Raw HTML, an HTML comment or an Obsidian %% comment before the section's end may
    # hide the section, or part of it, from a reader while the script still reads it.
    for n, line in outside_fences("\n".join(lines[:end])):
        if HTML_START.search(line):
            bad.append((n, "raw HTML or a comment before or in the section; a reader may not see it"))
            break
    return True, body, bad


def entries(text):
    """(found, [(line, OD id, text)], [(line, why)] lines that are not allowed)."""
    found, body, bad = section(text)
    out, none = [], None
    for n, line in body:
        if not PLAIN.match(line):
            odd = next(c for c in line if not PLAIN.match(c))
            bad.append((n, f"a character outside plain text (U+{ord(odd):04X})"))
            continue
        if not line.strip():
            continue
        if NONE.match(line):
            none = n
            continue
        m = ENTRY.match(line)
        if m:
            out.append((n, m.group(1), line.strip()))
        else:
            bad.append((n, "not an entry line, a blank line or the `none` line"))
    if none and out:
        bad.append((none, "the `none` line beside entries"))
    return found, out, sorted(bad)


def split_entry(text):
    """(decision part, applies-to text) at the `applies to:` marker; None when absent."""
    m = MARKER.search(text)
    if not m:
        return text, None
    return text[:m.start()], text[m.end():]


def parse_places(applies):
    """(places, unread words). Every word is a place, a command, a connector — or unread."""
    commands = {s.strip() for s in SPAN.findall(applies)}
    rest = SPAN.sub(" ", applies)
    p = {"preflight": False, "closeout": False, "stages": set(), "tasks": set(),
         "subplans": set(), "commands": commands}
    for m in PLACE.finditer(rest):
        w = m.group(0).lower()
        if w == "preflight":
            p["preflight"] = True
        elif w.replace("-", "") == "closeout":
            p["closeout"] = True
        elif m.group(1):
            p["stages"].add(int(m.group(1)))
        elif m.group(2):
            p["tasks"].add(m.group(2))
        elif m.group(3):
            p["subplans"].add(int(m.group(3)))
    rest = PLACE.sub(" ", rest)
    unread = [w for w in WORD.findall(rest) if w.lower() not in CONNECTORS]
    return p, unread


def structural(text, stages, tasks, sub=None, master_reg=None, bad=()):
    """(places, None) when the entry can be an answer somewhere, else (None, reason).
    `sub`: the sub-plan number when the entry comes from this plan's master.
    `master_reg`: the register when the plan checked is itself a master.
    `bad`: the section's disallowed lines, which void every entry in it."""
    if DECLINED.search(text):
        return None, "declined: ask at execution"
    if "``" in text or text.count("`") % 2:
        return None, "adjacent or unbalanced backticks; a renderer may read the spans otherwise"
    if MARKUP.search(SPAN.sub(" ", text)):
        return None, "markup outside a code span (< > ~ % & or a backslash); a renderer may show it otherwise"
    if len(MARKER.findall(text)) > 1:
        return None, "more than one `applies to:`; one entry has one"
    decision, applies = split_entry(text)
    plain = NOTE.sub(" ", decision)
    if "*(" in plain:
        return None, "an unterminated `*(` note"
    if not OWNER.search(plain):
        return None, "no owner's words (owner, YYYY-MM-DD: \"…\") before `applies to:`, outside a note"
    if applies is None:
        return None, "no `applies to:`"
    p, unread = parse_places(applies)
    if unread:
        shown = ", ".join(f"'{w}'" for w in unread[:4]) + (", …" if len(unread) > 4 else "")
        why = f"`applies to:` has words the reader cannot place: {shown}"
        missing = [f"no Stage {s}" for s in sorted(p["stages"] - stages)] if master_reg is None and sub is None else []
        return None, why + (f"; and the plan has {', '.join(missing)}" if missing else "")
    if any(not c for c in p["commands"]):
        return None, "an empty code span in `applies to:`"
    if p["subplans"] and master_reg is None and sub is None:
        return None, "names a Sub-plan, outside a master's section"
    positions = [k for k in ("preflight", "closeout") if p[k]] + (["stage"] if p["stages"] or p["tasks"] else [])
    if not positions:
        return None, "names no place (Preflight, close-out, Stage N, Task N.M)"
    if len(positions) > 1:
        return None, "names more than one position (Preflight, close-out and Stage N never combine)"
    if len(p["stages"]) > 1 or len(p["tasks"]) > 1:
        return None, "names more than one stage or task; one entry covers one"
    task = next(iter(p["tasks"]), None)
    if task and p["stages"] and int(task.split(".")[0]) not in p["stages"]:
        return None, f"names Task {task} outside Stage {next(iter(p['stages']))}"
    if master_reg is not None:
        for s in sorted(p["subplans"] - set(master_reg)):
            return None, f"names Sub-plan {s}; the register has no Sub-plan {s}"
        if not p["subplans"]:
            return None, "a master entry that names no Sub-plan"
    elif sub is not None:
        if not p["subplans"]:
            return None, "a master entry that names no Sub-plan"
        if p["subplans"] != {sub}:
            names = ", ".join(f"Sub-plan {n}" for n in sorted(p["subplans"]))
            return None, f"names {names}; this is Sub-plan {sub}"
    elif p["subplans"]:
        return None, "names a Sub-plan, outside a master's section"
    if master_reg is None:
        for s in sorted(p["stages"]):
            if s not in stages:
                have = ", ".join(map(str, sorted(stages))) or "none"
                return None, f"names Stage {s}; the plan has no Stage {s} (stages: {have})"
        if task and task not in tasks:
            return None, f"names Task {task}; the plan has no Task {task}"
    if bad:
        return None, f"the section holds a line that is not an entry (line {bad[0][0]}), so no entry in it is read"
    return p, None


def judge(p, case):
    """None when parsed places `p` cover `case`, else the reason they do not."""
    at = case["at"]
    if p["preflight"] and at != "preflight":
        return f"names Preflight; the case is at {at}"
    if p["closeout"] and at != "closeout":
        return f"names close-out; the case is at {at}"
    if p["stages"] or p["tasks"]:
        stage = next(iter(p["stages"]), None)
        task = next(iter(p["tasks"]), None)
        want = stage if stage is not None else int(task.split(".")[0])
        if at != "stage" or case.get("stage") != want:
            where = f"Stage {case['stage']}" if at == "stage" else at
            return f"names Stage {want}; the case is at {where}"
        if task and case.get("task") != task:
            return f"names Task {task}; the case is at {'Task ' + case['task'] if case.get('task') else 'no task'}"
    command = case["command"].strip() if case.get("command") else None
    if p["commands"]:
        if command is None:
            return "names commands; pass the one being run with --command"
        if command not in p["commands"]:
            return f"names other commands than `{command}` (commands match as exact text)"
    elif command is not None or case.get("require_command"):
        return "names no command, and this case needs the exact command named"
    return None


def plan_places(text):
    stages, tasks = set(), set()
    for _, line in outside_fences(text):
        if m := STAGE_HEAD.match(line):
            stages.add(int(m.group(1)))
        if m := TASK_HEAD.match(line):
            tasks.add(m.group(1))
    return stages, tasks


def register(master_text, master_path):
    """{sub-plan number: resolved plan path or None} of a master's register."""
    out, num = {}, None
    for _, line in outside_fences(master_text):
        if m := pu.SUBPLAN_RE.match(line):
            num = int(m.group(1))
            out[num] = None
            continue
        lm = pu.SUBPLAN_LINK_RE.match(line)
        if lm and num is not None and out.get(num) is None:
            target = pu.link_target(lm.group(1))
            out[num] = (master_path.parent / target).resolve() if target else None
    return out


def master_entries(text, plan_path):
    """[(master path, line, id, text, sub-plan number, the master's bad lines)]."""
    head = []
    bm = None
    for _, line in outside_fences(text):
        if (bm := pu.MASTER_BACKLINK_RE.match(line)):
            break
        head.append(line)
    # A Master: link a comment or raw HTML may hide is not followed: the reader would not
    # know the plan inherits anything.
    if bm is None or any(HTML_START.search(line) for line in head):
        return []
    target = pu.link_target(bm.group(1))
    if not target:
        return []
    mpath = (plan_path.parent / target).resolve()
    if not mpath.is_file():
        return []
    mtext = read(mpath)
    num = next((k for k, v in register(mtext, mpath).items() if v == plan_path.resolve()), None)
    if num is None:
        return []
    _, ents, bad = entries(mtext)
    return [(mpath, n, i, t, num, bad) for n, i, t in ents]


class Refused(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


GIT_IDENTITY = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def run_case(plan_path):
    """(at, stage, task) where the run of this plan is, or None when no run of it is in
    flight (no repo, no state, a finished run, a state for another plan). Read as the
    hooks read it: the git top level of the working directory first, then every other
    worktree of the repo, since each keeps its own git-ignored state. Raises Refused when
    this worktree's state cannot be read, when two other worktrees run this plan, or when
    the run is at no case match can judge."""
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    root = Path(r.stdout.strip())
    try:
        spec = importlib.util.spec_from_file_location("plan_continue_classify", _CLASSIFY)
        cls = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls)
    except Exception as e:  # noqa: BLE001 — no reader means no answer, never the arguments
        raise Refused(f"cannot read the run state {root / '.claude' / 'plan-progress.json'} "
                      f"({type(e).__name__}); ask the owner", 2)
    # Each worktree holds its own copy of a tracked plan, so another worktree's run of
    # this plan names the same path relative to that worktree.
    try:
        rel = plan_path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = None
    state = run_in(cls, root, plan_path, own=True)
    if state is not None:
        return case_of(state, root)
    found = []
    for wt in worktrees(root):
        if wt.resolve() != root.resolve():
            state = run_in(cls, wt, plan_path, own=False, rel=rel)
            if state is not None:
                found.append((wt, state))
    if len(found) > 1:
        raise Refused(f"runs of this plan are in flight in {len(found)} worktrees ("
                      + ", ".join(str(wt) for wt, _ in found) + "); ask the owner", 2)
    return case_of(found[0][1], found[0][0]) if found else None


def worktrees(root):
    """Every worktree of root's repository, from `git worktree list --porcelain`."""
    try:
        r = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(l[len("worktree "):]) for l in r.stdout.splitlines() if l.startswith("worktree ")]


def run_in(cls, root, plan_path, own, rel=None):
    """root's state when it is a run of this plan in flight, else None. Only this
    worktree's own unreadable state refuses: another worktree's unreadable state cannot
    say which plan it runs, so it is named on stderr and not counted."""
    state_file = root / ".claude" / "plan-progress.json"
    # git sets these in a hook or a linked worktree's environment; another worktree's
    # owned snapshot is read with git pointed at that worktree, as the hooks read it.
    saved = {} if own else {k: os.environ.pop(k) for k in GIT_IDENTITY if k in os.environ}
    try:
        state = cls.read_state(str(root))
    except Exception as e:  # noqa: BLE001
        state = {"state_status": "state_error", "note": type(e).__name__}
    finally:
        os.environ.update(saved)
    unreadable = (state is None and os.path.lexists(state_file)) or not (
        state is None or (isinstance(state, dict) and state.get("state_status") != "state_error"))
    if unreadable:
        note = state.get("note", "") if isinstance(state, dict) else ""
        if own:
            raise Refused(f"cannot read the run state {state_file}"
                          + (f" ({note})" if note else "") + "; ask the owner", 2)
        print(f"owner-decision: note: cannot read the run state {state_file}; not counted",
              file=sys.stderr)
        return None
    if state is None or cls.finished(state, str(root)):
        return None
    named = state.get("plan")
    if not isinstance(named, str) or not named.strip():
        return None
    named = (Path(named) if os.path.isabs(named) else root / named).resolve()
    if named == plan_path.resolve():
        return state
    return state if rel is not None and named == (root / rel).resolve() else None


def case_of(state, root):
    """(at, stage, task) of a run state, or Refused when it is at no case match judges."""
    state_file = root / ".claude" / "plan-progress.json"
    phase = state.get("phase")
    if phase == "preflight":
        return "preflight", None, None
    if phase == "closeout":
        return "closeout", None, None
    if phase in ("task", "gate"):
        try:
            stage = int(state.get("stage"))
        except (TypeError, ValueError):
            raise Refused(f"cannot read the run state {state_file} (stage "
                          f"{state.get('stage')!r}); ask the owner", 2)
        task = state.get("task") if phase == "task" else None
        task = task.strip() if isinstance(task, str) and task.strip() else None
        if task is not None and task.split(".")[0] != str(stage):
            task = None  # a stage opened with no task keeps the last stage's task field
        return "stage", stage, task
    raise Refused(f"the run state is at phase {phase!r} ({state_file}), not at a task, stage "
                  "or close-out match can judge; ask the owner", 1)


def case_from_run(a, at_run):
    """(at, stage, task) of the run, refusing any argument that disagrees with it."""
    at, stage, task = at_run
    where = f"stage {stage}" if stage is not None else f"at {at}"
    if a.at is not None and a.at != at:
        raise Refused(f"--at {a.at} disagrees with the run state (at {at}); ask the owner", 1)
    if a.stage is not None and a.stage != stage:
        raise Refused(f"--stage {a.stage} disagrees with the run state ({where}); ask the owner", 1)
    if a.task is not None and a.task.strip() != task:
        shown = f"task {task}" if task else f"no task: {where}"
        raise Refused(f"--task {a.task} disagrees with the run state ({shown}); ask the owner", 1)
    return at, stage, task


def cmd_match(a):
    plan_path = Path(a.plan)
    try:
        at_run = run_case(plan_path)
        at, stage, task = case_from_run(a, at_run) if at_run else (a.at, a.stage, a.task)
    except Refused as e:
        print(f"owner-decision: {e}", file=sys.stderr)
        return e.code
    if at is None:
        print("owner-decision: --at is needed when no run of this plan is in flight", file=sys.stderr)
        return 2
    if at == "stage" and stage is None:
        print("owner-decision: --at stage needs --stage", file=sys.stderr)
        return 2
    case = {"at": at, "stage": stage, "task": task, "command": a.command,
            "require_command": a.require_command}
    text = read(plan_path)
    stages, tasks = plan_places(text)
    is_master = pu.is_master_plan(text, plan_path)
    _, own, bad = entries(text)
    cands = [(plan_path, n, i, t, None, bad) for n, i, t in own] + master_entries(text, plan_path)
    applies, refused = [], []
    for src, n, i, t, sub, src_bad in cands:
        reg = register(text, plan_path) if is_master and src == plan_path else None
        p, why = structural(t, stages, tasks, sub, reg, src_bad)
        if p is not None and reg is not None:
            why = "a master entry binds the sub-plan it names; run match on that sub-plan"
        elif p is not None:
            why = judge(p, case)
        rec = {"id": i, "file": str(src), "line": n}
        if why is None:
            applies.append(rec)
        else:
            refused.append({**rec, "reason": why})
    if a.json:
        print(json.dumps({"case": case, "applies": applies, "refused": refused}, indent=2))
    else:
        for r in applies:
            print(f"applies {r['id']}  ({Path(r['file']).name}:{r['line']})")
        for r in refused:
            print(f"refused {r['id']}  ({Path(r['file']).name}:{r['line']}) — {r['reason']}")
        if not applies:
            print("no entry applies: ask the owner")
    return 0 if applies else 1


def cmd_check(a):
    plan_path = Path(a.plan)
    text = read(plan_path)
    stages, tasks = plan_places(text)
    reg = register(text, plan_path) if pu.is_master_plan(text, plan_path) else None
    found, own, bad = entries(text)
    problems = [(n, "-", f"line {n}: {why}") for n, why in bad]
    if not found:
        problems.append((0, "-", "no `## Owner decisions` section (write the `none` line when nothing triggered)"))
    elif not own and not bad and not any(NONE.match(l) for _, l in section(text)[1]):
        problems.append((0, "-", "an empty `## Owner decisions` section (write the `none` line when nothing triggered)"))
    for n, i, t in own:
        p, why = structural(t, stages, tasks, None, reg, bad)
        if why and why != "declined: ask at execution":
            problems.append((n, i, why))
    out = [f"{plan_path.name}:{n}: {i}: {why}" for n, i, why in sorted(problems)]
    # The section a sub-plan inherits is checked too, so check agrees with match.
    for src, n, i, t, sub, mbad in master_entries(text, plan_path):
        p, why = structural(t, stages, tasks, sub, None, mbad)
        if why and why != "declined: ask at execution" and not why.startswith("names Sub-plan") \
                and why != "a master entry that names no Sub-plan":
            out.append(f"{Path(src).name}:{n}: {i}: {why}")
            problems.append((n, i, why))
    for line in out:
        print(line)
    if not problems:
        print(f"{plan_path.name}: {len(own)} owner decision(s), no problem")
    return 1 if problems else 0


def main(argv=None):
    _warn_if_stale()
    ap = argparse.ArgumentParser(prog="owner-decision.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="op", required=True)
    m = sub.add_parser("match")
    m.add_argument("--plan", required=True)
    m.add_argument("--at", choices=AT)
    m.add_argument("--stage", type=int)
    m.add_argument("--task")
    m.add_argument("--command")
    m.add_argument("--require-command", action="store_true")
    m.add_argument("--json", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("plan")
    a = ap.parse_args(argv)
    try:
        return cmd_match(a) if a.op == "match" else cmd_check(a)
    except Unreadable as e:
        print(f"owner-decision: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
