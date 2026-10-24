# `plan-continue` — the Stop-hook backstop on Codex

`../../../hooks/plan-continue.sh` is this plugin's Codex `Stop` hook. While a plan is in
flight it refuses the turn's end by returning `{"decision":"block","reason":…}`: Codex then
continues, and uses the reason as the text of a new prompt. So a run that drifted into
ending its turn is handed back to itself instead of waiting for the user.

**It runs only after the user trusts it.** Codex starts every plugin hook untrusted and skips
it silently until the user trusts it in `/hooks`, and again after any change to the hook's
command. This plugin never writes that trust and never bypasses it. Until it is trusted,
nothing on this host continues a run: `../SKILL.md` § Run to completion is the whole
control.

## Why a hook, when the rule is already written

`../SKILL.md` § Run to completion says it plainly — *"stage boundaries are checkpoints, not
approval gates"*, *"never end a turn on an announcement"* — and `stage-gate.md` § If the gate
passes and `task-execution.md` restate it at both boundaries where it applies. That is the
primary control. This hook is the net under it: the rule is read once at session start and
the failure happens hundreds of thousands of tokens later, in a session with no compaction
and no error to notice. On Codex the failure has one common shape: the executor ends a turn
on a progress note it meant as commentary, and the run then waits for a user who typed
nothing. A commentary update inside a turn does not end it; the turn's final message does.

## How the Codex hook decides

The Codex fork reads the execution state, not a transcript. It loads core's classifier,
`plan_continue_classify.py`, from beside it in `hooks/`, and its lock entry carries the
classifier's digest, so a core change to the classifier fails the build until the fork is
reread against it.

- It continues the run while `<repo-root>/.claude/plan-progress.json` reads an in-flight
  phase — `preflight`, `task` or `gate` — an allow-list, so a phase added later fails open.
  For an owned run it reads the state through the execution-state contract's dispositions
  (`execution-state-contract.md`): working and repairing continue; an external wait, an
  owner decision, a measured handoff and completion allow the stop.
- On a legacy state file (no `schema_version`) it allows the stop on `blocked`, `closeout`
  and `handoff`. On any state it allows the stop on state older than 12 h or with an
  unparseable `updated`, and once it has continued too many times while the run's
  position did not move. The hook's own header names its switch and its limits.
- On a legacy state file it reads the Stop payload's last assistant message for one thing
  only: a `RESUME HERE` block (an owned run's message is never read). One carrying `context-usage.py`'s `reason:` line is a measured handoff and is
  allowed. One without it is the eyeball stop `session-handoff.md` forbids: the hook
  continues the run and names the script to run.

## Three ways to stop on purpose

All three are in this skill's contract; the hook reads them rather than inventing a fourth:

- Record a documented Stop condition with `plan-state.py set-blocker` **before** the report
  that names it, so the state reads `blocked` when the turn ends (`stage-gate.md` § ACTION
  NEEDED). An `ACTION NEEDED:` block alone is not read by the hook: written under an
  in-flight phase, it gets a continuation prompt instead of the user's answer.
- At close-out, record the merge choice with `set-blocker` (an owner decision) or run
  `finish` before the report that offers the merge (`close-out.md`). Phase `closeout` alone
  ends the turn only on a legacy state file.
- Hand off on **`context-usage.py`'s `handoff` verdict**: a `RESUME HERE` block carrying the
  script's `reason:` line and the `handoff_id:` line, recorded with `set-blocker`
  (disposition `handoff`; `session-handoff.md` § On `handoff`).

Saying what you are waiting on is not a fourth way here: the Codex hook reads no wait
marker. Wait inside the turn instead — `wait_agent` for a spawned agent, `wait <pid>` or a
sentinel file for a background job (`task-execution.md` § Waiting on background work).

## Switching it on

The hook does nothing unless the Codex session was started with `CODEX_PLAN_CONTINUE=1` in
its environment, and the user trusts it in `/hooks`. Start the session that executes a plan
that way; any other session in the same repo is left alone. Unset, or untrusted, it is off.

## It fails open, always

No state file, unparseable JSON, a garbage timestamp, stale state, a state file not owned by
you, no progress — every one of these allows the stop. A Stop hook that fails closed traps a
session in a loop the user cannot exit, which is strictly worse than the problem it solves.

The reason text is built only from clamped state-file fields. A repo can commit
`.claude/plan-progress.json`, so a cloned repo's state file is untrusted, and Codex feeds the
reason back as a prompt: nothing from it reaches that prompt unclamped.
