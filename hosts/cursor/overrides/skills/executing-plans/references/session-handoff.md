# Session handoff — a measured stop, never an eyeball call

The executor decides when a plan continues in a fresh session, and it decides by
measurement. Without one, a mid-plan stop waits for the user to notice a full context —
measured over five executions (one owner's plans, undated), the executor proposed a handoff
zero times — and advice to reset on large plans, with nothing to measure against, is never
taken on purpose. Every executing-plans file that mentions a fresh session cites this one,
`session-handoff.md`, as the rule that decides it.

## The measurement — absent on Cursor

On Claude Code, `context-usage.py` reads the session's own transcript and reports the exact
context in use against the model's window, plus the context each `Stage N green` commit in
the session cost; the stop rules below decide from those numbers. **That script does not ship
on Cursor:** no store Cursor writes records the context a session uses, so it could only ever
print `unknown`. What follows on Cursor:

- **Every measured verdict is `unknown`.** Rules 2–4 below need a context figure, so on Cursor
  they never fire, and `unknown` never stops (§ The bounds).
- **Rule 1, the owner's request, is not carried.** It is read through a supervisor's
  envelopes (`handoff-envelope.py`), and supervised handoff does not ship on Cursor.
- **Rule 5, a dated external wait, is the only handoff.** Its `reason:` is the dated check,
  quoted; it needs no measurement.
- **There is no per-stage cost and no compaction count.** The context rule's second clause and
  the re-grounding trigger have no input here.

**When.** The rules are evaluated once per stage gate and once per sub-plan gate, **after**
the gate commit. On Cursor that evaluation is the dated-wait check alone: is any gate check
written `- [~]` against a named future date? The user can still ask to stop at any time, as
on any host; that is the user's call, not a rule firing.

## The five stop rules

Evaluated in this order on hosts that measure. On Cursor only rule 5 can fire.

1. **Owner request** (`rule requested`): handoff when the owner's rollover request through
   a supervisor names this session. Not carried on Cursor.
2. **Sub-plan boundary** (master plans): handoff, unless the context is under 25% of the
   window. Needs a measurement, so it never fires on Cursor: a master plan's sub-plans
   continue in one session (`master-plans.md`).
3. **Context**: handoff when `now > 50` percent of the window, or when now plus
   `last_stage_cost` would pass 50%. Needs a measurement; never fires on Cursor.
4. **Dead weight**: handoff when the next stage's `Scope:` / `Test:` paths are `disjoint`
   from every stage finished in this session **and** the context is above 25%. Needs a
   measurement; never fires on Cursor.
5. **Dated external wait**: a gate check that cannot run before a named future date (a
   release, a store review, a device delivery) is written `- [~]` with the date, and the run
   hands off naming it. This rule's `reason:` is the dated check, quoted.

**Re-grounding after a summary — not a stop.** When the session has been summarized (on
Cursor nothing counts this, so watch for a summary in place of earlier turns), re-read the
plan's `Status:` flips and handoff notes before the next tool call. A summary is not a
source for task state.

## The bounds

Stated with the rules, not after them: every dispatch rule states its bound in the same
breath, because a rule without one gets over-corrected into its inverse. A stop
rule has the same failure shape, so the same discipline applies here.

- **`unknown` never stops.** On Cursor every measured verdict is `unknown`; the gate report
  says so, and execution continues.
- **No rule applies before a gate.** A handoff happens at a stage or sub-plan gate, after its
  commit — never mid-stage and never mid-task.
- **A stop without a rule's `reason:` line is not a legal stop.** "Context feels large"
  is the eyeball call this rule replaces. On Cursor the only such line is rule 5's dated
  check. The `stop` hook (`plan-continue-hook.md`) reads no text on Cursor: it lets a turn
  end on the state file's `phase: "handoff"`, and a `RESUME HERE` block alone, even one
  carrying a `reason:` line, does not end the run.

## On `continue`

Write `context: unknown — not measured on Cursor` into the handoff note as its `context:`
line, and issue the next stage's first tool call in the same turn (`stage-gate.md` § If the
gate passes). The gate report is already committed by then, so the line goes in the plan,
not the report, and rides the next commit that carries the plan (a plan outside the repo
rides none).

## On `handoff`

On Cursor a handoff is rule 5's dated wait. `<repo root>` below is the git top level
(`git rev-parse --show-toplevel`). The handoff id, the envelopes and the supervisor steps
that other hosts add are not carried on Cursor: `handoff-envelope.py` does not ship, and
nothing would read them. The steps below are the whole handoff here.

1. Append a `RESUME HERE` block under the stage's handoff note, its heading in column 0:

   ```
   **RESUME HERE (<YYYY-MM-DD>):**
   reason: rule 5: <the dated gate check, quoted>
   plan: <absolute plan path>   cwd: <repo root>   branch: <branch>
   next: Task <N.M> — <title>
   `dispatch: …`  `review: …`  `residuals: …`   (the gate report's lines, verbatim)
   **Decisions in force:** <IDs>
   ```

   Before writing it, list the background jobs and agents this run started, by the id each
   launch result carried, stop each whose result was used (on Cursor there is no tool that
   stops a background task by id: stop a background job you started through the shell, its
   whole process tree), and name each one still running in the block's `running:` line. Then
   run `python3 <planning-plugin>/skills/executing-plans/scripts/review-ledger-check.py --unstopped --repo <repo root>`.
   **On Cursor its exit 0 is not evidence:** Cursor fires no subagent start or stop event
   (Cursor probe, 2026-10-24), so the dispatch log holds no start lines and the check finds no
   agent left running by construction. The ids noted at launch are the record; with none,
   `running: none`; with no log (exit 3), `running: NOT RUN` beside the ids noted at launch.
   The successor must know what is still working before it starts anything of its own.
2. Commit it as its own `"Stage N handoff"` commit, whose body carries the same `reason:`
   line — the gate commit is already made. When the plan lives outside the repo, write the
   block at the plan's absolute path and make the same commit empty (`--allow-empty`), so the
   repo records why the run stopped.
3. Run `plan-state.py set-blocker` with disposition handoff, the prevented next operation,
   the dated check as the evidence, fresh-session dependency, remaining work and the
   verbatim reason. The writer projects `phase: "handoff"`. Unowned legacy display files
   carry `phase: "handoff"` and `reason` directly (`progress-state-file.md`). **On Cursor
   this step is what ends the run:** the `stop` hook lets the turn end on that phase.
4. End the turn with the reason and one line telling the user to resume in a fresh session
   pointed at the plan path. That line is not an `ACTION NEEDED:` block — nothing is being
   decided.

**From step 3 on, the session owns nothing.** Its only remaining action is step 4's last
line. It starts no task or gate, flips no `Status:`, and edits no decision. The plan now
belongs to whoever resumes it, and two concurrent sessions writing one plan would race.

**Resuming.** The new session reads the plan in full, finds the last `RESUME HERE` block, and
starts at the task it names; the Research Summary, `Status:` flips and handoff notes carry
everything else. A block too thin to resume from is the bug to fix. Close-out writes no
`RESUME HERE` — there is no next task.

## Adopting a handoff — not carried on Cursor

On other hosts a session a supervisor starts proves which handoff it holds, through the
envelope script's `plan`, `verify`, `fail` and `accept` steps, before it owns the plan. That
supervised handoff does not ship on Cursor: the script is absent and no supervisor starts a
Cursor session. A Cursor session resumes by **Resuming**, above.
