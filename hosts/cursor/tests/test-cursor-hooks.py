#!/usr/bin/env python3
"""The Cursor hooks and their installer, run as Cursor runs them: a JSON payload on stdin,
the plugin's own folder as the working directory, except for stop, which Cursor runs from
the workspace root through a shell with CURSOR_PLUGIN_ROOT set (Cursor probe, host.yaml).

Each case builds the Cursor plugin into a scratch dir and drives its hooks against
throwaway repos. Every payload carries `cursor_version`, as Cursor's do: these are the
hooks that answer under Cursor, so none of them may step aside on it.

  hooks.json         one route per event: stop, preToolUse(Task), beforeShellExecution;
                     the stop command, run from a workspace as Cursor runs it, reaches the
                     plugin's plan-continue.sh and never a same-named script in the repo
  dispatch-log.sh    a Task launch in a plan run logs one dispatch line at the repo root
                     (found from workspace_roots) with tool_input.subagent_type as the
                     agent, and an empty agent when the field is absent; a second run of
                     the same call adds none,
                     and every exit prints the explicit allow; inert with no plan in flight
  plan-continue.sh   a stop in flight answers with a followup_message; an aborted loop, a
                     recorded stop, no state and the kill switch print {}; the loop guard
                     releases after CURSOR_PLAN_CONTINUE_MAX continuations
  commit-gate.sh     while a plan is in flight, git is denied until the shim is installed,
                     then allowed; hooksPath and the installer's --remove are denied; with no
                     plan in flight a `Stage N green` commit is denied and everything else is
                     allowed
  git-ref-gate.sh    a task commit carries code only and passes; a `Stage N green` commit
                     with no records is refused for every claim of every task of stage N
  hooks-install.py   --dry-run writes nothing and names no event; --install removes only the
                     planning entries an older installer left, backs the file up, and writes
                     no user entry
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
GITENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[:600].replace("\n", "\n     | "))


tmp = tempfile.mkdtemp(prefix="cursor-hooks-test-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "cursor",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    hooks = os.path.join(out, "hooks")
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith(("CURSOR_", "CLAUDE_", "GIT_"))}
    env0.update(GITENV)

    def run(script, payload, env=None):
        e = dict(env0, **(env or {}))
        r = subprocess.run(["bash", os.path.join(hooks, script)], cwd=out,
                           input=json.dumps(payload) if not isinstance(payload, str) else payload,
                           capture_output=True, text=True, env=e)
        return r

    def git(repo, *a):
        return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True,
                              env=dict(env0))

    def mkrepo(name, plan=True, phase="task"):
        repo = os.path.join(tmp, name)
        os.makedirs(os.path.join(repo, ".claude"))
        os.makedirs(os.path.join(repo, "sub"))
        subprocess.run(["git", "init", "-q", "--template=", "-b", "main", repo], check=True,
                       env=dict(env0))
        if plan:
            write_state(repo, phase)
        return repo

    def write_state(repo, phase="task", age_h=0.0, task="1.1"):
        ts = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=age_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(repo, ".claude", "plan-progress.json"), "w") as fh:
            json.dump({"plan": "plans/p-plan.md", "phase": phase, "stage": 1, "task": task,
                       "updated": ts}, fh)

    # ---- hooks.json
    with open(os.path.join(hooks, "hooks.json")) as fh:
        hj = json.load(fh)
    want = {"stop": "plan-continue.sh", "preToolUse": "dispatch-log.sh",
            "beforeShellExecution": "commit-gate.sh"}
    got = {ev: [os.path.basename(e["command"].strip('"')) for e in es] for ev, es in hj["hooks"].items()}
    check(hj.get("version") == 1 and got == {k: [v] for k, v in want.items()}
          and hj["hooks"]["preToolUse"][0].get("matcher") == "Task"
          and hj["hooks"]["stop"][0].get("loop_limit") == 25,
          "hooks.json wires each event once, preToolUse on Task, stop with loop_limit 25", got)
    for s in want.values():
        check(os.access(os.path.join(hooks, s), os.X_OK), f"{s} ships executable")

    # ---- dispatch-log.sh
    repo = mkrepo("dl")

    def task_payload(root, tid="call-1"):
        return {"hook_event_name": "preToolUse", "tool_name": "Task", "cursor_version": "x",
                "conversation_id": "c1", "session_id": "c1", "tool_use_id": tid,
                "workspace_roots": [root],
                "tool_input": {"subagent_type": "code-reviewer", "model": "inherit",
                               "description": "Review Stage 1", "prompt": "p"}}

    log = os.path.join(repo, ".claude", "dispatch-log.jsonl")

    def lines():
        return open(log).read().splitlines() if os.path.exists(log) else []

    r = run("dispatch-log.sh", task_payload(os.path.join(repo, "sub")))
    rows = [json.loads(x) for x in lines()]
    check(r.returncode == 0 and json.loads(r.stdout) == {"permission": "allow"}
          and len(rows) == 1 and rows[0]["event"] == "dispatch"
          and rows[0]["subagent_type"] == "code-reviewer"
          and rows[0]["tool_use_id"] == "call-1",
          "a Task launch from a subfolder logs one dispatch line at the repo root, and allows",
          (r.stdout, r.stderr, rows))
    run("dispatch-log.sh", task_payload(repo))
    check(len(lines()) == 1, "a second run of the same call (same tool_use_id) adds no line",
          lines())
    run("dispatch-log.sh", task_payload(repo, "call-2"))
    check(len(lines()) == 2, "a second launch logs a second line", lines())
    bare = task_payload(repo, "call-3")
    del bare["tool_input"]["subagent_type"]
    run("dispatch-log.sh", bare)
    rows = [json.loads(x) for x in lines()]
    check(len(rows) == 3 and rows[2]["subagent_type"] == "",
          "a Task call with no subagent_type logs an empty agent, never a guessed one", rows[-1:])
    shell = {"hook_event_name": "preToolUse", "tool_name": "Shell", "cursor_version": "x",
             "workspace_roots": [repo], "tool_input": {"command": "ls"}}
    r = run("dispatch-log.sh", shell)
    check(len(lines()) == 3 and json.loads(r.stdout) == {"permission": "allow"},
          "a non-Task call is not logged, and is allowed")
    idle = mkrepo("dl-idle", plan=False)
    r = run("dispatch-log.sh", task_payload(idle))
    check(not os.path.exists(os.path.join(idle, ".claude", "dispatch-log.jsonl"))
          and json.loads(r.stdout) == {"permission": "allow"},
          "with no plan in flight nothing is written, and the call is allowed")
    r = run("dispatch-log.sh", "not json")
    check(r.returncode == 0 and json.loads(r.stdout) == {"permission": "allow"},
          "a payload that is not JSON is allowed")

    # ---- plan-continue.sh
    repo = mkrepo("pc")

    def stop(root, status="completed", conv="s1", env=None):
        p = {"hook_event_name": "stop", "cursor_version": "x", "conversation_id": conv,
             "session_id": conv, "status": status, "loop_count": 0,
             "workspace_roots": [root]}
        r = run("plan-continue.sh", p, env)
        try:
            return r.returncode, json.loads(r.stdout)
        except ValueError:
            return r.returncode, {"_raw": r.stdout}

    rc, d = stop(os.path.join(repo, "sub"), conv="a")
    check(rc == 0 and "Plan execution is still in flight" in d.get("followup_message", ""),
          "a stop while a plan is in flight answers with a followup_message", d)

    # Cursor runs a plugin's stop command through a shell from the workspace root, with
    # CURSOR_PLUGIN_ROOT set to the plugin folder. The workspace holds a decoy at the
    # plugin-relative path: a command that resolves against the working directory runs it.
    ws = mkrepo("pc-ws")
    os.makedirs(os.path.join(ws, "hooks"))
    decoy = os.path.join(ws, "hooks", "plan-continue.sh")
    with open(decoy, "w") as fh:
        fh.write("#!/bin/sh\ncat >/dev/null\necho '{\"followup_message\": \"DECOY\"}'\n")
    os.chmod(decoy, 0o755)
    cmd = hj["hooks"]["stop"][0]["command"]
    r = subprocess.run(["sh", "-c", cmd], cwd=ws, capture_output=True, text=True,
                       input=json.dumps({"hook_event_name": "stop", "cursor_version": "x",
                                         "conversation_id": "ws", "status": "completed",
                                         "loop_count": 0, "workspace_roots": [ws]}),
                       env=dict(env0, CURSOR_PLUGIN_ROOT=out, CURSOR_PROJECT_DIR=ws))
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"_raw": r.stdout}
    check(r.returncode == 0
          and "Plan execution is still in flight" in d.get("followup_message", ""),
          "the stop command run from the workspace root finds the plugin's plan-continue.sh",
          (cmd, r.returncode, r.stdout, r.stderr))
    rc, d = stop(repo, status="aborted", conv="b")
    check(rc == 0 and d == {}, "an aborted agent loop is not resumed: {}", d)
    rc, d = stop(repo, conv="c", env={"CURSOR_PLAN_CONTINUE": "0"})
    check(rc == 0 and d == {}, "CURSOR_PLAN_CONTINUE=0 switches it off: {}", d)
    for phase in ("blocked", "closeout", "handoff"):
        write_state(repo, phase)
        rc, d = stop(repo, conv="d-" + phase)
        check(rc == 0 and d == {}, f"phase {phase} lets the turn end: {{}}", d)
    write_state(repo, "task", age_h=13)
    rc, d = stop(repo, conv="e")
    check(rc == 0 and d == {}, "stale state lets the turn end: {}", d)
    os.remove(os.path.join(repo, ".claude", "plan-progress.json"))
    rc, d = stop(repo, conv="f")
    check(rc == 0 and d == {}, "no state file lets the turn end: {}", d)
    write_state(repo, "gate")
    seen = [stop(repo, conv="loop", env={"CURSOR_PLAN_CONTINUE_MAX": "2"})[1] for _ in range(3)]
    check(all("followup_message" in x for x in seen[:2]) and seen[2] == {},
          "the loop guard releases after CURSOR_PLAN_CONTINUE_MAX continuations", seen)

    # ---- commit-gate.sh and hooks-install.py --repo
    repo = mkrepo("cg")
    other = mkrepo("cg-idle", plan=False)
    installer = os.path.join(out, "scripts", "hooks-install.py")

    def gate(cmd, root):
        p = {"hook_event_name": "beforeShellExecution", "cursor_version": "x", "command": cmd,
             "cwd": root, "workspace_roots": [root]}
        r = run("commit-gate.sh", p)
        try:
            return json.loads(r.stdout).get("permission"), r
        except ValueError:
            return None, r

    perm, r = gate("git status", repo)
    check(perm == "deny" and "--install --repo" in json.loads(r.stdout)["agent_message"],
          "in flight with no shim, git is denied, naming the install command", r.stdout)
    check(gate("git status", other)[0] == "allow", "with no plan in flight git is allowed")
    perm, r = gate('git commit -q -m "Stage 1 green"', other)
    check(perm == "deny" and "plan-state.py init" in json.loads(r.stdout).get("agent_message", ""),
          "with no plan in flight, a Stage N green commit is denied, naming plan-state.py init",
          r.stdout)
    check(gate('git commit -q -m "Stage 1 handoff"', other)[0] == "allow",
          "with no plan in flight, a commit that is not Stage N green is allowed")
    check(gate("ls -la", repo)[0] == "allow", "a command that is not git is allowed")
    ir = subprocess.run([sys.executable, installer, "--install", "--repo", repo],
                        capture_output=True, text=True, env=env0)
    check(ir.returncode == 0 and "installed" in ir.stdout, "--install --repo writes the shim",
          ir.stdout + ir.stderr)
    check(gate("git status", repo)[0] == "allow", "with the shim installed git is allowed")
    for cmd in ("git -c core.hooksPath=/dev/null commit -m x",
                f"python3 {installer} --remove --repo {repo}",
                "rm .git/hooks/reference-transaction"):
        check(gate(cmd, repo)[0] == "deny", f"denied in flight: {cmd[:60]}")
    r = run("commit-gate.sh", "not json")
    check(r.returncode == 0 and json.loads(r.stdout) == {"permission": "allow"},
          "a payload that is not JSON is allowed", r.stdout)

    # ---- git-ref-gate.sh through the installed shim
    os.makedirs(os.path.join(repo, "plans"))
    with open(os.path.join(repo, "plans", "p-plan.md"), "w") as fh:
        fh.write("# Plan\n\n## Stage 1: s\n\n"
                 "### Task 1.1: calc\n- **Status:** [ ]\n- **Test:** `python3 t.py` — add "
                 "returns the sum (red if add subtracts); add stays a plain function\n\n"
                 "### Task 1.2: calc again\n- **Status:** [ ]\n- **Test:** `python3 t.py` — "
                 "add keeps its sign (red if add drops the sign)\n\n"
                 "### Stage 1 Gate\n- [ ] green\n\n## Stage 2: t\n\n"
                 "### Task 2.1: other\n- **Status:** [ ]\n- **Test:** `true` — passes\n")
    with open(os.path.join(repo, "calc.py"), "w") as fh:
        fh.write("def add(a, b):\n    return a + b\n")
    git(repo, "add", "-A")
    c = git(repo, "commit", "-q", "-m", "Task 1.1: calc")
    check(c.returncode == 0, "a task commit carries code only and is not gated", c.stderr)
    with open(os.path.join(repo, "calc.py"), "a") as fh:
        fh.write("# done\n")
    git(repo, "add", "-A")
    c = git(repo, "commit", "-q", "-m", "Stage 1 green")
    check(c.returncode != 0 and "Task 1.1 claim 1: no record" in c.stderr
          and "Task 1.1 claim 2: no record" in c.stderr
          and "Task 1.2 claim 1: no record" in c.stderr and "Task 2.1" not in c.stderr,
          "a Stage 1 green commit with no records is refused for every claim of every task "
          "of stage 1, and only stage 1", c.stderr)
    state = os.path.join(repo, ".claude", "plan-progress.json")
    os.rename(state, state + ".off")
    c = git(repo, "commit", "-q", "-m", "Stage 1 green")
    check(c.returncode != 0 and "plan-state.py init" in c.stderr,
          "with no execution state, the ref hook refuses a Stage N green commit", c.stderr)
    os.rename(state + ".off", state)

    # ---- hooks-install.py user route
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    r = subprocess.run([sys.executable, installer, "--dry-run", "--home", home],
                       capture_output=True, text=True, env=env0)
    events = ("stop", "preToolUse", "beforeShellExecution", "subagentStart", "subagentStop")
    check(r.returncode == 0 and not any(ev in r.stdout for ev in events)
          and not os.path.exists(os.path.join(home, ".cursor")),
          "--dry-run in an empty home writes nothing and names no event", r.stdout)
    cfg = os.path.join(home, ".cursor", "hooks.json")
    os.makedirs(os.path.dirname(cfg))
    old = os.path.join(home, ".cursor", "plugins", "local", "planning", "hooks")
    doc = {"version": 1, "custom": True, "hooks": {
        "stop": [{"type": "command", "command": os.path.join(old, "plan-continue.sh")},
                 {"type": "command", "command": "/opt/vendor/hooks/plan-continue.sh"}],
        "beforeShellExecution": [{"type": "command",
                                  "command": os.path.join(old, "commit-gate.sh")}],
        "afterFileEdit": [{"type": "command", "command": "/opt/mine.sh"}]}}
    with open(cfg, "w") as fh:
        json.dump(doc, fh, indent=4)
    os.chmod(cfg, 0o644)
    st = subprocess.run([sys.executable, installer, "--status", "--home", home],
                        capture_output=True, text=True, env=env0)
    check(st.returncode == 1 and "2 planning entries" in st.stdout,
          "--status names the leftover entries and exits 1", st.stdout)
    r = subprocess.run([sys.executable, installer, "--install", "--home", home],
                       capture_output=True, text=True, env=env0)
    with open(cfg) as fh:
        after = json.load(fh)
    check(r.returncode == 0 and after["custom"] is True
          and after["hooks"] == {"stop": [doc["hooks"]["stop"][1]],
                                 "afterFileEdit": doc["hooks"]["afterFileEdit"]}
          and oct(os.stat(cfg).st_mode & 0o777) == oct(0o644)
          and any(n.startswith("hooks.json.bak-") for n in os.listdir(os.path.dirname(cfg))),
          "--install removes only our leftover entries, keeps the rest and the mode, backs up",
          (r.stdout, r.stderr, after))
    st = subprocess.run([sys.executable, installer, "--status", "--home", home],
                        capture_output=True, text=True, env=env0)
    check(st.returncode == 0 and all(f"plugin route — {s} on " in st.stdout for s in
                                     ("plan-continue.sh", "commit-gate.sh", "dispatch-log.sh")),
          "--status reads the built hooks.json's quoted commands: all three wired, exit 0",
          st.stdout)
    with open(cfg, "w") as fh:
        fh.write("{not json")
    r = subprocess.run([sys.executable, installer, "--install", "--home", home],
                       capture_output=True, text=True, env=env0)
    check(r.returncode == 1 and open(cfg).read() == "{not json",
          "a hooks.json it cannot parse exits 1 untouched", r.stderr)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print(f"{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
