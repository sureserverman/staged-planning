# Session handoff — a measured stop, never an eyeball call

The executor decides when a plan continues in a fresh session, and it decides by
measurement. Without one, a mid-plan stop waits for the user to notice a full context —
measured over five executions (one owner's plans, undated), the executor proposed a handoff
zero times — and advice to reset on large plans, with nothing to measure against, is never
taken on purpose. Every executing-plans file that mentions a fresh session cites this one,
`session-handoff.md`, as the rule that decides it.

## The measurement

`../scripts/context-usage.py` is the OpenCode build of this script. OpenCode keeps no
transcript file: it records every model call's token accounting in its own session store
(the SQLite `opencode.db` under OpenCode's data directory, opened read-only). The script
reports the exact context in use — the last assistant message's `input + cache read + cache
write` tokens, not a guess; a message that recorded no usage (an errored or unfinished call)
is skipped — against the context limit OpenCode's models cache (`models.json` under its cache
directory) lists for that message's provider and model, plus the context each `Stage N green`
commit in this session cost:

```
python3 <planning-plugin>/skills/executing-plans/scripts/context-usage.py \
  --plan <plan path> --next-stage <N+1> [--sub-plan-boundary]
```

**Which session.** `--session <id>` if given, else the newest top-level session whose
directory is the one the script runs from — the repo root, where this rule runs it. OpenCode
puts no session id in the shell environment, so two sessions open in one directory can
measure the wrong one; the script names the session it read in `reason:`, and a reader who
sees the wrong one re-runs it with `--session`.

**The window.** `--window N` wins. Otherwise the models cache decides, and a model it does not
list is `unknown`. There is no live-window sidecar on OpenCode: only the Claude Code planning
mod writes one.

**When.** Once per stage gate and once per sub-plan gate, **after** the gate commit, **in a
separate `bash` tool call**. A call still running is not a completed part of the session, so
a `context-usage.py` chained onto the `Stage N green` commit does not see that commit and
reports the previous stage's cost. At a master plan's sub-plan close-out, add
`--sub-plan-boundary`.

**What it reads for per-stage cost.** A stage boundary is a completed `bash` tool call whose
command ran a real `git commit` whose *subject* is `Stage N green` — a call still running, or
one that errored, is not one. A compaction (an assistant message marked as a summary) resets
the baseline, so no cost spans one. `last_stage_cost` is the most recent stage's cost.

## The four stop rules

Evaluated in this order. Rules 1–3 are the script's, and it names the rule that fired and its numbers in `reason:`; rule 4, the dated wait, is the executor's.
The core's first rule, an owner's rollover request through a supervisor (`rule requested`), is not carried on
OpenCode: no supervisor rolls an OpenCode session over, and the handoff envelope it reads
does not ship.

1. **Sub-plan boundary** (master plans, `--sub-plan-boundary`): handoff, unless the context is
   under 25% of the window. A sub-plan boundary is the natural reset point; below 25% the fresh
   session buys too little to be worth the resume.
2. **Context**: handoff when `now > 50` percent of the window, or when now plus
   `last_stage_cost` would pass 50%. Exactly 50% continues. **The first stage of a session
   always runs** — with no `Stage N green` commit in this session there is no cost history,
   and the verdict is `continue` whatever the percentage.
3. **Dead weight**: handoff when the next stage's `Scope:` / `Test:` paths are `disjoint`
   from every stage finished in this session **and** the context is above 25%. Nothing the
   session holds helps the next stage, so it pays for context it does not use. A stage with
   no `Scope:` field makes `disjoint` `unknown`, and `unknown` is never a stop.
4. **Dated external wait**: a gate check that cannot run before a named future date (a
   release, a store review, a device delivery) is written `- [~]` with the date, and the run
   hands off naming it. This rule's `reason:` is the dated check, quoted; paste the
   `context-usage.py` line beside it.

**Post-compaction re-grounding — not a stop.** When the session has compacted (the script's
`compactions` count rose), re-read the plan's `Status:` flips and handoff notes before the
next tool call. A compaction summary is not a source for task state.

## The bounds

Stated with the rules, not after them: every dispatch rule states its bound in the same
breath, because a rule without one gets over-corrected into its inverse. A stop
rule has the same failure shape, so the same discipline applies here.

- **`unknown` never stops.** A missing store, an unlisted model, a stage without
  `Scope:` — the script says `unknown`, the gate report says so, and execution continues.
- **No rule applies before a gate.** A handoff happens at a stage or sub-plan gate, after its
  commit — never mid-stage and never mid-task.
- **A stop without the script's `reason:` line is not a legal stop.** "Context feels large"
  is the eyeball call this rule replaces. On OpenCode this rule is the only enforcement:
  the measurement reads OpenCode's own store and models cache, and no Stop hook runs that
  could catch a `RESUME HERE` block lacking a `reason:` line (`plan-continue-hook.md`).

## On `continue`

Paste the verdict line verbatim into the handoff note as its `context:` line, and issue the
next stage's first tool call in the same turn (`stage-gate.md` § If the gate passes). The
gate report is already committed by then — the script runs after that commit — so the line
goes in the plan, not the report, and rides the next commit that carries the plan (a
plan outside the repo rides none).

## On `handoff`

`<repo root>` below is the git top level (`git rev-parse --show-toplevel`). OpenCode carries no
supervised handoff: this package ships no handoff envelope, so there is no handoff id to mint
and no `ready` envelope to write. The `RESUME HERE` block and the plan are the whole handoff.

1. Append a `RESUME HERE` block under the stage's handoff note, its heading in column 0:

   ```
   **RESUME HERE (<YYYY-MM-DD>):**
   reason: <the script's reason: line, verbatim>
   plan: <absolute plan path>   cwd: <repo root>   branch: <branch>
   next: Task <N.M> — <title>
   `dispatch: …`  `review: …`  `residuals: …`   (the gate report's lines, verbatim)
   **Decisions in force:** <IDs>
   ```

   Before writing it, list the background jobs and agents this run started, stop each whose
   result was used (on OpenCode by `kill` of its pid or process group —
   `task-execution.md` § Waiting on background work), and name each one still running in the
   block's `running:` line. Then run
   `python3 <planning-plugin>/skills/executing-plans/scripts/review-ledger-check.py --unstopped --repo <repo root>`
   and add to that line each agent it lists (exit 1) by id and type; with nothing from
   either, `running: none`; with no log (exit 3), `running: NOT RUN` beside the ids
   noted at launch. The successor must know what is still working before it starts anything
   of its own.
2. Commit it as its own `"Stage N handoff"` commit, whose body carries the same `reason:`
   line — the gate commit is already made, since the script runs after it. When the plan
   lives outside the repo, write the block at the plan's absolute path and make the same
   commit empty (`--allow-empty`), so the repo records why the run stopped.
3. Run `plan-state.py set-blocker` with disposition handoff, the prevented next operation,
   original measurement evidence, fresh-session dependency, remaining work and the script's
   verbatim reason. The writer projects `phase: "handoff"`. This records the stop for the
   next reader; on OpenCode it does not hold the session.
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
