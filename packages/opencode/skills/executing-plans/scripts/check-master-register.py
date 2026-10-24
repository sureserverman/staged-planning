#!/usr/bin/env python3
"""A master's register and its sub-plans agree — in both directions.

RUN AT THE MASTER CLOSE-OUT, which is its position and not a repo validator.
It lives here rather than in `scripts/` deliberately: its corpus is a records home's plans,
which may sit outside the repo, so as a `check-*.py` in the repo's validator set it would
make a repo's build red or green according to plans it does not hold. A repo's CI may not depend on
another project's plan hygiene. `master-plans.md` step 5 is what invokes it.

WHY THIS EXISTS. `master-plans.md` step 3 flips a register entry to `[x]` once the
sub-plan carries a terminal marker, and step 5 forbids the master's own
`**Completed:**` line while any `[x]` entry's sub-plan is unclosed or carries an
unaccepted `[~]` gate. Both are rules a reader follows; without a checker neither is
checkable, and the register is the half that gets edited under pressure. Measured over
one owner's plans (undated): 7 sub-plans carried a register `[x]` with no terminal
marker of their own, 2 of them over sub-plans with zero tasks executed. A point-in-time
measurement, not a live invariant; the run's output is current.

The mirror direction (a finished sub-plan whose register entry never flipped) needs
this checker for a structural reason: the flip happens at a sub-plan close-out, outside any task transition, so
`status_lag`'s state-file comparison structurally cannot see it. A master can sit
with a finished sub-plan and an unflipped register indefinitely.

THE CONTRACT LIVES IN ONE PLACE. Every regex and predicate here comes from
the plugin's `lib/plan_parser.py` via importlib — STATUS_RE, SUBPLAN_RE, SUBPLAN_LINK_RE,
COMPLETED_RE, ABANDONED_RE, link_target, status_state, is_master_plan and
plan_blocked. This file defines none of them. If you find yourself about to write
one here, add it there and import it: two definitions of "closed" let two
consumers disagree about the same plan, each passing its own check.

WHAT THIS GUARD CANNOT SCREEN, disclosed because a guard that hides its blind spots
reads as covering them:

  - A register entry whose `- **Plan:**` link does not resolve is skipped, not
    reported. A broken link is a different defect with a different owner, and a
    checker that fails on one would fail on every master mid-authoring.
  - A sub-plan carrying `**Blocked-accepted:**` with no `[~]` gate anywhere has both
    blocked kinds permanently suppressed, because `plan_blocked()` checks acceptance
    first and short-circuits. That is the contract predicate's behaviour, not this
    checker's, and changing it here would be a second definition of "blocked".
  - It reads only the plans directories it is given (each recursively), or with none
    the project's records home `plans/` as `lib/records_home.py` resolves it. A plan
    outside those directories is not seen.
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LIB = _HERE.parents[2] / "lib"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _LIB / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pu = _load("staged_planning_plan_parser", "plan_parser.py")

# The staleness probe lives in the plugin's lib/, not beside this file, so a bare
# `import staleness` resolves against sys.path[0] — this script's own directory — and
# raises. Guarded, that failure is silent, and the probe would pass a grep while warning
# nobody. Loaded by explicit path for the same reason `pu` is.
_STALE = _LIB / "staleness.py"


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:
        pass          # a probe that cannot load must never stop the command it advises on

# The marker is recognised only at column 0. An indented one is the shape an
# author writes when tying it to the gate box it accepts, and it parses as absent.
# The one pattern with no owner upstream: the contract anchors the marker at column 0,
# so "the same marker, indented" has no representation there to import.
INDENTED_ACCEPT = re.compile(r"^[ \t]+\*\*Blocked-accepted:\*\*", re.M)


def terminal_marker(text):
    """Which terminal marker a plan carries, or None. Contract predicates only."""
    if pu.ABANDONED_RE.search(text):
        return "abandoned"
    if pu.COMPLETED_RE.search(text):
        return "completed"
    return None


def register_entries(master_text, master_path):
    """([(subplan_path, status_char, entry_line)], [unparsable Status lines]) for one master.

    The register walk: a `### Sub-plan N`
    heading opens an entry, a `- **Status:**` line records its state, and a
    `- **Plan:**` line names the file.
    """
    out, unparsed, status_line = [], [], None
    for line in master_text.splitlines():
        if pu.SUBPLAN_RE.match(line):
            status_line = None
            continue
        sm = pu.STATUS_RE.match(line)
        if sm:
            status_line = line
            continue
        anym = pu.ANY_STATUS_RE.match(line)
        if anym and not sm:
            # Out-of-contract Status: in the Status POSITION but outside the contract's `[ xX~]` class. The
            # entry is dropped by the walk below, so both directions go unchecked for it
            # silently — the failure this reports rather than skips.
            unparsed.append(line.strip()[:90])
            status_line = None
            continue
        if pu.SUBPLAN_LINK_RE.match(line) and status_line is None:
            # Status-less entry: a `- **Plan:**` with no Status before it — the entry is dropped by the
            # walk, so BOTH directions go unchecked for it. Same defect as an
            # out-of-contract Status, different axis.
            unparsed.append(f"Plan line with no preceding Status: {line.strip()[:70]}")
            continue
        lm = pu.SUBPLAN_LINK_RE.match(line)
        if lm and status_line is not None:
            target = pu.link_target(lm.group(1))
            if target:
                try:
                    out.append(((master_path.parent / target).resolve(),
                                pu.STATUS_RE.match(status_line).group(1),
                                status_line.strip()))
                except (OSError, ValueError):
                    pass
            status_line = None
    return out, unparsed


def master_gate_blocked(master_text):
    """Blocked master gate: a `[~]` in the master's own `**Gate:**` blocks.

    `plan_has_blocked_gate()` keys on `### Stage N Gate` headings, which a master does
    not have — its cross-plan checks live under `**Gate:**` markers on each register
    entry. Those are the checks that prove integration BETWEEN sub-plans, so a blocked
    one is a class member, not a predicate limit.
    """
    out, in_gate = [], False
    for line in master_text.splitlines():
        if line.strip().startswith("**Gate:**"):
            in_gate = True
            continue
        if in_gate:
            gi = pu.GATE_ITEM_RE.match(line)
            if gi and gi.group(1) == "~":
                out.append(line.strip()[:90])
            elif line.strip() and not gi:
                in_gate = False
    return out


ALLOW_PATH = Path(__file__).resolve().parent / "master-register-allow.txt"


def load_allowlist(path=None):
    """`<KIND> <sub-plan filename> — <reason>` per line; blanks and `#` ignored.

    Why an allowlist and not a new marker in the plan. A sub-plan can be closed
    DELIBERATELY partial — the master's close-out names it partial, with one item
    done and one still open, and honestly leaves that register entry `[ ]`.
    MASTER-OVER-UNFINISHED fires on it and cannot be cleared except by flipping an
    entry that is correctly `[ ]`. Without an allowlist the checker punishes the
    disclosure.

    The two alternatives both cost more. A new register state is another marker
    dialect, and the contract has decided to stop adding those —
    see `lib/plan_parser.py` § contract_warnings for that reasoning. Keying off
    the master's close-out prose ("names this sub-plan partial") makes free text
    load-bearing, which is fragile parsing.

    An allowlist adds no dialect, and the shape is already proven here:
    `scripts/extraction-integrity-allow.txt` runs exactly this way. The cost is
    real and worth naming — the acceptance lives beside the checker rather than
    in the plan, so a reader of the plan alone does not see it. The reason field
    is mandatory to blunt that: an entry has to say why, in the file a reviewer
    reads when counting how many exceptions exist.
    """
    p = Path(path) if path else ALLOW_PATH
    out = {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, _, reason = line.partition("—")
        parts = head.split()
        if len(parts) < 2 or not reason.strip():
            # A malformed entry must not silently suppress nothing OR everything.
            continue
        out[(parts[0], " ".join(parts[1:]).strip())] = reason.strip()
    return out


def audit(dirs, allowlist=None):
    findings, seen = [], set()
    allowed = load_allowlist(allowlist) if not isinstance(allowlist, dict) else allowlist

    def add(kind, sub, master, detail):
        key = (kind, str(sub), str(master), detail)
        if key in seen:                       # dedup: one defect, one finding
            return
        seen.add(key)
        if (kind, Path(sub).name) in allowed:
            return                            # accepted, with a reason on file
        findings.append(dict(kind=kind, path=str(sub), master=str(master), detail=detail))

    for d in sorted({Path(x).resolve() for x in ([dirs] if isinstance(dirs, (str, Path)) else dirs)}):
        masters = []
        for master in sorted(d.rglob("*.md")):
            if ".audit-backups" in master.parts:
                continue
            try:
                mtext = master.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                if not pu.is_master_plan(mtext, master):
                    continue
            except Exception:
                continue
            masters.append((master, mtext))

        for master, mtext in masters:
            if pu.ABANDONED_RE.search(mtext):
                # An abandoned master's register is a historical record, not a live
                # contract: the decomposition is over, so demanding its entries flip
                # reports a red nobody can legitimately clear — the same failure as a
                # master gate `[~]` with no acceptance: a master abandoned as superseded
                # or as a dead end otherwise reports every unflipped sub-plan forever.
                continue
            master_closed = bool(pu.COMPLETED_RE.search(mtext))
            entries, unparsed = register_entries(mtext, master)
            # Live before close-out: not gated on `master_closed` — step 5 runs the check
            # BEFORE the Completed line exists. A master whose every listed entry is [x]
            # IS at close-out, which is decidable now, so the kind is live there too.
            at_closeout = bool(entries) and all(
                pu.status_state(st) == "done" for _, st, _ in entries)
            # A master's own `[~]` is acceptable on exactly the terms a sub-plan's is:
            # `plan_blocked()` checks `**Blocked-accepted:**` first and short-circuits, and
            # without the same check here a master that performed the prescribed act would
            # still fire — a red clearable only by falsifying the `[~]`, which is the failure
            # this check exists to forbid.
            master_accepted = pu.blocked_acceptance(mtext)
            for blocked_line in master_gate_blocked(mtext):
                if master_accepted:
                    continue
                if master_closed or at_closeout:
                    add("MASTER-GATE-BLOCKED", master, master,
                        f"master's own `[~]` register gate check is unrun while the "
                        f"decomposition is at close-out: {blocked_line}")
            for raw in unparsed:              # out-of-contract Status
                add("ENTRY-UNPARSED", master, master,
                    f"register entry's Status is outside the contract's `[ xX~]`, so the "
                    f"entry is unreadable and BOTH directions go unchecked for it: {raw!r}")

            listed = set()
            for sub, state, entry in entries:
                if not sub.exists():
                    continue                  # disclosed: a dead link is a different defect
                listed.add(sub.resolve())
                stext = sub.read_text(encoding="utf-8", errors="replace")
                marker = terminal_marker(stext)
                done = pu.status_state(state) == "done"
                blocked, why = pu.plan_blocked(stext, sub)

                if done and marker is None:
                    add("REGISTER-AHEAD", sub, master,
                        "register marks this sub-plan [x] but the sub-plan carries no "
                        "terminal marker — the flip outran its close-out")

                # Close-out order: step 5 runs BEFORE the master's Completed line, so this
                # may not depend on master_closed or it is inert at the one gate that
                # could prevent the defect.
                if done and blocked and marker != "abandoned":
                    add("REGISTER-AHEAD-UNACCEPTED", sub, master,
                        f"register marks this sub-plan [x] but its completion was never "
                        f"proven and no acceptance stands: {why}")

                # Terminal-marker sync: both directions, for EITHER terminal marker. An abandoned sub-plan
                # whose entry never flipped deadlocks the master silently.
                if marker is not None and not done:
                    add("REGISTER-BEHIND", sub, master,
                        f"sub-plan carries a terminal marker ({marker}) but its register "
                        f"entry reads {entry!r} — a flip missed at close-out, invisible to status_lag")

                if master_closed and blocked and marker != "abandoned":
                    add("MASTER-OVER-BLOCKED", sub, master,
                        f"master carries **Completed:** over this sub-plan: {why}")

                # Every entry [x]: step 5's FIRST clause.
                if master_closed and not done:
                    add("MASTER-OVER-UNFINISHED", sub, master,
                        f"master carries **Completed:** while this entry still reads "
                        f"{entry!r} — the decomposition was declared done over it")

                if master_closed and marker == "abandoned":
                    add("MASTER-CLOSED-OVER-ABANDONED", sub, master,
                        "master's **Completed:** enumerates this sub-plan, which is "
                        "**Abandoned:** — the register cannot tell the two apart, so the "
                        "close-out list must not read as though the work was done")

                if INDENTED_ACCEPT.search(stext):
                    add("ACCEPTANCE-UNPARSED", sub, master,
                        "**Blocked-accepted:** is indented, so it parses as absent "
                        "— move it to column 0")

            # Membership: a sub-plan backlinking this master with no entry
            # in its register is the dangerous half — the master closes with every
            # LISTED entry [x] while a real sub-plan is unfinished.
            for cand in sorted(d.rglob("*.md")):
                if ".audit-backups" in cand.parts or cand.resolve() in listed:
                    continue
                if pu.is_not_a_plan(cand):
                    # Same predicate the classifier uses, from the same owner. Two
                    # scripts reading one corpus while disagreeing about what counts as
                    # a plan is the drift the one-owner rule exists to prevent.
                    continue
                try:
                    ctext = cand.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                bl = pu.MASTER_BACKLINK_RE.search(ctext)
                if not bl:
                    continue
                target = pu.link_target(bl.group(1))
                try:
                    same = target and (cand.parent / target).resolve() == master.resolve()
                except (OSError, ValueError):
                    same = False
                if same:
                    add("SUBPLAN-UNREGISTERED", cand, master,
                        "sub-plan backlinks this master but has no register entry in it — "
                        "the master can close with every listed entry [x] while this one "
                        "is unfinished")
    return findings


def main():
    _warn_if_stale()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("dirs", nargs="*",
                    help="plans directories to audit, each recursively (default: the "
                         "project's records home plans/)")
    ap.add_argument("--project", help="the project whose records home to audit when no "
                                      "directory is given (default: the git top level)")
    ap.add_argument("--allowlist", help="override the acceptance file")
    ap.add_argument("--list-allowlisted", action="store_true",
                    help="print accepted findings and their reasons, then exit")
    args = ap.parse_args()
    if args.list_allowlisted:
        for (kind, name), reason in sorted(load_allowlist(args.allowlist).items()):
            print(f"{kind}  {name}\n    {reason}")
        return 0
    dirs = args.dirs
    missing = [d for d in dirs if not Path(d).is_dir()]
    if missing:
        print(f"check-master-register: not a directory: {', '.join(missing)}", file=sys.stderr)
        return 2
    if not dirs:
        import subprocess
        project = args.project or subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
        if not project:
            print("check-master-register: not in a git repo; give a plans directory or --project",
                  file=sys.stderr)
            return 2
        code, home, msg = _load("staged_planning_records_home", "records_home.py").resolve(
            str(Path(project).resolve()))
        if code == 2:
            print(f"check-master-register: {msg}", file=sys.stderr)
            return 2
        plans = Path(home) / "plans"
        if not plans.is_dir():
            # Exit 2, never 0: a master close-out that audited nothing must not go green.
            print(f"check-master-register: no plans/ directory in the records home ({home}); "
                  f"there is nothing to audit, so the check cannot pass", file=sys.stderr)
            return 2
        dirs = [str(plans)]
    scanned = ", ".join(dirs)
    findings = audit(dirs, args.allowlist)
    if args.json:
        print(json.dumps({"findings": findings}, indent=2, sort_keys=True))
    else:
        for f in findings:
            print(f"  {f['kind']}  {f['path']}\n      {f['detail']}")
        n_allowed = len(load_allowlist(args.allowlist))
        print(f"Scanned {scanned}; {len(findings)} finding(s), "
              f"{n_allowed} accepted on file.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
