#!/bin/bash
# statusline-chain — wraps a base statusline with the executing-plans plan
# progress bar.
#
# Why: Cursor CLI spawns the configured `statusLine` command on every
# conversation update and pipes it a JSON payload on stdin. This shim runs the
# user's own base statusline command (if they have one configured at the
# conventional path) untouched and appends the plan-progress bar — present only
# while a plan is executing — on the NEXT line, not "line 2", since a base
# statusline may itself emit several lines. Both consumers read the SAME stdin
# bytes, captured once here so neither one starves the other.
#
# WHAT A CURSOR STATUS LINE DISPLACES. On Cursor a configured statusLine replaces
# the CLI's NATIVE FOOTER, which is not a command and cannot be chained: the
# model/context readout, auto-review state, working directory, branch and PR
# indicators disappear while it is set. The statusline skill says so before it
# installs; nothing here can repair it. What this script still does is preserve a
# base command the user configured THEMSELVES — displacing that silently would be
# the fault the installer's --force gate exists to prevent.
#
# Nothing here reads a field of the Cursor payload by name. The payload's key
# names are not vendor-documented, so the bytes are passed through to both
# consumers verbatim and plan-progress.py falls back to its own cwd.
#
# Accepted limitation: command substitution strips trailing newlines, so a base
# that deliberately ends in a blank line for spacing loses it. Preserving it
# would need a sentinel-and-strip dance; the spacing is not worth that.
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STDIN_JSON="$(cat)"

# A statusline is redrawn constantly, so a subprocess that blocks (a dead
# network mount, a stuck filesystem call, an infinite loop) would freeze the
# redraw indefinitely — worse than a missing line, and with nothing to explain
# it. Bound both subprocesses.
#
# The two bounds differ ON PURPOSE, and the base's is deliberately generous.
# A base statusline legitimately does slow work and bounds itself: a base that
# fetches over the network may make `curl -s --max-time 10` and
# `--max-time 5` calls, so a snug wrapper bound would cut off a base that is
# working exactly as designed and silently truncate the user's own status line.
# This wrapper's job is to catch an UNBOUNDED hang, not to second-guess a base
# that already bounds itself — so the default sits above any such self-bound.
# plan-progress.py is ours and only reads local files, so it gets a tight one.
#
# `timeout` is GNU coreutils and absent from a stock macOS, a platform this repo
# supports; fall back to gtimeout, then to running unbounded rather than losing
# the statusline entirely. Unquoted on purpose: empty must expand to no words.
BASE_TIMEOUT="${PLAN_STATUSLINE_BASE_TIMEOUT:-15}"
BAR_TIMEOUT="${PLAN_STATUSLINE_BAR_TIMEOUT:-5}"
if command -v timeout >/dev/null 2>&1; then
  TO_CMD=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  TO_CMD=gtimeout
else
  TO_CMD=""
fi
if [ -n "$TO_CMD" ]; then
  TO_BASE="$TO_CMD $BASE_TIMEOUT"
  TO_BAR="$TO_CMD $BAR_TIMEOUT"
else
  TO_BASE=""
  TO_BAR=""
fi

# The default base path. Cursor writes no status line script of its own (the native
# footer is internal), so this default normally does not exist and the bar renders
# alone, which is the expected result. It stays a default so a user who keeps their
# own script there gets it chained without configuring anything.
BASE="${PLAN_STATUSLINE_BASE:-$HOME/.cursor/statusline.sh}"
BASE_OUT=""
if [ -f "$BASE" ] && [ -r "$BASE" ]; then
  BASE_OUT="$(printf '%s' "$STDIN_JSON" | $TO_BASE bash "$BASE" 2>/dev/null)"
fi
printf '%s' "$BASE_OUT"

PLAN_OUT="$(printf '%s' "$STDIN_JSON" | $TO_BAR python3 "$HERE/plan-progress.py" 2>/dev/null)"
if [ -n "$PLAN_OUT" ]; then
  [ -n "$BASE_OUT" ] && printf '\n'
  printf '%s' "$PLAN_OUT"
fi

exit 0
