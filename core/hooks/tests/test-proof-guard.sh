#!/usr/bin/env bash
# Fixture suite for the PreToolUse guard — run directly (repo convention):
#
#     bash core/hooks/tests/test-proof-guard.sh
#
# WHAT THIS SUITE IS REALLY GUARDING. hooks/proof-guard.sh ships in the plugin's
# hooks.json, so it runs on EVERY Bash call of every user who enables planning.
# It must do nothing at all unless the project opted in (our reference-transaction
# shim is installed) AND a plan is in flight; there, it denies the commands that
# would turn the git ref hook off — any mention of hooksPath, the hook file, and
# the installer's --remove (the user removes the gate, with `!`). Three failures
# matter: the one bypass left open, a user who never opted in being denied
# anything, and the guard failing closed on its own errors.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/../proof-guard.sh"
# The Claude Code registration (hooks.json) is host-specific, so in this repo's source
# tree it lives in hosts/claude/add/hooks/; in a built plugin it sits beside this
# directory. Look beside first, then in the Claude layer — and fail if neither has it,
# rather than letting the registration checks below pass over nothing.
HOOKS_JSON="$HERE/../hooks.json"
[ -f "$HOOKS_JSON" ] || HOOKS_JSON="$HERE/../../../hosts/claude/add/hooks/hooks.json"
[ -f "$HOOKS_JSON" ] || { echo "FAIL: no hooks.json beside hooks/ or in hosts/claude/add/hooks/"; exit 1; }
INSTALL="$HERE/../../skills/executing-plans/scripts/proof-hooks-install.py"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok    $1"; }
bad() { fail=$((fail+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && printf '        | %s\n' "${2:0:700}"
        [ "${SUITE_FAIL_FAST:-}" = 1 ] && exit 1; }   # the battery needs only the first FAIL
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
unset CLAUDE_PROJECT_DIR

[ -f "$GUARD" ] || { echo "FAIL: $GUARD does not exist"; exit 1; }

mkrepo() {  # $1 = path [$2 = "plan" to put a plan in flight]
    git init -q -b main --template= "$1"
    mkdir -p "$1/.claude"
    if [ "${2:-}" = plan ]; then
        printf '{"plan": "%s", "phase": "task", "stage": 1, "task": "1.1"}\n' "$T/plan.md" \
            > "$1/.claude/plan-progress.json"
    fi
}
printf '# Plan\n' > "$T/plan.md"
REPO="$T/repo"; mkrepo "$REPO" plan
python3 "$INSTALL" --install --repo "$REPO" >/dev/null 2>&1 || bad "fixture: installing the shim failed"
OTHER="$T/other"; mkrepo "$OTHER"            # no plan, no shim

payload() {  # $1 = command  [$2 = cwd]
    python3 -c 'import json,sys; print(json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": sys.argv[1]}, "cwd": sys.argv[2]}))' "$1" "${2:-$REPO}"
}
decide() {  # stdin payload -> deny | none | (garbage: …); rc kept in $grc
    local out; out="$(bash "$GUARD" 2>"$T/err")"; grc=$?
    if [ -z "$out" ]; then echo none; return; fi
    printf '%s' "$out" | python3 -c '
import json, sys
d = json.loads(sys.stdin.read())["hookSpecificOutput"]
assert d["hookEventName"] == "PreToolUse"
print(d["permissionDecision"])' 2>/dev/null || echo "(garbage: $out)"
}
reason() { bash "$GUARD" 2>/dev/null | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["hookSpecificOutput"]["permissionDecisionReason"])'; }

# Catches: the embedded checker importing a module from the cwd. Claude Code runs the hook
# in the project, so a project file named like a stdlib module (here one that exits 0)
# must not stand in for it and silently allow.
PLANT="$T/plant"; mkdir -p "$PLANT"; printf 'import os\nos._exit(0)\n' > "$PLANT/json.py"
# Only the hook runs in the planted dir; the harness's own python runs outside it.
pl="$(payload 'git -c core.hooksPath=/dev/null commit -m x')"
planted_out="$(cd "$PLANT" && printf '%s' "$pl" | bash "$GUARD" 2>"$T/err")"
planted="$(printf '%s' "$planted_out" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["hookSpecificOutput"]["permissionDecision"])' 2>/dev/null || echo none)"
echo "proof-guard — the git ref hook stays on in an opted-in repo with a plan in flight"
echo

if [ "$planted" = deny ]; then ok "a json.py in the hook's cwd does not replace the stdlib module"
else bad "a planted json.py must not switch the guard off, got $planted" "$(cat "$T/err")"; fi

# Catches: the one bypass left open — any spelling of hooksPath, the hook file,
# and a repo reached only through `cd` or `git -C`.
for c in 'git -c core.hooksPath=/dev/null commit -m x' 'git config core.HOOKSPATH /tmp/none' \
         'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit -m x' \
         'rm .git/hooks/reference-transaction' 'chmod -x .git/hooks/reference-transaction' \
         'cd .git && rm hooks/reference-transaction' \
         "python3 $INSTALL --remove --repo $REPO"; do
    got="$(payload "$c" | decide)"
    if [ "$got" = deny ]; then ok "denied: ${c:0:70}"
    else bad "must deny '$c', got $got" "$(cat "$T/err")"; fi
done
for c in "cd $REPO && git -c core.hookspath=/x commit -m x" "git -C $REPO -c core.hooksPath=/x commit -m x"; do
    got="$(payload "$c" "$OTHER" | decide)"
    if [ "$got" = deny ]; then ok "denied from another repo: ${c:0:60}"
    else bad "must deny '$c' run from $OTHER, got $got" "$(cat "$T/err")"; fi
done
msg="$(payload 'git -c core.hooksPath=/dev/null commit -m x' | reason)"
if grep -q 'hooksPath' <<<"$msg" && grep -q 'proof' <<<"$msg"; then
    ok "the deny carries a reason the model can act on"
else bad "the deny must say why" "$msg"; fi
msg="$(payload "python3 $INSTALL --remove --repo $REPO" | reason)"
if grep -q '! python3' <<<"$msg"; then ok "the --remove deny tells the user how to remove it themselves"
else bad "the --remove deny must name the user's own route" "$msg"; fi

# Must not over-match: none of these can turn the git hook off.
for c in 'git commit -m "Task 1.1: a; b" --no-verify' 'git commit -am "Task 1.1: x"' \
         'git add -A && git commit -m x' 'git status' 'ls -la' \
         "python3 $INSTALL --status --repo $REPO" "python3 $INSTALL --install --repo $REPO"; do
    got="$(payload "$c" | decide)"
    if [ "$got" = none ]; then ok "no decision: ${c:0:70}"
    else bad "must not decide '$c', got $got"; fi
done

echo
echo "steps aside under Cursor"
# Catches: this guard answering under Cursor. cursor-agent runs a Claude Code plugin's
# hooks too, with its own payload (tool_name Shell, a cursor_version key); the Cursor
# plugin's own commit gate answers there, so this one must exit 0 and print nothing.
# The command is one this guard denies, in a gated repo.
cpl() {  # $1 = command; a Cursor-shaped payload
    python3 -c 'import json,sys; print(json.dumps({"session_id": "s", "hook_event_name": "preToolUse", "tool_name": "Shell", "tool_input": {"command": sys.argv[1], "cwd": sys.argv[2]}, "cwd": sys.argv[2], "cursor_version": "2026.10.22", "workspace_roots": [sys.argv[2]]}))' "$1" "$REPO"
}
out="$(cpl 'git -c core.hooksPath=/dev/null commit -m x' | bash "$GUARD" 2>/dev/null)"; grc=$?
if [ -z "$out" ] && [ "$grc" -eq 0 ]; then ok "a payload carrying cursor_version: exit 0, no output"
else bad "a payload carrying cursor_version must get no decision (rc=$grc)" "$out"; fi
# Catches: the step-aside matching text rather than the payload's own key — a Claude Code
# command could carry the word and switch the guard off.
got="$(payload 'git -c core.hooksPath=/dev/null commit -m "\"cursor_version\": 1"' | decide)"
if [ "$got" = deny ]; then ok "cursor_version inside the command is not the key: still denied"
else bad "cursor_version in the command text must not switch the guard off, got $got"; fi

echo
echo "inert unless the project opted in and a plan is in flight"
# Catches: the guard acting without opt-in — every user who enables the plugin runs it.
NOSHIM="$T/noshim"; mkrepo "$NOSHIM" plan
got="$(payload 'git -c core.hooksPath=/dev/null commit -m x' "$NOSHIM" | decide)"
if [ "$got" = none ]; then ok "a repo without the shim: hooksPath is not this guard's business"
else bad "a repo that did not opt in must see no decision, got $got"; fi
FOREIGN="$T/foreign"; mkrepo "$FOREIGN" plan; mkdir -p "$FOREIGN/.git/hooks"
printf '#!/bin/sh\nexit 0\n' > "$FOREIGN/.git/hooks/reference-transaction"
got="$(payload 'rm .git/hooks/reference-transaction' "$FOREIGN" | decide)"
if [ "$got" = none ]; then ok "a foreign reference-transaction hook is not our opt-in"
else bad "someone else's hook must not opt the repo in, got $got"; fi
# Catches: a shim in a hooks directory outside the repo (a shared core.hooksPath)
# counted as this repo's opt-in.
SHR="$T/shared"; mkrepo "$SHR" plan; mkdir -p "$T/sharedhooks"
cp "$REPO/.git/hooks/reference-transaction" "$T/sharedhooks/"
git -C "$SHR" config core.hooksPath "$T/sharedhooks"
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$SHR" | decide)"
if [ "$got" = none ]; then ok "our shim in a shared hooks directory outside the repo is not an opt-in"
else bad "a shared hooks directory must not opt a repo in, got $got"; fi
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$T" | decide)"
if [ "$got" = none ]; then ok "outside any repo: no decision"
else bad "outside a repo must see no decision, got $got"; fi
mv "$REPO/.claude/plan-progress.json" "$T/pp.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' | decide)"
if [ "$got" = none ]; then ok "opted in, no plan in flight: no decision"
else bad "no plan in flight must see no decision, got $got"; fi
ln -s "$T/pp.json" "$REPO/.claude/plan-progress.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' | decide)"
if [ "$got" = none ]; then ok "a symlinked plan-progress.json is not a plan in flight"
else bad "symlinked state must not count, got $got"; fi
rm "$REPO/.claude/plan-progress.json"; mv "$T/pp.json" "$REPO/.claude/plan-progress.json"
# Catches: O_NOFOLLOW guarding only the last path component.
mv "$REPO/.claude" "$T/claude-dir"; ln -s "$T/claude-dir" "$REPO/.claude"
got="$(payload 'git -c core.hooksPath=/x commit -m x' | decide)"
if [ "$got" = none ]; then ok "a symlinked .claude directory is not a plan in flight"
else bad "a symlinked .claude dir must not count, got $got"; fi
rm "$REPO/.claude"; mv "$T/claude-dir" "$REPO/.claude"

echo
echo "fails open"
# Catches: the guard failing closed. A broken payload must never block a command.
# Each but the empty one carries a deny-rule string, so it gets past the text pre-filter.
for p in 'not json hooksPath' '["hooksPath", 2]' '{"tool_input": "hooksPath"}' \
         '{"tool_input": {"command": 7}, "cwd": "hooksPath"}' \
         '{"tool_input": {"command": "git -c core.hooksPath=x commit"}, "cwd": 5}' \
         '{"tool_input": {"command": "git -c core.hooksPath=x commit"}, "cwd": "/nonexistent/x"}' ''; do
    out="$(printf '%s' "$p" | bash "$GUARD" 2>/dev/null)"; grc=$?
    if [ -z "$out" ] && [ "$grc" -eq 0 ]; then ok "no decision, exit 0 on payload: ${p:-<empty>}"
    else bad "a garbage payload must produce no decision (rc=$grc)" "$p -> $out"; fi
done

echo
echo "registered in the plugin's hooks.json"
if python3 - "$HOOKS_JSON" <<'PY'
import json, sys
h = json.load(open(sys.argv[1]))["hooks"]
ents = [x for g in h.get("PreToolUse", []) if g.get("matcher") == "Bash"
        for x in g.get("hooks", []) if "hooks/proof-guard.sh" in x.get("command", "")]
assert len(ents) == 1 and "${CLAUDE_PLUGIN_ROOT}" in ents[0]["command"], ents
assert "Stop" in h, "the plan-continue Stop hook must stay"
PY
then ok "hooks.json runs proof-guard.sh on PreToolUse Bash, beside the Stop hook"
else bad "hooks.json must register proof-guard.sh for PreToolUse on Bash"; fi


# Catches: the pre-filter failing open. A here-string or a pipe can fail where the plain
# string test cannot (no temp file, no SIGPIPE): a large payload with TMPDIR unwritable
# must still reach the deny rules.
big="git -c core.hooksPath=/dev/null commit -m x # $(head -c 300000 /dev/zero | tr '\0' 'y')"
got="$(printf '%s' "$big" | python3 -c 'import json,sys; print(json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": sys.stdin.read()}, "cwd": sys.argv[1]}))' "$REPO" | TMPDIR=/nonexistent/tmp decide)"
if [ "$got" = deny ]; then ok "a 300 KB payload with TMPDIR unwritable is still denied"
else bad "a large payload with TMPDIR unwritable must be denied, got $got" "$(cat "$T/err")"; fi


echo
echo "a commit while prove-claim.py has a break applied"
# Catches: `git commit -a` carrying a break a live prove-claim run applied. The run holds an exclusive lock at `git rev-parse --git-path prove-claim.lock`
# while the break is in the tree; an interrupted run leaves its journal there. Only this
# plugin's own tool takes either, so the rule holds in every repo, gated or not.
hold_lock() {  # $1 = repo; holds the lock in the background, pid in $holder
    local lp; lp="$(git -C "$1" rev-parse --git-path prove-claim.lock)"
    case "$lp" in /*) ;; *) lp="$1/$lp" ;; esac
    rm -f "$T/held"
    python3 -c 'import fcntl, sys, time
f = open(sys.argv[1], "w"); fcntl.flock(f, fcntl.LOCK_EX)
open(sys.argv[2], "w").close(); time.sleep(60)' "$lp" "$T/held" &
    holder=$!
    for _ in $(seq 50); do [ -f "$T/held" ] && return; sleep 0.1; done
}
for r in "$REPO" "$OTHER"; do
    hold_lock "$r"
    got="$(payload 'git commit -a -m "Stage 1 Task 1.1: x"' "$r" | decide)"
    why="$(payload 'git commit -a -m x' "$r" | reason 2>/dev/null)"
    kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
    if [ "$got" = deny ] && [[ $why == *prove-claim.lock* ]]; then
        ok "a commit while the lock is held is denied, naming the lock ($(basename "$r"))"
    else bad "a commit while prove-claim holds its lock must be denied naming it ($(basename "$r")), got $got" "$why"; fi
done
got="$(payload 'git commit -a -m x' "$OTHER" | decide)"
if [ "$got" = none ]; then ok "with the lock free a commit gets no decision"
else bad "a commit with the lock free must get no decision, got $got" "$(cat "$T/err")"; fi
JP="$(git -C "$OTHER" rev-parse --git-path prove-claim-journal.json)"
case "$JP" in /*) ;; *) JP="$OTHER/$JP" ;; esac
printf '{}' > "$JP"
got="$(payload 'git commit -a -m x' "$OTHER" | decide)"
why="$(payload 'git commit -a -m x' "$OTHER" | reason 2>/dev/null)"
rm -f "$JP"
if [ "$got" = deny ] && [[ $why == *prove-claim-journal.json* ]]; then
    ok "a commit while an interrupted run's journal is present is denied, naming it"
else bad "a commit with a prove-claim journal present must be denied, got $got" "$why"; fi
# A live run holds the lock AND has its journal while the break is applied: it is
# reported in progress, never as interrupted (re-running it then only meets the lock).
hold_lock "$OTHER"
printf '{}' > "$JP"
got="$(payload 'git commit -a -m x' "$OTHER" | decide)"
why="$(payload 'git commit -a -m x' "$OTHER" | reason 2>/dev/null)"
# `commit` reaches the rule (the pre-filter passes it) but no `git`: not a commit.
neg="$(payload 'echo commit done' "$OTHER" | decide)"
# Under Cursor this guard steps aside, the lock rule included (Cursor's own gate has it).
cur="$(python3 -c 'import json,sys; print(json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git commit -a -m x"}, "cwd": sys.argv[1], "cursor_version": "1.0"}))' "$OTHER" | decide)"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
rm -f "$JP"
if [ "$got" = deny ] && [[ $why == *"in progress"*prove-claim.lock* ]] && [[ $why != *interrupted* ]]; then
    ok "a commit during a live run (lock and journal both present) is denied as a run in progress"
else bad "a live run must be reported in progress, naming the lock, got $got" "$why"; fi
if [ "$neg" = none ]; then ok "with the lock held a command that is not a git commit gets no decision"
else bad "a non-commit command must get no decision while the lock is held, got $neg"; fi
if [ "$cur" = none ]; then ok "a Cursor payload gets no decision from the lock rule (the guard steps aside)"
else bad "under Cursor the lock rule must step aside, got $cur"; fi
# A linked worktree's lock lives under the main repo's .git/worktrees/<name>/: the
# git-path is absolute there, and the rule must still find it.
WMAIN="$T/wmain"; git init -q -b main --template= "$WMAIN"
git -C "$WMAIN" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m base
git -C "$WMAIN" worktree add -q "$T/wlinked" 2>/dev/null
hold_lock "$T/wlinked"
got="$(payload 'git commit -a -m x' "$T/wlinked" | decide)"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
if [ "$got" = deny ]; then ok "a commit in a linked worktree whose run holds its lock is denied"
else bad "the lock rule must find a linked worktree's lock, got $got" "$(cat "$T/err")"; fi

echo
echo "a linked worktree and the run in the main worktree"
# .claude/plan-progress.json is git-ignored, so each worktree has its own. The guard reads
# the command's own worktree first, and the main worktree's run when its own has none.
PS="$HERE/../../skills/executing-plans/scripts/plan-state.py"
wt_pair() {  # $1 = name: a main repo with the shim and no state, and a linked worktree
    WMAIN="$T/$1-main"; WLINK="$T/$1-linked"; mkrepo "$WMAIN"
    git -C "$WMAIN" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m base
    python3 "$INSTALL" --install --repo "$WMAIN" >/dev/null 2>&1
    git -C "$WMAIN" worktree add -q -b "$1-side" "$WLINK" 2>/dev/null
}
# Catches: the guard silently off in a linked worktree while the main worktree has a plan in flight.
wt_pair gl
printf '{"plan": "%s", "phase": "task", "stage": 1, "task": "1.1"}\n' "$T/plan.md" > "$WMAIN/.claude/plan-progress.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WLINK" | decide)"
if [ "$got" = deny ]; then ok "a hooksPath command in a linked worktree is denied while the main worktree has a plan in flight"
else bad "the main worktree's run must gate a linked worktree, got $got" "$(cat "$T/err")"; fi
# Catches: a run in a sibling, or in a linked worktree seen from the main one, unseen.
wt_pair gs; git -C "$WMAIN" worktree add -q -b gs-run "$T/gs-run" 2>/dev/null; mkdir -p "$T/gs-run/.claude"
printf '{"plan": "%s", "phase": "task", "stage": 1, "task": "1.1"}\n' "$T/plan.md" > "$T/gs-run/.claude/plan-progress.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WLINK" | decide)"
if [ "$got" = deny ]; then ok "a hooksPath command in a linked worktree is denied while a sibling has a plan in flight"
else bad "a sibling's run must gate a linked worktree, got $got" "$(cat "$T/err")"; fi
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WMAIN" | decide)"
if [ "$got" = deny ]; then ok "a hooksPath command in the main worktree is denied while a linked worktree has a plan in flight"
else bad "a linked worktree's run must gate the main worktree, got $got" "$(cat "$T/err")"; fi
# Catches: two runs elsewhere read as none. The rule protects shared config, so either one counts.
git -C "$WMAIN" worktree add -q -b gs-two "$T/gs-two" 2>/dev/null; mkdir -p "$T/gs-two/.claude"
cp "$T/gs-run/.claude/plan-progress.json" "$T/gs-two/.claude/plan-progress.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WLINK" | decide)"
if [ "$got" = deny ]; then ok "a hooksPath command is denied while two other worktrees have plans in flight"
else bad "two runs elsewhere must still gate, got $got" "$(cat "$T/err")"; fi
# Catches: a main-worktree lookup that strays into deciding where no plan is in flight.
wt_pair gn
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WLINK" | decide)"
if [ "$got" = none ]; then ok "with no state in either worktree, a linked worktree gets no decision"
else bad "no plan in flight anywhere must see no decision, got $got"; fi
# Catches: a main-only lookup: the linked worktree's own run must gate while the main
# worktree holds a finished one.
wt_pair go
printf '{"plan": "%s", "scope": "fixture", "source": "owner: run the fixture"}' "$T/plan.md" \
    | python3 "$PS" init --repo "$WMAIN" --expected-revision 0 --operation-id op-1 >/dev/null \
    && printf '{"evidence": "fixture finished"}' \
    | python3 "$PS" finish --repo "$WMAIN" --expected-revision 1 --operation-id op-2 >/dev/null \
    || bad "fixture: init/finish in the main worktree failed"
mkdir -p "$WLINK/.claude"
printf '{"plan": "%s", "phase": "task", "stage": 1, "task": "1.1"}\n' "$T/plan.md" > "$WLINK/.claude/plan-progress.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WLINK" | decide)"
if [ "$got" = deny ]; then ok "the linked worktree's own run gates first, over a finished run in the main worktree"
else bad "the linked worktree's own run must gate, got $got" "$(cat "$T/err")"; fi
# Catches: the main worktree's untrusted state read as "no plan" in silence.
wt_pair gu
printf 'not json\n' > "$WMAIN/.claude/plan-progress.json"
got="$(payload 'git -c core.hooksPath=/x commit -m x' "$WLINK" | decide)"
if [ "$got" = none ] && grep -q -- "$WMAIN/.claude/plan-progress.json" "$T/err"; then
    ok "an unreadable state file in the main worktree is no plan in flight, and is named"
else bad "an unreadable main-worktree state must be named, got $got" "$(cat "$T/err")"; fi

echo
echo "passed: $pass   failed: $fail"
[ "$fail" -eq 0 ]
