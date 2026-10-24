#!/bin/bash
# Silence-when-broken sweep for plan-progress.py.
#
# The renderer runs inside the user's status line on every redraw, in every
# project. Its one hard contract is that a broken environment produces a
# MISSING bar, never a noisy one: empty stdout, empty stderr, exit 0.
#
# Why a sweep and not a sampled case: the discovery surface (records config,
# resolver, records home, scan cache) has many ways to be broken, and a suite
# of hand-picked inputs covers only the ones its author thought of. This file
# enumerates a corpus of broken environments and runs EVERY member, so "silence
# holds across the discovery surface" is an executed sweep, not a claim about
# one input.
#
# EVERY CASE RUNS TWO LANES, and the second one is the point:
#
#   lane A — `python3 plan-progress.py`, the shipped entry point. Proves the
#            live redraw path stays silent with garbage sitting nearby.
#   lane B — a driver that calls records_plans_dir() -> discover_plans()
#            DIRECTLY, with no guard around them.
#
# Lane A alone cannot catch an exception from the discovery surface. main() ends in
# `except Exception: sys.exit(0)`, so lane A stays green whether these functions
# degrade gracefully or throw. Lane B is therefore deliberately UNGUARDED: an
# escaping exception lands on stderr as a traceback and the assertion below
# fails. What is under test is that the discovery surface degrades INTERNALLY,
# not that a catch-all hides it.
#
# Usage: bash test-plan-progress-corpus.sh    (exit 0 = pass)
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../scripts/plan-progress.py"
[ -f "$SCRIPT" ] || { echo "FAIL: cannot find plan-progress.py at $SCRIPT"; exit 1; }

TMP="$(mktemp -d)"
trap 'chmod -R u+rwX "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT

fail=0
cases=0

# Lane B's driver. Only the stdin parsing is guarded — everything from
# records_plans_dir() onward is the surface under test and must degrade on its
# own, so anything it raises escapes here as a traceback on stderr.
DRIVER="$TMP/discovery-driver.py"
cat > "$DRIVER" <<'PYEOF'
import importlib.util, json, os, sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("pp", os.environ["PP_SCRIPT"])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)          # unguarded: import itself must not raise

try:
    data = json.loads(sys.stdin.read() or "{}")
    if not isinstance(data, dict):
        data = {}
except Exception:
    data = {}
cwd = data.get("cwd") or "."

root = Path(cwd)
state = m.find_state(cwd)
pinned = None
if state is not None:
    try:
        pinned = Path(json.loads(state.read_text())["plan"])
    except Exception:
        pinned = None                # a corrupt state file pins nothing

plans = m.records_plans_dir(root)
if plans is None:
    print("RESOLVED=none")           # a degraded resolve, reached without raising
else:
    found = m.discover_plans(plans, pinned=pinned,
                             cache_file=root / ".claude" / m.CACHE_NAME)
    print("DISCOVERED=%d" % len(found))
PYEOF

# Carries a `[~]` BLOCKED gate check so every case in the sweep exercises the
# gate-state surface — blocked_gate_marker() and status_lag() both read the plan
# text on the render path. A plan without one would leave that surface out of
# every case, and the sweep would claim silence over code it never reached.
PLAN_BODY='### Task 1.1: a
- **Status:** [x]

### Task 1.2: b
- **Status:** [ ]

### Stage 1 Gate

- [x] the host suite is green
- [~] the device suite ran on hardware
'

# build_env <name> -> echoes the root; sets up a HOME whose staged-planning config names
# a records resolver, the resolver (it prints <root>/records), the records home's plans/,
# and a repo whose state file pins the plan there.
build_env() {
  local name="$1"
  local root="$TMP/$name"
  mkdir -p "$root/home/.config/staged-planning" "$root/repo/.claude" "$root/records/plans"
  printf '%s' "$PLAN_BODY" > "$root/records/plans/2026-01-01-x-plan.md"
  printf '#!/bin/sh\necho "%s/records"\n' "$root" > "$root/resolver.sh"
  chmod 755 "$root/resolver.sh"
  printf 'records_resolver: [%s/resolver.sh]\n' "$root" > "$root/home/.config/staged-planning/config.yaml"
  printf '{"plan": "%s/records/plans/2026-01-01-x-plan.md", "phase": "task", "stage": 1, "task": "1.1", "task_desc": "x"}\n' \
    "$root" > "$root/repo/.claude/plan-progress.json"
  echo "$root"
}

# run_lane <label> <lane-name> <repo-root> <home> <python-target>
# Asserts exit 0 and EMPTY stderr. stdout may be empty or a bar, but must never
# carry a traceback — a rendered bar is fine, a Python traceback never is.
# Only `Traceback` is matched: a broader `*"Error"*` pattern fails on a
# legitimate task description containing the word (e.g. "Handle Error case"),
# and the empty-stderr check already catches the real thing.
run_lane() {
  local label="$1" lane="$2" repo="$3" home="$4" target="$5"
  local out err rc bad=0
  err="$TMP/err.$cases.$lane"
  out="$(printf '{"cwd": "%s"}' "$repo" | env -u STAGED_PLANNING_CONFIG -u XDG_CONFIG_HOME \
         HOME="$home" PP_SCRIPT="$SCRIPT" python3 "$target" 2>"$err")"
  rc=$?
  [ "$rc" != 0 ] && { echo "FAIL: $label [$lane] — exit $rc, wanted 0"; bad=1; }
  [ -s "$err" ] && { echo "FAIL: $label [$lane] — stderr not empty: $(head -c 300 "$err")"; bad=1; }
  case "$out" in
    *Traceback*) echo "FAIL: $label [$lane] — traceback on stdout: $out"; bad=1 ;;
  esac
  return $bad
}

# expect_quiet <label> <repo-root> <home>
# Both lanes must be silent. Lane B is what makes this a claim about the
# discovery surface itself, not only about the guarded entry point.
expect_quiet() {
  local label="$1" repo="$2" home="$3"
  cases=$((cases + 1))
  local bad=0
  run_lane "$label" "entry" "$repo" "$home" "$SCRIPT"  || bad=1
  run_lane "$label" "discovery" "$repo" "$home" "$DRIVER" || bad=1
  if [ "$bad" = 1 ]; then fail=1; else echo "  ok: $label"; fi
}

echo "silence-when-broken corpus:"

# 0. the healthy baseline — proves each lane can actually reach its subject, so a
#    green sweep is not just "everything is broken everywhere". One guard per
#    lane: a lane that silently no-ops would otherwise report every case as a
#    pass, which is the exact failure this file exists to catch.
R="$(build_env healthy)"
out="$(printf '{"cwd": "%s"}' "$R/repo" | env -u STAGED_PLANNING_CONFIG -u XDG_CONFIG_HOME \
       HOME="$R/home" python3 "$SCRIPT" 2>/dev/null)"
if [ -z "$out" ]; then
  echo "FAIL: baseline [entry] — expected a rendered bar, got nothing (lane A would be vacuous)"
  fail=1
else
  echo "  ok: baseline renders a bar (lane A is not vacuously green)"
fi
cases=$((cases + 1))

drv="$(printf '{"cwd": "%s"}' "$R/repo" | env -u STAGED_PLANNING_CONFIG -u XDG_CONFIG_HOME \
       HOME="$R/home" PP_SCRIPT="$SCRIPT" python3 "$DRIVER" 2>/dev/null)"
case "$drv" in
  DISCOVERED=[1-9]*)
    echo "  ok: baseline reaches discovery — $drv (lane B is not vacuously green)" ;;
  *)
    echo "FAIL: baseline [discovery] — expected DISCOVERED=<n>=1, got '${drv:-<nothing>}'."
    echo "      Lane B is not reaching discover_plans, so every silence claim it"
    echo "      makes below is about code it never ran."
    fail=1 ;;
esac
cases=$((cases + 1))

# 1. no records config at all (records fall to the repo, which has no docs/plans)
R="$(build_env no-config)"; rm -f "$R/home/.config/staged-planning/config.yaml"
expect_quiet "no staged-planning config" "$R/repo" "$R/home"

# 2. the resolver the config names is missing, exits 2, or prints garbage
R="$(build_env no-resolver)"; rm -f "$R/resolver.sh"
expect_quiet "configured resolver missing" "$R/repo" "$R/home"
R="$(build_env resolver-exit-2)"; printf '#!/bin/sh\necho unreachable >&2\nexit 2\n' > "$R/resolver.sh"
expect_quiet "resolver exits 2 (store unreachable)" "$R/repo" "$R/home"
R="$(build_env resolver-garbage)"; printf '#!/bin/sh\necho relative/path\necho two\n' > "$R/resolver.sh"
expect_quiet "resolver prints garbage" "$R/repo" "$R/home"

# 3. malformed config
R="$(build_env bad-config)"; printf 'records_resolver: {{{ nope\n' > "$R/home/.config/staged-planning/config.yaml"
expect_quiet "malformed staged-planning config" "$R/repo" "$R/home"
R="$(build_env not-a-list)"; printf 'records_resolver: just-a-string\n' > "$R/home/.config/staged-planning/config.yaml"
expect_quiet "records_resolver is not a list" "$R/repo" "$R/home"

# 4. records home missing, and records home unreadable
R="$(build_env no-records)"; rm -rf "$R/records"
expect_quiet "records home does not exist" "$R/repo" "$R/home"
R="$(build_env locked-records)"; chmod 000 "$R/records"
expect_quiet "records home unreadable" "$R/repo" "$R/home"
chmod 755 "$R/records" 2>/dev/null

# 5. corrupt scan cache, in several shapes
for shape in 'truncated' 'binary' 'wrongtype'; do
  R="$(build_env "bad-cache-$shape")"
  case "$shape" in
    truncated) printf '{"version": 1, "signat' > "$R/repo/.claude/plan-progress-cache.json" ;;
    binary)    printf '\x00\x01\x02 junk'      > "$R/repo/.claude/plan-progress-cache.json" ;;
    wrongtype) printf '[1,2,3]'                > "$R/repo/.claude/plan-progress-cache.json" ;;
  esac
  expect_quiet "corrupt scan cache ($shape)" "$R/repo" "$R/home"
done

# 6. corrupt / empty / wrong-shaped state file
R="$(build_env bad-state)"; printf '{not json' > "$R/repo/.claude/plan-progress.json"
expect_quiet "corrupt state file" "$R/repo" "$R/home"
R="$(build_env empty-state)"; : > "$R/repo/.claude/plan-progress.json"
expect_quiet "empty state file" "$R/repo" "$R/home"
R="$(build_env array-state)"; printf '[]' > "$R/repo/.claude/plan-progress.json"
expect_quiet "state file is a JSON array, not an object" "$R/repo" "$R/home"

# 7. the plan the state file names is gone
R="$(build_env plan-deleted)"; rm -f "$R/records/plans/2026-01-01-x-plan.md"
expect_quiet "plan file deleted out from under the state file" "$R/repo" "$R/home"

# 8. plans dir unreadable mid-run
R="$(build_env locked-plans)"; chmod 000 "$R/records/plans"
expect_quiet "plans directory unreadable" "$R/repo" "$R/home"
chmod 755 "$R/records/plans" 2>/dev/null

# 9. plan file present but unreadable
R="$(build_env locked-plan)"; chmod 000 "$R/records/plans/2026-01-01-x-plan.md"
expect_quiet "plan file unreadable" "$R/repo" "$R/home"
chmod 644 "$R/records/plans/2026-01-01-x-plan.md" 2>/dev/null

# 10. read-only .claude (cache cannot be written)
R="$(build_env ro-claude)"; chmod 500 "$R/repo/.claude"
expect_quiet "read-only .claude (cache unwritable)" "$R/repo" "$R/home"
chmod 700 "$R/repo/.claude" 2>/dev/null

# 11. HOME itself unset / pointing nowhere
R="$(build_env no-home)"
expect_quiet "HOME points at a nonexistent directory" "$R/repo" "$TMP/does-not-exist"

# 12. garbage on stdin
for stdin_val in '' 'not json at all' '{}' '[]' '{"cwd": null}'; do
  cases=$((cases + 1))
  err="$TMP/err.stdin.$cases"
  out="$(printf '%s' "$stdin_val" | HOME="$TMP/healthy/home" python3 "$SCRIPT" 2>"$err")"
  rc=$?
  if [ "$rc" != 0 ] || [ -s "$err" ]; then
    echo "FAIL: stdin=${stdin_val:-<empty>} — exit $rc, stderr: $(head -c 120 "$err")"; fail=1
  else
    echo "  ok: stdin=${stdin_val:-<empty>} handled quietly"
  fi
done

echo
if [ "$fail" -eq 0 ]; then
  echo "OK — $cases corpus members, every one silent (exit 0, clean stderr, no traceback)"
  exit 0
fi
echo "FAILED"
exit 1
