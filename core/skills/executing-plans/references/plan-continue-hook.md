# `plan-continue` — the optional Stop-hook backstop

**Off by default. It is enabled by one environment variable and does nothing without it.**

`../../../hooks/plan-continue.sh` runs on Claude Code's `Stop` event and refuses a turn that
ends on a promise or an approval question while a plan is in flight, returning
`{"decision":"block","reason":…}` so the run continues instead of waiting for the user.

## Why a hook, when the rule is already written

`../SKILL.md` § Run to completion says it plainly — *"stage boundaries are checkpoints, not
approval gates"*, *"never end a turn on an announcement"* — and `stage-gate.md` § If the gate
passes and `task-execution.md` restate it at both boundaries where it applies. That is
the primary control. This hook is the net under it, for the case those three restatements do not cover:
the rule is read once at session start and the failure happens hundreds of thousands of
tokens later, in a session with no compaction and no error to notice.

Measured over 39 turn ends (two sessions of one owner's master plan, 2026-08-29/30):

| Shape | Count | What it cost |
|---|---|---|
| Ended waiting on a dispatched agent or background suite | 30 | Nothing — the host re-invoked within 0.5–51 min |
| Ended on a promise or an approval question, nothing pending | 7 | Idle from 8.1 min to over 8 h per stop |
| Ended otherwise | 2 | Fits neither of those two shapes |

Knowing the rule does not prevent the failure: it fires at a boundary long after the rule
was read.

## Structured state and host event boundaries

For owned v2 runs, the shared execution-state contract supplies the decision:
working/repairing continues recorded authority; external waits, owner decisions,
measured handoff and completion allow actual Stop. Qualification is separate.
Legacy message classification is retained only for unowned legacy state.
Commentary does not itself establish a turn boundary on every host. Each host layer
adapts its actual Stop envelope and keeps that host's trust/opt-in boundaries.

## When the legacy classifier blocks

All four must hold:

1. `PLAN_CONTINUE=1` in the environment.
2. `<repo-root>/.claude/plan-progress.json` exists, is owned by you, and its `phase` is
   `preflight`, `task` or `gate` — an allow-list, so a phase added to the contract later
   fails open. `closeout`, `blocked` and `handoff` are excluded. An owned v2 run is
   finished by `plan-state.py finish`, which keeps the snapshot as terminal evidence
   (`disposition: complete`) rather than deleting it; only unowned legacy state is
   deleted at close-out.
3. `updated` is parseable, not in the future, and under 12 h old.
4. The last main-thread assistant message matches a **promise** (*"Next: Task 2.4"*,
   *"starting now with Task 2.1"*, *"I'll start…"*) or an **approval question** (*"say the
   word"*, *"ready to start Stage 2"*, *"want me to carry on"*), and matches **neither** a
   wait marker (*"waiting on"*, *"once it reports"*, *"still running"*, *"blocked on"*) nor
   an `ACTION NEEDED` block — **or** it carries a `RESUME HERE` block with no `reason:` line
   (below).

Against the 39 measured turn ends: 7/7 bad stops caught, 0 of the 30 legitimate waits
blocked. One of the other two turn ends, announcing that the gate would be re-run and the
next stage started, was blocked too: it is an announcement ending whether or not the host
re-invokes soon after, and blocking it is the intended reading rather than a miss.

## Legacy forms for stopping on purpose

All three exist in this skill's contract; the hook reads them rather than inventing a
fourth:

- Write an **`ACTION NEEDED:`** block naming the decision that blocks the next stage
  (`stage-gate.md` § ACTION NEEDED — the one place a report asks the user for something).
- Write **`phase: "blocked"`** to the progress state file when a documented Stop condition
  fires (`progress-state-file.md`).
- Hand off on **`context-usage.py`'s `handoff` verdict**: a `RESUME HERE` block carrying the
  script's `reason:` line and the `handoff_id:` line, and `phase: "handoff"`
  (`session-handoff.md` § On `handoff`). A `RESUME HERE`
  with no `reason:` line is the eyeball stop that rule forbids: the hook blocks it and names
  the script to run — and fails open when that script is not installed beside the hook,
  since it cannot send the executor after a file that is not there. A legitimate block is
  allowed even though its `next: Task N` line reads like a promise.

Saying what you are waiting on also ends the turn cleanly — that is what the wait marker is.

## Enabling it

The hook ships with the plugin and is wired to `Stop` by `../../../hooks/hooks.json`, so
there is nothing to install; it exits immediately unless opted in. Enable it per project in
`.claude/settings.json`:

```json
{ "env": { "PLAN_CONTINUE": "1" } }
```

`PLAN_CONTINUE_MAX` (default 3) bounds how many times it may force a continuation while
the execution key does not move (legacy phase|stage|task; v2 meaningful task/gate/round/check/content movement); past that it lets the turn end so you can look. Unset
`PLAN_CONTINUE` or set it to `0` to switch it off.

## On Claude Code 2.1.288+, the planning mod answers first

The plugin's hooks module (`../../../hooks/mod/stop.ts`; the hook gathers, the script decides) runs the same check on
`classic.Stop`, under the same opt-in (`PLAN_CONTINUE`, read with `$.env`). It decides
nothing itself:

- It takes the last assistant message from the event (`last_assistant_message`) instead of
  tailing the transcript.
- One `plan_continue_classify.py --inputs` run gathers everything else: the repo root, the
  state file through the module's hardened reader (by directory fd, `O_NOFOLLOW`, FIFO-safe,
  owner, size cap), the shared execution counter key, and
  `PLAN_CONTINUE_MAX` parsed by `parse_max()` — the same function the command hook uses.
- A second run of the same module classifies. The no-progress count lives in `$.state`
  (`planning.stopCounter`), keyed by root and that execution key, so a hot reload keeps it.

**Who decides.** When the module answered, the mod passes the event on marked
`planning_mod_handled: true`; the user's own Stop hooks still run, and
`../../../hooks/plan-continue.sh` sees the mark and exits 0 without deciding twice. A user
hook's block wins over the mod's and is not counted. When the module did not answer — an
empty or missing last message, a run that was refused, timed out, exited non-zero or printed
garbage — the event passes on **unmarked** and the command hook decides from the
transcript. The `Stop` entry stays in `hooks.json` for builds without mods.

**Counter loss allows.** If the count cannot be stored, there is no loop guard, so the mod
lets the turn end and logs why rather than block without one — the command hook does the
same when its counter file cannot be written.

**The stage note.** At each new `(plan, stage)` in `preflight`, `task` or `gate`, the mod
appends one user-role note (at most 600 characters, every state field cleaned and quoted)
restating the three run-to-completion rules. It is sent once per `(plan, stage)` per session
and never goes into the system prompt.

## It fails open, always

No state file, unreadable or unparseable transcript, garbage timestamp, stale state, a
symlinked or FIFO state file, a world-writable repo root, no progress — every one of these
allows the stop. A Stop hook that fails closed traps a session in a loop the user cannot
exit, which is strictly worse than the problem it solves. Every exit is 0, enforced by the
script rather than borrowed from the host's treatment of odd exit codes.

The reason text is built only from clamped state-file fields (newlines flattened, 200 chars
each). Transcript text is read to make a yes/no decision and never quoted back — a repo can
commit `.claude/plan-progress.json`, so a cloned repo's state file is user-owned and still
untrusted.

Tests: `../tests/test-plan-continue.sh` (39 cases, decision-asserting),
`../../../hooks/tests/test-plan-continue-classify.py` (the shared module), and the mod's
`../../../hooks/mod/stop.test.ts` and `stage-note.test.ts` (`claude plugin test planning`).
