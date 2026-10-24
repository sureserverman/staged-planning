# Stage-gate failure: triage, class repair, remediation budget

Invoked from `executing-plans` Step 3.5 when a gate check fails. The exit criterion that
decides when repairing stops lives in the trunk, beside the gate itself; so does the
class-repair rule this procedure applies — `../SKILL.md` § **A bug found during execution is a class**.
This file is the *gate's* application of that rule: the triage, the ordering, and the bound
on the loop.

For v2 runs the [execution-state contract](execution-state-contract.md) governs
accounting. Use begin-round to reserve a new attempt, record-verification for actual
declared checks, and complete-round to finish the reserved assessment. At the authored
checkpoint (default two completed rounds), record strategy-review with defect-family
IDs, measured gain/false-rejection/cost or null and repair/redesign alternatives.
This assessment neither resets spent work nor grants a round. An evidenced owner
extension remains effective across restart. Continue already-authorized diagnosis;
surface any proposed new architecture or scope through an owner decision. A no-go
qualification is separate from that disposition. Do not infer either from prose.
The legacy counter procedure describes unowned legacy state only; never apply
its manual writes to an owned v2 run.

**If the gate fails:**

A gate is one caller of the class rule, and the sharpest one. Detection at a gate is
goal-scoped (the evaluator re-reads the whole artifact every round) while repair defaults to
instance-scoped — so a class with N instances costs ≈N rounds, each one looking like fresh
news. Triage before repairing, and bound the loop.

1. **Classify every finding by severity** — the same **Critical / Important /
   Suggestion** taxonomy the review tiers already use (Step 3.3 rule 6), so a gate
   finding and a review finding are graded on one scale rather than two.
2. **Run the class rule: diagnose evidence-first, then name the set it belongs to.**
   Diagnose evidence-first here — this is the most fix-prone moment in the whole
   workflow (a failed gate, under a bounded round budget), which is exactly where
   "Fix And Forget" produces a plausible-looking repair for a misdiagnosed cause.
   The order matters and is not decorative: a set derived from a wrong root cause is
   a *wrong set*, so the class sweep in step 3 would then sweep confidently over the
   wrong population and report green. Evidence first, then generalize.

   The trunk rule states how to derive and enumerate the set, and that a sweep finding
   members the `Scope:` did not means the plan's `Scope:` line is wrong and is fixed as part
   of the repair. **Two things the gate adds to it:**

   a. **The failing task's `Scope:` field is where the gate starts**, if it declares one —
      that is what the field is for
      (`../../planning-projects/references/task-fields.md` § Scope marking). It remains a
      starting point, not an authority: a `Scope:` is only as good as the sweep behind it,
      and a truncated authoring command is one way for one to arrive short.
   b. **Write the enumeration command into the gate report**, not merely into a commit
      body — the gate is what the next remediation round reads, so the command has to be
      where that round will look.

   A gate failure is usually an integration problem rather than one task's bug.
   Repairing the instance and leaving its siblings is what converts one class into
   N rounds.
3. **Add a test covering that interaction** to the relevant task. Where the finding
   is set-valued, that test is the **sweep over the set derived in step 2** (the
   class-predicate rule in `../../planning-projects/SKILL.md`), not a check on the
   single file that failed — an instance-shaped check cannot fail on the siblings
   that make the class. Fix **every member the sweep returns in this round**, not
   just the one the gate happened to report: a class repaired one instance per round
   is the oscillation the budget exists to bound, and bounding it is not the same as
   converging.
4. **Run that task through its Red-Green loop again.**
5. **Re-verify at fix-scope, plus the sweep.** Re-run the failed check(s), any check
   whose inputs the fix touched, and the step-3 class sweep — not every gate check
   from scratch, and **not the gate's stage-scope command again**. That command ran
   once when the gate was first attempted and is not re-bought per round
   (`../../planning-projects/references/test-scope-tiers.md` § *A stage-scope pass runs
   once per gate entry*); the gate goes green on this fix-scope pass plus that recorded
   result. Disclose both in the gate report, per honest-gates — "stage-scope at entry,
   fix-scope after round 2" is short and true, and it is what makes the recorded pass
   auditable rather than merely asserted.

**Remediation budget — default 2 rounds per gate.** One round is classify →
repair → re-verify. Required review/evaluator verification of an active repair
belongs to that reserved round, including at its ceiling; complete it only after
all declared verification returns. A separately initiated critique reserves new
work through begin-round. An owed review of an unread redesign is verification,
not extra admission. Only a Critical / Blocking fix re-dispatches its required
review; Important / Material fixes close on fix-scope evidence. Neither review
wording nor a strategy assessment extends the budget. The owned state contract
is authoritative; historical integer accounting is not a v2 mutation instruction.

**What a round costs, and why the default is 2.**
Step 2 above carries evidence-first root-cause diagnosis, three-way set derivation
with the enumerating command written down, and reconciliation — the bulk of a round's
work. The default is 2 deliberately: a budget raised on speculation is worse than one
left alone, and a third round buys another *repair* attempt when the thing that actually
runs long is the *diagnosis* inside round one. A gate that spends the full 2 rounds and
still closes with an open question is the expected shape, not a budget failure — **exhaustion with a residual list is a legitimate
outcome, not a defeat**, and escalating it is cheaper than a third round that
re-diagnoses from the same evidence. Raise the number on a stage only when the *repair*
was the part that ran out of room, and say so on the stage when you do.
Without that, a gate has two counters and one limit: repairs bounded at 2, while
fix → re-review → new findings → fix runs until the reviewer goes quiet, which for a
fresh judgment agent is not a reachable state. It is a default, and a plan may override it by stating a
different number of remediation rounds on the stage; **count the rounds and report
the count** in the gate report ("gate green — remediation round 2 of 2"). An
uncounted loop is how a gate reaches its fourth round with nobody noticing the
third.

**Stop repairing when the exit criterion is met** — no Critical remaining,
every Important fixed, and no finding-independent condition outstanding — the `backlog` is not a disposition for a defect (trunk, § Exit
criterion). A defect this session genuinely cannot fix — the fix needs a device, a credential,
an upstream release, or an environment this session lacks — escalates with its blocker named; that is the only exit that is not
a repair, and it is the user's call from there. Do not spend a round chasing Suggestions, and do not spend one trying to make a
judgment agent go quiet.

**On budget exhaustion, escalate with the residual list.** Report the findings
that remain, their severities, and how the rounds were spent. This is a documented
**Stop condition** (trunk, § Stop conditions) — not a failure to hide, and not a licence to keep
looping. The user decides between another round, returning to
`planning-projects`, and shipping with the residual recorded.

## A redesign the gate closes on

An Important fix closes on its fix-scope re-run, with no re-dispatched review
(`stage-gate.md` § Independent evaluator for non-command checks). That is right for a fix inside code the
review already read. It is wrong for code the review never saw: a round that answers a
finding by replacing a parser ships the replacement unread, because no later review is owed
— and that holds in round 1 of 2 as much as in the last one.

Two terms, decided from the round's diff:

- A **repair** is a change inside code the review read — a condition corrected, a branch
  added, a value fixed in a function the reviewer's diff already contained.
- A **redesign** is a new file or function, or a replacement of logic the review read — the
  reviewer's reading of that code no longer describes it.

**A redesign no review has read when the gate closes — whether the gate closes green or on an
exhausted budget — gets one review of the redesign's diff alone, at the tier that funded the
original review, or a deterministic substitute**: a battery entry that answers the question
the reviewer would ask of that code (does the replacement still refuse what the original
refused?). Every unread redesign of the gate goes into that one review. The review line
records which: `round K: redesign — reviewed by <agent name>` or
`round K: redesign — battery <name>`. A repair closes on its fix-scope re-run. Below tier `light`, nothing
is added: at `none` no review read the original either.

This review is an exception to two rules. First, it is not a remediation round and does not
count against the budget. Second, it is owed though nothing Blocking was fixed
(`stage-gate.md` § Independent evaluator for non-command checks, one dispatch per role per
gate). Its findings take the exit criterion like any other, repaired
within the rounds the budget has left; a Critical among them on an exhausted budget is
escalated with the residual list, as exhaustion always is. A redesign made to answer this
review is not reviewed again: the gate report names it `round K: redesign — unread`, so the
loop ends on the budget, never on a reviewer going quiet. One review line is written per
round whose redesign it covered.

## Remediation that re-runs a live check

A live or device-bound check — a real bot session, a device, a remote host — costs minutes per
run, and a fix fitted to the one capture the failed run left behind passes its fake and fails
the next live run. Repeated, that is a remediation loop that costs a live run per turn which a host-side
run ends in seconds. So the round's evidence is gathered on the host
first.

**Before a remediation round re-runs a live or device-bound check, the fix is proven against
every real capture or fixture of that kind the repo holds, plus any the failed run produced,
and the sweep command is recorded in the commit as a `fixture-sweep:` trailer**
(`fixture-sweep: pytest tests/captures -k parse  # 14 captures`). The live re-run comes
after, and it is the confirmation, not the search.

**A rule derived from a capture states the property it checks, and its test includes one real
capture that differs from the source in its incidental parts** — another session, another
id, another ordering. A rule written from one capture tends to encode that capture's
accidents; the second capture is what tells the property from the accident.

**A fake that encodes the behaviour under test is named in the gate report as "unproven
against the real system".** A stub that returns the shape the fix expects proves the fix
agrees with the stub. It stays a useful test of the code around it, and the label keeps it
from being read as evidence about the system it imitates.

Position: only a round that re-runs a live or device-bound check. A round whose
checks all run on the host pays nothing here. `plan-flip-audit.py --repo` reports a
`Stage N gate remediation` or `Stage N gate, remediation` commit, dated on or after the plan's
own date, for a gate with a `**Live check` line and no `fixture-sweep:` trailer (finding 10,
advisory). It matches by stage number and date, so plans sharing a date and stage numbers
read each other's commits; the report names each commit for the reader to place.

## The read-only budget projection

`plan-progress.py --budget-check` reads validated v2 accounts. New work is admitted
only by begin-round; active verification/completion stays allowed at the ceiling.
State errors never establish permission or exhaustion. Ambiguous positive legacy
counters require original migration evidence; do not increment or reset them as
part of adopting v2. The operation/output contract has one authority:
[execution-state-contract.md](execution-state-contract.md).

**Read the check by what it printed, not by its exit status alone.** Run it from the repo
root by the script's full path —
`python3 <planning-plugin>/skills/executing-plans/scripts/plan-progress.py --budget-check` —
because the script finds the state by walking up from the working directory. Exit 2 is a
spent budget only when stderr carries `budget_exhausted:`; Python's own `can't open file`
also exits 2, so a mistyped path would otherwise read as an exhausted budget. `state_error:`
(exit 3) is an instrument fault. Exit 0 with nothing on stderr reports no spent budget. Anything else
is a broken invocation: fix it and rerun before reading it as either answer.
