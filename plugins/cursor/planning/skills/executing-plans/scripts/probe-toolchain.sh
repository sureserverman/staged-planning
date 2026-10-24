#!/usr/bin/env bash
# probe-toolchain.sh — prove a toolchain WHERE THE BUILD WILL LOOK, and print it.
#
# USAGE
#   probe-toolchain.sh android [--repo DIR] [--ndk VERSION] [--require-ndk]
#                              [--expect-sdk PATH]
#
#   --repo DIR        the project root (default: .). Its local.properties and
#                     Gradle files decide which SDK and NDK the build uses.
#   --ndk VERSION     the NDK the plan needs. Default: the `ndkVersion` pinned in
#                     the project's Gradle files, if any.
#   --require-ndk     the project builds native code: an unpinned NDK is a
#                     failure, because AGP then picks its own default, which may
#                     not be installed in the SDK the build reads.
#   --expect-sdk PATH the SDK the PLAN names. A different SDK in the build's own
#                     configuration is a failure, not a detail.
#
# EXIT CODES
#
#   0   resolved: the SDK the build reads, and every required component in it,
#       exist. The resolved paths are printed — paste them into the Preflight
#       report.
#   1   the build's toolchain is wrong or missing: no SDK configured, the pinned
#       NDK or compileSdk platform absent from THAT SDK, an ambiguous pin, or a
#       mismatch with --expect-sdk. A real failure. When the missing component
#       exists in a DIFFERENT SDK on this host, that SDK is named.
#   2   could not probe: a usage error, or the project files are unreadable.
#
# There is no 78. probe-device.sh reserves 78 for hardware that did not answer;
# a toolchain is never BLOCKED — a missing one gets installed.
#
# WHY THIS EXISTS. A Preflight check can pass on the path a plan names (an NDK
# under one SDK) while the build's own local.properties points at another SDK
# that lacks it. The check then proves nothing about the build. Same lesson as
# probe-device.sh, one layer down:
#
#   A TOOL IS PROVEN WHERE THE BUILD WILL LOOK, NOT WHERE THE PLAN SAID.
#
# Re-run it after any task that writes local.properties or a toolchain pin:
# the Preflight result describes the configuration that existed at Preflight.
# END-OF-HELP
set -uo pipefail

usage() {
  sed -n '3,$p' "$0" | sed -e '/END-OF-HELP/,$d' -e 's/^# \{0,1\}//'
  exit 2
}
die_usage() { echo "probe-toolchain: $1" >&2; echo >&2; usage; }
die_host()  { echo "probe-toolchain: CANNOT PROBE — $1" >&2; exit 2; }

STACK="${1:-}"
case "$STACK" in
  android) shift ;;
  -h|--help|"") usage ;;
  *) die_usage "unknown stack '$STACK' (supported: android)" ;;
esac

REPO="."; NDK=""; REQUIRE_NDK=0; EXPECT_SDK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)        REPO="${2:-}"; [ -n "$REPO" ] || die_usage "--repo needs a directory"; shift 2 ;;
    --ndk)         NDK="${2:-}"; [ -n "$NDK" ] || die_usage "--ndk needs a version"; shift 2 ;;
    --require-ndk) REQUIRE_NDK=1; shift ;;
    --expect-sdk)  EXPECT_SDK="${2:-}"; [ -n "$EXPECT_SDK" ] || die_usage "--expect-sdk needs a path"; shift 2 ;;
    -h|--help)     usage ;;
    *)             die_usage "unknown argument: $1" ;;
  esac
done
[ -d "$REPO" ] || die_usage "--repo is not a directory: $REPO"

FAIL=0
fail() { echo "  FAIL  $1"; FAIL=1; }
canon() { (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; }

# --- which SDK does the build read? --------------------------------------
# Gradle's order: sdk.dir in local.properties, then ANDROID_HOME, then the
# deprecated ANDROID_SDK_ROOT. The plan's opinion is not in that list.
SDK=""; SDK_FROM=""
LP="$REPO/local.properties"
if [ -e "$LP" ]; then
  [ -r "$LP" ] || die_host "$LP exists but is not readable"
  # .properties escaping: `\:` -> `:`, `\\` -> `\` (Windows paths are written so).
  raw="$(grep -E '^[[:space:]]*sdk\.dir[[:space:]]*[=:]' "$LP" | tail -n 1 \
         | sed -E 's/^[[:space:]]*sdk\.dir[[:space:]]*[=:][[:space:]]*//')"
  if [ -n "$raw" ]; then
    SDK="$(printf '%s' "$raw" | sed -e 's/\\:/:/g' -e 's/\\\\/\\/g')"
    SDK_FROM="local.properties"
    # A relative sdk.dir is resolved by Gradle against the project, not the cwd.
    case "$SDK" in /*) ;; *) SDK="$REPO/$SDK" ;; esac
  fi
fi
if [ -z "$SDK" ] && [ -n "${ANDROID_HOME:-}" ]; then SDK="$ANDROID_HOME"; SDK_FROM="ANDROID_HOME"; fi
if [ -z "$SDK" ] && [ -n "${ANDROID_SDK_ROOT:-}" ]; then SDK="$ANDROID_SDK_ROOT"; SDK_FROM="ANDROID_SDK_ROOT"; fi

echo "probe-toolchain: android, project $(canon "$REPO")"
if [ -z "$SDK" ]; then
  fail "no SDK configured: no sdk.dir in $LP, ANDROID_HOME and ANDROID_SDK_ROOT unset"
elif [ ! -d "$SDK" ]; then
  fail "sdk: $SDK (from $SDK_FROM) does not exist"
  SDK=""
else
  SDK="$(canon "$SDK")"
  echo "  sdk:      $SDK (from $SDK_FROM)"
fi

# Every SDK root on this host, so a split between two of them is visible.
OTHER_ROOTS=()
for cand in "$HOME/Android/Sdk" "$HOME/android-sdk" "$HOME/Library/Android/sdk" \
            "${ANDROID_HOME:-}" "${ANDROID_SDK_ROOT:-}"; do
  [ -n "$cand" ] && [ -d "$cand" ] || continue
  c="$(canon "$cand")"
  [ "$c" = "$SDK" ] && continue
  dup=0; for o in "${OTHER_ROOTS[@]+"${OTHER_ROOTS[@]}"}"; do [ "$o" = "$c" ] && dup=1; done
  [ "$dup" = 0 ] && OTHER_ROOTS+=("$c")
done
[ "${#OTHER_ROOTS[@]}" -gt 0 ] && echo "  other SDK roots on this host: ${OTHER_ROOTS[*]}"

elsewhere() {   # $1 = relative component path; prints the other roots holding it
  local hits=() o
  for o in "${OTHER_ROOTS[@]+"${OTHER_ROOTS[@]}"}"; do [ -e "$o/$1" ] && hits+=("$o"); done
  [ "${#hits[@]}" -gt 0 ] && printf '%s' "${hits[*]}"
}

if [ -n "$EXPECT_SDK" ] && [ -n "$SDK" ]; then
  if [ "$(canon "$EXPECT_SDK")" != "$SDK" ]; then
    fail "the plan expects SDK $EXPECT_SDK but the build reads $SDK (from $SDK_FROM) — fix one of them, then re-probe"
  fi
fi

# --- Gradle pins ----------------------------------------------------------
GRADLE_FILES=()
while IFS= read -r f; do GRADLE_FILES+=("$f"); done < <(
  find "$REPO" -maxdepth 2 \( -name build.gradle -o -name build.gradle.kts \) \
       -not -path '*/build/*' 2>/dev/null | sort)
# A Gradle file the probe cannot read hides its pins: a gap here, never an OK.
for f in "${GRADLE_FILES[@]+"${GRADLE_FILES[@]}"}"; do
  [ -r "$f" ] || die_host "a Gradle file is unreadable, so its pins cannot be read: $f"
done
[ "${#GRADLE_FILES[@]}" -gt 0 ] || echo "  note: no build.gradle(.kts) within two levels of $REPO; no Gradle pin was read"
pins() {   # $1 = key regex; prints each distinct pinned value
  [ "${#GRADLE_FILES[@]}" -gt 0 ] || return 0
  grep -hE "^[[:space:]]*$1[[:space:]]*=?[[:space:]]*\"?[0-9][^\"[:space:]]*\"?" \
       "${GRADLE_FILES[@]}" 2>/dev/null \
    | sed -E "s/^[[:space:]]*$1[[:space:]]*=?[[:space:]]*\"?([0-9][^\"[:space:]]*)\"?.*/\1/" \
    | sort -u
}

NDK_FROM="--ndk"; NDK_AMBIGUOUS=0
if [ -z "$NDK" ]; then
  mapfile -t ndk_pins < <(pins 'ndkVersion')
  if [ "${#ndk_pins[@]}" -gt 1 ]; then
    fail "ndkVersion pinned to different values across Gradle files: ${ndk_pins[*]}"
    NDK_AMBIGUOUS=1
  elif [ "${#ndk_pins[@]}" -eq 1 ]; then
    NDK="${ndk_pins[0]}"; NDK_FROM="ndkVersion in Gradle"
  fi
fi

if [ -n "$SDK" ]; then
  installed="$(find "$SDK/ndk" -mindepth 1 -maxdepth 1 -type d -printf '%f ' 2>/dev/null)"
  installed="${installed% }"
  if [ -n "$NDK" ]; then
    if [ -f "$SDK/ndk/$NDK/source.properties" ]; then
      echo "  ndk:      $SDK/ndk/$NDK (from $NDK_FROM)"
    else
      where="$(elsewhere "ndk/$NDK/source.properties")"
      msg="ndk $NDK (from $NDK_FROM) is not in the SDK the build reads ($SDK; installed there: ${installed:-none})"
      [ -n "$where" ] && msg="$msg — it IS in $where, a DIFFERENT SDK: install it into $SDK or point sdk.dir there"
      fail "$msg"
    fi
  elif [ "$NDK_AMBIGUOUS" = 1 ]; then
    :   # already reported; an ambiguous pin is not "not pinned"
  elif [ "$REQUIRE_NDK" = 1 ]; then
    fail "no ndkVersion pinned: AGP will pick its own default, which may not be installed in $SDK (installed: ${installed:-none}) — pin ndkVersion"
  else
    echo "  ndk:      not pinned (installed in this SDK: ${installed:-none})"
  fi

  # Two calls, not one `compileSdk(Version)?`: a group in the key would shift
  # the capture the sed in pins() returns.
  mapfile -t api_pins < <({ pins 'compileSdk'; pins 'compileSdkVersion'; } | sort -u)
  # Only a literal pin is read; a variable or version-catalog value is said so.
  [ "${#api_pins[@]}" -gt 0 ] || echo "  compileSdk: not verified (no literal compileSdk pin; a variable or version-catalog value is not read)"
  for api in "${api_pins[@]+"${api_pins[@]}"}"; do
    if [ -d "$SDK/platforms/android-$api" ]; then
      echo "  platform: $SDK/platforms/android-$api (compileSdk)"
    else
      where="$(elsewhere "platforms/android-$api")"
      msg="compileSdk $api: platforms/android-$api is not in $SDK"
      [ -n "$where" ] && msg="$msg — it IS in $where, a DIFFERENT SDK"
      fail "$msg"
    fi
  done
fi

if [ "$FAIL" = 0 ]; then
  echo "probe-toolchain: OK — paste the lines above into the Preflight report"
  exit 0
fi
echo "probe-toolchain: the build's toolchain is not what it needs (exit 1 — fix it; never BLOCKED)"
exit 1
