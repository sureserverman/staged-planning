#!/usr/bin/env python3
"""plan_continue_classify.py — the decision half of the `plan-continue` Stop hook.

Two callers share it: plan-continue.sh (the command hook, which imports this file
and keeps only the transcript tail and the counter file), and the planning mod,
which runs it as a CLI:

    python3 plan_continue_classify.py  < {"state": {...}, "last_text": "...",
                                          "count": 0, "max": 3,
                                          "context_usage_path": "/.../context-usage.py"}
    -> {"decision": "allow" | "block", "reason"?: "...", "system_message"?: "...",
        "notice"?: "..."}

    python3 plan_continue_classify.py --inputs  < {"cwd": "/some/dir", "max": "<PLAN_CONTINUE_MAX>"}
    -> {"root": "/the/repo" | null, "state": {...} | null, "key": "phase|stage|task" | null,
        "max": 3}
       (find_repo_root, the hardened read_state, counter_key and parse_max: what a
        caller gathers before it classifies, each with one implementation here)

`state` is the parsed .claude/plan-progress.json, `last_text` the last main-thread
assistant message, `count` how many continuations this phase|stage|task has already
been forced, `max` the limit (PLAN_CONTINUE_MAX). `system_message` is set only when
the no-progress guard releases a turn the classifier would have blocked; a caller
that keeps the counter advances it when the decision is `block` or that message is
present, and on nothing else — except that the mod does not count a block another
Stop hook's block pre-empted. A caller that cannot store the advanced count allows:
without it the guard is gone. With `"check_updated": true` the module also applies the
staleness rule (stale_message) and answers a stale state with an uncounted `notice`.

THE CONTRACT IS FAIL-OPEN. Stdlib only. Malformed, non-object or oversized stdin, a
wrong-typed field, or any internal error prints {"decision":"allow"} and exits 0 —
never a traceback, never a non-zero exit. A Stop hook that fails closed traps the
session in a loop the user cannot leave.

EVERY INPUT STRING IS UNTRUSTED. A repo can commit .claude/plan-progress.json, so a
cloned repo's state file is user-owned and still hostile. Every state field that
reaches `reason` or `system_message` goes through clean() (whitespace flattened,
200 chars), and the whole reason is held to MAX_REASON_BYTES. `last_text` is read to
make a yes/no decision and is never quoted back.

The measurement behind the rules (39 turn ends over two sessions of one master
plan, 2026-08-29/30: 7/7 bad stops caught, 0/30 legitimate waits blocked) is in plan-continue.sh's header and
../skills/executing-plans/references/plan-continue-hook.md.
"""

import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

ALLOW = {"decision": "allow"}

# An allow-list, so a phase added to the contract later fails open. `closeout`,
# `blocked` and `handoff` are deliberate stops (see plan-continue.sh).
ACTIVE_PHASES = ("preflight", "task", "gate")

DEFAULT_MAX = 3
MAX_FIELD = 200
MAX_REASON_BYTES = 2048
MAX_STDIN_BYTES = 8 * 1024 * 1024
MAX_SHOWN_COUNT = 10 ** 6

# A promise about the next unit of plan work.
PROMISE = re.compile(
    r"\b(next(?: is| up)?[:,]?\s+(?:task|stage)"
    r"|starting (?:now )?with (?:task|stage)"
    r"|i'?ll (?:start|begin|move|run|do)"
    r"|then (?:task|stage)\s*\d"
    r"|moving (?:on )?to (?:task|stage)"
    r"|proceeding to (?:task|stage)"
    r"|follows? next)\b", re.I)

# Asking permission to continue between green units — which SKILL.md § Run to
# completion names as the failure mode the skill exists to prevent.
ASK = re.compile(
    r"\b(want me to (?:carry|continue|proceed|start|go)"
    r"|ready to (?:start|begin|move)"
    r"|shall i (?:carry|continue|proceed|start)"
    r"|say the word"
    r"|whenever you want me to"
    r"|let me know (?:if|when) you"
    r"|or (?:would you rather|do you want)"
    r"|carry straight on)\b", re.I)

# Genuinely parked on work that the harness will report. These turn ends are
# correct on this host and are 30 of the 39 measured.
WAIT = re.compile(
    r"\b(waiting on|wait for"
    r"|once (?:it|they|both|the)"
    r"|when (?:it|they|both|the)\b.{0,30}\b(?:land|report|clear|finish|complete)"
    r"|still running|holding|blocked on|the monitor will|until (?:it|they))\b", re.I)

# A measured handoff (session-handoff.md) is a legal stop only when it carries
# context-usage.py's `reason:` line — a RESUME HERE block without one is a stop
# judged by eye rather than measured.
RESUME = re.compile(r"RESUME HERE", re.I)
REASON_LINE = re.compile(r"^[\s>*`_-]*reason:\s*\S", re.I | re.M)


# Unicode categories no field may carry into model-bound text: controls (Cc), the
# invisible format characters (Cf: bidi overrides and isolates, zero-width marks,
# soft hyphen, the tag block used to smuggle hidden ASCII) and lone surrogates (Cs).
# A category, not a list, so a code point added to one later is covered too.
HIDDEN_CATEGORIES = ("Cc", "Cf", "Cs")


def clean(value, default="", limit=MAX_FIELD):
    """Bound and flatten one untrusted field: newlines let planted text escape the
    sentence it sits in; invisible characters hide or reorder what the reader sees;
    length turns a 100 KB field into a 100 KB prompt."""
    text = str(value if value is not None else default)
    # Whitespace first (a newline becomes a space, not a joined word), then every
    # hidden character goes. A lone surrogate ("\ud800", legal in JSON) would make
    # every later .encode() raise, turning a would-be block into an allow.
    text = " ".join(text.split())
    text = "".join(c for c in text if unicodedata.category(c) not in HIDDEN_CATEGORIES)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "...(truncated)"
    return text


def _int(value, default):
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _where(state, phase, limit):
    where = "phase %s, stage %s, task %s" % (clean(phase, "?", limit),
                                             clean(state.get("stage"), "?", limit),
                                             clean(state.get("task"), "?", limit))
    desc = clean(state.get("task_desc"), "", limit)
    if desc:
        where += " (%s)" % desc
    return where


def guard_message(state, count, limit=MAX_FIELD):
    key = "|".join(clean(str(state.get(k, "")), "", limit) for k in ("phase", "stage", "task"))
    return ("plan-continue: %d continuations with no movement past %s — letting the turn "
            "end so you can look. Raise PLAN_CONTINUE_MAX or unset PLAN_CONTINUE if this "
            "is wrong." % (count, key))


def handoff_reason(state, phase, context_usage_path, limit=MAX_FIELD):
    return (
        "You ended that turn with a RESUME HERE block that has no `reason:` line, while "
        "plan execution is in flight: %s — %s.\n\n"
        "executing-plans § Context resets / session-handoff.md: a handoff is a legal stop "
        "only on context-usage.py's verdict. Run it now, in its own Bash call:\n"
        "  python3 %s --plan <plan> --next-stage <N>\n"
        "On `handoff`, paste its reason: line into the RESUME HERE block verbatim and "
        "stop. On `continue` or `unknown`, delete the block and start the next stage now."
    ) % (clean(state.get("plan"), "the plan", limit), _where(state, phase, limit),
         clean(context_usage_path, "context-usage.py", limit))


def promise_reason(state, phase, limit=MAX_FIELD):
    return (
        "You ended that turn on an announcement or a question while plan execution is "
        "still in flight: %s — %s.\n\n"
        "executing-plans § Run to completion: stage boundaries are checkpoints, not "
        "approval gates, and the tool call opening announced work goes in the SAME turn "
        "as the sentence announcing it. Start the announced work now — do not re-plan, "
        "do not re-verify finished work, and do not summarise what you have done.\n\n"
        "If you genuinely need to stop, do it the documented ways rather than by "
        "trailing off: write an `ACTION NEEDED:` block naming the decision that blocks "
        "the next stage, record it with `plan-state.py set-blocker` when a documented "
        "Stop condition has fired (on a legacy run, phase:\"blocked\" in "
        ".claude/plan-progress.json), or hand off at a gate on context-usage.py's "
        "`handoff` verdict with its reason: line. Waiting on a dispatched agent is not a "
        "stop — say what you are waiting on and this hook will let the turn end."
    ) % (clean(state.get("plan"), "the plan", limit), _where(state, phase, limit))


def _bounded(build):
    """Hold a reason (or the guard's system_message) to MAX_REASON_BYTES. Normal fields never reach the cap; when
    hostile ones do, tighten the per-field bound first so the instructions survive
    whole, and only then cut."""
    for limit in (MAX_FIELD, 60, 20):
        reason = build(limit)
        if len(reason.encode("utf-8", "replace")) <= MAX_REASON_BYTES:
            return reason
    cut = reason.encode("utf-8", "replace")[:MAX_REASON_BYTES - len(b"...(truncated)")]
    return cut.decode("utf-8", "ignore") + "...(truncated)"


# --------------------------------------------------------------------------
# Repo root. THE HOOK'S SECURITY BOUNDARY, shared by both callers so it has one
# implementation: the command hook imports it, the mod asks for it through
# `--inputs`. The state file's `plan`/`task_desc` go into a prompt the host
# replays, so a climb to `/` for any `.git` would let a `.git` planted in a shared
# ancestor make the hook submit attacker-chosen text. Depth-bounded, `.git` FILES
# count (worktrees), and a world-writable candidate root is refused.
# Every failure returns None, and None means allow.
# --------------------------------------------------------------------------
def find_repo_root(start, max_depth=16):
    try:
        probe = os.path.abspath(start)
    except Exception:
        return None
    for _ in range(max_depth + 1):
        marker = os.path.join(probe, ".git")
        if os.path.isdir(marker) or os.path.isfile(marker):
            try:
                st = os.stat(probe)
            except OSError:
                return None
            # WORLD-writable only, deliberately not group-writable: with umask 002
            # an ordinary mkdir yields 775, so refusing group-writable disables the
            # hook in normal users' own repos — hardening into a fail-closed hole.
            if st.st_mode & 0o002:
                return None
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    return None


MAX_STATE_BYTES = 256 * 1024


def read_own_file(path, max_bytes, tail=False, dir_fd=None):
    """Open ONCE and check the descriptor; return text, or None for any failure.

    O_NOFOLLOW  a symlinked state file would leak another repo's plan text.
    O_NONBLOCK  os.open on a FIFO BLOCKS until a writer appears, so S_ISREG below
                is never reached and the hook hangs until the host kills it — on
                every single turn end.
    fstat       ownership and regular-file checked on the open fd, not by path,
                so the name cannot be swapped in between.
    """
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if st.st_uid != os.getuid():
            return None
        if not tail and st.st_size > max_bytes:
            return None
        if tail and st.st_size > max_bytes:
            os.lseek(fd, st.st_size - max_bytes, os.SEEK_SET)
        with os.fdopen(fd, "r", errors="replace") as fh:
            fd = None
            return fh.read(max_bytes + 1)
    except Exception:
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def execution_state_module():
    path=Path(__file__).resolve().parents[1]/'skills/executing-plans/scripts/plan_state.py'
    spec=importlib.util.spec_from_file_location('execution_state',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owned_state_fallback(root):
    """Use the shared bound for owned v2; legacy unusable files stay compatible."""
    try:
        module=execution_state_module()
        owner=module.owner_of(root)
    except Exception:
        return None  # an unregistered repository cannot own this protocol's run
    try:
        if module.read_pointer(owner) is not None:
            outcome=module.result(root,'show',{})
            if outcome['status']=='ok':
                return outcome['state']
            return {'state_status':'state_error','note':'owned execution snapshot is missing or unreadable'}
    except Exception:
        return {'state_status':'state_error','note':'invalid owned execution discovery metadata'}
    return None


MAX_PLAN_BYTES = 4 * 1024 * 1024
OPEN_TASK = re.compile(r"^\s*[-*+]\s*\*\*Status:\*\*\s*\[ \]", re.M)


def finished(state, root):
    """True when an owned v2 snapshot is `complete` AND the plan it names has no open
    task. `finish` is one self-attested call, so a snapshot marked complete over a plan
    with an unticked task still owns that plan's task numbers: the gates keep checking
    it. A plan that is gone owns nothing; one present but unreadable is not shown finished."""
    if not (isinstance(state, dict) and state.get("schema_version") == 2
            and state.get("disposition") == "complete"):
        return False
    plan = state.get("plan")
    if not isinstance(plan, str) or not plan:
        return True  # no plan named: there are no task numbers to own
    path = Path(plan) if os.path.isabs(plan) else Path(root) / plan
    try:
        with open(path, "rb") as fh:
            text = fh.read(MAX_PLAN_BYTES + 1).decode("utf-8", "replace")
    except FileNotFoundError:
        return True  # the plan is gone: no task numbers left to own, as the gates read it
    except OSError:
        return False
    return len(text) <= MAX_PLAN_BYTES and not OPEN_TASK.search(text)


def read_state(root):
    """The parsed <root>/.claude/plan-progress.json, or None.

    O_NOFOLLOW covers only the last component of a path, so a `.claude` directory
    symlinked out of the repo would still be followed. Opened one component at a
    time instead — the root, then `.claude` with O_NOFOLLOW | O_DIRECTORY relative
    to it, then the file relative to that — so no symlink below the root is
    followed and nothing can be swapped between a check and the open.
    """
    root_fd = dir_fd = None
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        dir_fd = os.open(".claude", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        raw = read_own_file("plan-progress.json", MAX_STATE_BYTES, dir_fd=dir_fd)
        if raw is None:
            return owned_state_fallback(root)
        state = json.loads(raw)
    except Exception:
        return owned_state_fallback(root)
    finally:
        for fd in (dir_fd, root_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
    if not isinstance(state, dict):
        return owned_state_fallback(root)
    if 'schema_version' not in state:
        owned=owned_state_fallback(root)
        if owned is not None:
            return owned
        return state  # labeled legacy display/classification compatibility
    if 'schema_version' in state:
        # The delivered helper owns schema and worktree identity. Load it from
        # the trusted plugin layout, never from the caller's repository sys.path.
        try:
            module=execution_state_module()
            outcome=module.result(root,'show',{})
            if outcome['status']=='ok':
                return outcome['state']
        except Exception:
            pass
        return {'state_status':'state_error','note':'unsupported or invalid owned execution snapshot'}
    return state


def parse_max(raw, default=DEFAULT_MAX):
    """PLAN_CONTINUE_MAX as Python int() reads it; anything else is the default.

    Clamped to +-MAX_SHOWN_COUNT: a 400-digit value is a legal int here but turns
    into Infinity, then null, on a JSON round trip through the mod.
    """
    if not isinstance(raw, str):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(-MAX_SHOWN_COUNT, min(value, MAX_SHOWN_COUNT))


def counter_key(state):
    """Reset on execution movement, preserving the escape across metadata churn."""
    keys=("phase","stage","task")
    if state.get('schema_version')==2:
        # Revisions advance for idempotent-looking control writes too. They do
        # not establish progress. Both Stop surfaces consume this same key.
        progress={k:state.get(k) for k in ('run_id',*keys,'disposition')}
        rounds=state.get('rounds') or {};active=rounds.get('active')
        verification=active.get('verification') if isinstance(active,dict) else None
        progress['rounds']={'completed':rounds.get('completed'),
            'active':active.get('number') if isinstance(active,dict) else None,
            'verification':{k:verification.get(k) for k in ('checks','worktree_digest')}
                if isinstance(verification,dict) else None}
        gate=state.get('gate')
        progress['gate']=gate.get('id') if isinstance(gate,dict) else None
        return hashlib.sha256(json.dumps(progress,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return "|".join(str(state.get(k, "")) for k in keys)


STALE_HOURS = 12


def stale_message(state, now=None):
    """None when `updated` is fresh; else the one line that says why the turn may end.

    An absent or unparseable `updated` counts as stale rather than fresh: it fails
    open and makes the defect visible instead of silently blocking forever. A FUTURE
    timestamp is garbage that would defeat the only time-based backstop.
    """
    try:
        ts = datetime.datetime.fromisoformat(str(state.get("updated", "")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return ("plan-continue: .claude/plan-progress.json has no parseable `updated` "
                "timestamp; letting the turn end.")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age_h = (now - ts).total_seconds() / 3600.0
    if age_h < -1.0:
        return "plan-continue: `updated` is %.1fh in the FUTURE; letting the turn end." % -age_h
    if age_h > STALE_HOURS:
        return ("plan-continue: .claude/plan-progress.json is %.1fh stale; letting the turn "
                "end rather than resuming a run that may be long dead." % age_h)
    return None


def classify(inp):
    """The decision for one turn end. Never raises; anything unexpected allows."""
    try:
        return _classify(inp)
    except Exception:
        return dict(ALLOW)


def _classify(inp):
    if not isinstance(inp, dict):
        return dict(ALLOW)
    state = inp.get("state")
    last_text = inp.get("last_text")
    if isinstance(state,dict) and state.get('state_status')=='state_error':
        return {'decision':'allow','notice':'plan-continue: state_error; diagnose the execution snapshot before mutating it.'}
    if not isinstance(state, dict) or not isinstance(last_text, str) or not last_text.strip():
        return dict(ALLOW)

    phase = str(state.get("phase", "")).strip().lower()
    if 'schema_version' not in state and phase not in ACTIVE_PHASES:
        return dict(ALLOW)

    # A caller that has not checked `updated` itself (the mod) asks for it here.
    # The line is a `notice`: shown, never counted as a forced continuation.
    if inp.get("check_updated") is True:
        notice = stale_message(state)
        if notice is not None:
            return {"decision": "allow", "notice": notice}

    if 'schema_version' in state:
        try:
            execution_state_module().validate(state)
        except Exception:
            return {'decision':'allow','notice':'plan-continue: state_error; diagnose the execution snapshot.'}
        if state['disposition'] in ('working','repairing'):
            count=_int(inp.get('count'),0)
            if count>=_int(inp.get('max'),DEFAULT_MAX):
                shown=max(-MAX_SHOWN_COUNT,min(count,MAX_SHOWN_COUNT))
                return {'decision':'allow','system_message':_bounded(
                    lambda limit:guard_message(state,shown,limit))}
            # A Stop event is a final turn boundary; commentary never reaches
            # this branch. Prose cannot revoke recorded scoped authorization.
            return {'decision':'block','reason':_bounded(lambda limit:
                'Continue authorized work for '+clean(state['plan'],'the plan',limit)+
                ' — '+_where(state,phase,limit)+'. Qualification '+
                clean(state['qualification'],limit=limit)+
                ' is separate from repair. Use plan-state.py to record a necessary dependency wait, '+
                'owner decision or measured handoff; do not ask again to continue the recorded scope.')}
        return dict(ALLOW)

    # The skill's own sanctioned ask. Checked over the WHOLE message: the block is
    # specified to come last, but a report that carries one is stopping on purpose
    # wherever it sits.
    if "ACTION NEEDED" in last_text:
        return dict(ALLOW)

    # Decided before the promise classifier, whose `next: Task N` pattern would
    # otherwise refuse a legitimate block's `next:` line.
    context_usage_path = inp.get("context_usage_path")
    bare_handoff = False
    m = RESUME.search(last_text)
    if m:
        if REASON_LINE.search(last_text[m.start():]):
            return dict(ALLOW)
        # The nudge sends the executor to run this script; with no script beside
        # the hook it cannot give that instruction, so it fails open.
        if (not isinstance(context_usage_path, str) or not context_usage_path
                or not os.path.isfile(context_usage_path)):
            return dict(ALLOW)
        bare_handoff = True
    else:
        tail = last_text[-400:]
        if not (PROMISE.search(tail) or ASK.search(tail)):
            return dict(ALLOW)
        if WAIT.search(tail):
            return dict(ALLOW)

    # No-progress guard: `count` continuations already forced at this key.
    count = _int(inp.get("count"), 0)
    limit = _int(inp.get("max"), DEFAULT_MAX)
    if count >= limit:
        # Clamped for display only: a 4000-digit JSON integer is a legal `count`.
        shown = max(-MAX_SHOWN_COUNT, min(count, MAX_SHOWN_COUNT))
        msg = _bounded(lambda n: guard_message(state, shown, n))
        return {"decision": "allow", "system_message": msg}

    if bare_handoff:
        reason = _bounded(lambda n: handoff_reason(state, phase, context_usage_path, n))
    else:
        reason = _bounded(lambda n: promise_reason(state, phase, n))
    return {"decision": "block", "reason": reason}


def inputs_main():
    """`--inputs`: {"cwd": "<dir>", "max": "<raw>"} on stdin -> the gathered inputs."""
    result = {"root": None, "state": None, "key": None, "max": DEFAULT_MAX}
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
        if len(raw) <= MAX_STDIN_BYTES:
            inp = json.loads(raw.decode("utf-8", "replace"))
            if isinstance(inp, dict):
                result["max"] = parse_max(inp.get("max"))
                cwd = inp.get("cwd")
                root = find_repo_root(cwd) if isinstance(cwd, str) and cwd else None
                if root is not None:
                    result["root"] = root
                    state = read_state(root)
                    if state is not None:
                        result["state"] = state
                        result["key"] = counter_key(state)
    except Exception:
        result = {"root": None, "state": None, "key": None, "max": DEFAULT_MAX}
    try:
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    return 0


def main():
    if sys.argv[1:] == ["--inputs"]:
        return inputs_main()
    result = dict(ALLOW)
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
        if len(raw) <= MAX_STDIN_BYTES:
            result = classify(json.loads(raw.decode("utf-8", "replace")))
    except Exception:
        result = dict(ALLOW)
    try:
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    os._exit(0)
