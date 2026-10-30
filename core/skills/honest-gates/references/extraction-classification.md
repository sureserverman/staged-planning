# Extraction classification — `../SKILL.md`

Classifies this trunk's sections; the reasons behind its rules live in `reasons.md`. The
`bytes` column is each section's size in the trunk, measured with
`python3 scripts/trunk-sections.py core/skills/honest-gates/SKILL.md`: **14395 B** across
**8 headings**, plus 674 B of scaffolding (frontmatter, title, preamble); the two sum to the
file size exactly. The `markers` column counts the section's rows in the retention-marker
table. Both are re-taken from the current tree, and a figure here that disagrees with the
command is stale. The command reads the source trunk; a host build may rewrite
the trunk it installs beside this file, so a built copy's sizes can differ from these.

**Every-run load:** the trunk alone. honest-gates has no Reference map and no every-run
reference set — `reasons.md` is reached only through the trunk's pointers, which no gate or
Preflight step reads unconditionally.

**This table is the authority for what may leave the trunk.** A section marked
`unconditional` stays whole. A section marked `rule+elaboration` keeps its rule and sheds
its justification — the reasons and worked examples — into
`reasons.md`. Only `conditional` sections leave.

**Why honest-gates is classified at all.** A trunk in neither guard's PAIRS list can lose an
entire rule section with the full suite green. A table with invented byte counts would
satisfy the pairing without earning it, so the pairing is earned here by a real extraction
with real numbers. The rule this implements is the one `scripts/trunk-budget.txt` records for every honest-gates ceiling
raise: these are **write-time disciplines**, so a rule sentence never leaves the trunk, and
only the reason behind it may.

## The table

### unconditional — 3 sections, 2946 B

| bytes | markers | section | reason |
|---|---|---|---|
| 802 | 2 | The one rule | the definition of green and BLOCKED; every gate report is written under it |
| 1354 | 6 | When a gate is BLOCKED | the five-step procedure and the `[~]` rule; binds the moment a check cannot run |
| 790 | 6 | Reporting | the three states, the collapse prohibition, the substrate line and the reproducible-figure rule; every status report is written under it |

### rule+elaboration — 4 sections, 11111 B

| bytes | markers | section | reason |
|---|---|---|---|
| 3963 | 13 | Prohibited (these are gate-faking) | nine prohibitions stay whole (the authored-artifact one among them); the amendment bullet's second half is elaboration of the pointer it already carries |
| 2624 | 6 | A behavioral claim is a gate too | the cite-your-source rule, the absence/aggregate shapes and the two teeth stay; why a correction is a new claim is the elaboration |
| 3543 | 8 | A test does not exist until its mutant dies | the mechanism question, the two ways out, the three numbered rules and the discriminating-cause rule stay; why the mechanism question comes first, why fixtures come from the requirement and the "why this is not covered" paragraph are the elaboration |
| 981 | 3 | Changing a contract reclassifies everything already written | the do-not-ship rule, the inventory-is-a-command rule and the tier line stay; the marker-change worked example is the elaboration |

### conditional — 1 section, 338 B

| bytes | markers | section | reason |
|---|---|---|---|
| 338 | 0 | Integration | pointers to the skills that consume these rules; consulted only when routing to one |

## Where the conditional material went

No `conditional` section leaves: Integration stays — 338 B of pointers is cheaper than a
pointer to the pointers. The elaboration half of each `rule+elaboration` row lives in one
destination:

| section | destination |
|---|---|
| Prohibited (these are gate-faking) | `reasons.md` — the amendment-disclosure rationale, the authored-stub pair, suites dropped "for disk/time", the proxy-data and self-grading examples |
| A behavioral claim is a gate too | `reasons.md` — why a correction is a new claim, the absence-claim scope rationale |
| A test does not exist until its mutant dies | `reasons.md` — why the mechanism question comes first, the test-first-rule backing, why fixtures come from the requirement, the hardening rationale, rule 1's rationale, the masking pair, why the cause and not the outcome, the "why not covered" paragraph |
| Changing a contract reclassifies everything already written | `reasons.md` — the marker-change worked example, the adds-net argument, the framing paragraph, the "~20+" remark |
| Integration | stays |

## Retention markers

Each row names a string that must be **trunk-resident**, in the body of the section that
claims it (not its heading line), on one physical line. `scripts/check-trunk-retention.py`
sweeps this table in full. A marker pins presence, and a negation in the few words before
it (`You need not **…**`) fails as NEGATED-RULE; a rule withdrawn later in its sentence
still passes there — the contract suite in `../tests/` is what reads whole sentences.

**One marker per obligation, not per section.** The Prohibited section retains nine distinct
prohibitions; pinned by one string, eight could be demoted with this sweep green.

| section | marker |
|---|---|
| The one rule | A gate is green only when its real command ran in the current environment and |
| The one rule | If you cannot make the real check run here, the gate is **BLOCKED**, not green. |
| Prohibited (these are gate-faking) | No-op tasks that impersonate a gate. |
| Prohibited (these are gate-faking) | A gate artifact the executor authored. |
| Prohibited (these are gate-faking) | outcomes is not a gate |
| Prohibited (these are gate-faking) | Fabricated evidence. |
| Prohibited (these are gate-faking) | Silently excluding the failing case. |
| Prohibited (these are gate-faking) | BLOCKED on that suite |
| Prohibited (these are gate-faking) | never an authorizing rule |
| Prohibited (these are gate-faking) | neither touched nor depend on |
| Prohibited (these are gate-faking) | whatever the report calls it |
| Prohibited (these are gate-faking) | Heuristic self-grading. |
| Prohibited (these are gate-faking) | Proxy data that doesn't measure what the gate measures. |
| Prohibited (these are gate-faking) | Unannotated amendment of a gate's own checks. |
| Prohibited (these are gate-faking) | Verifying against a dirty working tree. |
| When a gate is BLOCKED | Stop on that gate. |
| When a gate is BLOCKED | Name the exact blocker |
| When a gate is BLOCKED | Try to unblock it for real |
| When a gate is BLOCKED | escalate to the user |
| When a gate is BLOCKED | Write the checklist item as `- [~]`, never `- [x]` with a note explaining |
| When a gate is BLOCKED | Preflight blockers (repo/SDK/device marked FAILED) are BLOCKED gates by |
| A behavioral claim is a gate too | what a script covers — **cite the |
| A behavioral claim is a gate too | An absence claim |
| A behavioral claim is a gate too | An emergent or aggregate claim |
| A behavioral claim is a gate too | A correction is a new claim. |
| A behavioral claim is a gate too | Unrequested specificity is where errors hide. |
| A behavioral claim is a gate too | This one cannot be a script. |
| A test does not exist until its mutant dies | can this mechanism decide this property? |
| A test does not exist until its mutant dies | Make the property structural |
| A test does not exist until its mutant dies | Write the set down before the fix. |
| A test does not exist until its mutant dies | Revert the fix; the suite must go red. |
| A test does not exist until its mutant dies | independently reachable from a named test |
| A test does not exist until its mutant dies | battery, one mutation per guard |
| A test does not exist until its mutant dies | Build fixtures from the requirement, never from observed behavior. |
| A test does not exist until its mutant dies | Assert the discriminating cause, not the outcome. |
| Changing a contract reclassifies everything already written | A change to a parsing contract, marker vocabulary or classification rule does not ship |
| Changing a contract reclassifies everything already written | The inventory is a command and its output, never an estimate. |
| Changing a contract reclassifies everything already written | Tier: untiered. |
| Reporting | every gate is one of: **GREEN** |
| Reporting | Never collapse BLOCKED into GREEN. |
| Reporting | names where its evidence executed |
| Reporting | ran anywhere else is |
| Reporting | emitted by a command at a sha it names |
| Reporting | a corpus figure states its selection rule |
