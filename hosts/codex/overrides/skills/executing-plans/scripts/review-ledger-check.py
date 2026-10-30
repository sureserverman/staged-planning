#!/usr/bin/env python3
"""review-ledger-check.py — a review a gate report claims was dispatched, was dispatched.

    review-ledger-check.py --plan P --stage N --repo R [--report F]
    review-ledger-check.py --unstopped --repo R

WHY THIS EXISTS. The gate report's review line (stage-gate.md § The gate report's
review line) names the agent that ran each review. On its own that line is a
self-report: a review the executor ran itself, or never ran, reads exactly like one a
fresh agent ran. hooks/dispatch-log.sh appends every subagent start and stop of a plan
run to <R>/.claude/dispatch-log.jsonl; this script compares the two. The hook gathers,
this script decides: a hook that also judged would put the verdict where no test or
reviewer reads it.

CODEX FORK. Codex's hooks see a spawned agent only at SubagentStart and SubagentStop,
and those payloads carry the agent's role (`agent_type`) and id, never a description of
the work. So the Codex log has `start` and `stop` rows and no `dispatch` row, and gate
mode matches each claim against a `start` row of the claimed role instead. So a claim
must name an installed `planning:<agent>` role: an untyped (`default`) agent cannot be
told from any other untyped spawn, such as Preflight's probe, so it never matches. Each
agent id counts once, and with no description to tell a stage's pass from a task's, the
time does it: a claim naming `Task N.M` (Tier-1) matches a start before the stage's last
task commit, any other claim one after it. What that cannot check, and the core can:
that the agent was briefed for this stage and this role. Everything else is the core's.

GATE MODE (--plan --stage). Reads Stage N's `review:` and `evaluator:` lines — from
--report F (a draft gate report; `-` is stdin) when given, else from the plan's
`## Stage N` section, where the handoff note carries them verbatim. Each line is one of:

  a dispatch claim   review: <label> <agent> over <range> — <verdict>
                     evaluator: <agent> in the <role> role … — <verdict>
  a substitution     SUBSTITUTED in the line's head — needs no dispatch (a
                     disclosed deviation, valid whatever the log says)
  a scope statement  a line naming no agent that says why no review ran — `not run`,
                     `not dispatched`, `not mandated`, an `opt-out`, a `trivial`
                     (`non-code`, `docs-only`, `config-only`, `comment-only`,
                     `version bump`) diff — in its head, or after a head saying it was
                     `skipped` ("review: Tier-2 not run — tier none", "review: Tier-2
                     skipped — docs-only diff"); a line stating a verdict (APPROVE, LGTM,
                     clean, `0 Critical`, PASS …) is never one
  a redesign line    review: round K: redesign — reviewed by <agent> (a claim),
                     — battery <name> or — unread (scope, unless it states a verdict),
                     per gate-failure-procedure.md; read in any case, `round K` optional
  a goal-command skip  evaluator: skipped — goal command `<cmd>` at <sha>
                     (stage-gate.md § Skipped when a recorded command decides the goal):
                     valid only when the plan does not declare `high`, Stage N's gate has
                     a ticked `(goal)` box whose code span is <cmd> and no `(judgment)`
                     line, <sha> is a commit HEAD holds, and no file but the plan and
                     proof/ changed from <sha> to the commit the stage ends on (its
                     `Stage N green`, else HEAD). Otherwise it fails (exit 1),
                     named, like an unmatched claim. Any other evaluator line saying
                     `skipped` fails the same way, whatever excuse it gives: a skip names
                     its goal command or quotes the owner
  an evaluator scope line where the evaluator is mandated (above `none`, a gate with a
                     `(judgment)` line or a stage with Outcomes; always at `high`) fails
                     unless it quotes the owner (`owner, <date>: "<words>"`): an excuse word
                     does not excuse a mandated evaluator. There, so does an evaluator line
                     stating neither an agent, a reason nor a verdict (`n/a`, `waived`), and a
                     report with no evaluator line at all. A `(judgment)` line that is a
                     decisions- or architecture-conformance check does not count: the executor
                     reads it, so it mandates no evaluator (review-scope.md)

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

Each claim needs its own `start` line of that agent's role, logged at or after the newest
`Stage N-1 green` commit (for Stage 1, the log's start), of the installed `planning:<agent>`
role the claim names (the claim may drop the prefix; the log row may not). A claim naming an
untyped agent never matches. Each agent id counts once, so two claimed passes need two
agents. A claim whose head names `Task N.M` (a Tier-1 line, "review: Tier-1 <agent> over
the Task 2.1 diff — …") must name a task of this gate's stage; it takes a start like any
other claim, because a Codex start carries no task to tell it from the stage's pass. Only
the first task a head names is read: write one Tier-1 line per task.
Measured 2026-10-08 over 298 review:/evaluator: lines in `Stage N green` commit bodies of
one owner's repos (repo count not recorded):
12 heads name a `Task N.M`; 5 of them name a dispatchable type before `over`, and all 5
are true per-task Tier-1 lines, so the Tier-1 reading stays on the blocking path. The other 7 classify like any other line.

WHAT THIS DOES NOT DO. It cannot tell whether the agent was briefed on the right diff,
or whether the verdict quoted is the one it returned — only that an agent of the claimed
role started in the stage's window. The window rests on the newest
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
  3  NOT RUN — the dispatch log is missing and a line claims a dispatch — or NOT
     CHECKED — no review: or evaluator: line for the stage; never 0. The evaluator's
     skip and mandate checks read the plan and git, so they run with no log, and
     their failures exit 1
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
# names no agent: `round K: redesign — reviewed by <agent>` (a dispatch claim),
# `— battery <name>` and `— unread` (scope: no dispatch was owed or made).
# Read in any case, with or without `round K`, its colon, or backticks around the type, and
# after an em dash, en dash or `--`: a claim in another spelling must not fall to advisory.
REDESIGN = re.compile(rf"^review:\s+(?:round\s+\d+:?\s+)?redesign\s*:?\s+(?:—|–|--)\s+"
                      rf"(?:reviewed\s+by\s+`?{TYPE}`?|battery\s+\S|unread\b)", re.I)
# stage-gate.md § Skipped when a recorded command decides the goal: the gate evaluator skipped
# because the gate's ticked `(goal)` check is a command the executor ran green. GOAL_SKIP_ANY
# catches the intent in any shape, so a malformed line fails rather than falling to advisory.
GOAL_SKIP = re.compile(r"^evaluator:\s+skipped\s+(?:—|–|--)\s+goal\s+command\s+`(?P<cmd>[^`]+)`"
                       r"\s+at\s+(?P<sha>[0-9a-f]{7,40})\b", re.I)
GOAL_SKIP_ANY = re.compile(r"^evaluator:\s+skipped\b.*\bgoal\s+command\b", re.I)
# The audit's own readings (plan-flip-audit.py GATE_HEAD, BULLET_BOX / LABELED_BOX,
# DECLARED_TIER), so the two never disagree on which gate, which box, which tier.
GATE_HEAD = re.compile(r"^\s*(?P<hashes>#{1,5})\s+Stage\s+(\d+)(?:[-\s][A-Za-z]+)?\s*[:.\-—–]?\s*Gate\b",
                       re.I)
HEADING = re.compile(r"^\s*(#{1,6})\s")
BOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*(?:\*\*[^*]+\*\*:?\s*)?\[(?P<mark>[ xX~])\]\s*(?P<text>.*)$")
DECLARED_TIER = re.compile(r"review-scope:\s*`?\s*(none|light|standard|high)\b", re.I)
ATTESTED = re.compile(r"\b(owner|user)\b[^\"“”\n]{0,30}:\s*[\"“][^\"”\n]{2,}[\"”]", re.I)
OUTCOMES_FIELD = re.compile(r"^\s*\*\*Outcomes:\*\*", re.M)
# review-scope.md § Conformance lines do not fund an evaluator: the executor reads these.
CONFORMANCE = re.compile(r"contradicts?\s+a\s+decision|(?:decisions?|architecture)[- ]conformance|"
                         r"contradicts?\s+(?:the\s+|an?\s+)?architecture", re.I)
CODE_SPAN = re.compile(r"`([^`]+)`")
# A skip verb in the head lets the reason follow the dash ("Tier-2 skipped — docs-only diff").
SKIPPED = re.compile(r"\b(?:auto-)?skipped\b", re.I)
# A line that states a verdict reports a review; it is never a scope line.
VERDICT = re.compile(r"\bAPPROVE\b|\bLGTM\b|\bREQUEST CHANGES\b|\bBLOCK\b|"
                     r"\b\d+\s+Critical\b|\bclean\b|\bPASS\b|\bFAIL\b", re.I)
# `Gate evaluator:`, `Goal-evaluator:` and `evaluator skipped` are the same line: a label the
# prefix misses is a line no check reads.
LEDGER_PREFIX = re.compile(r"^(?:(review)\s*:|(?:(?:gate|goal)[- ]+)?(evaluator)(?:\s*:|\s+(?=skipped\b)))",
                           re.I)
# The task field `Review: required` / `Review: skip` (task-fields.md) shares the prefix and is
# never a ledger line.
TASK_FIELD = re.compile(r"^review:\s*(required|skip)\b", re.I)
LIST_MARKER = re.compile(r"^(?:[-*+>]|\d+[.)])\s+")
TASK_ID = re.compile(r"\bTask\s+(\d+)\.(\d+)\b", re.I)
# This plugin's prefix: a claim may name a role as `planning:<agent>` or `<agent>`, and
# the log must hold the installed `planning:<agent>` name, so a user's own role of the
# same bare name never stands in for this plugin's.
OWN_PREFIX = "planning:"
UNTYPED = ("", "default")


def own_role(claimed):
    """The installed role a claim names, or None for an untyped agent."""
    bare = claimed[len(OWN_PREFIX):] if claimed.startswith(OWN_PREFIX) else claimed
    return None if bare in UNTYPED else OWN_PREFIX + bare


def same_role(logged, claimed):
    """Whether a Codex `start` row's role is the installed role the claim names."""
    role = own_role(claimed)
    return role is not None and isinstance(logged, str) and logged == role


def last_task_commit(repo, stage):
    """When the newest `Stage N Task …` commit was made, or None when there is none."""
    r = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%cI", "-E",
                        f"--grep=^Stage {stage} Task "], capture_output=True, text=True)
    try:
        return ts(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except (TypeError, ValueError):
        return None


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
            out.append((m.group(1) or m.group(2)).lower() + ": " + line[m.end():].strip())
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


def gate_region(plan_text, stage):
    """Every line under the plan's `### Stage <stage> Gate` heading, up to the next heading
    of the same or a higher level: a `#### Round 2` inside the gate stays in it."""
    out, level = [], None
    for line in plan_text.splitlines():
        h = HEADING.match(line)
        if h:
            m = GATE_HEAD.match(line)
            if m and int(m.group(2)) == stage:
                level = len(m.group("hashes"))
                continue
            if level is not None and len(h.group(1)) <= level:
                level = None
        if level is not None:
            out.append(line)
    return out


def gate_boxes(plan_text, stage):
    """(mark, text) for every checklist box in the stage's gate region, bulleted, numbered
    or labelled."""
    return [(b.group("mark"), b.group("text"))
            for b in map(BOX.match, gate_region(plan_text, stage)) if b]


def gate_has_judgment(plan_text, stage):
    """A `(judgment)` line that needs a reader other than the executor."""
    return any("(judgment)" in line.lower() and not CONFORMANCE.search(line)
               for line in gate_region(plan_text, stage))


def declared_tier(plan_text):
    m = DECLARED_TIER.search(plan_text)
    return m.group(1).lower() if m else None


def evaluator_mandated(plan_text, stage):
    """review-scope.md's gate column: never at `none`, always at `high`, otherwise at a gate
    with a `(judgment)` line or a stage with Outcomes. An undeclared plan is `standard`."""
    tier = declared_tier(plan_text)
    if tier == "none":
        return False
    if tier == "high" or gate_has_judgment(plan_text, stage):
        return True
    try:
        return OUTCOMES_FIELD.search(stage_section(plan_text, stage)) is not None
    except Usage:
        return False


def files_moved_since(sha, stage, repo, plan):
    """The files the commit the stage ends on (its `Stage N green`, else HEAD) holds
    differently from <sha>: a command green there says nothing about those. proof/ and
    the plan are the gate's own record, written after the command ran."""
    green = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%H", "-E",
                            f"--grep=^Stage {stage} green$", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    spec = [":(top)", ":(top,exclude)proof"]
    try:
        spec.append(":(top,exclude)" + Path(plan).resolve().relative_to(
            Path(repo).resolve()).as_posix())
    except ValueError:
        pass
    r = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", sha, green or "HEAD",
                        "--", *spec], capture_output=True, text=True)
    return r.stdout.split()


def goal_skip_problems(line, plan_text, stage, repo, plan):
    """Why an `evaluator: skipped — goal command` line does not stand, or [] when it does."""
    m = GOAL_SKIP.match(line)
    if not m:
        return ["name the command and the commit: `evaluator: skipped — goal command "
                "`<cmd>` at <sha>`, or quote the owner's opt-out"]
    probs = []
    if declared_tier(plan_text) == "high":
        probs.append("the plan declares review-scope high, where the evaluator always runs")
    boxes = gate_boxes(plan_text, stage)
    if gate_has_judgment(plan_text, stage):
        probs.append(f"the Stage {stage} gate has a (judgment) line: a reader decides it, so "
                     "the evaluator runs")
    cmd = " ".join(m.group("cmd").split())
    if not any(mark in "xX" and "(goal)" in text.lower()
               and cmd in (" ".join(c.split()) for c in CODE_SPAN.findall(text))
               for mark, text in boxes):
        probs.append(f"no ticked (goal) box of the Stage {stage} gate runs `{cmd}`")
    sha = m.group("sha")
    ok = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                         f"{sha}^{{commit}}", "HEAD"], capture_output=True).returncode == 0
    if not ok:
        probs.append(f"{sha} is not a commit HEAD holds")
    else:
        moved = files_moved_since(sha, stage, repo, plan)
        if moved:
            probs.append(f"{sha} is not the tree the stage ends on: {', '.join(moved[:5])} "
                         "changed after it, so run the command on the last commit and name that")
    return probs


def gate(args):
    try:
        plan_text = Path(args.plan).read_text(errors="replace")
    except OSError as e:
        raise Usage(f"cannot read plan {args.plan}: {e}")
    if args.report:
        try:
            text = (sys.stdin.read() if args.report == "-"
                    else Path(args.report).read_text(errors="replace"))
        except OSError as e:
            raise Usage(f"cannot read --report {args.report}: {e}")
    else:
        text = stage_section(plan_text, args.stage)
    lines = ledger_lines(text)
    since = previous_green(args.repo, args.stage)
    try:
        rows = read_log(args.repo)
    except OSError as e:
        raise Usage(f"cannot read the dispatch log: {e}")
    no_log = (f"NOT RUN — no dispatch log at {Path(args.repo) / LOG}; no claimed review was "
              "checked. The hook (hooks/dispatch-log.sh) writes it only while "
              ".claude/plan-progress.json exists.")
    if rows is None and not lines:
        print(no_log)
        return 3
    if not lines:
        print(f"NOT CHECKED — no review: or evaluator: line for Stage {args.stage} "
              f"({'--report' if args.report else 'the plan section'}). A gate states every "
              "review, run or not; pass the draft report with --report.")
        return 3
    pool, ids = [], set()
    for r in rows or []:
        if r.get("event") != "start" or not isinstance(r.get("agent_id"), str) \
                or r["agent_id"] in ids:
            continue
        try:
            when = ts(r.get("ts"))
        except (TypeError, ValueError):
            continue
        if since is None or when >= since:
            ids.add(r["agent_id"])
            pool.append((when, r))
    boundary = last_task_commit(args.repo, args.stage)
    bad, advisory, unread = [], [], []
    for line in lines:
        head = VERDICT_SEP.split(line, maxsplit=1)[0]
        if line.startswith("evaluator:") and "SUBSTITUTED" not in head and (
                GOAL_SKIP_ANY.match(line) or SKIPPED.search(head)):
            if ATTESTED.search(line) and not GOAL_SKIP.match(line):
                print(f"  {'scope':<12} {line[:100]}")
                continue
            probs = goal_skip_problems(line, plan_text, args.stage, args.repo, args.plan)
            if probs:
                bad.append("; ".join(probs) + f": {line}")
            else:
                print(f"  {'goal-skip':<12} {line[:100]}")
            continue
        kind, role, stype = classify(line)
        if (kind == "scope" and role == "evaluator" and not ATTESTED.search(line)
                and evaluator_mandated(plan_text, args.stage)):
            bad.append(f"the Stage {args.stage} evaluator is mandated here; only the owner's "
                       f"quoted words or a goal-command skip excuse it: {line}")
            continue
        if (kind == "unnamed" and role == "evaluator" and not VERDICT.search(line)
                and not ATTESTED.search(line) and evaluator_mandated(plan_text, args.stage)):
            bad.append(f"the Stage {args.stage} evaluator is mandated here; name the agent, the "
                       f"goal command or the owner's quoted words: {line}")
            continue
        if kind == "claim" and rows is None:
            unread.append(line)
        elif kind == "claim":
            # A claim whose head names `Task N.M` is that task's Tier-1 review.
            t = TASK_ID.search(VERDICT_SEP.split(line, maxsplit=1)[0])
            task = (int(t.group(1)), int(t.group(2))) if t else None
            if task is not None and task[0] != args.stage:
                bad.append(f"names Task {task[0]}.{task[1]}, which is not a Stage "
                           f"{args.stage} task: {line}")
                continue
            if own_role(stype) is None:
                bad.append(f"names an untyped `{stype}` agent, which no log row can tell "
                           f"from another spawn; name the installed planning: role: {line}")
                continue
            # A task's review ran before that task's commit; a stage's after the last one.
            fits = (lambda w: True) if boundary is None else \
                ((lambda w: w < boundary) if task is not None else (lambda w: w >= boundary))
            hit = next(((w, r) for w, r in pool
                        if fits(w) and same_role(r.get("agent_type"), stype)), None)
            if hit is not None:
                pool.remove(hit)
                print(f"  matched      {stype} (start {hit[1].get('agent_id')}): {line[:90]}")
            else:
                window = ("before" if task is not None else "after") + \
                    " the stage's last task commit" if boundary is not None else "in the window"
                bad.append(f"no `{own_role(stype)}` start logged {window} since "
                           f"{'the log start' if since is None else since.isoformat()}: {line}")
        elif kind == "unnamed":
            advisory.append(f"names no dispatched agent as `<agent> over <range>` "
                            f"before its first ` — `, and gives no reason a review did not "
                            f"run (not run, not dispatched, not mandated, opt-out, a trivial "
                            f"or non-code diff) outside verdict prose: {line}")
        else:
            print(f"  {kind:<12} {line[:100]}")
    if (evaluator_mandated(plan_text, args.stage)
            and not any(line.startswith("evaluator:") for line in lines)):
        bad.append(f"no evaluator line, and the Stage {args.stage} evaluator is mandated here")
    for b in bad:
        print(f"  UNMATCHED    {b}")
    for a in advisory:
        print(f"  ADVISORY     {a}")
    if unread and not bad:
        print(no_log)
        return 3
    return 1 if bad else 3 if unread else 4 if advisory else 0


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
