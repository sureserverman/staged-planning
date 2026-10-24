#!/usr/bin/env bash
# Fixture suite for probe-toolchain.sh — run directly (repo convention):
#
#     bash skills/executing-plans/tests/test-probe-toolchain.sh
#
# WHAT THIS SUITE IS REALLY GUARDING. A Preflight check of "NDK installed" at
# the path the PLAN names can pass while the build's own local.properties points
# at a different SDK that lacks that NDK. So the property under
# test is that the probe reads the SDK the BUILD reads, and says so when the
# plan's SDK and the build's SDK are two different things.
#
# Hermetic: every case builds a fake SDK tree and runs under a throwaway HOME,
# with ANDROID_HOME / ANDROID_SDK_ROOT unset unless the case sets them, so the
# operator's real SDKs can never satisfy (or fail) a check.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../scripts/probe-toolchain.sh"
PASS=0; FAIL=0
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

ok()  { PASS=$((PASS+1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && printf '        | %s\n' "$2"; }

# run <home> [args...] — hermetic environment, output captured.
run() {
  local home="$1"; shift
  env -u ANDROID_HOME -u ANDROID_SDK_ROOT HOME="$home" bash "$SCRIPT" "$@" 2>&1
}
run_env() {   # run_env <home> <ANDROID_HOME> [args...]
  local home="$1" ah="$2"; shift 2
  env -u ANDROID_SDK_ROOT HOME="$home" ANDROID_HOME="$ah" bash "$SCRIPT" "$@" 2>&1
}

mksdk() {   # mksdk <dir> [ndk versions...] — also gives it platform android-35
  local d="$1"; shift
  mkdir -p "$d/platforms/android-35"
  for v in "$@"; do mkdir -p "$d/ndk/$v"; echo "Pkg.Revision = $v" > "$d/ndk/$v/source.properties"; done
}
mkproj() {  # mkproj <dir> <sdk.dir or ""> [gradle body]
  local d="$1" sdk="$2" body="${3:-}"
  mkdir -p "$d/app"
  [ -n "$sdk" ] && echo "sdk.dir=$sdk" > "$d/local.properties"
  printf 'android {\n    compileSdk = 35\n%s\n}\n' "$body" > "$d/app/build.gradle.kts"
}

echo "probe-toolchain.sh — a tool is proven where the build will look"
echo
[ -f "$SCRIPT" ] || { bad "script not found: $SCRIPT"; echo "passed $PASS, failed $FAIL"; exit 1; }

# ------------------------------------------------------------ the happy path
H="$T/h1"; mkdir -p "$H"; mksdk "$T/sdkA" 28.2.13676358
mkproj "$T/p1" "$T/sdkA" '    ndkVersion = "28.2.13676358"'
out=$(run "$H" android --repo "$T/p1"); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "sdk:.*sdkA (from local.properties)" \
   && printf '%s' "$out" | grep -q "ndk:.*28.2.13676358 (from ndkVersion in Gradle)"; then
  ok "sdk.dir + pinned ndkVersion present: exit 0, both resolved paths printed"
else bad "happy path: exit $rc" "$out"; fi

# ---------------------------------------------- what the probe could not read
# An unreadable Gradle file hides its pins, so it is a gap HERE (2), not an OK.
mkproj "$T/p-unread" "$T/sdkA" '    ndkVersion = "28.2.13676358"'
chmod 000 "$T/p-unread/app/build.gradle.kts"
if [ ! -r "$T/p-unread/app/build.gradle.kts" ]; then
  out=$(run "$H" android --repo "$T/p-unread"); rc=$?
  if [ "$rc" -eq 2 ]; then ok "an unreadable Gradle file exits 2, never OK"
  else bad "unreadable Gradle file exited $rc, expected 2" "$out"; fi
fi
chmod 644 "$T/p-unread/app/build.gradle.kts"
# A compileSdk the probe cannot read as a literal is reported, not passed over.
mkdir -p "$T/p-var/app"; echo "sdk.dir=$T/sdkA" > "$T/p-var/local.properties"
printf 'android {\n    compileSdk = libs.versions.sdk.get().toInt()\n    ndkVersion = "28.2.13676358"\n}\n' \
  > "$T/p-var/app/build.gradle.kts"
out=$(run "$H" android --repo "$T/p-var"); rc=$?
if printf '%s' "$out" | grep -q "compileSdk: not verified"; then
  ok "a compileSdk that is not a literal pin is reported as not verified"
else bad "an unread compileSdk passed silently (exit $rc)" "$out"; fi

# ----------------------------------------------- two SDKs, split
# The build reads sdkA (local.properties); the NDK the plan wants is in
# ~/Android/Sdk only. That must be a failure that names the other SDK.
H="$T/h2"; mksdk "$H/Android/Sdk" 27.2.12479018; mksdk "$T/sdkB" 28.2.13676358
mkproj "$T/p2" "$T/sdkB"
out=$(run "$H" android --repo "$T/p2" --ndk 27.2.12479018); rc=$?
if [ "$rc" -eq 1 ]; then ok "NDK only in a different SDK: exit 1"
else bad "split SDK exited $rc, expected 1" "$out"; fi
if printf '%s' "$out" | grep -q "IS in $H/Android/Sdk, a DIFFERENT SDK"; then
  ok "the failure names the other SDK that holds the NDK"
else bad "split SDK must name the other root" "$out"; fi

# --expect-sdk: the plan's SDK differs from the build's.
out=$(run "$H" android --repo "$T/p2" --expect-sdk "$H/Android/Sdk"); rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "plan expects SDK"; then
  ok "--expect-sdk mismatch with the build's SDK: exit 1, both named"
else bad "--expect-sdk mismatch exited $rc" "$out"; fi
out=$(run "$H" android --repo "$T/p2" --expect-sdk "$T/sdkB"); rc=$?
if [ "$rc" -eq 0 ]; then ok "--expect-sdk equal to the build's SDK: exit 0"
else bad "--expect-sdk match exited $rc" "$out"; fi

# ------------------------------------------------- resolution order (Gradle's)
# local.properties beats ANDROID_HOME — the env var must not mask the file.
H="$T/h3"; mkdir -p "$H"; mksdk "$T/sdkC" 26.1.0; mksdk "$T/sdkD"
mkproj "$T/p3" "$T/sdkC" '    ndkVersion = "26.1.0"'
out=$(run_env "$H" "$T/sdkD" android --repo "$T/p3"); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "sdkC (from local.properties)"; then
  ok "local.properties wins over ANDROID_HOME"
else bad "resolution order wrong (exit $rc)" "$out"; fi
# With no sdk.dir, ANDROID_HOME is used.
mkproj "$T/p4" ""
out=$(run_env "$H" "$T/sdkC" android --repo "$T/p4"); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "sdkC (from ANDROID_HOME)"; then
  ok "no sdk.dir: ANDROID_HOME is used and named as the source"
else bad "ANDROID_HOME fallback (exit $rc)" "$out"; fi
# A relative sdk.dir resolves against the project, not the caller's cwd.
mkdir -p "$T/p5"; mksdk "$T/p5/sdk-rel" 26.1.0; mkproj "$T/p5" "sdk-rel"
out=$(cd / && run "$H" android --repo "$T/p5"); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "p5/sdk-rel"; then
  ok "a relative sdk.dir resolves against the project"
else bad "relative sdk.dir (exit $rc)" "$out"; fi

# ------------------------------------------------------------- failures are 1
H="$T/h4"; mkdir -p "$H"; mkproj "$T/p6" ""
out=$(run "$H" android --repo "$T/p6"); rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "no SDK configured"; then
  ok "no SDK anywhere: exit 1 (a toolchain is never BLOCKED, never 78)"
else bad "no SDK exited $rc, expected 1" "$out"; fi

mkproj "$T/p7" "$T/does-not-exist"
out=$(run "$H" android --repo "$T/p7"); rc=$?
if [ "$rc" -eq 1 ]; then ok "sdk.dir pointing at nothing: exit 1"
else bad "missing sdk dir exited $rc" "$out"; fi

mksdk "$T/sdkE" 28.2.13676358; mkproj "$T/p8" "$T/sdkE"
out=$(run "$H" android --repo "$T/p8" --require-ndk); rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "no ndkVersion pinned"; then
  ok "--require-ndk with no pin: exit 1, says pin it"
else bad "--require-ndk unpinned exited $rc" "$out"; fi
out=$(run "$H" android --repo "$T/p8"); rc=$?
if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q "not pinned"; then
  ok "no pin and not required: exit 0, reported as not pinned"
else bad "unpinned, not required exited $rc" "$out"; fi

mkdir -p "$T/p9/lib"; mkproj "$T/p9" "$T/sdkE" '    ndkVersion = "28.2.13676358"'
printf 'android {\n    ndkVersion = "27.0.1"\n}\n' > "$T/p9/lib/build.gradle"
out=$(run "$H" android --repo "$T/p9"); rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "different values" \
   && ! printf '%s' "$out" | grep -q "not pinned"; then
  ok "two different ndkVersion pins: exit 1, reported as ambiguous (not as unpinned)"
else bad "ambiguous pins exited $rc" "$out"; fi

mkdir -p "$T/sdkF/ndk"; mkproj "$T/p10" "$T/sdkF"     # no platforms/android-35
out=$(run "$H" android --repo "$T/p10"); rc=$?
if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q "compileSdk 35"; then
  ok "compileSdk platform missing from the build's SDK: exit 1"
else bad "missing platform exited $rc" "$out"; fi

# ---------------------------------------------------------------- usage is 2
out=$(run "$H" android --repo "$T/nope"); rc=$?
if [ "$rc" -eq 2 ]; then ok "--repo that is not a directory: exit 2"
else bad "bad --repo exited $rc" "$out"; fi
out=$(run "$H" cobol); rc=$?
if [ "$rc" -eq 2 ]; then ok "unknown stack: exit 2"
else bad "unknown stack exited $rc" "$out"; fi
out=$(run "$H" android --bogus); rc=$?
if [ "$rc" -eq 2 ]; then ok "unknown flag: exit 2"
else bad "unknown flag exited $rc" "$out"; fi

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
