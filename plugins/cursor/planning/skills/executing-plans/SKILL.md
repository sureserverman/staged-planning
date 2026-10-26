---
name: executing-plans
description: Use when you have a planning-projects plan — Standard (staged), master (sub-plans), or light (single-stage) — and need to execute it, driving Red-Green loops and stage gates. Triggers on "execute this plan", "run the plan", "execute the master plan".
---

> On Cursor, `<planning-plugin>` is this plugin's installed folder: the folder that holds `skills/` and `.cursor-plugin/` (`~/.cursor/plugins/local/planning` for a local install), which is `../..` from this SKILL.md. In a shell command use its absolute path, quoted.

# Executing Plans

Execute a plan produced by `planning-projects`. Honor the stage-gate model: tasks run through Red-Green loops, a stage's gate must pass before the next stage starts, and independent tasks are dispatched in parallel when the plan's dependency graph allows it.

**Announce at start:** "Using the executing-plans skill to implement `<plan-path>`."

## What this skill expects

The plan file was produced by `planning-projects`. It contains:

- A **Research Summary** (background, not executed)
- A **Preflight** checklist (verified before Stage 1)
- One or more **Stages**, each with:
  - Goal, Depends on, Blocks, Risk, Rollback
  - Ordered **Tasks**, each with `Depends on`, `Blocks`, `Dispatch: YES|NO`, `Test:` (a concrete runnable check), `Red-Green max cycles: N`
  - A **Stage gate** checklist

If the plan doesn't have these fields, stop — it wasn't produced by `planning-projects` and must be either rewritten through that skill or executed manually.

**Exceptions.** A `*-master-plan.md` (`# Master Plan:`) or a `*-light-plan.md` (`# Light
Plan:`). It deliberately has no Preflight, Stages or Tasks (master), or no Research Summary,
Preflight, Risk / Rollback / Blocks / Dispatch fields (light). Do NOT reject either — execute
them per **Master plans** and **Light plans** below.

---

## Reference map

The trunk carries what fires on every run; these load when their condition is met — read
the one you need rather than working from memory.

| Read this | When |
|---|---|
| `references/master-plans.md` | the plan file is a `*-master-plan.md` |
| `references/light-plans.md` | the plan file is a `*-light-plan.md` |
| `references/review-scope.md` | declaring the tier at Preflight, or resolving how format and tier compose — **the authority on both, and on the opt-out rules** |
| `references/preflight-checks.md` | running Preflight — the procedure for each check, and the amendment protocol |
| `references/dispatch-fidelity.md` | the roster, probe or `Review: skip` snapshot needs justifying rather than just following |
| `references/task-execution.md` | dispatching or inlining a task, writing its test, or running Tier 1 |
| `references/bug-is-a-class.md` | a bug surfaced and the set it belongs to has to be named |
| `references/stage-gate.md` | running a stage gate — report shapes, verify hooks, evaluator, Tier 2, dispositions |
| `references/gate-failure-procedure.md` | a stage gate has failed |
| `references/close-out.md` | every stage is green — the close-out procedure |
| `references/progress-state-file.md` | writing `.claude/plan-progress.json`, or wiring the statusline |
| `references/session-handoff.md` | a stage or sub-plan gate has passed — whether to continue or hand off (`--adopt-handoff <id>` is not carried on Cursor) |
| `../planning-projects/references/owner-decisions.md` | an owner decision's scope is in doubt — what each catalog point asks |
| `references/integration.md` | routing to another skill or agent, or citing the opt-out rules |
| `references/sources.md` | citing why a rule here exists |

Paths are relative to this skill's directory; from a dispatch use
`references/<file>`.

---

## Master plans

A `*-master-plan.md` (or `# Master Plan:` heading) links 2–7 sub-plans through a
`## Sub-plans` register. It deliberately has no Preflight, Stages or Tasks — do not reject
it. Execute sub-plans in register dependency order; on each sub-plan's close-out flip its
register `Status`, run that entry's `**Gate:**` checks, append a handoff note, commit
`"Sub-plan N green"`, then continue with the next sub-plan: elsewhere a measured verdict
(`context-usage.py --sub-plan-boundary`) can hand off here, but that script does not ship on
Cursor, so on this host only a dated wait hands off and the master file is the cross-session
handoff artifact. **Version bumps defer to the master
close-out** — one feature landing across five sub-plans is one release event, not five.

Run `validate-gate-checks.py` and `validate-dispatch.py` (both under `<planning-plugin>/skills/planning-projects/scripts/`) on the master itself, not only on each sub-plan: a master's
cross-plan checks are exactly the ones that prove integration *between* sub-plans, so an
instance-shaped one there survives every sub-plan gate.

Full execution model, critique checklist and close-out: `references/master-plans.md`.

---

## Light plans

A `*-light-plan.md` (or `# Light Plan:` heading) is a single stage of 2–5 tasks with one
gate. It deliberately has **no Research Summary, no Preflight section, and no Risk /
Rollback / Blocks / Parallel fields** — do not reject it for those. Execute it through the
normal flow with four deltas: Preflight is git-bootstrap plus a green baseline only; every
task runs **inline** (no fan-out); the format sets a **whole-diff** review shape in place of
per-task passes — **that single pre-gate review IS the light plan's Tier-2, so do not also
run a separate stage-gate Tier-2 pass**; and close-out applies a single stated version bump.
**How many passes actually run is the declared tier's call, not the format's**
(`references/review-scope.md`): `none` runs none, `light` and `standard` run that one, `high`
adds a second pass and Tier-1 even here, on the risk-listed tasks its declaration names.

Everything else is unchanged.

Full deltas: `references/light-plans.md`.

---

## Checklist

Keep a plain checklist of these in your working notes, and work them in order:

1. **Load and critique the plan** — raise concerns before starting
2. **Run Preflight** — verify every check; stop on failure
3. **For each stage, in order:**
   a. Dispatch `Dispatch: YES` tasks via `dispatching-parallel-agents`; work `Dispatch: NO` tasks in the main session
   b. Drive each task through its Red-Green loop
   c. Run the stage gate; stop if it fails
   d. After the gate commit, evaluate the stop rules — `context-usage.py` does not ship on Cursor, so no measured rule fires and only a dated wait hands off
4. **After all stages green:** hand off for review and merge (Phase Close-out)

---

## Run to completion — don't stop until you have to

Once Preflight passes, **drive the plan straight through to close-out.** Stage boundaries
are checkpoints, not approval gates: commit a passed gate and start the next stage without
asking "should I continue?" — the plan is the approval. Keep going through a
green task, a passed gate, a failed cycle that still has budget, and any surprise you can
resolve from the plan plus evidence.

**Only the documented Stop conditions halt execution.** Everything else is work to push
through. When you do stop, it is because continuing would be guessing or unsafe — say which,
with evidence, and what you need to resume. A context handoff is **not** a licence to stop
early: it happens at a gate, on a rule's `handoff` verdict, never on an impression that the
session is degraded (§ Context resets at stage boundaries). On Cursor nothing measures the
context (`context-usage.py` does not ship here), so only a dated wait hands off.

**Never end a turn on an announcement.** *"Starting Stage 3."* as last words has started
nothing: the tool call opening the announced work goes in the **same turn** as the sentence,
or instead of it — never in place of it (`references/stage-gate.md` § If the gate passes).
On Cursor this is sharper still: an assistant message with no tool call ends the turn, so
narration between tasks is itself a stop (§ Host notes (Cursor)).

---

## The plan is the authorization — dispatch without a confirmation turn

**A dispatch this plan mandates is a direct order, and you execute it without asking.** That
covers a `Dispatch: YES` task, and — **each on the conditions `references/review-scope.md`
already sets for it, never beyond them** — a review the declared tier calls for, an evaluator
the tier funds at a `(judgment)` gate, and the Preflight probe on a non-empty roster at
`standard` or `high`. The rule removes the *asking*, never the *conditions*. Do not spend a
turn on *"shall I fan these out?"* or *"should I dispatch the reviewer?"* — the answer was
given when the plan was handed to you.

**Why this needs saying at all.** A session usually carries a standing caution of roughly the
form *"do not launch a subagent with the `Task` tool unless the user requested it"*. That caution is
**conditional, not absolute**, and a plan whose execution model names dispatch points is the
condition being met: **approving the plan WAS the request.**

**The bound, which carries equal weight.** With **no plan in play and no mandate**, the
caution stands and you ask. This rule deletes a confirmation turn where a plan already
authorized the work; it does not authorize dispatch in general, and it never makes a dispatch
the *tier* did not fund (`references/review-scope.md`) suddenly due. A rule stated without its
bound gets over-corrected into its own inverse — a standing refusal to dispatch unless asked —
which strips the same reviews for the opposite reason.

**What still halts a dispatch**, unchanged: the probe fails or dispatch is unavailable (a
Preflight failure and a documented Stop condition — the user chooses, and inline substitution
is not the executor's call to make), or a component that needs hooks or a bundled MCP
server cannot be lazy-loaded (Step 3.2 says to stop and ask the user to install or enable
that plugin). *"I wasn't sure whether to fan out"* has never been on that list.

Why a skipped mandated dispatch leaves no trace: `references/dispatch-fidelity.md`.

---

## A bug found during execution is a class — sweep it, fix every instance

**Any defect you find during a run is one sample of a class until a command proves
otherwise.** This fires wherever a bug surfaces: a RED test inside a Red-Green loop, a
finding from either review tier, an evaluator finding, a failed gate check, or something you
simply notice while editing a file. It is **not** scoped to gates.

When you find one:

1. **Diagnose evidence-first** before generalizing. A set derived
   from a wrong root cause is a *wrong set*, swept confidently, reporting green.
2. **Name the set, and enumerate it with a command** — grep the defect's distinguishing
   string, list every sibling of the failing artifact's kind, list every caller of the changed
   symbol. The task's `Scope:` field is a starting point, not an authority. **When no `Scope:`
   exists, you still enumerate**; an undeclared set is still a set.
3. **Fix every member the sweep returns, in the same change** — not the instance that
   happened to surface.
4. **Write the command down** — in the commit body, or in the gate report when a gate is what
   surfaced the bug.

**The whole project is the search space, not the plan's blast radius** — "out of scope"
describes a plan's *subject matter*, never a defect's *reach*. **Where the sweep stops:** it covers the defect's
own predicate — whatever makes an instance an instance — and nothing wider; it is not a licence
to refactor whatever lives nearby. **A class you cannot express as a command is
absence-shaped: assert the property rather than extend the list.** Disclose the limit.
**It costs a command, never a dispatch**, so it belongs with the untiered
mandates and runs at **every** review tier, including `none`.

Both shapes, the repeat trigger, where the sweep stops, and the dispatch-shaped
consequence when it widens the diff into a risk-listed area: `references/bug-is-a-class.md`.

---

## Phase 1 — Load and critique

1. Read the plan file in full (supervised handoff, `--adopt-handoff <id>`, is not carried on
   Cursor)
2. Verify the structure: Research Summary, Preflight, Stages with the expected fields. **For
   a light plan those first two and the Risk / Rollback / Blocks / Dispatch fields are
   correctly absent — do not flag it**; verify instead a single stage of 2–5 tasks, each with
   a `Status` and a runnable `Test:`, plus one gate. A light plan with a second stage or a
   6th task should have been Standard — flag that.
3. Critique: is any task's test vague ("should work")? Is any stage oversized (>7 tasks)? Is any dependency cycle present? Does any task modify a file that a parallel sibling also modifies? (The parallel-conflict and stage-oversize checks are moot for a light plan — one stage, inline execution.)
4. **If concerns exist, surface them to the user before starting.** A plan with an unrunnable test or a dependency cycle will waste an entire Red-Green budget before the problem is found

4a. **Classify the plan's gate checks** — run
   `python3 <planning-plugin>/skills/planning-projects/scripts/validate-gate-checks.py <plan>`
   and surface the result with the other concerns. An **INSTANCE-SHAPED** check names one
   artifact where the goal is a property of many, so it cannot fail on the siblings that make
   the defect class — each survivor costs another remediation round, and catching it here is
   the cheapest it will ever be.

   **Advisory on an existing plan, mandatory on a new one** — say which case you are in.
   `(judgment)` is the sanctioned escape hatch for a check that genuinely needs a reader.
   Beside it run `python3 <planning-plugin>/skills/planning-projects/scripts/validate-dispatch.py <plan>`: a FAIL is a wrong `Dispatch:` field, surfaced
   the same way — advisory on an existing plan too — before Preflight builds a roster from it.

5. **Read the plan's `## Decisions in force`** — the constraints it was written under,
   carried into the file so a session that never reads the register still implements under
   them. Note which tasks carry `Honors DEC-NNN` and which carry `Supersedes …` (a deliberate
   override you record at close-out). **A plan with no such section is not a plan with no
   decisions** — treat its absence as *"not recorded"*, never *"none apply"*, and run the
   Preflight scan.

Keep a plain checklist in your working notes mirroring the plan: one task per stage, sub-items per task. Mark the current stage in progress only when Preflight passes. Then take the record audit's baseline: `python3 <planning-plugin>/skills/executing-plans/scripts/plan-flip-audit.py <plan> --snapshot --repo <repo-root>` (§ Host notes (Cursor), "The record audit").

## Phase 2 — Preflight

Run every check in the Preflight section and report pass/fail:

- Tools installed and at compatible versions
- Dependencies resolvable
- APIs reachable, keys valid
- Access / permissions verified — a hardware or remote target is proven by an executed probe, never by an environment variable; see below
- Baseline test suite passes
- **Version control is live** — see below
- **Decisions in force are current** — see below
- **Every gate selector collects something** — probed with `--collect-only`, not assumed; see below
- **Calibration re-check** — review-scope, test-scope commands and roster recomputed from today's rules rather than trusted from the plan file; see below
- **The dispatch roster is declared** — every `Dispatch: YES` task, with its routed agent type; see below
- **Pre-existing `Review: skip` annotations are recorded** — the list, at the commit the run starts from; see below
- **Review scope is declared** — which tier the plan's diff warrants, and why; see below
- **Dispatch works in this session** — probed, not assumed; only when the roster is non-empty **and** the declared tier is `standard` or `high`; see below

**If any check fails, stop and report which check failed and how it failed.** Do not
proceed to Stage 1.

The procedure for each — the steps, the worked examples, the reasons behind them:
`references/preflight-checks.md`.

### Decisions re-check (the plan's snapshot can be stale)

The register **accretes between planning and execution**, so re-run the `decisions` skill's
`relevant` operation and diff it against the plan's `## Decisions in force`: a new entry in
scope, or a superseded one the plan honors, is surfaced before Stage 1; unchanged → one line;
no section → the scan result is the working set. A report, not a stop — unless it
invalidates a task, which returns the plan to `planning-projects`.

### Calibration re-check (the plan's ceremony can be stale)

Recompute the review-scope tier, the test-scope commands and the roster from today's rules
(`references/review-scope.md`, `../planning-projects/references/test-scope-tiers.md`, the
plan's `Dispatch:` fields), **time the stage-scope command at the baseline run**, and diff
against the plan's declarations. Unchanged → one line. Changed, or a stage-scope command over
~5 minutes → amend under the protocol, stating both values.
**What is never recomputed: the plan's facts** — tasks, `Test:` fields, gate checks'
substance, `Scope:` sets; recalibration changes only what the run *costs*. Procedure:
`references/preflight-checks.md`.

### Amending authored ceremony

An amendment is legal only when all three hold: **unexecuted checks only** (never a passed
gate's or an `[x]` task's — that edits the evidence), **the annotation cites the authorizing
rule**, and **the was-value survives**. Amending a check to make a *failing* gate pass is the
gate-failure procedure, not recalibration. Protocol:
`references/preflight-checks.md`.

### Gate-selector probe (a gate that cannot pass is a plan defect, not a gate failure)

For every gate check invoking pytest whose target file exists now, run
`pytest --collect-only -q <the check's selector>`. **Collects ≥1** → proceed. **Collects 0 and
no task creates that test** (or the target file does not exist and no task creates it) →
**plan defect**: stop and return it to `planning-projects` (§ When to revisit earlier steps).
**Collects 0 but a task's `Test:` builds toward it** → expected; record which task satisfies
it. A **command, not a dispatch**, so it is not tier-gated; its position is once at
Preflight, never per stage.

### Git bootstrap (hard prerequisite for commit-per-task)

Every task commits its own work (the Red-Green loop's rule 7), so a working
repo must exist before Stage 1. Not a repo → `git init`, a sane `.gitignore`, an initial
commit so the first task has a parent, then *offer* a remote — never push a repo public
without consent. On `main`/`master` → do NOT execute here; branch or worktree first (Safety
rails). Dirty with unrelated changes → surface them; don't sweep them into the first task's
commit. A missing remote is **not** a stop condition; only an un-initializable repo blocks.
Decision tree: `references/preflight-checks.md`.

### Dispatch roster and capability probe

1. **Enumerate the roster** — sweep **every task in the plan, across all stages**, and list
   each one whose `Dispatch:` reads `YES` with the agent name it routes to per
   `../dispatching-parallel-agents/references/stack-routing.md`:

   ```
   Dispatch roster (Dispatch: YES) — <n> of <total> tasks
     Task <N.M> → <agent name>
   ```

   A roster covering only the first stage is not a roster. An empty roster is a legitimate
   result — write `0 tasks`, so the absence is recorded as observed rather than as never
   examined.

2. **Probe the capability — only if the roster is non-empty and the tier is `standard` or
   `high`** (`references/review-scope.md` gates this like any other dispatch). Dispatch one
   throwaway `generalPurpose` subagent whose whole task is to reply `DISPATCH-OK`, and
   confirm it came back. Record the skip with its reason — `probe: skipped — empty roster`,
   or `probe: skipped — tier light`.

3. **Snapshot the `Review: skip` annotations** against the commit the run starts from
   (`Review: skip annotations at <base-sha> — <n> task(s): <Task N.M>, …`; `0 tasks` when
   there are none). The executor writes to the plan file throughout the run, so only an
   annotation in this snapshot is evidence the *user* authored it. Cite the snapshot when you
   skip, not the task line.

**A failed probe is a Preflight failure.** When dispatch is unavailable or disallowed in
this session and the roster lists at least one task, **Preflight fails and you stop** — the
user decides whether to enable it, re-plan those tasks as `Dispatch: NO`, or accept inline
execution knowingly. Substituting inline execution on your own authority is not a
resolution; it takes a decision that belongs to the user and makes it silently.

Why each of these three exists, and why the probe's condition is a conjunction rather than a
replacement: `references/dispatch-fidelity.md`.

### Review scope — the machinery scales to the change

**Declare a tier at Preflight and restate it in every gate report** (`review-scope: light —
prose edits to 3 skill files`). An undeclared run is `standard`. Pick it once, from the
plan's **cumulative diff**, not per task. **The declaration is what makes the choice
reviewable** — downgrading silently and openly produce the same diff.

**What the tier gates** is both review tiers, the gate evaluator (at a stage with Outcomes,
the demo), the close-out evaluator and `high`'s second pass. What it does **not** gate is the dispatch roster, the executor trailer,
the dispatched-vs-inline reconciliation, honest-gates disclosure, the class sweep every
surfaced bug requires, and the plan's own tests and gate checks: those run at every tier
including `none`. The line is cost — a mandate costing an
agent dispatch is tiered, a mandate costing a line of text is not.

**The format decides the review's SHAPE. The tier decides its DEPTH.** **Resolve a
disagreement by the risk floor**, not by taking the lighter or the heavier option: touching a
risk-listed area sets `high` whatever the size, and **size alone never escalates**.
**Risk-listed names a path a task's diff touches, never a project's subject matter**: a
`high` declaration that would bind more than a third of the plan's tasks is re-derived per
task (`references/review-scope.md` § Risk-listed names a path, not a project). A tier is
a floor, not a ceiling — escalate mid-plan when the diff turns out riskier than it looked and
say so in the gate report; never quietly de-escalate.

`references/review-scope.md` is the authority — the tier table, which tasks a `high`
declaration binds, the per-sub-plan rule for masters, and the opt-out rules.

## Phase 3 — Stage execution

For each stage in order:

### Step 3.0 — Test the stage's premise first, in the real environment

A stage opens only when every stage in its `**Depends on:**` has a fully `[x]` gate: run `python3 <planning-plugin>/skills/executing-plans/scripts/plan-progress.py --stage-order-check --stage <N>` from the repo root first; exit 2 is a Stop condition.

Every check after this point — tests, proofs, reviews — compares the code with the plan.
None of them can tell you the plan is wrong about the world. So before the first task, find
out whether it is.

1. **Outcomes.** A stage that delivers something to a person or another program but has no
   `**Outcomes:**` (a plan written before stages carried them) gets them now, from the Goal
   and the Research Summary, under its `**Goal:**`, marked `*(added at execution, <date>)*`.
2. **List what the stage assumes about things you do not control.** Read the Goal, the
   Outcomes and the **Risk** line. Each names something outside the code that must hold:
   the platform routes a request to this app, another app sends a certain input, a
   permission exists, an API or service behaves a certain way, a device has a capability.
   A HIGH Risk line is an assumption by definition.
3. **Check each one on the real environment, with what exists right now** — the attached
   device, the running service, the real CLI. Not the docs and not the code: one or two
   commands each, run before any code is written for it. Record them in the worksheet
   `python3 <planning-plugin>/skills/executing-plans/scripts/stage-brief.py premise --plan <plan> --repo <repo> --stage <N>` writes
   (`proof/<plan>/stage-<N>/premise.md`): one entry per assumption — what was checked, the
   command, what came back, and a verdict. Commit it with the stage's first task (with
   `proof/` local, it stays on disk); the `Stage N green` commit is refused without it.
4. **If one is false, stop** (§ Stop conditions, "The plan's premise is false"). Report the
   evidence and what it means for the Goal, and record the stop with `plan-state.py
   set-blocker` (`awaiting_owner_decision`). Do not build around it, and do not record it as
   a deviation: changing the plan is the owner's decision.
5. **If one cannot be checked here** (no device attached, no access), its verdict is
   `not checkable here — <why>`; carry on. The demo brief hands it to the evaluator.

A stage with no `**Outcomes:**` — nobody outside the code meets its result — has no premise
worksheet to write; steps 2–5 still apply to what its Risk line assumes.

### Step 3.1 — Identify what can run now

Scan the stage's tasks. A task is **dispatchable** when every task in its `Depends on` list is green. At stage start, this is every task whose `Depends on` is either empty or lists only tasks from already-green prior stages.

### Step 3.2 — Split by parallelism

- Tasks with `Dispatch: YES` and no file conflicts with another ready task → hand to `dispatching-parallel-agents`, concurrently
- Tasks with `Dispatch: YES` that modify files another ready task modifies → still dispatched, one after another
- Tasks with `Dispatch: NO` → work in the main session, always

**File-conflict check:** before dispatching, verify no two parallel tasks edit the same file.
If they do, **serialize the dispatches — do not inline either one.** A file conflict says
these two cannot run at the same moment, which is a different claim from "this task need not
go to a subagent"; the conflicting task is dispatched on its own once the first returns.

**A `Dispatch: NO` task runs in the main session.** The plan's `Dispatch` field is the whole
decision: `YES` obligates a dispatch, `NO` means inline. There is no executor discretion to
hand a sequential task to a subagent anyway — and none, in the other direction, to check
first: a `YES` is dispatched **without asking**
(§ The plan is the authorization — dispatch without a confirmation turn).

**If a `Dispatch: YES` task ends up inline, that is a deviation the user authorised.** An
unavailable dispatch *raises* the Stop condition, it does not resolve it — the choice that
follows is the user's. *"It seemed easier inline"* and *"I judged it unnecessary"* are not on
that list. Run it, say so in the gate report's dispatch line with the reason, and let
the trailer record `Executor: inline (dispatch failed)` or `Executor: inline (user
authorised)` — a bare `Executor: inline` on a `YES` task hides a silent downgrade.

**If the matched capability's plugin isn't installed**, don't fall through to `generalPurpose`
with no domain knowledge — resolve it from disk per
`../dispatching-parallel-agents/references/stack-routing.md` § *Resolving a capability whose plugin isn't enabled*. A Cursor install copies only the plugin folder, so no
`capability-index.json` is on disk beside it: the component's path comes from the routing
table's plugin and name, under `~/.cursor/plugins/local/<plugin>/` —
`skills/<name>/SKILL.md` or `agents/<name>.md`. Read and follow the SKILL.md, or dispatch
`generalPurpose` with the agent's body injected verbatim (Cursor chooses the model, so there
is nothing to carry across). If the file is not on disk either, do the work without it and say
so — never silently substitute a different skill. A component that needs hooks or a bundled
MCP server can't be lazy-loaded: stop and ask the user to install or enable that plugin.

Why there is no third execution mode: `references/task-execution.md`.

### Step 3.3 — Red-Green loop (per task)

Every task follows this loop. **The test is written first and must go RED for the right
reason before any implementation is attempted.** No task is "done" until its test is green.

```
 Write the test → Run it → RED for the named reason?
                              │              │
                              no            yes
                              ↓              ↓
              the TEST is wrong,        Implement → Test → Pass? ──yes──► Next task
              not the code —                        │
              repair and re-run                     no
              (not an implementation                ↓
               cycle)                            Diagnose → Fix → Retest
                                                    (max `Red-Green max cycles` per task)
```

A test written after the implementation cannot distinguish "the behavior is missing" from "my
test is wrong" — both print RED. **Repairing a wrong RED is not an implementation cycle** and
does not consume the budget, which bounds failed *fix hypotheses about the product*; repairs
are still bounded by honesty — never weaken an assertion to reach green (`honest-gates`).
**When the plan names a `pytest <file> -k <expr>` selector, name the tests to match it as you
write them.** The reasons behind all three: `references/task-execution.md`.

**Loop rules:**

1. **One fix per cycle.** Don't shotgun. Isolate, fix that one thing, retest.
2. **Diagnose before fixing, then fix the class.** Read the error, form a hypothesis, confirm it against the code, then write the fix. On the **second** RED cycle for a task, stop improvising and diagnose evidence-first: one failed targeted fix is bad luck, two says the hypothesis is wrong rather than the patch. Once the diagnosis holds, the repair is class-scoped — **A bug found during execution is a class** applies here exactly as it does at a gate, and a RED test is the earliest, cheapest place it fires.
3. **Respect the cycle budget** (plan-set, default 3). On exhaustion stop and escalate — three failed targeted fixes means the approach is wrong, not the implementation. If the user skips rather than re-plans, `backlog add` the task; don't silently drop it.
4. **Never skip the test — and never widen it into a regression sweep.** The task's Test field is the gate; "it looks right" is not green. It is also the **whole** of the task's testing: **do not run the plan's `stage-scope:` command inside a task**. The stage gate runs it once, at the gate. Widening within the task's own subject — the whole test file instead of one filter, or the class a fix touched — is task-scope and needs no permission; a genuine class sweep is likewise untouched.
4a. **On Cursor, proof is made once per stage, at the gate, by the `claim-verifier`
   (§ Host notes (Cursor), "Proof is made by the tool, once per stage"). Do not revert and
   re-run per task, run no proving tool before the Status flip, and put no proof record in a
   task commit** (the premise worksheet excepted). Why the rule exists — **prove it, one break per claim, on the
   host**: nothing in a finished artifact distinguishes a test written first from one
   transcribed out of the fix; both are green. So the verifier reverts the fix (not the
   test), re-runs the task's own `Test:`, sees it go RED, and lets `prove-claim.py claim`
   record it — for **every claim** of the task: on Cursor each claim needs its own record,
   and the commit gate refuses `Stage N green` without one per claim. A
   requirement may be recorded too — checkable → `prove-claim.py req`, else `prove-claim.py
   deviation`. Untiered (a re-run, not an agent's judgment), so it runs at every scope
   including `none` — **but never on a device, VM or instrumented suite**: the break is
   proved against the host-side test guarding the same line, or the device-only claim is
   recorded with `prove-claim.py deviation --claim`. A per-guard *battery* is for
   verdict-producing checkers, not product tests. Corollaries for the task itself:
   enumerate the population **as a command, before patching**; **build fixtures from the
   requirement, never from observed behavior**; and before writing a CHECKER rather than a
   test, ask whether the mechanism can decide the property at all. Why:
   `../honest-gates/SKILL.md` § *A test does not exist until its mutant dies*.

5. **Flip the task's Status to `[x]` the moment its test is green**, in the same change as the work — except for a plan the repo does not contain, where rule 7 says what happens instead. It is the authoritative done-marker; downstream tools (backlog unify) read it rather than guessing from gates or git. **The flip records that the task is done, never who did it** — an inlined task and a dispatched one write the identical `[x]`, so rule 7's trailer is the only artifact carrying that.
6. **Quick review gate (Tier 1) — `high` tier's risk-listed tasks and `Review: required` tasks only.** Whether it runs comes from `references/review-scope.md`; do not re-derive it. **At `none`, `light` and `standard` there is no per-task review**: a green task goes straight to its commit, and the stage's Tier-2 pass is where its diff is read. When it does run: after the test is green and Status is flipped but **before** the commit, dispatch `code-reviewer` (read-only) as a **fresh dispatch seeing only the task diff** — never the executor self-reviewing. A **Critical is blocking** (fix inline, sweep its class, re-run at fix-scope, re-dispatch — all against the same cycle budget); **Important / Suggestion are advisory**, appended to the plan as `**Review notes (Task N.M):** …` for the gate's deep review to triage. Trivial/non-code diffs skip it — but a docs change *asserting* a command, flag, exit code, default or path is not trivial. Full machinery: `references/task-execution.md`.
7. **Commit after each green task** (`"Stage 2 Task 2.3: parse config entries"`), including the work, any Tier-1 fixes, and — where this repo contains the plan — the flipped `Status: [x]`. The per-task commit is the unit of record and what makes a mid-plan stop recoverable. A passed gate adds its own `"Stage N green"` commit: keep **both** granularities, never collapse to one.

   **The plan file may sit outside the repo it plans** — a records resolver can
   put the records home outside the repo, in no git repository: edit the plan at its
   absolute path and run every git command from the repo root, never `cd` to the plan's
   directory first (a chained `git add` there dies on `fatal: not a git repository` after the
   plan edit landed). A plan outside the repo has its `Status: [x]` flip ride no commit
   (`references/task-execution.md`).

   **Every per-task commit ends with an executor trailer** — the last line of the message, taking one of these shapes:

   ```
   Executor: inline
   Executor: dispatched — <agent name>
   Executor: dispatched — <agent name>, <agent name>    (one task, several agents)
   Executor: inline (dispatch failed)                          (the body says why)
   Executor: inline (user authorised)                          (dispatch was available)
   ```

   **Keep the trailer to one physical line** — an unindented wrap ends the trailer block, so
   the trailer vanishes from every `%(trailers:…)` query with no error at all. Put the reason
   in the body; keep the trailer bare. **Name the actual agent that ran the work**,
   not the routing table's suggestion, and say so when a dispatch failed and finished inline.
   **A trailer that misstates who ran the task is worse than none** — it converts a visible
   gap into a false record. A routed agent that cannot commit does not become an inline task:
   the trailer records who did the work, not who typed `git commit`
   (`references/task-execution.md`).

### Step 3.4 — Propagate unblock

When a task finishes green, scan its `Blocks` field. For each blocked task, check whether ALL of its `Depends on` items are now green. If yes, it becomes dispatchable — return to Step 3.1.

### Step 3.5 — Stage gate

**These bind every gate**, restated rather than cited — a pointer to a rule goes unread:

> **A gate is green only when its real command ran in the current environment and actually
> passed. Nothing else counts as green.** **If you cannot make the real check run here, the
> gate is BLOCKED, not green** — one that ran and failed is RED, and takes the gate-failure
> procedure below. **Violating the letter of a gate is violating its spirit.** **And a
> sentence asserting behavior is itself a claim that something was verified** — cite the
> `file:line`. **Never collapse BLOCKED into GREEN.** **A gate whose commands ran over
> uncommitted edits proves nothing about what the branch records** — commit first, then
> run it. A BLOCKED gate takes neither branch: stop on it, name the blocker and the exact
> command that cannot run, try to unblock it, and escalate — and **write the checklist item
> as `- [~]`, never `- [x]` with a note explaining it away.** `[~]` is the gate checklist's
> BLOCKED state and it parses everywhere the plan tooling reads; a ticked box carrying
> *(amended — exit 2)* is a GREEN check to every reader, so the plan reads as finished.
> Prohibitions: `honest-gates`.

When every task in the stage is green, run the stage gate:

- Run each check against its specific pass criterion, in order; stop at the first failure
- **On Cursor, proof comes last.** The checks, the reviews, the demo (its brief from
  `stage-brief.py demo`) and their fixes first; then one `claim-verifier` dispatch on the
  final staged tree; then `git add proof/` and `Stage N green`, which the git hook refuses
  without every task's records and, where the stage needs them, its `premise.md` and
  `demo.md` (§ Host notes (Cursor), "Proof is made by the tool, once per stage")
- **Regressions check runs at stage-scope on intermediate gates:** cheap host-side checks in full, expensive suites (device/instrumented/e2e) restricted to the modules the stage's commits touched — never `clean`. Use the plan's declared `stage-scope:` command when its Preflight carries a "Test-scope commands" block; when the full suite is cheap (<~5 min), just run it in full. Policy: `../planning-projects/references/test-scope-tiers.md`.
- **The final stage's gate runs at plan-scope**, together with close-out — the plan's one full clean pass.
- **A review or remediation fix re-runs at `fix-scope` — never the full suite or the
  stage-scope command**; the gate stands on that plus the recorded stage-scope result
  (`references/stage-gate.md` § *A review fix does not re-earn the full pass*). Never re-run a
  passed tree (`test-scope-tiers.md` § *Outside a plan, and proven trees*).
- **The record audit runs at every stage gate:** `python3 <planning-plugin>/skills/executing-plans/scripts/plan-flip-audit.py <plan> --repo <repo-root> --require-all-checks`
  — exit 1, a `blocking` finding, fails the gate. Exit 2 is an error to fix first; name each
  `advisory` finding (exit 4) in the report; exit 3 means a check could not run, and the
  report carries its coverage line (§ Host notes (Cursor), "The record audit").
- A scoped gate report states what scope actually ran (honest-gates disclosure) — e.g. "gate green — stage-scope: `:payments` instrumented + full `check`."
- **The gate report states the stage's dispatched-vs-inline counts, and a reason for every inlined `Dispatch: YES` task** — read off the executor trailers rather than from memory, and reconciled against the roster Preflight declared. A stage that dispatched all it marked still says `dispatch: 4 of 4`; silence is never interpreted. **An empty trailer value is `unknown`, never `inline`.**
- **The gate report names every review that ran, the agent that ran it, and the diff it saw** — and, for one that did not, which of the **three** reasons applies: the declared tier never mandated it (a *scope* statement, needing no excuse), or, where the tier did mandate it, an evidenced opt-out or a trivial/non-code diff. Never report a tier-scoped absence as an opt-out. Name the agent by a type dispatch can actually take — `goal-evaluator` is a **role**, not a registered agent.
  **A mandated review the executor ran itself is a substitution, not a review**, legal only
  where the **user** authorised it — an undispatchable reviewer is a Stop condition, not a
  licence. The review line records it, quoting them; **with no recorded reason the gate
  fails.** Bound: only reviews the declared tier mandates, never a dispatch beyond
  it — and within it, the mandate IS the authorization to **dispatch** it.

- **One `ACTION NEEDED:` block, or none** — a report that carries one does not also say it is proceeding. Either the decision blocks the next stage, so say so and stop, or it is not an ask at all (`references/stage-gate.md`).

**Platform stage-verify hook.** After the stage's own gate checks pass, **if the project's
platform ships a stage-verify skill, invoke it as the final gate step** — it proves the stage
on the real artifact, not just the test suite; a failure there is a gate failure. Find it
among installed skills by a description matching the project type (Android: `settings.gradle`).
Brief it with the gate's tier: stage-scope at an intermediate gate, the full device suite at
the final one — and that run **is** the plan-scope pass's device portion, not an addition to
it. No matching skill installed → note it; that is not itself a gate failure.

**A redesign stage carries the design-fidelity hook** in the same position — the
`applying-design-handoff` fidelity verify loop, graded by a separate evaluator; if the tier
does not fund that evaluator, **the hook does not run and the gate report says so**.

Exact report shapes, both hooks' full procedure, the evaluator's briefing, and the Tier-2
pass: `references/stage-gate.md`.

**Reviews reading the same diff are dispatched together, not in sequence.** A gate's Tier-2
pass, `high`'s second pass and the gate evaluator (or its demo of the committed build) depend
on none of each other's findings — one batch, one triage, one round of fixes. Only what reads a
*different* artifact stays sequential: Tier-1 (one task's diff, pre-commit) and the close-out
evaluator (the finished plan). Why:
`references/stage-gate.md` § *Same-diff reviews go out together*.

**Independent evaluator for non-command checks.** **Whether it runs comes from
`references/review-scope.md` — do not re-derive it**: never at `none`, at `light` and
`standard` when the gate carries a `(judgment)` check or its stage has `**Outcomes:**`,
always at `high`. Run command checks yourself; dispatch a fresh evaluator for the judgment
checks, briefed ONLY with the plan goal, the stage goal and the gate's pass criteria — never
the transcript or your own summary. **At a stage with Outcomes it is a demo** of the built
product as its user meets it, briefed by `stage-brief.py demo`, never reading the diff. The session that wrote the code grades its own work too generously. A declared tier that does not
mandate one is **scope**, reported as such and never as an opt-out; an evaluator that cannot
be dispatched is a Stop condition, not a skip.

**Brief it to grade by severity, not just pass/fail** — **Blocking** (the goal in scope is
not met; the gate does not pass), **Material** (real defect, goal still met — fixed, its
class swept), **Minor** (nit; recorded in the gate report and the handoff note, never
blocking). **Tell it explicitly that a FAIL carrying no Blocking finding is a pass with
recorded residuals**, or it will withhold PASS to seem rigorous and hand the loop an
unsatisfiable condition: a fresh judgment agent reading a real artifact essentially always
finds *something*, so "no adverse findings" is not a reachable state to wait for. **A
Material fix is proven at fix-scope without re-dispatching the evaluator; re-dispatch is
owed only to a Blocking fix** (`references/stage-gate.md` § Independent evaluator for non-command checks).

**Deep code review (Tier 2).** Whether it runs, and at what shape, comes from
`references/review-scope.md`. It is a gate criterion, not advisory — a **Critical** here is a
**gate failure**, and every **Important** leaves the gate **fixed** per the exit criterion,
its class swept. **Brief it to audit the stage's behavioral claims as a set**: the stage
view is where a claim that was true when written and false after a later task shows up.

**Decisions-conformance check (gate criterion, not advisory).** Run it at the **final** stage
gate and at close-out, over the plan's cumulative diff — not at every intermediate gate. A
contradiction is a **gate failure wherever it is found**; what is scoped to the
final gate is the *sweep*, not the rule, so an intermediate stage that knowingly lands one
raises it when it sees it. Two legal resolutions, and only two: **re-scope the change**, or
**record a deliberate supersede** (the `decisions` skill's `supersede` operation) and cite `Supersedes DEC-NNN — <why>`
on the task. "The decision seems outdated" is not a third option. State **which IDs were
checked against which parts of the diff** rather than asserting blanket conformance.

**Exit criterion — what "the gate passed" means.** This governs **every** gate pass, not only
one reached by repairing a failure:

> A gate passes when **no Critical finding remains** and **every Important finding is
> fixed**, its class swept under the class-sweep rule. Suggestions are **recorded in the gate report and carried into the stage handoff
> note**, never blocking.

**Findings are not the only way a gate fails.** The platform stage-verify hook, the
decisions-conformance sweep and an unrecorded review substitution each fail it on their own,
whatever the finding list says.

**A defect is fixed. The backlog is for what is not a defect** — a significant improvement, or
a decision the user must make. A defect you genuinely cannot fix here **escalates with its
blocker named**, and that valve is evidenced, not asserted. It is deliberately *not* "the
detector returned silent": a fresh judgment agent never reports zero findings, so a gate with
that exit condition is not a gate but a loop. Dispositions, the measured backlog
drift, and what a scope guardrail actually bounds: `references/stage-gate.md`.

**If the gate fails:** a gate is one caller of **A bug found during execution is a class**,
and the sharpest one — detection at a gate is goal-scoped while repair defaults to
instance-scoped, so a class with N instances costs about N rounds, each looking like fresh
news.

1. **Classify every finding** as **Critical**, **Important** or **Suggestion** — the same
   scale the review tiers use, so a gate finding and a review finding are graded once.
2. **Run the shared rule: diagnose evidence-first, then name the set.** Diagnose
   evidence-first before generalizing; derive the set from the failing task's `Scope:`
   field where it declares one, enumerate it with a command, and **write the command down**
   in the gate report. A set derived from a wrong root cause is a wrong set, swept
   confidently, reporting green.
3. **Add a test covering the set**, not the one file that failed, and fix **every member the
   sweep returns in this round**.
4. **Re-run the task's Red-Green loop**, then re-verify narrowly plus the sweep.

**Remediation budget — default 2 rounds per gate.** A plan may override it, and the gate
report states the count. **Required verification belongs to the active round.** A separately initiated
critique reserves new work; an unread redesign's owed review does not.
**Before dispatching a further round, run `python3 <planning-plugin>/skills/executing-plans/scripts/plan-progress.py --budget-check` from the repo root** (the repo root as the working directory, the plugin path as the argument: they are different directories, and an exit 2 with no `budget_exhausted:` on stderr is a **broken invocation** — fix the path and re-run) —
untiered, a command not a dispatch, read-only; read it by what it printed
(`references/gate-failure-procedure.md` § The read-only budget projection). V2 reads validated completed/active accounts:
finish authorized active work at the ceiling; admit new work only via begin-round.
`budget_exhausted` is a Stop condition: escalate the residual list. `state_error`
requires instrument diagnosis, never permission or proof of exhaustion. Strategy
assessment grants no round; original extensions survive restart. Mechanics:
`references/execution-state-contract.md`; repair bounds: `references/gate-failure-procedure.md`.

**If the gate passes** — no Critical remains, every Important is fixed, and no
finding-independent condition is outstanding — mark the
stage complete, append the stage's handoff note to the plan,
commit with `"Stage N green"`, and start Step 3.0 for the next stage. The gate report states
the remediation rounds spent, every Suggestion recorded, and any finding escalated rather than
fixed, so "green" never reads as "nothing was found".

---

## Context resets at stage boundaries

Long executions degrade and compaction loses unpredictable detail; structured resets beat
degraded context, and the plan file is already the handoff artifact.

- **Stage gates are the reset points.** After each gate passes, append a handoff note to the
  plan file under the stage: the deviations, surprises and decisions a fresh context needs
  that the Status flips don't capture, plus — copied verbatim from the gate report, not
  re-derived — its `dispatch:`, `review:` and `residuals:` lines and the **Decisions in
  force** still binding. **The dispatch and review lines are carried here for the same
  reason**, and they earn the space: the dispatch counts can be rebuilt from the trailers, but
  **the review ledger cannot** — which agent saw which diff exists only in the gate report.
  Committed with the `"Stage N green"` commit. **The plan file gets the handoff note only
  (~15 lines); the gate report itself goes in the `"Stage N green"` commit body, never into
  the plan**
  (`references/stage-gate.md` § The plan file is read whole; exact shape there too).
- **Stop on a stated rule, never by eye.** Elsewhere a script measures the context after
  each gate commit (`context-usage.py`). It does not ship on Cursor: no store Cursor writes
  records the context a session uses, so the measured rules — **context**, **dead weight**,
  **sub-plan boundary** — give no verdict here, and the owner's rollover request through a
  supervisor is not carried either. On Cursor only the **dated wait** rule hands off, which
  writes `RESUME HERE` and `phase: "handoff"`; the `handoff` phase is also what releases the
  `stop` hook. No rule fires before a gate, and a stop with no rule named is not a legal
  stop (`references/session-handoff.md`).
- **Resuming fresh:** a new session reads the Research Summary, `Status:` flips, handoff
  notes and the last `RESUME HERE` block — never by needing the prior transcript.

---

## Progress state file (live statusline bar)

**Every run is owned: `scripts/plan-state.py` alone writes
`<repo-root>/.claude/plan-progress.json`, and only `init` starts a run.** Call `init` when
Preflight starts, on the run's branch (it owns the run); `transition` when a task starts, a gate runs and close-out starts;
`begin-round` / `record-verification` / `complete-round` around a remediation round;
`set-blocker` on a Stop condition or a handoff; `finish` as close-out's last step. The
payload is JSON on stdin, with `--expected-revision` (the last receipt's; 0 for `init`)
and a fresh `--operation-id`; a retry returns the original receipt. Payloads per point:
`references/progress-state-file.md`; the contract: `references/execution-state-contract.md`.
Never edit counters or delete the snapshot by hand: `finish` retains terminal evidence.
Readers do not grant authority. Explicit migration needs original legacy evidence.
Keep these private files gitignored.

---

## Stop conditions

Stop immediately and escalate to the user when:

- Preflight fails
- A task exhausts its Red-Green cycle budget
- A stage gate's remediation budget is exhausted — the responsible task(s), or the defect class they belong to, were re-run and Critical findings remain (escalate with the residual list)
- The plan contains an instruction you don't understand
- A test cannot be run (missing fixture, unreachable service, unclear invocation)
- **A mandated verification or dispatch cannot be performed** — dispatch is unavailable or disallowed and Preflight's dispatch roster is non-empty (§ Dispatch roster and capability probe), or a review the gate requires cannot be run. Substituting inline execution, or proceeding unreviewed, is not a documented resolution; asking is
- Verifying the test requires modifying shared infrastructure (production DB, live service) — see Safety rails
- **An Outcome cannot be met or shown as written** — a task or the demo finds it unreachable or wrong. Report it (`ACTION NEEDED:`) with the evidence and the options, and record it with `plan-state.py set-blocker` (`awaiting_owner_decision`): the Stop hook reads the snapshot, not prose. Do not drop or reword it yourself: `Stage N green` is checked against the Outcomes recorded in the Step 3.0 worksheet, and a change stands only with the owner's words quoted in its amendment note (`owner, <date>: "<their words>"`)
- **The plan's premise is false** — Step 3.0, a task or the gate's demo shows that something the stage's Goal, Outcomes or Risk relies on does not hold in the real environment. Report the evidence (`ACTION NEEDED:`), what it means for the Goal, and the options you can see, and record it with `plan-state.py set-blocker` (`awaiting_owner_decision`). Building around it, or recording it as a deviation, is not a resolution: the plan is the owner's to change

**Read the plan's `## Owner decisions` before you ask** — a sub-plan's, and its master's.
Planning asked the questions it could foresee. An entry naming this case — this command,
this stage, this choice — is the owner's answer: act on it, cite its `OD-N` in the commit
or the report, and do not ask again. An entry covers only the case it names, never a wider
one: it applies only when every qualifier of its `applies to:` holds. One naming another
task, stage or command, or one the plan does not have, does not apply; never reinterpret it
to fit. `ask at execution` is no answer. A case no entry names stops and asks.

**Never guess through a stop condition.** Ask.

**Equally: never ask through a dispatch the plan mandated.** These conditions fire when a
mandated dispatch *cannot be performed*, never when you are merely unsure — the plan answers
that (§ The plan is the authorization — dispatch without a confirmation turn). Why the choice
is the user's: `references/dispatch-fidelity.md`.

## When to revisit earlier steps

Return to Phase 1 (critique) when:

- The user updates the plan after feedback — treat the new version as a fresh plan and re-critique
- A stage gate failure reveals a fundamental gap in the plan (e.g., missing task, wrong dependency) — stop execution, return to `planning-projects` to revise
- A mid-execution request for new work arrives ("what else can you implement?") — it goes
  through `planning-projects` triage before any of it is implemented (Direct for a one-liner,
  a Light plan otherwise), and such work does not share the plan's branch or its gate

## Phase Close-out — After the last stage

When every stage is green: run the plan's **sole plan-scope pass** (the only `clean` in the
whole execution), the tier's remaining review and evaluator passes, the version bumps and
their mirrors, the plan's closing note, the backlog and decisions reconciliation, the
decisions-conformance sweep, and the workflow-spec audit — then report, and carry out the
merge the plan's owner decisions record or offer merge options.
**Do not merge without explicit confirmation** — an owner decision naming the merge is one.

Ordered procedure, and what the report must contain: `references/close-out.md`.

---

## Safety rails

- **Never start on `main` / `master` without explicit user consent.** Use a feature branch or worktree.
- **Destructive commands** (schema migrations, data deletes, force pushes, production deploys) — confirm before running, even if the plan (a task, gate check or close-out step) says to; an owner decision naming that command (§ Stop conditions) is the confirmation.
- **Secrets** — if a task would read or write credentials, stop and confirm the mechanism (env var, secrets manager) with the user before proceeding, unless an owner decision names it.
- **Shared infrastructure** — staging/prod-adjacent changes get confirmation per stage, not per plan; an owner decision naming the stage is that confirmation.
- **The host's own footing** — never reconfigure the agent host's own network interfaces,
  routes or DNS to reach a device under test; use a second interface, a spare client, or a
  subagent on another machine, and if none is available the gate is BLOCKED. Generalizes to
  anything the session depends on to keep running: an agent that severs its own control
  link cannot report that it did.

---

## Sources and rationale

What each source is load-bearing for: `references/sources.md`.

## Integration

This skill routes to `planning-projects` (which produced the plan),
`dispatching-parallel-agents` (every `Dispatch: YES` task), `backlog` and `decisions` (at
close-out), `workflow-spec` (the close-out audit), the `code-reviewer` agent (both
review tiers) and a fresh agent in the goal-evaluator role (gate and close-out). What each is
for, on what condition it fires, and the **Review opt-out** rules: `references/integration.md`.

---

## Host notes (Cursor)

- **Delegation is native.** Cursor's subagent tool is `Task`, and several `Task` calls in one
  message run concurrently — dispatch all ready tasks together. An agent is addressed by its
  **bare name** (`code-reviewer`, `claim-verifier`, `architecture-researcher`,
  `design-handoff-reproducer`, or the name the session lists for another plugin's agent):
  Cursor has no plugin namespace. Read `<agent name>` throughout this skill as that bare name.
- **Cursor chooses the model.** An agent file carries no model, and no dispatch names one;
  read any tier language here as review *depth* or the agent's *role*, never as a model.
- **Reviews.** The `code-reviewer` agent ships in this plugin; how to address it, and what
  the tiers mean here: `references/review-scope.md` § Host notes (Cursor).
- **Tracking tasks.** Keep a plain checklist in your working notes wherever this skill
  says to keep one.
- **Silence is how you continue.** On Cursor an assistant message with no tool call ends the
  turn, and the run waits for the user: the moment you narrate "Continuing Stage 3…" and
  stop there, the run has stopped. Run-to-completion forbids *asking* between green tasks;
  here it also forbids *narrating* in place of the next call. Between a per-task commit and
  the next task's first tool call, write no user-facing text at all. Progress goes to
  `.claude/plan-progress.json` and the plan's `Status:` fields, which is where a fresh
  session reads it anyway. A summary that ends "say if you want me to continue" is a stop,
  however much it reads like an update.
- **A background job's return is not a turn boundary.** Cursor delivers a finished
  background task with an instruction to inform the user of its result; obeying that
  literally ends the turn. Fold the result into the plan and keep going, and report it in
  the stage gate report where it belongs.
- **The `stop` hook is a backstop, not a licence.** `hooks/hooks.json` runs
  `plan-continue.sh` on Cursor's `stop` event (`loop_limit: 25`). It fires only in an
  interactive session — a headless `cursor-agent -p` run has no backstop — and it resumes a
  run that ended anyway; it does not make ending one free. Every hook ships on the plugin
  route only; the `hooks` skill (`/hooks`) explains and checks them. If the Claude Code
  planning plugin is also installed, Cursor runs its hooks too, and each of them exits
  quietly on Cursor's payload, so only this plugin's hooks answer.
- **Progress state file.** The state-file writes apply at every transition. Cursor **can**
  draw the bar, because its CLI runs a configured `statusLine` command on each conversation
  update: wire it with `/plan-statusline install`, and tell the user first that a custom status
  line **replaces** Cursor's own footer rows rather than adding one
  (`references/progress-state-file.md`). The band and plan pane are a Claude Code mod and do
  not exist here.
- **The record audit.** `plan-flip-audit.py` reads git history for findings 1, 3 and 5, and
  a plan kept outside the repo has none. So take its baseline when a plan loads, before
  anything is ticked: `python3 <planning-plugin>/skills/executing-plans/scripts/plan-flip-audit.py
  <plan> --snapshot --repo <repo-root>`, and pass the same `--repo` to every later run. It
  works before the first commit, so take it before the git bootstrap. **Never re-snapshot
  mid-run** — the script refuses, because a second baseline launders every flip since the
  first. **Resuming a plan is a load too**: a session that picks up an in-flight plan never
  passes Phase 1, so before its first task take the baseline if none exists (it records how
  many boxes were already ticked, so a late baseline shows as late) and run the audit with
  `--require-all-checks`. A blocking finding stops the run before the next task — unless a
  not-yet-done task in the plan is there to clear it, named in the progress note; the
  stage gate's own audit is not excused either way.
  **Exit codes.** 1 a **blocking** finding — a RED gate, never a note; 4 advisory findings
  only — each named in the gate report with the heuristic that matched and why it does not
  void the tick, never deleted silently; 3 (with `--require-all-checks`) nothing found but a
  check could not run — record the coverage line in the gate report ("plan-flip-audit: no
  findings; checks 1/3/5 NOT RUN (no baseline)"), and never drop the flag to turn 3 into 0;
  2 the audit itself failed — fix the invocation and re-run, and report no gate while it
  exits 2. Findings 8 and 9 run only with `--repo`.
- **An owner decision is ticked with the owner's words.** A box whose claim is the owner's
  decision ("Owner confirms …", "user approves …") is ticked only after you asked and were
  answered, with the answer appended: `*(owner, <date>: "<their words>")*`. Finding 6 is a
  RED gate on a tick without one. An owner *action* whose result a command proves needs the
  command's output, not a quote.
- **An amendment sweeps its old value.** When an amendment replaces a value
  (``was: `<old>` ``), search the whole plan for the old value and update every other mention,
  or mark it historical. Finding 7 lists the survivors; name each in the gate report.
- **Proof is made by the tool, once per stage, at the gate.** A `mutation:` or `req:` line is
  the executor's word about its own work, and no gate can audit it, so claims are proven by
  a tool. Proving after the gate's fixes proves the code that ships, once; proving per task
  would re-prove after every review fix.
  0. **Once per plan, when it loads,** run `python3 <planning-plugin>/scripts/hooks-install.py
     --install --repo <repo-root>`. It installs the proof-record git `reference-transaction`
     hook (`hooks/git-ref-gate.sh`) in the project; git runs it whenever a branch moves —
     `--no-verify`, amend, cherry-pick and plumbing included. If another
     reference-transaction hook is already there, the installer refuses: ask the user.
     Cursor's `beforeShellExecution` hook (`hooks/commit-gate.sh`) keeps it installed while
     a plan is in flight. The gate is on by default.
  1. **Tasks commit code only.** Green task → commit, as Step 3.3 says. No verifier, no
     records, nothing under `proof/` but the premise worksheet, no re-proving when a later task or a review fix touches
     the same code. The git hook does not gate task commits.
  2. **At the gate, prove last.** Run the gate's checks, reviews and demo first, and land
     their fixes. Then stage the final tree and dispatch `claim-verifier` **once**, briefed
     with the plan path, the stage number, the stage's base commit (the previous
     `Stage N green`, or the plan's first commit) and the build command — nothing else from
     this conversation. For every task of the stage it breaks **every claim** of the task
     (the plan's named break where the claim says `(red if …)`) and runs
     `prove-claim.py claim`, which writes a record only when it watched the test pass, go RED
     under the break, and the tree come back exactly. It records requirements with
     `prove-claim.py req` or `deviation` as rule 4a says. A claim no repo patch can break (a
     device, the network, a person) is recorded with `prove-claim.py deviation --claim K
     --why …`: a valid record, disclosed, never proof.
  3. On **NOT VERIFIED**, fix the test or the code — never the plan's wording to make a
     claim easier — stage, and dispatch the verifier again for the tasks that failed. A
     deviation needs the user's say-so or an annotated plan amendment; report each one.
  4. `git add proof/`, then commit `Stage N green`. The git hook refuses that commit while a
     task of the stage lacks its records for the commit's own tree, and lists what is
     missing; for a stage with Outcomes it also reads `proof/<plan>/stage-N/premise.md` and
     `demo.md` from that tree. A `Stage N green` commit rebased or cherry-picked onto
     another tree needs re-proving.
  5. Then run `plan-flip-audit.py --repo <repo-root>`. Its findings 8 and 9 read the committed
     records; on Cursor they skip the stage in flight until its `Stage N green` exists,
     because that is where its records land.
- **What the verifier cannot judge for you.** A value the plan says to take from somewhere
  (a pin, a path, a version) is *read* from there in code, never copied — a copy drifts the
  first time the source changes. A claim that something rebuilds, regenerates or caches is
  proven by changing each input it reads and watching it rerun. A requirement that can break
  without the planned `Test:` going RED gets a check that would catch it — keep the planned
  `Test:` too — and that check is the requirement's evidence. Before committing a task that
  introduces a path, a name or a behaviour later tasks depend on, search the later tasks,
  gates and rollbacks for those names; match them, or amend the plan in the same commit
  with a `was:` note.
- **Commits on Cursor.** The per-task commit (Step 3.3 rule 7) is not conditional on the
  user asking for it. A standing *"don't commit unless asked"* caution is conditional in
  exactly the way the dispatch caution is (§ The plan is the authorization — dispatch without a confirmation turn): the plan under
  execution is the request, so approving the plan authorized the commits it specifies. A
  mid-plan stop is recoverable only as far back as the last commit. **The bound:** with no
  plan in flight the caution stands and you ask.
