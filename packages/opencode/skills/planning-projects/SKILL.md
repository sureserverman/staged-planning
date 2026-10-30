---
name: planning-projects
description: Use when the user wants a plan for a project of any size. Triggers on "roadmap", "break this down", "create a plan", "plan this", "how should I build".
  On OpenCode, invoke this skill by name.
---

> On OpenCode, `<planning-plugin>` is this package's folder: the folder that holds `skills/`, `../..` from the base directory OpenCode prints with this skill. In a shell command use its absolute path, quoted.

# Project Planner

Create detailed, staged project plans grounded in real technical research. Every task gets a test. Every test gets a Red-Green loop. Nothing moves forward until the current task is green.

This skill produces plans where every task has a concrete test and the execution model prevents half-built states. For the default **Standard** plan, every claim also traces back to researched documentation and every stage carries stage gates and rollback notes; the lighter formats (see Phase -0.5) keep the test-and-gate backbone and scale the rest to the size of the job.

---

## Reference map

The trunk carries the authoring decisions. These load when their condition is met:

| Read this | When |
|---|---|
| `references/plan-document-template.md` | writing the plan file — the literal template |
| `references/task-fields.md` | the exact semantics of any task or stage field |
| `references/set-valued-checks.md` | writing a gate check whose goal quantifies over a set |
| `references/format-triage.md` | triaging a request, or defending a format call |
| `references/light-plan-format.md` | Phase -0.5 selected **Light** |
| `references/master-plan-format.md` | Phase 2.5 selected **Master** |
| `references/research-scans.md` | running a Phase 0 scan and the trunk's rule leaves a case open |
| `references/gate-authoring.md` | authoring a stage gate, or adding a verification mandate |
| `references/authoring-checklist.md` | running the pre-presentation checklist — the full item list, Standard and Light |
| `references/test-scope-tiers.md` | declaring the plan's test-scope commands |
| `references/owner-decisions.md` | the draft exists — the questions execution would stop for, and how answers are recorded |

---

## Phase -1 — Clarification

Before researching or planning anything, make sure you understand what the user actually wants. Ambiguous or underspecified prompts produce plans that solve the wrong problem — and a wrong plan executed perfectly is worse than no plan at all.

### When to ask

Ask clarifying questions if any of these are unclear:

- **Scope**: What's included and what's explicitly out of scope?
- **Target environment**: What platform, language, framework, or infrastructure?
- **Constraints**: Performance, compatibility, security needs, deadlines?
- **Existing state**: Greenfield, or integrating with an existing system — and where's the code?
- **Success criteria**: How will the user know the project is done? What does "working" look like?
- **Audience**: Who uses the end result — the user, their team, end users, CI/CD?

### How to ask

- One question at a time. Don't dump a wall of questions. This is for scope; the questions
  execution would stop for wait for § Ask execution's questions now, which batches them
- Prefer multiple-choice when the options are finite ("Are you targeting A, B, or C?")
- If you can infer an answer from the codebase or context, state your assumption and ask for confirmation rather than asking open-ended
- Stop asking once you have enough to produce a meaningful plan — you need enough to avoid building the wrong thing, not perfect information

### Ask execution's questions now

Execution stops to ask the owner at named points: the branch, a destructive command, a
secret, the merge. Most of those answers are known before Stage 1, so ask them here, not
mid-run. **Once the draft exists and before it is presented**, sweep it against the catalog
in `references/owner-decisions.md`: every point the draft reaches is a question. Ask them
in **one batched round** — up to four per prompt, each multiple choice with the recommended
option first — and a follow-up round only for what the answers raise. Record each answer in
the plan's `## Owner decisions` as `OD-N`: the owner's words quoted and dated, naming the
case it covers. A declined question is recorded `ask at execution`; a plan that reaches no
point records `none`. An entry covers only the case it names; execution still stops on
anything else (`../executing-plans/SKILL.md` § Stop conditions).

### When NOT to ask

If the prompt is specific enough to plan against (names a technology, describes the goal, implies the scope), skip straight to Phase -0.5. Don't ask questions for the sake of being thorough — ask because the answer would change the plan.

---

## Phase -0.5 — Format triage

Once the request is clear enough to size, pick the **format** before you plan.

| Format | Trigger | What you produce |
|--------|---------|------------------|
| **Direct** | ≤ ~2 tasks, one session, no staging value | **No plan file.** Recommend direct execution with a test and a commit, then stop — do not run Phases 0–5. |
| **Light** | Single stage, 2–5 tasks, one session, one stack, low risk | A Light plan per `references/light-plan-format.md` (`*-light-plan.md`) |
| **Standard** | Everything between Light and Master | The full staged plan (Phases 0–5) |
| **Master** | > ~6 stages / ~25 tasks, or ≥2 independently shippable workstreams | A master plan + sub-plans (Phase 2.5, `references/master-plan-format.md`) |

**Size each request, not the batch.** A prompt often carries several independent asks, and
the ladder applies to **each item on its own**: the tweaks are not larger for having arrived
in the same sentence as something that is. So triage may return a **split verdict** — some
items executed Direct, the remainder planned at whatever format the *remainder alone* warrants
(`Format: Split — items 1, 4, 5 Direct; items 2, 3 Light`). Escalation to Master requires the
**plannable remainder** to cross Phase 2.5's thresholds by itself, never the raw item count.
**Split only where the items are genuinely independent:** items sharing a file, a migration,
or a behavior contract are one item for triage purposes however separately they were phrased.

**How to triage:**

- **Direct is the off-ramp.** If the job is a couple of tested edits in one sitting, say so
  and execute it directly — the skill is allowed to decline to plan. Still write a test and
  commit, and still do a quick backlog-title check before you start (the one Phase 0 step
  Direct keeps — silently redoing a tracked item is the same planning bug at any size).
- **Light** is real-but-small work: one coherent stage, no fan-out, no cross-session handoff
  (`references/light-plan-format.md`).
- **Standard** is the default staged plan authored by Phases 0–5 of this skill.
- **Master** is the existing decomposition path; **Phase 2.5 is the sole authority on the
  Standard→Master decision** — this table only points at it, it does not restate the rule.

**Record the call.** State the chosen format and the trigger that selected it in one line at
the top of the plan you produce (`Format: Light — single stage, 4 tasks, one session`). A
Standard or Master plan may omit the line (they are the unmarked default); a Light plan should
carry it. **A split verdict always carries the line** — it names which items left the plan
entirely, and that is the half a reader cannot reconstruct from the plan file.

**When in doubt, round up — per item, never per batch.** A *single job* on the Light/Standard
or Standard/Master boundary takes the heavier format; a batch does not, because rounding up
there charges every small item for the largest item's container. The user can always override
in either direction.

Why each boundary sits where it does, and a worked example of the per-item rule: `references/format-triage.md`.

---

## Light plans

If Phase -0.5 selected **Light**, do not run the full Phase 0–5 apparatus. Author a
single-stage plan per `references/light-plan-format.md` — the authoritative spec — through
this compressed path. The deltas from the Standard flow:

- **Research is proportionate, not a mandated section.** A 1–3 sentence **Context** line
  replaces the Research Summary. **The backlog scan still runs** — a Light plan that silently
  duplicates an open backlog item is the same planning bug at any size;
  fold in matches with `Closes BL-NNN`. Likewise, if `docs/workflows/` exists and the change
  touches a documented flow, still declare `Changes/Removes WF-NNN` on the task — behavior
  contracts don't get a size exemption.
- **Preflight collapses into the gate.** There is no Preflight section; "baseline tests pass"
  lives as a bullet inside the single `### Stage 1 Gate`.
- **No Risk / Rollback / Blocks / Dispatch fields.** Keep `Depends on` only where a task
  genuinely consumes a prior task's output.
- **Output location is unchanged.** Same records-home resolution as any plan
  (§ Output location). Filename ends in `-light-plan.md` (and its first heading is
  `# Light Plan:` — either one lets `executing-plans` detect the format).
- **Use the Light checklist**, not the full one (§ Checklist — Light plans).

If while authoring you find the job needs a second stage or a 6th task, stop treating it as
Light: re-issue it as a Standard plan (the upgrade rule in `references/light-plan-format.md`).
Don't stretch the Light format past its bounds.

---

## Phase 0 — Research

Before writing a single task, gather the technical facts. Plans built on assumptions fall apart mid-build when the API doesn't work the way you imagined or the library dropped that feature two versions ago.

### Online sources

Use WebSearch / WebFetch to pull documentation for every technology in scope: API formats, SDK
methods and config schemas; version-specific behavior — don't assume, check, since a method
that exists in v3 may not exist in v2; known limitations, gotchas, deprecations and breaking
changes; community patterns.

If the project uses a library or framework, use context7 MCP to fetch current documentation rather than relying on training data that may be months old.

### Linked notes

If the project has linked notes (a notes folder or tool it already uses), search them for prior
decisions on this topic (ADRs, design docs), architecture notes that constrain the approach, and
related past work — what was tried, what worked, what didn't.

Check the project's existing plans for prior design decisions: `<records home>/plans/` (§ Output location; by default `<repo>/docs/plans/`).

### Decisions scan

Call the `decisions` skill's `relevant` operation — it digests the project's register and any further register the configured records resolver lists, in one step.

- A task that would contradict an accepted decision is a planning bug. Either the plan supersedes the decision deliberately — say so on the task with a `Supersedes` citation, and the executor records the supersede at close-out — or the task is re-scoped.
- A plan that *creates* a binding constraint should add a task to record it (`decisions add`), so the next plan inherits the reason rather than rediscovering it.
- **Superseded entries in the digest are still informative.** They record an approach already tried and abandoned; re-proposing it is the failure they exist to prevent.

**On a brand-new project** there is no `decisions.md` yet — that is expected, not a reason to skip the scan. Any register the records resolver lists still binds the project. Record the state in the plan (`project register: absent — new project`) and carry the listed registers forward.

**Write the findings into the plan.** The scan's output goes in a `## Decisions in force` section directly below the Research Summary — a constraint discovered at planning time that isn't recorded there is a constraint the executor will never see. Use non-checkbox bullets (a raw `- [ ]` outside Preflight/Gate blocks becomes a false backlog candidate in backlog unify). Record what was consulted, so a reader can tell **"nothing binds this scope"** from **"nobody looked"**. When nothing applies, say so explicitly; the literal form of that section, and why these entries beat a plan's own summary, are in `references/research-scans.md`.

### Backlog scan

Call the `backlog` skill (`read` or `list`) and check the backlog (`<records home>/backlog.md`) for open entries that touch the new plan's scope — same component, same tags, or named in `Source`. For each match:

- If the new plan naturally subsumes the item, fold it in and reference the ID on the relevant task (`Closes BL-NNN`) so `executing-plans` can remove it on Close-out.
- If not, leave it deferred and note in the Research Summary why it stays out.

A new plan that silently duplicates an open backlog item is a planning bug — the scan is how you catch it.

### Workflow-spec scan

If `docs/workflows/` exists, read the files whose scope touches the plan. They are the project's behavior contracts and dictate what the plan must preserve, change, or extend:

- A task that intentionally alters a documented behavior must declare it on the task line: `Changes WF-AUTH-003 — passwordless replaces bcrypt branch`.
- A task that removes a documented behavior must declare it: `Removes WF-AUTH-007`.
- A task that adds a new user-visible flow must add a corresponding capture/extend step to the plan so the spec doesn't fall behind code.

Plans that touch the codebase without referencing any in-scope WF-ID either (a) genuinely don't change documented behavior, or (b) are missing a declaration. Be explicit about which.

**Redesign-from-handoff plans** (via `applying-design-handoff`) make behavior changes *the
rule, not the exception*: the design wins, but every behavior change is still declared on its
task, each new design screen adds a capture step, and the stage carries a
**reconciliation/sign-off task** that gets the user's explicit approval before any destructive
behavior change is applied (`references/research-scans.md`).

### Architecture doc scan

If the `architecting-projects` skill produced an architecture doc for this topic
(`<records home>/plans/YYYY-MM-DD-<topic>-architecture.md`), it is the authoritative structure the plan builds — read it before
writing any task:

- **Structure-creating tasks MUST cite the ARCH-ID they implement** on the task line
  (`Creates ARCH-01 tree`, `Implements ARCH-03 RemoteStore boundary`). A task that
  invents structure not present in the doc is either missing a citation or
  contradicting an approved decision — resolve which before presenting the plan.
- **Emit the conformance gate:** the plan's final stage gate includes the check
  `- [ ] **(judgment)** Built structure conforms to the architecture doc (ARCH-NN tree
  matches, ARCH-NN boundaries respected — list the IDs actually in scope)`. The marker is
  required, not optional — it marks a reading the **executor** performs; it does not by
  itself fund an evaluator (`../executing-plans/references/review-scope.md`).
- **Decomposed projects (Phase 2.5):** each *sub-plan* that creates structure carries its own
  ARCH-ID citations and its own conformance check in its own final stage gate
  (`references/research-scans.md`).
- The plan must not silently deviate from the doc. A deviation discovered during
  planning goes back to the user (the architecture was explicitly approved); the doc
  is then revised — ARCH-IDs are stable, revisions append rather than renumber.

No architecture doc for a plan with obvious structural surface? State it explicitly in
the Research Summary ("no architecture doc — structure decided inline") rather than
leaving the reader to wonder whether one was consulted.

### Citing decisions on tasks

Decisions use the **same citation mechanism as `ARCH-NN`** — deliberately, so
`executing-plans` needs no special handling for either:

- **A task constrained by a decision cites it:** `Honors DEC-NNN` on the task line. This
  is what carries the constraint from the register to the person (or agent) implementing
  the task, who may never read the register itself.
- **A task that deliberately overrides one cites it with a reason:**
  `Supersedes DEC-NNN — the library dropped streaming in 4.0`. The citation is what
  makes the override *auditable* rather than silent, and it is the executor's instruction
  to record the supersede at close-out.
- **Emit the conformance gate:** the plan's final stage gate carries
  `- [ ] **(judgment)** No change contradicts a decision in force (DEC-NNN — list
  the IDs actually in scope); any Supersedes citation has been recorded via decisions
  supersede`. The marker is **required**, not optional — and, like the architecture
  conformance line, it does not by itself fund an evaluator.
- **A citation restates the constraint** in the entry's own words. A decision
  sourced from an audit never brings the report body into the plan.

An uncited change that contradicts an accepted decision is a **gate failure** in
`executing-plans`, not an advisory — silently violating a recorded decision is the exact
failure the register exists to prevent.

### Project context

Read the codebase before planning against it:

- Existing patterns, conventions, file structure — the plan should fit, not fight
- Dependencies already in use — don't introduce a second HTTP client when one is already there
- Test patterns already established — match the existing test framework and style
- CI/CD pipeline — understand what runs on push so you can write tests that work in CI

### Research summary

Compile findings into a **Research Summary** at the top of the plan document. Every task below should trace back to something learned here. If a task can't be grounded in research, that's a signal you need to research more before planning it.

---

## Phase 1 — Preflight

Before Stage 1 begins, verify that everything needed to execute the plan is in place. Discovering a missing tool or expired API key mid-build wastes time and breaks flow.

### Preflight checklist

Verify each of these and report the result:

- [ ] **Tools**: All CLI tools required by the plan are installed and at compatible versions — checked where the **build** looks for them (its own config, e.g. `local.properties`), not at a path assumed while planning
- [ ] **Dependencies**: All libraries/packages are available and version-compatible with each other
- [ ] **APIs**: Required endpoints are reachable, keys are valid, auth works
- [ ] **Access**: Required permissions exist (repo write, service accounts, deploy targets)
- [ ] **Environment**: The dev environment can build the project and run the test suite
- [ ] **Baseline**: Existing tests pass before any changes begin (don't build on a broken foundation)
- [ ] **Review scope**: the tier this plan's cumulative diff warrants — `none` / `light` / `standard` / `high` — stated with its reason, and declared once from the plan's **cumulative** diff rather than per task. Undeclared means `standard`; touching a risk-listed area sets `high` regardless of size. **A `high` declaration names the risk-listed tasks it binds** (`review-scope: high — tasks 1.1, 1.3 (schema migration)`), because Tier-1 attaches to the **risk-listed task**, not the plan — an unnamed `high` conservatively binds every task (`../executing-plans/references/review-scope.md`)
- [ ] **Dispatch probe**: A throwaway subagent returns a fixed string — dispatch works in this session (skipped on an empty roster, or below tier `standard`)
- [ ] **Dispatch roster**: Every `Dispatch: YES` task in the plan is listed with the subagent type it routes to (`../dispatching-parallel-agents/references/stack-routing.md`), or `0 tasks` when there are none. It must cover **every stage, not the first** — a partial roster is the instance-shaped check this skill rejects everywhere else
- [ ] **Test-scope commands**: for a project whose full test suite is expensive (`references/test-scope-tiers.md`), the plan's stage-scope and plan-scope commands are declared here in Preflight, so executors run known-good invocations instead of improvising scope mid-execution

If any preflight check fails, stop. Fix it or flag it to the user before proceeding.

Do not plan what execution's Preflight already does: it bootstraps a missing git repo itself
(`../executing-plans/SKILL.md` § Git bootstrap), so no task runs `git init`.

The dispatch checks are the *executor's* rules; the author's job is to carry them into the plan's Preflight so a run cannot skip them by never being asked. The reasoning lives at `../executing-plans/SKILL.md` § Dispatch roster and capability probe and is deliberately not repeated here.

---

## Phase 2 — Stage Breakdown

Divide the project into sequential stages. Each stage is a coherent unit of work that produces a testable milestone — something you can point to and say "this works end-to-end."

**Write each stage's Outcomes before its tasks.** Name the person or program that meets
the result. Write what they get when it works, and for every way it can fail (input refused,
input unreadable or not granted, too large, nothing usable left, a dependency missing) what
they see. "Nothing — it closes" is a bug written down, not an outcome. Use the Research
Summary: a promise there ("until X, the app shows a clear 'file too large' result") belongs
in the Outcomes of the stage that meets it. The executor builds every Outcomes line, not
only what the `Test:` lines reach, and the gate's evaluator grades the stage against them
as that user. A promise in the Scope that no stage gives an owner is the one nobody builds:
the code drops that case silently and every test still passes.

### Stage structure

```
Stage N: [Name]
  Goal:       What this stage achieves, naming who it is for (one sentence)
  Outcomes:   Who uses the result (a person, another app, a later stage, a worker), then
              one line for what they get when it works and one per way it can fail, each
              with what they see. Omit only when nobody outside the code meets the result
  Depends on: Stage(s) that must be green first
  Blocks:     Stage(s) that cannot start until this stage's gate passes
  Risk:       LOW | MEDIUM | HIGH — why
  Rollback:   What to undo if this stage fails irreparably

  Tasks (dependency-ordered):
    Task N.1: [description]
      Depends on: [prior task(s) or "none"]
      Blocks:     [task(s) that wait on this one, or "none"]
      Dispatch:   YES | NO  (an instruction to the executor — YES obligates dispatch to a
                  subagent; it is not a note about whether a sibling task runs alongside it)
      Scope:      [the SET this task changes — omit when it changes exactly one thing,
                  unless Dispatch is YES]
      Test:       [concrete pass/fail criterion]
      Review:     skip   (OPTIONAL, and only on the user's say-so — see below)

    Task N.2: [description]
      Depends on: Task N.1
      Blocks:     Task N.3, Task N.4
      Dispatch:   NO  (blocked by N.1)
      Test:       [concrete pass/fail criterion]

  Stage gate:
    - [ ] Integration check 1
    - [ ] Class predicate: the command that sweeps the set the claim is over
    - [ ] No regressions in existing tests
    - [ ] (judgment) [only where a reader decides what no command can — most gates: none]
```

### Status marking (per-task done-state)

Every task carries a **Status** checkbox as its first field: `- **Status:** [ ]` when planned, flipped to `- **Status:** [x]` by `executing-plans` the moment the task's test goes green (and committed in the same commit). This is the **single source of truth for task completion**, read by downstream tools (e.g. backlog unify) rather than inferred from stage gates or git archaeology.

At the end `executing-plans` appends `**Completed:** YYYY-MM-DD — commits: <list>`; that line plus all `Status: [x]` is unambiguously done.

### Task and stage fields

Each task carries `Status`, `Depends on`, `Blocks`, `Dispatch`, `Test:` and
`Red-Green max cycles:`; a task sweeping a set also carries `Scope:`, and each stage carries
`Risk:` and `Rollback:`. These rules are load-bearing enough to state here rather than defer:

- **`Dispatch: YES` is a directive to dispatch**, not a description of what happened.
- **`Scope:` is only as good as the sweep behind it** — a truncated authoring command is a
  documented way for one to arrive short, and a gate failure then repairs an instance while
  its siblings survive.
- **`Depends on` and `Blocks` are both required on every task, and they are symmetric** — if
  A lists B under `Blocks`, B lists A under `Depends on`. An asymmetric pair is how a task
  becomes dispatchable before the work it needs exists.
- **Tasks are in dependency order within their stage, and no task depends on a later
  stage's** — a backward-pointing dependency across a stage gate cannot be satisfied without
  reordering the plan.
- **Every task carries `Dispatch` (YES/NO), consistent with its dependencies** — a task with
  an unsatisfied `Depends on` is not `Dispatch: YES` however independent it looks.
- **A name a later task, gate or rollback relies on is fixed by the task that creates it** —
  a path, directory or API used downstream is written into the creating task, so execution
  cannot pick another (`references/task-fields.md` § Names other tasks rely on).

Exact semantics for every field — including `Review: skip`, risk flags and rollback
notes: `references/task-fields.md`. (Stage sizing is not there; it is § Stage sizing,
in this trunk.)
### Stage sizing

If a stage has more than 7 tasks, it's too large. Split it. Large stages hide integration problems behind a wall of individual task tests that all pass but don't work together. Aim for 3-5 tasks per stage.

---

### A plan that adds an obligation names what it removes

This applies to plans that change a **process** — a skill, a gate, a checklist, a
convention every future run must honor. It does not apply to ordinary feature work.

So a plan that adds a mandatory step states, in its Research Summary, one of:

- **Removes:** the obligation it retires, or the one it subsumes; or
- **Replaces:** the step it supersedes rather than sits beside; or
- **Adds, net:** the new obligation with its **cost** (what it makes every future run do)
  and **what it catches that nothing else does** — a step that duplicates an existing
  check's coverage is not new protection, it is new cost.

The third option is legitimate and expected; the point is that it must be *argued*, not
assumed.

**The honest test for an existing obligation: has it ever caught a real defect?** Not
"could it in principle" — has it, in this repo's history. An obligation that has produced
only false alarms, or only findings about itself, is a candidate for the `Removes:` line of
the next plan that touches its area.

**A new verification mandate names the tier or scope rule that gates it** — and a
mandate that names none does not enter. So a plan adding a mandate says which of these
governs it: a **review-scope tier** (for anything dispatching an agent), a **test-scope
tier** — task / fix / stage / plan — for a test command, or a **position** (once per gate
entry, final gate only, close-out only). "It runs every time" is an answer, but it is the one
that must be argued hardest.

Why a process only ever grows, and the measured accretion behind this rule:
`references/gate-authoring.md`.

## Phase 2.5 — Decomposition decision (master plan + sub-plans)

When the *plan itself* is too large, don't write one monolith — decompose it into several
independently executable **sub-plans** linked by one **master plan**. The canonical format
(naming, master document structure, register fields, parser-safety rules) is
`references/master-plan-format.md`; this section is only the decision rule.

**Decompose when ANY of these hold:**

- The single plan would exceed **~6 stages or ~25 tasks**
- The work spans **two or more independently shippable workstreams** (separate
  deliverables, repos, or subsystems)
- Execution will clearly span **multiple sessions or stacks**, each wanting its own
  context window

**How to split:**

- **2–7 sub-plans.** One sub-plan means no master was needed; more than seven means the
  scope is several projects, not one.
- **Each sub-plan is a complete, independently executable plan** — its own Research
  Summary (scoped), Preflight, Stages, gates, and close-out. If a candidate sub-plan
  can't run alone, it's a stage of another sub-plan; fold it back in.
- **The master plan holds what's shared:** the cross-cutting Research Summary, the
  sub-plan register, and a `**Gate:**` block per entry with integration checks across
  sub-plans. It carries **no tasks and no Preflight**, and no raw `- [ ]` bullets outside
  `**Gate:**` blocks.
- **Sub-plan register dependencies are symmetric**, exactly like task fields — and if you
  can't name a master gate check between two sub-plans, question the split.
- **Each sub-plan backlinks to the master** (`Master: ./<master-file>` under `Date:`).

Research once, at master level, then scope each sub-plan's Research Summary down. The backlog
and workflow-spec scans run once for the whole decomposition; fold-ins (`Closes BL-NNN`) and
WF declarations land on tasks inside the relevant sub-plan. Hand the master to
`executing-plans`, which drives sub-plans in register dependency order and defers version
bumps to the master close-out.

---

## Output location

Plans live in the project's **records home**. Resolve it before writing — do not resolve
it in prose:

1. Run `python3 <planning-plugin>/lib/records_home.py --project <repo> --for-write`.
   Its exit code is the instruction:
   - **0 or 3** — stdout is the records home. Use it. On **3** the records home is the
     repo's `docs/` (nothing is configured); warn once that the plan goes into the repo.
   - **2** — a records resolver is configured but cannot reach its storage. **Stop and show
     the message.** Do not fall back to the repo and do not create anything: a missing
     store is not an empty one, and creating folders there builds a phantom tree.
   - **2 whose stderr does not start with `records_home:`** is not that answer: Python's
     own can't-open-file also exits 2, so it is a broken invocation. Fix the path and
     rerun; decide by the message, never by the bare status.
   The exit-code contract is `../../references/records-resolver.md`; it is not restated here, because
   two definitions of "reachable" drift.
2. Save the plan to `<records home>/plans/YYYY-MM-DD-<topic>-plan.md`, creating `plans/`
   if needed. (The design doc from `brainstorming` lands beside it via the same
   resolution.) Recording the project anywhere else is the resolver's job when it is
   called with `--for-write`, never this skill's.

**Decomposed projects** (Phase 2.5) save all files flat in the same `plans/` dir: the master
plan as `YYYY-MM-DD-<topic>-master-plan.md` and each sub-plan as
`YYYY-MM-DD-<topic>-sub-NN-<slug>-plan.md`, numbered in dependency order.

## Plan Document Format

Save to `<records home>/plans/YYYY-MM-DD-<topic>-plan.md`. The literal template — Research
Summary, Decisions in force, Preflight, per-stage tasks with their fields, and the gate
shape — is `references/plan-document-template.md`. Copy it there rather than reconstructing it from
memory; the parser-safety rules (a non-checkbox bullet in Decisions in force, the exact
`- **Status:** [ ]` form) are why it is a fixture rather than a sketch.
## Phase 3 — The Red-Green Loop

Every task carries a `Test:` and a `Red-Green max cycles:` because execution drives them
through a diagnose → fix → retest loop with a bounded budget. The loop itself is
`executing-plans` Step 3.3 and is not restated here. What the plan owes it: a test that is a
**runnable command or a checkable criterion**, never "should work", and a cycle budget
(default 3). The test asserts the **outcome** the task promises, not a side effect of it, and
each claim in it would go red if that claim were false; a task that prepares something for
later tasks tests that it did (`references/task-fields.md` § `Test:`).
## Phase 4 — Stage Gates

After all tasks in a stage pass their individual tests, run a stage-level integration check before proceeding to the next stage. Individual tests prove each piece works. Stage gates prove the pieces work together.

### What a stage gate checks

- **Integration**: The tasks in this stage interact correctly (e.g., the API endpoint serves data from the database schema that was just created)
- **Regressions**: Scoped to the gate's position in the plan. Intermediate gates check at **stage-scope** — cheap host-side checks in full, any expensive suite restricted to the modules the stage touched, never `clean`. The final gate (and close-out) runs **plan-scope** — one full clean pass. A cheap full suite (well under ~5 min) skips the tiering. Scope policy: `references/test-scope-tiers.md`.
- **Goal verification**: The stage's stated goal is actually met end-to-end, not just task-by-task
- **Early integration premise** — at the first driveable stage, author one bounded
  smoke case against the actual available artifact and configured route. Record
  requirement origin, evidence claim and remaining authorized work in that stage's
  fields (template). Label fixture/synthetic scope explicitly; a missing requested
  service blocks its live claim. Continue other runnable authorized work, and use a
  structured wait only when the next actual operation depends on it. This early
  smoke does not replace the whole-artifact `(goal)` check or final live validation.
- **Live artifact over static checks** — **once per plan**, at the final gate of the last stage shipping user-visible behaviour, and only what this session can drive itself (adb, a probed VM, an endpoint). Unit tests pass on stubbed features; only live interaction catches them. A check needing a person the session cannot reach — a fluent reviewer, an accessibility tester, the owner's phone — is not a gate check but a close-out `ACTION NEEDED:` item: a gate waiting on a person stalls. Why once: 167 VM calls, one master.

### Every fact has one owner

**A fact a task's `Test:` proves is not re-proved at the gate.** Write each gate check to
verify something no task test already decides — integration between the stage's tasks, the
stage's goal end-to-end, regressions. Two exceptions, and they are the useful cases:

- **A strictly wider set**, provided the widening is *nameable*: "the task proved the route
  is gone from the router; the gate sweeps the whole source tree for the vocabulary". The
  gate owns the *class*, the task owns its *instance*.
- **A different mechanism proving a different claim.** A test asserting the code behaves
  and a sweep asserting no stale prose survives are two facts, not one fact twice.

**A `(judgment)` line may never restate a fact an executable check in the same plan already
decides.** The marker routes to an evaluator dispatch — the most expensive check in the
plan. Reserve it for what genuinely needs a reader.

A worked example of one fact verified four times: `references/gate-authoring.md`.

### Write a set-valued check as the sweep that proves it

**A gate check over a set is an executable sweep, not a spot check**. A check that
names one artifact where the goal is a property of many cannot fail on the siblings that make
the defect class — they survive the gate, and each survivor costs another remediation round.
So a check whose goal quantifies over a set is written as the command that sweeps it:
`! grep -rl '<the stale claim>' <scope>` rather than "file X no longer says Y". A sweep for
a forbidden call matches the bare name, so an import cannot hide the call
(`references/set-valued-checks.md` § The fifth error).

A check that genuinely needs a reader carries the **(judgment)** marker and routes to the
gate's evaluator — the sanctioned escape hatch, not a loophole. **Most gates carry none:**
each buys an evaluator dispatch at every tier above `none`, and a fresh evaluator never
returns empty-handed (one owner's three sub-plans, 2026-09-10/11: 13 of 13 gate evaluators
returning fixes). Write one only where a reader decides what no command can.

Verify before presenting: `python3 scripts/validate-gate-checks.py <plan>` (in this skill's
directory). **A newly authored plan may not be presented while it reports INSTANCE-SHAPED.**

Worked examples, the predicate-vs-instance test, and the validator's classification rules:
`references/set-valued-checks.md`.

### When a stage gate fails

A gate failure is rarely a *single instance*: treat it as a defect class sampled once, name
the set the finding quantifies over, and make the repair test the **sweep over that set** —
otherwise the siblings survive and each costs another round. That rule is not gate-only in
`executing-plans` — it fires wherever a defect surfaces, and a gate is simply its sharpest
caller.

`executing-plans` owns the operative procedure (severity, budget, exit criterion,
escalation). Do not restate those rules here. What matters at *authoring* time is that gate
checks are shaped so a class can fail them (this trunk's § Write a set-valued check as the
sweep that proves it).

---

## Phase 5 — Dispatch

Mark a task `Dispatch: YES` when its `Depends on` are satisfiable independently and it
shares no file with a sibling. The dispatch procedure belongs to
`../dispatching-parallel-agents/SKILL.md` and `executing-plans` Step 3.2; what the *plan*
owes them is accurate `Depends on` / `Blocks` / `Dispatch` fields and a file-conflict-free set.
`python3 scripts/validate-dispatch.py <plan>` checks exactly that before presenting: it fails a
YES task that depends on a same-stage sibling, two YES siblings sharing a `Scope` path, a YES
task with no `Scope`, a stage-dependency cycle, and a master's YES sub-plan that reads a sibling.
## Checklist — Before Presenting the Plan

**Light plans use § Checklist — Light plans instead of this one.** This full checklist
applies to Standard plans (and, with the decomposition addendum, Master plans).

Before showing the plan to the user, verify **every** item in
`references/authoring-checklist.md` — that file is the full list, and most items name the
section that owns the rule they enforce. **It is a mandatory read on the Standard path.**
Five command-decided items are restated here:

- [ ] `python3 scripts/validate-gate-checks.py <plan>` reports **zero INSTANCE-SHAPED** and **zero GOAL-CHECK-MISSING** — no check names one artifact where the goal spans many items or widens past its set; a `(goal)` check sweeps the goal (`references/set-valued-checks.md`, `gate-authoring.md`)
- [ ] **Every gate check can pass as authored**: the same validator reports **zero SELECTOR-UNMATCHED** — every `pytest <file> -k <expr>` selector in a gate is one some task's `Test:` builds toward, so no gate names a filter that collects nothing (`executing-plans` re-checks it at Preflight with `--collect-only`)
- [ ] **No task's own `Test:` runs the whole suite**: on a plan declaring expensive-suite tiering, the same validator reports **zero TASK-TEST-UNSCOPED** — every task `Test:` is path- or suite-scoped, or its task carries an explicit `full-suite: accepted` (`references/test-scope-tiers.md`)
- [ ] `python3 scripts/validate-dispatch.py <plan>` exits 0 (§ Phase 5 — Dispatch)
- [ ] The plan is saved to the project's `<records home>/plans/`, resolved through `lib/records_home.py --for-write` (exit 2 stopped the save and created nothing)

**Additionally, for a decomposed project (master plan + sub-plans):**

- [ ] The decomposition trigger actually held (Phase 2.5) — 2–7 sub-plans, each independently executable
- [ ] Register `Depends on` / `Blocks` fields are symmetric across sub-plan entries
- [ ] Every register entry ends with a `**Gate:**` block containing at least one cross-plan integration check
- [ ] Every sub-plan carries the `Master: ./<master-file>` backlink; every register `Plan:` link resolves
- [ ] The master plan is parser-safe: no raw `- [ ]` bullets outside `**Gate:**` blocks, no tasks, no Preflight (see `references/master-plan-format.md`)

---

## Checklist — Light plans

For a **Light** plan (Phase -0.5), verify only the twelve Light items; the full checklist
does not apply. See `references/authoring-checklist.md` § Checklist — Light plans.
