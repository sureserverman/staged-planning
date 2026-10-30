#!/usr/bin/env bash
# dispatch-log.sh — Claude Code hook (PreToolUse matcher Agent|Task, SubagentStart,
# SubagentStop): log every agent dispatch, start and stop of a plan run.
#
# WHY. A gate report's review line says which reviews were dispatched, and on its
# own that line is a self-report.
# This hook gathers; review-ledger-check.py decides: at each gate it
# compares the claimed reviews with the `dispatch` lines here, and at close-out and
# a handoff it lists agents with a `start` and no `stop`.
#
# INERT UNLESS A PLAN IS IN FLIGHT. It runs on every Agent call of every user who
# enables the plugin, so it does nothing — no Python, no write — unless
# $CLAUDE_PROJECT_DIR/.claude/plan-progress.json, or the main worktree's (below), exists.
# A `.claude` or log that is a symlink is never written through.
#
# ONE LINE PER EVENT, appended to $CLAUDE_PROJECT_DIR/.claude/dispatch-log.jsonl:
#   {"ts", "event": "dispatch", "session_id", "subagent_type", "description"}
#   {"ts", "event": "start"|"stop", "session_id", "agent_type", "agent_id"}
# PreToolUse does not carry the agent id of the launch it precedes, so a
# dispatch and its start are matched by type, not by id.
#
# IT NEVER BLOCKS. Every error exits 0 with empty stdout: a hook's stdout can be
# read as a decision, and a dispatch must never fail because logging did.
#
# IT STEPS ASIDE UNDER CURSOR. cursor-agent runs a Claude Code plugin's hooks too, and
# its payload carries a top-level `cursor_version` key. The Cursor build of this plugin
# logs its own dispatches, so a payload with that key is left alone: exit 0, no line.
#
# A LINKED WORKTREE. .claude/plan-progress.json is git-ignored, so each worktree has its
# own. With no run in flight in $CLAUDE_PROJECT_DIR (no state, or a finished run), the run
# is the main worktree's — the parent of the common git directory when that is named `.git`
# (git-worktree(1)) — and the line goes to the main worktree's log.
D="${CLAUDE_PROJECT_DIR:-}"
logs_here() {  # $1 = worktree: a state file to read, and a log that is not a symlink
    [ -d "$1/.claude" ] && [ ! -L "$1/.claude" ] \
        && [ -f "$1/.claude/plan-progress.json" ] && [ ! -L "$1/.claude/dispatch-log.jsonl" ]
}
M=""
if [ -n "$D" ]; then
    M="$(git -C "$D" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
    case "$M" in */.git) M="${M%/.git}" ;; *) M="" ;; esac
    { [ -n "$M" ] && [ "$M" != "$D" ] && logs_here "$M"; } || M=""
fi
[ -n "$D" ] && { logs_here "$D" || [ -n "$M" ]; } \
    || { cat >/dev/null 2>&1; exit 0; }  # drain stdin: the caller's write must not hit EPIPE
DISPATCH_HOOKS="${BASH_SOURCE[0]%/*}" \
DISPATCH_REPO="$D" DISPATCH_MAIN="$M" python3 -I -c '
import datetime, importlib.util, json, os, sys
from pathlib import Path
try:
    p = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or "cursor_version" in p:
    sys.exit(0)
try:
    spec = importlib.util.spec_from_file_location("dispatch_state_reader",
        Path(os.environ["DISPATCH_HOOKS"]) / "plan_continue_classify.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    root = Path(os.environ["DISPATCH_REPO"])
    state = reader.read_state(root)
    if isinstance(state, dict) and state.get("state_status") == "state_error":
        sys.exit(0)
    if (state is None or reader.finished(state, root)) and os.environ["DISPATCH_MAIN"]:
        root = Path(os.environ["DISPATCH_MAIN"])
        state = reader.read_state(root)
    if not isinstance(state, dict) or state.get("state_status") == "state_error":
        sys.exit(0)
    if reader.finished(state, root):
        sys.exit(0)
except Exception:
    sys.exit(0)
claude, log = root / ".claude", root / ".claude" / "dispatch-log.jsonl"
if not claude.is_dir() or claude.is_symlink() or log.is_symlink():
    sys.exit(0)
ev = p.get("hook_event_name")
line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "session_id": p.get("session_id")}
if ev == "PreToolUse" and p.get("tool_name") in ("Agent", "Task"):
    ti = p.get("tool_input")
    if not isinstance(ti, dict):
        sys.exit(0)
    line.update(event="dispatch", subagent_type=ti.get("subagent_type") or "general-purpose",
                description=ti.get("description"))
elif ev in ("SubagentStart", "SubagentStop") and p.get("agent_id"):
    line.update(event="start" if ev == "SubagentStart" else "stop",
                agent_type=p.get("agent_type"), agent_id=p.get("agent_id"))
else:
    sys.exit(0)
fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "a") as fh:
    fh.write(json.dumps(line) + "\n")
' >/dev/null 2>&1
exit 0
