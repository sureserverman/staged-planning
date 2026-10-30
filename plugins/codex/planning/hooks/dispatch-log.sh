#!/usr/bin/env bash
# dispatch-log.sh — Codex hook (SubagentStart, SubagentStop): log every agent start and
# stop of a plan run. The Codex fork of the plugin's dispatch-log.sh.
#
# WHY. A gate report's review line says which reviews were spawned, and on its own that
# line is a self-report. This hook gathers; review-ledger-check.py decides: at each gate
# it matches each claimed review against a `start` line of the claimed role, and at
# close-out and a handoff it lists agents with a `start` and no `stop`.
#
# WHAT DIFFERS ON CODEX, AND WHY.
#   * The project folder. Codex sets no project-folder variable in a hook's environment,
#     so the folder is the git top level of the payload's `cwd`. A session started in a
#     subdirectory still logs at the repo root, and an inherited variable never points the
#     log at another project.
#   * No `dispatch` line. Codex's spawn call carries no description or agent type that a
#     tool-use hook could log, so this hook is wired to SubagentStart and SubagentStop
#     only, whose payloads carry the role (`agent_type`) and the agent's id.
#
# INERT UNLESS A PLAN IS IN FLIGHT. It writes nothing unless the project's
# .claude/plan-progress.json (or, in a worktree with none, the one run among the others)
# exists. A `.claude` or log that is a symlink is never written through.
#
# ONE LINE PER EVENT, appended to <project>/.claude/dispatch-log.jsonl:
#   {"ts", "event": "start"|"stop", "session_id", "agent_type", "agent_id"}
#
# IT NEVER BLOCKS. Every error exits 0 with empty stdout: a hook's stdout can be
# read as a decision, and an agent must never fail because logging did.
# One Python process reads the payload from stdin once: an environment string is capped
# at 128 KiB, and SubagentStop's payload carries the agent's last message.
DISPATCH_HOOKS="${BASH_SOURCE[0]%/*}" python3 -I -c '
import datetime, importlib.util, json, os, subprocess, sys
from pathlib import Path
try:
    p = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or not isinstance(p.get("cwd"), str) or not os.path.isdir(p["cwd"]):
    sys.exit(0)
ev = p.get("hook_event_name")
if ev not in ("SubagentStart", "SubagentStop") or not isinstance(p.get("agent_id"), str) \
        or not p["agent_id"]:
    sys.exit(0)
r = subprocess.run(["git", "-C", p["cwd"], "rev-parse", "--show-toplevel"],
                   capture_output=True, text=True)
if r.returncode != 0 or not r.stdout.strip():
    sys.exit(0)
repo = Path(r.stdout.strip())


def logs_here(root):
    claude, log = root / ".claude", root / ".claude" / "dispatch-log.jsonl"
    return claude.is_dir() and not claude.is_symlink() \
        and (claude / "plan-progress.json").is_file() and not log.is_symlink()


# .claude/plan-progress.json is git-ignored, so each worktree has its own. With no run in
# flight here (no state, or a finished run), the line goes to the log of the one run in
# flight among the others, and with two or more to neither: a line in the log of the wrong run
# would pass the review check of that run.
try:
    spec = importlib.util.spec_from_file_location("dispatch_state_reader",
        Path(os.environ["DISPATCH_HOOKS"]) / "plan_continue_classify.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    root = repo
    state = reader.read_state(repo) if logs_here(repo) else None
    if isinstance(state, dict) and state.get("state_status") == "state_error":
        sys.exit(0)
    if state is None or reader.finished(state, repo):
        runs, _ = reader.other_runs(repo)
        if len(runs) != 1 or not logs_here(runs[0][0]):
            sys.exit(0)
        root, state = runs[0]
    if not isinstance(state, dict) or state.get("state_status") == "state_error":
        sys.exit(0)
    if reader.finished(state, root):
        sys.exit(0)
except Exception:
    sys.exit(0)
log = root / ".claude" / "dispatch-log.jsonl"
role = p.get("agent_type")
line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "session_id": p.get("session_id") if isinstance(p.get("session_id"), str) else None,
        "event": "start" if ev == "SubagentStart" else "stop",
        "agent_type": role if isinstance(role, str) else None, "agent_id": p["agent_id"]}
fd = os.open(str(log), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "a") as fh:
    fh.write(json.dumps(line) + "\n")
' >/dev/null 2>&1
exit 0
