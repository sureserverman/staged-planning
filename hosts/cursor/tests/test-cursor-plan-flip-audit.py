#!/usr/bin/env python3
"""Four paths of the Cursor plan-flip-audit.py, run from the built Cursor plugin.

On Cursor a stage's claims are proven once, at its gate: task commits carry code only
and the stage's records land with its `Stage N green` commit. The fork follows that in
two places core does not have, and shares two more with core that no Cursor-side test
ran before:

  every claim      findings 8 and 9 hold EVERY Test claim of a ticked task to a
                   prove-claim.py record (every_claim()); core asks only for the first
                   claim and those that name their break "(red if …)". Two claims, the
                   second naming no break, only the first proven -> finding 8 blocking,
                   "1 of 2"; both proven -> clean; one claim proven -> clean
  stage in flight  the tasks of the stage .claude/plan-progress.json names for this plan,
                   in phase preflight, task or gate, with no gate box ticked and no
                   `Stage N green` commit, are skipped by findings 8 and 9 (open_stage());
                   core holds them to their proof. Each phase skips; no run state,
                   phase stage-complete, a ticked gate box, a `Stage 1 green` commit, or
                   a state naming another plan each hold the task again; a finished
                   stage 1 is still held while stage 2 is in flight
  gate remediation finding 10: a `Stage N gate remediation` commit, on or after the
                   plan's date, for a gate with a `**Live check` box and no
                   `fixture-sweep:` trailer -> one advisory finding, exit 4; the trailer
                   clears it; a gate with no live check, or a commit dated before the
                   plan, is not reported
  goal skip        a demo report recording the evaluator skipped because the gate's
                   ticked `(goal)` command decides the goal (demo_problems, which the
                   Cursor ref hook calls with the plan and the stage): accepted with each
                   Outcome's `Decided by:`; refused at a gate with a `(judgment)` line, an
                   unticked `(goal)` box, an Outcome with no `Decided by:`, or no plan
  staleness wiring a copy of the built plugin in a cache-shaped tree, behind a checkout
                   that advertises a newer version, warns on stderr (even on a refused
                   run, and with --json stdout still one document); the opt-out
                   silences it; with the plugin's lib/staleness.py gone the warning goes
                   and the audit still runs

Each case builds its own throwaway project repo (hermetic git env, `--template=`) with
the plan kept outside it, as a records home is. HOME is a scratch dir. The records are
written by the built prove-claim.py. unrecorded_gate() is test-cursor-unrecorded-gate.py's.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REL = os.path.join("skills", "executing-plans", "scripts")
FORK = os.path.join(REPO, "hosts", "cursor", "overrides", REL, "plan-flip-audit.py")
FAILS = []
GITENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}

CALC = "def add(a, b):\n    return a + b\n"
TESTPY = "import sys\nsys.path.insert(0, '.')\nfrom calc import add\nassert add(2, 3) == 5\n"
BUILD = "python3 -c 'import ast; ast.parse(open(\"calc.py\").read())'"
TEST_CMD = "python3 tests/test_calc.py"
CLAIM1 = "add returns the sum (red if add subtracts)"
REC_PLAN = (
    "# Plan\n\n## Stage 1: calc\n\n"
    "### Task 1.1: calc\n- **Status:** [x]\n- `add` returns the sum.\n"
    f"- **Test:** `{TEST_CMD}` — {CLAIM1}{{more}}\n\n"
    "### Stage 1 Gate\n- [{gate}] the suite passes: `" + TEST_CMD + "`\n"
)
TWO_STAGE_PLAN = (
    "# Plan\n\n## Stage 1: calc\n\n"
    "### Task 1.1: calc\n- **Status:** [x]\n- `add` returns the sum.\n"
    f"- **Test:** `{TEST_CMD}` — {CLAIM1}\n\n"
    "### Stage 1 Gate\n- [x] the suite passes: `" + TEST_CMD + "`\n\n"
    "## Stage 2: more\n\n"
    "### Task 2.1: more\n- **Status:** [x]\n- `add` still returns the sum.\n"
    f"- **Test:** `{TEST_CMD}` — {CLAIM1}\n\n"
    "### Stage 2 Gate\n- [ ] the suite passes: `" + TEST_CMD + "`\n"
)
LIVE_PLAN = (
    "# Plan\n\n## Stage 1: parser\n\n"
    "### Task 1.1: parse\n- **Status:** [ ]\n"
    "- **Test:** `python3 t.py` — parses (red if it does not)\n\n"
    "### Stage 1 Gate\n\n"
    "- [ ] Stage-scope: `make test` exits 0\n"
    "- [ ] **Live check, rig-driven:** the test rig answers the probe request\n\n"
    "## Stage 2: docs\n\n"
    "### Task 2.1: docs\n- **Status:** [ ]\n"
    "- **Test:** `python3 d.py` — documents (red if it does not)\n\n"
    "### Stage 2 Gate\n\n"
    "- [ ] Stage-scope: `make test` exits 0\n"
)
STALE_MSG = "from the plugin cache"


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[:700].replace("\n", "\n     | "))


tmp = tempfile.mkdtemp(prefix="cursor-plan-flip-audit-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "cursor",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    AUDIT = os.path.join(out, REL, "plan-flip-audit.py")
    PC = os.path.join(out, REL, "prove-claim.py")
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith(("CURSOR_", "CLAUDE_", "GIT_", "STAGED_PLANNING_"))}
    env0.update(GITENV, HOME=os.path.join(tmp, "home"), XDG_CONFIG_HOME=os.path.join(tmp, "xdg"),
                PYTHONDONTWRITEBYTECODE="1")
    os.makedirs(env0["HOME"])
    n = [0]

    with open(AUDIT, "rb") as a, open(FORK, "rb") as b:
        check(a.read() == b.read(), "the built plan-flip-audit.py is the Cursor override")

    def git(repo, *a, env=None):
        r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", repo, *a],
                           capture_output=True, text=True, env=dict(env0, **(env or {})))
        assert r.returncode == 0, (a, r.stderr)
        return r.stdout

    def commit(repo, msg, env=None):
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--allow-empty", "-m", msg, env=env)

    def newdir(label):
        n[0] += 1
        d = os.path.join(tmp, f"{n[0]:02d}-{label}")
        os.makedirs(d)
        return d

    def newrepo(label):
        d = newdir(label)
        subprocess.run(["git", "init", "-q", "--template=", "-b", "main", d], check=True,
                       env=dict(env0))
        return d

    def rec_world(label, plan_text):
        plans = newdir(f"{label}-plans")
        proj = newrepo(f"{label}-proj")
        with open(os.path.join(proj, "calc.py"), "w") as fh:
            fh.write(CALC)
        os.makedirs(os.path.join(proj, "tests"))
        with open(os.path.join(proj, "tests", "test_calc.py"), "w") as fh:
            fh.write(TESTPY)
        with open(os.path.join(proj, ".gitignore"), "w") as fh:
            fh.write("__pycache__/\n.claude/\n")
        commit(proj, "base")
        plan = os.path.join(plans, "2026-10-04-rec-plan.md")
        with open(plan, "w") as fh:
            fh.write(plan_text)
        return plan, proj

    def add_code(proj):
        with open(os.path.join(proj, "calc.py"), "w") as fh:
            fh.write(CALC + "\n\ndef twice(a):\n    return 2 * a\n")

    def break_patch(proj):
        f = os.path.join(proj, "calc.py")
        orig = open(f).read()
        with open(f, "w") as fh:
            fh.write(orig.replace("return a + b", "return a - b"))
        d = git(proj, "diff", "--", "calc.py")
        with open(f, "w") as fh:
            fh.write(orig)
        p = os.path.join(newdir("brk"), "break.patch")
        with open(p, "w") as fh:
            fh.write(d)
        return p

    def prove(plan, proj, claims=(1,), task="1.1"):
        """Record the given claims, and requirement 1 covered by the first, on the index."""
        git(proj, "add", "-A")
        brk = break_patch(proj)
        base = ["--repo", proj, "--plan", plan, "--task", task]
        for k in claims:
            r = subprocess.run([sys.executable, PC, "claim", *base, "--claim", str(k), "--break",
                                brk, "--test", TEST_CMD, "--build", BUILD],
                               capture_output=True, text=True, env=dict(env0))
            assert r.returncode == 0, ("claim", k, r.stdout, r.stderr)
        r = subprocess.run([sys.executable, PC, "req", *base, "--req", "1", "--covered-by-claim",
                            str(claims[0])], capture_output=True, text=True, env=dict(env0))
        assert r.returncode == 0, ("req", r.stdout, r.stderr)

    def state(proj, plan, phase, stage=1, task="1.1"):
        os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(proj, ".claude", "plan-progress.json"), "w") as fh:
            json.dump({"plan": plan, "phase": phase, "stage": stage, "task": task,
                       "updated": ts}, fh)

    def audit(plan, proj, script=None, env=None):
        r = subprocess.run([sys.executable, script or AUDIT, plan, "--repo", proj, "--json"],
                           capture_output=True, text=True, cwd=tmp,
                           env=dict(env0, **(env or {})))
        try:
            return r, json.loads(r.stdout)
        except ValueError:
            return r, None

    def task_f(doc, finding, task="1.1"):
        if doc is None:
            return None
        return [f for f in doc.get("findings", [])
                if f.get("finding") == finding and f.get("text") == f"Task {task}"]

    # ======================================================== every claim (every_claim)
    print("every claim of a ticked task needs a record on Cursor")
    plan, proj = rec_world("one-claim", REC_PLAN.format(more="", gate=" "))
    add_code(proj)
    prove(plan, proj)
    commit(proj, "Stage 1 Task 1.1: twice")
    r, doc = audit(plan, proj)
    check(doc is not None and task_f(doc, 8) == [] and task_f(doc, 9) == []
          and {8, 9} <= set(doc.get("checks_run", [])),
          "one claim, proven and committed with its code: clean on findings 8 and 9",
          (r.returncode, r.stdout[:600], r.stderr[:300]))

    two = REC_PLAN.format(more="; add is commutative", gate=" ")
    plan, proj = rec_world("unnamed-second", two)
    add_code(proj)
    prove(plan, proj)
    commit(proj, "Stage 1 Task 1.1: second claim names no break")
    r, doc = audit(plan, proj)
    f8 = task_f(doc, 8) or []
    check(len(f8) == 1 and f8[0].get("severity") == "blocking"
          and "1 of 2 required claim" in f8[0].get("rule", "") and r.returncode == 1,
          "a second claim that names no break and has no record blocks the task",
          (r.returncode, f8, r.stderr[:300]))

    plan, proj = rec_world("both-proven", two)
    add_code(proj)
    prove(plan, proj, claims=(1, 2))
    commit(proj, "Stage 1 Task 1.1: both claims proven")
    r, doc = audit(plan, proj)
    check(doc is not None and task_f(doc, 8) == [],
          "with both claims recorded the task is clean on finding 8",
          (r.returncode, task_f(doc, 8), r.stderr[:300]))

    # ======================================================== stage in flight (open_stage)
    print("the stage in flight is proven at its gate, not before")

    def unproven(label, gate=" ", green=False):
        plan, proj = rec_world(label, REC_PLAN.format(more="", gate=gate))
        add_code(proj)
        commit(proj, "Stage 1 Task 1.1: twice")
        if green:
            commit(proj, "Stage 1 green")
        return plan, proj

    plan, proj = unproven("no-state")
    r, doc = audit(plan, proj)
    f8 = task_f(doc, 8) or []
    check(len(f8) == 1 and f8[0].get("severity") == "blocking",
          "no run state: a ticked task with no record is blocking", (r.returncode, f8))

    for phase in ("preflight", "task", "gate"):
        plan, proj = unproven(f"in-flight-{phase}")
        state(proj, plan, phase)
        r, doc = audit(plan, proj)
        check(doc is not None and task_f(doc, 8) == [] and task_f(doc, 9) == []
              and {8, 9} <= set(doc.get("checks_run", [])),
              f"phase {phase}, gate unticked, no green commit: the stage's tasks are skipped "
              "by findings 8 and 9", (r.returncode, r.stdout[:600], r.stderr[:300]))

    held = [
        ("phase stage-complete", dict(), dict(phase="stage-complete")),
        ("phase closeout", dict(), dict(phase="closeout")),
        ("a ticked Stage 1 Gate box", dict(gate="x"), dict(phase="task")),
        ("a `Stage 1 green` commit in HEAD's history", dict(green=True), dict(phase="task")),
    ]
    for i, (why, world, st) in enumerate(held):
        plan, proj = unproven(f"held-{i}", **world)
        state(proj, plan, **st)
        r, doc = audit(plan, proj)
        f8 = task_f(doc, 8) or []
        check(len(f8) == 1 and f8[0].get("severity") == "blocking",
              f"{why}: the task is held to its record again", (r.returncode, f8, r.stderr[:300]))

    plan, proj = unproven("other-plan")
    other = os.path.join(os.path.dirname(plan), "2026-10-04-other-plan.md")
    with open(other, "w") as fh:
        fh.write(REC_PLAN.format(more="", gate=" "))
    state(proj, other, "task")
    r, doc = audit(plan, proj)
    f8 = task_f(doc, 8) or []
    check(len(f8) == 1 and f8[0].get("severity") == "blocking",
          "a run state naming another plan exempts nothing here", (r.returncode, f8))

    plan, proj = rec_world("stage-2-in-flight", TWO_STAGE_PLAN)
    add_code(proj)
    commit(proj, "Stage 1 Task 1.1: twice")
    commit(proj, "Stage 1 green")
    commit(proj, "Stage 2 Task 2.1: more")
    state(proj, plan, "task", stage=2, task="2.1")
    r, doc = audit(plan, proj)
    f8_1, f8_2 = task_f(doc, 8) or [], task_f(doc, 8, "2.1")
    check(len(f8_1) == 1 and f8_1[0].get("severity") == "blocking" and f8_2 == [],
          "stage 2 in flight skips Task 2.1 and still holds finished stage 1's Task 1.1",
          (r.returncode, f8_1, f8_2))

    # ======================================================== gate remediation (finding 10)
    print("finding 10 — a live-checked gate's remediation commit without a fixture sweep")

    def live_world(label, subject, body="", date=None):
        plans = newdir(f"{label}-plans")
        proj = newrepo(f"{label}-proj")
        with open(os.path.join(proj, "README"), "w") as fh:
            fh.write("x\n")
        commit(proj, "base")
        plan = os.path.join(plans, "2026-10-01-live-plan.md")
        with open(plan, "w") as fh:
            fh.write(LIVE_PLAN)
        with open(os.path.join(proj, "parser.py"), "w") as fh:
            fh.write("x = 1\n")
        when = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else None
        commit(proj, subject + ("\n\n" + body if body else ""), env=when)
        return plan, proj

    def f10(doc):
        return None if doc is None else [f for f in doc.get("findings", []) if f.get("finding") == 10]

    plan, proj = live_world("live-nosweep", "Stage 1 gate remediation round 1: fit the parser")
    r, doc = audit(plan, proj)
    got = f10(doc) or []
    check(len(got) == 1 and got[0].get("severity") == "advisory" and r.returncode == 4
          and 10 in doc.get("checks_run", []) and "fixture-sweep:" in got[0].get("rule", ""),
          "a remediation commit on a live-checked gate with no fixture-sweep: trailer: one "
          "advisory finding, exit 4", (r.returncode, got, r.stderr[:300]))
    plan, proj = live_world("live-comma", "Stage 1 gate, remediation round 2: refit")
    r, doc = audit(plan, proj)
    check(len(f10(doc) or []) == 1, "the `Stage N gate, remediation` spelling is read too",
          (r.returncode, f10(doc)))
    plan, proj = live_world("live-sweep", "Stage 1 gate remediation round 1: fit the parser",
                            "fixture-sweep: python3 -m pytest tests/captures  # 3 captures")
    r, doc = audit(plan, proj)
    check(doc is not None and f10(doc) == [] and r.returncode == 0
          and 10 in doc.get("checks_run", []),
          "the same commit with a fixture-sweep: trailer is clean", (r.returncode, f10(doc)))
    plan, proj = live_world("live-hostonly", "Stage 2 gate remediation round 1: reword the docs")
    r, doc = audit(plan, proj)
    check(doc is not None and f10(doc) == [],
          "a remediation of a gate with no **Live check box is not reported",
          (r.returncode, f10(doc)))
    plan, proj = live_world("live-earlier", "Stage 1 gate remediation round 1: an older plan",
                            date="2026-09-01T12:00:00+00:00")
    r, doc = audit(plan, proj)
    check(doc is not None and f10(doc) == [],
          "a remediation commit dated before the plan's own date is not reported",
          (r.returncode, f10(doc)))

    # ======================================================== staleness wiring
    print("staleness — the audit warns when it runs from a superseded plugin cache")
    cache = os.path.join(tmp, "stale", "plugins", "cache", "example-market", "planning", "0.0.1")
    shutil.copytree(out, cache)
    cached = os.path.join(cache, REL, "plan-flip-audit.py")
    checkout = os.path.join(tmp, "stale", "checkout")
    os.makedirs(os.path.join(checkout, ".claude-plugin"))
    with open(os.path.join(checkout, ".claude-plugin", "marketplace.json"), "w") as fh:
        json.dump({"name": "example-market",
                   "plugins": [{"name": "planning", "version": "9.9.9"}]}, fh)
    senv = {"STAGED_PLANNING_CHECKOUT": checkout}

    def run_cached(*args, env=None):
        return subprocess.run([sys.executable, cached, *args], capture_output=True, text=True,
                              cwd=tmp, env=dict(env0, **senv, **(env or {})))

    r = run_cached("--no-such-flag-xyz")
    check(STALE_MSG in r.stderr and "planning 0.0.1" in r.stderr and "9.9.9" in r.stderr,
          "a refused run from a stale cache still warns on stderr", (r.returncode, r.stderr[:300]))
    plan, proj = live_world("stale-run", "Stage 1 gate remediation round 1: fit the parser")
    r, doc = audit(plan, proj, script=cached, env=senv)
    check(STALE_MSG in r.stderr and STALE_MSG not in r.stdout and doc is not None
          and len(f10(doc) or []) == 1,
          "a real audit from the stale cache warns on stderr and its --json stdout is still "
          "one document with its findings", (r.returncode, r.stdout[:300], r.stderr[:300]))
    r = run_cached("--no-such-flag-xyz", env={"STAGED_PLANNING_NO_STALE_WARNING": "1"})
    check(STALE_MSG not in r.stderr, "STAGED_PLANNING_NO_STALE_WARNING=1 silences it",
          r.stderr[:300])
    r = subprocess.run([sys.executable, AUDIT, "--no-such-flag-xyz"], capture_output=True,
                       text=True, cwd=tmp, env=dict(env0, **senv))
    check(STALE_MSG not in r.stderr, "the same audit outside a plugin cache is silent",
          r.stderr[:300])
    os.remove(os.path.join(cache, "lib", "staleness.py"))
    r, doc = audit(plan, proj, script=cached, env=senv)
    check(STALE_MSG not in r.stderr and doc is not None and len(f10(doc) or []) == 1
          and r.returncode == 4,
          "the probe is the plugin's own lib/staleness.py: without it there is no warning, "
          "and the audit still runs", (r.returncode, r.stdout[:300], r.stderr[:300]))

    # ---- goal skip: the built fork's demo check, as the Cursor ref hook calls it
    import importlib.util
    spec = importlib.util.spec_from_file_location("cursor_pfa", AUDIT)
    pfa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pfa)
    outcome = "Works: the sum reaches the caller."
    goal = "- [x] **(goal)** the sum is right: `python3 tests/test_calc.py`"
    splan = ("# Plan\n\n## Stage 1: calc\n\n**Outcomes:** the caller\n- " + outcome
             + "\n\n### Stage 1 Gate\n{gate}\n")
    demo = ("Evaluator: skipped — goal command `python3 tests/test_calc.py` at 0123abcd\n\n"
            "## Outcome 1\n> " + outcome + "\nVerdict: holds\n{decided}"
            "Evidence:\n$ python3 tests/test_calc.py -> exit 0, sum 5\n")
    decided = "Decided by: `python3 tests/test_calc.py` at 0123abcd\n"
    for name, gate, dec, plan_given, want in (
            ("accepted with each Outcome's Decided by", goal, decided, True, ""),
            ("refused at a gate with a (judgment) line",
             goal + "\n- [x] **(judgment)** reads well", decided, True, "(judgment)"),
            ("refused with the (goal) box unticked", goal.replace("[x]", "[ ]"), decided, True,
             "(goal)"),
            ("refused with an Outcome naming no Decided by", goal, "", True, "Decided by"),
            ("refused with no plan to judge it against", goal, decided, False, "none was given")):
        probs = pfa.demo_problems(demo.format(decided=dec), [outcome],
                                  splan.format(gate=gate) if plan_given else None,
                                  "1" if plan_given else None)
        ok = (not probs) if not want else any(want in p for p in probs)
        check(ok, f"goal skip: {name}", probs)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
