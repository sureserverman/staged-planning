#!/usr/bin/env bash
# plan-continue.sh — Claude Code `Stop` hook that refuses a turn ending on a
# promise while a plan is in flight.
#
# WHY THIS EXISTS. `../skills/executing-plans/SKILL.md` § Run to completion already
# forbids this ("Never end a turn on an announcement", "stage boundaries are
# checkpoints, not approval gates"). The rule is read once, at session start, and
# the failure it describes happens hundreds of thousands of tokens later. Measured
# over 39 turn ends (two sessions executing one master plan, 2026-08-29/30):
#
#   * 30 ended waiting on a dispatched agent or a background suite. Every one was
#     resumed automatically by the harness's task notification within 0.5-51 min.
#     These are CORRECT on this host and must never be blocked.
#   *  7 ended on a future-tense promise or an approval question with nothing
#      pending: an announcement that the next task is starting, a "next is" line,
#      or an offer to start once the user says so. A stop like this needs a human
#      nudge, and the run sits idle until one comes.
#   *  2 were neither.
#
# THAT ASYMMETRY IS THE WHOLE DESIGN. Blocking EVERY turn end while a plan runs suits
# a host where an assistant message *is* the turn boundary. Here it would fight the
# harness: it would force ~30 pointless continuations, each spinning against agents
# that have not reported yet. So this hook blocks only on a narrow classifier over
# the last assistant message, behind an in-flight signal and hardened reads.
#
# WHAT IT DOES. A Claude Code `Stop` hook may return {"decision":"block","reason":…},
# which keeps the turn going and hands `reason` to the model. This hook returns that
# only when ALL of the following hold:
#
#   1. PLAN_CONTINUE=1              — opt-in; the default is off.
#   2. .claude/plan-progress.json   — phase is preflight/task/gate. `closeout` and
#                                     `blocked` are excluded (see the allow-list). An
#                                     owned v2 run self-disables at `finish`
#                                     (disposition complete, the snapshot kept as
#                                     evidence); legacy state is deleted at close-out.
#   3. The last assistant message   — matches PROMISE or ASK, and matches neither
#                                     WAIT nor `ACTION NEEDED:`.
#
# Measured against the 39 turn ends above: 7/7 of the bad stops caught, 0 of the 30
# legitimate waits blocked, and 1 of the 2 others blocked — an announcement ending (a
# promise to re-run the gate and then start the next stage) that the harness resumed
# unaided. Blocking it is the intended reading, not a miss: the classifier reads the
# message, not whatever happens to be pending.
#
# TWO DOCUMENTED WAYS TO STOP ON PURPOSE, both already in the skill's contract:
# write `ACTION NEEDED:` (stage-gate.md § the one place a report asks the user for
# something), or write phase:"blocked" to the state file (a documented Stop
# condition). Neither is invented here; the hook reads the contract that exists.
#
# IT FAILS OPEN, ALWAYS. No state file, unreadable transcript, unparseable JSON,
# missing or garbage timestamp, stale state, no progress — every one allows the
# stop. A Stop hook that fails closed traps a session in a loop the user cannot
# exit, which is strictly worse than the problem it solves. `set -e` is deliberately
# NOT used and every exit is 0.
#
# Kill switch: PLAN_CONTINUE=0 (or simply unset).
#
# IT STEPS ASIDE UNDER CURSOR. cursor-agent runs a Claude Code plugin's Stop hook too,
# and its payload carries a top-level `cursor_version` key. The Cursor build of this
# plugin has its own stop hook, so a payload with that key gets no answer from this one.

set -uo pipefail

PAYLOAD="$(cat)"

# Opt-in, checked before anything else can go wrong.
if [[ "${PLAN_CONTINUE:-0}" != "1" ]]; then
    exit 0
fi

# The payload never goes in argv: /proc/<pid>/cmdline is world-readable, so passing it
# as an argument would publish session_id and the repo root to every local user, and
# make the counter path below predictable enough to pre-plant a symlink at.
# The measured-handoff nudge tells the executor to run this script; resolved beside
# the hook so a hook installed without it can fail open instead of sending the
# executor after a file that is not there.
# Located from the script's RESOLVED path, so a hook reached through a symlink still
# finds its siblings instead of silently failing open; BASH_SOURCE is the fallback
# where neither realpath nor readlink -f exists.
SELF="${BASH_SOURCE[0]}"
SELF="$(realpath -- "$SELF" 2>/dev/null || readlink -f -- "$SELF" 2>/dev/null || printf '%s' "$SELF")"
HOOK_DIR="$(cd "$(dirname -- "$SELF")" 2>/dev/null && pwd)"
CONTEXT_USAGE="$HOOK_DIR/../skills/executing-plans/scripts/context-usage.py"
# The classifier is a sibling module; absent, the hook fails open.
CLASSIFIER="$HOOK_DIR/plan_continue_classify.py"

# -I (isolated): `python3 -` otherwise puts the cwd — the user's repo, possibly a
# hostile clone — first on sys.path, so a planted hashlib.py would run as the user.
# The payload goes on fd 3 through a pipe: one environment string is capped at 128 KiB,
# and argv is world-readable in /proc. Every exit before Python reads it is an allow, and
# the closing `exit 0` keeps a SIGPIPE'd printf from reaching the host.
printf '%s' "$PAYLOAD" | PLAN_CONTINUE_CONTEXT_USAGE="$CONTEXT_USAGE" \
    PLAN_CONTINUE_CLASSIFIER="$CLASSIFIER" python3 -I - 3<&0 <<'PY'
import json, os, sys, hashlib, tempfile


def allow(msg=None):
    """Let the turn end. Optionally surface one line to the user."""
    if msg:
        json.dump({"systemMessage": msg}, sys.stdout)
    sys.exit(0)


# --------------------------------------------------------------------------
# plan_continue_classify.py, beside this script, is shared with the planning mod:
# the repo-root boundary, the hardened file reads (read_own_file, read_state),
# PLAN_CONTINUE_MAX parsing, the counter key, the staleness rule, PROMISE/ASK/WAIT/RESUME, the
# `ACTION NEEDED` and `reason:` carve-outs, clean() and both reason builders. A
# missing or failing module allows: this hook never traps a session on its own
# breakage.
# --------------------------------------------------------------------------
try:
    import importlib.util
    sys.dont_write_bytecode = True   # nothing written into the plugin directory
    _spec = importlib.util.spec_from_file_location(
        "plan_continue_classify", os.environ.get("PLAN_CONTINUE_CLASSIFIER", ""))
    classifier = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(classifier)
except Exception:
    allow()

MAX_NO_PROGRESS = classifier.parse_max(os.environ.get("PLAN_CONTINUE_MAX", "3"))

try:
    with os.fdopen(3, encoding="utf-8", errors="replace") as _fh:
        payload = json.loads(_fh.read() or "{}")
except Exception:
    allow()
if not isinstance(payload, dict) or "cursor_version" in payload:
    allow()

# stop_hook_active says a continuation already fired. We do NOT blanket-allow on
# it: a plan legitimately needs several in a row. The no-progress counter below is
# the loop guard instead, and it is a better one because it measures whether the
# run is actually moving rather than merely whether it was pushed.
# On Claude Code 2.1.288+ the planning mod answers classic.Stop first and, when the
# module gave it an answer, passes the event on with this field set, so user Stop
# hooks still run but this one — the same decision, from the same module — does
# not run twice. Unset (no last message on the event, a failed run), this decides.
if payload.get("planning_mod_handled") is True:
    allow()

# The repo-root boundary (the module's find_repo_root): depth-bounded, `.git` files
# count, a world-writable candidate root is refused; None means allow.
root = classifier.find_repo_root(payload.get("cwd") or os.getcwd())
if root is None:
    allow()

# Opened component by component under the root with O_NOFOLLOW, FIFO-safe,
# owner-checked, 256 KB.
state = classifier.read_state(root)
if state is None:
    allow()
if state.get("state_status") == "state_error":
    allow("plan-continue: state_error; diagnose the execution snapshot before mutating it.")

phase = str(state.get("phase", "")).strip().lower()

# Legacy allow-list: a phase added to the old contract later fails
# OPEN. `blocked` means a documented Stop condition already halted the run and
# said so. `closeout` matters just as much: close-out ends by offering merge
# options that must not be auto-answered, and its remaining steps are short and
# end by deleting this file, so continuing through it buys nothing. It is also
# the phase at a master plan's sub-plan boundary. `handoff` is the measured stop
# of session-handoff.md: context-usage.py said so, and the reason is on record.
# Validated v2 snapshots instead use the structured disposition in the classifier.
if "schema_version" not in state and phase not in ("preflight", "task", "gate"):
    allow()

# Staleness — absent, garbage, FUTURE or >12h `updated` — is the module's rule.
stale = classifier.stale_message(state)
if stale is not None:
    allow(stale)

# --------------------------------------------------------------------------
# The classifier. Applied to the LAST assistant message only, and its text is
# read to make a yes/no decision — never interpolated into the reason, which is
# built solely from clamped state-file fields.
# --------------------------------------------------------------------------
MAX_TRANSCRIPT_TAIL = 512 * 1024

transcript = payload.get("transcript_path")
if not isinstance(transcript, str) or not transcript:
    allow()
blob = classifier.read_own_file(transcript, MAX_TRANSCRIPT_TAIL, tail=True)
if not blob:
    allow()

last_text = None
lines = blob.splitlines()
# The tail may begin mid-line; that first fragment is dropped by json.loads failing.
for line in reversed(lines):
    try:
        row = json.loads(line)
    except Exception:
        continue
    if not isinstance(row, dict) or row.get("type") != "assistant":
        continue
    if row.get("isSidechain"):        # a subagent's own transcript, not ours
        continue
    msg = row.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    else:
        continue
    if text.strip():
        last_text = text
        break

if not last_text:
    allow()


# --------------------------------------------------------------------------
# No-progress guard. Keyed per session so it needs no file in the user's repo.
# --------------------------------------------------------------------------
key = classifier.counter_key(state)
# Hashed, never interpolated raw: session_id is host-supplied and this is a
# filename. Folding the root in stops two repos in one session sharing a counter.
sid = hashlib.sha1(("%s|%s" % (payload.get("session_id") or "", root)).encode()).hexdigest()[:16]
counter_path = os.path.join(tempfile.gettempdir(), "claude-plan-continue-%s.json" % sid)

count = 0
try:
    rfd = os.open(counter_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(rfd, "r") as fh:
        prev = json.load(fh)
    if prev.get("key") == key:
        count = int(prev.get("count", 0))
except Exception:
    pass

# `count` is the continuations already forced at this key; the module releases the
# turn (with a system_message) once it reaches MAX_NO_PROGRESS.
try:
    result = classifier.classify({"state": state, "last_text": last_text, "count": count,
                                  "max": MAX_NO_PROGRESS,
                                  "context_usage_path": os.environ.get("PLAN_CONTINUE_CONTEXT_USAGE", "")})
    decision = result.get("decision")
    reason = result.get("reason")
    message = result.get("system_message")
except Exception:
    allow()

if decision != "block" and not message:
    allow()     # the classifier let it end; the counter is not touched

# The classifier matched: count this continuation, whether or not the guard released it.
count += 1
try:
    # O_NOFOLLOW: the tmpdir is world-writable, and a symlink pre-planted here would
    # make open(path,"w") overwrite whatever it points at — an arbitrary file write as
    # the user. 0600 keeps the counter unreadable by whoever planted it.
    wfd = os.open(counter_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(wfd, "w") as fh:
        json.dump({"key": key, "count": count}, fh)
except Exception:
    # A count that cannot be stored leaves no loop guard, so this stop is allowed
    # rather than blocked: a block now could repeat on every turn end.
    allow(message if isinstance(message, str) and message else
          "plan-continue: the no-progress count could not be stored, so there is no "
          "loop guard; letting the turn end.")

if decision != "block" or not isinstance(reason, str) or not reason:
    allow(message if isinstance(message, str) else None)

json.dump({"decision": "block", "reason": reason}, sys.stdout)
sys.exit(0)
PY

# The invariant this file claims is "every exit is 0", and it must be the script's
# own rather than borrowed from the host's fail-open treatment of odd exit codes:
# python3 absent from PATH (127), an OOM kill, or a bad env override would otherwise
# leak that code to a host that may one day read it as fail-closed.
exit 0
