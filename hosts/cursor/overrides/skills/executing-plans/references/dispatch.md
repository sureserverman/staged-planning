# Dispatch — running a plan's `Dispatch: YES` tasks

The procedure `../SKILL.md` § Step 3.2 — Split by parallelism runs for every ready
`Dispatch: YES` task: select, guard, brief, dispatch, collect, integrate. Which subagent
type and stack skill a task gets is `stack-routing.md`'s to say.

> On Cursor, `<planning-plugin>` is this plugin's installed folder: the folder that holds `skills/` and `.cursor-plugin/` (`~/.cursor/plugins/local/planning` for a local install). In a shell command use its absolute path, quoted.

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
fails, a component that needs hooks or a bundled MCP server and can't be lazy-loaded, or dispatch
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

## Guard against file conflicts

For every pair in S, compare the file paths each task will modify. If the paths overlap,
remove one from S (keep the task with the higher `Blocks` count, since it unblocks more).
The removed task is **dispatched on its own after this batch returns**: the conflict
decided *when*, not *whether*.

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
If that skill's plugin isn't installed, instead: "Read
~/.cursor/plugins/local/<plugin>/skills/<name>/SKILL.md and follow it" — the same skill body,
loaded from disk (see stack-routing.md § Resolving; a Cursor install has no capability index
beside it, so the path comes from the routing table's plugin and name).>

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
7. Commit your change (`git add` the files you changed). Do NOT launch the
   `claim-verifier` and write nothing under `proof/`: on Cursor claims are proven once per
   stage, at the gate, after the review fixes (executing-plans rule 4a), so a proof made
   now would only go stale
8. What the gate's verifier cannot judge for you: a value the task says to take from
   somewhere (a pin, a path, a version) is READ from there in code, never copied; a claim
   that something rebuilds or regenerates is proven by changing each input it reads and
   watching it rerun; if a requirement can break without the Test going RED, add a check
   that would catch it (keep the Test as given) and name it in your report. A requirement
   you cannot meet goes in your report as a deviation — never work around it silently. A
   claim in the Test that no patch in the repo can break (it holds only on a device, over
   the network, or in front of a person) goes in your report too: the gate's verifier
   records it with `prove-claim.py deviation --claim`, disclosed and never counted as proof

## Constraints
- Do NOT modify files outside the Files list above
- Do NOT refactor unrelated code
- Do NOT introduce new dependencies not already in the project
- Wait on a background job you start by its own completion — the harness notification,
  `wait <pid>`, or a sentinel file it writes last; a `pgrep -f` loop matches its own shell
- Commit with message: "Stage <N> Task <N.M>: <description>" — code only, nothing under
  `proof/`. The git reference-transaction hook does not gate task commits; it gates the
  stage's `Stage N green` commit, after the gate's verifier has proven every task. End the
  message with the executor trailer on its own single physical line:
  `Executor: dispatched — <your agent name>`
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
when the plan was approved. A standing caution against calling the Task tool unless the
user requested it is conditional, not absolute: approving a plan whose execution model
names this dispatch point *was* the request.

Launch every task in S in a **single message** with one `Task` call each, naming its agent
by bare name; sequential tool calls wait on each other. Take each call's agent name, and
the stack skill the agent loads first, from `stack-routing.md` (the fallback is
`generalPurpose`) — read it before dispatch; don't reinvent the mapping.

**When the matched agent's plugin isn't installed or enabled**, don't drop to
`generalPurpose` blind: resolve it from disk per `stack-routing.md` § *Resolving a
capability whose plugin isn't enabled*. Dispatch `generalPurpose` with the agent's `.md`
body (read from `~/.cursor/plugins/local/<plugin>/agents/<name>.md` — a Cursor install has
no capability index beside it, so the path comes from the routing table) injected as its
instructions. A component that needs hooks or a bundled MCP server can't be lazy-loaded —
stop and ask the user to enable that plugin.

## Collect and integrate

Wait for every dispatched agent before integrating. Each returns `STATUS: GREEN` or
`STATUS: ESCALATE`.

For each GREEN task:

1. Confirm the commit exists and spot-check the diff.
2. Run the task's test **in the main session** — agents occasionally claim green on a test that was skipped or misreported.
3. **Verify the executor trailer**: `git log -1 --format='%(trailers:key=Executor,valueonly)' <sha>` must be non-empty and read `dispatched`. If it is blank or wrong, amend it now; a blank trailer otherwise surfaces at the stage gate as `unknown` (`../SKILL.md` Step 3.3 rule 7, Step 3.5).
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

## Host notes (Cursor)

- **Agents are dispatched by bare name** through Cursor's Task tool: `design-handoff-reproducer`,
  `architecture-researcher`, `code-reviewer`, `claim-verifier`, the built-in
  `generalPurpose`, and another plugin's agent by the name the session lists. Cursor has
  no plugin namespace, and every local plugin is installed side by side under
  `~/.cursor/plugins/local/`.
- **Cursor chooses the model.** No agent file pins one and no dispatch names one.
- **Proof is the gate's.** A dispatched task commits code only; the stage gate's one
  `claim-verifier` dispatch proves the stage's claims after the review fixes
  (`../SKILL.md` rule 4a).
- **The dispatch log has dispatch lines only.** Cursor's `preToolUse` hook (matcher
  `Task`) logs each launch; Cursor sends no subagent start or stop event, so a review is
  matched to its dispatch line, never to a start or stop line.
