# `plan-continue` — the Stop-hook backstop, and why OpenCode has none

**On OpenCode there is no auto-continue at Stop.** OpenCode has no Stop hook that can hold
or resume a turn, so this package ships no `plan-continue` hook and nothing continues a run
for you. When a turn ends, the run waits for the user, however much of the plan is left.

On a host that has one, the hook runs on the Stop event and refuses a turn that ends on a
promise or an approval question while a plan is in flight, so the run continues instead of
waiting. Here that net does not exist, and the written rule is the whole control.

## Why the rule matters more without the hook

`../SKILL.md` § Run to completion says it plainly — *"stage boundaries are checkpoints, not
approval gates"*, *"never end a turn on an announcement"* — and `stage-gate.md` § If the gate
passes and `task-execution.md` restate it at both boundaries where it applies. Elsewhere a
hook is the net under that rule, for the case the restatements do not cover: the rule is read
once at session start and the failure happens hundreds of thousands of tokens later, in a
session with no compaction and no error to notice.

Measured over 39 turn ends on a host with the hook (two sessions of one owner's master plan,
2026-08-29/30):

| Shape | Count | What it cost |
|---|---|---|
| Ended waiting on a dispatched agent or background suite | 30 | Nothing — the host re-invoked within 0.5–51 min |
| Ended on a promise or an approval question, nothing pending | 7 | Idle from 8.1 min to over 8 h per stop |
| Ended otherwise | 2 | Fits neither of those two shapes |

Knowing the rule does not prevent the failure: it fires at a boundary long after the rule
was read. On OpenCode every one of those seven stops would stand. **Do the next piece of
work in the same turn**, and end a turn only in one of the three ways § Three ways to stop on purpose names.

## Three ways to stop on purpose

These are the skill's contract on every host. On OpenCode no hook reads them; they are how a
run ends on purpose and how the next reader learns why.

- Write an **`ACTION NEEDED:`** block naming the decision that blocks the next stage
  (`stage-gate.md` § ACTION NEEDED — the one place a report asks the user for something).
- Record a documented Stop condition with **`plan-state.py set-blocker`**
  (`progress-state-file.md`).
- Hand off on **`context-usage.py`'s `handoff` verdict**: a `RESUME HERE` block carrying the
  script's `reason:` line, and the handoff recorded in the state
  (`session-handoff.md` § On `handoff`). There is no handoff id on OpenCode: the supervised
  handoff envelope is not shipped.

Saying what you are waiting on also ends the turn cleanly — but on OpenCode nothing comes
back on its own, so say it only when the wait is the user's.

## What a state write buys here, and what it does not

The state file keeps its contract (`progress-state-file.md`): a recorded blocker, a spent
budget, a close-out and a handoff still mean what they mean. **A state write records a stop;
it does not enforce one.** It cannot hold the session past a report, and it cannot resume a
session that ended early. What it buys is the record: the next session, or the user coming
back, reads where the run stands rather than a `task` or `gate` phase that looks mid-flight.

Two rules therefore have no mechanical check on OpenCode and are enforced only by the
executor:

- **A `RESUME HERE` block with no `reason:` line is the eyeball stop** the context rule
  forbids. Nothing blocks it here; `session-handoff.md`'s rule — no stop without
  `context-usage.py`'s `reason:` line — is its only enforcement.
- **A spent remediation budget stops the run** (`gate-failure-procedure.md` § The read-only
  budget projection). Nothing holds the session at the escalation; the escalation is the
  turn's last act.

## Not shipped here

The `plan-continue.sh` command hook, its `PLAN_CONTINUE` / `PLAN_CONTINUE_MAX` opt-in, and the
Claude Code planning mod that answers the Stop event first are Claude Code's and do not ship
in this package. The shared classifier `../../../hooks/plan_continue_classify.py` does ship,
because the dispatch logger reads the state through it.
