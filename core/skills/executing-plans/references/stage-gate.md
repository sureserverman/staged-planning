# Stage gate — reports, hooks, evaluator, Tier 2, and what "passed" means

The trunk (`../SKILL.md` § Step 3.5 — Stage gate) carries the gate's order, its exit
criterion and its remediation budget. This file carries everything that fires on a branch:
the report's exact shapes, the two verify hooks, the evaluator's briefing, the Tier-2 pass,
the decisions sweep, and the reasoning behind each disposition rule.

## The gate report's dispatch line

**The gate report states the stage's dispatched-vs-inline counts, and a reason for every
inlined `Dispatch: YES` task.** Read them off the executor trailers rather than from memory —
`git log --format='%h %(trailers:key=Executor,valueonly)' <base>..HEAD`, where `<base>` is the
previous stage's `"Stage N green"` commit (for Stage 1, the commit the branch started from) —
and reconcile against the roster Preflight declared. One line: `dispatch: 3 of 4 YES tasks
dispatched; Task N.M inlined — <reason>`. A stage that dispatched everything it marked says
`dispatch: 4 of 4` rather than saying nothing, so silence never has to be interpreted. A
**Light plan** has no `Dispatch` field and never fans out, so its single gate carries no
dispatch line — the requirement is scoped to plans that can have a roster, not waived where
one would be vacuous.

**An empty trailer value is `unknown`, never `inline`.** Git drops a whole trailer block at a
line it cannot parse, so a wrapped or malformed trailer returns blank with exit 0 —
indistinguishable, to the query, from a task nobody dispatched. Counting blanks as inline
invents a deviation; counting them as dispatched hides one. So resolve each blank against the
commit body, count it as `unknown` if it says nothing either, and report the unknowns:
`dispatch: 1 of 1 dispatched; 2 commits predate the trailer convention (resolved from their
bodies)`.

## The gate report's review line

**The gate report names every review that ran, the agent that ran it, and the diff it saw** —
and, for one that did not, which of the **three** reasons applies: the declared tier never
mandated it (state the tier — this is a *scope* statement and needs no excuse), or, where the
tier did mandate it, an evidenced opt-out (`../references/integration.md` § Review opt-out) or
a trivial/non-code diff. Do not report a tier-scoped absence as an opt-out; that is how a
skipped mandate hides inside a legitimate tier. One line per tier, resolving `<base>` the same
way the dispatch line does — the previous stage's `"Stage N green"` commit — and naming the
agent by a type dispatch can actually take. `goal-evaluator` is a **role**, not a registered
agent: no `goal-evaluator` agent file ships in this marketplace, so a report naming it records
a dispatch nobody can reproduce. Write the type that ran, then the role:

```
review: Tier-2 planning:code-reviewer over <base>..HEAD — APPROVE, 0 Critical
evaluator: general-purpose in the goal-evaluator role, briefed on the plan goal + stage goal + gate criteria — PASS, 2 Material
evidence: pytest tests/integration — host; Playwright e2e — container (compose); device acceptance — target device (board over ssh)
```

Each **evidence** line likewise names the **substrate** it ran on — host, emulator,
container, or target device — because "the tests passed" says nothing about where. What
that changes for the verdict (a deployed-behaviour claim whose evidence ran elsewhere) is
defined once, in `../../honest-gates/SKILL.md` § Reporting; this line is the place the
substrate gets written down so that rule has something to read.

Naming the **agent** distinguishes a dispatched review from the executor reading its own diff,
which both tiers forbid; naming the **diff** makes its coverage checkable, since a reviewer
briefed on the wrong range returns a clean verdict over code nobody looked at and "reviewed"
reads identically either way. An inlined `Dispatch: YES` task is a **deviation being
disclosed**, not one being ratified — a gate report that keeps producing them is evidence the
plan's `Dispatch` fields belong back in `planning-projects`.

## ACTION NEEDED — the one place a report asks the user for something

A gate report either needs something from the user or it does not. When it does, the ask goes
in **one** block, **last**, under this exact heading, with the options numbered so the reply
can be a number rather than a reconstruction of the choice:

```
ACTION NEEDED: <one line naming the decision>
  1. <option>
  2. <option>
```

**A report carrying an `ACTION NEEDED:` block does not also say it is proceeding.** "Two
things for you" in one paragraph and "proceeding to Stage 3" in the next is the shape that
draws a *"what do you want from me?"* reply: the reader cannot tell whether the run stopped, and the cost of guessing wrong is asymmetric —
answering a question the run already moved past is wasted, and not answering one it is
blocked on stalls the plan silently. Either the decision blocks the next stage, in which case
say so and stop, or it does not, in which case it is not `ACTION NEEDED:` at all and routes
where its kind already routes — a decision the user must make to the `backlog`, a Suggestion
to the `residuals:` line. This adds no third destination; `residuals:` keeps the definition
§ The handoff note's contents gives it.

**One block per report, or none.** Scattering asks through the narrative is the same defect
with better manners: three asks in three paragraphs is three chances to miss one.

**Tier: untiered.** This mandate costs a line of text, not an agent dispatch, so it
runs at every review scope including `none` — named here because a new mandate states the
rule that gates it rather than leave it inferred: an inferred tier gets guessed differently
by each reader.

## Platform stage-verify hook

After the stage's own gate checks pass, if the project's platform ships a stage-verify skill,
invoke it as the final gate step — it proves the stage on the real artifact, not just the test
suite. A failure there is a gate failure (handle it like any other). Brief the stage-verify
skill with the gate's tier: at an intermediate gate it verifies at stage-scope (touched-module
instrumented tests); at the final gate it runs the full device suite (plan-scope) — and that
run IS the plan-scope pass's device portion, not an addition to it (don't run the declared
`plan-scope:` device suite separately and then the hook's again). Match by project type:

| Project type (detector) | Stage-verify skill |
|-------------------------|--------------------|
| Android — `settings.gradle{,.kts}` / `app/build.gradle{,.kts}` present | a platform stage-verify skill, if one is installed whose description matches the project type (e.g. an Android build-and-smoke-test skill) — builds the debug APK, and if an adb device is attached, installs + smoke-launches + runs instrumented tests |

If no matching skill is installed, note it and rely on the regular gate checks — the absence
of a platform verifier is not itself a gate failure.

## Design-fidelity verify hook (redesign stages)

A stage whose tasks reproduce a Claude Design handoff pack (a *design-handoff* / *redesign*
task — driven by the `applying-design-handoff` skill) carries its own gate step: run that
skill's **fidelity verify loop** (capture → grade against its fidelity rubric with a separate
evaluator → iterate, max 3) as the final gate check, exactly as the platform stage-verify hook
proves a platform stage. A sub-threshold verdict that doesn't recover within the loop is a
gate failure. This is the design analogue of the stage-verify hook: a green build is not a
reproduced design.

Its separate evaluator is a dispatch, so **whether it runs comes from
`../references/review-scope.md`** like any other: never at `none`, at `light`/`standard` when
the stage's fidelity is a `(judgment)` gate check, always at `high`.

**If the hook fires and the tier does not fund its evaluator, the hook does not run — and the
gate report says so.** A fidelity loop with no independent grader is the executor grading its
own reproduction, which is the one thing this hook exists to prevent, so running it ungraded
is worse than not running it. Two ways out, both the plan's to choose ahead of time: mark the
stage's fidelity check `(judgment)`, which funds the evaluator at `light` and `standard` and
is the right answer whenever fidelity actually matters; or accept that the stage is verified
by its ordinary gate checks alone and record `design-fidelity: not run — tier <name>, fidelity
not marked (judgment)`. What you may not do is dispatch the loop and let the executor score it.

## Independent evaluator for non-command checks

**Whether it runs comes from `../references/review-scope.md` — do not re-derive it**: never at
`none`, at `light` and `standard` when the gate carries a `(judgment)` check or its stage has
`**Outcomes:**`, always at `high`. Run command checks yourself. When the tier mandates an
evaluator, dispatch a fresh one for the judgment checks, briefed ONLY with the plan goal, the
stage goal and the gate's pass criteria — never the implementation transcript or your own
summary. The session that wrote the
code grades its own work too generously. A sub-plan's gate evaluator is also briefed with its
master register Goal. The plan goal is there so a stage gate can see a gap in the plan's end
goal. A gate briefed on the stage goal alone lets that gap survive every round, to be found
first by the close-out evaluator, the first reader given the plan goal. Whether an evaluator runs is the
tier's call alone (`../references/review-scope.md`).

**At a stage with `**Outcomes:**`, the evaluator is a demo, not a reader.** It does not read
the code or the diff. It uses the built product the way the goal's user does, by the route
they take, and reports what happened. Code-reading is the Tier-2 reviewer's job; nothing else
at the gate touches the real environment. A `(judgment)` check at the same gate that no demo
can settle still goes to a reader briefed with the plan goal, the stage goal and the gate's
pass criteria, in the same batch.

**Its brief is generated, never written.** Run

```
python3 <planning-plugin>/skills/executing-plans/scripts/stage-brief.py demo --plan <plan> --repo <repo> --stage <N>
```

It writes `proof/<plan>/stage-<N>/demo.md` — one section per Outcome, the plan's text quoted
word for word — and prints the brief: the plan's goal (its `(goal)` gate checks), a
sub-plan's master register Goal, the stage Goal, the gate criteria and the Outcomes verbatim,
the premises Step 3.0
could not check, the devices, and how to act as the user on this platform (on Android, a
probe app from an installed platform stage-verify skill, which shares to the app and asks it
for files as another app does). **Dispatch the evaluator with that output exactly as
printed** — do not summarise it, reword an Outcome, or add a fallback. The evaluator fills in
`demo.md`, and the `Stage N green` commit carries it (or, with `proof/` local, leaves it on
disk): the git hook refuses that commit unless every Outcome's section quotes the plan, reads
`Verdict: holds`, and has evidence. Its Outcomes are held to the worksheet as first
committed, so a worksheet rewritten later does not move them; with `proof/` local the
worksheet has no history, and the copy on disk is the baseline — so deleting the plan's
Outcomes together with both reports goes unseen there. Limits the hook cannot decide: an
Outcome dropped before the worksheet's first commit never reaches the baseline, which is why
the worksheet is committed with the stage's first task; a worksheet moved into place with
`git mv` has no first add, and its current copy becomes the baseline; an owner note counts
toward the notes a dropped Outcome needs whenever it was written; and the evidence's length
says nothing of its truth. The evaluator's honesty and the Tier-2 reader carry these. To demo again after a fix,
delete `demo.md` first — `stage-brief.py` never overwrites a report.

The demo is this gate's evaluator, so it follows the tier: a plan declaring
`review-scope: none` runs none, and its green commit needs the premise worksheet only. Where
the tier mandates it, the one stand-in is the owner's evidenced opt-out: a `## Not demoed`
section in `demo.md` quoting their words (`owner, <date>: "<words>"`). A reason in the
executor's own words is not one, and the hook refuses it.

With no device or environment to drive, the evaluator cannot demo, and that is a Stop
condition at a tier that mandates it — not a fallback to reading the code. A reader
grading Outcomes from the diff passes a feature that crashes on first use, and a brief
written by hand paraphrases an Outcome away or lets a test stand in for the demo. Prose and
templates bend; a generated brief and a report the commit hook reads do not.

**Once the tier mandates it, the list of excuses is closed at two** — an **evidenced** user
opt-out, or, **below `high` only**, a gate whose every check is a command and whose stage has
no `**Outcomes:**`. There is no third
reason: an evaluator that cannot be dispatched is a Stop condition, not a skip. A tier that
does not mandate one is not an excuse at all but the machinery scaling as designed, and it is
reported as scope (`evaluator: not run — tier is light, no (judgment) check or Outcomes at this gate`)
rather than as an opt-out.

**Why the command-only excuse stops at `high`.** Below `high` it is not really an excuse: the
tier already says "only at a gate carrying a `(judgment)` check or Outcomes", and an
all-command gate with no Outcomes has neither, so the two conditions name the same gates and
the excuse is a restatement. At `high`
the tier says **always**, and there the excuse would contradict it — collapsing `high` into
`standard` for the one column where they were meant to differ. The evaluator grades whether
the *goal* was met, which a green command check does not establish; at `high` that question
is exactly the one worth paying an agent for.

**Every finding it returns is a class sample**, so the disposition of one is settled by
`../SKILL.md` § A bug found during execution is a class — sweep it, fix every instance — an
evaluator reading the artifact black-box routinely names one instance of something that is
true of several, and it has no way to know that.

**Describe the dispatch as `Stage N gate evaluator`.** The dispatch log keeps the Agent call's
description, and `review-ledger-check.py` counts an evaluator claim only against a dispatch
whose description names the stage and the evaluator role (§ Checked against the dispatch log).

**Brief it to grade by severity, not just pass/fail** — a bare pass/fail gives the loop
nothing to terminate on, because a fresh judgment agent reading a real artifact essentially
always finds *something*, so "no adverse findings" is not a reachable state. Require, for
each finding, exactly one of:

| Severity | Meaning | Consequence |
|----------|---------|-------------|
| **Blocking** | the goal in scope is not met — the stage's at a gate, the plan's at close-out; at a gate also when the stage's finished output already falls short of the plan goal and no later stage is planned to change it | must be fixed; the gate does not pass |
| **Material** | real defect, goal still met | **fixed**, with its class swept; the `backlog` is not where a defect goes |
| **Minor** | nit, polish, taste | recorded in the gate report and carried into the stage handoff note; never blocks |

Blocking maps to Critical, Material to Important, Minor to Suggestion, so both scales
resolve to the one exit criterion in this file. An evaluator FAIL carrying no Blocking finding
is a **pass with recorded residuals**, not a failure — tell the evaluator so explicitly, or
it will withhold PASS to seem rigorous and hand the loop an unsatisfiable condition. **Tell it
too that it returns only after its own background work has finished or been stopped, and says
which**: a suite or probe it started in the background keeps running after its verdict
arrives.

**One dispatch per role per gate unless something Blocking was fixed.** A Material finding
is fixed and its fix proven at fix-scope by the executor; it does **not** re-dispatch the
evaluator, and an Important finding does not re-dispatch the reviewer. Re-dispatch is owed
only to a Blocking / Critical fix, because only there is the verdict itself in question. One
review is owed beyond that: a redesign no review has read when the gate closes
(`gate-failure-procedure.md` § A redesign the gate closes on).
Measured over 13 gate evaluators (one owner's master plan of three sub-plans, 2026-09-10/11):
all 13 returned Material findings, every one fed a remediation commit, and the re-dispatches
after Material-only rounds cost 28 minutes for no changed verdict.

**Never brief it with a command check.** The suite is the executor's to run; an evaluator
handed *"the stage-scope suite passes over the committed tree"* as a criterion re-runs the
suite itself. Measured (one owner's runs, undated): an evaluator handed an 11-minute suite
took 16.6 minutes; one handed `tests/unit` took 20. Brief it with the plan goal, the stage
goal and the `(judgment)` lines only.

## Deep code review (Tier 2)

Whether it runs, and at what shape, comes from `../references/review-scope.md`. The evaluator
verifies *goals* black-box; this is the complementary *white-box* pass: dispatch
`planning:code-reviewer` (read-only) over the **full stage diff** plus the stage's collected
`**Review notes (Task N.M):**` lines. Describe the dispatch as `Stage N Tier-2 review`; the
ledger check counts it only when its description names the stage and the review role. It is a gate criterion, not advisory — a **Critical**
here is a **gate failure**. Important findings are **not free either**: each leaves the gate
**fixed**, per the exit criterion, which governs every gate pass and not only one reached
through the failure branch. Suggestions are recorded. This is the only point where findings
are judged against the *coherent stage*, so cross-task issues Tier-1 could not see
(duplication across tasks, an abstraction that should have been shared) surface here. **Each
finding is repaired as a class** per `../SKILL.md` § A bug found during execution is a class —
sweep it, fix every instance — a reviewer cites the line it read, which is one member of
whatever set that line belongs to. **Brief it to audit the stage's behavioral claims as a
set**, per `honest-gates` and its rule that a behavioral claim is a gate too — the stage view is where a
claim that was true when written and false after a later task shows up. Brief it, as the
evaluator is briefed, that it returns only after its own background work has finished or been
stopped, and says which.

## Decisions-conformance check (gate criterion, not advisory)

**Run it at the final stage gate and at close-out, over the plan's cumulative diff — not at
every intermediate gate.** A contradiction is a **gate failure wherever it is found**,
and finding one at an intermediate gate still fails that gate; what the position sets is how
often the sweep is *repeated* over a diff that is still growing. Re-running it at every gate
re-reads mostly the same diff and re-reaches mostly the same verdict, and the one reading that
can be complete is the one over the finished diff. An intermediate stage that knowingly lands
a contradiction does not wait for the final gate to say so — raise it when you see it.

A change that contradicts a decision in force, without a `Supersedes` citation on its
task, is a **gate failure**. Two legal resolutions, and only two:

- **Re-scope the change** so it stops contradicting the decision, or
- **Record a deliberate supersede** (the `decisions` skill's `supersede` operation) and add the `Supersedes
  DEC-NNN — <why>` citation to the task, making the override auditable.

"The decision seems outdated" is not a third option — that judgment is exactly what
`supersede` exists to record, and skipping it is how a register decays into fiction.

**Disclose the check's limits (honest-gates).** This is a judgment call over a diff, not a
test command: it can miss a subtle contradiction, and green is not proof of conformance. The
gate report states **which IDs were checked against which parts of the diff** rather than
asserting blanket conformance — a check that overstates its coverage is worse than one that
admits its scope, because the next reader trusts it. Skip only when the diff is genuinely
non-code and no decision in force bears on documentation.

## Exit criterion — the dispositions behind it

The trunk states the criterion itself. What it resolves to, finding by finding:

**"Recorded" names a destination.** A Suggestion is not a backlog candidate — `backlog add`
refuses a defect found during execution, and a nit is still a defect — so the gate report and
the handoff note are where it lives. Without a named destination it survives only in a
transcript this skill then tells you to discard at the next stage boundary, which is how a
finding disappears with nobody told. A Suggestion worth fixing is simply fixed; a Suggestion
worth neither fixing nor writing down was not a finding.

The criterion is deliberately *not* "the detector returned silent" — a fresh judgment agent
never reports zero findings, so a gate with that exit condition is not a gate but a loop. What
ends the loop is that the findings were *dealt with*, and for a defect that means fixed.

**A defect is fixed. The backlog is for what is not a defect.**

| Kind of finding | Disposition |
|---|---|
| **A defect — anywhere in the project, whether or not this plan touched the file** | **Fix it**, and sweep its class. The diagnosis is already loaded; this is the cheapest it will ever be, and it will not get cheaper by being written down. |
| **A significant improvement** — a refactor, a new capability, performance work with no bug behind it | **Record it.** Nothing is broken; this is work someone should choose to schedule. |
| **A decision** — a change needing sign-off, a trade-off with no obviously right answer, an editorial call | **Record it.** It is the user's call, not the executor's. |
| **A defect you genuinely cannot fix here** — the fix needs a device, a credential, an upstream release, or an environment this session lacks | **Escalate**, naming the blocker. Recording it is then the user's decision, not your default. |

**Why there is no "outside the blast radius" row.** A row saying *record it, and say why it
was out of reach* lets every deferral be narrated as scope discipline. A sibling instance in a
file this plan never touched is the same defect, and `../SKILL.md` § A bug found during
execution is a class — sweep it, fix every instance already sends you there. Out of scope
describes a plan's *subject matter*, never a defect's *reach*.

The asymmetry this closes: recording is frictionless and always available, while fixing risks
the gate you are trying to pass. So an executor under gate pressure drifts toward the backlog
for *everything*, and each deferral reads as discipline rather than as avoidance. The symptom
is a backlog that grows with every plan, with entries that record review
findings as not worth closing yet: findings, deferred by the executor that
found them. A deferred finding can leave a repo's own test suite
standing red for days, teaching every later reader to skim past the runner's verdict.

**The escalation valve is narrow on purpose.** *"I could not fix it"* means the fix needs
something this session does not have, and you say which. It does not mean the fix looked
large, or risky, or like it belonged to someone else — those are the readings that reopen the
door this rule closes. If you find yourself reaching for the valve twice in one gate, the
honest report is that the gate is blocked, not that the backlog grew.

**And the valve is evidenced, not asserted — the same bar the review opt-out sets.**
Escalating names the *missing thing* (`escalated: cannot reproduce without a physical
device`), which is checkable against the session. If the user then decides to file it, that
decision is recorded by **quoting their words**, exactly as a review opt-out is:

```
BL-0NN opened — escalated at Stage 2 gate: "no device here"; user: "yeah, file it for now"
```

Without that bar the valve is strictly weaker than the opt-out mechanism it sits beside, and
in the same way: *"escalated, user chose to file"* written by the executor is the executor
deciding on the user's behalf and recording it as though the user had. That is the exact
failure `../references/integration.md` § Review opt-out names, so it gets the exact same
answer — **an unevidenced escalation is not an escalation**, and the finding is still owed a
fix.

**A plan's scope guardrails bound that plan's subject matter. They are not a licence to defer
unrelated defects.** A guardrail like *"change only the values, never which fields are
written"* governs exactly that axis. An overflow, a crash, a parser that rejects valid input,
a false claim in a doc comment — none of those are the axis the guardrail names, so it does
not authorise deferring them. Read a guardrail for what it actually constrains, and be
suspicious when your reading of one turns out to be the reading that avoids work: **a defect
found in a file you are already editing is in scope by default.** A plan that genuinely means
"report defects, do not fix them" has to say that about *defects*, not about coverage.

One question settles most cases: *would fixing this change what the gate measures?* If not,
fixing it is not scope creep, and the guardrail is not about it.

## If the gate passes

**Commit it and open the next stage in the same turn.** The run-to-completion rule lives in
`../SKILL.md` and is read once, at session start; this section restates it at the moment it
applies.

Measured over 39 turn ends (two sessions of one owner's master plan, 2026-08-29/30): seven
ended on a promise about the next unit of work — an announcement of the next task, or an
offer to start it on the user's word — with
no dispatched agent outstanding and nothing blocking, idle from 8.1 minutes to over 8 hours
each. All seven sat at a gate or task boundary. Each such stop makes the user ask again for
work already authorized, and knowing the rule does not prevent it: it is read at session
start and fires at a boundary long after.

So the boundary is not a decision point:

- **A green gate is a commit, not a question.** Commit the gate, write the handoff note, run
  `../scripts/context-usage.py` in the next Bash call, and — on `continue` or `unknown` —
  issue the next stage's first tool call. No "should I continue?", no "ready to start Stage
  3", no summary offered in place of the work. Only its `handoff` verdict ends the turn
  (`session-handoff.md`).
- **The announcement and the call ship together.** If you name the next task, the tool call
  starting it is in the same turn. An announcement alone has started nothing: it hands the
  turn back on a promise, and the user has to ask again for work already authorized. An
  announcement the trunk mandates is still made — in the same turn as the call, never in
  place of it, or instead of it where the sentence was yours to choose. This is
  run-to-completion at the granularity of a single turn.
- **Waiting is not stopping.** If a host re-invokes the run on completion, its supported
  wait may end the turn while a reviewer or suite is outstanding. Otherwise wait in the
  current turn, with concise commentary. Thirty of the thirty-nine measured turn ends were
  exactly this, and they cost nothing.
- **To stop on purpose, use one of the two documented forms** — an `ACTION NEEDED:` block
  naming the decision that blocks the next stage, recorded with `set-blocker` first (§ ACTION NEEDED — the one place a report asks the user for something), or a documented
  Stop condition recorded through v2 `set-blocker` with original evidence,
  dependency and remaining work (legacy: `phase: "blocked"`). Trailing off
  into a summary is neither.

`../../../hooks/plan-continue.sh` is the optional backstop for when this rule is read and
still not followed — see `plan-continue-hook.md`. It is off unless the user enables it, and
it is a net, not a substitute: the rule holds whether or not the hook is running.

## If the gate fails

A gate is one caller of `../SKILL.md` § A bug found during execution is a class — sweep it,
fix every instance, and the sharpest one — detection at a gate is goal-scoped while repair
defaults to instance-scoped, so a class with N instances costs about N rounds, each looking
like fresh news.

1. **Classify every finding** as **Critical**, **Important**, or **Suggestion** — the same
   scale the review tiers use, so a gate finding and a review finding are graded once.
2. **Run the shared rule: diagnose evidence-first, then name the set.** Diagnose
   evidence-first before generalizing, enumerate the set with a command, and **write
   that command down in the gate report**. A failed gate under a bounded round budget is the
   most fix-prone moment in the workflow, which is why the rule's evidence-first ordering is
   load-bearing here rather than advisory: a set derived from a wrong root cause is a wrong
   set, swept confidently, reporting green.
3. **Add a test covering the set**, not the one file that failed, and fix **every member the
   sweep returns in this round**.
4. **Re-run the task's Red-Green loop**, then re-verify narrowly plus the sweep.

**Required verification belongs to the active round.** A re-dispatched review or
evaluator owed to a Critical / Blocking fix verifies that reserved repair; it
must return before complete-round and does not consume a second admission.
A separately initiated critique starts new work through begin-round and is
bounded by the recorded ceiling. Important / Material fixes close on fix-scope
evidence without re-dispatch. A review of an unread redesign is owed verification.
Review until silence is not the exit condition: no Critical remains, every
Important is fixed and no finding-independent condition remains. Evaluate this
after each completed round; further new repair is subject to admission, not an
inferred extension or a manual counter change.

The full procedure — how to derive the set, when the task's `Scope:` field is the authority
and when it is wrong, and what each severity obliges: `../references/gate-failure-procedure.md`.

## The handoff note's contents

The trunk requires one at every passed gate. What it must carry:

```
**Stage N handoff:** <deviations from plan, surprises found, decisions made,
anything a fresh context needs that the Status flips don't capture>
`dispatch: <the gate report's dispatched-vs-inline line, verbatim>`
`review: <the gate report's per-tier reviewer/diff line, verbatim>`
`residuals: <every Suggestion recorded at this gate, and anything escalated rather than
fixed — one line each; "none" when there were none>`
**Decisions in force:** <the DEC IDs still binding, from the project register and any
resolver-listed register, plus any Supersedes citation raised in this stage and not yet
recorded>
`context: <context-usage.py's verdict line, verbatim>`
```

The decisions line is not redundant with the plan's `## Decisions in force`: a constraint
that surfaced mid-stage exists nowhere else, and one absent from the handoff is one the
next session will not know about. **The dispatch and review lines are carried for the same
reason**, and they earn the space: the reset discards the context that holds them. The
dispatch counts can be rebuilt from the trailers, but **the review ledger cannot** — which
agent saw which diff exists only in the gate report, so a reset without it turns "the stage
was reviewed" into a claim with no artifact behind it. Copy the lines the gate already
produced; do not re-derive them. Committed with the `"Stage N green"` commit, and kept to a
few lines — a briefing, not a log. The `context:` line is the exception: it is measured after
that commit, so it is appended then and rides the next one (`session-handoff.md`).

**A reset is measured, not suggested.** Whether the next stage runs in this session or a
fresh one is `context-usage.py`'s verdict, under the five rules in `session-handoff.md` — not
an impression of how noisy the stage was. The handoff note is what makes a reset safe; if you
could not continue from it without the old transcript, the note was too thin, and that is the
bug to fix.

## The plan file is read whole

Every session that resumes a plan reads the plan file in full before doing anything, so
every byte written into it is paid at every resume and on every turn after. **The plan file
receives the handoff note only — the shape above, about 15 lines per gate.** The gate report
itself (each check with its evidence, the finding list, dispositions, the remediation
narrative) goes in the `"Stage N green"` commit body; the Preflight report goes in the
branch's first commit; an `ACTION NEEDED:` block and its resolution live in the transcript
and the commit that resolved it. None of them is written under the stage.

Measured on one owner's plan (undated): a 100 KB plan whose largest sections were a gate
report (8.8 KB), a plan-scope re-run record (6.8 KB), the Preflight record (4.9 KB) and an
`ACTION NEEDED:` block (4.9 KB) opened every session at 37–66k tokens of context before the
first tool call. The note is a briefing; the log is git's.

## The dispatched-vs-inline review ledger

A review the executor ran itself is byte-identical, in every artifact, to one a fresh agent
ran. Measured over five sessions (one owner's sessions, undated): every mandated review ran
inline, none was dispatched, and no artifact said so. The `Executor:` trailer cannot say it
either — it is a per-task record, and a review is not a task. The ledger exists because
nothing else can tell the two apart.

**A mandated review the executor ran itself is a substitution, not a review.** It is recorded
on the gate report's review line, naming the dispatch failure that forced it:

```
review: Tier-2 SUBSTITUTED — ran inline, user authorised at Preflight:
        "don't bother dispatching the reviewer on this one" — over <base>..HEAD
```

**With no recorded reason the gate fails.** Not "is discouraged" — fails. A substitution is a
disclosed deviation; an undisclosed one is a review that did not happen wearing the report of
one, and the exit criterion has no way to see it.

**The bound, which carries equal weight, has two halves.** The ceiling: this
governs only the reviews the declared tier mandates, adds no dispatch beyond the tier, and is
not a licence to run reviews the tier did not fund. The floor: **within the tier, the mandate IS the authorization** — approving a plan
whose execution model mandates a review is the request the standing "don't dispatch unless
asked" caution is waiting for, so at this point that caution does not apply and there is no
confirmation turn to spend — a rule stated without its bound gets over-corrected into its
own inverse, a standing refusal to dispatch anything unless explicitly asked,
which strips the same reviews for the opposite reason.

**A substitution is not an excuse the executor may grant itself, and a dispatch failure is
not one either.** `integration.md` § Review opt-out closes the excuses for a mandated review
at two — an evidenced user opt-out, and a trivial/non-code diff — and says in as many words
that a reviewer which cannot be dispatched **is not a third**: that is the Stop condition for
a mandated review that cannot be run, "the resolution is the user's to choose, not the
executor's to assume."

So the order is: dispatch fails → **stop** → the user chooses (enable dispatch, re-mark the
tasks through `planning-projects`, or authorise the inline run in their own words) → and only
then is there a substitution to record, quoting them. An executor that goes straight from a
failed probe to an inline review and a ledger line has recorded the deviation and skipped the
decision, which is the half that was never the executor's. *"I judged it unnecessary"* and
*"the diff looked small"* are the same move with less paperwork.

### Checked against the dispatch log

The review line names the subagent type it dispatched, because that type is what the check
matches: `review: Tier-2 planning:code-reviewer over <base>..HEAD — …`, `evaluator:
general-purpose in the goal-evaluator role …`. The agent is read from the text before the
first ` — `, so write it there. While a plan is in flight,
`../../../hooks/dispatch-log.sh` appends every `Agent` dispatch, subagent start and subagent
stop to `.claude/dispatch-log.jsonl` (the hook gathers; the script decides).

**Write the dispatch's description so it names the stage and the role**: `Stage 2 Tier-2
review`, `Stage 2 second-pass review`, `Stage 2 gate evaluator`. A dispatch counts toward a
stage's claim only when its description names that stage and the role (review or pass, or
evaluator) and names no task. Without it, any task worker of the same type would satisfy
an evaluator claim, and a per-task Tier-1 review would satisfy the stage's Tier-2 claim.
A Tier-1 review names its task (`Stage 2 Task 2.3 quick review`) for the same reason, and
so does its gate-report line (`review: Tier-1 planning:code-reviewer over the Task 2.3
diff — …`): a line whose head names `Task N.M` is matched only against a dispatch naming
that task, so it never takes the dispatch the stage's own Tier-2 line needs.

Run the check once per gate entry, from the repo root, before the gate report is final:

```
python3 <planning-plugin>/skills/executing-plans/scripts/review-ledger-check.py \
  --plan <plan> --stage <N> --repo <repo root> --report <draft gate report>
```

Each claimed review needs its own matching `dispatch` line, logged since the previous
`Stage N-1 green` commit (for Stage 1, since the log began). Its exit 1 fails the gate. The
failure names the claim: run the review it claims, or rewrite the line as the substitution it
was, with the user's words. The redesign lines `gate-failure-procedure.md` prescribes are
read as written: `round K: redesign — reviewed by <subagent_type>` is a claim, `— battery
<name>` and `— unread` need no dispatch; the claim is read in any case, with or without
`round K`. Any other review line that names no agent before its first ` — ` is ADVISORY,
exit 4, unless it says why no review ran (`not run`, `not dispatched`, `not mandated`, an
opt-out, a trivial diff — `trivial`, `non-code`, `docs-only`, `config-only`, `comment-only` or
a `version bump`) in its head, or after a head saying the review was `skipped` (`Tier-2
skipped — docs-only diff`). A reason inside verdict prose does not count: a line stating a
verdict (APPROVE, LGTM, clean, `0 Critical`) reports a review, never a skip. Name an
advisory line in the gate report; it does not fail the gate, because the same pattern also
matches honest lines. The script's exit 3 is reported as NOT RUN, never green: either no
log exists, so nothing was compared (the hook is not loaded, or no state file existed when
the review was dispatched), or the report has no `review:` or `evaluator:` line at all, which
a gate report always has. A line with `SUBSTITUTED` before its first ` — ` needs no
dispatch — it is a disclosed substitution. The check is a command, so it
runs at every tier; its position is once per gate entry.

**What it cannot see.** It proves a dispatch of the claimed type and role happened in the
stage's window — not that the agent saw the diff the line names, nor that the verdict quoted
is the one it returned. The window opens at the newest commit whose subject is exactly
`Stage N-1 green`, so that commit's subject is load-bearing; and a log left by a plan whose
close-out never ran satisfies Stage 1 claims, which is why close-out archives it out of the
window (`close-out.md`) rather than leaving it in place.

## A review fix does not re-earn the full pass

`../../planning-projects/references/test-scope-tiers.md` sets the rule: a fix made for a Tier-1/Tier-2 finding, a gate triage, or any re-verification inside a
remediation loop runs at **fix-scope** — the classes the fix touched, plus the originating
task's `Test:`, the gate check that failed, every cheap repo validator (the `scripts/check-*`
class) and every test that doubles a changed signature. Measured on 2026-10-25: all four
failures caught after a fix were validator or test-double breaks that the fix itself made.
**Never the full suite, and never a repeat of the gate's stage-scope command.** The gate goes green on the fix-scope result *plus* the
stage-scope result already recorded.

**It is restated in the trunk because a pointer goes unread.** An executor that never opens
the policy file re-runs the **full** suite after every review round, reasoning that each
round's fixes invalidated the previous run, and buys several full passes where the policy
allows about two.

Three things follow, and the second is the one that generalises:

1. **The re-run after a fix is fix-scope.** That is the letter of the policy.
2. **A full run that a later fix invalidates was the wrong run to have started.** Order the
   work so the expensive pass happens once, after every review round has landed — which is
   also what makes the light-plan close-out exemption reachable
   (`light-plans.md` item 5) rather than a clause that merely describes what did not happen.
3. **The gate's evidence is two shas, and the report names both.** The stage- or plan-scope
   pass stands at the sha it ran over; each commit landed after it by a review or evaluator
   fix is proven by its fix-scope run. *"The tree moved"* is never, by itself, the reason
   for another full pass — honest-gates' *commit first, then run it* rule governs the pass
   you are about to record, not passes already recorded over a sha the log still names.
   Measured on one owner's plan (undated): a device suite re-run after each remediation
   commit ran five times, about six hours in all.

## Same-diff reviews go out together

A gate's Tier-2 pass and `high`'s second independent pass read the **committed diff**, its
evaluator reads that diff or, at a stage with Outcomes, demos the **committed build**, and none
of them consumes another's findings. Dispatch them as one
batch, triage the findings as one set, and land the fixes in one pass. Serialising them buys
nothing and costs a full agent round-trip each time.

What stays sequential is only what reads a *different* artifact: **Tier-1** sees one task's
diff before its commit, and the **close-out evaluator** sees the finished plan.


## Early premise and actual Stop events

The first driveable stage runs its authored bounded integration smoke against the
available artifact/route and records requirement origin, evidence claim and the
remaining authorized work. The whole artifact `(goal)` mechanism and evaluator
brief remain in force. A fixture pass or local protocol exercise cannot establish
live AI quality or owner usefulness. Missing requested service blocks that claim;
continue other runnable authorized work before declaring a necessary external wait.
These fields stay on the stage in the plan; Step 3.0 runs the early premise's smoke as one
of its premise checks and records it in the worksheet, never a second worksheet. Final live validation remains in its approved position.

Commentary is progress reporting. Continuation policy applies at actual host Stop
or turn-completion events; do not infer that every assistant message ends a turn.
Wait within the current turn on hosts without automatic re-invocation. V2 decisions
come from the execution-state contract's dispositions, rather than narration regexes.
