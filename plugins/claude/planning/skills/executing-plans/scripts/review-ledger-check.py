#!/usr/bin/env python3
"""review-ledger-check.py — a review a gate report claims was dispatched, was dispatched.

    review-ledger-check.py --plan P --stage N --repo R [--report F]
    review-ledger-check.py --unstopped --repo R

WHY THIS EXISTS. The gate report's review line (stage-gate.md § The gate report's
review line) names the agent that ran each review. On its own that line is a
self-report: a review the executor ran itself, or never ran, reads exactly like one a
fresh agent ran. hooks/dispatch-log.sh appends every Agent
dispatch, subagent start and stop of a plan run to <R>/.claude/dispatch-log.jsonl;
this script compares the two. The hook gathers, this script decides: a hook that also
judged would put the verdict where no test or reviewer reads it.

GATE MODE (--plan --stage). Reads Stage N's `review:` and `evaluator:` lines — from
--report F (a draft gate report; `-` is stdin) when given, else from the plan's
`## Stage N` section, where the handoff note carries them verbatim. Each line is one of:

  a dispatch claim   review: <label> <subagent_type> over <range> — <verdict>
                     evaluator: <subagent_type> in the <role> role … — <verdict>
  a substitution     SUBSTITUTED in the line's head — needs no dispatch (a
                     disclosed deviation, valid whatever the log says)
  a scope statement  a line naming no agent that says why no review ran — `not run`,
                     `not dispatched`, `not mandated`, an `opt-out`, a `trivial`
                     (`non-code`, `docs-only`, `config-only`, `comment-only`,
                     `version bump`) diff — in its head, or after a head saying it was
                     `skipped` ("review: Tier-2 not run — tier none", "review: Tier-2
                     skipped — docs-only diff"); a line stating a verdict (APPROVE, LGTM,
                     clean, `0 Critical`, PASS …) is never one
  a redesign line    review: round K: redesign — reviewed by <subagent_type> (a claim),
                     — battery <name> or — unread (scope, unless it states a verdict),
                     per gate-failure-procedure.md; read in any case, `round K` optional

The agent and SUBSTITUTED are read from the line's head — the text before the first
` — ` — so nothing written after the verdict can supply either. Prefixes are read in
any case and under list markers or bold. Any other line is ADVISORY (exit 4): "looked at
the diff, clean" may claim a review whatever words it uses, so the gate report names it.
It is advisory, not a failure, because a heuristic that blocks on a measured 0% true
rate fails honest work: measured 2026-10-06 over 258 review:/evaluator: lines in `Stage N green`
commit bodies of 13 of one owner's repos, with this classifier (the head-anchored reasons and the
verdict exclusion included): 134 hits, 0 true — every hit read was an honest review or
scope line in a wording older than this grammar. Only an unmatched dispatch claim
fails. Text may follow the range ("over a..b
(round 2): APPROVE"). The task field `Review: required` / `Review: skip` is not a ledger
line. A stage with no ledger line at all is NOT CHECKED (exit 3): a gate report
states every review, run or not.

Each claim needs its own `dispatch` line of that subagent_type whose description names
`Stage N` and the claim's role (the word review or pass, or evaluator) and names no `Task N.M`,
logged at or after the newest `Stage N-1 green` commit (for Stage 1, the log's start).
So the executor writes the dispatch description as `Stage N Tier-2 review` or
`Stage N gate evaluator`. Two claimed passes need two dispatches. A claim whose head names
`Task N.M` (a Tier-1 line, "review: Tier-1 <type> over the Task 2.1 diff — …") is that
task's: it takes a dispatch naming exactly that task and the role (`Stage 2 Task 2.1 quick
review`), N must be this gate's stage, and it never takes a stage pass's dispatch. Only
the first task a head names is read: write one Tier-1 line per task.
Measured 2026-10-08 over 298 review:/evaluator: lines in `Stage N green` commit bodies of
one owner's repos (repo count not recorded):
12 heads name a `Task N.M`; 5 of them name a dispatchable type before `over`, and all 5
are true per-task Tier-1 lines, so the Tier-1 reading stays on the blocking path. The other 7 classify like any other line.

WHAT THIS DOES NOT DO. It cannot tell whether the agent was briefed on the right diff,
or whether the verdict quoted is the one it returned — only that a dispatch of the
claimed type and role happened in the stage's window. The window rests on the newest
commit with the exact subject `Stage N-1 green`: a missing or reworded commit from this
plan lets an older plan's commit open it, and a log left behind by a plan whose
close-out never ran satisfies Stage 1 claims.

UNSTOPPED MODE (--unstopped). Lists every agent with a `start` line and no `stop`
line — an agent still running after the run that started it used its result.

EXIT CODES:
  0  every claim matched / no agent left running
  1  a claimed dispatch has no match, or an agent is still running (each named)
  2  usage error (no Stage N section, no `Stage N-1 green` commit, unreadable input,
     no git)
  3  NOT RUN — the dispatch log is missing — or NOT CHECKED — no review: or
     evaluator: line for the stage; never 0
  4  gate mode only: every claim matched, and a line names no agent and gives no
     reason (ADVISORY, each named); --unstopped uses only 0, 1 and 3
"""
import argparse
import datetime
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

LOG = Path(".claude") / "dispatch-log.jsonl"
_STALE = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"
# A line naming no agent is a scope statement only when it says why no review ran: the tier
# did not mandate it, an evidenced opt-out, or a trivial diff (stage-gate.md § The gate
# report's review line), in the words review-scope.md § Review opt-out uses for them:
# docs-only, config-only, pure version bumps, comment-only, non-code. Anything else naming no
# agent is ADVISORY — "looked at it, clean" may claim a review, whatever words it uses — and
# the gate report names it (measured trigger rate in the module docstring).
SCOPE_REASON = re.compile(r"\bnot run\b|\bnot dispatched\b|\bnot mandated\b|\bmandates? none\b|"
                          r"\bopt-?out\b|"
                          r"\bopted[- ]out\b|\btrivial\b|\bnon-code\b|"
                          r"\b(?:docs|config|comment)-only\b|\bversion bump\b", re.I)
TYPE = r"(?P<type>[A-Za-z][\w.-]*(?::[\w.-]+)?)"
# Matched against the line's HEAD only — the text before the first ` — ` — so nothing
# written after the verdict ("… carried over to the backlog") can be read as the agent.
REVIEW_CLAIM = re.compile(rf"^review:\s+(?:[^—]*?[\s(])?{TYPE}\s+over\s+\S")
EVALUATOR_CLAIM = re.compile(rf"^evaluator:\s+{TYPE}\s+in\s+the\s")
VERDICT_SEP = re.compile(r"\s+(?:—|--)\s+")
# gate-failure-procedure.md § A redesign the gate closes on prescribes three lines whose head
# names no agent: `round K: redesign — reviewed by <subagent_type>` (a dispatch claim),
# `— battery <name>` and `— unread` (scope: no dispatch was owed or made).
# Read in any case, with or without `round K`, its colon, or backticks around the type, and
# after an em dash, en dash or `--`: a claim in another spelling must not fall to advisory.
REDESIGN = re.compile(rf"^review:\s+(?:round\s+\d+:?\s+)?redesign\s*:?\s+(?:—|–|--)\s+"
                      rf"(?:reviewed\s+by\s+`?{TYPE}`?|battery\s+\S|unread\b)", re.I)
# A skip verb in the head lets the reason follow the dash ("Tier-2 skipped — docs-only diff").
SKIPPED = re.compile(r"\b(?:auto-)?skipped\b", re.I)
# A line that states a verdict reports a review; it is never a scope line.
VERDICT = re.compile(r"\bAPPROVE\b|\bLGTM\b|\bREQUEST CHANGES\b|\bBLOCK\b|"
                     r"\b\d+\s+Critical\b|\bclean\b|\bPASS\b|\bFAIL\b", re.I)
LEDGER_PREFIX = re.compile(r"^(review|evaluator)\s*:", re.I)
# The task field `Review: required` / `Review: skip` (task-fields.md) shares the prefix and is
# never a ledger line.
TASK_FIELD = re.compile(r"^review:\s*(required|skip)\b", re.I)
LIST_MARKER = re.compile(r"^(?:[-*+>]|\d+[.)])\s+")
# A dispatch counts toward a stage's claim only when its description names that stage and
# the claim's role; one naming a task (`Task 2.1`) is per-task work, never the stage's pass.
ROLE = {"review": re.compile(r"\breview|\bpass\b", re.I),
        "evaluator": re.compile(r"evaluat", re.I)}
TASK_REF = re.compile(r"\bTask\s+\d+\.\d+\b", re.I)
TASK_ID = re.compile(r"\bTask\s+(\d+)\.(\d+)\b", re.I)


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass


class Usage(Exception):
    pass


def ts(s):
    t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def read_log(repo):
    """The log's rows, or None when there is no log. A row that is not JSON is skipped."""
    path = Path(repo) / LOG
    if not path.is_file():
        return None
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event"):
            rows.append(row)
    return rows


def stage_section(plan_text, stage):
    m = re.search(rf"^## Stage {stage}\b.*$", plan_text, re.M)
    if not m:
        raise Usage(f"no `## Stage {stage}` section in the plan")
    nxt = re.search(r"^## ", plan_text[m.end():], re.M)
    return plan_text[m.end(): m.end() + nxt.start()] if nxt else plan_text[m.end():]


def ledger_lines(text):
    """Every review:/evaluator: line, whatever its case, list marker or emphasis, normalised
    to a lowercase prefix with the markup removed."""
    out = []
    for raw in text.splitlines():
        line = LIST_MARKER.sub("", raw.strip()).replace("**", "").strip().strip("`").strip()
        m = LEDGER_PREFIX.match(line)
        if m and not TASK_FIELD.match(line):
            out.append(m.group(1).lower() + ":" + line[m.end():])
    return out


def classify(line):
    """('claim', role, type) | ('substituted', …) | ('scope', …) | ('unnamed', …)."""
    head = VERDICT_SEP.split(line, maxsplit=1)[0]
    role = "evaluator" if line.startswith("evaluator:") else "review"
    if "SUBSTITUTED" in head:
        return "substituted", role, None
    r = REDESIGN.match(line)
    if r and r.group("type"):
        return "claim", role, r.group("type")
    if r:
        return ("unnamed" if VERDICT.search(line) else "scope"), role, None
    m = REVIEW_CLAIM.match(head) or EVALUATOR_CLAIM.match(head)
    if m:
        return "claim", role, m.group("type")
    # The reason is read from the head, or after a head saying the review was skipped — never
    # from verdict prose ("APPROVE, docs-only change" names no reason a review did not run).
    reason = SCOPE_REASON.search(head) or (SKIPPED.search(head) and SCOPE_REASON.search(line))
    return ("scope" if reason and not VERDICT.search(line) else "unnamed"), role, None


def counts_for(row, stage, role, task=None):
    """A stage claim takes a dispatch naming `Stage N` and the role and no task. A per-task
    (Tier-1) claim, `task` = (N, M), takes one naming that `Task N.M` and the role: the
    task's own number carries its stage, so N must be this gate's."""
    d = row.get("description") or ""
    if ROLE[role].search(d) is None:
        return False
    if task is not None:
        named = [(int(a), int(b)) for a, b in TASK_ID.findall(d)]
        return task[0] == stage and named == [task]
    return (re.search(rf"\bStage\s+{stage}\b", d, re.I) is not None
            and not TASK_REF.search(d))


def previous_green(repo, stage):
    """Committer time of the newest `Stage <stage-1> green` commit, or None for Stage 1."""
    if stage <= 1:
        return None
    subject = f"Stage {stage - 1} green"
    try:
        r = subprocess.run(["git", "-C", str(repo), "log", "--format=%cI%x09%s", "HEAD"],
                           capture_output=True, text=True)
    except OSError as e:
        raise Usage(f"cannot run git: {e}")
    if r.returncode != 0:
        raise Usage(f"git log failed in {repo}: {r.stderr.strip()}")
    for row in r.stdout.splitlines():
        when, _, subj = row.partition("\t")
        if subj.strip() == subject:
            return ts(when)
    raise Usage(f"no `{subject}` commit on HEAD in {repo} — the window for Stage {stage}'s "
                "dispatches starts there, so nothing can be matched without it")


def gate(args):
    if args.report:
        try:
            text = (sys.stdin.read() if args.report == "-"
                    else Path(args.report).read_text(errors="replace"))
        except OSError as e:
            raise Usage(f"cannot read --report {args.report}: {e}")
    else:
        try:
            text = stage_section(Path(args.plan).read_text(errors="replace"), args.stage)
        except OSError as e:
            raise Usage(f"cannot read plan {args.plan}: {e}")
    lines = ledger_lines(text)
    since = previous_green(args.repo, args.stage)
    try:
        rows = read_log(args.repo)
    except OSError as e:
        raise Usage(f"cannot read the dispatch log: {e}")
    if rows is None:
        print(f"NOT RUN — no dispatch log at {Path(args.repo) / LOG}; no claimed review was "
              "checked. The hook (hooks/dispatch-log.sh) writes it only while "
              ".claude/plan-progress.json exists.")
        return 3
    if not lines:
        print(f"NOT CHECKED — no review: or evaluator: line for Stage {args.stage} "
              f"({'--report' if args.report else 'the plan section'}). A gate states every "
              "review, run or not; pass the draft report with --report.")
        return 3
    pool = []
    for r in rows:
        if r.get("event") != "dispatch":
            continue
        try:
            when = ts(r.get("ts"))
        except (TypeError, ValueError):
            continue
        if since is None or when >= since:
            pool.append(r)
    bad, advisory = [], []
    for line in lines:
        kind, role, stype = classify(line)
        if kind == "claim":
            # A claim whose head names `Task N.M` is that task's Tier-1 review.
            t = TASK_ID.search(VERDICT_SEP.split(line, maxsplit=1)[0])
            task = (int(t.group(1)), int(t.group(2))) if t else None
            hit = next((r for r in pool if r.get("subagent_type") == stype
                        and counts_for(r, args.stage, role, task)), None)
            if hit is not None:
                pool.remove(hit)
                print(f"  matched      {stype} ({hit.get('description')}): {line[:90]}")
            else:
                whom = (f"Task {task[0]}.{task[1]}" if task is not None
                        else f"Stage {args.stage}")
                bad.append(f"no `{stype}` dispatch whose description names {whom} "
                           f"and the {role} role, logged since "
                           f"{'the log start' if since is None else since.isoformat()}: {line}")
        elif kind == "unnamed":
            advisory.append(f"names no dispatched agent as `<subagent_type> over <range>` "
                            f"before its first ` — `, and gives no reason a review did not "
                            f"run (not run, not dispatched, not mandated, opt-out, a trivial "
                            f"or non-code diff) outside verdict prose: {line}")
        else:
            print(f"  {kind:<12} {line[:100]}")
    for b in bad:
        print(f"  UNMATCHED    {b}")
    for a in advisory:
        print(f"  ADVISORY     {a}")
    return 1 if bad else 4 if advisory else 0


def unstopped(args):
    try:
        rows = read_log(args.repo)
    except OSError as e:
        raise Usage(f"cannot read the dispatch log: {e}")
    if rows is None:
        print(f"NOT RUN — no dispatch log at {Path(args.repo) / LOG}")
        return 3
    started, stopped = {}, set()
    for r in rows:
        aid = r.get("agent_id")
        if r.get("event") == "start" and aid:
            started.setdefault(aid, r)
        elif r.get("event") == "stop" and aid:
            stopped.add(aid)
    running = [r for aid, r in started.items() if aid not in stopped]
    for r in running:
        print(f"  RUNNING  {r.get('agent_id')} ({r.get('agent_type')}), started {r.get('ts')}")
    print(f"{len(running)} agent(s) started and never stopped")
    return 1 if running else 0


def main(argv=None):
    _warn_if_stale()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--plan")
    ap.add_argument("--stage", type=int)
    ap.add_argument("--report")
    ap.add_argument("--unstopped", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.unstopped:
            return unstopped(args)
        if not args.plan or args.stage is None:
            raise Usage("--plan and --stage are required (or --unstopped)")
        return gate(args)
    except Usage as e:
        print(f"review-ledger-check: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
