# Reasons behind the honest-gates rules

Companion to `../SKILL.md`. Each heading names the rule it belongs to and holds only the
reason behind it — with a worked example where one helps, and a lead-in so it reads on its
own. The rule sentence itself
is not repeated here: the trunk is its only definition site, and
`extraction-classification.md` pins it there. A copy in this file would be a second site
that can drift.

## Prohibited — why an unannotated amendment is indistinguishable from a cheapened gate

The amendment bullet says a legitimate amendment is annotated with the authorizing rule and
the value it replaced. The reason disclosure is the whole difference: without it, a
recalibrated gate and a quietly cheapened one leave identical artifacts, which is the same
reason a scope change must be disclosed rather than merely made.

## Prohibited — the authored-stub pair

An executor that writes the scripts its own gates run can close them on stubs: a body that
ends `echo OK` passes, and an unconditional `exit 2` gets ticked `[x]` with *(amended —
exit 2)*, the block serving as the excuse. A rule that never asks who wrote the gate cannot
see either.

## Prohibited — suites dropped "for disk/time"

A suite removed from a gate command "for disk/time" lets a sub-plan close green on less
evidence than its gate names. Disk and wall-clock are real constraints and arguments for re-scoping the plan —
never for re-scoping the evidence a written gate demands. The reconciliation with the tiering
policy is deliberate: `test-scope-tiers.md` narrows a *declared stage-scope command* when it
crosses ~5 minutes and requires the gate report to say which scope ran; that is scope, and
disclosed as scope. Dropping a suite a written check names is an amendment, and cost never
authorizes one.

## Prohibited — the proxy-data example

Suppose a gate names first-time users finishing a task in under 20 minutes, and the evidence is
runs by someone who already knows the optimal path. The evidence is real, and it measures a
different population than the gate names.

## Prohibited — the self-grading example

Suppose a run reports 7% of frames over budget and is stamped `Pass: true` against a "≥96%
within refresh" bar. The number is reported; the verdict it earns is not. A reader who reads
only the verdict never sees the miss.

## A behavioral claim — why a correction is a new claim

A commit that corrects an overreach can introduce new false claims of its own. A
correction written from a reviewer's negative finding, without verifying the positive claim
replacing it, is an unchecked claim like any other.

## A behavioral claim — why an absence claim names its scope

The absence-claim rule requires citing the query and the scope it ran over. The reason: the
claim is only as strong as the scope, and a scope narrower than the reader assumes is how an
absence claim turns out false.

## A test does not exist until its mutant dies — why the mechanism question comes first

The mechanism question sits first in its section because it is the one choice the later
rules cannot repair. Suppose a checker is built as a pattern matcher over what prose means:
each review round finds a sentence that evades it, each fix admits the next, and the three
numbered rules can all be followed while the checker decides nothing. A rule not consulted
at the moment of choosing is not in force; hence its position, first.

## A test does not exist until its mutant dies — why the test-first rule needs backing

`../../executing-plans/SKILL.md` Step 3.3 opens "the test is written first and must go RED
for the right reason" — correct, and unenforceable after the fact: a test written first and
a test transcribed from the fix are byte-identical in a passing suite. So every failure the
section's three rules answer remains possible with that rule in force.

## A test does not exist until its mutant dies — hardening buys one evasion class per round

Each hardening pass rejects the counterexample you were shown and admits the next one, while
the suite stays green and reads like progress.

## A test does not exist until its mutant dies — rule 1's rationale

A fix scoped from the counterexample that revealed it will regenerate the finding on the
next sibling, and each round reads as progress — which is why the set is written down as a
command before the fix.

## A test does not exist until its mutant dies — the masking pair

A suite can stay green with a whole clause removed, or with two guards that each keep the
single negative fixture clean — so deleting *either alone* looks harmless. No individual
test is wrong, and no reader of the suite sees it. A mutation battery, one mutation per
guard, reports every such pair as survivors; one isolating fixture per guard kills them.

## A test does not exist until its mutant dies — why fixtures come from the requirement

Suppose the requirement names a directory level the code does not yet create, and the
fixture is built without it — because that is what the code then accepts. The fixture now
asserts the accepting behavior as correct, and the whole suite stays green over the defect
it was written to catch.

## A test does not exist until its mutant dies — why the cause, not the outcome

A non-discriminating assertion is usually an outcome assertion standing in for a cause. An
outcome has several producers; only the cause names the mechanism under test.

## A test does not exist until its mutant dies — why the section is not covered by the two before it

The *Prohibited* and *A behavioral claim is a gate too* sections catch a false sentence
about behavior. This one catches a *true* sentence — "the suite passes" — that means less
than the reader takes it to mean. Nothing in a passing run distinguishes a test that would
catch the regression from one that would not, which is why the distinguishing step has to
be performed rather than assumed.

## Changing a contract — the framing

Every other honest-gates rule reads the artifact in front of you. This one governs a change
whose effect lands elsewhere: a parsing rule, marker vocabulary or classification predicate
re-reads every document already written, under rules their authors could not have followed.

## Changing a contract — the marker-change worked example

Suppose one change makes a plan count as closed only when it ends with a `**Shipped:**`
line — retroactive over every plan already written — while every plan closed before the
change ends with `**Verified:**`, which no longer counts. **Every one of those plans
re-opens** and reads as in-flight work, though nobody touched it, and nothing in the diff
shows it. Only a sweep of the existing corpus finds them, so each can be backfilled or filed
as a migration entry.

## Changing a contract — what an estimate is

A migration entry that says "~20+" records that the sweep was never run; an uncounted set
cannot be backfilled or checked off.

## Changing a contract — the adds-net argument

The rule removes nothing — no other honest-gates rule looks at documents the change did not
touch — and costs one sweep per contract change, paid only by the change that earns it. What
it catches that nothing else does: a change that is right in the diff and wrong in the
corpus, where the diff, the suite and the rule are all green and the whole of the damage
sits in files no one opened.

## Reporting — host fixtures reported as device acceptance

Playwright runs against **host fixtures** can be reported as browser acceptance of the
product while nothing is deployed to a reachable device. Every individual claim is true — the tests ran, and passed. What is false is the implied subject: evidence
about the host, presented as evidence about the artifact.

## Reporting — figures that drift, and a corpus with no selection rule

Before/after counts recorded round after round go wrong by construction: the "after" numbers
go stale when the same commit keeps editing the files, and "before" numbers transcribed
rather than measured drift by one. A different shape: a false-positive rate "over N plans"
does not reproduce when no selection rule for those N is stated — a sha would not help there;
the missing line is the one naming what was counted.
