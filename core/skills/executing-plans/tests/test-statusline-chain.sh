#!/bin/bash
# Regression guard for statusline-chain.sh's sibling-resolution and
# fault-tolerance contract.
#
# What it protects: statusline-chain.sh is SELF-LOCATING (finds
# plan-progress.py as a literal sibling via BASH_SOURCE) so it works
# identically from a dev checkout and from a plugin-marketplace install, and
# it is fault-SILENT (a missing/broken base or a missing/broken
# plan-progress.py must never leak an error onto stdout/stderr or take down
# the whole statusline) since a statusline that errors is worse than one
# that is silent. Both properties are easy to break with a well-meaning edit
# (hardcoding a dev path, or letting a sub-script's failure propagate) with
# nothing else here to catch it.
#
# Runs a COPY of the shipped script in a scratch dir with stub siblings, so
# tests control exactly what "the base statusline" and "plan-progress.py" do
# without touching the developer's real ~/.claude/statusline.sh. Requirement
# 7 (no hardcoded dev path) is the one check run against the SHIPPED file
# directly, since a copy would launder the very thing it's checking for.
#
# Usage: bash test-statusline-chain.sh    (exit 0 = pass)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHAIN_SRC="$SCRIPT_DIR/../scripts/statusline-chain.sh"
# tests -> executing-plans -> skills -> core -> repo-root
REPO="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

[ -f "$CHAIN_SRC" ] || { echo "FAIL: cannot find statusline-chain.sh at $CHAIN_SRC"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

WORK="$TMP/work"
mkdir -p "$WORK"
cp "$CHAIN_SRC" "$WORK/statusline-chain.sh"
chmod +x "$WORK/statusline-chain.sh"

fail=0

# --- stub siblings ------------------------------------------------------

stub_plan() { # stub_plan <bar|empty|nonzero|traceback|missing|unreadable|hang>
  rm -f "$WORK/plan-progress.py"
  case "$1" in
    bar)        printf 'import sys\nsys.stdin.read()\nprint("PLANBAR", end="")\n' > "$WORK/plan-progress.py" ;;
    empty)      printf 'import sys\nsys.stdin.read()\n' > "$WORK/plan-progress.py" ;;
    nonzero)    printf 'import sys\nsys.stdin.read()\nsys.exit(1)\n' > "$WORK/plan-progress.py" ;;
    traceback)  printf 'import sys\nsys.stdin.read()\nraise RuntimeError("boom")\n' > "$WORK/plan-progress.py" ;;
    hang)       printf 'import sys,time\nsys.stdin.read()\ntime.sleep(30)\nprint("NEVER", end="")\n' > "$WORK/plan-progress.py" ;;
    missing)    : ;; # already removed above
    unreadable) printf 'print("PLANBAR")\n' > "$WORK/plan-progress.py"; chmod 000 "$WORK/plan-progress.py" ;;
  esac
}

stub_base() { # stub_base <ok|nonzero|absent>
  rm -f "$WORK/base.sh"
  case "$1" in
    ok)      printf '#!/bin/bash\ncat >/dev/null\nprintf "BASEOUT"\n' > "$WORK/base.sh"; chmod +x "$WORK/base.sh" ;;
    nonzero) printf '#!/bin/bash\ncat >/dev/null\nprintf "BASEOUT"\nexit 3\n' > "$WORK/base.sh"; chmod +x "$WORK/base.sh" ;;
    absent)  : ;; # leave missing
  esac
}

# run_chain <cwd> <base-path> -> "<rc>|<stdout>", stderr left in $TMP/err.log
run_chain() {
  local dir="$1" base="$2" out rc=0
  out="$(cd "$dir" && PLAN_STATUSLINE_BASE="$base" bash "$WORK/statusline-chain.sh" <<<'{}' 2>"$TMP/err.log")" || rc=$?
  printf '%s|%s' "$rc" "$out"
}

check() { # check <label> <want-rc> <want-stdout> <result "rc|out">
  local label="$1" want_rc="$2" want_out="$3" res="$4" rc out
  rc="${res%%|*}"; out="${res#*|}"
  if [ "$rc" != "$want_rc" ]; then
    echo "FAIL: $label — exit $rc, wanted $want_rc"; fail=1; return
  fi
  if [ "$out" != "$want_out" ]; then
    echo "FAIL: $label — stdout '$out', wanted '$want_out'"; fail=1; return
  fi
  echo "  ok: $label"
}

ABSENT_BASE="$WORK/does-not-exist.sh"

# 1. sibling resolution holds from three different working directories -----
echo "case 1 — plan-progress.py sibling is found regardless of cwd"
stub_plan bar
for dir in / /tmp "$REPO"; do
  check "sibling resolved from cwd=$dir" 0 "PLANBAR" "$(run_chain "$dir" "$ABSENT_BASE")"
done

# 2. PLAN_STATUSLINE_BASE is honored ----------------------------------------
echo "case 2 — PLAN_STATUSLINE_BASE overrides the default base path"
stub_base ok
stub_plan empty
check "custom base honored" 0 "BASEOUT" "$(run_chain "$WORK" "$WORK/base.sh")"

# 3. missing base statusline -> plan bar alone, empty stderr, exit 0 -------
echo "case 3 — missing base statusline yields the plan bar alone"
stub_plan bar
res="$(run_chain "$WORK" "$ABSENT_BASE")"
check "plan bar alone when base is missing" 0 "PLANBAR" "$res"
if [ -s "$TMP/err.log" ]; then
  echo "FAIL: missing base produced stderr: $(cat "$TMP/err.log")"; fail=1
else
  echo "  ok: stderr empty when base is missing"
fi

# 4. a base that exits non-zero does not suppress the plan bar -------------
echo "case 4 — non-zero base exit does not suppress the plan bar"
stub_base nonzero
stub_plan bar
check "plan bar survives a failing base" 0 "BASEOUT
PLANBAR" "$(run_chain "$WORK" "$WORK/base.sh")"

# 5. plan-progress.py faults never leak onto stdout/stderr or break exit ---
echo "case 5 — a broken plan-progress.py degrades to base-only output"
stub_base ok
for kind in missing unreadable nonzero traceback; do
  stub_plan "$kind"
  res="$(run_chain "$WORK" "$WORK/base.sh")"
  rc="${res%%|*}"; out="${res#*|}"
  ok=1
  [ "$rc" = 0 ] || { echo "FAIL: plan-progress.py=$kind — exit $rc, wanted 0"; fail=1; ok=0; }
  [ "$out" = "BASEOUT" ] || { echo "FAIL: plan-progress.py=$kind — stdout '$out', wanted 'BASEOUT'"; fail=1; ok=0; }
  if grep -qi 'traceback' <<<"$out"; then
    echo "FAIL: plan-progress.py=$kind — traceback leaked onto stdout"; fail=1; ok=0
  fi
  # $TMP/err.log is (re)written by run_chain's own stderr redirect above; the
  # suite's header claims stderr stays clean for all four fault kinds, so this
  # is the check that makes the claim true.
  if [ -s "$TMP/err.log" ]; then
    echo "FAIL: plan-progress.py=$kind — stderr not empty: $(cat "$TMP/err.log")"; fail=1; ok=0
  fi
  [ "$ok" = 1 ] && echo "  ok: plan-progress.py=$kind degrades cleanly (stdout AND stderr clean)"
done

# 6. an empty plan-progress.py output leaves NO trailing blank line --------
echo "case 6 — empty plan-progress.py output leaves no trailing blank line"
stub_base ok
stub_plan empty
printf 'BASEOUT' > "$TMP/expected.out"
(cd "$WORK" && PLAN_STATUSLINE_BASE="$WORK/base.sh" bash "$WORK/statusline-chain.sh" \
  <<<'{}' >"$TMP/actual.out" 2>"$TMP/err.log")
rc=$?
if [ "$rc" != 0 ]; then
  echo "FAIL: exact-output case — exit $rc, wanted 0"; fail=1
elif ! cmp -s "$TMP/expected.out" "$TMP/actual.out"; then
  echo "FAIL: exact-output case — byte mismatch (trailing newline or extra bytes)"
  echo "  expected: $(od -c "$TMP/expected.out" | head -3)"
  echo "  actual:   $(od -c "$TMP/actual.out" | head -3)"
  fail=1
else
  echo "  ok: output is exactly the base's bytes, no trailing blank line"
fi

# 7. no hardcoded developer checkout path in the SHIPPED script ------------
echo "case 7 — shipped script contains no hardcoded \$HOME/dev path"
n="$(grep -c '\$HOME/dev' "$CHAIN_SRC" || true)"
if [ "${n:-0}" -eq 0 ]; then
  echo "  ok: no \$HOME/dev in $CHAIN_SRC"
else
  echo "FAIL: found \$HOME/dev in the shipped script ($n occurrence(s))"; fail=1
fi

# 8. the DEFAULT base path (PLAN_STATUSLINE_BASE unset) actually fires -------
# Every case above passes PLAN_STATUSLINE_BASE explicitly, so only this case
# exercises the `${PLAN_STATUSLINE_BASE:-$HOME/.claude/statusline.sh}` default
# branch — the one essentially every real user relies on.
echo "case 8 — default base path (\$HOME/.claude/statusline.sh) fires when PLAN_STATUSLINE_BASE is unset"
DEFAULT_HOME="$TMP/default-home"
mkdir -p "$DEFAULT_HOME/.claude"
printf '#!/bin/bash\ncat >/dev/null\nprintf "DEFAULTBASE"\n' > "$DEFAULT_HOME/.claude/statusline.sh"
chmod +x "$DEFAULT_HOME/.claude/statusline.sh"
stub_plan empty
out="$(cd "$WORK" && env -u PLAN_STATUSLINE_BASE HOME="$DEFAULT_HOME" bash "$WORK/statusline-chain.sh" <<<'{}' 2>"$TMP/default-err.log")"
rc=$?
if [ "$rc" != 0 ]; then
  echo "FAIL: default base path — exit $rc, wanted 0"; fail=1
elif [ "$out" != "DEFAULTBASE" ]; then
  echo "FAIL: default base path — stdout '$out', wanted 'DEFAULTBASE'"; fail=1
elif [ -s "$TMP/default-err.log" ]; then
  echo "FAIL: default base path — stderr not empty: $(cat "$TMP/default-err.log")"; fail=1
else
  echo "  ok: default base path (\$HOME/.claude/statusline.sh) fires when PLAN_STATUSLINE_BASE is unset"
fi

echo "case 9 — a HANGING base statusline does not hang the redraw"
# A statusline is redrawn constantly, so an unbounded base that blocks freezes
# every redraw indefinitely with nothing to explain it — worse than a missing
# line. Both subprocesses are bounded; the test overrides the bounds so it can
# assert the behavior in ~2s rather than sitting through the shipped default.
# Skipped rather than silently passing where no timeout binary exists, so the
# skip is visible instead of looking like a pass.
if command -v timeout >/dev/null 2>&1 || command -v gtimeout >/dev/null 2>&1; then
  HANG_BASE="$TMP/hang-base.sh"
  printf '#!/bin/bash\ncat >/dev/null\nsleep 30\nprintf "NEVER"\n' > "$HANG_BASE"
  chmod +x "$HANG_BASE"
  stub_plan bar
  start=$(date +%s)
  out="$(cd "$WORK" && PLAN_STATUSLINE_BASE="$HANG_BASE" \
        PLAN_STATUSLINE_BASE_TIMEOUT=2 bash "$WORK/statusline-chain.sh" \
        <<<'{}' 2>"$TMP/hang-err.log")"
  rc=$?
  elapsed=$(( $(date +%s) - start ))
  if [ "$elapsed" -ge 10 ]; then
    echo "FAIL: hanging base — took ${elapsed}s, wanted a bounded return"; fail=1
  elif [ "$rc" != 0 ]; then
    echo "FAIL: hanging base — exit $rc, wanted 0"; fail=1
  elif [ "$out" != "PLANBAR" ]; then
    echo "FAIL: hanging base — stdout '$out', wanted the plan bar alone ('PLANBAR')"; fail=1
  elif [ -s "$TMP/hang-err.log" ]; then
    echo "FAIL: hanging base — stderr not empty: $(cat "$TMP/hang-err.log")"; fail=1
  else
    echo "  ok: a hanging base is cut off (${elapsed}s) and the plan bar still renders"
  fi

  # A hanging RENDERER must not take the base down with it — the base is the
  # user's own status line and matters more than our bar.
  printf '#!/bin/bash\ncat >/dev/null\nprintf "OKBASE"\n' > "$TMP/ok-base.sh"
  chmod +x "$TMP/ok-base.sh"
  stub_plan hang
  start=$(date +%s)
  out="$(cd "$WORK" && PLAN_STATUSLINE_BASE="$TMP/ok-base.sh" \
        PLAN_STATUSLINE_BAR_TIMEOUT=2 bash "$WORK/statusline-chain.sh" \
        <<<'{}' 2>"$TMP/hang2-err.log")"
  elapsed=$(( $(date +%s) - start ))
  if [ "$elapsed" -ge 10 ]; then
    echo "FAIL: hanging renderer — took ${elapsed}s, wanted a bounded return"; fail=1
  elif [ "$out" != "OKBASE" ]; then
    echo "FAIL: hanging renderer — stdout '$out', wanted the base alone ('OKBASE')"; fail=1
  elif [ -s "$TMP/hang2-err.log" ]; then
    echo "FAIL: hanging renderer — stderr not empty: $(cat "$TMP/hang2-err.log")"; fail=1
  else
    echo "  ok: a hanging plan-progress.py is cut off (${elapsed}s), base survives"
  fi
else
  echo "  SKIP: neither timeout nor gtimeout on this host — nothing bounds the base here"
fi

echo "case 10 — the shipped default bound does not truncate a self-bounding base"
# The reason for this check: a base that legitimately
# does slow work already bounds ITSELF (for example with
# `curl -s --max-time 10`), so a snug wrapper bound would cut off a base working
# exactly as designed. The wrapper's default must sit ABOVE any such self-bound,
# and this asserts that relationship rather than the literal number.
DEFAULT_BASE_TO=$(sed -n 's/^BASE_TIMEOUT="${PLAN_STATUSLINE_BASE_TIMEOUT:-\([0-9]*\)}"/\1/p' "$CHAIN_SRC")
if [ -z "$DEFAULT_BASE_TO" ]; then
  echo "FAIL: could not read the default base timeout out of the shipped script"; fail=1
elif [ "$DEFAULT_BASE_TO" -le 10 ]; then
  echo "FAIL: default base timeout ${DEFAULT_BASE_TO}s would truncate a base self-bounded at 10s"; fail=1
else
  echo "  ok: default base bound (${DEFAULT_BASE_TO}s) clears a 10s self-bounded base"
fi

[ "$fail" -eq 0 ] || { echo; echo "FAILED"; exit 1; }
echo
echo "OK — sibling resolution is cwd-independent, PLAN_STATUSLINE_BASE is honored,"
echo "     the default \$HOME/.claude/statusline.sh path fires when unset,"
echo "     missing/failing base or plan-progress.py never breaks the chain, a"
echo "     hanging base is bounded rather than freezing the redraw, and the"
echo "     shipped script carries no hardcoded developer checkout path."
