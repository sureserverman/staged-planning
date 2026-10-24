#!/usr/bin/env bash
# plan-continue.sh — Cursor `stop` hook that keeps a plan in flight running. The Cursor
# fork of the plugin's plan-continue.sh.
#
# WHY THIS EXISTS. On Cursor an assistant message ends the turn, and nothing resumes it:
# the moment the executor narrates ("Continuing Stage 3…") or summarises, the run waits
# for the user to type "carry on". executing-plans § Run to completion forbids those
# stops; this hook enforces it.
#
# WHAT IT DOES. A Cursor `stop` hook may print {"followup_message": "…"}, which Cursor
# submits as the next user message. While a plan is in flight this hook prints that on
# every stop, except the documented ways to stop, each read from the execution state,
# never from the message (Cursor's stop payload carries no message text):
#
#   * a recorded stop: plan-state.py set-blocker or a finished owned run; on a legacy
#     state file, phase `blocked` or `handoff` (the handoff of session-handoff.md is the
#     phase; a RESUME HERE block alone does not end the run), or `closeout` or
#     `stage-complete` once HEAD's history has that stage's `Stage N green` commit.
#     Until then those two are held, and so is any other phase outside preflight, task
#     and gate whose `### Stage N Gate` boxes are ticked: a stage claimed done with no
#     green commit is not done. plan-flip-audit.py's unrecorded_gate() decides, so the
#     hook and the audit agree. In preflight, task and gate the plan is in flight and a
#     completed stop continues regardless;
#   * an agent loop that ended with `status` other than `completed`: `aborted` is the
#     user interrupting, and this hook never fights an interrupt;
#   * stale state (`updated` absent, in the future, or older than 12 h);
#   * CURSOR_PLAN_CONTINUE_MAX continuations (default 25) with no movement past the same
#     phase, stage and task, which ends the loop rather than the session. Cursor's own
#     `loop_limit` (25 in hooks.json) is a second, independent bound.
#
# WHEN IT RUNS. Cursor fires `stop` only in an interactive session; a headless
# `cursor-agent -p` run never calls it (probe facts in hosts/cursor/host.yaml). It ships
# on the plugin route, so it is live wherever the plugin is installed, and inert unless
# the workspace's repo has a plan in flight. CURSOR_PLAN_CONTINUE=0 in Cursor's
# environment switches it off.
#
# WHAT DIFFERS FROM THE OTHER HOSTS. Cursor runs a plugin's stop hook from the workspace
# root, not the plugin folder, so hooks.json names this script through CURSOR_PLUGIN_ROOT:
# a relative command would run whatever the repo keeps at that path. The repo is found
# from the payload's first `workspace_roots` entry (CURSOR_PROJECT_DIR when the payload
# has none), and this script finds its siblings from its own path. The
# conversation is keyed by `conversation_id`. A stop that lets the turn end prints {}
# and says why on stderr.
#
# IT FAILS OPEN, ALWAYS. No state file, unparseable JSON, a missing classifier module,
# garbage or stale timestamps: every one lets the turn end. A stop hook that fails closed
# traps a session in a loop the user cannot exit. `set -e` is deliberately NOT used and
# every exit is 0.

set -uo pipefail

PAYLOAD="$(cat)"

# Kill switch, checked before anything else can go wrong.
if [[ "${CURSOR_PLAN_CONTINUE:-1}" == "0" ]]; then
    printf '{}\n'
    exit 0
fi

# Located from the script's RESOLVED path, so a hook reached through a symlink still
# finds its siblings instead of silently failing open.
SELF="${BASH_SOURCE[0]}"
SELF="$(realpath -- "$SELF" 2>/dev/null || readlink -f -- "$SELF" 2>/dev/null || printf '%s' "$SELF")"
HOOK_DIR="$(cd "$(dirname -- "$SELF")" 2>/dev/null && pwd)"
CLASSIFIER="$HOOK_DIR/plan_continue_classify.py"
AUDIT="$HOOK_DIR/../skills/executing-plans/scripts/plan-flip-audit.py"

# -I (isolated): `python3 -` otherwise puts the cwd first on sys.path. The payload goes on
# fd 3 through a pipe: one environment string is capped at 128 KiB, and argv is
# world-readable in /proc. The closing `exit 0` keeps a failed python3 from reaching Cursor.
# pipefail off here: a writer cut short by SIGPIPE must not add a second answer.
set +o pipefail
printf '%s' "$PAYLOAD" | PLAN_CONTINUE_CLASSIFIER="$CLASSIFIER" PLAN_CONTINUE_AUDIT="$AUDIT" \
    python3 -I - 3<&0 <<'PY' || printf '{}\n'
import json, os, sys, hashlib, tempfile


def allow(msg=None):
    """Let the turn end. A note goes to stderr: Cursor reads stdout as the decision."""
    if msg:
        sys.stderr.write(msg.rstrip() + "\n")
    print("{}")
    sys.exit(0)


def follow_up(text):
    json.dump({"followup_message": text}, sys.stdout)
    sys.exit(0)


try:
    import importlib.util
    sys.dont_write_bytecode = True   # nothing written into the plugin directory
    _spec = importlib.util.spec_from_file_location(
        "plan_continue_classify", os.environ.get("PLAN_CONTINUE_CLASSIFIER", ""))
    classifier = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(classifier)
except Exception:
    allow()

MAX_NO_PROGRESS = classifier.parse_max(os.environ.get("CURSOR_PLAN_CONTINUE_MAX", "25"), 25)

try:
    with os.fdopen(3, encoding="utf-8", errors="replace") as _fh:
        payload = json.loads(_fh.read() or "{}")
except Exception:
    allow()
if not isinstance(payload, dict):
    allow()

# Only a normally completed agent loop is resumed: `aborted` is the user interrupting,
# `error` a run already broken. An absent status is the documented default shape.
status = payload.get("status")
if status is not None and str(status) != "completed":
    allow("plan-continue: the agent loop ended with status %s; not resuming."
          % classifier.clean(status))

roots = payload.get("workspace_roots")
start = roots[0] if isinstance(roots, list) and roots and isinstance(roots[0], str) \
    else os.environ.get("CURSOR_PROJECT_DIR", "")
if not start:
    allow()
# The repo-root boundary (the module's find_repo_root): depth-bounded, `.git` files
# count, a world-writable candidate root is refused; None means allow.
root = classifier.find_repo_root(start)
if root is None:
    allow()

state = classifier.read_state(root)
if state is None:
    allow()
if state.get("state_status") == "state_error":
    allow("plan-continue: state_error; diagnose the execution snapshot before mutating it.")

phase = str(state.get("phase", "")).strip().lower()


def unrecorded_gate():
    """The stage claimed done with no `Stage N green` commit, from the plan audit's
    unrecorded_gate() when the shipped audit has one; else None. Fails open."""
    try:
        spec = importlib.util.spec_from_file_location(
            "plan_flip_audit", os.environ.get("PLAN_CONTINUE_AUDIT", ""))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        check = getattr(mod, "unrecorded_gate", None)
        plan = state.get("plan")
        if check is None or not isinstance(plan, str) or not plan or len(plan) > 4096:
            return None
        return check(root, plan if os.path.isabs(plan) else os.path.join(root, plan))
    except Exception:
        return None


# Legacy allow-list: a phase added to the old contract later fails OPEN. `blocked` is a
# documented Stop condition, `closeout` ends by offering merge options that must not be
# auto-answered, `handoff` is the recorded stop of session-handoff.md (on Cursor, a dated wait). Validated v2
# snapshots use the structured disposition in the classifier instead.
claimed = None
if "schema_version" not in state and phase not in ("preflight", "task", "gate"):
    claimed = unrecorded_gate()
    if claimed is None:
        allow()

stale = classifier.stale_message(state)
if stale is not None:
    allow(stale)

# No-progress guard. Keyed per conversation so it needs no file in the user's repo.
key = classifier.counter_key(state)
# Hashed, never interpolated raw: the id is host-supplied and this is a filename. Folding
# the root in stops two repos in one conversation sharing a counter.
cid = payload.get("conversation_id") or payload.get("session_id") or ""
sid = hashlib.sha1(("%s|%s" % (cid, root)).encode("utf-8", "surrogatepass")).hexdigest()[:16]
counter_path = os.path.join(tempfile.gettempdir(), "cursor-plan-continue-%s.json" % sid)

count = 0
try:
    rfd = os.open(counter_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(rfd, "r") as fh:
        prev = json.load(fh)
    if prev.get("key") == key:
        count = int(prev.get("count", 0))
except Exception:
    pass

# An owned execution snapshot is decided by the shared module: it continues a run whose
# disposition is working or repairing. On a legacy state file every stop in flight
# continues, since nothing else resumes a Cursor turn.
try:
    where = classifier._where
    plan_name = lambda n: classifier.clean(state.get("plan"), "the plan", n)
    if "schema_version" in state:
        result = classifier.classify({"state": state, "last_text": ".", "count": count,
                                      "max": MAX_NO_PROGRESS})
    elif count >= MAX_NO_PROGRESS:
        result = {"decision": "allow", "system_message": classifier._bounded(
            lambda n: classifier.guard_message(state, count, n))}
    elif claimed is not None:
        result = {"decision": "block", "reason": classifier._bounded(lambda n: (
            "Stage %s of %s is marked done (its gate boxes are ticked or the state file says "
            "phase \"%s\"), but this repo has no `Stage %s green` commit, so the gate was never "
            "recorded and nothing it claims was checked. Run the gate now (executing-plans § "
            "the stage gate): its checks, the review and the demo evaluator, then prove every "
            "claim of every task of the stage and commit `Stage %s green` with the records — "
            "the git hook refuses it without them. If the gate cannot pass, untick its boxes, "
            "record the blocker, and report."
        ) % (classifier.clean(claimed, "?", n), plan_name(n), classifier.clean(phase, "?", n),
             classifier.clean(claimed, "?", n), classifier.clean(claimed, "?", n)))}
    else:
        result = {"decision": "block", "reason": classifier._bounded(lambda n: (
            "Plan execution is still in flight: %s — %s. Resume the executing-plans loop "
            "from exactly that point: do not re-plan, re-verify finished work or summarise. "
            "On Cursor an assistant message ends the turn, so keep progress in the state file "
            "and the plan's Status: fields, not in narration. To stop on purpose, record it "
            "first: a documented Stop condition as phase \"blocked\" in "
            ".claude/plan-progress.json (or plan-state.py set-blocker on an owned run), then "
            "the `ACTION NEEDED:` block; or hand off at a gate by writing phase \"handoff\"."
        ) % (plan_name(n), where(state, phase, n)))}
    decision = result.get("decision")
    reason = result.get("reason")
    message = result.get("system_message")
    if isinstance(message, str):   # the shared module names the other host's switches
        message = message.replace("Raise PLAN_CONTINUE_MAX or unset PLAN_CONTINUE",
                                  "Raise CURSOR_PLAN_CONTINUE_MAX or set CURSOR_PLAN_CONTINUE=0")
except Exception:
    allow()

if decision != "block" and not message:
    allow()     # let it end; the counter is not touched

count += 1
try:
    # O_NOFOLLOW: the tmpdir is world-writable, and a symlink pre-planted here would make
    # the write follow it — an arbitrary file write as the user. 0600 keeps it private.
    wfd = os.open(counter_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(wfd, "w") as fh:
        json.dump({"key": key, "count": count}, fh)
except Exception:
    # A count that cannot be stored leaves no loop guard, so this stop is allowed rather
    # than continued: a follow-up now could repeat on every turn end.
    allow(message if isinstance(message, str) and message else
          "plan-continue: the no-progress count could not be stored, so there is no loop "
          "guard; letting the turn end.")

if decision != "block" or not isinstance(reason, str) or not reason:
    allow(message if isinstance(message, str) else None)

follow_up(reason)
PY

# Every exit is 0, the script's own invariant rather than one borrowed from the host.
exit 0
