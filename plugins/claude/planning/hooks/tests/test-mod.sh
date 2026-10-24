#!/usr/bin/env bash
# test-mod.sh — the planning plugin's hooks module (planning/hooks/mod/), checked by
# the engine itself: `claude plugin validate` reads the manifest and the module's
# source the way a session will (including every `$.state` key against
# types/index.d.ts), and `claude plugin test` runs the mod's *.test.ts(x) files.
#
# The mod's own suites are named *.test.ts(x), which scripts/run-tests.sh does not
# discover (it finds test-*.py / test-*.sh). This wrapper is how they are reached.
#
# A missing `claude` binary is a FAILURE, never a skip: a runner that reports green
# without having run the mod's tests is the defect this rule exists to prevent.

set -uo pipefail

PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# In this repo's source tree the mod lives in the Claude layer (hosts/claude/add/), which
# is not a whole plugin: `claude plugin validate|test` need core/ laid under it. The built
# copy is exactly that, and `build.py --check` proves it matches these sources — so check
# that first, then validate and test the built copy.
if [ ! -d "$PLUGIN/skills" ]; then
  REPO="$(cd "$PLUGIN/../../.." && pwd)"
  if ! python3 "$REPO/build/build.py" --host claude --check; then
    echo "FAIL: plugins/claude/planning is stale against its sources — run build/build.py --host claude" >&2
    exit 1
  fi
  PLUGIN="$REPO/plugins/claude/planning"
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "FAIL: the claude CLI is not on PATH; the mod's validate and test runs cannot execute" >&2
  exit 1
fi

rc=0

echo "== claude plugin validate $PLUGIN"
if ! claude plugin validate "$PLUGIN"; then
  echo "FAIL: claude plugin validate" >&2
  rc=1
fi

# The stage-boundary note goes through $.session.append, never a system-prompt
# section: a prompt.compose hook would rewrite the whole cached prefix.
echo "== no prompt.compose hook"
if ! report="$(claude plugin validate "$PLUGIN" 2>&1)"; then
  echo "FAIL: claude plugin validate (for the hook list)" >&2
  rc=1
elif grep -q 'prompt\.compose' <<<"$report"; then
  echo "FAIL: the mod registers a prompt.compose hook" >&2
  rc=1
elif grep -rlE "['\"]prompt\.compose['\"]" "$PLUGIN/hooks/mod"; then
  echo "FAIL: the mod's source names the prompt.compose event" >&2
  rc=1
fi

echo "== claude plugin test $PLUGIN"
if ! claude plugin test "$PLUGIN"; then
  echo "FAIL: claude plugin test" >&2
  rc=1
fi

exit "$rc"
