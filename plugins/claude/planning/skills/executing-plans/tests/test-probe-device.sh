#!/usr/bin/env bash
# Fixture suite for probe-device.sh — run directly (repo convention):
#
#     bash skills/executing-plans/tests/test-probe-device.sh
#
# WHAT THIS SUITE IS REALLY GUARDING. An unset environment variable naming a
# device is not evidence that the device is absent: a gate can read it that way,
# tick itself as amended, and never try the address the repo's own deploy script
# names.
#
# So the property under test is not "can it ssh". It is the DISTINCTION between
# four outcomes that are easy to collapse into one:
#
#   exit 0   something answered and told us who it was
#   exit 1   something answered and the answer was WRONG — the identity did not
#            match, or none could be read. The probe worked, so this is a real
#            failure and never BLOCKED
#   exit 2   we could not probe from HERE — usage error, or an agent-host gap
#            (no ssh/ping client, an unreadable device node). Missing
#            configuration on the probing machine, not a fact about the device
#   exit 78  a probe RAN and nothing answered — BLOCKED, and the only outcome
#            that may be recorded as such
#
# A probe that cannot tell these apart hands the executor back the same excuse.
# The 2-vs-78 line is as load-bearing as 1-vs-78: a missing `ping` binary must
# not read as 78, nor a missing ssh client as 0 with a fabricated identity, and
# only a fault injected on the agent host itself can show either.
#
# Network-independent by construction: the unreachable cases use a closed port
# on 127.0.0.1, and the identity cases read a file, so the suite behaves the
# same on a laptop with no lab on the network.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../scripts/probe-device.sh"
PASS=0; FAIL=0
TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

ok()  { PASS=$((PASS+1)); echo "  ok    $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && printf '        | %s\n' "$2"; }

# A TCP port that is closed but routable — "nothing answered" without waiting
# on a network timeout, so the suite stays fast and deterministic.
CLOSED_PORT=9
run() { "$SCRIPT" "$@" 2>"$TMPROOT/err"; }

echo "probe-device.sh — hardware is proven by I/O, not by an env var"
echo

if [ ! -f "$SCRIPT" ]; then
  bad "script not found: $SCRIPT"
  echo; echo "passed $PASS, failed $FAIL"; exit 1
fi

# ------------------------------------------------------- nothing answered = 78
echo "nothing answered -> 78 (BLOCKED), never 0 and never 1"
out=$(run --tcp "127.0.0.1:$CLOSED_PORT"); rc=$?
if [ "$rc" -eq 78 ]; then ok "closed TCP port exits 78"
else bad "closed TCP port exited $rc, expected 78" "$out"; fi

out=$(run --ssh "127.0.0.1" --ssh-port "$CLOSED_PORT"); rc=$?
if [ "$rc" -eq 78 ]; then ok "unreachable ssh exits 78"
else bad "unreachable ssh exited $rc, expected 78" "$out"; fi

# Capture first, then grep: under `set -o pipefail` a pipeline whose FIRST
# element exits 78 returns 78 regardless of grep's verdict, so `if run ... |
# grep -q` would test the exit code it was never about. Same idiom as
# test-plan-continue.sh.
out=$(run --tcp "127.0.0.1:$CLOSED_PORT")
if printf '%s' "$out" | grep -qi 'blocked'; then
  ok "the 78 path says BLOCKED in words, not just in a code"
else bad "78 path does not print BLOCKED" "$out"; fi

# ------------------------------------------------- answered + identity = 0
echo
echo "answered, identity read -> 0, and the identity is PRINTED"
echo "cafef00d" > "$TMPROOT/serial"
out=$(run --serial "$TMPROOT/serial"); rc=$?
if [ "$rc" -eq 0 ]; then ok "readable identity source exits 0"
else bad "readable identity exited $rc, expected 0" "$out"; fi
if printf '%s' "$out" | grep -q 'cafef00d'; then
  ok "prints the identity it actually read"
else bad "identity not printed" "$out"; fi

out=$(run --serial "$TMPROOT/serial" --expect-serial cafef00d); rc=$?
if [ "$rc" -eq 0 ]; then ok "matching --expect-serial exits 0"
else bad "matching expectation exited $rc, expected 0" "$out"; fi

# The conventional short form must match: a Pi's Serial is 16 hex digits and
# every human reference to it uses the last 8: /proc/cpuinfo reports
# 10000000deadbeef where a plan asks for deadbeef. Exact-only comparison calls
# the right device the wrong one.
echo "10000000deadbeef" > "$TMPROOT/serial16"
out=$(run --serial "$TMPROOT/serial16" --expect-serial deadbeef); rc=$?
if [ "$rc" -eq 0 ]; then
  ok "a 16-digit serial matches its conventional 8-digit short form"
else bad "short-form serial exited $rc, expected 0" "$out"; fi
if printf '%s' "$out" | grep -q 'ENDS WITH'; then
  ok "a suffix match SAYS it was a suffix match, never silently"
else bad "suffix match not disclosed in the output" "$out"; fi

# ...but a suffix short enough to be ambiguous must not identify anything.
out=$(run --serial "$TMPROOT/serial16" --expect-serial 6f); rc=$?
if [ "$rc" -eq 1 ]; then
  ok "a 2-character suffix does not identify a device (mismatch)"
else bad "short suffix exited $rc, expected 1" "$out"; fi

# --------------------------------------- answered + WRONG identity = 1, not 78
echo
echo "answered but WRONG device -> 1 (a real failure), never 78"
out=$(run --serial "$TMPROOT/serial" --expect-serial deadbeef); rc=$?
if [ "$rc" -eq 1 ]; then
  ok "identity mismatch exits 1 — a failure, not a BLOCKED"
else bad "mismatch exited $rc, expected 1" "$out"; fi
if [ "$rc" -ne 78 ]; then ok "mismatch is NOT reported as BLOCKED"
else bad "mismatch reported as BLOCKED — the exact collapse this script prevents"; fi

# An empty identity source answered, but told us nothing -> 78, not 0.
: > "$TMPROOT/empty"
# ANSWERED but said nothing: the probe WORKED, so this is a failure (1), never
# BLOCKED (78). Letting it be 78 hands back the excuse the script abolishes.
out=$(run --serial "$TMPROOT/empty"); rc=$?
if [ "$rc" -eq 1 ]; then
  ok "a readable source that reports nothing is 1 (failure), not 78"
else bad "empty identity exited $rc, expected 1" "$out"; fi

# ------------------------------------------------------------- discovery
echo
echo "an unset variable is missing CONFIGURATION, not missing hardware"
REPO="$TMPROOT/repo"; mkdir -p "$REPO/scripts"
cat > "$REPO/scripts/deploy.sh" <<'EOF'
#!/usr/bin/env bash
HOST="${DEVICE_HOST:-pi@192.0.2.57}"
scp build.tar "$HOST":/tmp/
EOF
cat > "$REPO/scripts/hil-thing.sh" <<'EOF'
#!/usr/bin/env bash
ssh pi@192.0.2.57 'true'
EOF
out=$(run --discover "$REPO"); rc=$?
if printf '%s' "$out" | grep -q '192\.0\.2\.57'; then
  ok "discovers the host from the repo's own deploy/HIL scripts"
else bad "discovery found no candidate" "$out"; fi
if [ "$rc" -eq 0 ]; then ok "discovery with candidates exits 0"
else bad "discovery exited $rc, expected 0" "$out"; fi

EMPTY="$TMPROOT/emptyrepo"; mkdir -p "$EMPTY"
# Discovery probes nothing, so it can never produce a device verdict. "No
# candidate" is a configuration gap (2), not "the device did not answer" (78).
out=$(run --discover "$EMPTY"); rc=$?
if [ "$rc" -eq 2 ]; then
  ok "discovery with NO candidate exits 2 — nothing was probed, so not BLOCKED"
else bad "empty discovery exited $rc, expected 2" "$out"; fi

# ---------------------------------------------------------------- usage
echo
echo "usage errors are 2 — never confusable with a probe result"
# A host starting with "-" would reach ssh or ping as an option (an ssh
# -oProxyCommand= runs a command), so every host-taking mode refuses it.
for m in --ssh --tcp --ping; do
  out=$(run "$m" "-oProxyCommand=touch $TMPROOT/pwned"); rc=$?
  if [ "$rc" -eq 2 ] && [ ! -e "$TMPROOT/pwned" ]; then ok "$m refuses a host that starts with -"
  else bad "$m with a leading-dash host exited $rc, expected 2" "$out"; fi
done
out=$(run); rc=$?
if [ "$rc" -eq 2 ]; then ok "no arguments exits 2"
else bad "no args exited $rc, expected 2" "$out"; fi
out=$(run --serial "$TMPROOT/nope-does-not-exist"); rc=$?
if [ "$rc" -eq 78 ]; then
  ok "an ABSENT device node is 78 — the node isn't there, nothing to answer"
else bad "missing source exited $rc, expected 78" "$out"; fi
out=$(run --bogus-flag); rc=$?
if [ "$rc" -eq 2 ]; then ok "unknown flag exits 2"
else bad "unknown flag exited $rc, expected 2" "$out"; fi

# ------------------------------------------------- the env-var anti-pattern
# ---------------------------------------------- fault injection (agent host)
# Cases with a reachable device or a closed port never exercise THIS HOST being
# unable to probe at all, so these inject that fault. A source-text grep for the
# anti-pattern would be a check whose only possible outcome is a pass.
echo
echo "agent-host gaps are 2 — never 78, never a fabricated identity"

# A PATH with coreutils but no ssh/ping.
STUB="$TMPROOT/bin"; mkdir -p "$STUB"
for t in bash sed grep awk head tr timeout cat sort find xargs printf; do
  src="$(command -p which "$t" 2>/dev/null || true)"
  [ -n "$src" ] && ln -sf "$src" "$STUB/$t"
done
noprobe() { PATH="$STUB" "$SCRIPT" "$@" 2>"$TMPROOT/err"; }

if [ -x "$STUB/bash" ]; then
  out=$(noprobe --ping 127.0.0.1); rc=$?
  if [ "$rc" -eq 2 ]; then
    ok "missing 'ping' exits 2 (cannot probe), not 78"
  else bad "missing ping exited $rc, expected 2" "$out$(cat "$TMPROOT/err")"; fi

  out=$(noprobe --ssh 127.0.0.1 --ssh-port 22); rc=$?
  if [ "$rc" -eq 2 ]; then
    ok "missing 'ssh' client exits 2 — never 0 with a fabricated identity"
  else bad "missing ssh exited $rc, expected 2" "$out$(cat "$TMPROOT/err")"; fi
  if ! printf '%s' "$out" | grep -q 'identity ='; then
    ok "no identity is printed when none was read"
  else bad "an identity was fabricated from an open port" "$out"; fi
  # The same stub without `timeout`: every network and serial probe runs under
  # it, so its absence is a gap HERE (2), never a device that did not answer (78).
  NOTIMEOUT="$TMPROOT/bin-notimeout"; mkdir -p "$NOTIMEOUT"
  for f in "$STUB"/*; do [ "$(basename "$f")" = timeout ] || ln -sf "$(readlink -f "$f")" "$NOTIMEOUT/$(basename "$f")"; done
  for args in "--tcp 127.0.0.1:1" "--ssh 127.0.0.1"; do
    out=$(PATH="$NOTIMEOUT" "$STUB/bash" "$SCRIPT" $args 2>"$TMPROOT/err"); rc=$?
    if [ "$rc" -eq 2 ]; then ok "missing 'timeout' exits 2 for $args, not 78"
    else bad "missing timeout with $args exited $rc, expected 2" "$out$(cat "$TMPROOT/err")"; fi
  done
else
  bad "could not build a restricted PATH stub — fault injection did not run"
fi

# An identity source that exists but cannot be read is a permissions gap here,
# not a statement about the device.
printf 'deadbeef\n' > "$TMPROOT/unreadable"
chmod 000 "$TMPROOT/unreadable" 2>/dev/null || true
if [ ! -r "$TMPROOT/unreadable" ]; then
  out=$(run --serial "$TMPROOT/unreadable"); rc=$?
  if [ "$rc" -eq 2 ]; then
    ok "an unreadable-but-present device node exits 2, not 78"
  else bad "unreadable source exited $rc, expected 2" "$out"; fi
else
  ok "skipped: running as a user who can read mode-000 files (root)"
fi
chmod 644 "$TMPROOT/unreadable" 2>/dev/null || true

echo
echo "--expect-serial may only be graded by a mode that reads an identity"
for m in "--ping 127.0.0.1" "--tcp 127.0.0.1:9"; do
  # shellcheck disable=SC2086
  out=$(run $m --expect-serial deadbeef); rc=$?
  if [ "$rc" -eq 2 ]; then
    ok "$m with --expect-serial is a usage error, not a false 'wrong device'"
  else bad "$m --expect-serial exited $rc, expected 2" "$out"; fi
done

echo
echo "the host argument is not a shell code path"
rm -f "$TMPROOT/PWNED"
run --tcp "127.0.0.1/\$(touch $TMPROOT/PWNED)/x:9" >/dev/null 2>&1
if [ ! -e "$TMPROOT/PWNED" ]; then
  ok "a command-substitution in the host argument is not executed"
else bad "COMMAND INJECTION: the host argument reached a shell"; fi

echo
echo "malformed arguments are usage errors, not device verdicts"
out=$(run --ssh 127.0.0.1 --ssh-port abc); rc=$?
if [ "$rc" -eq 2 ]; then ok "non-numeric --ssh-port exits 2"
else bad "--ssh-port abc exited $rc, expected 2" "$out"; fi
out=$(run --tcp "127.0.0.1:"); rc=$?
if [ "$rc" -eq 2 ]; then ok "an empty --tcp port exits 2"
else bad "--tcp with no port exited $rc, expected 2" "$out"; fi

echo
echo "host-key verification (CWE-295) — the SSHPASS pair is the case that leaks"
# A security change needs a regression test in the tree: "verified live against
# a listener" is evidence nothing in the tree can corroborate.
#
# No sshd is needed. The warning prints after tcp_open() succeeds and BEFORE the
# identity read, so a bare TCP listener that accepts and closes is enough to
# reach the branch and assert on stderr.
LISTEN_PORT=0
python3 - "$TMPROOT" <<'PY' &
import socket, sys, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 0)); s.listen(8)
open(sys.argv[1] + "/port", "w").write(str(s.getsockname()[1]))
end = time.time() + 45
while time.time() < end:
    s.settimeout(1)
    try:
        c, _ = s.accept(); c.close()
    except socket.timeout:
        pass
PY
LISTENER=$!
for _ in $(seq 1 50); do [ -s "$TMPROOT/port" ] && break; sleep 0.1; done
LISTEN_PORT="$(cat "$TMPROOT/port" 2>/dev/null || echo 0)"

if [ "$LISTEN_PORT" -gt 0 ] 2>/dev/null; then
  SSHPASS=dummy run --ssh "user@127.0.0.1" --ssh-port "$LISTEN_PORT" >/dev/null 2>/dev/null || true
  err=$(cat "$TMPROOT/err")
  case "$err" in
    *"host-key verification is DISABLED and SSHPASS is set"*)
      ok "SSHPASS + no --known-hosts warns loudly that a password can be captured" ;;
    *) bad "the SSHPASS/no-verification pair must warn (CWE-295)" "$err" ;;
  esac
  case "$err" in
    *"--known-hosts"*) ok "the warning names the flag that fixes it" ;;
    *) bad "the warning must name --known-hosts" "$err" ;;
  esac

  run --ssh "user@127.0.0.1" --ssh-port "$LISTEN_PORT" >/dev/null 2>/dev/null || true
  err=$(cat "$TMPROOT/err")
  case "$err" in
    *"host-key verification is DISABLED and SSHPASS is set"*)
      bad "the LOUD warning must fire only when SSHPASS is set" "$err" ;;
    *"host-key verification disabled"*)
      ok "without SSHPASS it notes the same fact quietly, not loudly" ;;
    *) bad "no --known-hosts must still disclose that verification is off" "$err" ;;
  esac
else
  bad "could not start a loopback listener — the host-key cases did not run" \
      "this is a BLOCKED check, not a pass"
fi
kill "$LISTENER" 2>/dev/null || true
wait "$LISTENER" 2>/dev/null || true

echo
echo "--known-hosts is validated before anything is probed"
out=$(run --ssh 127.0.0.1 --known-hosts "$TMPROOT/definitely-not-here"); rc=$?
if [ "$rc" -eq 2 ]; then ok "an unreadable --known-hosts file exits 2 (usage), not a device verdict"
else bad "--known-hosts with a missing file exited $rc, expected 2" "$out"; fi

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
