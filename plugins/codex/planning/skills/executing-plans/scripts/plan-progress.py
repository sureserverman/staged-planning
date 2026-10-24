#!/usr/bin/env python3
"""plan-progress — the gate checks of executing-plans, without the status-line renderer.

    plan-progress.py --budget-check
    plan-progress.py --stage-order-check [--stage N] [--plan <path>]
    plan-progress.py --dispatch-check <plan> [--since <ref>]

CODEX FORK. The core file is mostly a status-line renderer: it reads the host's
status-line JSON on stdin and draws one bar per plan in flight. Codex's status line
takes only predefined items and runs no command, so nothing on Codex can ever call that
renderer. This fork ships only the three gate checks the skill runs from a shell.

Every function and constant below except main() is copied byte-for-byte from the core
file; main() is the core's with its stdin entry paths replaced by the usage exit. What is
left out, by name: render() and render_json() and every function reachable only from
them (the bar, segment, colour, cache, discovery, grouping, lag and marker code); the
stdin entry paths of main(); and the core's bottom-of-file handler that exits 0 on any
crash, which exists so a status line never prints a traceback. Here an argument this
file does not implement prints a usage line and exits 64, so a caller that expected a
renderer learns at once that there is none, and each gate path keeps its own handler:
a gate that crashes must never read as a gate that passed.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Reuse the authoritative plan-parser pieces from the plugin's lib/ (loaded by
# file path, so this module's sys.path is untouched). The plan-status contract
# (what `[ ]` / `[x]` / `[~]` mean) is defined and argued once, at
# lib/plan_parser.py's STATUS_RE — read it there before changing anything here. This module classifies via pu.status_state() and
# never tests the captured character directly: a partial task counts toward
# the bar's denominator but never fills it.
_LIB = Path(__file__).resolve().parents[3] / "lib"
_PARSER = _LIB / "plan_parser.py"
_spec = importlib.util.spec_from_file_location("staged_planning_plan_parser", _PARSER)
pu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pu)

# pathlib raises ValueError -- NOT OSError -- for a path containing a NUL byte
# ("embedded null byte"). Every guard in this file that means "this path is
# unusable, degrade" therefore has to name both, and a bare `except OSError` is
# a hole wherever the path came from text rather than from a directory listing.
# Three sources feed such paths: the `cwd` in the statusline's stdin JSON, the
# `plan` field of the state file, and the `Master:` / `- **Plan:**` links read
# out of plan PROSE. One NUL in a sub-plan's backlink would blank the whole
# status line, pinned bar included, on every redraw.
#
# WHICH calls raise is not uniform, and guessing it wrong opens the hole. Measured on CPython 3.12: `stat()`, `resolve()` and `read_text()`
# RAISE, while `is_file()`, `is_dir()` and `exists()` SWALLOW it internally
# (pathlib classes a NUL path as non-encodable and returns False). The guards
# below therefore load-bear on the first group and are belt-and-braces on the
# second; test-plan-progress.py pins both halves, so a future pathlib that
# changes either one fails loudly rather than silently reopening this.
BAD_PATH = (OSError, ValueError)


def find_state(start):
    try:
        d = Path(start).resolve()
    except BAD_PATH:
        return None
    for p in [d, *d.parents]:
        try:
            f = p / ".claude" / "plan-progress.json"
            if f.is_file():
                return f
        except BAD_PATH:
            continue
    return None


def repo_root_of(state_file):
    """The repo root implied by a state file at <root>/.claude/plan-progress.json."""
    return state_file.parent.parent


def pinned_plan_path(state, state_file):
    """The absolute path of the plan a state file names.

    A relative `plan` is anchored to the REPO ROOT (.claude's parent), never to
    the process cwd — the statusline runs from wherever the user happens to be.
    This is a shared helper rather than inline code because two places must
    agree: if render() re-parsed `state["plan"]` itself and kept it relative,
    both discover_plans()'s exclusion and render()'s own post-filter would
    resolve it against the OS cwd. The pinned plan would then fail to match
    itself and render twice — once with its phase part, once as a discovered
    stranger — whenever a relative `plan` points inside the discovered plans
    directory, which is exactly the shape of the `docs/plans` fallback. It would
    also burn a MAX_BARS slot that a genuinely different plan should have.
    """
    plan = Path(state["plan"])
    if not plan.is_absolute():
        plan = state_file.parent.parent / plan
    return plan


STAGE_DEPS_RE = re.compile(r"^\*\*Depends on:\*\*\s*(.*)$")


_VD = None


def _stage_refs(value):
    """validate-dispatch.py's `stage_refs()`, loaded on first use.

    One parser for a stage's `Depends on:` value, not two: real plans write
    `Stages 1–3`, `Stages 2 and 3`, parentheticals and a `**Blocks:**` on the
    same line, and that function already reads all of them. Loaded lazily so a
    redraw with no stage in the state file never pays for it.
    """
    global _VD
    if _VD is None:
        path = Path(__file__).resolve().parents[2] / "planning-projects" / "scripts" / "validate-dispatch.py"
        spec = importlib.util.spec_from_file_location("validate_dispatch", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _VD = mod
    return _VD.stage_refs(value)


def unpassed_dependencies(text, stage):
    """Stage numbers `stage` depends on whose gate is not fully `[x]`.

    Without it a stage can close before the gate it depends on although it
    reads `Depends on: Stage 3 gate`: if nothing parses a stage-level
    `**Depends on:**`, the field is decoration.

    The dependency line is the one between `## Stage N` and its first `###`
    heading — a task's `- **Depends on:**` is a list item and never matches.
    A gate passes only when it has at least one check and every check is
    `[x]`: an open `[ ]` and a BLOCKED `[~]` both fail it, and a dependency
    with no gate checks at all is unproven, not passed.
    """
    deps, gates = set(), {}
    cur, in_head, gate = None, False, None
    for line in text.splitlines():
        m = pu.STAGEHDR_RE.match(line)
        if m and not line.startswith("###"):
            cur, in_head, gate = int(m.group(1)), True, None
            continue
        if line.startswith("#"):
            in_head = False
            g = pu.GATEHDR_RE.match(line)
            gate = int(g.group(1)) if g else None
            if gate is not None:
                gates.setdefault(gate, [])
            continue
        if in_head and cur == stage:
            d = STAGE_DEPS_RE.match(line.strip())
            if d:
                deps.update(_stage_refs(d.group(1)))
        if gate is not None:
            item = pu.GATE_ITEM_RE.match(line)
            if item:
                gates[gate].append(pu.gate_item_state(item.group(1)))
    deps.discard(stage)
    return sorted(n for n in deps
                  if not gates.get(n) or any(s != "done" for s in gates[n]))


def execution_module():
    spec = importlib.util.spec_from_file_location('execution_state',
              Path(__file__).resolve().with_name('plan_state.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def projection_state(state_file):
    """Legacy display is compatible; owned/versioned display must validate."""
    module = execution_module()
    try:
        owner = module.owner_of(repo_root_of(state_file))
    except Exception:
        owner = None  # compatible legacy display outside a registered Git run
    owned = False
    if owner is not None:
        try:
            owned = module.read_pointer(owner) is not None
        except Exception as exc:
            raise ValueError('state_error: invalid execution discovery metadata') from exc
    if owned:
        outcome = module.result(repo_root_of(state_file), 'show', {})
        if outcome['status'] != 'ok':
            raise ValueError('state_error: ' + outcome.get('message', outcome['status']))
        return outcome['state']
    # No run pointer: keep the legacy renderer's silence for unusable legacy
    # files. A parsed version marker still requires the shared owned reader.
    state = json.loads(state_file.read_text())
    if isinstance(state, dict) and 'schema_version' in state:
        outcome = module.result(repo_root_of(state_file), 'show', {})
        if outcome['status'] != 'ok':
            raise ValueError('state_error: ' + outcome.get('message', outcome['status']))
        return outcome['state']
    return state


def missing_projection_error(cwd):
    """A run pointer survives snapshot loss; no Git run remains ordinary idle."""
    try:
        probe = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode == 0:
            outcome = execution_module().result(probe.stdout.strip(), 'show', {})
            if outcome['status'] == 'state_error':
                return 'state_error: ' + outcome.get('message', 'invalid execution snapshot')
    except Exception:
        pass
    return None


def budget_check(cwd):
    """Read-only compatibility wrapper; plan-state owns reservation/accounting.

    Legacy positive counters are ambiguous, so require evidenced migration rather
    than diagnosing them as exhausted. Idle legacy projections stay readable.
    """
    sf = find_state(cwd)
    try:
        if sf is not None:
            state = projection_state(sf)
            if not isinstance(state, dict):
                raise ValueError('state is not an object')
            if 'schema_version' not in state:
                rnd = state.get('remediation_round')
                if rnd is None and 'remediation_round' not in state:
                    return 0  # labeled legacy compatibility, not mutation authority
                print('state_error: legacy round requires evidenced migration', file=sys.stderr)
                return 3
        module = execution_module()
        if sf is None:
            probe = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                                   capture_output=True, text=True, timeout=10)
            if probe.returncode != 0:
                return 0  # no_active_plan outside a Git run
        outcome = module.budget_result(cwd)
        if outcome['status'] not in ('ok', 'no_active_plan'):
            print(outcome['status'] + ': ' + outcome.get('message', ''), file=sys.stderr)
        return module.EXITS[outcome['status']]
    except Exception as exc:
        print('state_error: cannot read execution state (' + type(exc).__name__ + ')', file=sys.stderr)
        return 3


ROSTER_ITEM_RE = re.compile(r"^\s*- \[.\] .*Dispatch roster")


# Any list item ends the roster, not only a checkbox: a plain `- **Probe results:**`
# bullet after it that names another task would otherwise count as rostered.
ROSTER_END_RE = re.compile(r"^\s*(- |#)")


ROSTER_COUNT_RE = re.compile(r"\b(\d+)\s+of\s+\d+\s+tasks\b|\b(0)\s+tasks\b")


TASK_REF_RE = re.compile(r"\bTask\s+(\d+\.\d+)\b")


# A commit belongs to the task its subject OPENS with (`Stage 4 Task 4.1: …`).
# A task named later in the subject is a cross-reference, and counting it would
# let one task's `dispatched` trailer reconcile another it merely mentions.
COMMIT_TASK_RE = re.compile(r"^(?:Stage\s+\d+\s+)?Task\s+(\d+\.\d+)\b")


AUTHORISED_INLINE = "inline (user authorised)"


# The routing table's own inline route, `Executor: inline (routing table — no <stack>
# agent on this host)`: a routing outcome accepted at Preflight, not a deviation, so it
# reconciles, and is counted as its own term, never as dispatched. Inert on a host whose
# table always names an agent, so one script serves every host.
TABLE_ROUTED_INLINE = "inline (routing table"


def roster_body(text):
    """Preflight's `Dispatch roster` item as one line, or None.

    The item wraps across continuation lines, so it runs until the next
    list item (checkbox or not), a heading, or a blank line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not ROSTER_ITEM_RE.match(line):
            continue
        item = [line]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or ROSTER_END_RE.match(nxt):
                break
            item.append(nxt)
        return " ".join(item)
    return None


def parse_roster(text):
    """(count, [task ids]) from Preflight's `Dispatch roster` item, or None."""
    body = roster_body(text)
    if body is None:
        return None
    m = ROSTER_COUNT_RE.search(body)
    count = int(m.group(1) or m.group(2)) if m else None
    return count, list(dict.fromkeys(TASK_REF_RE.findall(body)))


# A roster entry routing a task inline by the table: `Task 4.2 → inline (routing table …`.
ROSTER_INLINE_RE = re.compile(r"\bTask\s+(\d+\.\d+)\s*(?:→|->)\s*`?inline \(routing table")


def dispatch_check(args):
    """Exit status for `--dispatch-check <plan> [--since <ref>]`: 0 when every
    rostered task is reconciled, 2 otherwise.

    Reconciling Preflight's roster by reading trailers and writing prose permits
    one failure: a rostered task run inline under a bare `Executor: inline`, and
    a close-out that reports the plan done. Reconciled means ANY of the task's commits carries a
    `dispatched …` trailer or the explicit `inline (user authorised)`; an empty
    trailer is `unknown`, never `inline`. Every failure path — unreadable plan,
    not a git repo, bad ref — is a FAIL: line and exit 2, never a silent 0.
    """
    def fail(msg):
        print(f"FAIL: {msg}", file=sys.stderr)
        return 2

    rest = args[args.index("--dispatch-check") + 1:]
    since = None
    if "--since" in rest:
        j = rest.index("--since")
        if j + 1 >= len(rest):
            return fail("--since needs a ref")
        since = rest[j + 1]
        del rest[j:j + 2]
        if since.startswith("-"):
            return fail(f"bad --since ref: {since}")
    if not rest:
        return fail("usage: plan-progress.py --dispatch-check <plan> [--since <ref>]")
    plan = rest[0]
    try:
        text = Path(plan).read_text()
    except BAD_PATH as e:
        return fail(f"cannot read plan {plan}: {e}")

    roster = parse_roster(text)
    if roster is None:
        return fail(f"roster missing — no `Dispatch roster` item in {plan}")
    count, ids = roster
    # A table-routed trailer reconciles only a task the roster itself routed inline:
    # the routing outcome is accepted at Preflight, never claimed afterwards.
    table_inline = set(ROSTER_INLINE_RE.findall(roster_body(text) or ""))
    if count is None:
        return fail("roster count unreadable — expected `<n> of <m> tasks` or `0 tasks`")
    if count == 0:
        print("dispatch: 0 of 0 rostered tasks dispatched")
        return 0
    if count != len(ids):
        return fail(f"roster says {count} tasks but lists {len(ids)} task ids")

    rng = f"{since}..HEAD" if since else "HEAD"
    try:
        r = subprocess.run(
            ["git", "log", "--format=%s%x1f%(trailers:key=Executor,valueonly,unfold)%x1e", rng],
            capture_output=True, text=True)
    except OSError as e:
        return fail(f"cannot run git: {e}")
    if r.returncode != 0:
        why = (r.stderr.strip().splitlines() or ["git log failed"])[0]
        return fail(f"git log {rng}: {why}")

    seen = {}  # task id -> list of Executor values across its commits
    for rec in r.stdout.split("\x1e"):
        if "\x1f" not in rec:
            continue
        subject, trailer = rec.split("\x1f", 1)
        values = [v.strip() for v in trailer.splitlines() if v.strip()] or ["unknown"]
        m = COMMIT_TASK_RE.match(subject.strip())
        if m:
            seen.setdefault(m.group(1), []).extend(values)

    dispatched = 0
    table_routed = 0
    unreconciled = []
    for tid in ids:
        values = seen.get(tid)
        if not values:
            unreconciled.append((tid, f"no commit in {rng}"))
            continue
        if any(v.startswith("dispatched") for v in values):
            dispatched += 1
        elif tid in table_inline and any(v.startswith(TABLE_ROUTED_INLINE) for v in values):
            table_routed += 1
        elif AUTHORISED_INLINE not in values:
            unreconciled.append(
                (tid, "Executor: " + ", ".join(dict.fromkeys(values))))
    for tid, why in unreconciled:
        print(f"FAIL: Task {tid} — rostered Dispatch: YES, not reconciled ({why})",
              file=sys.stderr)
    tail = f"; {table_routed} table-routed inline" if table_routed else ""
    print(f"dispatch: {dispatched} of {count} rostered tasks dispatched{tail}")
    return 2 if unreconciled else 0


def stage_order_check(cwd, args=()):
    """Exit status for `--stage-order-check [--stage N] [--plan <path>]`: 0 when the
    stage may open, 2 when a stage it depends on has a gate that is not fully `[x]`.

    Run at stage open, before the stage's first task — and so BEFORE the state file
    moves to it. `--stage N` names the stage being opened; without it the check reads
    the file's `stage`, which at that moment is the stage already running (so the check
    would pass a Stage 4 opened over an open Stage 3 gate). `--plan` names the plan when there is no state file to read it from.

    Without `--stage`, silent 0 where no stage is open — no state file, or no `stage`.
    With `--stage`, the caller asked about a specific stage, so a plan that cannot be
    found or read exits 2: an unreadable plan cannot prove the order holds.
    """
    args = list(args)

    def opt(name):
        if name not in args:
            return None
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else ""

    stage_arg, plan_arg = opt("--stage"), opt("--plan")
    state, sf = {}, find_state(cwd)
    if sf is None:
        error = missing_projection_error(cwd)
        if error:
            print(error, file=sys.stderr)
            return 3
    if sf is not None:
        try:
            state = projection_state(sf)
        except (OSError, ValueError) as e:
            print(f"FAIL: cannot read {sf}: {e}", file=sys.stderr)
            return 3 if 'state_error:' in str(e) else 2
        if not isinstance(state, dict):
            state = {}
    if stage_arg is not None:
        try:
            stage = int(stage_arg)
        except ValueError:
            print(f"FAIL: --stage takes a stage number (got {stage_arg!r})", file=sys.stderr)
            return 2
    else:
        stage = state.get("stage")
        if not isinstance(stage, int) or isinstance(stage, bool):
            return 0
    if plan_arg:
        plan = Path(plan_arg)
    elif state.get("plan") and sf is not None:
        plan = pinned_plan_path(state, sf)
    elif stage_arg is not None:
        print("FAIL: no plan to read — pass --plan or write the state file first",
              file=sys.stderr)
        return 2
    else:
        return 0
    try:
        text = plan.read_text(errors="ignore")
    except BAD_PATH as e:
        print(f"FAIL: cannot read plan {plan}: {e}", file=sys.stderr)
        return 2
    bad = unpassed_dependencies(text, stage)
    for n in bad:
        print(f"FAIL: Stage {stage} depends on Stage {n}, whose gate is not fully [x]",
              file=sys.stderr)
    return 2 if bad else 0


def main():
    if "--budget-check" in sys.argv[1:]:
        sys.exit(budget_check(os.getcwd()))
    if "--stage-order-check" in sys.argv[1:]:
        try:
            status = stage_order_check(os.getcwd(), sys.argv[1:])
        except Exception as e:
            print(f"FAIL: --stage-order-check crashed: {e!r}", file=sys.stderr)
            status = 2
        sys.exit(status)
    if "--dispatch-check" in sys.argv[1:]:
        # Its own handler: a gate that crashes must never read as a gate that passed.
        try:
            status = dispatch_check(sys.argv[1:])
        except Exception as e:
            print(f"FAIL: --dispatch-check crashed: {e!r}", file=sys.stderr)
            status = 2
        sys.exit(status)
    print("usage: plan-progress.py --budget-check | --stage-order-check [--stage N] "
          "[--plan <path>] | --dispatch-check <plan> [--since <ref>]", file=sys.stderr)
    print("This Codex build has no status-line renderer; see the module docstring.",
          file=sys.stderr)
    sys.exit(64)


if __name__ == "__main__":
    main()
