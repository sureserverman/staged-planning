#!/usr/bin/env bash
# plan-continue.sh — Codex `Stop` hook that keeps a plan in flight running. The Codex
# fork of the plugin's plan-continue.sh.
#
# WHY THIS EXISTS. On Codex a final assistant message ends the turn, and nothing
# resumes it: there is no task notification, so a run that stops to wait, announce
# or ask sits idle until the user types again. executing-plans § Run to completion
# already forbids those stops; this hook enforces it. Waiting on a spawned agent is
# done inside the turn (`wait_agent`), so a final stop is never a wait.
#
# WHAT IT DOES. A Codex `Stop` hook may return {"decision":"block","reason":…}, which
# makes Codex start a new turn with `reason` as its prompt. While a plan is in flight
# this hook returns that on every final stop, except the documented ways to stop, each
# read from the execution state rather than from the message:
#
#   * a recorded stop: plan-state.py set-blocker or a finished owned run; on a legacy
#     state file, phase `blocked`, `closeout` or `handoff`. An `ACTION NEEDED:` block
#     alone is not one: record the blocker first (stage-gate.md § ACTION NEEDED);
#   * on a legacy state file, a `RESUME HERE` block carrying context-usage.py's `reason:`
#     line (a measured handoff); a block without one is sent back to run context-usage.py;
#   * stale state (`updated` absent, more than an hour in the future, or older than 12 h);
#   * CODEX_PLAN_CONTINUE_MAX continuations (default 25) with no movement past the same
#     phase, stage and task, which ends the loop rather than the session. The default is
#     higher than Claude Code's 3 because every stop continues here, not only a
#     promise, so one long task legitimately ends many turns at one key.
#
# OPT-IN PER SESSION. The hook does nothing unless the Codex session was started with
# CODEX_PLAN_CONTINUE=1 in its environment (and the user trusts the hook in /hooks), so a
# second session in the same repo, an unrelated chat, is never pushed to continue a plan.
#
# IT FAILS OPEN, ALWAYS. No state file, unparseable JSON, a missing classifier module,
# garbage or stale timestamps: every one allows the stop. A Stop hook that fails closed
# traps a session in a loop the user cannot exit. `set -e` is deliberately NOT used and
# every exit is 0.

set -uo pipefail

PAYLOAD="$(cat)"

# Opt-in, checked before anything else can go wrong.
if [[ "${CODEX_PLAN_CONTINUE:-0}" != "1" ]]; then
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
# plan_continue_classify.py, beside this script, is shared with the Claude Code planning mod:
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

MAX_NO_PROGRESS = classifier.parse_max(os.environ.get("CODEX_PLAN_CONTINUE_MAX", "25"), 25)

try:
    with os.fdopen(3, encoding="utf-8", errors="replace") as _fh:
        payload = json.loads(_fh.read() or "{}")
except Exception:
    allow()
if not isinstance(payload, dict):
    allow()

# stop_hook_active says a continuation already fired. We do NOT blanket-allow on
# it: a plan legitimately needs many in a row. The no-progress counter below is
# the loop guard instead, and it is a better one because it measures whether the
# run is actually moving rather than merely whether it was pushed.

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
# The last message. Codex's Stop input carries it as `last_assistant_message` (absent
# when there is none). It is read to make a yes/no decision, never interpolated into
# the reason, which is built solely from clamped state-file fields.
# --------------------------------------------------------------------------
last_text = payload.get("last_assistant_message")
if not isinstance(last_text, str):
    last_text = ""


# --------------------------------------------------------------------------
# No-progress guard. Keyed per session so it needs no file in the user's repo.
# --------------------------------------------------------------------------
key = classifier.counter_key(state)
# Hashed, never interpolated raw: session_id is host-supplied and this is a
# filename. Folding the root in stops two repos in one session sharing a counter.
sid = hashlib.sha1(("%s|%s" % (payload.get("session_id") or "", root)).encode()).hexdigest()[:16]
counter_path = os.path.join(tempfile.gettempdir(), "codex-plan-continue-%s.json" % sid)

count = 0
try:
    rfd = os.open(counter_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(rfd, "r") as fh:
        prev = json.load(fh)
    if prev.get("key") == key:
        count = int(prev.get("count", 0))
except Exception:
    pass

# `count` is the continuations already forced at this key.
# An owned execution snapshot is decided by the shared module: it continues a run whose
# disposition is working or repairing, whatever the message says. On a legacy state
# file the module would let a waiting or quiet stop end, which suits a host that
# resumes a turn by itself; Codex does not, so every final stop continues there except
# the documented ones.
try:
    if "schema_version" in state:
        result = classifier.classify({"state": state, "last_text": last_text or ".",
                                      "count": count, "max": MAX_NO_PROGRESS})
    elif classifier.RESUME.search(last_text):
        m = classifier.RESUME.search(last_text)
        cu = os.environ.get("PLAN_CONTINUE_CONTEXT_USAGE", "")
        if classifier.REASON_LINE.search(last_text[m.start():]) or not os.path.isfile(cu):
            result = {"decision": "allow"}
        elif count >= MAX_NO_PROGRESS:
            result = {"decision": "allow", "system_message": classifier._bounded(
                lambda n: classifier.guard_message(state, count, n))}
        else:
            result = {"decision": "block", "reason": classifier._bounded(
                lambda n: classifier.handoff_reason(state, phase, cu, n))}
    elif count >= MAX_NO_PROGRESS:
        result = {"decision": "allow", "system_message": classifier._bounded(
            lambda n: classifier.guard_message(state, count, n))}
    else:
        where = classifier._where
        result = {"decision": "block", "reason": classifier._bounded(lambda n: (
            "Plan execution is still in flight: %s — %s. On Codex a final message ends "
            "the turn and nothing resumes it, so continue the work now: do not re-plan, "
            "re-verify finished work or summarise. Wait for spawned agents inside the "
            "turn with wait_agent. To stop on purpose, record it first: a documented Stop "
            "condition with plan-state.py set-blocker (on a legacy run, phase \"blocked\" "
            "in .claude/plan-progress.json), then the `ACTION NEEDED:` block naming the "
            "decision; or hand off at a gate on context-usage.py's `handoff` verdict with "
            "its reason: line."
        ) % (classifier.clean(state.get("plan"), "the plan", n), where(state, phase, n)))}
    decision = result.get("decision")
    reason = result.get("reason")
    message = result.get("system_message")
    if isinstance(message, str):   # the shared module names the other host's switches
        message = message.replace("Raise PLAN_CONTINUE_MAX or unset PLAN_CONTINUE",
                                  "Raise CODEX_PLAN_CONTINUE_MAX or unset CODEX_PLAN_CONTINUE")
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
