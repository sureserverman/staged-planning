#!/usr/bin/env bash
# probe-device.sh — prove hardware by I/O, and print the identity you read.
#
# USAGE
#   probe-device.sh --ssh HOST [--ssh-port N] [--expect-serial VALUE]
#                        [--known-hosts FILE]
#       --known-hosts verifies the device's host key against FILE
#       (StrictHostKeyChecking=yes). WITHOUT it the probe still runs but host-key
#       verification is off, and it says so on stderr — loudly when SSHPASS is
#       also set, because that pair is what leaks a password to an on-path
#       attacker (CWE-295). Populate FILE once with ssh-keyscan.
#       export SSHPASS=... first for a device that offers password auth only;
#       --expect-serial matches exactly OR as a suffix (the 8-of-16-digit short
#       form everyone quotes for a Raspberry Pi serial).
#   probe-device.sh --serial PATH [--expect-serial VALUE]
#   probe-device.sh --tcp HOST:PORT
#   probe-device.sh --ping HOST
#   probe-device.sh --discover REPO_ROOT
#
# EXIT CODES — the distinction is the whole point:
#
#   0   a probe ran, something answered, and (where the mode reads one) it told
#       us who it was
#   1   a probe ran and something answered, but the answer was WRONG: the
#       identity did not match --expect-serial, or none could be read at all.
#       The probe worked. This is a real failure and is NEVER BLOCKED.
#   2   we could not probe from here — a usage error, or an agent-host gap such
#       as a missing ssh/ping client or an unreadable device node. This is
#       missing CONFIGURATION on the machine running the probe.
#   78  a probe RAN and nothing answered — BLOCKED, and the only outcome that
#       may be recorded as such. CARVE-OUT: for --serial, a device node that is
#       ABSENT is 78, because for a directly-attached device the node IS the
#       device and its absence is the device's absence. A node that is PRESENT
#       but unreadable is 2 — that is a permissions gap on this host.
#
# The 1-vs-78 line is the one that matters, and it is drawn strictly: 78 is
# reachable only after a probe has actually executed and gone unanswered. A
# tool that is missing, an argument that is wrong, a device node we may not
# read — none of those are the device being absent, and none of them may
# borrow the code that excuses a gate.
#
# WHY THIS EXISTS. An unset variable naming a device can be read as "there is no
# hardware", and a gate ticked as amended, while the device sits on the network
# at an address the repo's own deploy script names. So:
#
#   AN UNSET VARIABLE IS MISSING CONFIGURATION, NOT MISSING HARDWARE.
#
# This script therefore has no "variable unset => blocked" branch anywhere in
# it. When you do not know the host, `--discover` reads it out of the repo's own
# deploy and HIL scripts, where the repo itself records the address.
# END-OF-HELP
set -uo pipefail

usage() {
  sed -n '3,$p' "$0" | sed -e '/END-OF-HELP/,$d' -e 's/^# \{0,1\}//'
  exit 2
}

# Exit 2 covers both "you asked wrongly" and "this host cannot probe" — see the
# exit-code table. Neither is evidence about the device.
die_usage() { echo "probe-device: $1" >&2; echo >&2; usage; }
die_host()  { echo "probe-device: CANNOT PROBE — $1" >&2
              echo "probe-device: this is an agent-host gap, not a device result." >&2
              exit 2; }

MODE=""; TARGET=""; SSH_PORT=22; EXPECT=""; KNOWN_HOSTS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --ssh)      MODE=ssh;      TARGET="${2:-}"; [ -n "$TARGET" ] || die_usage "--ssh needs a host"; shift 2 ;;
    --tcp)      MODE=tcp;      TARGET="${2:-}"; [ -n "$TARGET" ] || die_usage "--tcp needs HOST:PORT"; shift 2 ;;
    --ping)     MODE=ping;     TARGET="${2:-}"; [ -n "$TARGET" ] || die_usage "--ping needs a host"; shift 2 ;;
    --serial)   MODE=serial;   TARGET="${2:-}"; [ -n "$TARGET" ] || die_usage "--serial needs a path"; shift 2 ;;
    --discover) MODE=discover; TARGET="${2:-}"; [ -n "$TARGET" ] || die_usage "--discover needs a repo root"; shift 2 ;;
    --ssh-port) SSH_PORT="${2:-}"; [ -n "$SSH_PORT" ] || die_usage "--ssh-port needs a number"; shift 2 ;;
    --expect-serial) EXPECT="${2:-}"; [ -n "$EXPECT" ] || die_usage "--expect-serial needs a value"; shift 2 ;;
    --known-hosts) KNOWN_HOSTS="${2:-}"; [ -n "$KNOWN_HOSTS" ] || die_usage "--known-hosts needs a path"
                   [ -r "$KNOWN_HOSTS" ] || die_usage "--known-hosts file is not readable: $KNOWN_HOSTS"; shift 2 ;;
    -h|--help)  usage ;;
    *)          die_usage "unknown argument: $1" ;;
  esac
done

[ -n "$MODE" ] || die_usage "no probe requested"

# A host is never an option: one starting with "-" would reach ssh or ping as
# one (ssh -oProxyCommand= runs a command), so it is refused before any probe.
case "$MODE:$TARGET" in
  ssh:-*|tcp:-*|ping:-*) die_usage "--$MODE: a host may not start with '-': $TARGET" ;;
esac

# Every probe but --discover runs under `timeout`: without it a connect that
# could not even start would read as "nothing answered" (78), a gap HERE.
if [ "$MODE" != discover ] && ! command -v timeout >/dev/null 2>&1; then
  die_host "no 'timeout' on this host (coreutils), so no probe can run here"
fi

case "$SSH_PORT" in
  ''|*[!0-9]*) die_usage "--ssh-port must be a number: $SSH_PORT" ;;
esac

# --tcp and --ping observe reachability; neither reads an identity, so grading
# one against --expect-serial could only ever produce a false "wrong device".
if [ -n "$EXPECT" ] && { [ "$MODE" = tcp ] || [ "$MODE" = ping ] || [ "$MODE" = discover ]; }; then
  die_usage "--expect-serial needs a mode that reads an identity (--ssh or --serial)"
fi

blocked() {
  echo "probe-device: BLOCKED — $1"
  echo "probe-device: a probe ran and nothing answered. BLOCKED, not proof of absent hardware."
  exit 78
}

# Something answered but could not say who it was. The probe WORKED, so this is
# a failure to investigate, not a gate excuse.
answered_unidentified() {
  echo "probe-device: ANSWERED, NO IDENTITY — $1" >&2
  echo "probe-device: the probe worked, so this is a failure, not BLOCKED." >&2
  exit 1
}

# Report an identity that was actually read, and grade it against --expect.
report() {
  local what="$1" identity="$2"
  identity="$(printf '%s' "$identity" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  echo "probe-device: $what answered"
  echo "probe-device: identity = $identity"
  if [ -n "$EXPECT" ]; then
    # Exact, or the conventional short form: a Raspberry Pi's /proc/cpuinfo
    # Serial is 16 hex digits ("10000000deadbeef") and plans and people commonly
    # quote the last 8 ("deadbeef"). An
    # exact-only comparison therefore fails on the real device and calls it the
    # WRONG one, which is a false accusation, not a safety margin. The suffix
    # must be at least 6 characters so it still identifies.
    if [ "$identity" = "$EXPECT" ]; then
      echo "probe-device: identity matches --expect-serial"
    elif [ "${#EXPECT}" -ge 6 ] && [ "${identity%"$EXPECT"}" != "$identity" ]; then
      echo "probe-device: identity ENDS WITH --expect-serial '$EXPECT' (short form)"
    else
      echo "probe-device: MISMATCH — expected '$EXPECT', read '$identity'" >&2
      echo "probe-device: the probe WORKED; the wrong device answered. Not BLOCKED." >&2
      exit 1
    fi
  fi
  exit 0
}

# A TCP connect with a bounded wait, via bash's /dev/tcp. Host and port are
# passed as ARGUMENTS, never interpolated into the -c string: `--discover`
# hands the operator candidates read out of repo files, so an interpolated
# form would make repo text a code path.
tcp_open() {
  timeout 6 bash -c 'exec 3<>/dev/tcp/$0/$1' "$1" "$2" 2>/dev/null
}

case "$MODE" in
  tcp)
    host="${TARGET%%:*}"; port="${TARGET##*:}"
    [ "$host" != "$TARGET" ] || die_usage "--tcp needs HOST:PORT"
    case "$port" in ''|*[!0-9]*) die_usage "--tcp port must be a number: $port" ;; esac
    if tcp_open "$host" "$port"; then
      report "tcp $host:$port" "$host:$port open"
    fi
    blocked "no TCP answer from $host:$port"
    ;;

  ping)
    command -v ping >/dev/null 2>&1 || die_host "no 'ping' on PATH — install it or use --tcp"
    if ping -c 2 -W 2 "$TARGET" >/dev/null 2>&1; then
      report "ping $TARGET" "$TARGET replies to ICMP"
    fi
    blocked "no ICMP reply from $TARGET"
    ;;

  ssh)
    # A missing client is an agent-host gap. Checked BEFORE the probe so it can
    # never be mistaken for a device result.
    command -v ssh >/dev/null 2>&1 || die_host "no 'ssh' on PATH — install it or use --tcp"
    # Auth mechanism. BatchMode=yes is right when keys are in play and wrong
    # when they are not: it disables password auth outright, so on a device
    # offering only `publickey,password` it guarantees "no identity". When
    # SSHPASS is exported and sshpass is present, use it -- with `-e`, never
    # `-p`, because /proc/<pid>/cmdline is world-readable and a password in
    # argv is a password on the process list.
    ssh_auth=(ssh -o BatchMode=yes)
    auth_note="key/BatchMode"
    if [ -n "${SSHPASS:-}" ]; then
      if command -v sshpass >/dev/null 2>&1; then
        ssh_auth=(sshpass -e ssh -o PubkeyAuthentication=no)
        auth_note="password via SSHPASS"
      else
        die_host "SSHPASS is set but 'sshpass' is not on PATH — install it or use keys"
      fi
    fi
    if ! tcp_open "${TARGET#*@}" "$SSH_PORT"; then
      blocked "no TCP answer from ${TARGET#*@}:$SSH_PORT"
    fi
    # Each source is captured and TESTED separately. Chaining these with `||`
    # silently does nothing: `||` binds to the whole pipeline, and awk exits 0
    # when it matches no line, so on any host without a `Serial` line in
    # /proc/cpuinfo the fallbacks were dead code and a fully working session
    # reported "nothing answered".
    remote='id=$(awk -F": " "/^Serial/{print \$2; exit}" /proc/cpuinfo 2>/dev/null)
            [ -n "$id" ] || id=$(cat /sys/class/dmi/id/product_serial 2>/dev/null)
            [ -n "$id" ] || id=$(hostname 2>/dev/null)
            printf "%s\n" "$id"'
    # HOST-KEY VERIFICATION. A reachability probe against a lab device that may
    # be reimaged between runs is the classic reason to skip it, and that is what
    # this did unconditionally. But combined with SSHPASS it stops being a
    # convenience and becomes a credential-disclosure path (CWE-295): an on-path
    # attacker on the same LAN presents their own host key, we accept it in
    # silence, and then send the password to them. So the two cases are now
    # separated. With --known-hosts, verify properly. Without it, still probe --
    # a probe that refuses to run is a probe nobody keeps -- but say so on
    # stderr, and say it LOUDLY when a password is in play, which is the case
    # that actually leaks something.
    ssh_hostkey=(-o ConnectTimeout=8)
    if [ -n "${KNOWN_HOSTS:-}" ]; then
        ssh_hostkey+=(-o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KNOWN_HOSTS")
    else
        ssh_hostkey+=(-o StrictHostKeyChecking=no
                      -o UserKnownHostsFile=/dev/null
                      -o GlobalKnownHostsFile=/dev/null)
        if [ -n "${SSHPASS:-}" ]; then
            printf 'probe-device: WARNING — host-key verification is DISABLED and SSHPASS is set.\n' >&2
            printf 'probe-device:   An on-path attacker can impersonate %s and capture that password.\n' "$TARGET" >&2
            printf 'probe-device:   Pass --known-hosts FILE to verify the host key. Do not use this form\n' >&2
            printf 'probe-device:   over a network you do not control.\n' >&2
        else
            printf 'probe-device: note — host-key verification disabled (no --known-hosts given).\n' >&2
        fi
    fi
    id="$(timeout 20 "${ssh_auth[@]}" "${ssh_hostkey[@]}" \
            -p "$SSH_PORT" "$TARGET" "$remote" 2>/dev/null)"
    id="$(printf '%s' "$id" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [ -n "$id" ] || answered_unidentified \
      "ssh to $TARGET opened but returned no identity (tried $auth_note; export SSHPASS for a password-auth device)"
    report "ssh $TARGET ($auth_note)" "$id"
    ;;

  serial)
    # A path that is not there at all: the device node is absent, so nothing
    # answered. A path that IS there but we may not read (dialout group, say)
    # is a permissions gap on this host, not a fact about the device.
    if [ ! -e "$TARGET" ]; then
      blocked "identity source $TARGET does not exist"
    fi
    [ -r "$TARGET" ] || die_host "identity source $TARGET exists but is not readable (permissions?)"
    id="$(timeout 10 head -c 4096 "$TARGET" 2>/dev/null | head -n 1)"
    id="$(printf '%s' "$id" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [ -n "$id" ] || answered_unidentified "$TARGET is readable but reported nothing"
    report "identity source $TARGET" "$id"
    ;;

  discover)
    [ -d "$TARGET" ] || die_usage "--discover: not a directory: $TARGET"
    # Where the host actually lives: the repo's own deploy and HIL scripts, on
    # a line that actually REACHES it. Grepping every IP-shaped string in the
    # tree returns four-part version numbers, placeholder subnets and doc
    # examples — a candidate list nobody reads is as useless as no list, so
    # this is deliberately narrow: shell/Makefile sources only, and only lines
    # carrying a command that talks to a host.
    hits="$(
      find "$TARGET" -type f \( -name '*.sh' -o -name '*.bash' -o -name 'Makefile' \
                                -o -name 'makefile' -o -name 'GNUmakefile' \) \
           -not -path '*/.git/*' -print0 2>/dev/null \
      | xargs -0 -r grep -hE 'ssh|scp|rsync|ping|curl|nc |telnet|HOST|host' 2>/dev/null \
      | grep -oE '([a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])' \
      | grep -vE '(^|@)(0\.0\.0\.0|127\.0\.0\.1|255\.255\.255\.255|1\.2\.3\.4|8\.8\.8\.8)$' \
      | sort -u
    )"
    if [ -z "$hits" ]; then
      # Nothing was probed here, so this is not a device result. Saying BLOCKED
      # would be the excuse this script exists to remove.
      die_host "no host candidate found under $TARGET — nothing to probe"
    fi
    echo "probe-device: host candidates found in the repo's own scripts:"
    printf '%s\n' "$hits" | sed 's/^/  /'
    echo "probe-device: an unset variable was missing CONFIGURATION, not hardware."
    echo "probe-device: re-run with --ssh <one of the above> to prove it by I/O."
    exit 0
    ;;
esac

# Unreachable: every mode above exits. If control ever arrives here, no probe
# ran, so 2 is the honest code — never 78.
die_host "no probe ran"
