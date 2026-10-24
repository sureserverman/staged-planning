---
name: dispatching-parallel-agents
description: Use when executing-plans has Dispatch YES tasks from a planning-projects plan whose dependencies are green. Dispatches one agent per task, running concurrently. Triggers on "dispatch these tasks in parallel", "run these Dispatch YES tasks", "fan out these independent fixes". On OpenCode, invoke this skill by name.
---

> On OpenCode, `<planning-plugin>` is this package's folder: the folder that holds `skills/`, `../..` from the base directory OpenCode prints with this skill. In a shell command use its absolute path, quoted.

# Dispatching Parallel Agents

Fan out independent tasks from a `planning-projects` plan to concurrent sub-agents, collect their results, propagate the dependency graph, and return control to `executing-plans` (or the caller).

This skill is the operational arm of `planning-projects` Phase 5 ("Dispatch"), usually invoked by `executing-plans`.

**Announce at start:** "Using the dispatching-parallel-agents skill to fan out <N> independent tasks."

---

## Preconditions

Refuse to dispatch unless all are true:

1. **A plan exists** at a known path, produced by `planning-projects`. The plan's task fields (`Depends on`, `Blocks`, `Dispatch`, `Test`, `Red-Green max cycles`) are the source of truth. Older plans spell the field `Parallel:`; treat it identically.
2. **Every task in scope has `Dispatch: YES`** in the plan.
3. **Every task's `Depends on` list is fully green** (every referenced prior task has passed its test and been committed).
4. **No two tasks in scope modify the same file.** This is checked against the plan's declared file paths; if the plan doesn't list files, scan the task descriptions. When in doubt, force sequential.
5. **The stage gate has not yet run.** Dispatches happen before the gate, not after.

If any precondition fails, stop and report which one — do not relax them on your own.

**These five preconditions are the whole check.** Satisfying them means dispatch — not a
pause to confirm with the user first. A plan's `Dispatch: YES` is a direct order, approved
when the plan was approved; asking "should I dispatch these?" here re-litigates a decision
that's already made. (An inlined task and a dispatched one produce byte-identical
artifacts, so skipping a mandated dispatch shows up nowhere in the diff — only later, when
the review work that dispatch was supposed to trigger turns out to have never happened.)
The only legitimate halts remain the ones in § Preconditions: a precondition genuinely fails, or **dispatch is mechanically unavailable or disallowed in this session** — which is a Stop condition for the caller (`../executing-plans/SKILL.md` § Stop conditions), reported as such rather than resolved by quietly inlining the work. "I wasn't sure
whether to fan out" is not one.

---

## Checklist

Create a task for each:

1. **Select** — identify the set of tasks that satisfy all preconditions
2. **Guard** — verify file-path disjointness; force any conflicting pair sequential
3. **Brief** — construct an agent prompt per task from the plan (see prompt template)
4. **Dispatch** — dispatch every selected task (the task tool) before waiting on any
5. **Collect** — wait for every sub-agent to return
6. **Integrate** — commit green results, escalate failures, re-check the dependency graph
7. **Report** — hand control back to `executing-plans` with the updated task status

---

## Phase 1 — Select

From the current stage, identify tasks where:

- `Dispatch: YES`
- Every task in `Depends on` is in the completed set (check the plan's `Status:` fields or your `todowrite` todo list)
- The task has not already been dispatched or completed

Call this set **S**. A lone ready task is **still dispatched**: |S| = 1 runs as a single
dispatch rather than a fan-out, and is never a reason to hand the task back to the caller.
Having nothing to run alongside it is a fact about *concurrency*, while `Dispatch: YES` is
a *delegation* directive — two different properties (`../planning-projects/SKILL.md` § Stage structure). Only |S| = 0 returns control to the caller with nothing to do.

On OpenCode a single dispatch needs no special shape: `references/stack-routing.md` names
an agent for every row, and its fallback (OpenCode's built-in `general`) is always there,
so |S| = 1 is an ordinary dispatch of one agent — same brief, same trailer, same
trust-but-verify as any member of a larger batch. Only the concurrency disappears.

## Phase 2 — Guard against file conflicts

For every pair `(tᵢ, tⱼ)` in S, compare the file paths each task will modify:

- If paths are disjoint → keep both in S
- If paths overlap → remove one from S (prefer keeping the higher-`Blocks`-count task, since it unblocks more downstream work). The removed task is **dispatched on its own after this batch returns** — removing it from S drops it from *this concurrent batch*, never from dispatch. It carries `Dispatch: YES`, so it goes to a subagent whenever it runs; the conflict decided *when*, not *whether*.

Also guard against **shared resources** beyond files: same DB table schema migration, same CI config section, same feature flag — these are "logical" file conflicts even when the literal paths differ.

Log which task (if any) was deferred and why.

## Phase 3 — Brief each agent

For each task remaining in S, construct a self-contained prompt. A sub-agent will not see the conversation — it sees only its prompt.

An OpenCode subagent starts in a fresh session with its own `AGENTS.md` load; nothing in
that startup path reaches the plan file, so the prompt is the only channel that exists.

### Prompt template

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
<The installed stack skill references/stack-routing.md matched, by name — load it before editing>

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
7. Stage your work, then prove it (executing-plans rule 4a): `python3 <absolute path of
   <planning-plugin>/skills/executing-plans/scripts/prove-claim.py claim` (`--help` lists its arguments) for the
   first claim and each `(red if …)` claim — `--test` the Test command above, `--break` a
   patch reverting your fix in `.claude/`; then `git add proof/`

## Constraints
- Do NOT modify files outside the Files list above
- Do NOT refactor unrelated code
- Do NOT introduce new dependencies not already in the project
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

**Prompt discipline:** focused scope (one task), self-contained (all needed context inlined), explicit constraints (no refactoring creep), specific return format (so the caller can integrate).

**Why decisions must be in the prompt.** A dispatched agent is otherwise structurally
blind to them: it sees a task, a file list, and a slice of research — never the register,
never the plan's decisions section, never the surrounding session. A constraint that is
not in the prompt is a constraint the agent cannot honor, and the violation surfaces (if
at all) at the stage gate, after the work is built. Carry the entry's own words — a security-sourced decision
never brings its report body into an agent prompt, which needs the constraint, not the findings.

## Phase 4 — Dispatch

Tasks that cleared Preconditions are already authorized. Dispatch on invocation,
**without asking** whether to proceed or whether to run them in parallel — the
confirmation turn happened when the plan was approved, not here. A standing caution against dispatching
subagents unless the user requested it is conditional, not absolute: a plan whose
execution model names this dispatch point is the condition being met, so approving that
plan *was* the request.

Dispatch every selected task to its agent **together** — one task-tool call per task, each with its self-contained prompt from Phase 3, all issued before
waiting on any of them. That is the only way they actually run concurrently: a dispatch
that waits on the previous one's result runs the batch one after another.

```
task(agent: code-reviewer,  description: "Task 2.3: review parser", prompt: <per task 2.3>)
task(agent: general,        description: "Task 2.4: validate schema", prompt: <per task 2.4>)
task(agent: <stack agent>,  description: "Task 2.5: write config file", prompt: <per task 2.5>)
```

Match each dispatch's agent name — **and the stack skill it should load first** — using the
routing table in `references/stack-routing.md`. That table is the source of truth (stack
work goes to an installed agent whose description matches the stack, with OpenCode's
built-in `general` agent as the fallback). Read it before dispatch; don't reinvent the
mapping here.

**There is no plugin-enablement layer on OpenCode, so no routed agent can be "installed but
not enabled".** An agent either appears in OpenCode's agent list (this package's four, the
built-ins, and whatever the user installed) or it does not exist, and there is no capability
index beside an install to load one from disk. So the load-from-disk branch Claude Code has
cannot fire here: a task whose row names no installed agent goes to `general` with the
stack skill named at the top of its prompt. An agent this package ships that is missing
from the list is a broken install: stop and say so, rather than degrading silently.

## Phase 5 — Collect

Wait for every dispatched agent to return. A single outstanding agent blocks propagation — don't start integrating until all are in.

Each agent returns `STATUS: GREEN` or `STATUS: ESCALATE`. Trust-but-verify:

- For `GREEN`: confirm the commit exists, run the task's test in the main session to verify, spot-check the diff
- For `ESCALATE`: read the reported diagnosis; that's evidence, not a fix — don't act on it blindly

## Phase 6 — Integrate

For each GREEN task:

1. Mark the task completed in the plan's status notes and in your `todowrite` todo list
2. Run the task's test **in the main session** (not just via the sub-agent's report) — agents occasionally claim green on a test that was skipped or misreported
3. **Verify the executor trailer the agent was asked to write**: `git log -1 --format='%(trailers:key=Executor,valueonly)' <sha>` must be non-empty and read `dispatched — <agent>`. If it is blank or wrong, amend it now. This is the same trust-but-verify this phase already applies to the test, aimed at the one artifact a sub-agent cannot check for itself — it never sees the main session's conventions, and a blank trailer otherwise surfaces only at the stage gate as an `unknown`, long after the cheap moment to fix it (`../executing-plans/SKILL.md` Step 3.3 rule 7, Step 3.5). The agent in the trailer is the name it was dispatched as, written without the `@`; a trailer naming an agent this install does not have is as wrong as a blank one
4. Check the task's `Blocks` list: for each blocked task, check whether its `Depends on` is now fully green. If yes, that task becomes dispatchable in the next round.

For each ESCALATE task:

1. Do not dispatch its dependents (the graph is blocked through this node)
2. Surface the escalation to the user with: task ID, last error, agent's diagnosis, your read on it, and what option you're recommending (re-dispatch with tighter scope, revise the plan, execute manually)
3. Wait for user direction

### Merge check

After integrating, run **the round's own tests together** — every dispatched task's `Test:`
in one invocation — plus any test file whose subject two of them both touched. Parallel work
sometimes interacts at seams the individual tests don't cover, and that seam is what this
check is for.

**Not the full suite.** This is a checkpoint inside a stage, so it takes the same bound every
other in-stage run takes: the stage gate runs the plan's `stage-scope:` command once, and
close-out runs the one full pass (`../planning-projects/references/test-scope-tiers.md`).
A full suite here would be the third sweep of the same stage.

## Phase 7 — Report and hand back

Return to `executing-plans` (or the calling session) with:

- Count dispatched, count green, count escalated
- Commit SHAs for green tasks
- Outstanding escalations
- Newly-unblocked tasks ready for the next dispatch round

`executing-plans` decides whether to call this skill again for the next round or move on to the stage gate.

---

## Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Dispatching tasks that share a file | Merge conflicts or silent overwrites in parallel branches | Run the Phase 2 file-disjointness check; force sequential on conflict |
| Inlining the entire research summary into every agent prompt | Blown context, slow dispatch, agents get lost | Give each agent only the 2-4 bullets relevant to its task |
| Trusting the agent's "GREEN" without verifying | Integration-time surprises; green tests that were actually skipped | Re-run the task's test in the main session for every green return |
| Dispatching before all Depends-on are green | Agents block waiting for prerequisites, or produce broken code | Hard-check: every task in scope has every Depends-on in the completed set |
| Dispatching one agent at a time and waiting on each | No actual parallelism; same runtime as running them one after another | Dispatch the whole ready set before waiting on any |
| Relaxing preconditions "just this once" | The shape of the whole execution model breaks; future tasks depend on assumptions that no longer hold | Stop and ask — or revise the plan through `planning-projects` |
| Ignoring escalations to keep the pipeline moving | Downstream dispatch on a broken graph; wasted agent time | Escalation freezes the subtree; surface it and wait |

## When NOT to use this skill

- Tasks are related (one fix might fix others) — investigate as a group first
- You don't have a plan — brainstorm and plan before dispatching
- |S| = 0 — nothing is dispatchable yet (a `Depends on` is still red). **|S| = 1 is not on this list**: a lone `Dispatch: YES` task is dispatched as a single dispatch, per Phase 1
- Tasks touch shared state (same file, same DB schema, same CI job) — force sequential
- The stage gate is ready to run — gates are a synchronization point; don't dispatch past them

---

## Sources and rationale

- **Dependency graph execution** — classic topological sort from graph theory; *Introduction to Algorithms* (CLRS) section 22.4
- **Fan-out / fan-in pattern** — Communicating Sequential Processes (Hoare, 1978); Go's `sync.WaitGroup` and Erlang supervision trees
- **Self-contained agent prompts** — Anthropic multi-agent orchestration guidance; sub-agents have no conversation context and must be briefed completely
- **Trust-but-verify** — Reagan / Gorbachev; applied to sub-agent reports. On incident postmortems: *Google SRE Book* Ch. 15
- **Merge check after parallel work** — continuous integration practice; Fowler, "Continuous Integration" (2006)
- **Failure propagation through dependents** — Erlang "let it crash" + supervisor trees; don't build on broken foundations

## Integration

- **planning-projects** — the upstream skill producing the plan with Dispatch and dependency fields this skill consumes
- **executing-plans** — the usual caller; decides when to invoke this skill during stage execution
- **stack-routing reference** (`references/stack-routing.md`) — the source of truth for Phase 4's agent + stack-skill choice; maps three of this package's four agents (`design-handoff-reproducer`, `architecture-researcher`, `code-reviewer`; `claim-verifier` is dispatched by executing-plans) and routes stack work to an installed agent whose description matches, with OpenCode's built-in `general` agent as the fallback. Shared with `executing-plans` Step 3.2
- **code-reviewer agent** — optional between dispatch rounds if integrated diffs need independent review before the stage gate

---

## Host notes (OpenCode)

- **Dispatch** uses OpenCode subagents: an explicit task-tool call naming the agent. The `task` permission must be allowed for the calling agent. Dispatch
  the whole ready set before waiting on any result.
- **The dispatch mandate is carried, not narrowed.** Every `Dispatch: YES` task goes to a
  subagent on this host: every routing-table row names an agent, and the fallback
  (`general`) is built in. There is no table-routed inline outcome here.
- **When `task` is denied for this session**, dispatch is *unavailable* — not routed
  elsewhere. Stop and tell the user which permission to grant; do not quietly run the
  batch inline and report it as executed. Enabling it is the user's call, and a run that
  substitutes inline execution for a permission the user withheld has misreported what
  happened (`../executing-plans/SKILL.md` § Stop conditions).
- **The executor trailer names the agent, not the tool.** `Executor: dispatched —
  code-reviewer` for a task routed to `@code-reviewer`; `general` when the fallback row
  took it. One physical line, no `@`.
- **The todo list** is OpenCode's `todowrite` tool; the plan's `Status:` fields stay the
  record.
- **Decisions in force** is host-neutral: the Phase 3 block reads the plan's
  `## Decisions in force` (see the `decisions` skill) and ships in every dispatch prompt
  that has an entry bearing on its task.
