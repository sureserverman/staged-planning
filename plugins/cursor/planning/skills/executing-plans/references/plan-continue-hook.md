# `plan-continue` — the `stop`-hook backstop

**On once the plugin is installed, in an interactive session.** `../../../hooks/plan-continue.sh`
is wired to Cursor's `stop` event by the plugin's own `../../../hooks/hooks.json`, with
`loop_limit: 25`. The installer writes no `~/.cursor/hooks.json` entry for it: an event wired
on both routes runs twice. While a plan is in flight the hook answers with a
`followup_message`, which Cursor submits as the next user message, so the run continues
instead of waiting for the user.

**It fires only in an interactive session.** Cursor runs `stop` hooks in the interactive
agent; a headless `cursor-agent -p` run was not seen to run one (Cursor probe, 2026-10-24).
A headless run gets no backstop and relies on the skill's rules alone.

## Why a hook, when the rule is already written

`../SKILL.md` § Run to completion says it plainly — *"stage boundaries are checkpoints, not
approval gates"*, *"never end a turn on an announcement"* — and `stage-gate.md` § If the gate
passes and `task-execution.md` restate it at both boundaries where it applies. That is
the primary control. This hook is the net under it: the rule is read once at session start
and the failure happens hundreds of thousands of tokens later, in a session with no error to
notice. Knowing the rule does not prevent the failure.

## Why it continues on every turn end on Cursor

On Cursor an assistant message with no tool call ends the turn, and the run waits for the
user. A subagent's result comes back inside the turn that dispatched it, so no turn on
Cursor legitimately ends *waiting* on a dispatched agent. A turn that ends while a plan is
in flight is a stop the user has to undo by typing "carry on".

So this hook has **no classifier** over the last message: any completed turn while a plan is
in flight is continued. Claude Code's version classifies the last assistant message (a
promise or an approval question blocks; a wait marker or `ACTION NEEDED` allows), because
there a turn that ends waiting on a background agent is correct — the host re-invokes when
the agent reports. That policy would miss the stops that matter here. Same in-flight
signal, same hardening, a different policy for a host fact.

## Structured state

For owned v2 runs, the shared execution-state contract supplies the decision:
working/repairing continues recorded authority; external waits, owner decisions,
a recorded handoff (on Cursor, a dated wait) and completion allow the stop. For unowned legacy state, the phase
allow-list below decides.

## When it continues

All of these must hold:

1. The payload's `status` is `completed`. An aborted or errored turn is never resumed:
   resuming a run the user aborted would fight the user with an auto-submitted prompt.
2. `<workspace root>/.claude/plan-progress.json` exists, is owned by you, and its `phase` is
   `preflight`, `task` or `gate` — an allow-list, so a phase added to the contract later
   fails open. `blocked` and `handoff` let the stop through. `closeout`, `stage-complete` and
   any other phase outside the list let it through too, unless the stage they name is claimed
   done with no `Stage N green` commit in HEAD's history (`progress-state-file.md`); then the
   run continues until that gate is recorded.
3. `updated` is parseable, not in the future, and under 12 h old.
4. The execution key (legacy `phase|stage|task`; v2 task, gate, round, check or content
   movement) has moved since the last continuation, or the no-progress bound is not yet
   spent. Cursor also bounds follow-ups itself through the `loop_limit` in `hooks.json`.

## Stopping on purpose on Cursor

The hook reads no text, so a stop on purpose is a state-file write:

- Write an **`ACTION NEEDED:`** block naming the decision that blocks the next stage
  (`stage-gate.md` § ACTION NEEDED) **and** set `phase: "blocked"`. On Cursor the block
  alone does not end the turn, because nothing reads it.
- Write **`phase: "blocked"`** to the progress state file when a documented Stop condition
  fires (`progress-state-file.md`).
- Hand off by writing **`phase: "handoff"`** at a gate (`session-handoff.md` § On `handoff`).
  On Cursor nothing measures the context, so only a dated wait hands off. A `RESUME HERE`
  block, even one carrying a `reason:` line, does not release the hook; only the phase does.

## Checking the wiring

The Cursor-only `hooks` skill (`/hooks`) reports which of this plugin's hooks are wired and
on which route. Every hook is on the plugin route; nothing is installed into
`~/.cursor/hooks.json`.

**With the Claude Code planning plugin also installed,** Cursor runs that plugin's hooks too,
its Stop hook among them. Each of them exits quietly when the payload carries
`cursor_version`, so only this plugin's `stop` hook answers under Cursor.

## It fails open, always

No state file, no workspace root in the payload, unparseable JSON, a garbage timestamp,
stale state, a symlinked or FIFO state file, a world-writable repo root, no progress — every
one of these allows the stop. A stop hook that fails closed traps a session in a loop the
user cannot exit, which is strictly worse than the problem it solves. Every exit is 0,
enforced by the script rather than borrowed from the host's treatment of odd exit codes.

The follow-up text is built only from clamped state-file fields (newlines flattened, 200
chars each). A repo can commit `.claude/plan-progress.json`, so a cloned repo's state file
is user-owned and still untrusted.

The hook's tests run from the source repository; they do not ship in the plugin.
