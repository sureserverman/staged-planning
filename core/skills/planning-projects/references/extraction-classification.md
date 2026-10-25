# Extraction classification — `../SKILL.md`

What each `../SKILL.md` section keeps in the trunk and where its elaboration lives.
The trunk is **39439 B** across **37 headings**, of which 886 B is scaffolding
(frontmatter, title, and the preamble that precedes the first heading). Every `bytes`
figure is re-taken by
`python3 scripts/trunk-sections.py --all-levels core/skills/planning-projects/SKILL.md`;
the ceiling and the rules it pays for are in `scripts/trunk-budget.txt`. The command reads the source trunk; a host build may rewrite
the trunk it installs beside this file, so a built copy's sizes can differ from these.

**This table is the authority for what may leave the trunk.** A section marked
`unconditional` stays in the trunk whole. A section marked `rule+elaboration`
keeps its rule in the trunk, and its justification lives in the file the
`elaboration` column names. Only `conditional` sections leave.

The rule this implements: extraction is safe for material a reader consults when
a branch is taken, and unsafe for a rule that must bind every run — because a
`references/` file is a definition site the author may never open, which is how a
field authored as a capability comes to be consumed as an instruction.

## What the trunk's shape allows

**A heading inside a code fence is not a section.** A worked example of a plan's
own section, put in a ```markdown fence, is sample content, not a section of this
skill. `scripts/_skill_sections.py` excludes fenced headings for both guards;
without that, this table would have to file a classification decision about a
code sample, and the row would fail the day anyone edited the example.

**An enumeration of rules has nothing to shed.** A section that states a rule and
then says *why* sheds the why. A section whose bullets **are** the rule —
`Preflight checklist`, `Phase 2.5 — Decomposition decision` — has no
justification layer, so moving any of its text moves a rule. Most of this
trunk's `rule+elaboration` sections are enumerations of obligations, which is why
they keep most of their bytes: the retention ratio is a property of a trunk's
shape, not of the classification class. `Checklist — Before Presenting the Plan`
is the one section that restates rules owned by other trunk sections, so its
full item list lives in `authoring-checklist.md` at no loss.

**A live obligation inside elaboration is promoted, never dropped.** `Preflight
checklist`'s rationale holds a live obligation — the plan declares its stage-scope
and plan-scope test commands in Preflight — so that sentence is a checklist
bullet, not prose that leaves with its paragraph. A paragraph can be elaboration
while a sentence inside it is a rule.

**Only one section is `conditional`.** `planning-projects` is consulted once per
plan, and almost every section fires on that single pass, so the trunk is kept
short by compressing justification, not by relocating procedure.

## The table

`bytes` is the section's current size in the trunk. `elaboration` names the file in
this directory that holds what the trunk does not, or `—` where the section has none.

### unconditional — 14 sections, 9582 B

| bytes | elaboration | section | reason |
|---|---|---|---|
| 1659 | — | Stage structure | the literal task/stage field template every plan is built from |
| 1392 | `set-valued-checks.md` | Write a set-valued check as the sweep that proves it | binds every gate check an author writes |
| 1667 | `task-fields.md` | Task and stage fields | a pointer at task-fields.md plus six load-bearing rules — among them `Depends on`/`Blocks` required and symmetric, intra-stage dependency order with no forward reference, and a consistent `Dispatch`, because a rule that survives only as a noun in a pointer sentence binds nothing |
| 1028 | — | Reference map | the index — without it no reference is reachable; it carries a row for every reference a run of this skill loads (`extraction-classification.md` and `plan-parser.md` are maintenance documents, read by their guards and by other references, not by a run) |
| 468 | `plan-document-template.md` | Plan Document Format | a pointer at the template fixture |
| 646 | `task-fields.md` | Phase 3 — The Red-Green Loop | a pointer plus its five obligations: a runnable test, a cycle budget, a test of the promised outcome, a claim that goes red when false, and a preparing task testing that it prepared |
| 277 | — | Phase -1 — Clarification | phase header; runs before every plan |
| 271 | — | Research summary | every task must trace back to it |
| 267 | — | When NOT to ask | the off-ramp rule; small and unconditional |
| 243 | — | Phase 4 — Stage Gates | phase header |
| 233 | — | Phase 0 — Research | phase header |
| 230 | — | Stage sizing | the >7-tasks rule; one sentence, binds every stage |
| 1003 | — | Phase 2 — Stage Breakdown | phase header plus the write-Outcomes-first rule, which binds every stage |
| 198 | — | Phase 1 — Preflight | phase header |

### rule+elaboration — 22 sections, 28757 B

| bytes | elaboration | section | reason |
|---|---|---|---|
| 3181 | `format-triage.md` | Phase -0.5 — Format triage | keeps the format table, the size-each-request rule, round-up and record-the-call; the per-format prose and the batch worked example are elaboration |
| 2304 | `authoring-checklist.md` | Checklist — Before Presenting the Plan | keeps the imperative to run every item, with the items that restate no other trunk section (the validator commands, the records-home save item, the master addendum); the full item list restates rules stated in their own sections |
| 2680 | `test-scope-tiers.md` | Preflight checklist | keeps the checklist bullets, which ARE the rule, the test-scope declaration among them; the rationale is elaboration |
| 1671 | `gate-authoring.md` | A plan that adds an obligation names what it removes | keeps Removes/Replaces/Adds-net, the has-it-caught-a-defect test and the name-the-tier rule; the accretion argument and the measured example are elaboration |
| 1710 | `research-scans.md` | Decisions scan | keeps call `relevant`, contradiction-is-a-planning-bug, record-what-was-consulted and the new-project rule; the sample block and the why are elaboration |
| 2038 | `master-plan-format.md` | Phase 2.5 — Decomposition decision (master plan + sub-plans) | keeps the decompose-when triggers and the 2–7 split rule — this is the sole authority on Standard→Master; the how-to-split detail is branch-taken |
| 1584 | `light-plan-format.md` | Light plans | a trunk summary over light-plan-format.md; keeps the five deltas and the upgrade rule, and the per-delta prose is elaboration |
| 1697 | `research-scans.md` | Architecture doc scan | keeps cite-the-ARCH-ID, emit-the-conformance-gate and no-silent-deviation; sub-plan mechanics are branch-taken |
| 1609 | — | Output location | keeps the resolve-then-save steps, the exit-2 stop and the broken-invocation rule; the exit-code contract lives in the plugin's `references/records-resolver.md` |
| 1027 | `gate-authoring.md` | Every fact has one owner | keeps the one-owner rule, both exceptions and the `(judgment)` restriction; the four-checks example is elaboration |
| 1429 | `research-scans.md` | Citing decisions on tasks | keeps the Honors/Supersedes citation forms, the required conformance gate and the own-words restatement; the reasoning is elaboration |
| 1178 | `research-scans.md` | Workflow-spec scan | keeps the three declaration rules and be-explicit-about-which; the redesign paragraph is branch-taken |
| 703 | `gate-authoring.md` | When a stage gate fails | keeps class-sampled-once and the do-not-restate deferral to executing-plans; the deferral detail is elaboration |
| 1791 | `test-scope-tiers.md` | What a stage gate checks | keeps the five check kinds; the regressions bullet's scope policy is owned by test-scope-tiers.md |
| 571 | — | Status marking (per-task done-state) | keeps the exact `- **Status:** [ ]` form and the close-out line |
| 651 | — | Phase 5 — Dispatch | keeps the mark-YES-when rule, stated once |
| 575 | — | When to ask | the six ambiguity axes are the rule and stay; the framing is compressed |
| 590 | `research-scans.md` | Backlog scan | keeps fold-in-with-`Closes BL-NNN` and duplicate-is-a-planning-bug |
| 486 | — | Online sources | keeps check version-specific behavior and use context7; the category list is compressed |
| 419 | — | Linked notes | keeps search-the-linked-notes and the plans-path fallback |
| 440 | — | How to ask | keeps one-question-at-a-time and state-your-assumption |
| 423 | — | Project context | keeps the four read-before-planning axes |

### conditional — 1 section, 214 B

| bytes | elaboration | section | reason |
|---|---|---|---|
| 214 | `authoring-checklist.md` | Checklist — Light plans | read only when Phase -0.5 selected Light, and light-plan-format.md is its authority; the trunk keeps only the existence pointer |

`conditional` rows carry no retention marker, by construction: their content lives
elsewhere, and their retained pointer is checked by the DEAD-PATH half of
`check-extraction-integrity.py` instead.

## Retention markers

A heading over a pointer satisfies set equality perfectly and loses the rule, so
each binding row names a string that must stay **trunk-resident**.
`scripts/check-trunk-retention.py` sweeps this table in full.

**Every binding section carries at least one marker, and a multi-obligation
section carries several** — one marker per section leaves the guard blind on exactly
the multi-obligation rows that are most dangerous to lose.

These markers are the trunk's contract with this table. Where a marker quotes text
that must survive verbatim, it is quoted from the trunk.

| section | must appear in the trunk |
|---|---|
| Reference map | The trunk carries the authoring decisions |
| Phase -1 — Clarification | make sure you understand what the user actually wants |
| When to ask | Success criteria |
| When to ask | Target environment |
| How to ask | One question at a time |
| When NOT to ask | ask because the answer would change the plan |
| Phase -0.5 — Format triage | Size each request, not the batch |
| Phase -0.5 — Format triage | Direct is the off-ramp |
| Phase -0.5 — Format triage | Record the call |
| Phase -0.5 — Format triage | round up — per item, never per batch |
| Light plans | fold in matches with `Closes BL-NNN` |
| Light plans | re-issue it as a Standard plan |
| Phase 0 — Research | Before writing a single task |
| Online sources | don't assume, check |
| Linked notes | prior design decisions |
| Decisions scan | contradict an accepted decision is a planning bug |
| Decisions scan | nothing binds this scope |
| Decisions scan | project register: absent |
| Backlog scan | Closes BL-NNN |
| Backlog scan | silently duplicates an open backlog item is a planning bug |
| Workflow-spec scan | Changes WF-AUTH-003 |
| Workflow-spec scan | Removes WF-AUTH-007 |
| Architecture doc scan | MUST cite the ARCH-ID |
| Architecture doc scan | Emit the conformance gate |
| Architecture doc scan | no architecture doc — structure decided inline |
| Citing decisions on tasks | Honors DEC-NNN |
| Citing decisions on tasks | The marker is **required**, not optional |
| Citing decisions on tasks | uncited change that contradicts an accepted decision is a **gate failure** |
| Project context | the plan should fit, not fight |
| Research summary | Every task below should trace back |
| Phase 1 — Preflight | Before Stage 1 begins |
| Preflight checklist | Baseline |
| Preflight checklist | Review scope |
| Preflight checklist | Dispatch probe |
| Preflight checklist | Dispatch roster |
| Preflight checklist | If any preflight check fails, stop |
| Phase 2 — Stage Breakdown | Divide the project into sequential stages |
| Phase 2 — Stage Breakdown | Write each stage's Outcomes before its tasks |
| Stage structure | an instruction to the executor — YES obligates dispatch |
| Stage structure | the SET this task changes |
| Stage structure | Class predicate: the command that sweeps the set |
| Status marking (per-task done-state) | `- **Status:** [ ]` when planned |
| Status marking (per-task done-state) | single source of truth for task completion |
| Status marking (per-task done-state) | the moment the task's test goes green |
| Status marking (per-task done-state) | rather than inferred from stage gates or git archaeology |
| Task and stage fields | is a directive to dispatch |
| Task and stage fields | only as good as the sweep behind it |
| Task and stage fields | are both required on every task, and they are symmetric |
| Task and stage fields | no task depends on a later |
| Task and stage fields | consistent with its dependencies |
| Stage sizing | more than 7 tasks |
| A plan that adds an obligation names what it removes | Adds, net: |
| A plan that adds an obligation names what it removes | has it ever caught a real defect |
| A plan that adds an obligation names what it removes | names the tier or scope rule that gates it |
| Phase 2.5 — Decomposition decision (master plan + sub-plans) | ~6 stages or ~25 tasks |
| Phase 2.5 — Decomposition decision (master plan + sub-plans) | 2–7 sub-plans |
| Phase 2.5 — Decomposition decision (master plan + sub-plans) | no tasks and no Preflight |
| Output location | do not create anything |
| Output location | Recording the project anywhere else is the resolver's job |
| Plan Document Format | Save to `<records home>/plans/YYYY-MM-DD-<topic>-plan.md` |
| Plan Document Format | Copy it there rather than reconstructing it |
| Plan Document Format | why it is a fixture rather than a sketch |
| Phase 3 — The Red-Green Loop | runnable command or a checkable criterion |
| Phase 4 — Stage Gates | Stage gates prove the pieces work together |
| What a stage gate checks | Live artifact over static checks |
| What a stage gate checks | Intermediate gates check at **stage-scope** |
| Every fact has one owner | is not re-proved at the gate |
| Every fact has one owner | may never restate a fact an executable check |
| Write a set-valued check as the sweep that proves it | is an executable sweep, not a spot check |
| Write a set-valued check as the sweep that proves it | may not be presented while it reports INSTANCE-SHAPED |
| Write a set-valued check as the sweep that proves it | **(judgment)** |
| When a stage gate fails | defect class sampled once |
| When a stage gate fails | Do not restate those rules here |
| Phase 5 — Dispatch | shares no file with a sibling |
| Checklist — Before Presenting the Plan | Before showing the plan to the user, verify |
| Checklist — Before Presenting the Plan | zero SELECTOR-UNMATCHED |
