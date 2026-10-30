#!/usr/bin/env bash
# dispatch-log.sh — Cursor hook (preToolUse, matcher Task): log every subagent dispatch of
# a plan run. The Cursor fork of the plugin's dispatch-log.sh.
#
# WHY. A gate report's review line says which reviews were dispatched, and on its own
# that line is a self-report. This hook gathers; review-ledger-check.py decides: at each
# gate it compares the claimed reviews with the `dispatch` lines here.
#
# WHAT DIFFERS ON CURSOR, AND WHY (probe facts in hosts/cursor/host.yaml, probe_date).
#   * The event. Cursor never sent subagentStart or subagentStop in any mode the probe
#     ran, so this hook is wired on preToolUse with matcher Task, and writes `dispatch`
#     lines only. Cursor spells the event `preToolUse`.
#   * The answer. preToolUse is a permission hook: every exit prints
#     {"permission":"allow"} and nothing else reaches stdout, so logging can never block
#     a launch.
#   * The project folder. This hook (preToolUse, matcher Task) runs with the plugin's own folder as
#     its working directory, so the folder is the git top level of the payload's first
#     `workspace_roots` entry (CURSOR_PROJECT_DIR when the payload has none).
#   * The agent. Cursor's Task call names the agent in tool_input.subagent_type: the
#     custom agent's own name (`code-reviewer`), or a built-in (`generalPurpose`,
#     `explore`). A call without it logs an empty name, so no review is credited to an
#     agent the call never named.
#   * One line per call. A Task call carries a `tool_use_id`. With an entry for this hook
#     left in ~/.cursor/hooks.json beside the plugin's, Cursor runs it twice for one call,
#     and review-ledger-check.py counts one dispatch line per claimed review. So a
#     dispatch line records the id, and under an exclusive lock on the log a second write
#     of the same id is dropped. Two launches have two ids and log two lines.
#
# INERT UNLESS A PLAN IS IN FLIGHT. It writes nothing unless the project's
# .claude/plan-progress.json (or, in a worktree with none, the one other worktree's run)
# names a plan that is not finished. A `.claude` or log that is a symlink is never
# written through.
#
# ONE LINE PER DISPATCH, appended to <project>/.claude/dispatch-log.jsonl:
#   {"ts", "event": "dispatch", "session_id", "subagent_type", "description", "tool_use_id"}
allow() { printf '{"permission":"allow"}\n'; exit 0; }
# Drain stdin when there is no python3: the caller's write must not hit EPIPE.
command -v python3 >/dev/null 2>&1 || { cat >/dev/null 2>&1; allow; }
DISPATCH_HOOKS="${BASH_SOURCE[0]%/*}" python3 -I -c '
import datetime, fcntl, importlib.util, json, os, subprocess, sys
from pathlib import Path
try:
    p = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
if not isinstance(p, dict) or p.get("hook_event_name") not in ("preToolUse", "PreToolUse") \
        or p.get("tool_name") != "Task" or not isinstance(p.get("tool_input"), dict):
    sys.exit(0)
roots = p.get("workspace_roots")
start = roots[0] if isinstance(roots, list) and roots and isinstance(roots[0], str) \
    else os.environ.get("CURSOR_PROJECT_DIR", "")
if not start or not os.path.isdir(start):
    sys.exit(0)
r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                   capture_output=True, text=True)
repo = Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else Path(start)


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
ti = p["tool_input"]
line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "event": "dispatch", "session_id": p.get("session_id") or p.get("conversation_id"),
        "subagent_type": ti.get("subagent_type") if isinstance(ti.get("subagent_type"), str) else "",
        "description": ti.get("description")}
if isinstance(p.get("tool_use_id"), str) and p["tool_use_id"]:
    line["tool_use_id"] = p["tool_use_id"]
fd = os.open(log, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "a+") as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    if "tool_use_id" in line:
        fh.seek(0)
        for old in fh:
            try:
                o = json.loads(old)
            except ValueError:
                continue
            if isinstance(o, dict) and o.get("event") == "dispatch" \
                    and o.get("tool_use_id") == line["tool_use_id"]:
                sys.exit(0)
    fh.write(json.dumps(line) + "\n")
' >/dev/null 2>&1
allow
