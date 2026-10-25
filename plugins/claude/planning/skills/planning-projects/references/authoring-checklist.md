# Pre-presentation checklist — the full item list

`../SKILL.md` § Checklist — Before Presenting the Plan carries the imperative (run every item)
and restates five of them — **the five a command decides rather than a reading**. This file
is the list itself.

Most items name the section that owns the rule they enforce, so a failed item is fixed at its
source rather than argued with here; a few name the reference file that owns it instead, and
the rest name no owner: four Standard items (one of them names only its validator), whose
rule lives in `../SKILL.md` § Task and stage fields; three master items, whose rule lives
in `master-plan-format.md`; and six Light items, owned by the Standard item each one
mirrors or by `light-plan-format.md`. The checklist is a **sweep**, not a second
definition site: nothing here introduces an obligation the trunk does not already carry.

## Checklist — Standard plans

Run every item before showing the plan to the user.

**Structure**

- [ ] Every task has a concrete, runnable test — no "it should work" tests (`../SKILL.md` § Phase 3 — The Red-Green Loop)
- [ ] Each `Test:` asserts the outcome the task promises, not a side effect of it; each claim would go red if false, with the break named where it is not obvious; a task that prepares something for later tasks tests that the preparation is there (`../SKILL.md` § Phase 3; `task-fields.md` § `Test:`)
- [ ] No task re-does what execution's Preflight does — no `git init` task (`../SKILL.md` § Phase 1 — Preflight)
- [ ] Tasks within each stage follow their dependency order
- [ ] No task depends on something from a later stage
- [ ] Every stage has a risk flag with a reason (`task-fields.md`)
- [ ] Every stage whose result a person or another program meets has `**Outcomes:**`: who, what they get when it works, and what they see for each way it can fail; every promise in the Research Summary lands in some stage's Outcomes (`../SKILL.md` § Phase 2 — Stage Breakdown)
- [ ] Every stage has a rollback note (`task-fields.md`)
- [ ] Every stage has a gate with specific checks (`../SKILL.md` § Phase 4 — Stage Gates)
- [ ] No stage has more than 7 tasks (`../SKILL.md` § Stage sizing)

**Gate checks**

- [ ] The final gate of the last user-facing stage has one gate check that exercises the running artifact, driveable by the session itself; no intermediate gate repeats it, and no gate check depends on a person outside the session (`../SKILL.md` § What a stage gate checks)
- [ ] Every `(judgment)` line names what a reader decides that no command can; the plan carries as few as that allows — each buys an evaluator dispatch (`../SKILL.md` § Write a set-valued check as the sweep that proves it)
- [ ] A `review-scope: high` declaration names, per bound task, the risk-listed path its diff touches, and binds no more than a third of the plan's tasks — otherwise it is `standard` with `Review: required` on the tasks that genuinely qualify (`../../executing-plans/references/review-scope.md` § Risk-listed names a path, not a project)
- [ ] Every gate check asserting a property of a **set** is an executable sweep over that set, or carries the `(judgment)` marker naming why a reader must verify it, or — where one artifact genuinely *is* the whole set — the `(scoped)` marker saying why. No check names one artifact where the goal is a property of many, and none is widened past the set its claim is over, which produces a check that cannot pass at all (`../scripts/validate-gate-checks.py` reports zero INSTANCE-SHAPED; `set-valued-checks.md`)
- [ ] A sweep that forbids a call matches the bare name at a word boundary, not one qualified spelling an import can bypass (`../SKILL.md` § Write a set-valued check; `set-valued-checks.md` § The fifth error)
- [ ] **One owner per fact**: no gate check re-proves what a task's `Test:` already decides, unless it sweeps a strictly wider, nameable set; and no `(judgment)` line restates a fact an executable check in this plan already answers (`../SKILL.md` § Every fact has one owner)
- [ ] **Every gate check can fail in the direction its hazard runs.** For each set-valued check, name what the defect would look like in the tree: an unwanted presence is a new line and an allow-list sweep catches it; a *missing* call adds nothing for a grep to find, so it needs an invariant asserted over every operation — a test the gate runs, not a sweep of the sites the plan chose. No validator can tell these apart, because the syntax is identical and only the hazard differs (`set-valued-checks.md` § The third error)
- [ ] A gate check over what a commit range changed (`git diff --name-only <base>..HEAD`) leaves out the files the executor commits itself — `proof/` records and any `.gitignore` git bootstrap writes — or it fails on the run's own bookkeeping
- [ ] A task that adds a member to a closed set (an enum, event list, migration count, snapshot baseline) updates every test that pins that set, in the same task (`task-fields.md` § `Test:`)
- [ ] **The plan's goal is a check from the first gate**: every gate from the first one whose artifact exists carries a `(goal)` check sweeping the plan's goal over the whole artifact, never a subset by category — `../scripts/validate-gate-checks.py` reports zero GOAL-CHECK-MISSING, and any FILTERED-SUBSET note on it is answered. The validator checks presence, not placement: zero means some gate carries one, so placement from the first gate is checked here by the author (`gate-authoring.md` § The plan's goal is a check from the first gate)
- [ ] **Every gate check can pass as authored**: `validate-gate-checks.py` reports zero SELECTOR-UNMATCHED — every `pytest <file> -k <expr>` selector in a gate is one some task's `Test:` builds toward, so no gate names a filter that collects nothing (such a gate cannot pass, and nothing else finds that before execution; `executing-plans` re-checks it at Preflight with `--collect-only`, where the tests actually exist)

**Research and Preflight**

- [ ] The research summary has actual findings, not placeholders (`../SKILL.md` § Research summary)
- [ ] Preflight checks cover all tools, deps, and access needed by the plan, each checked where the build looks for it rather than at an assumed path (`../SKILL.md` § Preflight checklist)
- [ ] If the project's full suite is expensive (>~5 min): the plan declares its stage-scope and plan-scope commands, only the final gate runs the full clean pass, and any single test >~2 min is quarantined behind an opt-in filter (`test-scope-tiers.md`)
- [ ] The declared stage-scope command runs in under ~5 min — the trees the stages touch or depend on, not every tree the project owns; a stage-scope that is the full suite renamed pays plan-scope cost at every gate (`test-scope-tiers.md` § A declared stage-scope command is subject to the same cost threshold)

**Task fields**

- [ ] Every task that changes more than one artifact carries a `Scope:` naming that set, derived from a command that was actually run rather than recalled; single-artifact tasks correctly omit it, except a `Dispatch: YES` task, which always carries one (`../SKILL.md` § Task and stage fields)
- [ ] Every task has both `Depends on` and `Blocks` fields — and they're symmetric
- [ ] Every path, directory or API that a later task, gate check or rollback names is named in the task that creates it (`../SKILL.md` § Task and stage fields; `task-fields.md` § Names other tasks rely on)
- [ ] Every task has a `Dispatch` field (YES/NO) consistent with its dependencies — `../scripts/validate-dispatch.py <plan>` exits 0
- [ ] No two parallel tasks modify the same files (`../SKILL.md` § Phase 5 — Dispatch)
- [ ] On an expensive-suite project (>~5 min), every task's `Test:` is path- or suite-scoped, or the task carries `full-suite: accepted` with a reason — an **authoring-time** check, run once per authored plan and never per execution turn (`test-scope-tiers.md` § A task-level `Test:` is task-scope only when the author scoped it; `../scripts/validate-gate-checks.py` reports zero TASK-TEST-UNSCOPED)

**Where it lands, and what it reconciles**

- [ ] The plan is saved to the project's `<records home>/plans/`, resolved through `lib/records_home.py --for-write`; exit 2 stopped the save and created nothing (`../SKILL.md` § Output location)
- [ ] Open backlog items in scope were reviewed; folded-in items carry a `Closes BL-NNN` reference on the task that closes them (`../SKILL.md` § Backlog scan)
- [ ] Workflow specs in scope were read; any altered or removed behavior is declared on the corresponding task (`Changes WF-NNN` / `Removes WF-NNN`); new flows have a capture/extend task (`../SKILL.md` § Workflow-spec scan)
- [ ] If an architecture doc exists for this topic: every structure-creating task cites its ARCH-ID, the final stage gate carries the architecture-conformance check, and no task contradicts an approved ARCH section (`../SKILL.md` § Architecture doc scan)
- [ ] The decisions scan ran and its result is written into `## Decisions in force` (including the explicit `none — registers consulted: …` form, and `project register: absent` on a new project); tasks constrained by an entry cite it (`Honors DEC-NNN`), any deliberate override cites it (`Supersedes …— <why>`), and the final stage gate carries the decisions-conformance check (`../SKILL.md` § Decisions scan)

## Additionally, for a decomposed project (master plan + sub-plans)

- [ ] The decomposition trigger actually held (`../SKILL.md` § Phase 2.5 — Decomposition decision (master plan + sub-plans)) — 2–7 sub-plans, each independently executable
- [ ] Register `Depends on` / `Blocks` fields are symmetric across sub-plan entries
- [ ] Every register entry ends with a `**Gate:**` block containing at least one cross-plan integration check
- [ ] Every register entry's `**Gate:**` block, and every sub-plan's gates from the first whose artifact exists, carry a `(goal)` check — `validate-gate-checks.py` reports zero GOAL-CHECK-MISSING on the master and on each sub-plan. It checks presence, not placement, so a sub-plan's placement from its first gate is the author's to check (`gate-authoring.md` § The plan's goal is a check from the first gate)
- [ ] Every sub-plan carries the `Master: ./<master-file>` backlink; every register `Plan:` link resolves
- [ ] The master plan is parser-safe: no raw `- [ ]` bullets outside `**Gate:**` blocks, no tasks, no Preflight (`master-plan-format.md`)

## Checklist — Light plans

For a **Light** plan (`../SKILL.md` § Phase -0.5 — Format triage selected it), verify only
these eleven — the Standard checklist does not apply:

- [ ] Every task has a concrete, runnable `Test:` that asserts the outcome and could go red — the same bar as any plan
- [ ] Tasks are in dependency order; any `Depends on` points only backward within the stage
- [ ] Exactly one stage, with 2–5 tasks (a 6th task or a second stage means re-issue as Standard)
- [ ] The stage has `**Outcomes:**` unless nobody outside the code meets its result (`../SKILL.md` § Phase 2 — Stage Breakdown)
- [ ] The single `### Stage 1 Gate` includes "full existing test suite passes" and a `(goal)` check sweeping the plan's goal over the whole artifact — `../scripts/validate-gate-checks.py` reports zero GOAL-CHECK-MISSING (`gate-authoring.md` § The plan's goal is a check from the first gate)
- [ ] A gate check over what a commit range changed (`git diff --name-only <base>..HEAD`) leaves out the files the executor commits itself — `proof/` records and any `.gitignore` git bootstrap writes — or it fails on the run's own bookkeeping
- [ ] A task that adds a member to a closed set (an enum, event list, migration count, snapshot baseline) updates every test that pins that set, in the same task (`task-fields.md` § `Test:`)
- [ ] The `Format: Light — …` line is present at the top; the file is saved to `<records home>/plans/` as `*-light-plan.md`
- [ ] Open backlog items in scope were reviewed (the scan runs at every size); folded-in items carry `Closes BL-NNN`
- [ ] If `docs/workflows/` exists and the change touches a documented flow, the altered/removed behavior is declared on the task (`Changes WF-NNN` / `Removes WF-NNN`) — behavior contracts don't get a size exemption
- [ ] On an expensive-suite project, every task's `Test:` is path- or suite-scoped, or the **task** carries a `full-suite: accepted` field with a reason — the same bar as any plan, and an **authoring-time** check (`test-scope-tiers.md`). A Light plan has task `Test:` fields, so this is not one of the items the format drops; it also carries the `**Test-scope commands**` block that arms the check (`light-plan-format.md` § Preflight collapses into the gate), without which this item is unenforceable

**Why the Light list is shorter rather than softer.** Every item it drops is a field the Light
format does not have (Risk, Rollback, Blocks, Dispatch, a Preflight section) or a long-horizon
artifact it does not produce. The items it keeps are the invariants — a runnable test, one
gate, the two scans — and those are identical to a Standard plan's, because a small plan can
violate a binding constraint just as thoroughly as a large one.
