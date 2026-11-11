# Dispatch — running a plan's `Dispatch: YES` tasks

The procedure `../SKILL.md` § Step 3.2 — Split by parallelism runs for every ready
`Dispatch: YES` task: select, guard, brief, dispatch, collect, integrate. Which subagent
type and stack skill a task gets is `stack-routing.md`'s to say.

> On Codex, `<planning-plugin>` is this plugin's installed folder: the folder that holds `skills/` and `.codex-plugin/`. In a shell command use its absolute path, quoted.

On Codex a sub-agent is one this session spawns with `spawn_agent` and collects with
`wait_agent`. Codex never spawns on its own, runs at most 6 at once, and a spawned agent
cannot spawn another (§ Host notes (Codex)).

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
fails, a routed role that is not installed, or dispatch
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

**On Codex a dispatch has two declared shapes, and neither is a hand-back.** If
`stack-routing.md` names an agent for the task, spawn it. If the table routes the task
*inline*, the dispatch is satisfied by **table-routed inline execution** in this session,
on the same brief and the same Red-Green rules. That is a routing outcome the table fixed,
not an executor judgment call, and it is recorded as one (§ Dispatch,
§ Collect and integrate).

## Guard against file conflicts

For every pair in S, compare the file paths each task will modify. If the paths overlap,
remove one from S (keep the task with the higher `Blocks` count, since it unblocks more).
The removed task is **dispatched on its own after this batch returns** (to its routed agent, or
table-routed inline where the table names none): the conflict decided *when*, not *whether*.

Guard **shared resources** the same way: the same schema migration, the same CI config
section, the same feature flag are conflicts even when the literal paths differ. Log which
task was deferred and why.

## Brief each agent

A sub-agent sees only its prompt. Build one per task in S from this template:

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
<The installed stack skill stack-routing.md matched, by name — load it before editing.
When none is installed, leave this heading out and say so in the Context block.>

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
6. Run NOTHING WIDER than the Test above. No full suite, no regression sweep, no "check I broke nothing else" — the main session runs that once at the
   gate. A whole test file instead of one filter is fine
7. Stage your work, then prove it (executing-plans rule 4a): `python3 <absolute path of
   <planning-plugin>/skills/executing-plans/scripts/prove-claim.py claim` (`--help` lists its arguments) for the
   first claim and each `(red if …)` claim — `--test` the Test command above, `--break` a
   patch reverting your fix, which a shell redirect writes into `"${TMPDIR:-/tmp}"`; then `git add proof/`

## Constraints
- Do NOT modify files outside the Files list above
- Do NOT refactor unrelated code
- Do NOT introduce new dependencies not already in the project
- Wait on a background job you start by its own completion — `wait_agent` for an agent
  you spawned, `wait <pid>`, or a sentinel file it writes last (a Codex shell call keeps no
  jobs for the next call); a `pgrep -f` loop matches its own shell and waits for ever
- Commit with message: "Stage <N> Task <N.M>: <description>", ending with the
  executor trailer on its own single physical line:
  `Executor: dispatched — planning:<the role you were spawned as>`
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
when the plan was approved. Codex spawns an agent only when it is explicitly asked to, and
a standing caution against spawning agents unless the user requested it is conditional, not
absolute: approving a plan whose execution model names this dispatch point *was* the request.

**Spawn the whole ready batch before waiting on any of it.** For each task in S, call
`spawn_agent` with the routed role, the task id and its prompt; only then collect them with
`wait_agent`. Codex runs at most 6 spawned agents at once (`[agents] max_threads`, default
6): with more than 6 ready, spawn 6 and start the next as each returns. A spawned agent
cannot spawn another (`max_depth` 1), so this session owns every dispatch round.

Take each task's route, and the stack skill it loads first, from `stack-routing.md` — read
it before dispatch; don't reinvent the mapping. The table decides *how* a `Dispatch: YES`
task is dispatched, never *whether*:

| Table says | What you do | Trailer on the task's commit |
|---|---|---|
| `planning:<agent>` | spawn that role with the task's prompt | `Executor: dispatched — planning:<agent>` |
| *inline* | run it here on the same brief | `Executor: inline (routing table — no <stack> agent on this host)` |

**A table-routed inline task gets the same brief**, `## Decisions in force` included.
Neither shape may borrow `Executor: inline (dispatch failed)`: that shape means the
mechanism was unavailable, and a table-routed inline is the mechanism working as routed.

**When the routed role is not installed** (no `planning-<agent>.toml` under `$CODEX_HOME/agents`, `~/.codex/agents` when `CODEX_HOME` is unset; `python3 <planning-plugin>/scripts/install-agents.py --install` writes the missing ones), it cannot
be spawned: that is dispatch unavailable — a Stop condition, never an inline run on your
own authority.

## Collect and integrate

Wait for every spawned agent (`wait_agent`) before integrating. Each returns `STATUS: GREEN` or
`STATUS: ESCALATE`.

For each GREEN task:

1. Confirm the commit exists and spot-check the diff.
2. Run the task's test **in the main session** — agents occasionally claim green on a test that was skipped or misreported.
3. **Verify the executor trailer**: `git log -1 --format='%(trailers:key=Executor,valueonly)' <sha>` must be non-empty, and read `dispatched — planning:<agent>` for a spawned task or `inline (routing table — no <stack> agent on this host)` for a table-routed one. If it is blank or wrong, amend it now; a blank trailer otherwise surfaces at the stage gate as `unknown` (`../SKILL.md` Step 3.3 rule 7, Step 3.5).
4. Flip the task's Status (and `update_plan` when this session lists it), then check its `Blocks` list: a blocked task whose `Depends on` is now fully green is ready for the next round.

For each ESCALATE task:

1. Do not dispatch its dependents — the graph is blocked through this node.
2. Treat the agent's diagnosis as evidence, not a fix. Surface the task ID, the last error, the diagnosis, your read on it and the option you recommend (re-dispatch with tighter scope, revise the plan, execute manually).
3. Wait for the user's direction.

Count a round in **three** terms on this host — dispatched to an agent, table-routed
inline, escalated — plus green (`3 dispatched, 2 table-routed inline, 0 escalated; 5
green`). Folding the table-routed inlines into the dispatched count overstates delegation;
folding them into a deviation count invents a failure that did not happen.

## Merge check

After integrating, run **the round's own tests together** — every dispatched task's `Test:`
in one invocation — plus any test file whose subject two of them both touched. Parallel
work sometimes interacts at seams the individual tests don't cover.

**Not the full suite.** This is a checkpoint inside a stage: the stage gate runs the plan's
`stage-scope:` command once, and close-out runs the one full pass
(`../../planning-projects/references/test-scope-tiers.md`).

Then return to `../SKILL.md` § Step 3.4 — Propagate unblock: a newly ready task starts the
next round, and an empty S goes to the stage gate.

## Host notes (Codex)

- **The roles are installed, not shipped.** A Codex plugin cannot carry agent roles, so the
  plugin's installer writes them under `$CODEX_HOME/agents`. A trailer or report naming a
  role it has not written records a dispatch nobody can reproduce.
- **Most stacks route inline.** Codex has no general stack agent, so the routing table sends
  every stack to table-routed inline execution. The table decides it, never the executor,
  and every instance is visible in `git log`.
- **Progress is a file, not a message.** There is no task-list tool: the plan's `Status:`
  fields and the execution state are the record. A progress note between phases is
  commentary inside the turn; only a final message ends it, and the Stop hook may continue
  a run in flight (`plan-continue-hook.md`).
