# Extraction classification — `../SKILL.md`

Classifies every trunk heading for extraction: what stays in the trunk, and what may move
to a reference file. The `bytes` column is each section's size in the trunk, measured with
`python3 scripts/trunk-sections.py --all-levels core/skills/executing-plans/SKILL.md`:
**55913 B** across **32 headings**, plus 664 B of scaffolding (title, preamble, and rules
sitting outside any heading); the two sum to the file size exactly. The `markers` column
counts the section's rows in the retention-marker table. Both are re-taken from the current
tree, and a figure here that disagrees with the command is stale. The command reads the source trunk; a host build may rewrite
the trunk it installs beside this file, so a built copy's sizes can differ from these.

**This table is the authority for what may move out of the trunk.** A section marked
`unconditional` stays in the trunk whole. A section marked `rule+elaboration`
keeps its rule and sheds its justification. Only `conditional` sections leave.

The rule this implements: extraction is safe for material a reader consults when
a branch is taken, and unsafe for a rule that must bind every run — because a
`references/` file is a definition site the executor may never open: a rule that lives
only there is authored as binding and read, if at all, as optional.

## The ceiling follows the obligations

**If an extraction's retained total exceeds its estimated ceiling, record the miss and
re-derive the ceiling from what the extraction retained — never move an obligation to hit a
number.** The active ceiling is whatever `scripts/trunk-budget.txt` says, and it rises when
a rule is restored to the trunk. Read it there rather than here; a byte count copied into
prose is a second definition site for a number the ratchet already owns.

**A compression that drops an obligation-bearing phrase is wrong even when the
classification is right.** A rule that must bind each run keeps its obligation-bearing
phrases in the trunk, not only its gist — such as the gate-failure branch's routing to the
class rule and its evidence-first diagnosis, the `Scope:` derivation source, "write the command
down", the sweep's outer bound, Tier-2's binding of an Important to the exit criterion, the
evaluator's tier reference, and the handoff's "carried here". None of them belongs in a
reference file.

**A `rule+elaboration` section keeps every obligation it carries, not a fixed share of its
bytes.** `Step 3.5 — Stage gate` keeps its exit criterion, gate order, evaluator rule,
Tier-2 rule, decisions-conformance rule, remediation budget and pass/fail branches, because
those *are* the section's obligations; an estimate that assumes a rule compresses to a set
fraction of its section undercounts exactly these.

**Two sections keep more than a pointer, deliberately:**

- **`Amending authored ceremony`** keeps the three legality conditions (unexecuted checks
  only, the annotation cites the authorizing rule, the was-value survives) in the trunk; the
  pointer alone would leave an executor amending unguided. *A pointer is not a rule.*
- **`Reference map`** keeps an index row, with its load condition, for each reference file
  a run is routed to. The index grows with the extraction, and that is the extraction working.

**A section that only restates rules the trunk states in their own sections is deleted, not
relocated** — relocating a duplicate keeps a second copy that drifts from the first. Such a
section has no row in the table below, because `scripts/check-extraction-classification.py`
enforces set equality against the trunk's real headings.

## The table

`bytes` is the section's size in the trunk and `markers` its retention-marker count, both
measured as stated at the top of this file.

### unconditional — 14 sections, 18981 B

| bytes | markers | section | reason |
|---|---|---|---|
| 2543 | 3 | Phase 1 — Load and critique | runs on every plan |
| 2249 | 3 | The plan is the authorization — dispatch without a confirmation turn | dispatch-bound obligation; binds every dispatch decision |
| 1848 | 1 | Reference map | the index — without it no reference is reachable |
| 1412 | 3 | Phase 2 — Preflight | phase header + the check list itself |
| 3168 | 3 | Stop conditions | must bind every run, whole — never a pointer; it carries the read-the-owner-decisions-first rule, which decides whether each stop asks at all |
| 1165 | 3 | Run to completion — don't stop until you have to | governs every turn of every run |
| 951 | 2 | What this skill expects | the format contract; every run validates against it |
| 1329 | 3 | Safety rails | branch/destructive/secrets/shared-infra — every run |
| 609 | 1 | Checklist | the four-step loop every execution follows |
| 604 | 2 | When to revisit earlier steps | small, unconditional |
| 2547 | 4 | Step 3.0 — Test the stage's premise first, in the real environment | every stage start: the stage-order check, Outcomes, and the premise worksheet the green commit needs |
| 270 | 1 | Step 3.1 — Identify what can run now | every stage start |
| 228 | 1 | Step 3.4 — Propagate unblock | every green task |
| 58 | 1 | Phase 3 — Stage execution | phase header |

### rule+elaboration — 14 sections, 35299 B

| bytes | markers | section | reason |
|---|---|---|---|
| 12699 | 16 | Step 3.5 — Stage gate | exit criterion + gate order stay; the two verify hooks (Android, redesign), evaluator briefing, Tier-2 shape, decisions sweep and failure procedure are each branch-taken |
| 7696 | 10 | Step 3.3 — Red-Green loop (per task) | loop rules 1-7 stay; Tier-1 machinery is tier-gated and the test-first rationale is elaboration |
| 2026 | 3 | Step 3.2 — Split by parallelism | the YES-obligates-dispatch rule stays; the no-third-mode rationale is elaboration |
| 1971 | 3 | Dispatch roster and capability probe | fires every Preflight; rationale already in references/dispatch-fidelity.md |
| 1939 | 3 | A bug found during execution is a class — sweep it, fix every instance | rule is one paragraph; the worked reasoning is elaboration |
| 1820 | 3 | Context resets at stage boundaries | the handoff-note requirement fires at every gate; the rest is guidance |
| 1736 | 2 | Review scope — the machinery scales to the change | tier declaration is unconditional; the table is RESTATED from references/review-scope.md, which the trunk already calls the authority |
| 997 | 1 | Light plans | already a trunk summary over references/light-plans.md |
| 950 | 1 | Master plans | already a trunk summary over references/master-plans.md |
| 699 | 1 | Calibration re-check (the plan's ceremony can be stale) | fires every Preflight; the worked example is elaboration |
| 975 | 1 | Progress state file (live statusline bar) | already a pointer at references/progress-state-file.md |
| 652 | 2 | Gate-selector probe (a gate that cannot pass is a plan defect, not a gate failure) | probe fires every Preflight; the false-positive analysis is elaboration |
| 646 | 1 | Git bootstrap (hard prerequisite for commit-per-task) | fires every Preflight; the decision tree is mechanical detail |
| 493 | 1 | Decisions re-check (the plan's snapshot can be stale) | fires every Preflight; the why is elaboration |

### conditional — 4 sections, 1633 B

| bytes | markers | section | reason |
|---|---|---|---|
| 706 | 1 | Phase Close-out — After the last stage | a phase reached once, at the end; nothing before it needs the text |
| 437 | 1 | Integration | per-skill descriptions consulted only when routing to one |
| 400 | 2 | Amending authored ceremony | only when an amendment is actually needed; the three legality conditions stay because a pointer is not a rule |
| 90 | 1 | Sources and rationale | already a pointer at references/sources.md |

## Where the conditional material went

| material | lives in |
|---|---|
| Phase Close-out (steps 1–10) | `../references/close-out.md` |
| Integration list + Review opt-out | `../references/integration.md` |
| Step 3.5's hooks, evaluator, Tier 2, dispositions, failure branch, handoff shape | `../references/stage-gate.md` |
| Step 3.2's rationale + Step 3.3's test-first evidence, Tier-1 machinery, trailer detail | `../references/task-execution.md` |
| Preflight's five check procedures + the amendment protocol | `../references/preflight-checks.md` |
| The class-sweep reasoning and its cost rule | `../references/bug-is-a-class.md` |

## Retention markers

The classification's obligation is not only that a heading survived — a heading over a pointer would
satisfy set equality perfectly and lose the rule. Each row names a string that must be
**trunk-resident**: the rule the row promised to keep, in the trunk's own words.
`scripts/check-trunk-retention.py` sweeps this table in full, so a rule quietly demoted to a
pointer in some later edit fails the suite rather than passing unnoticed.

**Every binding section carries at least one marker, and a section may carry several.** Each
property closes a gap:

- **`unconditional` rows are not exempt.** Exempting them, on the reasoning that they may
  never move so heading presence is enough, is exactly backwards: they carry the strongest
  guarantee in the table, and heading presence is the one check that cannot see a section
  gutted to a stub. An exempt guard is blind on the class it calls most dangerous.
- **One marker per section is instance-shaped.** `Step 3.5 — Stage gate` retains more
  than a dozen distinct obligations; pinned by a single string, all but one could be demoted
  with the sweep still green — the defect class this plugin's own gate rules exist to reject,
  reproduced inside the guard meant to enforce them.

**A marker may not span a line wrap.** `check-trunk-retention.py` matches plain
case-sensitive substrings against **the body of the section that claims the marker** — not the
raw file, and not including that section's own heading line. So a marker crossing a newline
plus the next line's indent (or a `> ` blockquote prefix) can never match, and the guard reports MISSING-RULE
for a rule that is present. Pick a marker that sits on one physical line.

| section | must appear in the trunk |
|---|---|
| What this skill expects | It deliberately has no |
| What this skill expects | it wasn't produced by `planning-projects` |
| Reference map | The trunk carries what fires on every run |
| Master plans | Version bumps defer to the master |
| Light plans | that single pre-gate review IS the light plan's Tier-2 |
| Checklist | Run the stage gate; stop if it fails |
| Run to completion — don't stop until you have to | Only the documented Stop conditions halt execution |
| Run to completion — don't stop until you have to | Stage boundaries |
| The plan is the authorization — dispatch without a confirmation turn | is a direct order, and you execute it without asking |
| The plan is the authorization — dispatch without a confirmation turn | conditional, not absolute |
| The plan is the authorization — dispatch without a confirmation turn | no plan in play |
| A bug found during execution is a class — sweep it, fix every instance | one sample of a class until a command proves |
| A bug found during execution is a class — sweep it, fix every instance | nothing wider |
| A bug found during execution is a class — sweep it, fix every instance | costs a command, never a dispatch |
| Phase 1 — Load and critique | Read the plan file in full |
| Phase 1 — Load and critique | INSTANCE-SHAPED |
| Phase 1 — Load and critique | Decisions in force |
| Phase 2 — Preflight | Baseline test suite passes |
| Phase 2 — Preflight | proven by an executed probe, never by an environment variable |
| Phase 2 — Preflight | Review scope is declared |
| Decisions re-check (the plan's snapshot can be stale) | accretes between planning and execution |
| Calibration re-check (the plan's ceremony can be stale) | What is never recomputed: the plan's facts |
| Amending authored ceremony | unexecuted checks only |
| Amending authored ceremony | the was-value survives |
| Gate-selector probe (a gate that cannot pass is a plan defect, not a gate failure) | pytest --collect-only -q |
| Gate-selector probe (a gate that cannot pass is a plan defect, not a gate failure) | plan defect |
| Git bootstrap (hard prerequisite for commit-per-task) | A missing remote is **not** a stop condition |
| Dispatch roster and capability probe | A failed probe is a Preflight failure |
| Dispatch roster and capability probe | across all stages |
| Dispatch roster and capability probe | Snapshot the `Review: skip` annotations |
| Review scope — the machinery scales to the change | Declare a tier at Preflight and restate it in every gate report |
| Review scope — the machinery scales to the change | size alone never escalates |
| Phase 3 — Stage execution | For each stage in order |
| Step 3.0 — Test the stage's premise first, in the real environment | --stage-order-check |
| Step 3.0 — Test the stage's premise first, in the real environment | gets them now, from the Goal |
| Step 3.0 — Test the stage's premise first, in the real environment | the `Stage N green` commit is refused without it |
| Step 3.0 — Test the stage's premise first, in the real environment | If one is false, stop |
| Step 3.1 — Identify what can run now | every task in its `Depends on` list is green |
| Step 3.2 — Split by parallelism | `YES` obligates a dispatch, `NO` means inline |
| Step 3.2 — Split by parallelism | serialize the dispatches |
| Step 3.2 — Split by parallelism | is a deviation |
| Step 3.3 — Red-Green loop (per task) | **One fix per cycle.** |
| Step 3.3 — Red-Green loop (per task) | must go RED for the right |
| Step 3.3 — Red-Green loop (per task) | revert the fix (not the test) |
| Step 3.3 — Red-Green loop (per task) | whether the mechanism |
| Step 3.3 — Red-Green loop (per task) | Respect the cycle budget |
| Step 3.3 — Red-Green loop (per task) | Flip the task's Status to `[x]` |
| Step 3.3 — Red-Green loop (per task) | Executor: dispatched — <subagent_type> |
| Step 3.3 — Red-Green loop (per task) | one physical line |
| Step 3.4 — Propagate unblock | scan its `Blocks` field |
| Step 3.5 — Stage gate | A gate passes when **no Critical finding remains** |
| Step 3.5 — Stage gate | A gate is green only when its real command ran |
| Step 3.5 — Stage gate | is a substitution, not a review |
| Step 3.5 — Stage gate | with no recorded reason the gate |
| Step 3.3 — Red-Green loop (per task) | put the records home outside the repo |
| Step 3.3 — Red-Green loop (per task) | from the repo root |
| Run to completion — don't stop until you have to | Never end a turn on an announcement |
| Step 3.5 — Stage gate | gate is BLOCKED, not green |
| Step 3.5 — Stage gate | Never collapse BLOCKED into GREEN |
| Step 3.5 — Stage gate | Regressions check runs at stage-scope |
| Step 3.5 — Stage gate | dispatched-vs-inline counts |
| Step 3.5 — Stage gate | the agent that ran it |
| Step 3.5 — Stage gate | Platform stage-verify hook |
| Step 3.5 — Stage gate | briefed ONLY with the plan goal |
| Step 3.5 — Stage gate | pass with |
| Step 3.5 — Stage gate | a **Critical** here is a |
| Step 3.5 — Stage gate | Decisions-conformance check |
| Step 3.5 — Stage gate | default 2 rounds per gate |
| Step 3.5 — Stage gate | Required verification belongs to the active round |
| Context resets at stage boundaries | Stage gates are the reset points |
| Context resets at stage boundaries | the review ledger cannot |
| Context resets at stage boundaries | never by needing |
| Progress state file (live statusline bar) | `finish` retains terminal evidence |
| Stop conditions | Never guess through a stop condition |
| Stop conditions | never ask through a dispatch the plan mandated |
| Stop conditions | cannot be performed |
| When to revisit earlier steps | treat the new version as a fresh plan |
| When to revisit earlier steps | does not share the plan's branch or its gate |
| Phase Close-out — After the last stage | Do not merge without explicit confirmation |
| Safety rails | Never start on `main` / `master` without explicit user consent |
| Safety rails | Destructive commands |
| Safety rails | routes or DNS to reach a device under test |
| Sources and rationale | references/sources.md |
| Integration | references/integration.md |

The progress-state retention marker pins owned v2 terminal evidence. Deleting the
state file at close-out applies only to unowned legacy state; the owned snapshot
contract retains it.

The Step 3.5 accounting marker follows the transactional contract: required review
verifies the reserved repair, and a separately initiated critique needs new admission.
