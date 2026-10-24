# Test-Scope Tiers Reference

Canonical policy for **how much of the test suite runs at each point of plan
execution**. This file is the single source of truth for that policy —
`planning-projects` authors plans that declare their scoped commands, and
`executing-plans` drives gates and review fixes at the tier this file assigns them.

The problem it solves: on a project with an expensive suite (device instrumentation,
e2e, hardware-in-the-loop), a plan that runs "the full suite" at every stage gate and
after every review fix spends hours re-proving code that didn't change. Measured over
one owner's plan executions (undated):
80+ minutes of repeated full device passes in one session, plus a `clean` at every gate that throws away all incremental build state
for zero extra verification. Most of the waste lives in **full-suite re-runs at
intermediate checkpoints**, and a *scoped* per-task test is cheap — targeted,
class-filtered runs cost 1–3 minutes.

Not all of it, though. A task's
`Test:` is scoped only because its author scoped it; when nobody does, a task field
can be the single most expensive run in a session (the measurement is in
§ A task-level `Test:` is task-scope only when the author scoped it).

The fix is not fewer tests — it is the same total coverage, scheduled so the
expensive full pass happens **exactly once per plan**, where it actually protects
the merge.

## The four tiers

| Tier | When it runs | What runs |
|------|--------------|-----------|
| **task-scope** | Every Red-Green cycle | The task's own `Test:` — **and nothing else**. The stage-scope command does not run inside a task. On an expensive-suite project the field is targeted *because the author scoped it* (§ Plan-authoring declaration), never as a property of being a task field. |
| **fix-scope** | After a Tier-1/Tier-2 Critical fix, a gate-triage fix, or **any re-verification inside a gate's remediation loop** | Only the test classes/modules the fix touched, plus the originating task's own `Test:` and the gate check that failed. Never the full suite, and never a repeat of the gate's stage-scope command — a review or remediation fix is a targeted change and gets a targeted re-proof. |
| **stage-scope** | Intermediate stage gates | All **cheap host-side checks in full** (unit tests, lint, static/architecture checks, build). **Expensive suites restricted to the modules touched by the stage's commits.** Never `clean`. |
| **plan-scope** | Final stage gate + close-out — once | The full suite from a clean state, including every expensive suite and every quarantined slow test. The one place `clean` belongs. |

`clean` appears in **exactly one command per plan**: the plan-scope pass. An
intermediate gate that wipes incremental state re-buys the whole build for nothing —
regressions an incremental build would miss are exactly what the single clean
plan-scope pass exists to catch.

## A stage-scope pass runs once per gate entry

**The stage-scope command runs once, when the gate is first attempted.** Every
re-verification inside that gate's remediation loop is **fix-scope**, and the gate goes
green on the fix-scope result *plus* the stage-scope result already recorded — which is
still a real pass over real commits, not a remembered one, because the fixes since are
exactly what fix-scope re-proves.

Without this rule the tiers are correct per-run and unbounded in aggregate: a gate that
takes three remediation rounds runs its full stage-scope sweep four times, and nothing in
the table above forbids it. Measured over one owner's plan executions (undated): 75 pytest invocations in one
execution, 10 of them the declared stage-scope set or the full suite, and **6 of those 10
labelled per task**, not per gate. A task's own `Test:` is not the cost — what an executor
adds *after* it is, which is what the next section bounds.

**A class sweep is not a fix-scope re-run.** When the repair is a **project-wide class fix**
(a defect found at a gate is swept across the project and fixed at every member),
fix-scope covers the classes the fix touched, and the fix touched every member of the class:
the sweep *is* the scope, and it runs in full. This rule bounds a gate from re-buying its
whole stage-scope command per round; it does not narrow a repair that legitimately spans the
project. Where the two read as competing, the class fix wins and the gate report says which scope
ran, per guard rail 2.

**Accepted cost, stated because it is real.** Running stage-scope once per gate entry means a
remediation fix that breaks a *sibling* module — via a shared dependency or a signature
change — is no longer caught at that gate; it surfaces at the plan-scope pass. That is
latency, not lost coverage: the same trade review tier `standard` already accepts, where
a Critical waits for the stage gate rather than the next task. It is named here so a future
reader meets it as a decision rather than discovering it as a surprise.

**A declared stage-scope command is subject to the same cost threshold as the full
suite.** If the stage-scope command itself crosses ~5 minutes, narrow it: run the cheap
trees the stage's commits *touched or depend on*, not every cheap tree the project owns —
and record the narrowed command on the gate report's scope line (guard rail 2). That is
scope, never an amendment of a written check; a suite a written check names, or a tree the
stage did touch, is not narrowed away for cost
(`../../executing-plans/references/preflight-checks.md` § Amending authored ceremony).
"Cheap host-side checks in full" is an economy when a project has three test trees and a
tax when it has ten — a stage-scope of four whole trees, run at every gate for stages
that touch one, pays for three trees nobody changed.

**A task test's budget.** On a plan that declares these commands, each task's `Test:` runs
under a budget of 300 s unless the Preflight block carries `task-test budget: N s`; over it,
execution stops (`../../executing-plans/references/task-execution.md` § A task test has a
time budget). Set it from the task tests' measured cost, not to make a slow test fit.

**Four or more trees carry a reason each.** A `stage-scope:` declaration naming four or more
test trees or modules ends with a `justified:` clause that gives every tree its reason:

```
- stage-scope: `uv run pytest tests/parser tests/storage tests/api tests/cli -q`
  justified: tests/parser — Stage 1 edits it; tests/storage — Stage 1 imports the parser;
  tests/api — Stage 2 changes the handler; tests/cli — Stage 2 adds a flag
```

`validate-gate-checks.py` reports a four-tree declaration with no reason for some tree as
STAGE-SCOPE-WIDE, naming the trees that lack one. The finding is advisory: its measured hits
include build tasks (`:app:lintDebug`) counted as trees, so it does not fail a plan, and a
tree that needs no reason is a tree to drop.

## A stage-scope pass never runs inside a task

**Between a task's Red-Green loop starting and its commit landing, the only tests that run
are the task's own `Test:`** — plus, when a Tier-1 Critical is fixed, that fix's fix-scope.
Nothing else. Not the stage-scope command, not "the suites this task touched", not a
regression sweep across sibling trees. The stage that owns the task runs stage-scope **at its
gate**, once (previous section), and that is where a cross-task regression is meant to
surface.

The previous section bounds a gate to one stage-scope pass per entry, which leaves the
per-task step unbounded, and per-task runs are not targeted on their own.
Measured over one owner's plan executions (undated): one task's regression run covered the stage-scope trees plus the integration and
end-to-end trees for **297s** — the whole 290-second suite, for one task, between its green
filtered test and its commit. A per-gate bound cannot help here, because such runs are not
attributed to a gate.

**Why an executor reaches for it, and why the answer is no.** A task's `Test:` proves the
task; it does not prove the task broke nothing else. That instinct is correct and its
scheduling is wrong — "did this break a sibling?" is precisely the question the stage gate
asks, and asking it n times per stage buys the same answer at n times the price. The
accepted cost is the one the previous section already named and takes one paragraph
further: a task that breaks a sibling module is caught at the stage gate rather than at the
task. That is latency measured in tasks, against a full suite per task.

**What is still allowed.** Widening *within* the task's own subject — running a whole test
file rather than one `-k` filter, or the class the fix touched — is task-scope and needs no
permission. **The bug-is-a-class rule in `../../executing-plans/SKILL.md`** is likewise untouched: when a
class sweep genuinely reaches other trees, the sweep is the scope and it runs. The rule
bars the *unprompted* regression sweep, not a repair that legitimately spans the project.

**Disclosure.** A task reporting green on a run wider than its `Test:` says so, under the
same guard rail 2 that governs a scoped gate report. "Ran the stage-scope suite for Task
2.3" is honest and also a rule violation; running it and reporting only the task's
`Test:` as green is the disclosure failure on top.

## Guard rails

1. **Cost activation threshold.** Tiering applies only when the project's full suite
   is expensive — rule of thumb: **> ~5 minutes** wall-clock. Below that, just run
   the full suite at every gate; scoping ceremony on a 90-second suite is overhead
   with no payoff. A plan states which side of the threshold its project is on
   (see § Plan-authoring declaration), and cheap-suite projects run the full suite at every gate.

2. **Honest-gates disclosure.** A gate reported green on a scoped run must say what
   scope actually ran — e.g. "gate green — stage-scope: `:payments` instrumented +
   full `check`". Reporting a stage-scope run as "full suite green" is gate-faking
   under the `honest-gates` contract. The tier vocabulary exists so the report can
   be honest *and* short.

3. **Expensive-test quarantine.** Any single test or fixture costing **> ~2 minutes**
   goes behind an opt-in filter (an `@LargeTest`-style annotation, a Gradle
   property, a pytest marker) and runs only at plan-scope. A slow test inside the
   default suite taxes every scoped run that touches its module; quarantined, it
   costs exactly one run per plan. Quarantine is a plan-authoring act, declared in the
   Preflight test-scope block — never something an executor applies at a gate to a suite a
   written check names.

4. **Overlap with reviews.** An expensive stage-scope suite and the Tier-2 stage
   review are independent — start the suite in the background, then dispatch the
   review while it runs. Serializing them leaves the test device or CI executor
   idle for the whole review.

5. **Declared commands, never improvised scope.** A plan for an expensive-suite
   project declares its scoped commands once, so executors run known-good
   invocations instead of inventing filters mid-execution (see next section).

## Plan-authoring declaration

A Standard plan whose project crosses the cost threshold carries a **Test-scope
commands** block — in Preflight or as a conventions line near it:

```markdown
**Test-scope commands** (per references/test-scope-tiers.md):
- stage-scope: <command(s) — cheap checks in full + expensive suites for touched modules>
- plan-scope:  <command — the single full clean pass, quarantined tests included>
```

If the project is under the threshold, the block is simply omitted (the plan
template includes it only for expensive suites); optionally note "full suite
~90s — tiering not applicable" so the executor knows the omission is deliberate.
`fix-scope` needs no declaration: it is derived per-fix (the touched classes plus
the task's own `Test:`).

### A task-level `Test:` is task-scope only when the author scoped it

Being a task field does not bound a command. Measured over one owner's plan executions (undated): one task `Test:`, a marker
deselector with no path filter at all, ran **~3.5 h against a 3132-test collection**,
inside one Red-Green loop; the declared stage-scope command finished in ~7 minutes. Nothing in this policy can
detect that: the tiers above govern **gates**, `fix-scope` is derived per fix, and a
task field is the one place here where an unbounded command has no upstream check at all.

So on a project over the cost threshold, every task's `Test:` is either

- **path- or suite-scoped** — it names a path, a module, a class filter or a marker
  selector that bounds what it *collects*; or
- **explicitly flagged** with a `full-suite: accepted` **field on the task**, recording
  that the author priced the full run and chose it:

  ```markdown
  - **Test:** `uv run --locked pytest`
  - **full-suite: accepted** — the change is cross-cutting and no narrower selector covers it
  ```

  **A field of its own, and nowhere else.** Not on the `Test:` line, not loose in the task's
  prose. The reason is worth stating, because the narrower rule looks arbitrary until you see
  it: a sentence saying the task was *not* marked `full-suite: accepted` contains those exact
  words, so any check reading free text for them lets that sentence grant the exemption it
  denies. Allowing two placements means four cases to get right — two placements times
  granting and denying — and the fourth is a hole. One
  placement has no cross-product to miss, and a denial cannot be written *as* a
  `full-suite:` field without being one.

A bare deselector like `-m 'not slow'` is **not** a scope: it collects the
whole tree minus a slice. The question is what the command collects, not what it skips.

**Tier: authoring-time.** This is checked at whichever pre-presentation checklist
the plan's format uses: `authoring-checklist.md` § Checklist — Standard plans, or
`authoring-checklist.md` § Checklist — Light plans. The rule is in both, and in neither
does it run per execution turn — one scan per authored plan on an expensive-suite
project, and none at all on a project under the threshold, where guard rail 1 already
says there is nothing to bound.

## Worked example (Android, instrumented suite)

A project whose full pass is `./gradlew clean check lint assembleDebug` host-side
plus `connectedCheck` on a device (~25 min total), with one known 4-minute
fixture-download test:

```markdown
**Test-scope commands** (per references/test-scope-tiers.md):
- stage-scope: ./gradlew check lint assembleDebug
               && ./gradlew :<touched-module>:connectedDebugAndroidTest   # no clean
- plan-scope:  ./gradlew clean check lint assembleDebug
               && ./gradlew connectedCheck -PlargeTests=true              # the one clean, quarantine included
```

- Task 2.3's Red-Green loop runs its own filtered class
  (`-Pandroid.testInstrumentationRunnerArguments.class=…`) — task-scope, ~2 min.
- A Tier-1 Critical fix to that task re-runs that class plus the classes the fix
  touched — fix-scope, ~2 min. Not the module suite, not `connectedCheck`.
- The Stage 2 gate (stages 2 of 4) runs the stage-scope pair with
  `:payments` as the touched module — ~5 min, device suite in the background while
  the Tier-2 review runs.
- The final gate + close-out runs the plan-scope pass once — ~30 min, including the
  quarantined 4-minute test — and that is the only `clean` and the only
  `connectedCheck` in the whole execution.

Total: one expensive pass per plan instead of one per gate per re-run.

## Relationship to the other formats

- **Light plans** need no changes: a Light plan's single gate *is* its final gate,
  so its "full existing test suite" check is already plan-scope. When a Light
  plan's close-out re-run would immediately follow the gate's full pass with no
  commits in between, the gate's pass counts as the close-out run — one pass, not
  two.
- **Master plans**: each sub-plan is an independently executed plan and keeps its
  own single plan-scope pass at its own close-out. Tiering applies *inside* each
  sub-plan (its intermediate gates are stage-scope); the master's register gates
  are integration checks, not suite re-runs.
- **honest-gates** binds here too: a scoped gate is still a real gate —
  its commands really ran, here, and passed — plus the disclosure duty in guard
  rail 2.
