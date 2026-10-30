#!/usr/bin/env bash
# Fixture suite for the dispatch-log hook — run directly (repo convention):
#
#     bash core/hooks/tests/test-dispatch-log.sh
#
# WHAT THIS SUITE IS REALLY GUARDING. hooks/dispatch-log.sh ships in the plugin's
# hooks.json, so it runs on EVERY Agent call and every subagent start and stop of
# every user who enables planning. It must write nothing unless a plan is in flight
# (.claude/plan-progress.json), and it must never block a dispatch: whatever goes
# wrong, it exits 0 with empty stdout. Inside a plan run it appends one JSON line per
# event to .claude/dispatch-log.jsonl, which review-ledger-check.py reads. The payload
# shapes below are the fields a `claude -p` run hands the hooks: PreToolUse carries
# tool_input.subagent_type and description;
# SubagentStart / SubagentStop carry agent_id and agent_type.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/../dispatch-log.sh"
# The Claude Code registration (hooks.json) is host-specific, so in this repo's source
# tree it lives in hosts/claude/add/hooks/; in a built plugin it sits beside this
# directory. Look beside first, then in the Claude layer — and fail if neither has it,
# rather than letting the registration checks below pass over nothing.
HOOKS_JSON="$HERE/../hooks.json"
[ -f "$HOOKS_JSON" ] || HOOKS_JSON="$HERE/../../../hosts/claude/add/hooks/hooks.json"
[ -f "$HOOKS_JSON" ] || { echo "FAIL: no hooks.json beside hooks/ or in hosts/claude/add/hooks/"; exit 1; }
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok    $1"; }
bad() { fail=$((fail+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && printf '        | %s\n' "${2:0:700}"; }

[ -f "$HOOK" ] || { echo "FAIL: $HOOK does not exist"; exit 1; }

mkrepo() {  # $1 = path [$2 = "plan" to put a plan in flight]
    mkdir -p "$1/.claude"
    if [ "${2:-}" = plan ]; then
        printf '{"plan": "%s", "phase": "task", "stage": 1, "task": "1.1"}\n' "$T/plan.md" \
            > "$1/.claude/plan-progress.json"
    fi
}
dispatch_payload() {  # $1 = subagent_type
    python3 -c 'import json,sys; print(json.dumps({"session_id": "sess-1", "transcript_path": "/x.jsonl", "cwd": "/x", "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"description": "Review Stage 1", "prompt": "review it", "subagent_type": sys.argv[1]}, "tool_use_id": "toolu_1"}))' "$1"
}
agent_payload() {  # $1 = SubagentStart|SubagentStop  $2 = agent_id  $3 = agent_type
    python3 -c 'import json,sys; print(json.dumps({"session_id": "sess-1", "transcript_path": "/x.jsonl", "cwd": "/x", "hook_event_name": sys.argv[1], "agent_id": sys.argv[2], "agent_type": sys.argv[3]}))' "$1" "$2" "$3"
}
hook() {  # $1 = repo; stdin payload. stdout -> $T/out, rc -> $T/rc (read it with rc_of)
    # Called at the end of a pipe, so it runs in a subshell: the rc goes through a file.
    CLAUDE_PROJECT_DIR="$1" bash "$HOOK" >"$T/out" 2>"$T/err"; echo $? > "$T/rc"
}
rc_of() { cat "$T/rc"; }
lines() { [ -f "$1/.claude/dispatch-log.jsonl" ] && wc -l < "$1/.claude/dispatch-log.jsonl" || echo 0; }
field() {  # $1 = repo $2 = line no (1-based) $3 = key
    sed -n "${2}p" "$1/.claude/dispatch-log.jsonl" | python3 -c 'import json,sys; v=json.loads(sys.stdin.read()).get(sys.argv[1]); print("" if v is None else v)' "$3"
}

echo "dispatch-log — every dispatch, start and stop of a plan run is logged; nothing else"
echo

# Catches: the embedded logger importing a module from the cwd: a project file named like a
# stdlib module (here one that exits 0) must not stand in for it and drop the line.
PLANT="$T/plant"; mkdir -p "$PLANT"; printf 'import os\nos._exit(0)\n' > "$PLANT/json.py"
P="$T/planted"; mkrepo "$P" plan
pl="$(dispatch_payload planning:code-reviewer)"   # the harness's python runs outside it
( cd "$PLANT" && printf '%s' "$pl" | hook "$P" )
if [ "$(lines "$P")" = 1 ]; then ok "a json.py in the hook's cwd does not replace the stdlib module"
else bad "a planted json.py must not drop the dispatch line" "lines=$(lines "$P") $(cat "$T/err")"; fi

# Catches: the hook writing nothing for a dispatch during a plan run.
R="$T/inflight"; mkrepo "$R" plan
dispatch_payload planning:code-reviewer | hook "$R"
if [ "$(rc_of)" = 0 ] && [ "$(lines "$R")" = 1 ] && [ "$(field "$R" 1 event)" = dispatch ] \
   && [ "$(field "$R" 1 subagent_type)" = planning:code-reviewer ] \
   && [ "$(field "$R" 1 description)" = "Review Stage 1" ] \
   && [ "$(field "$R" 1 session_id)" = sess-1 ] && [ -n "$(field "$R" 1 ts)" ]; then
    ok "a dispatch during a plan run appends one dispatch line with its subagent_type"
else
    bad "a dispatch during a plan run appends one dispatch line with its subagent_type" \
        "rc=$(rc_of) lines=$(lines "$R") $(cat "$R/.claude/dispatch-log.jsonl" 2>/dev/null)"
fi
[ -s "$T/out" ] && bad "a logged dispatch prints nothing on stdout" "$(cat "$T/out")" \
    || ok "a logged dispatch prints nothing on stdout"

# Catches: the log being written outside a plan run.
N="$T/noplan"; mkrepo "$N"
dispatch_payload general-purpose | hook "$N"
if [ "$(rc_of)" = 0 ] && [ ! -e "$N/.claude/dispatch-log.jsonl" ] && [ ! -s "$T/out" ]; then
    ok "with no plan in flight nothing is written"
else
    bad "with no plan in flight nothing is written" "rc=$(rc_of) $(ls -A "$N/.claude")"
fi

# Catches: a non-Agent PreToolUse being logged as a dispatch (matcher widened by hand).
python3 -c 'import json; print(json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}))' | hook "$R"
[ "$(lines "$R")" = 1 ] && ok "a PreToolUse for another tool is not logged" \
    || bad "a PreToolUse for another tool is not logged" "lines=$(lines "$R")"

# Catches: start or stop dropping agent_id / agent_type.
agent_payload SubagentStart a-123 planning:code-reviewer | hook "$R"
agent_payload SubagentStop a-123 planning:code-reviewer | hook "$R"
if [ "$(lines "$R")" = 3 ] \
   && [ "$(field "$R" 2 event)" = start ] && [ "$(field "$R" 2 agent_id)" = a-123 ] \
   && [ "$(field "$R" 2 agent_type)" = planning:code-reviewer ] \
   && [ "$(field "$R" 3 event)" = stop ] && [ "$(field "$R" 3 agent_id)" = a-123 ] \
   && [ "$(field "$R" 3 agent_type)" = planning:code-reviewer ]; then
    ok "start and stop lines carry agent_id and agent_type"
else
    bad "start and stop lines carry agent_id and agent_type" "$(cat "$R/.claude/dispatch-log.jsonl")"
fi

# Catches: the hook blocking a dispatch on bad input — any stdout could be read as a
# decision, and a non-zero exit is a hook error shown to the user.
for junk in 'not json' '' '[1,2]' '{"hook_event_name": "SubagentStart"}' \
            '{"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": "x"}'; do
    printf '%s' "$junk" | hook "$R"
    if [ "$(rc_of)" != 0 ] || [ -s "$T/out" ]; then
        bad "malformed stdin exits 0 with empty stdout: '$junk'" "rc=$(rc_of) out=$(cat "$T/out")"
        continue
    fi
    ok "malformed stdin exits 0 with empty stdout: '${junk:0:40}'"
done

# Catches: a .claude symlinked out of the repo being followed to write elsewhere.
S="$T/symlinked"; mkdir -p "$S" "$T/elsewhere"
printf '{"plan": "p", "phase": "task"}\n' > "$T/elsewhere/plan-progress.json"
ln -s "$T/elsewhere" "$S/.claude"
dispatch_payload general-purpose | hook "$S"
[ "$(rc_of)" = 0 ] && [ ! -e "$T/elsewhere/dispatch-log.jsonl" ] \
    && ok "a symlinked .claude is not written through" \
    || bad "a symlinked .claude is not written through" "rc=$(rc_of) $(ls "$T/elsewhere")"

# Catches: a symlinked log being written through.
L="$T/linklog"; mkrepo "$L" plan; : > "$T/target.jsonl"
ln -s "$T/target.jsonl" "$L/.claude/dispatch-log.jsonl"
dispatch_payload general-purpose | hook "$L"
[ "$(rc_of)" = 0 ] && [ ! -s "$T/target.jsonl" ] \
    && ok "a symlinked dispatch-log.jsonl is not written through" \
    || bad "a symlinked dispatch-log.jsonl is not written through" "$(cat "$T/target.jsonl")"

# Catches: the legacy `Task` tool name (the Agent tool's alias) going unlogged.
K="$T/tasktool"; mkrepo "$K" plan
python3 -c 'import json; print(json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Task", "tool_input": {"subagent_type": "general-purpose", "description": "d"}}))' | hook "$K"
[ "$(lines "$K")" = 1 ] && [ "$(field "$K" 1 event)" = dispatch ] \
    && ok "a dispatch through the Task alias is logged" \
    || bad "a dispatch through the Task alias is logged" "lines=$(lines "$K")"

# Catches: this hook answering under Cursor. cursor-agent runs a Claude Code plugin's hooks
# too, with its own payload, which always carries `cursor_version`; the Cursor plugin logs
# that dispatch itself, so this hook must step aside or the line is written twice. The
# payloads are ones it would otherwise log: a dispatch and a start, plus the key.
C="$T/cursor"; mkrepo "$C" plan
for ev in PreToolUse SubagentStart; do
    python3 -c 'import json,sys; ev=sys.argv[1]; p={"session_id": "s", "hook_event_name": ev, "cursor_version": "2026.10.22", "workspace_roots": ["/x"]}
p.update({"tool_name": "Task", "tool_input": {"subagent_type": "general-purpose", "description": "d"}} if ev == "PreToolUse" else {"agent_id": "a-1", "agent_type": "general-purpose"})
print(json.dumps(p))' "$ev" | hook "$C"
    if [ "$(rc_of)" = 0 ] && [ ! -s "$T/out" ] && [ "$(lines "$C")" = 0 ]; then
        ok "a $ev payload carrying cursor_version exits 0 with no output and no line"
    else
        bad "a $ev payload carrying cursor_version exits 0 with no output and no line" \
            "rc=$(rc_of) out=$(cat "$T/out") lines=$(lines "$C")"
    fi
done
# Catches: the step-aside matching text anywhere in the payload, which a Claude Code
# dispatch could carry in its own description and so go unlogged.
python3 -c 'import json; print(json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"subagent_type": "general-purpose", "description": "\"cursor_version\": \"x\""}}))' | hook "$C"
[ "$(lines "$C")" = 1 ] && ok "cursor_version inside a field is not the key: still logged" \
    || bad "cursor_version inside a field is not the key: still logged" "lines=$(lines "$C")"

# .claude/plan-progress.json is git-ignored, so each worktree has its own. A dispatch from a
# linked worktree while the run lives in the main one belongs to that run's log: the hook
# reads its own worktree first, and the main worktree's run when its own has none.
PS="$HERE/../../skills/executing-plans/scripts/plan-state.py"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
wt_pair() {  # $1 = name: a main repo with no state, and a linked worktree
    WMAIN="$T/$1-main"; WLINK="$T/$1-linked"
    git init -q -b main --template= "$WMAIN"; mkrepo "$WMAIN"
    git -C "$WMAIN" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m base
    git -C "$WMAIN" worktree add -q -b "$1-side" "$WLINK" 2>/dev/null
}
# Catches: a dispatch from a linked worktree going unlogged during a main-worktree run.
wt_pair dl
printf '{"plan": "%s", "phase": "task", "stage": 1, "task": "1.1"}\n' "$T/plan.md" > "$WMAIN/.claude/plan-progress.json"
dispatch_payload planning:code-reviewer | hook "$WLINK"
if [ "$(rc_of)" = 0 ] && [ ! -s "$T/out" ] && [ "$(lines "$WMAIN")" = 1 ] \
   && [ "$(field "$WMAIN" 1 subagent_type)" = planning:code-reviewer ] && [ ! -e "$WLINK/.claude" ]; then
    ok "a dispatch from a linked worktree is logged to the main worktree's run"
else bad "a dispatch from a linked worktree must reach the main worktree's log" \
    "rc=$(rc_of) main=$(lines "$WMAIN") linked=$(lines "$WLINK") $(cat "$T/err")"; fi
# Catches: a main-worktree lookup that strays into writing where no plan is in flight.
wt_pair dn
dispatch_payload general-purpose | hook "$WLINK"
if [ "$(rc_of)" = 0 ] && [ ! -e "$WMAIN/.claude/dispatch-log.jsonl" ] && [ ! -e "$WLINK/.claude" ]; then
    ok "with no state in either worktree nothing is written"
else bad "with no plan in flight anywhere nothing is written" "rc=$(rc_of)"; fi
# Catches: a main-only lookup: the linked worktree's own run keeps its own log while the
# main worktree holds a finished one.
wt_pair do
printf '# Plan\n' > "$T/plan.md"
printf '{"plan": "%s", "scope": "fixture", "source": "owner: run the fixture"}' "$T/plan.md" \
    | python3 "$PS" init --repo "$WMAIN" --expected-revision 0 --operation-id op-1 >/dev/null \
    && printf '{"evidence": "fixture finished"}' \
    | python3 "$PS" finish --repo "$WMAIN" --expected-revision 1 --operation-id op-2 >/dev/null \
    || bad "fixture: init/finish in the main worktree failed"
mkrepo "$WLINK" plan
dispatch_payload general-purpose | hook "$WLINK"
if [ "$(lines "$WLINK")" = 1 ] && [ ! -e "$WMAIN/.claude/dispatch-log.jsonl" ]; then
    ok "the linked worktree's own run is logged in its own log, over a finished main-worktree run"
else bad "the linked worktree's own run must keep its own log" \
    "linked=$(lines "$WLINK") main=$(lines "$WMAIN")"; fi
# Catches: the main worktree's untrusted state taken as a run.
wt_pair du
printf 'not json\n' > "$WMAIN/.claude/plan-progress.json"
dispatch_payload general-purpose | hook "$WLINK"
if [ "$(rc_of)" = 0 ] && [ ! -s "$T/out" ] && [ ! -e "$WMAIN/.claude/dispatch-log.jsonl" ]; then
    ok "an unreadable state file in the main worktree is no run: nothing is written"
else bad "an unreadable main-worktree state must not be logged to" "rc=$(rc_of) main=$(lines "$WMAIN")"; fi

# Catches: no python3 on PATH failing closed.
E="$T/nopy"; mkrepo "$E" plan; mkdir -p "$T/bin"
for b in bash cat; do ln -sf "$(command -v $b)" "$T/bin/$b"; done
dispatch_payload general-purpose > "$T/payload.json"
CLAUDE_PROJECT_DIR="$E" PATH="$T/bin" "$T/bin/bash" "$HOOK" < "$T/payload.json" >"$T/out" 2>&1; rc=$?
[ "$rc" = 0 ] && [ ! -s "$T/out" ] && [ ! -e "$E/.claude/dispatch-log.jsonl" ] \
    && ok "with no python3 it exits 0 silently" \
    || bad "with no python3 it exits 0 silently" "rc=$rc $(cat "$T/out")"

# Catches: no project dir at all failing closed.
dispatch_payload general-purpose | env -u CLAUDE_PROJECT_DIR bash "$HOOK" >"$T/out" 2>&1; rc=$?
[ "$rc" = 0 ] && [ ! -s "$T/out" ] && ok "with CLAUDE_PROJECT_DIR unset it exits 0 silently" \
    || bad "with CLAUDE_PROJECT_DIR unset it exits 0 silently" "rc=$rc $(cat "$T/out")"

# Catches: an event missing from hooks.json, or registered to another script.
reg="$(python3 - "$HOOKS_JSON" <<'PY'
import json, sys
h = json.load(open(sys.argv[1]))["hooks"]
def cmds(event, matcher=None):
    return [c.get("command", "") for g in h.get(event, [])
            if matcher is None or matcher in (g.get("matcher") or "").split("|")
            for c in g.get("hooks", [])]
out = []
for event, matcher in (("PreToolUse", "Agent"), ("SubagentStart", None), ("SubagentStop", None)):
    hit = [c for c in cmds(event, matcher) if c.rstrip('"').endswith("/hooks/dispatch-log.sh")]
    out.append(f"{event}:{'ok' if hit else 'missing'}")
print(" ".join(out))
PY
)"
for want in PreToolUse SubagentStart SubagentStop; do
    case "$reg" in
        *"$want:ok"*) ok "hooks.json registers $want to dispatch-log.sh" ;;
        *) bad "hooks.json registers $want to dispatch-log.sh" "$reg" ;;
    esac
done
[ -x "$HOOK" ] && ok "dispatch-log.sh is executable" || bad "dispatch-log.sh is executable"

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
