# Plan document format

The literal template `planning-projects` emits. Consulted once, at write time.

## Plan Document Format

Output the plan as a markdown document following this structure. Save it to `<records home>/plans/YYYY-MM-DD-<topic>-plan.md` (`../SKILL.md` § Output location).

```markdown
# Project Plan: [Name]
Date: [YYYY-MM-DD]

## Research Summary

### Online sources
- [What was found, with links]

### Linked notes / local docs
- [Prior decisions, architecture notes]

### Project context
- [Existing patterns, dependencies, test framework]

## Decisions in force

[One NON-CHECKBOX bullet per binding entry — a raw `- [ ]` here would be read as
deferred work by the plan parser (backlog unify) and become a false backlog candidate.]

- DEC-NNN — [title] (accepted; [domains]) — [the constraint in one line]
- DEC-NNN — [title] (accepted; security; from a resolver-listed register) — [the constraint in one line]

**Registers consulted:** [`<records home>/decisions.md`; any register the records resolver lists …]

## Preflight

- [ ] [Check 1]: [how to verify]
- [ ] [Check 2]: [how to verify]
- [ ] Review scope declared — `review-scope: <none|light|standard|high> — [why, in one clause]`. Emit it in exactly that form: it is the string the executor restates in every gate report, so a plan and its gates read the same. Undeclared means `standard`; a risk-listed area (security/auth, data-destructive, public API, schema/migration) sets `high` whatever the size (`planning/skills/executing-plans/references/review-scope.md`)
- [ ] Dispatch probe: a throwaway subagent returns a fixed string — dispatch works in this session; skipped when the roster is `0 tasks` or the tier is below `standard`
- [ ] Dispatch roster — `<n> of <total> tasks`: every `Dispatch: YES` task below, with the subagent type it routes to (`planning/skills/dispatching-parallel-agents/references/stack-routing.md`) — `[Task N.M → <agent name>, …]`, or `0 tasks` if the plan has none. The count is what the stage gate reconciles its dispatched-vs-inline ledger against, so a roster without one cannot be checked

**Test-scope commands** (per test-scope-tiers.md — only when the full suite exceeds ~5 min):
- stage-scope: [cheap checks in full + expensive suites for touched modules; no clean]
- plan-scope:  [the single full clean pass, quarantined tests included]

---

## Stage 1: [Name]

**Goal:** [one sentence, naming who it is for]
**Outcomes:** [who uses the result — a person, another app, a later stage]
- Works: [what they get]
- [a way it can fail] → [what they see]
- [another way it can fail] → [what they see]
<!-- Keep only Outcomes bullets under the field; indent a wrapped line. The commit hook
     refuses any other line there rather than drop the bullets after it. -->
**Depends on:** none
**Blocks:** Stage 2
**Risk:** LOW | MEDIUM | HIGH — [reason]
**Rollback:** [what to undo and how]

<!-- At the first driveable stage, include one bounded integration smoke case:
**Requirement origin:** [owner requirement / approved design / explicit assumption]
**Early premise:** [actual artifact/route, concrete smoke invocation, evidence reference]
**Evidence claim:** [synthetic / retrospective / prospective / live_local_protocol; claim limits]
**Remaining authorized work:** [what proceeds if this premise or requested live claim is blocked]
These stay on the stage; Step 3.0 runs the early premise's smoke as one of its premise
checks and records it in the worksheet, never a second worksheet. A fixture cannot establish live AI usefulness. -->

### Task 1.1: [description]
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Dispatch:** YES
- **Scope:** [the set this task sweeps — omit for a single-artifact task]
- **Test:** `[exact command or criterion]`
- **Red-Green max cycles:** 3

<!-- Only for comparison experiments: name the original receipt and bound candidate,
     baseline, evidence/split/rubric/dependency identities. Declare evidence class and
     availability/schema/support/usefulness/preference separately, including unknown.
     Follow executing-plans/references/evaluation-evidence-contract.md; reused evidence
     keeps original experiment attribution and never becomes a fresh success. -->

### Task 1.2: [description]
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** Task 1.3, Task 2.1
- **Dispatch:** NO (blocked by 1.1)
- **Test:** `[exact command or criterion]`
- **Red-Green max cycles:** 3

### Stage 1 Gate

<!-- Gate checkbox states: `[ ]` not yet run · `[x]` ran and passed · `[~]` BLOCKED,
     the check could not be run here. `[~]` is not a softer `[x]`: a plan carrying one
     cannot classify as completed, however its close-out line reads. A gate that ran
     and FAILED is not written down at all — it is repaired (honest-gates).
     To close a plan whose gate genuinely cannot be run here, add a terminal
     `**Blocked-accepted:** <date> — <why>` line beside the close-out line. That is
     the author's answer, and it is the ONLY thing that retires such a plan; do not
     edit the `[~]` to `[x]`, which falsifies the record the marker exists to keep. -->
- [ ] **(goal)** [the plan's goal as one cheap sweep over the WHOLE artifact it is about, in every gate from the first one whose artifact exists — gate-authoring.md § The plan's goal is a check from the first gate]
- [ ] [Integration check]
- [ ] [Class predicate — the sweep that proves a set-wide property, e.g. `! grep -rl '<the stale claim>' <scope>`]
- [ ] [No regressions in touched scope (stage-scope — see references/test-scope-tiers.md)]
- [ ] [Stage goal verified end-to-end]
<!-- A stage with **Outcomes:** gets an evaluator at every tier above `none`, grading those
     lines as their user; do not restate them here. A `(judgment)` line also buys an
     evaluator dispatch, and a fresh evaluator never returns empty-handed. Add one only where
     a reader decides something else no command can, and say what:
- [ ] **(judgment)** [what a reader decides here that no command can] -->

---

## Stage 2: [Name]

**Goal:** ...
**Outcomes:** ...
**Depends on:** Stage 1 gate passing
**Blocks:** Stage 3
**Risk:** ...
**Rollback:** ...

[Tasks with Depends on / Blocks / Dispatch fields...]

### Stage 2 Gate
- [ ] **(goal)** [the same goal sweep as Stage 1 — every gate from the first one whose artifact exists repeats it]
[Checks...] — if Stage 2 is the plan's final stage, its gate replaces the
regression check above with the plan-scope bullet instead:
- [ ] [Full clean test pass (plan-scope — the plan's single full run)]
- [ ] **(judgment)** [No change contradicts a decision in force (list the DEC IDs in
      scope, from every register consulted); any Supersedes citation has been recorded via the `decisions` skill's `supersede` operation] — a
      conformance judgment over a diff; no sweep can prove it
```

---
