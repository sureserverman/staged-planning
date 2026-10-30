#!/usr/bin/env python3
"""The Codex review-ledger fork: a claimed review matches a logged start of its role.

Built from the sources to a scratch dir, then run against a throwaway repo holding a
`Stage 1 Task 1.1` commit, a dispatch log and a draft gate report. Codex logs only an
agent's role and id, so these are the ways a claim could pass with no review behind it:

  untyped     an evaluator claim naming an agent with no custom role never matches, so
              Preflight's untyped probe cannot stand in for the evaluator
  own role    a claim matches only the installed `planning:<agent>` role, never a user's
              own role of the same bare name
  once        one agent id counts once, however many rows repeat it
  timing      a Tier-1 claim takes a start before the stage's last task commit, a stage
              claim one after it, so task reviews cannot stand in for the stage's pass
  good        each claim with its own start of its role in its window matches (exit 0)
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FAILS = []
NOW = datetime.datetime.now(datetime.timezone.utc)
BEFORE = (NOW - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
AFTER = (NOW + datetime.timedelta(hours=1)).isoformat(timespec="seconds")
TIER2 = "review: Tier-2 planning:code-reviewer over a1..b2 — APPROVE"
SECOND = "review: second pass planning:code-reviewer over a1..b2 — APPROVE"
TIER1 = "review: Tier-1 planning:code-reviewer over the Task 1.1 diff — APPROVE"
EVAL = "evaluator: planning:goal-evaluator in the goal-evaluator role — PASS"
EVAL_UNTYPED = "evaluator: default in the goal-evaluator role — PASS"


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-ledger-test-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    script = os.path.join(out, "skills", "executing-plans", "scripts", "review-ledger-check.py")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, ".claude"))
    subprocess.run(["git", "init", "-q", "--template=", repo], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "--allow-empty", "-qm", "Stage 1 Task 1.1: the work"], check=True)
    plan = os.path.join(repo, "p-plan.md")
    with open(plan, "w") as fh:
        fh.write("# Project Plan: fixture\n\n## Stage 1: one\n\n### Stage 1 Gate\n- [ ] x\n")

    def run(rows, lines):
        with open(os.path.join(repo, ".claude", "dispatch-log.jsonl"), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        report = os.path.join(tmp, "report.md")
        with open(report, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        r = subprocess.run([sys.executable, script, "--plan", plan, "--stage", "1", "--repo", repo,
                            "--report", report], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def start(agent_id, role, when):
        return {"ts": when, "event": "start", "session_id": "s", "agent_type": role,
                "agent_id": agent_id}

    rc, o = run([start("p1", None, AFTER)], [EVAL_UNTYPED])
    check(rc == 1 and "untyped" in o, f"an untyped evaluator claim never matches ({rc})")
    rc, o = run([start("u1", "code-reviewer", AFTER)], [TIER2])
    check(rc == 1, f"a user's own `code-reviewer` role does not stand in ({rc})")
    rc, o = run([start("a1", "planning:code-reviewer", AFTER)] * 2, [TIER2, SECOND])
    check(rc == 1, f"one agent id repeated satisfies one claim, not two ({rc})")
    rc, o = run([start("t1", "planning:code-reviewer", BEFORE)], [TIER2])
    check(rc == 1 and "after the stage's last task commit" in o,
          f"a review started before the last task commit is no stage pass ({rc})")
    rc, o = run([start("t1", "planning:code-reviewer", BEFORE),
                 start("t2", "planning:code-reviewer", BEFORE)], [TIER1, TIER2])
    check(rc == 1, f"two task-time reviews cannot cover a Tier-1 and a Tier-2 claim ({rc})")
    rc, o = run([start("t1", "planning:code-reviewer", BEFORE),
                 start("g1", "planning:code-reviewer", AFTER),
                 start("g2", "planning:code-reviewer", AFTER),
                 start("e1", "planning:goal-evaluator", AFTER)], [TIER1, TIER2, SECOND, EVAL])
    check(rc == 0, f"each claim with its own start in its window matches ({rc}: {o[-300:]})")

    # goal skip: the gate evaluator skipped because the ticked (goal) command decides the
    # goal; the fork reads the line as the core does (stage-gate.md § Skipped when a
    # recorded command decides the goal).
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    skip = f"evaluator: skipped — goal command `python3 t.py` at {head}"
    goal = "- [x] **(goal)** it works: `python3 t.py`\n"
    for gate, want, msg in ((goal, 0, "a skip naming the ticked (goal) command passes"),
                            (goal + "- [x] **(judgment)** reads well\n", 1,
                             "a skip at a gate with a (judgment) line fails"),
                            (goal.replace("[x]", "[ ]"), 1,
                             "a skip whose (goal) box is not ticked fails")):
        with open(plan, "w") as fh:
            fh.write("# Project Plan: fixture\n\n## Stage 1: one\n\n### Stage 1 Gate\n" + gate)
        rc, o = run([], [skip])
        check(rc == want, f"{msg} ({rc}: {o[-200:]})")
    with open(plan, "w") as fh:
        fh.write("# Project Plan: fixture\n\n## Stage 1: one\n\n### Stage 1 Gate\n" + goal)
    rc, o = run([], ["evaluator: skipped"])
    check(rc == 1 and "name the command" in o, f"a bare `evaluator: skipped` fails ({rc}: {o[-200:]})")
    rc, o = run([], ["evaluator: skipped — docs-only diff"])
    check(rc == 1, f"an excuse word does not make a skip stand ({rc}: {o[-200:]})")
    # The fork's own loop reads the same two rules: the skip's commit is the tree the stage
    # ends on, and a missing log leaves the skip checks on.
    with open(os.path.join(repo, "later.py"), "w") as fh:
        fh.write("x = 1\n")
    subprocess.run(["git", "-C", repo, "add", "later.py"], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-qm", "later"], check=True)
    rc, o = run([], [skip])
    check(rc == 1 and "later.py" in o, f"a skip at a commit the stage changed files after fails ({rc}: {o[-200:]})")
    moved = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                           text=True, check=True).stdout.strip()
    skip = f"evaluator: skipped — goal command `python3 t.py` at {moved}"
    rc, o = run([], [skip])
    check(rc == 0, f"a skip at the commit the stage ends on passes ({rc}: {o[-200:]})")
    rows_gone = ["--plan", plan, "--stage", "1", "--repo", repo, "--report", "-"]
    os.remove(os.path.join(repo, ".claude", "dispatch-log.jsonl"))
    for line, want, msg in (("evaluator: skipped", 1, "with no log a bare skip still fails"),
                            (skip, 0, "with no log a correct skip and no claim passes"),
                            (skip + "\n" + TIER2, 3, "with no log a claim stays NOT RUN")):
        r = subprocess.run([sys.executable, script, *rows_gone], input=line + "\n",
                           capture_output=True, text=True)
        check(r.returncode == want, f"{msg} ({r.returncode}: {r.stdout[-200:]})")
    with open(plan, "w") as fh:
        fh.write("# Project Plan: fixture\n\n## Stage 1: one\n\n**Outcomes:** the user\n"
                 "- Works: it reads a file.\n\n### Stage 1 Gate\n" + goal)
    rc, o = run([], ["evaluator: not run — the diff looked small"])
    check(rc == 1 and "mandated" in o, f"a scope line at a stage with Outcomes fails ({rc}: {o[-200:]})")
    rc, o = run([], ['evaluator: not run — owner, 2026-10-30: "no evaluator here"'])
    check(rc == 0, f"the owner's quoted words excuse it ({rc}: {o[-200:]})")
finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
