#!/bin/bash
# The Cursor statusline-chain.sh, run as Cursor's CLI runs a statusLine command: a JSON
# payload on stdin, the user's own base statusline first, the plan bar on the next line.
#
# What the Cursor fork changes from core: its default base is $HOME/.cursor/statusline.sh,
# not $HOME/.claude/statusline.sh. Cursor writes no statusline script of its own, so a
# fork that kept the core default would chain a Claude Code statusline into a Cursor
# footer, or show the bar alone where the user keeps a Cursor one.
#
# Builds the Cursor plugin into a scratch dir and runs a COPY of the BUILT chain script
# beside a stub plan-progress.py, so each case controls what the bar prints and nothing
# depends on the real renderer. HOME is a scratch dir: nothing reads or writes the real one.
#
#   default base   ~/.cursor/statusline.sh runs and ~/.claude/statusline.sh never does;
#                  with only ~/.claude/statusline.sh present the bar renders alone
#   override       PLAN_STATUSLINE_BASE wins over the default
#   stdin          the base and the bar each read the same payload bytes
#   no bar         a base with no plan in flight prints the base alone, no stray newline
#   shipped        the built chain is the fork, and names no ~/.claude path
#
# Usage: bash hosts/cursor/tests/test-cursor-statusline-chain.sh    (exit 0 = pass)
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
FORK_SRC="$REPO/hosts/cursor/overrides/skills/executing-plans/scripts/statusline-chain.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
OUT="$TMP/out"
if ! python3 "$REPO/build/build.py" --host cursor --no-lock-check --out "$OUT" >"$TMP/build.log" 2>&1; then
  echo "FAIL: the Cursor build failed"; sed 's/^/     | /' "$TMP/build.log" | head -20
  echo "FAILED: 1"; exit 1
fi
CHAIN_SRC="$OUT/skills/executing-plans/scripts/statusline-chain.sh"

pass=0
fails=0
ok()   { echo "ok   $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL $1"; [ -n "${2:-}" ] && printf '     | %s\n' "$2"; fails=$((fails + 1)); }

WORK="$TMP/work"
mkdir -p "$WORK"
cp "$CHAIN_SRC" "$WORK/statusline-chain.sh"
chmod +x "$WORK/statusline-chain.sh"
# The bar's stand-in: records the stdin it was given, prints a fixed bar.
cat >"$WORK/plan-progress.py" <<'EOF'
import os, sys
data = sys.stdin.read()
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bar-stdin"), "w") as fh:
    fh.write(data)
if os.environ.get("STUB_BAR", "1") == "1":
    print("PLANBAR", end="")
EOF

H="$TMP/home"
mkbase() { # mkbase <path> <text>: a base statusline that records its stdin and prints <text>
  mkdir -p "$(dirname "$1")"
  printf '#!/bin/bash\ncat >"%s.stdin"\nprintf "%s"\n' "$1" "$2" >"$1"
  chmod +x "$1"
}
run() { # run [VAR=val ...]: the chain with HOME=$H, stdin from $PAYLOAD
  (cd "$TMP" && env -u PLAN_STATUSLINE_BASE HOME="$H" "$@" bash "$WORK/statusline-chain.sh" \
     <<<"$PAYLOAD" 2>"$TMP/err.log")
}
NL=$'\n'
PAYLOAD='{"session_id":"s-1","model":{"name":"m"},"workspace":{"current_dir":"/w"}}'

# ---- default base: ~/.cursor/statusline.sh
rm -rf "$H"
mkbase "$H/.cursor/statusline.sh" "CURSORBASE"
mkbase "$H/.claude/statusline.sh" "CLAUDEBASE"
got="$(run)"
if [ "$got" = "CURSORBASE${NL}PLANBAR" ]; then
  ok "the default base is ~/.cursor/statusline.sh, chained above the bar"
else
  bad "the default base is ~/.cursor/statusline.sh, chained above the bar" "got: $got"
fi
if [ ! -e "$H/.claude/statusline.sh.stdin" ]; then
  ok "~/.claude/statusline.sh is never run on Cursor"
else
  bad "~/.claude/statusline.sh is never run on Cursor" "it ran"
fi

rm -rf "$H"
mkbase "$H/.claude/statusline.sh" "CLAUDEBASE"
got="$(run)"
if [ "$got" = "PLANBAR" ]; then
  ok "with no ~/.cursor/statusline.sh the bar renders alone"
else
  bad "with no ~/.cursor/statusline.sh the bar renders alone" "got: $got"
fi

# ---- PLAN_STATUSLINE_BASE wins over the default
rm -rf "$H"
mkbase "$H/.cursor/statusline.sh" "CURSORBASE"
mkbase "$TMP/mine/base.sh" "MINE"
got="$(run PLAN_STATUSLINE_BASE="$TMP/mine/base.sh")"
if [ "$got" = "MINE${NL}PLANBAR" ]; then
  ok "PLAN_STATUSLINE_BASE overrides the default base"
else
  bad "PLAN_STATUSLINE_BASE overrides the default base" "got: $got"
fi

# ---- both consumers read the same stdin bytes
rm -rf "$H" "$WORK/bar-stdin"
mkbase "$H/.cursor/statusline.sh" "CURSORBASE"
run >/dev/null
if [ "$(cat "$H/.cursor/statusline.sh.stdin" 2>/dev/null)" = "$PAYLOAD" ] \
   && [ "$(cat "$WORK/bar-stdin" 2>/dev/null)" = "$PAYLOAD" ]; then
  ok "the base and the bar each read the payload verbatim"
else
  bad "the base and the bar each read the payload verbatim" \
      "base: $(cat "$H/.cursor/statusline.sh.stdin" 2>/dev/null) bar: $(cat "$WORK/bar-stdin" 2>/dev/null)"
fi

# ---- no plan in flight: the base alone
got="$(run STUB_BAR=0; printf x)"
if [ "$got" = "CURSORBASEx" ]; then
  ok "no bar: the base prints alone, with no trailing newline"
else
  bad "no bar: the base prints alone, with no trailing newline" "got: ${got%x}"
fi
if [ ! -s "$TMP/err.log" ]; then
  ok "nothing is written to stderr"
else
  bad "nothing is written to stderr" "$(head -3 "$TMP/err.log")"
fi

# ---- the shipped copy is the fork
if cmp -s "$CHAIN_SRC" "$FORK_SRC"; then
  ok "the built statusline-chain.sh is the Cursor override, byte for byte"
else
  bad "the built statusline-chain.sh is the Cursor override, byte for byte"
fi
if ! grep -q '\.claude/' "$WORK/statusline-chain.sh"; then
  ok "the chain script names no ~/.claude path"
else
  bad "the chain script names no ~/.claude path" "$(grep -n '\.claude/' "$WORK/statusline-chain.sh" | head -3)"
fi

if [ "$fails" -eq 0 ]; then
  echo "all passed ($pass)"
  exit 0
fi
echo "FAILED: $fails"
exit 1
