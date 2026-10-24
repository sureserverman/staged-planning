#!/usr/bin/env bash
# Fail-fast suite — run directly (repo convention):
#
#     bash core/skills/executing-plans/tests/test-suite-fail-fast.sh
#
# WHAT THIS SUITE IS REALLY GUARDING. The mutation battery (battery-proof-tools.py) runs
# the four proof-tool suites once per mutation, and a killed mutation needs only the
# FIRST failing check. With SUITE_FAIL_FAST=1 each suite prints its first `  FAIL` line
# and exits 1 at once. Two failures matter: a suite that runs on past its first failure
# (the battery saves nothing), and a suite whose DEFAULT mode changed (every other caller
# — run-tests.sh, a person reading a red suite — now sees less).
#
# For each suite, a copy of the plugin tree gets one known guard broken: the battery's
# own mutation, by label, chosen because it makes that suite report several failures.
# The suite then runs three ways on that broken copy: with its fail-fast step removed
# (the suite as it reads without fail-fast), as it is now in default mode, and now with
# SUITE_FAIL_FAST=1.
#
# The text without fail-fast is built at run time from the current suite, so the suite
# needs no git history and runs in any copy of the tree (an archive, an installed
# plugin). Each suite carries exactly one fail-fast step — the `SUITE_FAIL_FAST` test at
# the end of its `bad()` — and the builder removes that one step and nothing else. It
# refuses when it finds no such step, or more than one, or any mention of
# SUITE_FAIL_FAST left after the removal: a copy that still holds the step would compare
# the suite with itself and prove nothing.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BATTERY="$HERE/battery-proof-tools.py"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok    $1"; }
bad() { fail=$((fail+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && printf '        | %s\n' "${2:0:700}"; }
d=""
trap '[ -n "$d" ] && rm -rf "$d"' EXIT

echo "suite fail-fast — SUITE_FAIL_FAST=1 stops at the first FAIL; default mode unchanged"
echo

# suite (relative to planning/) | battery label whose mutation that suite reports several
# times | floor. The floor is the number of failures the suite reports under that break
# in default mode (measured). The text built at run time differs from the
# current suite only by the fail-fast step, so a change elsewhere that cut default mode
# short would cut both short alike; the floor is what still catches it.
CASES=(
  "skills/executing-plans/tests/test-plan-flip-audit.py|strong tier voids alone -> demoted to advisory|18"
  "skills/executing-plans/tests/test-prove-claim.py|prove: green under the break is recorded|5"
  "hooks/tests/test-git-ref-gate.sh|ref gate: acts in the committed phase, where a refusal aborts nothing|23"
  "hooks/tests/test-proof-guard.sh|guard: the hooksPath rule off|6"
)

for case in "${CASES[@]}"; do
  suite="${case%%|*}"; rest="${case#*|}"; label="${rest%|*}"; floor="${rest##*|}"
  name="$(basename "$suite")"
  # copy + break, using the battery's own copy_skill() and its entry for `label`
  d="$(python3 - "$BATTERY" "$label" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("bat", sys.argv[1])
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
entry = [e for e in b.M if e[0] == sys.argv[2]]
if len(entry) != 1:
    sys.exit(f"no battery entry labelled {sys.argv[2]!r}")
_label, target, old, new = entry[0][:4]   # (label, target, old, new, killer)
d = b.copy_skill()
f = d / "planning" / target
f.write_text(f.read_text().replace(old, new))
print(d)
PY
)" || { bad "$name: the battery entry '$label' could not be applied" "$d"; continue; }
  root="$d/planning"
  runner=python3; case "$suite" in *.sh) runner=bash ;; esac
  # the suite without its fail-fast step, beside the current one so it finds the same scripts
  orig="${suite%.*}.orig.${suite##*.}"
  why="$(python3 - "$root/$suite" "$root/$orig" 2>&1 <<'PY'
import re, sys
src_path, out_path = sys.argv[1], sys.argv[2]
src = open(src_path, encoding="utf-8").read()
if src_path.endswith(".sh"):
    # bad() { …; [ -n "${2:-}" ] && printf … "${2:0:700}"
    #         [ "${SUITE_FAIL_FAST:-}" = 1 ] && exit 1; }   # comment
    step = re.compile(r'"\$\{2:0:700\}"\n[ \t]+\[ "\$\{SUITE_FAIL_FAST:-\}" = 1 \] '
                      r'&& exit 1; \}[^\n]*')
    out, n = step.subn('"${2:0:700}"; }', src)
else:
    # the `if os.environ.get("SUITE_FAIL_FAST") == "1":` block that ends bad(),
    # with every line indented deeper than its `if`
    step = re.compile(r'\n([ \t]+)if os\.environ\.get\("SUITE_FAIL_FAST"\) == "1":[^\n]*\n'
                      r'(?:\1[ \t]+[^\n]*\n)+')
    out, n = step.subn("\n", src)
if n != 1:
    sys.exit(f"found {n} fail-fast steps, expected exactly 1")
if "SUITE_FAIL_FAST" in out:
    sys.exit("SUITE_FAIL_FAST is still named after the step was removed")
open(out_path, "w", encoding="utf-8").write(out)
PY
)" || { bad "$name: the text without fail-fast could not be built" "$why"; rm -rf "$d"; continue; }

  out_old="$(env -u SUITE_FAIL_FAST $runner "$root/$orig" 2>/dev/null)"
  out_def="$(env -u SUITE_FAIL_FAST $runner "$root/$suite" 2>/dev/null)"; rc_def=$?
  out_ff="$(SUITE_FAIL_FAST=1 $runner "$root/$suite" 2>/dev/null)"; rc_ff=$?
  n_old="$(printf '%s\n' "$out_old" | grep -c '^  FAIL')"
  n_def="$(printf '%s\n' "$out_def" | grep -c '^  FAIL')"
  n_ff="$(printf '%s\n' "$out_ff" | grep -c '^  FAIL')"
  rm -rf "$d"

  # Catches: the fixture measuring nothing — a break the suite reports once cannot show
  # fail-fast stopping early.
  if [ "$n_old" -ge 2 ]; then ok "$name: the broken copy fails $n_old checks without fail-fast"
  else bad "$name: the chosen break must make the suite report >=2 failures" "got $n_old"; fi
  # Catches: a suite running on past its first failure.
  if [ "$n_ff" = 1 ] && [ "$rc_ff" = 1 ]; then ok "$name: SUITE_FAIL_FAST=1 prints one FAIL and exits 1"
  else bad "$name: SUITE_FAIL_FAST=1 must print exactly one FAIL and exit 1" "FAIL lines $n_ff, exit $rc_ff"; fi
  # Catches: default mode stopping early. The fail-fast step must be inert without the
  # variable, so default mode reports at least as many failures as the text without it;
  # and the suite may gain cases that fail under the same break, so it reports at least
  # the floor, never fewer.
  if [ "$n_def" -ge "$n_old" ] && [ "$n_def" -ge "$floor" ] && [ "$rc_def" != 0 ]; then
    ok "$name: default mode reports all $n_def failures (without fail-fast $n_old, floor $floor)"
  else
    bad "$name: default mode must keep running past a failure" \
        "without fail-fast $n_old, floor $floor, now $n_def (exit $rc_def)"
  fi
done

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
