#!/usr/bin/env python3
"""Fixture suite for review-ledger-check.py — run directly (repo convention):

    python3 core/skills/executing-plans/tests/test-review-ledger-check.py

WHAT THIS SUITE IS REALLY GUARDING. A gate report's review line is a self-report:
"review: Tier-2 planning:code-reviewer over <base>..HEAD — APPROVE" reads the same
whether a reviewer ran or not. review-ledger-check.py compares each
claimed dispatch with the dispatch log hooks/dispatch-log.sh writes. The failures that
matter: a fabricated review passing, an old dispatch (an earlier stage's) satisfying a
new claim, a missing log reading as green, a disclosed SUBSTITUTED line being refused,
and an agent left running going unreported. One case builds its log through the real
hook, so the script and the hook cannot drift apart on the line format.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "review-ledger-check.py"
HOOK = HERE.parents[2] / "hooks" / "dispatch-log.sh"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")
        if detail:
            print(f"        | {str(detail)[:700]}")


GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo, *args, date=None):
    env = dict(GIT_ENV)
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True,
                          text=True, check=True)


def mkrepo(root):
    repo = Path(root) / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "work")
    (repo / ".claude").mkdir()
    (repo / "f").write_text("0\n")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "base", date="2026-10-06T08:00:00+00:00")
    return repo


def commit(repo, subject, date):
    (repo / "f").write_text(f"{subject} {date}\n")  # unique: a repeated subject still commits
    git(repo, "commit", "-q", "-am", subject, date=date)


def write_log(repo, rows):
    with open(repo / ".claude" / "dispatch-log.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def dispatch(ts, stype, description="Stage 2 Tier-2 review"):
    return {"ts": ts, "event": "dispatch", "session_id": "s", "subagent_type": stype,
            "description": description}


def agent(ts, event, aid, atype):
    return {"ts": ts, "event": event, "session_id": "s", "agent_type": atype, "agent_id": aid}


PLAN = """# Project Plan: fixture

## Stage 1: one

### Task 1.1: a
- **Status:** [x]

### Stage 1 Gate

- [x] Stage-scope: `true`

**Handoff (Stage 1):**
{s1}

---

## Stage 2: two

### Task 2.1: b
- **Status:** [x]

### Stage 2 Gate

- [ ] Stage-scope: `true`

**Handoff (Stage 2):**
{s2}
"""


_plans = 0


def write_plan(root, s1="", s2=""):
    # A file per call: a case holding an earlier plan must not read a later one's text.
    global _plans
    _plans += 1
    p = Path(root) / f"fixture-{_plans}-plan.md"
    p.write_text(PLAN.format(s1=s1, s2=s2))
    return p


def run(*args, stdin=None):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True,
                       text=True, input=stdin)
    return r.returncode, r.stdout + r.stderr


REVIEW = "review: Tier-2 planning:code-reviewer over 1a2b3c..HEAD — APPROVE, 0 Critical"

print("review-ledger-check — claimed reviews against the dispatch log, and agents left running")
print()

if not SCRIPT.exists():
    print(f"FAIL: {SCRIPT} does not exist")
    sys.exit(1)

with tempfile.TemporaryDirectory() as t:
    repo = mkrepo(t)
    commit(repo, "Stage 1 green", "2026-10-06T10:00:00+00:00")

    # Catches: a real review being refused.
    plan = write_plan(t, s2=REVIEW)
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a claimed Tier-2 review with a matching dispatch passes", rc == 0, f"rc={rc} {out}")

    # Catches: a fabricated review passing — no dispatch of the claimed type.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "general-purpose")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a claimed review with no dispatch of that type exits 1 naming it",
          rc == 1 and "planning:code-reviewer" in out, f"rc={rc} {out}")

    # Catches: an old dispatch (before the previous stage's green commit) satisfying a new claim.
    write_log(repo, [dispatch("2026-10-06T09:55:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a dispatch before the previous stage's green commit does not count",
          rc == 1 and "planning:code-reviewer" in out, f"rc={rc} {out}")

    # Catches: two passes claimed on one dispatch (high tier's second pass).
    plan2 = write_plan(t, s2=REVIEW + "\nreview: second pass planning:code-reviewer over "
                       "1a2b3c..HEAD — APPROVE")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan2, "--stage", 2, "--repo", repo)
    check("two claimed passes need two dispatches", rc == 1, f"rc={rc} {out}")

    # Catches: an evaluator claim escaping the check.
    plan3 = write_plan(t, s2="evaluator: general-purpose in the goal-evaluator role, briefed "
                       "on the stage goal + gate criteria — PASS")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan3, "--stage", 2, "--repo", repo)
    check("a claimed evaluator with no general-purpose dispatch exits 1",
          rc == 1 and "general-purpose" in out, f"rc={rc} {out}")

    # Catches: a task worker of the claimed type satisfying an evaluator claim —
    # the dispatch must name the stage and the role in its description.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "general-purpose",
                              "Task 2.1: build the parser")])
    rc, out = run("--plan", plan3, "--stage", 2, "--repo", repo)
    check("a task worker of the claimed type does not satisfy an evaluator claim",
          rc == 1, f"rc={rc} {out}")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "general-purpose",
                              "Stage 2 gate evaluator")])
    rc, out = run("--plan", plan3, "--stage", 2, "--repo", repo)
    check("a dispatch naming the stage and the evaluator role satisfies it", rc == 0,
          f"rc={rc} {out}")
    # A per-task (Tier-1) review of the same type is not the stage's Tier-2 pass.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Stage 2 Task 2.1 quick review")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a per-task review dispatch does not satisfy a stage Tier-2 claim", rc == 1,
          f"rc={rc} {out}")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Stage 3 Tier-2 review")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a review dispatch naming another stage does not count", rc == 1, f"rc={rc} {out}")

    # A Tier-1 line names its task: it is matched against that task's dispatch, never
    # a stage pass, so it cannot take the dispatch the stage's own line needs.
    tier1 = ("review: Tier-1 planning:code-reviewer over the Task 2.1 diff — APPROVE\n"
             + REVIEW)
    plan_t1 = write_plan(t, s2=tier1)
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Stage 2 Task 2.1 quick review"),
                     dispatch("2026-10-06T10:06:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan_t1, "--stage", 2, "--repo", repo)
    check("a Tier-1 line matches its task's dispatch and the stage line the stage's",
          rc == 0, f"rc={rc} {out}")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer"),
                     dispatch("2026-10-06T10:06:00+00:00", "planning:code-reviewer",
                              "Stage 2 second-pass review")])
    rc, out = run("--plan", plan_t1, "--stage", 2, "--repo", repo)
    check("a Tier-1 line is not satisfied by a stage pass", rc == 1 and "Task 2.1" in out,
          f"rc={rc} {out}")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Stage 2 Task 2.2 quick review"),
                     dispatch("2026-10-06T10:06:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan_t1, "--stage", 2, "--repo", repo)
    check("a Tier-1 line is not satisfied by another task's dispatch", rc == 1,
          f"rc={rc} {out}")
    plan_t1x = write_plan(t, s2="review: Tier-1 planning:code-reviewer over the Task 1.1 diff — APPROVE")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Task 1.1 quick review")])
    rc, out = run("--plan", plan_t1x, "--stage", 2, "--repo", repo)
    check("a Tier-1 line naming another stage's task does not count at this gate", rc == 1,
          f"rc={rc} {out}")

    # Catches: the type read from text after the verdict.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    plan_i1 = write_plan(t, s2=REVIEW + "; 2 Suggestions carried over to the backlog")
    rc, out = run("--plan", plan_i1, "--stage", 2, "--repo", repo)
    check("an honest line with a second `over` after the verdict is read correctly",
          rc == 0, f"rc={rc} {out}")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "general-purpose",
                              "Stage 2 Tier-2 review")])
    plan_i1b = write_plan(t, s2="review: Tier-2 inline — APPROVE; general-purpose over x")
    rc, out = run("--plan", plan_i1b, "--stage", 2, "--repo", repo)
    check("a type placed after the verdict is not read as the claim's agent", rc == 4,
          f"rc={rc} {out}")

    # Catches: SUBSTITUTED anywhere on the line exempting a dispatch claim.
    write_log(repo, [])
    plan_s1 = write_plan(t, s2=REVIEW + " (not SUBSTITUTED)")
    rc, out = run("--plan", plan_s1, "--stage", 2, "--repo", repo)
    check("SUBSTITUTED after the verdict does not exempt the claim", rc == 1, f"rc={rc} {out}")

    # Catches: ledger lines in another case or under a list marker read as none.
    write_log(repo, [])
    for form in ("- **Review:** Tier-2 planning:code-reviewer over a..HEAD — APPROVE",
                 "1. review: Tier-2 planning:code-reviewer over a..HEAD — APPROVE"):
        rc, out = run("--plan", write_plan(t, s2=form), "--stage", 2, "--repo", repo)
        check(f"a ledger line is read under its markup: {form[:24]!r}", rc == 1,
              f"rc={rc} {out}")

    # Catches: a task's `Review: required` field read as a ledger line,
    # turning "nothing checked" into a scope line and exit 0.
    write_log(repo, [])
    rc, out = run("--plan", write_plan(t, s2="- **Review:** required"), "--stage", 2,
                  "--repo", repo)
    check("a task's `Review: required` field is not a ledger line (exit 3, NOT CHECKED)",
          rc == 3 and "NOT CHECKED" in out, f"rc={rc} {out}")

    # Catches: a fabricated review with an unlisted verdict word passing as a scope line.
    # A line naming no agent and no reason is ADVISORY (exit 4), never 0: over a corpus of
    # real ledgers its hits are honest lines (the count is in the script's docstring), so
    # it warns, and only an unmatched dispatch claim fails.
    for fake in ("review: Tier-2 planning:code-reviewer — looked at the diff, clean",
                 "review: Tier-2 — LGTM", "review: done, no issues"):
        rc, out = run("--plan", write_plan(t, s2=fake), "--stage", 2, "--repo", repo)
        check(f"a review line naming no agent and no scope reason is advisory: {fake[:30]!r}",
              rc == 4 and "ADVISORY" in out, f"rc={rc} {out}")
    # An unmatched claim still fails the gate beside an advisory line.
    rc, out = run("--plan", write_plan(t, s2=REVIEW + "\nreview: Tier-2 — LGTM"), "--stage", 2,
                  "--repo", repo)
    check("an unmatched claim beside an advisory line exits 1", rc == 1, f"rc={rc} {out}")
    # A matched claim beside an advisory line is advisory, not clean.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", write_plan(t, s2=REVIEW + "\nreview: Tier-2 — LGTM"), "--stage", 2,
                  "--repo", repo)
    check("a matched claim beside an advisory line exits 4", rc == 4, f"rc={rc} {out}")
    write_log(repo, [])

    # Catches: honest lines refused for trailing text after the range.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")] * 3)
    for honest in ("review: Tier-2 planning:code-reviewer over 0a1b2c3..4d5e6f7 "
                   "(second dispatch) — APPROVE",
                   "review: Tier-2 planning:code-reviewer over a..b: APPROVE, 0 Critical",
                   "review: Tier-2 review (planning:code-reviewer over 0a1..4d5): 0 Critical"):
        rc, out = run("--plan", write_plan(t, s2=honest), "--stage", 2, "--repo", repo)
        check(f"an honest line with text after the range is read: {honest[24:60]!r}",
              rc == 0, f"rc={rc} {out}")

    # Catches: `pass` matching inside another word.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Stage 2 encompassing bypass check")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a description containing `bypass` is not a review-role dispatch", rc == 1,
          f"rc={rc} {out}")

    # Catches: a claim dodging the grammar — a verdict with no named dispatched agent.
    plan4 = write_plan(t, s2="review: Tier-2 deep review done — APPROVE, 0 Critical")
    rc, out = run("--plan", plan4, "--stage", 2, "--repo", repo)
    check("a review line stating a verdict but naming no agent is advisory", rc == 4,
          f"rc={rc} {out}")

    # Catches: a tier-scope statement being refused.
    plan5 = write_plan(t, s2="review: Tier-2 not run — review-scope none mandates none")
    rc, out = run("--plan", plan5, "--stage", 2, "--repo", repo)
    check("a scope statement with no verdict passes", rc == 0, f"rc={rc} {out}")

    # Catches: a reason review-scope.md § Review opt-out sanctions refused for its
    # wording — the trivial/non-code diffs it names (docs-only, config-only,
    # pure version bumps, comment-only) and a user who "opted out".
    for sanctioned in ('review: Tier-2 skipped — user opt-out, Preflight: "skip it"',
                       'review: Tier-2 opted out by the user at Preflight — "skip it"',
                       "review: Tier-2 skipped — docs-only diff",
                       "review: Tier-2 skipped — config-only diff",
                       "review: Tier-2 skipped — a pure version bump",
                       "review: Tier-2 skipped — comment-only diff",
                       "review: Tier-2 skipped — non-code diff"):
        rc, out = run("--plan", write_plan(t, s2=sanctioned), "--stage", 2, "--repo", repo)
        check(f"a sanctioned reason is a scope line: {sanctioned[16:50]!r}", rc == 0,
              f"rc={rc} {out}")

    # Catches: a skip word in verdict prose clearing a line. The
    # reason must sit in the line's head, or follow a head that says the review was skipped,
    # and a line carrying a verdict is never a scope line.
    write_log(repo, [])
    for verdict in ("review: Tier-2 planning:code-reviewer — APPROVE, docs-only change",
                    "review: Tier-2 — LGTM, version bump looks right",
                    "review: Tier-2 planning:code-reviewer — skipped, docs-only diff",
                    "review: Tier-2 trivial — APPROVE, 0 Critical",
                    "review: round 2: redesign — unread, reviewed it myself: clean"):
        rc, out = run("--plan", write_plan(t, s2=verdict), "--stage", 2, "--repo", repo)
        check(f"a skip word in verdict prose is not a scope line: {verdict[16:52]!r}",
              rc == 4, f"rc={rc} {out}")
    rc, out = run("--plan", write_plan(t, s2=REVIEW + ", docs-only"), "--stage", 2,
                  "--repo", repo)
    check("a scope word cannot rescue a real claim with no dispatch", rc == 1, f"rc={rc} {out}")

    # Catches: the three lines gate-failure-procedure.md § A redesign the gate closes on
    # prescribes, read as unnamed. `reviewed by <type>` is a
    # dispatch claim; `battery <name>` and `unread` are scope.
    write_log(repo, [])
    for form in ("review: round 2: redesign — battery finding-10 trailer",
                 "review: round 2: redesign — unread (parse_rows() rewrite)",
                 "evaluator: not dispatched — all 5 gate checks are command checks"):
        rc, out = run("--plan", write_plan(t, s2=form), "--stage", 2, "--repo", repo)
        check(f"a prescribed no-dispatch line is a scope line: {form[8:40]!r}", rc == 0,
              f"rc={rc} {out}")
    redesign = "review: round 1: redesign — reviewed by planning:code-reviewer"
    rc, out = run("--plan", write_plan(t, s2=redesign), "--stage", 2, "--repo", repo)
    check("a redesign review with no dispatch exits 1", rc == 1, f"rc={rc} {out}")
    # Catches: a redesign claim in another spelling dropping from
    # a refusal to a warning.
    for variant in ("Review: Round 1: Redesign — reviewed by planning:code-reviewer",
                    "review: round 1: redesign — reviewed by `planning:code-reviewer`",
                    "review: round 1 redesign — reviewed by planning:code-reviewer",
                    "review: redesign — reviewed by planning:code-reviewer",
                    "review: round 1: redesign – reviewed by planning:code-reviewer",
                    "review: round 1: redesign -- reviewed by planning:code-reviewer"):
        rc, out = run("--plan", write_plan(t, s2=variant), "--stage", 2, "--repo", repo)
        check(f"a redesign claim variant with no dispatch exits 1: {variant[:40]!r}", rc == 1,
              f"rc={rc} {out}")
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer",
                              "Stage 2 redesign review")])
    rc, out = run("--plan", write_plan(t, s2=redesign), "--stage", 2, "--repo", repo)
    check("a redesign review with its dispatch passes", rc == 0, f"rc={rc} {out}")

    # Catches: the disclosed substitution path being refused.
    plan6 = write_plan(t, s2='review: Tier-2 SUBSTITUTED — ran inline, user authorised at '
                       'Preflight: "skip dispatch" — over 1a2b3c..HEAD — APPROVE')
    write_log(repo, [])
    rc, out = run("--plan", plan6, "--stage", 2, "--repo", repo)
    check("a SUBSTITUTED line passes with no dispatch", rc == 0, f"rc={rc} {out}")

    # Catches: no ledger line at all reading as checked.
    write_log(repo, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", write_plan(t, s2="nothing about reviews here"), "--stage", 2,
                  "--repo", repo)
    check("no review: or evaluator: line exits 3 (NOT CHECKED), never 0",
          rc == 3 and "NOT CHECKED" in out, f"rc={rc} {out}")

    # Catches: a draft report (--report) being ignored in favour of the plan.
    draft = Path(t) / "draft.txt"
    draft.write_text(REVIEW + "\n")
    plan7 = write_plan(t, s2="")
    write_log(repo, [])
    rc, out = run("--plan", plan7, "--stage", 2, "--repo", repo, "--report", draft)
    check("--report is read instead of the plan's handoff note", rc == 1, f"rc={rc} {out}")

    # Catches: Stage 1 having no previous green commit to bound it — the log's start is the bound.
    plan8 = write_plan(t, s1=REVIEW)
    write_log(repo, [dispatch("2026-10-06T09:00:00+00:00", "planning:code-reviewer",
                              "Stage 1 Tier-2 review")])
    rc, out = run("--plan", plan8, "--stage", 1, "--repo", repo)
    check("Stage 1 counts from the log's start", rc == 0, f"rc={rc} {out}")

    # Catches: no evidence reading as green.
    os.remove(repo / ".claude" / "dispatch-log.jsonl")
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a missing log exits 3 (NOT RUN), never 0", rc == 3 and "NOT RUN" in out,
          f"rc={rc} {out}")

    # Catches: an agent left running going unreported.
    write_log(repo, [agent("2026-10-06T10:01:00+00:00", "start", "a1", "general-purpose"),
                     agent("2026-10-06T10:02:00+00:00", "start", "a2", "planning:code-reviewer"),
                     agent("2026-10-06T10:03:00+00:00", "stop", "a1", "general-purpose")])
    rc, out = run("--unstopped", "--repo", repo)
    check("--unstopped lists a started-never-stopped agent and exits 1",
          rc == 1 and "a2" in out and "a1" not in out, f"rc={rc} {out}")
    write_log(repo, [agent("2026-10-06T10:01:00+00:00", "start", "a1", "general-purpose"),
                     agent("2026-10-06T10:03:00+00:00", "stop", "a1", "general-purpose")])
    rc, out = run("--unstopped", "--repo", repo)
    check("--unstopped exits 0 when every started agent stopped", rc == 0, f"rc={rc} {out}")
    os.remove(repo / ".claude" / "dispatch-log.jsonl")
    rc, out = run("--unstopped", "--repo", repo)
    check("--unstopped with no log exits 3 (NOT RUN)", rc == 3, f"rc={rc} {out}")

    # Catches: the script and the hook disagreeing on the line format — the log is
    # written by piping hook inputs through the real dispatch-log.sh.
    (repo / ".claude" / "plan-progress.json").write_text('{"plan": "p", "phase": "gate"}\n')
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    for payload in (
        {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Agent",
         "tool_input": {"subagent_type": "planning:code-reviewer", "description": "Stage 2 Tier-2 review",
                        "prompt": "p"}},
        {"session_id": "s", "hook_event_name": "SubagentStart", "agent_id": "h1",
         "agent_type": "planning:code-reviewer"},
    ):
        subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True, env=env,
                       capture_output=True)
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("a log written by the real hook satisfies a matching claim", rc == 0, f"rc={rc} {out}")
    # The hook writes wall-clock timestamps, so the case is repeated with the green commit an
    # hour before now rather than at the fixed date above: it holds whatever day it runs.
    hour_ago = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    commit(repo, "Stage 1 green", hour_ago)
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo)
    check("...also when the green commit is relative to now", rc == 0, f"rc={rc} {out}")
    rc, out = run("--unstopped", "--repo", repo)
    check("a start written by the real hook, with no stop, is listed by --unstopped",
          rc == 1 and "h1" in out, f"rc={rc} {out}")

    # Catches: the window opening at an OLDER `Stage 1 green` (an earlier plan's).
    repo3 = Path(t) / "r3"
    repo3.mkdir()
    git(repo3, "init", "-q", "-b", "work")
    (repo3 / ".claude").mkdir()
    (repo3 / "f").write_text("0\n")
    git(repo3, "add", "f")
    git(repo3, "commit", "-q", "-m", "base", date="2026-10-01T08:00:00+00:00")
    commit(repo3, "Stage 1 green", "2026-10-01T09:00:00+00:00")
    commit(repo3, "Stage 1 green", "2026-10-06T10:00:00+00:00")
    write_log(repo3, [dispatch("2026-10-03T10:00:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo3)
    check("the window opens at the NEWEST `Stage N-1 green` commit", rc == 1, f"rc={rc} {out}")

    # Catches: unreadable input escaping the documented usage exit.
    bad = Path(t) / "bad.txt"
    bad.write_bytes(b"\xff\xfe review: \x80\n")
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo3, "--report", Path(t) / "nope")
    check("an unreadable --report exits 2", rc == 2, f"rc={rc} {out}")
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo3, "--report", bad)
    check("an undecodable --report is read, not a traceback: no ledger line, so NOT CHECKED",
          rc == 3 and "NOT CHECKED" in out and "Traceback" not in out, f"rc={rc} {out}")

    # Catches: a missing Stage N-1 green commit silently widening the window.
    repo2 = Path(t) / "r2"
    repo2.mkdir()
    git(repo2, "init", "-q", "-b", "work")
    (repo2 / ".claude").mkdir()
    (repo2 / "f").write_text("0\n")
    git(repo2, "add", "f")
    git(repo2, "commit", "-q", "-m", "base")
    write_log(repo2, [dispatch("2026-10-06T10:05:00+00:00", "planning:code-reviewer")])
    rc, out = run("--plan", plan, "--stage", 2, "--repo", repo2)
    check("no `Stage N-1 green` commit is a usage error (exit 2), not a pass", rc == 2,
          f"rc={rc} {out}")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
