# A bug is a class — how to name the set, and where the sweep stops

The trunk (`../SKILL.md` § A bug found during execution is a class — sweep it, fix every
instance) carries the rule and its four steps, because it must bind every run. This file
carries the reasoning that keeps the rule from being read narrowly.

## Where it fires

Wherever a bug surfaces: a RED test inside a Red-Green loop, a finding from either review
tier, an evaluator finding, a failed gate check, or something you simply notice while editing
a file. It is **not** scoped to gates — the gate-failure branch is one caller of this rule,
not its home.

## Diagnose before generalizing

Diagnose evidence-first before naming the set. The order is not decorative: a set derived
from a wrong root cause is a *wrong set*, so the sweep would then run confidently over the
wrong population and report green. **The step begins where the failure becomes *unexpected***
— the first RED of a Red-Green cycle is the test doing its job and has nothing to diagnose,
which is why the loop's second-cycle threshold for evidence-first diagnosis stands rather
than being overridden here.

## Two shapes, and only one of them can be enumerated

Before reaching for a command, decide which shape the class has, because the two need
opposite techniques and the wrong one cannot converge.

**Presence-shaped** — every site that *does* X does it wrong. The members share a string, so
`grep` finds them, and enumeration is both correct and cheap. This is the common case and the
rest of this section is about it.

**Absence-shaped** — some sites that *should* do X don't. The members share nothing, because
what makes an instance an instance is a call that is missing. **No command can list them.**
An enumeration here returns the members you happened to think of, which is why each round
finds one more just outside the last boundary you drew.

**The tell is the fix, and it is mechanical: a repair that *adds* a call means the class is
absence-shaped.** Where the repair changes a call that already runs, the class is
presence-shaped and a sweep will find its siblings. Symptoms are no help here — "it didn't
publish", "it didn't lock", "it didn't invalidate" all read like ordinary bugs, and the shape
only shows in what the fix has to do.

For an absence-shaped class, assert the property instead of listing the members. Prefer, in
this order — which is the reverse of the instinct:

1. **An invariant test.** After every operation that can affect the property, assert it holds.
   It names no members, so it has no boundary to get wrong, and it fails on the path nobody
   thought of. This is the only one of the three that ends the class rather than bounding it.
2. **A structural rule.** A check phrased so membership is decidable without listing members —
   "only a screen fills itself", "no module outside X reaches Y". A wide boundary, but a
   boundary.
3. **A funnel.** Make one code path the only way to reach the effect. Cheapest, most tempting,
   and weakest: its boundary is exactly the set of callers that route through it, which is the
   set you already got wrong. A funnel is a good repair *after* an invariant pins the property,
   and a trap when it is the whole repair.

## A repeat finding is not a new bug

**A second finding inside a class you have already remediated is evidence the set was misnamed,
not evidence of another instance.** Do not fix it and re-sweep — that is the oscillation named
below, and one more round of it buys exactly one more member.

Stop, reclassify the class by shape, and replace the enumeration with an assertion of the
property. Say in the gate report that you changed technique and why. A round spent changing
method is worth more than a round spent extending a list, and the remediation budget is not
large enough to discover a set one member at a time.

## Naming the set

Enumerate it with a command — grep the defect's distinguishing string, list every sibling of
the failing artifact's kind, list every caller of the changed symbol. Start from the task's
`Scope:` field where it declares one; that is a starting point, not an authority, and a sweep
that finds members the `Scope:` did not means the plan's `Scope:` line is wrong and is fixed
as part of the repair. **When no `Scope:` exists, you still enumerate** — and that is the
common case, since a defect rarely surfaces exactly where some task happened to declare its
set. An undeclared set is still a set; skipping the sweep there quietly shrinks this rule
to a gate-only one.

Then fix **every member the sweep returns, in the same change** — not the instance that
happened to surface. A class repaired one instance per round is the oscillation the gate's
remediation budget exists to bound, and bounding it is not the same as converging; when you
see it, the repair is a technique change, not another round (above). **Write the
command down** — in the commit body, or in the gate report when a gate is what surfaced the
bug. The next round then argues with a command rather than a recollection.

## The whole project is the search space, not the plan's blast radius

A sibling instance living in a file this plan never touches is the same defect; "out of scope"
describes a plan's *subject matter*, never a defect's *reach*
(`../references/stage-gate.md` § Exit criterion — the dispositions behind it, on what a scope
guardrail actually bounds). Fixing it is the cheapest it will ever be, because the diagnosis
is already loaded.

## Where the sweep stops

It covers the defect's own predicate — whatever makes an instance an instance — and nothing
wider. It is not a licence to refactor, restyle, or repair unrelated things that merely live
nearby. **A class you cannot express as a command is a class you have not named yet** — and the usual
reason is that it is absence-shaped, in which case the answer is not a better command but the
invariant above. Where it is genuinely neither, fix the members you can identify and state in
the report what you were unable to sweep. Sweeping by feel produces a confident green over a
population nobody defined.

## It costs a command, never a dispatch

The sweep is a `grep`, an `ls`, a `git grep` you run yourself — so it belongs with the
untiered mandates (the dispatch roster, the executor trailer, the dispatch
reconciliation, honest-gates disclosure, the plan's own tests and gate checks) and runs at
**every** review tier, including `none`. A tier gates agent cost; this has none to gate.

**One dispatch-shaped consequence, named so it is not a surprise.** A sweep that pulls a
risk-listed file into the diff — auth, schema, a data-destructive path — trips the risk floor
and escalates the plan's tier (`../references/review-scope.md`), and *that* buys dispatches.
This is the sanctioned way up rather than a breach of the cost rule: the escalation runs
through the tier mechanism, is declared in the gate report like any other, and is the correct
outcome, because a plan whose blast radius just reached an auth path is a riskier plan than
the one that was declared. Say so in the gate report when it happens; never suppress the sweep
to avoid it.
