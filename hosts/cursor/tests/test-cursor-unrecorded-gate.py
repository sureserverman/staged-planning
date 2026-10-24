#!/usr/bin/env python3
"""A stage claimed done with no `Stage N green` commit holds the Cursor stop hook.

The Cursor stop hook (hooks/plan-continue.sh) asks the shipped plan-flip-audit.py for
unrecorded_gate(repo, plan): the stage the run state claims done (phase stage-complete
or closeout, or the plan's own gate boxes for that stage ticked) whose `Stage N green`
commit is not in HEAD's history. While it answers a stage, the hook does not let the
turn end: it says to run the gate. Without the function the hook's check finds nothing
and the turn ends, so a stage that never committed its gate is never checked.

Each case builds the Cursor plugin into a scratch dir, makes a throwaway repo, and both
calls unrecorded_gate() from the built audit and runs the built stop hook as Cursor
does: from the workspace root, through a shell, with CURSOR_PLUGIN_ROOT set.

  unrecorded_gate  stage-complete, no green commit -> "1"; closeout -> "1"; phase task
                   with the stage's gate boxes ticked -> "1"; blocked or handoff -> None;
                   a `Stage 1 green` commit present -> None
  plan-continue    stage-complete and closeout with ticked boxes, no green commit -> a
                   followup_message saying to run the gate; with the green commit -> {}
"""
import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FAILS = []
GITENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
PLAN = """# Probe plan

## Stage 1: probe

### Task 1.1: probe
- **Status:** [x]
- **Test:** `true`

### Stage 1 Gate
- [{tick}] the probe passes: `true`

## Stage 2: next

### Task 2.1: next
- **Status:** [ ]
- **Test:** `true`
"""


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[:600].replace("\n", "\n     | "))


tmp = tempfile.mkdtemp(prefix="cursor-unrecorded-gate-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "cursor",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith(("CURSOR_", "CLAUDE_", "GIT_"))}
    env0.update(GITENV)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(
        "plan_flip_audit_cursor",
        os.path.join(out, "skills", "executing-plans", "scripts", "plan-flip-audit.py"))
    pfa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pfa)
    gate = getattr(pfa, "unrecorded_gate", None)
    check(callable(gate), "the built plan-flip-audit.py defines unrecorded_gate()")

    def git(repo, *a):
        # A global template or hooks path can abort a commit: none reaches this repo.
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", repo, *a],
                              capture_output=True, text=True, env=dict(env0))

    def mkrepo(name, phase, tick=" ", green=False):
        repo = os.path.join(tmp, name)
        os.makedirs(os.path.join(repo, ".claude"))
        os.makedirs(os.path.join(repo, "plans"))
        subprocess.run(["git", "init", "-q", "--template=", "-b", "main", repo], check=True,
                       env=dict(env0))
        with open(os.path.join(repo, "plans", "p-plan.md"), "w") as fh:
            fh.write(PLAN.format(tick=tick))
        with open(os.path.join(repo, "work.txt"), "w") as fh:
            fh.write("stage 1 work\n")
        git(repo, "add", "plans", "work.txt")
        r = git(repo, "commit", "-q", "-m", "Stage 1 Task 1.1: probe")
        assert r.returncode == 0, r.stderr
        if green:
            r = git(repo, "commit", "-q", "--allow-empty", "-m", "Stage 1 green")
            assert r.returncode == 0, r.stderr
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(repo, ".claude", "plan-progress.json"), "w") as fh:
            json.dump({"plan": "plans/p-plan.md", "phase": phase, "stage": 1, "task": "1.1",
                       "updated": ts}, fh)
        return repo

    def ask(repo):
        if not callable(gate):
            return "<no unrecorded_gate>"
        return gate(repo, os.path.join(repo, "plans", "p-plan.md"))

    def stop(repo):
        e = dict(env0, CURSOR_PLUGIN_ROOT=out)
        payload = {"hook_event_name": "stop", "status": "completed", "cursor_version": "x",
                   "conversation_id": "c-%s" % os.path.basename(repo),
                   "workspace_roots": [repo]}
        r = subprocess.run(["sh", "-c", '"${CURSOR_PLUGIN_ROOT}/hooks/plan-continue.sh"'],
                           cwd=repo, input=json.dumps(payload), capture_output=True, text=True,
                           env=e)
        try:
            return r.returncode, json.loads(r.stdout or "{}"), r.stderr
        except ValueError:
            return r.returncode, {"unparsed": r.stdout}, r.stderr

    # ---- unrecorded_gate()
    got = ask(mkrepo("complete", "stage-complete"))
    check(got == "1", "phase stage-complete with no Stage 1 green commit answers stage 1", got)
    got = ask(mkrepo("closeout", "closeout"))
    check(got == "1", "phase closeout with no Stage 1 green commit answers stage 1", got)
    got = ask(mkrepo("ticked", "task", tick="x"))
    check(got == "1", "the stage's gate boxes ticked with no Stage 1 green commit answer stage 1",
          got)
    got = ask(mkrepo("open", "task"))
    check(got is None, "a stage still being worked, nothing ticked, answers None", got)
    for ph in ("blocked", "handoff"):
        got = ask(mkrepo("stop-" + ph, ph, tick="x"))
        check(got is None, f"phase {ph} answers None even with the gate ticked", got)
    got = ask(mkrepo("green", "stage-complete", tick="x", green=True))
    check(got is None, "a Stage 1 green commit in HEAD's history answers None", got)

    # ---- the stop hook, end to end
    for name, phase in (("hook-complete", "stage-complete"), ("hook-closeout", "closeout")):
        rc, ans, err = stop(mkrepo(name, phase, tick="x"))
        msg = ans.get("followup_message", "")
        check(rc == 0 and "Stage 1 green" in msg and "Run the gate now" in msg,
              f"the stop hook holds phase {phase} with no Stage 1 green commit and says to run "
              "the gate", (rc, ans, err))
    rc, ans, err = stop(mkrepo("hook-green", "stage-complete", tick="x", green=True))
    check(rc == 0 and ans == {}, "with the Stage 1 green commit the stop hook lets the turn end",
          (rc, ans, err))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
