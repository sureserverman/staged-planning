# Review scope and the opt-out rules

How much verification machinery a run pays for, what shape it takes, and the two — only two —
reasons a review the tier mandates may be skipped. `executing-plans` declares the tier at
Preflight and restates it in every gate report.

### Review scope — the machinery scales to the change

Declare this at Preflight, next to the test-scope commands, and state it in every gate
report. Test scope is already tiered (`../../planning-projects/references/test-scope-tiers.md`)
so a gate does not run the full suite to prove a one-line fix. **Review scope is the same
idea applied to the verification machinery**: without it every review, probe, evaluator and
conformance check runs at one weight regardless of what it is reviewing, and a table that
gates only the two review passes leaves the rest running unconditionally underneath.

| Tier | When (judged on the plan's **cumulative diff**) | Tier-1 (which tasks) | Tier-2 (the deep review) | Gate evaluator | Close-out evaluator |
|---|---|---|---|---|---|
| **none** | Docs-only, config-only, version-bump-only, comment-only across the whole plan — **and none of that prose asserting executable behavior** (see below) | skip | skip | skip | skip |
| **light** | No new executable behavior, **or** a diff under roughly 200 changed lines across ≤ ~5 files — and no risk-listed area touched | skip | **one**, over the whole plan diff, before close-out | at a gate carrying a `(judgment)` check **or whose stage has `**Outcomes:**`**, unless a recorded goal command decides it (`stage-gate.md` § Skipped when a recorded command decides the goal) | if the final gate carries `(judgment)` or any stage has Outcomes |
| **standard** | Multi-file code with new behavior — the default when unsure, and what an undeclared run gets | skip | at the shape the format sets | at a gate carrying a `(judgment)` check **or whose stage has `**Outcomes:**`**, unless a recorded goal command decides it (`stage-gate.md` § Skipped when a recorded command decides the goal) | if the final gate carries `(judgment)` or any stage has Outcomes |
| **high** | **Risk-listed:** security-sensitive, auth, data-destructive, public API, schema/migration — **paths a task's diff touches, never a project's subject matter** (`review-scope.md` § Risk-listed names a path, not a project) | per **risk-listed task** (see below) | that, **plus** a second independent pass | **every gate, always** | **always** |

**`none` excludes prose that asserts executable behavior.** A docs-only diff qualifies for
`none` only when its prose *mentions* things; the moment it **asserts** a fact about a
command, flag, env var, exit code, default, path or invocation example, the plan is `light`,
not `none` — and `light`'s one whole-diff review is what checks the assertion against the
source. This is the same test Step 3.3 rule 6 applies to a task-level docs diff, lifted to
the tier where it actually binds: prose is where behavioral claims go unchecked longest (no
compiler, no test), so a tier that skips every review is exactly the wrong home for it. The
distinction is *asserting* versus *mentioning* — naming a flag in a heading, or an unchanged
sample, claims nothing and still lands at `none`.

**Read the table top-down: the first row whose criteria the diff satisfies wins.** `none` and
`light` deliberately overlap (a docs-only plan also has "no new executable behavior"), and
without a precedence rule the "default when unsure" line would push the cheapest plan in the
ladder to the middle of it. Top-down is also why `high`'s risk list is checked first in
practice — see this file's risk-floor rule, **Escalation: risk raises a tier, size never
does**, which overrides the row order in the one direction that matters.

Pick the tier from the **plan's cumulative diff**, not per task, and pick it once. A plan
that edits three markdown files is `light` even if it has four stages; a plan touching an
auth path is `high` even if it is small.

### Risk-listed names a path, not a project

The `high` row's list names **code paths a task's diff touches**: the function that checks a
credential, the statement that drops or migrates a table, the signature a downstream caller
binds to, the rule that decides where a packet goes. It does not name a project's subject
matter. A network service, a chat bot and a mobile app with a database
are *about* risk-listed things, and reading the list that way puts every task in every such
project on it. Measured over five plans that read it that way and declared `high` (one
owner's plans across 15 sessions, 2026-09-09..11): in three of them Tier-1 bound 7 of 8,
5 of 9 and 6 of 9 tasks, the five runs bought 65 verification dispatches for 12 execution
ones, and none of the five used the `light` or `standard` row.

Two bounds, checked at authoring and re-checked at Preflight's calibration step:

- **A `high` declaration names, per bound task, the risk-listed path its diff touches** —
  `high — 1.3 (drops the legacy column), 2.1 (rewrites the session-token check)`. A
  declaration that cannot say which path a task touches has no ground to bind it.
- **A declaration that would bind more than a third of the plan's tasks is describing the
  project, not the diff.** Re-derive per task. The usual correct result is `standard` with
  `Review: required` on the tasks that genuinely touch a risk-listed path: those get
  Tier-1, and the plan pays one Tier-2 per stage rather than two passes plus an evaluator
  at every gate. Where more than a third genuinely do touch such paths, say so on each and
  keep `high` — the bound exists to force the sentence, not to forbid the tier.

**Conformance lines do not fund an evaluator.** The decisions-conformance and
architecture-conformance checks carry `(judgment)` because a reader decides them, but that
reader is the **executor** (`stage-gate.md` § Decisions-conformance check). A gate whose
only `(judgment)` lines are those two is, for the tier table's evaluator column, a gate
carrying none.

**What the tier gates.** Everything in the row: the two review tiers, the gate evaluator, the
close-out evaluator, and the second independent pass. Two more agent-dispatching mandates are
gated by it, and are named here because a table that leaves them off is a half-measure:

- **The Preflight dispatch probe** runs only when the roster is non-empty **and** the tier is
  `standard` or `high`. Record `probe: skipped — tier <name>` alongside the roster line. What
  a probe buys is learning that dispatch is dead *at Preflight*, while the finding can still
  change the plan. That value scales with how many dispatches the run depends on: at `none`
  and `light` nothing is dispatched but the rostered tasks themselves, and the first of those
  delivers the same news almost as early. The accepted cost, stated because it is real: a
  `light` run with a non-empty roster learns one task later than a `standard` run would.
- **The design-fidelity verify loop's evaluator** (Step 3.5's redesign hook) is a dispatch
  like any other and follows the same rule as the gate evaluator: never at `none`, at
  `light`/`standard` when the stage carries a design-handoff task whose fidelity is a
  `(judgment)` gate check, always at `high`. A redesign stage that reproduces a handoff pack
  is essentially always at least `standard`, so in practice this loop runs — but it is listed
  here because a mandate costing an agent dispatch that appears on neither list is exactly
  the gap this section exists to close.
- **The redesign review** (`gate-failure-procedure.md` § A redesign the gate closes on): a
  redesign no review has read when the gate closes gets one review of its diff, at the tier
  that funded the original review, or a battery entry in its place. It adds at most one
  dispatch per gate to the row's count, and only at `light` and above — at `none` no review
  read the original either. It is not a remediation round.

**Not tier-gated, but relocated: the decisions-conformance check.** It runs at the **final**
stage gate and at close-out rather than at every intermediate gate — at every tier where the
diff is code. This is a **position** rule, not a tier rule, and it is stated here rather than
in the list above because putting it there would imply a tier term it does not have. A
contradiction is a **gate failure wherever it is found**; what the position sets is only how
often the sweep is repeated over a diff that is still growing, and the one reading that can be
complete is the one over the finished diff.

What the tier does **not** gate — because each costs a line of text and its absence is
invisible — is the dispatch roster, the executor trailer, the dispatch
reconciliation, honest-gates disclosure, the class sweep of `../SKILL.md` § *A bug found
during execution is a class*, and the plan's own tests and gate checks. Those run
at every tier including `none`. The distinction is cost: **a *verification* mandate that costs
an agent dispatch is tiered; one that costs a line of text is not.**

"Verification" is load-bearing in that sentence. The run's **execution** dispatches — the
rostered `Dispatch: YES` tasks — also cost an agent, and are deliberately **not** tiered:
they are how the work gets done, not how it gets checked, and a `light` run dispatches them
exactly as a `standard` one does. Tiering those would not reduce the cost of verification, it would
reduce the plan.

**The tier is declared, not assumed.** Write it in the Preflight report
(`review-scope: light — prose edits to 3 skill files`) and repeat it in each gate report.
An undeclared run is `standard`. This is the honest-gates disclosure rule applied to review
effort: downgrading silently and downgrading openly produce the same diff, so the
declaration is what makes the choice reviewable.

**Why this exists.** A review pass is not free and does not have a fixed value: dispatching
four agents over a 160-line prose change costs more than the change and returns findings
about the reviewing apparatus rather than the product — measured at ~800k tokens for a
160-line prose plan (one owner's plan, undated). Running the same four over an auth rewrite
is cheap insurance. The failure this table prevents is the one that is invisible without it
— machinery whose cost nobody compares to what it is protecting, because no rule asks.

**Why the criteria are diff-shaped rather than prose-shaped.** Suppose `light` were defined
as *"prose or config edits, or one file, or no new executable behavior"*. Almost no real plan
would qualify: a plan is multi-file by construction, so every plan would fall through to
`standard` and the damping term would never engage. A criterion that cannot be met is not a
conservative default, it is a dead branch — so the bar is a size the diff can actually be
measured against, and the escalation is carried by the risk list rather than by making the
lower tiers unreachable.

### Escalation: risk raises a tier, size never does

**A tier is a floor, not a ceiling.** Escalate mid-plan when the diff turns out riskier than
it looked — say so in the gate report; do not quietly de-escalate, which is what the
declaration exists to catch.

Two rules govern which direction an ambiguity resolves:

- **Touching a risk-listed area sets `high`**, whatever the size. Small and dangerous is
  still dangerous; the `high` row's list is the authority on what counts.
- **The floor escalates the plan, but Tier-1 attaches to the risk-listed task.** Everything
  in the `high` row that reads an *integrated* diff — both evaluators, the second Tier-2
  pass — is plan-level and runs for the whole plan, because a risk-listed task's blast
  radius is not confined to its own diff. Tier-1 is the exception: it reads one task's diff
  in isolation, so it runs for **the tasks whose `Scope:`/diff touches the risk-listed area,
  plus any task carrying `Review: required` — and for no others.** A `high` declaration
  therefore names the tasks it binds (`review-scope: high — tasks 1.1, 1.3 (schema
  migration)`); one naming no tasks is read conservatively, as binding all of them.

  **Why the floor is per task for Tier-1.** Suppose two genuinely risky tasks — a schema
  migration and a token check — set a plan to `high`: a plan-wide floor then buys a Tier-1
  dispatch for every ordinary rendering edit beside them. The risk is real and the
  escalation is correct; what is wrong is the *unit* it applies to. A rule that
  escalates by plan cannot express "this task is dangerous", which is the only thing the
  risk list ever actually knows.
- **Size alone never escalates.** A large diff of prose, or of mechanical renames, is a big
  `light` change, not a `standard` one. Volume is not risk, and treating it as risk is the
  "when in doubt, go heavier" instinct that reintroduces the cost this table removes.

### Composing with the plan format

The format ladder (Direct / Light / Standard / Master) and the tier above answer **different
questions**, and a plan carries both at once. Resolve them this way, always:

> **The format decides the review's SHAPE. The tier decides its DEPTH.**

| From the **format** — shape | |
|---|---|
| Direct, Light | Tier-2 runs over the **whole plan diff**, once, before close-out |
| Standard, Master | Tier-2 runs **per stage gate** |

| From the **tier** — depth | Tier-2 passes | Tier-1 (which tasks) | Evaluator |
|---|---|---|---|
| `none` | none | no | no |
| `light` | **one**, whatever shape the format sets | no | only at a gate carrying `(judgment)` or whose stage has Outcomes, unless a recorded goal command decides it |
| `standard` | one **per** unit the format's shape names | no | only at a gate carrying `(judgment)` or whose stage has Outcomes, unless a recorded goal command decides it |
| `high` | that, plus a second independent pass | **yes — risk-listed tasks only** | **yes, always** — every gate and close-out |

**How to read the two together without them fighting.** The format's row names the unit a
Tier-2 pass *would* cover if the tier bought one pass per unit: the whole plan diff for
Direct/Light, one stage for Standard/Master. The tier then says **how many passes you get**.

- `light` buys **exactly one pass, always over the whole plan diff, before close-out** —
  whatever the format. One pass cannot be "per stage" in a multi-stage plan; there is only
  one of it, so the only unit it can cover is the whole diff. The format's unit is what
  `light` overrides, and this is the single place the two axes genuinely cross.
- `standard` buys **one pass per unit the format names** — per stage for a Standard or Master
  plan, once over the whole diff for a Direct or Light one.
- `high` buys that plus a second independent pass, and adds Tier-1 for its risk-listed
  tasks.

A shape in the `light` row ("over the whole plan diff") and a shape in the format row ("per
stage gate"), with no rule for which wins, leave a Standard plan at `light` reading as either
1 review or N. Resolving it the format's way would make `light` and `standard` identical for
every multi-stage plan, retiring the damping term for the exact case it exists for — so
`light` overriding the unit is not a wrinkle, it is the point.

**Tier-1 is the tier's alone.** The format never sets it: `high` runs it for its
risk-listed tasks in any format, including Light, and no other tier runs it at all without a
task's `Review: required`. A format row saying "never per task" would contradict `high`'s
Tier-1 column for precisely the Light-plan-touching-auth case the risk floor exists to
settle.

**Resolve a disagreement by the risk floor, not by "take the lighter option" and not by
"take the heavier".** Both of those are instincts standing in for a rule. The rule is: apply
the format's shape and the tier's depth, and let a risk-listed area override the tier upward.
A Light plan touching an auth path is a *small plan doing a dangerous thing* — it gets
whole-diff shape (from Light) and `high`'s depth (from the risk floor), with Tier-1 on the
task that touches auth rather than on all five. A Light plan editing
four prose files is a small plan doing a small thing, and gets exactly one review; a "never
take the lighter option" rule would make that case pay `standard`'s price for no protection,
which is the asymmetry the risk floor removes.

Master plans declare a tier **per sub-plan**, from that sub-plan's own diff — sub-plans are
independently executable, so a `high` sub-plan must not be diluted by a cheap sibling, and a
cheap sibling must not inherit the `high` one's cost. **The master's own close-out takes the
highest tier any sub-plan declared**, since per-sub-plan tiers leave the master itself
ungoverned and its close-out is the only pass that sees the integrated result — a `high`
sub-plan's risk does not stop being the master's because a cheap sibling landed after it.
(`../references/master-plans.md` applies this at step 5; the rule is stated here because this
file is the authority on tier selection.)

**Why this is written down at all.** Without it, the two axes are each internally consistent
and silent about the other, so an executor meeting a Light plan that declares `standard`
could run one review or four and be equally compliant either way. That is not a tie the
executor should break on instinct — instinct breaks it differently each time, and taking
the lighter option skips an evaluator this table requires.

---

**Review opt-out.** A review the declared tier mandates is default-on. Disable it per task with a `Review: skip` field on the task line (use for non-code or throwaway tasks), or globally for a run when the user opts out (state it once at Preflight, mirroring the goal-evaluator opt-out). A task may also opt *in* below `high` with `Review: required`, which is how a plan buys per-task review for the one task that warrants it without raising the whole plan's tier. The author marks it only on a task whose `Scope:` names a risk-listed path; what counts as one is in `review-scope.md` § Risk-listed names a path, not a project. A word in the task's text — identity, permission, protocol — never earns it. Trivial/non-code diffs — docs-only, config-only, pure version bumps, comment-only — are auto-skipped without needing an annotation. **Two reasons excuse a mandated review, and the list is closed at two: an evidenced user opt-out, and a trivial/non-code diff.** A `code-reviewer` that cannot be dispatched is not a third one: it is the Stop condition for a mandated review that cannot be run (`../SKILL.md` § Stop conditions), on the same ground as an unrunnable test. An unrun review is not a passed review, and it leaves an artifact indistinguishable from a reviewed one — which is why the resolution is the user's to choose and not the executor's to assume.

**A tier that does not mandate a review is not an opt-out at all.** It is the machinery
scaling as designed, and it is recorded by the declared tier rather than by a quote — the
tier *is* the evidence, checkable against the diff it was picked from. Keep the two apart in
the gate report: "Tier-1 not run — tier is `light`" is a *scope* statement; "review skipped —
user opt-out, Preflight: '…'" is an *opt-out* statement. Conflating them is how a skipped
mandate hides inside a legitimate tier.

**An opt-out is evidenced, not asserted.** The two reasons differ in who authors them, so
they carry their evidence differently. A **trivial/non-code diff** carries its own evidence:
it is a property of the diff, and any later reader can check it against the diff itself. A
**user opt-out** is a claim about something that happened outside the artifact, and the only
person who can author it is the user — so recording it means **quoting the user's own
words**, with where they were said. For example:

```
Review skipped — user opt-out, Preflight: "don't bother with the reviewer on this one"
```

**A `Review: skip` annotation counts as an opt-out when Preflight's snapshot lists it**
(`../SKILL.md` § Dispatch roster and capability probe, step 3), and the snapshot is what makes it
evidence. The executor writes to the plan file throughout the run, so an annotation read
at skip time proves nothing about who put it there; one recorded against the run's base
commit was demonstrably there before the run began. An annotation missing from that
snapshot is an executor-authored note, worth exactly what the executor's own judgment is
worth here — nothing. Cite the snapshot line rather than the task line.

**Executor judgment is not an opt-out.** *"I judged the review unnecessary"*, *"the diff
looked small to me"*, *"there was nothing a reviewer would have caught"* are the executor
deciding on the user's behalf and then recording the decision as though the user had made
it. That is the same substitution the executor trailer exists to expose (Step 3.3 rule 7),
one axis over. A skip reported without a quote or a cited annotation is an **unevidenced
skip**: it reads downstream as a review that did not happen, because that is what it is.
The point is not to make opting out hard — it is to keep the legitimate path open and
auditable, so that "the user asked me to skip this" and "I decided to skip this" stop
producing the same record.
