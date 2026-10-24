# Preflight checks — the machinery behind each one

The trunk (`../SKILL.md` § Phase 2 — Preflight) carries the rule each of these
checks imposes on every run. This file carries the procedure, the worked
reasoning and the reasons behind them — read the entry for the check
you are actually running.

## Decisions re-check (the plan's snapshot can be stale)

The decisions register **accretes between planning and execution**. A plan written last
month can be executed against a register that has since gained a constraint, or superseded
one the plan still honors — the same staleness problem the plan's own age signals, applied
to a second artifact.

So Preflight does not trust the recorded section: re-run the scan and diff it.

1. Call the `decisions` skill's `relevant` operation for this project. It digests the
   project's register and any register the configured records resolver lists.
2. Diff the result against the plan's `## Decisions in force`:
   - **New entry in scope** → surface it before Stage 1. It may invalidate a task.
   - **An entry the plan honors is now superseded** → surface it. The plan may be
     implementing a constraint that no longer holds.
   - **Unchanged** → say so in one line and proceed.
3. **A plan with no section** (an older or hand-written plan): report the scan result as
   the working set and proceed. Absence is not exemption.

Surfacing at Preflight is cheap; discovering it at the gate costs a stage. This is a report,
not a stop condition — unless the diff invalidates a task outright, in which case it is a
plan defect and returns to `planning-projects` (`../SKILL.md` § When to revisit earlier steps).

## Calibration re-check (the plan's ceremony can be stale)

The **calibration references accrete between planning and execution**, exactly as the
decisions register does — and a plan's Preflight froze its review-scope tier, its test-scope
commands and its roster at authoring time. A plan written under older rules therefore
executes at older ceremony forever, however much the rules have since improved. This is the
same staleness the decisions re-check exists for, applied to the second thing a plan
records about how it will be run.

So Preflight does not trust the recorded declarations either: recompute and diff them. The
Preflight report itself goes in the branch's first commit, not into the plan file
(`stage-gate.md` § The plan file is read whole); the plan receives only the amended
declarations.

1. Recompute from the current rules — `../references/review-scope.md` for the tier (including
   **which tasks** a `high` declaration binds, and that it binds no more than a third of them
   without naming the path each touches — `review-scope.md` § *Risk-listed names a path, not a project*),
   `../../planning-projects/references/test-scope-tiers.md`
   for the scoped commands, and the roster from the plan's own `Dispatch:` fields.
   **Time the stage-scope command at the baseline run.** Over ~5 minutes it is narrowed to
   the trees the stage's commits touch or depend on (`test-scope-tiers.md` § *A declared
   stage-scope command is subject to the same cost threshold*), amended under the protocol
   below with the measured time recorded. A stage-scope command that is the full suite under
   another name buys the plan-scope cost at every gate: measured on one owner's plan (undated),
   a seven-tree declaration at 10.5 minutes ran 40 times, about 420 minutes.
2. Diff against what the plan's Preflight declares:
   - **Unchanged** → say so in one line and proceed.
   - **Changed** → **amend** under the protocol in this file, and state both values in the
     Preflight report (`review-scope: high — recalibrated to bind tasks 1.1, 1.3; as
     authored, bound all 12`).
3. **A plan with no declaration** (an older or hand-written plan): recompute and record the
   result as the working set. Absence is not exemption — the same rule the decisions
   re-check applies.

**What is never recomputed: the plan's facts.** Tasks, their `Test:` fields, gate checks'
substance, invariants, `Scope:` sets. Recalibration changes only what the run *costs* — how
many reviews and evaluators it buys, how wide its regression sweeps are. A rule that let
Preflight rewrite what a task must prove would not be recalibration, it would be re-planning
without the user in the room.

## Amending authored ceremony

Execution edits authored gate checks when they turn out unrunnable. Without a protocol that
shows up as ad-hoc `*(corrected during execution …)*` annotations, with no rule about what
may be touched or what must be disclosed; this protocol sets both.

An amendment is legal only when all three hold:

- **Unexecuted checks only.** A check belonging to a stage whose gate has already passed, or
  a task already `Status: [x]`, is **never** rewritten. Recorded results describe a run that
  happened; editing their checks retroactively edits the evidence.
- **The annotation cites the authorizing rule.** Not "corrected during execution" but
  `*(amended at Preflight per review-scope.md § task-scoped floor — was: `review-scope: high`
  binding all tasks)*`. A reader must be able to check the amendment against the rule that
  permitted it, which is exactly what the bare form makes impossible.
- **The was-value survives.** An amendment that deletes what it replaced leaves no way to
  tell a recalibration from an author's original intent.

**honest-gates treats an unannotated ceremony change as it treats an undisclosed scope
change** — the artifacts are identical either way, so the annotation is the only thing
distinguishing "the rules moved" from "the executor wanted a cheaper run". Amending a check
to make a *failing* gate pass is not recalibration under any reading; that is the gate-
failure procedure, and it is not this.

**What never authorizes an amendment.** Cost, wall-clock and disk are real constraints and
arguments for **re-scoping the plan** — never for re-scoping the evidence a written gate
demands. A suite dropped from a gate command "for disk/time" does not make the gate cheaper;
it is recorded `[~]` **BLOCKED on that suite**, not reported as a pass on the remainder
(`../../honest-gates/SKILL.md`, the *Prohibited* section's excluding-the-failing-case bullet,
which owns this rule).
The tiering policy is not an exception to it: narrowing per `test-scope-tiers.md` drops only
trees the stage's commits neither touched nor depend on, is declared as scope, and lands on
the gate report's scope line — a suite a written check names, or a tree the stage touched,
removed for cost, is an amendment whatever the report calls it, and cost is not among the
rules that can authorize one.

**Verify against committed state.** Recompute from the plan file as committed and confirm
the working tree is clean before recording any Preflight result. A calibration re-check run
over uncommitted edits certifies a plan nobody else can see — the same defect as a gate
verified against a dirty working tree, one phase earlier: the check passes on edits the
commit does not hold.

## Access probe (hardware and remote targets are proven by I/O, not by environment)

An unset environment variable is not evidence that hardware is missing: the repo's own
deploy script may name the host, and only a gate that tries the connection can tell.

So for every device, board, VM or remote host a task or gate depends on:

1. **Resolve the target from the repo's own deploy, HIL or provisioning scripts** — the
   address, port, user and serial the project already uses — before concluding anything
   from an environment variable. An unset variable is **missing configuration**; only an
   executed probe can report **missing hardware**, and the two have opposite consequences
   for a gate.
2. **Run a probe** (ssh, ping, a serial identity read — whatever the project's scripts do)
   and **record what answered**, verbatim, in the Preflight report.
3. **Nothing answered** → the target is unreachable: Preflight fails on that line, and every
   gate needing it is **BLOCKED**, written `[~]`. **Something answered but was not what was
   expected** (wrong serial, wrong identity, auth refused) → **investigate before excusing**:
   a failed probe is as often the tool's fault as the device's — the probe's own
   `BatchMode=yes` against a password-only host, a defect in the serial comparison — and an
   env-var check reports "no hardware" at every one of them.

Position: once at Preflight, like the gate-selector probe. A command, never a dispatch,
so untiered. `../scripts/probe-device.sh` encodes exactly the split in step 3: it exits 78
when nothing answered, 1 when something answered but was not what was expected, and 0 on
a match, and its `--discover <repo root>` does step 1. Its header is the authority on
its modes. For a toolchain, `../scripts/probe-toolchain.sh android --repo <project root>`
proves the SDK and NDK where the build will look for them, not where the plan says. It
reads literal pins only, and says so when a `compileSdk` comes from a variable or a
version catalog.

## Gate-selector probe (a gate that cannot pass is a plan defect, not a gate failure)

`planning-projects` cross-references every `pytest <file> -k <expr>` in a gate against the
plan's task `Test:` fields at authoring time (its `validate-gate-checks.py` reports
SELECTOR-UNMATCHED). That check is static, because at authoring time the selected tests
usually do not exist yet. **Preflight runs the half that authoring could not**: here, the
tests either exist or are about to be created by a named task.

For every gate check invoking pytest whose target file exists now:

```
pytest --collect-only -q <the check's selector>
```

- **Collects ≥1 test** → fine, proceed.
- **Collects 0, and no task in the plan creates that test** → **plan defect**. Stop and
  return it to `planning-projects` (`../SKILL.md` § When to revisit earlier steps), exactly
  as an invalidated task in the decisions re-check does. The gate cannot pass however well
  the work goes, so discovering it now saves the stage it would otherwise fail at.
- **Collects 0, but a task's `Test:` builds toward it** → expected. Record which task
  satisfies the selector (`gate-selector: Stage 1 gate `-k restart` — created by Task 1.4`)
  so the gate report can say why an empty collection at Preflight was not a defect.
- **Target file does not exist yet** → same as the previous case: name the task that creates
  it, or it is a defect.

**The same probe for the other two runners** the authoring check reads (`validate-gate-checks.py`
reports their unmatched selectors as advisory, because some match tests that already exist —
this is where each one is settled):

- **cargo** — a gate's `cargo test <filter>` is probed with `cargo test <filter> -- --list`
  (the gate's own package and target flags kept), which builds and lists the matching tests
  without running them. It must list at least one test.
- **Gradle** — a gate's `--tests '<pattern>'` must match a test class or method name under the
  project's test source sets. Gradle has no cheap "what would this filter collect" mode, so
  search the sources instead, on the simple name: drop the package (`com.x.FooTest.parses`
  → `FooTest`, then `parses`), read `*` as `.*`, and search every test source set at any
  depth, the root module's included:
  `grep -rlsE --include='*.kt' --include='*.java' '<name as a regex>' $(find . -type d \( -path '*/src/test' -o -path '*/src/androidTest' \))`.

A zero result is a plan defect at Preflight for every runner, exactly as for pytest — and, as
there, a zero that a task's `Test:` builds toward is expected and recorded with the task that
satisfies it.

This is a **command, not a dispatch**, so it is not tier-gated by review-scope (the cost
rule: only a mandate costing an agent dispatch is tiered). Its own gate is a **position** —
once at Preflight, never per stage — which a command-costing mandate names instead of a
tier. It exists because a gate can name a real test file with a filter matching nothing in
it, and that is otherwise discovered only by failing mid-stage.

## Git bootstrap (hard prerequisite for commit-per-task)

Every task commits its own work (`../SKILL.md` § Step 3.3 — Red-Green loop (per task), rule
7), so a working repo must exist before Stage 1:

```
git rev-parse --is-inside-work-tree  →  is this a repo?
├── NO → `git init`, ensure a sane .gitignore, and make an initial commit of the
│        current tree ("chore: initial commit before plan execution") so the
│        first task has a parent. Then offer to create a GitHub remote
│        (`gh repo create <name> --private --source=. --remote=origin`) — create
│        it only on user confirmation; never push a repo public without consent.
│        Execution proceeds locally whether or not a remote is created.
└── YES ↓
On main / master?  → do NOT execute here. Create a feature branch (or worktree)
                     per the Safety rails before Stage 1.
Working tree dirty with unrelated changes? → surface them; don't sweep them into
                     the first task's commit.
```

A missing remote is **not** a stop condition — local commits are the unit of
record. Only an un-initializable repo (e.g. read-only filesystem) blocks here.

## Host notes (Cursor)

- **A toolchain is proven where the build will look.** "Tools installed" is not satisfied by
  the plan's literal path. Resolve the toolchain from the configuration the build reads —
  for Android, `../scripts/probe-toolchain.sh android --repo <project root>`, which follows
  Gradle's order (`local.properties` `sdk.dir`, then `ANDROID_HOME`) and names any other SDK
  on the host — and record what it printed. Its exit 1 is a failure to fix, never BLOCKED.
  Re-probe after a task that writes `local.properties` or a toolchain pin.
- **Hardware is proven by I/O, not by an env var.** Resolve the host from the repo's own
  deploy or HIL scripts, then prove it with `../scripts/probe-device.sh`. Its exit 78 — a
  probe ran and nothing answered — is the only outcome that may be recorded as BLOCKED,
  including a `--serial` node that is absent, since the node is the device. A missing client,
  or a node present but unreadable, is exit 2: a gap on the agent's host, which may not
  borrow that excuse. The 78/1/0 split is given in this file's access-probe section; the script's header is the
  authority on exit 2.
