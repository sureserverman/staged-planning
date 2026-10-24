# Integration — the skills and agents this one routes to

Consulted when routing to one of them. The trunk (`../SKILL.md` § Integration) names the set;
this file says what each one is for and on what condition it fires.

- **planning-projects** — produces the plan this skill consumes; for decomposed big projects it produces a master plan plus sub-plans (format: its `../../planning-projects/references/master-plan-format.md`), which this skill executes per its master-plan path — sub-plans in register order, cross-plan gates on each completion, version bumps deferred to the master close-out
- **dispatching-parallel-agents** — invoked for every `Dispatch: YES` task; a file conflict serializes the dispatches rather than cancelling one. Its `../../dispatching-parallel-agents/references/stack-routing.md` is the shared table that routes each `Dispatch: YES` task to a stack-matched subagent (e.g. a stack-specialist agent). It routes nothing else: a `Dispatch: NO` task runs inline, with no exception for independent, output-heavy sequential tasks (`task-execution.md` § Why there is no third execution mode)
- **backlog** — invoked to `add` what is **not** a defect: a significant improvement, a decision the user must make, or a task the user chose to skip after a cycle budget exhausted. A defect found during a run is fixed, never filed (`../references/stage-gate.md` § Exit criterion — the dispositions behind it). Also invoked to `remove` items the plan closed in Phase Close-out
- **decisions** — the architectural-decision register, consumed on three paths: `relevant` at Preflight (re-scan and diff against the plan's recorded `## Decisions in force`, since the register accretes between planning and execution), the conformance check at the **final** stage gate and close-out (a contradiction without a `Supersedes` citation is a gate failure wherever it is found — what is scoped to the final gate is the *sweep*, not the rule), and `supersede` / `add` at close-out (recording overrides the plan declared, and constraints execution itself discovered)
- **workflow-spec** — invoked in Phase Close-out to `audit` the cumulative diff against `docs/workflows/`; undeclared `Removed` findings block the merge
- **goal-evaluator agent** — the *black-box* gate/close-out evaluator: a fresh agent briefed ONLY with the stage/plan goals and gate criteria, never the implementation transcript. Verifies the *goal* is met against the artifact; at a stage with Outcomes it is a demo, briefed with the output of `stage-brief.py demo`, using the built product as their user. **When it runs is the declared review scope's call** (`../references/review-scope.md`): never at `none`, at `light`/`standard` wherever a gate carries a `(judgment)` check or its stage has Outcomes, always at `high` and at that tier's Phase Close-out. Where the tier mandates it, skip only on an evidenced user opt-out (quoted) or — below `high` only — when every check is a command and the stage has no Outcomes.
- **planning:code-reviewer agent** — the *white-box* review (read-only): reads the actual diff and returns a Critical / Important / Suggestion triage. Runs in two tiers, **each gated by the declared review scope** (`../references/review-scope.md`, which is the authority on when either fires) — **Tier 1** per green task, at `high` only or on a task's `Review: required` (a Critical blocks the task within its Red-Green cycle budget), and **Tier 2** never at `none`, at `light` once over the whole plan diff whatever the format, and at `standard`/`high` once per unit the format names — per stage gate for a Standard or Master plan, once over the whole diff for a Direct or Light one (a Critical fails the gate, and an Important leaves the gate fixed per the exit criterion — never merely mentioned, and never merely filed). Distinct axis from the goal-evaluator: *code quality* vs *goal attainment*. Bundled in this plugin (`agents/code-reviewer.md`).
- **applying-design-handoff** — drives a *design-handoff* / *redesign* task: detects the
  handoff pack (local bundle or live claude.ai design project), reproduces it precisely,
  reshapes functionality to fit (behavior changes gated through `workflow-spec` with
  sign-off), and dispatches the `planning:design-handoff-reproducer` agent per slice. Its
  fidelity verify loop is the design-fidelity gate hook
  (`../references/stage-gate.md` § Design-fidelity verify hook (redesign stages)).
- **design-handoff-reproducer agent** — the per-slice reproducer the redesign path
  dispatches: reproduces one normalized spec slice (component/screen + tokens + assets)
  faithfully in the target stack, self-checks against the fidelity rubric, and FLAGs
  behavior changes back instead of applying them.
- **platform stage-verify skills** — invoked at each stage gate to prove the stage on the real artifact when the project type matches. Found by discovery: a platform stage-verify skill, if one is installed whose description matches the project type (e.g. an Android build-and-smoke-test skill). Absence of a match is not a gate failure
- **test-scope-tiers reference** (`../../planning-projects/references/test-scope-tiers.md`) — the shared scope policy the task loop (fix-scope), the stage gate (stage-scope), and Close-out (plan-scope) follow

## Review opt-out

A review **the declared tier mandates** is default-on; a tier that does not mandate one is the
machinery scaling as designed, reported as scope and never as an opt-out
(`../references/review-scope.md`). **Two reasons excuse a mandated review, and the list is
closed at two: an evidenced user opt-out, and a trivial/non-code diff.** A reviewer that
cannot be dispatched is not a third: that is the **Stop condition for a mandated review**
that cannot be run, on the same ground as an unrunnable test. An unrun review is not a
passed review, and it leaves an artifact indistinguishable from a reviewed one — which is
why the resolution is the user's to choose, not the executor's to assume.

**An opt-out is evidenced, not asserted.** A trivial/non-code diff carries its own evidence,
checkable against the diff. A user opt-out is a claim about something outside the artifact,
so recording it means **quoting the user's own words**, with where they were said:

```
Review skipped — user opt-out, Preflight: "don't bother with the reviewer on this one"
```

A `Review: skip` annotation **counts as an opt-out when Preflight's snapshot lists it** — the
snapshot is what makes it evidence, because the executor writes to the plan file throughout
the run, so an annotation read at skip time proves nothing about who put it there. An
annotation missing from that snapshot is an executor-authored note. Cite the snapshot line,
not the task line.

**Executor judgment is not an opt-out.** *"I judged the review unnecessary"*, *"the diff
looked small"* are the executor deciding on the user's behalf and recording it as though the
user had. A skip reported without a quote or a cited snapshot is an **unevidenced skip**: it
reads downstream as a review that did not happen, because that is what it is.

Why the snapshot rather than the task line is the evidence, and the full tier table:
`../references/review-scope.md`.
