# Light Plan Format Reference

Canonical format for a **Light plan**: the smallest plan the pipeline produces, for a
job that is real work but too small to earn the full staged apparatus. This file is the
single source of truth for that format — `planning-projects` writes it, `executing-plans`
executes it, and the plan parser (`plan-parser.md`, implemented by `lib/plan_parser.py`)
reads it deterministically.

A Light plan is one stage of a handful of tested tasks. It keeps the invariants that
protect against drift and drops the artifacts that only pay off across long horizons. It
sits one rung below the standard staged plan on the format ladder:

| Format | Trigger | Artifact |
|--------|---------|----------|
| **Direct** | ≤ ~2 tasks, one session, no staging value | No plan file — execute directly with a test + commit |
| **Light** | Single stage, ≤ ~5 tasks, one session, one stack | This format (`*-light-plan.md`) |
| **Standard** | Everything between | The full staged plan (SKILL.md § Plan Document Format) |
| **Master** | > ~6 stages / ~25 tasks, or multiple workstreams | Master + sub-plans (`master-plan-format.md`) |

The triage that picks a format lives in `planning-projects` SKILL.md § "Phase -0.5 —
Format triage". This file only defines the Light artifact.

## When to write a Light plan

Write a Light plan (rather than a Standard one) when ALL of these hold:

- The whole job fits in **one stage of 2–5 tasks**. Fewer than 2 tested tasks is a Direct
  job (no plan); a 6th task or a second natural stage means it's a Standard plan.
- It runs in **one session on one stack** — no fan-out to parallel agents, no
  cross-session handoff.
- The risk is low and the path is understood — no spike, no rollback choreography, no
  external dependency whose failure needs a documented recovery.

When any of those is false, write a Standard plan. Borderline cases round **up** to the
heavier format; the user can always override down.

## Invariants kept vs artifacts dropped

The Light format is defined by exactly this split. The kept column is the drift
protection — it is not negotiable at any format. The dropped column is long-horizon
guardrail that a one-session job cannot need.

| Kept at Light (invariants) | Dropped at Light (long-horizon artifacts) |
|----------------------------|-------------------------------------------|
| Concrete runnable `Test:` per task | Mandated **Research Summary** section (findings go inline as a short **Context** line) |
| `- **Status:** [ ]` per task, flipped on green | Full **Preflight** checklist (only "baseline tests pass", folded into the gate) — **except** the `**Test-scope commands**` block on an expensive-suite project, which is kept; see below |
| Commit per green task | **Risk** / **Rollback** stage fields |
| Red-Green cycle budget (default 3) | `Blocks:` field (derivable from `Depends on` at ≤5 tasks) |
| Run-to-completion + stop conditions | `Dispatch:` field (no fan-out at this size) |
| A single **Stage 1 Gate** incl. the full existing test suite | Tier-1 per-task review — the format replaces it with one whole-diff review before close-out, and the declared tier then decides whether even that runs (`high` restores Tier-1 for the risk-listed tasks its declaration names) |
| honest-gates integrity contract | Default goal-evaluator dispatch (opt-in at Light) |
| | Mirror-grep version-bump ritual (one stated bump) |

## Deltas from the Standard authoring flow — what each one means

`../SKILL.md` § Light plans lists the five deltas as rules. This section is what each of them
means in practice, for an author deciding how far to scale a step down.

**Research is proportionate, not a mandated section.** The Research Summary is replaced by a
1–3 sentence **Context** line at the top of the plan: the key facts that ground the change.
Skip the online/linked-notes research sweep unless a specific unknown demands it — at this size the
sweep usually rediscovers what the author already knows. What does *not* scale down is the
backlog scan and, where `docs/workflows/` exists, the workflow-spec declaration: a Light plan
that silently duplicates an open backlog item is the same planning bug at any size, and
behavior contracts do not get a size exemption.

**Preflight collapses into the gate.** There is no Preflight section at all. The only
pre-execution check that matters at this size — "baseline tests pass" — lives as a bullet
inside the single `### Stage 1 Gate`, alongside the git bootstrap `executing-plans` always
does. Everything else a Standard Preflight verifies (tool versions, API reachability, the
dispatch probe and roster) is either irrelevant to a one-session job or moot with no fan-out.

**One exception, and it is a fact rather than a ceremony.** On a project whose full suite
crosses the ~5 min threshold (`test-scope-tiers.md` guard rail 1), a Light plan carries the
`**Test-scope commands**` block — the `stage-scope:` / `plan-scope:` pair — immediately after
its `Context:` line:

```markdown
**Test-scope commands** (per references/test-scope-tiers.md):
- stage-scope: `./gradlew :app:testDebugUnitTest`
- plan-scope:  `./gradlew clean check connectedCheck`
```

What the Light format drops is long-horizon *guardrail*. How expensive this project's suite is
is not guardrail — it is a property of the project, true whatever the plan's size, and the
authoring checklist's rule that a task `Test:` be scoped or carry `full-suite: accepted` is
**armed by this declaration and by nothing else**. Without the block that rule is unenforceable
at Light: a Light plan whose task `Test:` collects the whole suite reports zero findings. A
rule stated
in a checklist and unreachable by its checker is a check that measures nothing.
Below the threshold the block is omitted, as at any size.

**No Risk / Rollback / Blocks / Dispatch fields.** One low-risk stage does not need a rollback
rehearsal, and with ≤5 tasks in one session there is no fan-out to coordinate. `Depends on`
survives, but only where a task genuinely consumes a prior task's output.

**Output location is unchanged.** A Light plan saves to the same `<records home>/plans/`
under the same resolution as any plan (`../SKILL.md` § Output location). It is a first-class plan, just a small one, and the only
thing its filename changes is which format `executing-plans` detects.

**Use the Light checklist**, not the Standard one:
`authoring-checklist.md` § Checklist — Light plans.

## Naming

A Light plan lives in the same `<records home>/plans/` directory as any other plan:

```
YYYY-MM-DD-<topic>-light-plan.md
```

Detection rule (used by `executing-plans` to recognize the format): a file is a Light
plan when its name ends in `-light-plan.md` **or** its first heading is `# Light Plan:`.
This mirrors the master-plan detection rule. The deterministic plan parser does **not**
use this rule — it routes purely off the `- **Status:**` field (see Parser-safety rules
below), so it treats a Light plan identically to any Status-field plan without ever
reading the filename or first heading.

## Light plan document format

A Light plan is one `## Stage 1:` holding 2–5 `### Task 1.N:` tasks and one
`### Stage 1 Gate`. It carries no Preflight section, no Risk/Rollback, and no
Blocks/Dispatch fields.

```markdown
# Light Plan: [Name]
Date: YYYY-MM-DD
Format: Light — [the trigger that selected this format, e.g. "single stage, 4 tasks, one session"]

**Context:** [1–3 sentences: what this changes and the one or two facts that ground it —
the proportionate replacement for a Research Summary. Link a source if one matters.
Include any decision in force that bears on the change, inline:
"DEC-NNN binds this — <constraint in half a line>."]

[The owner's answers to the questions execution would stop for (`owner-decisions.md`) —
non-checkbox bullets; `- none — the catalog triggered no question (swept YYYY-MM-DD)` when
it triggers nothing. The section holds only one-line entries (or the `none` line) and blank lines: `owner-decision.py` reads nothing else, so this note stays above it.]

## Owner decisions

- **OD-1** — [the decision, in one line] — owner, YYYY-MM-DD: "[their words]" — applies to: [one place: Preflight, close-out, Stage N or Task N.M] (`[each command it covers]`)

## Stage 1: [Name]

**Outcomes:** [who uses the result — omit only when nobody outside the code meets it]
- Works: [what they get]
- [a way it can fail] → [what they see]

### Task 1.1: [description]
- **Status:** [ ]
- **Scope:** [the set this task sweeps — omit for a single-artifact task]
- **Test:** `[exact command or concrete pass/fail criterion]`

### Task 1.2: [description]
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Test:** `[exact command or concrete pass/fail criterion]`
- **Red-Green max cycles:** 3

### Stage 1 Gate
- [ ] **(goal)** [the plan's goal as one cheap sweep over the WHOLE artifact it is about, in every gate from the first one whose artifact exists — gate-authoring.md § The plan's goal is a check from the first gate]
- [ ] [Class predicate — the sweep that proves a set-wide property, e.g. `! grep -rl '<claim>' <scope>`]
- [ ] Full existing test suite passes (regressions check)
<!-- (judgment) only where a reader decides what no command can — it buys an evaluator; most
     light plans carry none -->
```

**The class-predicate rule applies at Light too.** A gate check asserting a property of a
*set* is written as the command that sweeps it, or carries the `(judgment)` marker — see
the main skill's "Write a set-valued check as the sweep that proves it". Light drops
ceremony, not the rule: an instance-shaped check costs a remediation round at any plan
size, and a Light plan has only one gate to catch it.

### Field semantics

| Field | Meaning |
|-------|---------|
| `Format` | Mandatory header line directly under `Date:`. Records the triage decision (Phase -0.5) and the trigger that selected Light, so a reader sees *why* this is a Light plan, not just that it is. Form: `Format: Light — <trigger>`. |
| `Status` | `[ ]` planned → flipped to `[x]` by executing-plans the moment the task's test goes green. Authoritative done-marker, identical to Standard plans. |
| `Depends on` | Optional. Present only when a task genuinely needs a prior task's output; omit for independent tasks (they simply run in listed order). No `Blocks` counterpart at Light. |
| `Test` | Mandatory. A concrete runnable check — the same bar as a Standard task. "It should work" is not a test. |
| `Red-Green max cycles` | Optional; defaults to 3 when omitted. |

### Decisions at Light

A Light plan carries decisions as **one line inside `Context:`**, never as a
`## Decisions in force` section. The section is Standard-and-up machinery; a Light plan
that grows one has been stretched past its bounds (apply the upgrade rule instead).
`## Owner decisions` is not that section and stays: the owner's answers bind a run at
any size.

What does **not** scale down: the scan still runs, exactly like the backlog scan. A small
plan can violate a binding constraint just as thoroughly as a large one, and the cost of
finding out at review time is the same. If a Light task deliberately overrides a decision,
it carries the same `Supersedes DEC-NNN — <why>` citation a Standard task would, and the
single Stage 1 Gate carries the conformance check. If nothing binds it, say so in one
clause rather than leaving the reader unable to tell a clean scan from a skipped one.

The close-out line is identical to a Standard plan's:

```markdown
**Completed:** YYYY-MM-DD — commits: <list>
```

## Upgrade rule (do not patch a Light plan past its bounds)

A Light plan that grows during execution — a task splits into a second stage, or a 6th
task appears — is **re-issued as a Standard plan**, not patched in place. The Light
format has no Risk/Rollback/Blocks/Dispatch fields to absorb the growth, and stretching
it produces a malformed hybrid. Re-run `planning-projects` on the expanded scope; the
Light plan file is superseded. This keeps the format boundary crisp: a `-light-plan.md`
file always means "single stage, ≤5 tasks."

## Parser-safety rules (mandatory)

The deterministic parser (`lib/plan_parser.py`) is already correct for Light plans **by
construction** — a Light plan keeps the three line shapes the authoritative path keys on
(`## Stage N`, `### Task N.N:`, `- **Status:** [ ]`), so it needs no parser code. The
rules that keep it safe are the same ones every Status-field plan follows:

1. **Task done-state uses the `- **Status:** [ ]` field form, never a bare `- [ ]`
   bullet.** The field form is the authoritative signal; a bare checkbox in a task body
   would be suppressed anyway, but keep task bodies field-shaped.
2. **The only raw `- [ ]` bullets are under the `### Stage 1 Gate` heading.** On the
   authoritative path the parser ignores *every* raw `- [ ]` bullet outside a `## Deferred`
   section regardless of heading — so gate bullets never become candidates. Keeping them
   confined to the gate is format cleanliness, not the safety mechanism (the `Status:`
   field is).
3. **No Preflight section.** A Light plan has none — the single baseline-tests check lives
   inside the gate. (The parser excludes Preflight bullets too, so this is about format
   cleanliness, not parser safety.)

A Light plan following this file yields exactly one backlog candidate per `Status: [ ]`
task while in progress, and **zero** candidates once its close-out line lands and every
task is `[x]` — identical to a Standard plan. That invariant is locked by
`core/lib/tests/test-plan-parser.py`.

## Execution semantics (summary)

Full model in `../../executing-plans/SKILL.md` § "Light plans". In short: Preflight is
git-bootstrap + baseline tests only; tasks run inline through the normal Red-Green loop
(no parallel dispatch at this size); the per-task review is replaced by **one** whole-diff
`planning:code-reviewer` pass after the last task goes green and before the gate — the
*format* sets that shape, while the plan's declared **review-scope tier** decides how many
passes actually run and whether an evaluator joins them (`none` runs none; `high` restores
Tier-1 even here, for its risk-listed tasks); the goal-evaluator follows that tier rather than being opt-in
by format; and close-out applies a **single stated** SemVer bump (naming the manifest/marketplace mirror pair explicitly in this repo
rather than grepping for every mirror). Everything in the "Kept at Light" column above —
Status flips, commit per green task, cycle budgets, stop conditions, honest-gates, and
one handoff note at the single gate — is unchanged from a Standard plan.
