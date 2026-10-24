#!/usr/bin/env python3
"""The Codex hook forks, run as Codex runs them: a JSON payload on stdin.

Each case copies the hook and its shared module from the Codex build into a scratch dir,
makes a throwaway repo with a legacy plan state file, and reads what the hook prints.

  plan-continue.sh (Stop), in a session opted in with CODEX_PLAN_CONTINUE=1
    opt-in      unset, the hook says nothing, so another session in the repo is left alone
    continues   a final message while a plan is in flight is blocked with a reason: a
                plain wait, no message, and an `ACTION NEEDED:` block with no recorded
                blocker (on a legacy file and on an owned v2 run alike)
    stops       a recorded stop: phase blocked, closeout or handoff on a legacy file, a
                set-blocker on an owned run; a RESUME HERE block with its `reason:`
                line; stale state; no state file
    sends back  a RESUME HERE block with no `reason:` line, to run context-usage.py
    loop guard  after CODEX_PLAN_CONTINUE_MAX continuations at one key it lets the turn
                end, naming the Codex switches
    fails open  a payload that is not JSON, or a missing classifier module, ends the turn
  dispatch-log.sh (SubagentStart/SubagentStop)
    logs        a start from a subdirectory at the repo root, with role and id, a stop as
                a stop, and a payload over 128 KiB whole
    inert       nothing written with no plan in flight, or through a symlinked .claude;
                a non-string agent id is not logged
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


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-hooks-test-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    hooks = os.path.join(out, "hooks")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, ".claude"))
    os.makedirs(os.path.join(repo, "sub"))
    subprocess.run(["git", "init", "-q", "--template=", repo], check=True)
    state_path = os.path.join(repo, ".claude", "plan-progress.json")

    def state(phase="task", age_h=0.0, task="2.1"):
        ts = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=age_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(state_path, "w") as fh:
            json.dump({"plan": "docs/plans/p-plan.md", "phase": phase, "stage": 2,
                       "task": task, "updated": ts}, fh)

    def stop(message, env=None, session="s1"):
        payload = {"hook_event_name": "Stop", "cwd": os.path.join(repo, "sub"),
                   "session_id": session, "stop_hook_active": False}
        if message is not None:
            payload["last_assistant_message"] = message
        e = {k: v for k, v in os.environ.items() if not k.startswith("CODEX_PLAN_CONTINUE")}
        e["CODEX_PLAN_CONTINUE"] = "1"
        e.update(env or {})
        e = {k: v for k, v in e.items() if v is not None}
        r = subprocess.run(["bash", os.path.join(hooks, "plan-continue.sh")],
                           input=json.dumps(payload), capture_output=True, text=True, env=e)
        doc = json.loads(r.stdout) if r.stdout.strip() else {}
        return r.returncode, doc

    state()
    rc, d = stop("Waiting on the reviewer agents.", session="a")
    check(rc == 0 and d.get("decision") == "block" and "wait_agent" in d.get("reason", ""),
          "a final wait while in flight continues, telling the run to wait inside the turn")
    rc, d = stop(None, session="b")
    check(d.get("decision") == "block", "a stop with no last message continues")
    rc, d = stop("Report.\n\nACTION NEEDED: pick option 1 or 2.", session="c")
    check(d.get("decision") == "block" and "set-blocker" in d.get("reason", ""),
          "ACTION NEEDED with no recorded blocker continues, naming set-blocker")
    rc, d = stop("**RESUME HERE**\nreason: rule context: 61% > 50%\n", session="d")
    check(d.get("decision") != "block", "a RESUME HERE with its reason: line lets it end")
    rc, d = stop("**RESUME HERE**\nnext: Task 3.1\n", session="e")
    check(d.get("decision") == "block" and "context-usage.py" in d.get("reason", ""),
          "a RESUME HERE without reason: is sent back to run context-usage.py")
    rc, d = stop("Next is Task 2.2.", env={"CODEX_PLAN_CONTINUE": None}, session="f")
    check(rc == 0 and d == {}, "a session not opted in is left alone")
    for ph in ("blocked", "closeout", "handoff"):
        state(phase=ph)
        rc, d = stop("Next is Task 2.2.", session="g" + ph)
        check(d.get("decision") != "block", f"phase {ph} lets the turn end")
    state(age_h=13)
    rc, d = stop("Next is Task 2.2.", session="h")
    check(d.get("decision") != "block", "stale state lets the turn end")
    os.remove(state_path)
    rc, d = stop("Next is Task 2.2.", session="i")
    check(rc == 0 and d == {}, "no plan in flight: the hook says nothing")
    state(task="2.9")
    decisions = [stop("Next is Task 2.9.", env={"CODEX_PLAN_CONTINUE_MAX": "2"},
                      session="loop")[1] for _ in range(3)]
    check([x.get("decision") for x in decisions[:2]] == ["block", "block"]
          and decisions[2].get("decision") != "block"
          and "CODEX_PLAN_CONTINUE_MAX" in decisions[2].get("systemMessage", ""),
          "the loop guard ends the loop at the cap and names the Codex switches")

    # Fail open: a payload that is not JSON, and a hook whose shared module is missing.
    state()
    e = dict(os.environ, CODEX_PLAN_CONTINUE="1")
    r = subprocess.run(["bash", os.path.join(hooks, "plan-continue.sh")], input="{not json",
                       capture_output=True, text=True, env=e)
    check(r.returncode == 0 and r.stdout == "", "a payload that is not JSON lets the turn end")
    bare = os.path.join(tmp, "bare-hooks")
    os.makedirs(bare)
    shutil.copy(os.path.join(hooks, "plan-continue.sh"), bare)
    r = subprocess.run(["bash", os.path.join(bare, "plan-continue.sh")], env=e,
                       input=json.dumps({"hook_event_name": "Stop", "cwd": repo,
                                         "last_assistant_message": "Next is Task 2.2."}),
                       capture_output=True, text=True)
    check(r.returncode == 0 and r.stdout == "", "a missing classifier module lets the turn end")

    # An owned (v2) run, made by the plugin's own plan-state.py.
    v2 = os.path.join(tmp, "v2")
    os.makedirs(v2)
    subprocess.run(["git", "init", "-q", "--template=", v2], check=True)
    subprocess.run(["git", "-C", v2, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "--allow-empty", "-qm", "base"], check=True)
    ps = os.path.join(out, "skills", "executing-plans", "scripts", "plan-state.py")

    def owned(op, payload, rev, opid):
        r = subprocess.run([sys.executable, ps, op, "--repo", v2, "--expected-revision",
                            str(rev), "--operation-id", opid], input=json.dumps(payload),
                           capture_output=True, text=True)
        doc = json.loads(r.stdout)
        assert doc.get("status") == "ok", (op, doc, r.stderr)
        return doc["revision"]

    rev = owned("init", {"plan": "fixture-plan.md", "scope": "fixture",
                         "source": "owner: execute the fixture plan"}, 0, "op-1")
    repo_saved, repo = repo, v2
    rc, d = stop("Report.\n\nACTION NEEDED: pick option 1 or 2.", session="v2a")
    check(d.get("decision") == "block", "owned run: ACTION NEEDED alone continues")
    owned("set-blocker", {"disposition": "awaiting_owner_decision", "prevented_operation":
                          "next stage", "evidence": "a decision only the owner can make",
                          "dependency": "owner instruction", "remaining_work": []}, rev, "op-2")
    rc, d = stop("Report.\n\nACTION NEEDED: pick option 1 or 2.", session="v2b")
    check(d.get("decision") != "block", "owned run: a recorded blocker lets the turn end")
    repo = repo_saved

    log = os.path.join(repo, ".claude", "dispatch-log.jsonl")

    def subagent(event, cwd):
        payload = {"hook_event_name": event, "cwd": cwd, "session_id": "s1",
                   "agent_type": "planning:code-reviewer", "agent_id": "ag-1"}
        return subprocess.run(["bash", os.path.join(hooks, "dispatch-log.sh")],
                              input=json.dumps(payload), capture_output=True, text=True)

    state()
    r = subagent("SubagentStart", os.path.join(repo, "sub"))
    with open(log) as fh:
        rows = [json.loads(line) for line in fh]
    check(r.returncode == 0 and r.stdout == "" and rows and rows[-1]["event"] == "start"
          and rows[-1]["agent_type"] == "planning:code-reviewer" and rows[-1]["agent_id"] == "ag-1",
          "a start from a subdirectory is logged at the repo root, with role and id")
    big = {"hook_event_name": "SubagentStop", "cwd": repo, "agent_id": "ag-1",
           "agent_type": "planning:code-reviewer", "last_assistant_message": "x" * 200_000}
    subprocess.run(["bash", os.path.join(hooks, "dispatch-log.sh")], input=json.dumps(big),
                   capture_output=True, text=True)
    bad = {"hook_event_name": "SubagentStart", "cwd": repo, "agent_id": {"a": 1}}
    subprocess.run(["bash", os.path.join(hooks, "dispatch-log.sh")], input=json.dumps(bad),
                   capture_output=True, text=True)
    with open(log) as fh:
        rows = [json.loads(line) for line in fh]
    check(len(rows) == 2 and rows[1]["event"] == "stop" and rows[1]["agent_id"] == "ag-1",
          "a stop over 128 KiB is logged whole, as a stop; a non-string id is not logged")
    os.remove(state_path)
    subagent("SubagentStop", repo)
    with open(log) as fh:
        check(len(fh.readlines()) == 2, "nothing is logged with no plan in flight")
    real = os.path.join(tmp, "elsewhere")
    os.makedirs(real)
    shutil.move(os.path.join(repo, ".claude"), os.path.join(real, ".claude"))
    os.symlink(os.path.join(real, ".claude"), os.path.join(repo, ".claude"))
    state()
    subagent("SubagentStop", repo)
    with open(os.path.join(real, ".claude", "dispatch-log.jsonl")) as fh:
        check(len(fh.readlines()) == 2, "nothing is written through a symlinked .claude")
finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
