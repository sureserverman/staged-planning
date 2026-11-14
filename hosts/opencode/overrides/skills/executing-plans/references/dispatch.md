# Dispatch — running a plan's `Dispatch: YES` tasks

The procedure `../SKILL.md` § Step 3.2 — Split by parallelism runs for every ready
`Dispatch: YES` task: select, guard, brief, dispatch, collect, integrate. Which subagent
type and stack skill a task gets is `stack-routing.md`'s to say.

> On OpenCode, `<planning-plugin>` is this package's folder: the folder that holds `skills/`. In a shell command use its absolute path, quoted.

## Preconditions

Refuse to dispatch unless all are true:

1. **A plan exists** at a known path, produced by `planning-projects`. Its task fields (`Depends on`, `Blocks`, `Dispatch`, `Test`, `Red-Green max cycles`) are the source of truth. Older plans spell the field `Parallel:`; treat it identically.
2. **Every task in scope has `Dispatch: YES`** in the plan.
3. **Every task's `Depends on` list is fully green** (every referenced task has passed its test and been committed).
4. **No two tasks in scope modify the same file**, checked against the plan's declared file paths; if the plan lists none, scan the task descriptions. When in doubt, force sequential.
5. **The stage gate has not yet run.** Dispatches happen before the gate, not after.

If any precondition fails, stop and report which one — do not relax them on your own.

**These five preconditions are the whole check.** Satisfying them means dispatch — not a
pause to confirm with the user first. A plan's `Dispatch: YES` is a direct order, approved
when the plan was approved. The only legitimate halts are a precondition that genuinely
fails, or dispatch
that is mechanically unavailable or disallowed in this session — a Stop condition
(`../SKILL.md` § Stop conditions), reported as such rather than resolved by quietly
inlining the work. "I wasn't sure whether to fan out" is not one.

## Select

From the current stage, take the tasks with `Dispatch: YES` whose every `Depends on` is
green and that have not already been dispatched or completed. Call this set **S**. A lone
ready task is **still dispatched**: |S| = 1 runs as a single dispatch, never inline.
Having nothing to run alongside it is a fact about *concurrency*, while `Dispatch: YES` is
a *delegation* directive (`../../planning-projects/SKILL.md` § Stage structure). Only
|S| = 0 leaves nothing to do.

On OpenCode a single dispatch needs no special shape: `stack-routing.md` names an agent for
every row, and its fallback (OpenCode's built-in `general`) is always there. Only the
concurrency disappears.

## Guard against file conflicts

For every pair in S, compare the file paths each task will modify. If the paths overlap,
remove one from S (keep the task with the higher `Blocks` count, since it unblocks more).
The removed task is **dispatched on its own after this batch returns**: the conflict
decided *when*, not *whether*.

Guard **shared resources** the same way: the same schema migration, the same CI config
section, the same feature flag are conflicts even when the literal paths differ. Log which
task was deferred and why.

## Brief each agent

A sub-agent sees only its prompt: an OpenCode subagent starts in a fresh session with its
own `AGENTS.md` load, and nothing in that startup path reaches the plan file. Build one per task in S from this template:

```
You are a sub-agent executing Task <N.M> from plan <plan-path>.

## What this is for
Stage goal: <the stage's **Goal:** line, verbatim>
<The Research Summary lines that promise something this task delivers or that its
user will hit — Scope, deferred items, "until X the app …" — verbatim.>
Who uses this task's result: <the user, another app, a later task, a worker> — and
what they see when it works and when it cannot.

## Task
<Task description from plan, verbatim>

## Files
<Files from plan, verbatim — Create / Modify / Test paths>

## Context (only what this task needs)
<Extract from Research Summary the 2-4 bullets that bear on this task.
Do NOT paste the entire research summary.>

## Decisions in force
<From the plan's `## Decisions in force`, ONLY the entries bearing on this task —
same discipline as Context above, not the whole section. One line each:
"DEC-NNN (accepted) — <the constraint, in the entry's own words>".
If the task line carries `Honors DEC-NNN`, that entry MUST appear here.
If it carries `Supersedes DEC-NNN`, say so and state what replaces it.
Omit the heading entirely when no decision bears on this task.>

## Stack skill — invoke first (omit if the routing table names none)
<The installed stack skill stack-routing.md matched, by name — load it before editing>

## Execution model (Red-Green loop — test first)
1. Write the test FIRST, before touching the implementation. If the Test command below
   names a `-k` expression or a test id, name your test so that expression collects it —
   the selector is a naming constraint, not something to rename to afterwards
2. Run the Test and confirm it goes RED **for the reason this task names** (the behavior
   is missing). A RED for any other reason means YOUR TEST is wrong, not the code: fix
   the test and re-run. Those repairs do not count against the cycle budget in step 5
3. Implement the behavior "What this is for" describes: the success path and every way
   it can fail, each ending in something its user sees. The Test checks one path. It
   is the minimum evidence, not the spec, and green is not the signal to stop. Write
   what a senior engineer on this stack would ship, not the least code that passes
4. Run the Test again:
   <Test command, verbatim from plan>
   Expected: <expected pass criterion>
5. If RED: diagnose the actual error, form a hypothesis, make ONE targeted fix, retest.
   Max <Red-Green max cycles> RED cycles. If exceeded, STOP and report — do not keep looping
6. Run NOTHING WIDER than the Test above. No full suite, no regression sweep across other
   test trees, no "check I broke nothing else" — the main session runs that once at the
   stage gate. Running a whole test file instead of one filter is fine
7. When the task carries `Proof: required` (its plan entry has the field): Stage your work,
   then prove it (executing-plans rule 4a): `python3 <absolute path of
   <planning-plugin>/skills/executing-plans/scripts/prove-claim.py claim` (`--help` lists its arguments) for the
   first claim and each `(red if …)` claim — `--test` the Test command above, `--break` a
   patch reverting your fix in `.claude/`; then `git add proof/`

## Constraints
- Do NOT modify files outside the Files list above
- Do NOT refactor unrelated code
- Do NOT introduce new dependencies not already in the project
- Wait on a background job you start by its own completion — the harness notification,
  `wait <pid>`, or a sentinel file it writes last; a `pgrep -f` loop matches its own shell
- Commit with message: "Stage <N> Task <N.M>: <description>", ending with the
  executor trailer on its own single physical line:
  `Executor: dispatched — <the agent name you were dispatched as, without the @>`
  (executing-plans rule 7: without it the task reads as `unknown`)

## Return
A structured report:
- STATUS: GREEN | ESCALATE
- If GREEN: commit SHA, test output summary, any notes
- If ESCALATE: last error, diagnosis, what was tried, what's needed from the caller
- An agent returns only after its own background work has finished or been stopped, and says which
```

A constraint that is not in the prompt is a constraint the agent cannot honor. Carry a
decision in the entry's own words; a security-sourced decision never brings its report
body into a prompt.

## Dispatch

Tasks that cleared the preconditions are already authorized. Dispatch **without asking**
whether to proceed or whether to run them in parallel — the confirmation turn happened
when the plan was approved. A standing caution against dispatching subagents unless the
user requested it is conditional, not absolute: approving a plan whose execution model
names this dispatch point *was* the request.

Dispatch every task in S to its agent **together** — one task-tool call per task, all
issued before waiting on any of them; a dispatch that waits on the previous one's result
runs the batch one after another. Take each call's agent name, and the stack skill the
agent loads first, from `stack-routing.md` (the fallback is OpenCode's built-in `general`)
— read it before dispatch; don't reinvent the mapping.

**There is no plugin-enablement layer on OpenCode, so no routed agent can be "installed but
not enabled".** An agent either appears in OpenCode's agent list or it does not exist, and
there is no capability index beside an install to load one from disk. A task whose row
names no installed agent goes to `general` with the stack skill named at the top of its
prompt. An agent this package ships that is missing from the list is a broken install:
stop and say so, rather than degrading silently.

## Collect and integrate

Wait for every dispatched agent before integrating. Each returns `STATUS: GREEN` or
`STATUS: ESCALATE`.

For each GREEN task:

1. Confirm the commit exists and spot-check the diff.
2. Run the task's test **in the main session** — agents occasionally claim green on a test that was skipped or misreported.
3. **Verify the executor trailer**: `git log -1 --format='%(trailers:key=Executor,valueonly)' <sha>` must be non-empty and read `dispatched — <agent>`: the name it was dispatched as, without the `@`, and one this install has. If it is blank or wrong, amend it now; a blank trailer otherwise surfaces at the stage gate as `unknown` (`../SKILL.md` Step 3.3 rule 7, Step 3.5).
4. Flip the task's Status, then check its `Blocks` list: a blocked task whose `Depends on` is now fully green is ready for the next round.

For each ESCALATE task:

1. Do not dispatch its dependents — the graph is blocked through this node.
2. Treat the agent's diagnosis as evidence, not a fix. Surface the task ID, the last error, the diagnosis, your read on it and the option you recommend (re-dispatch with tighter scope, revise the plan, execute manually).
3. Wait for the user's direction.

## Merge check

After integrating, run **the round's own tests together** — every dispatched task's `Test:`
in one invocation — plus any test file whose subject two of them both touched. Parallel
work sometimes interacts at seams the individual tests don't cover.

**Not the full suite.** This is a checkpoint inside a stage: the stage gate runs the plan's
`stage-scope:` command once, and close-out runs the one full pass
(`../../planning-projects/references/test-scope-tiers.md`).

Then return to `../SKILL.md` § Step 3.4 — Propagate unblock: a newly ready task starts the
next round, and an empty S goes to the stage gate.

## Host notes (OpenCode)

- **Dispatch** uses OpenCode subagents: an explicit task-tool call naming the agent. The
  `task` permission must be allowed for the calling agent.
- **The dispatch mandate is carried, not narrowed.** Every `Dispatch: YES` task goes to a
  subagent on this host; there is no table-routed inline outcome here.
- **When `task` is denied for this session**, dispatch is *unavailable* — not routed
  elsewhere. Stop and tell the user which permission to grant; do not quietly run the
  batch inline and report it as executed (`../SKILL.md` § Stop conditions).
- **The todo list** is OpenCode's `todowrite` tool; the plan's `Status:` fields stay the
  record.
