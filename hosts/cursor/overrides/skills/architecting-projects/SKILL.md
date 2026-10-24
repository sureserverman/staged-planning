---
name: architecting-projects
description: Use after a design is validated (or on a direct architecture request) to produce a researched, user-approved architecture document that planning-projects consumes. Triggers on "design the architecture", "architecture options", "pick an architecture", "compare architecture candidates".
---

> On Cursor, `<planning-plugin>` is this plugin's installed folder: the folder that holds `skills/` and `.cursor-plugin/` (`~/.cursor/plugins/local/planning` for a local install), which is `../..` from this SKILL.md. In a shell command use its absolute path, quoted.

# Architecting Projects

Turn a validated design into a **researched, user-approved architecture** before any
plan is written. The output of this skill is an **architecture document** whose
`ARCH-NN` sections the `planning-projects` plan cites and the build follows.

**Announce at start:** "Using the architecting-projects skill to research and validate the project architecture."

<HARD-GATE>
Do NOT write the architecture document, invoke `planning-projects`, or scaffold
anything until the comparison matrix has been presented and the user has explicitly
approved one option. Research findings are not a decision — the user's approval is.
</HARD-GATE>

## Position in the pipeline

`brainstorming` (validated design) → **architecting-projects** → `planning-projects`
(staged plan citing ARCH-IDs) → `executing-plans` (builds exactly that structure).

Also directly invocable without a prior design doc — then Phase 1 grounds from the
user's brief and the codebase instead.

**Skip rule (for callers):** skip this skill only when the design has no meaningful
structural surface — a config change, a single-file fix, a component-level change, a
doc update. A design has a
structural surface when it touches module boundaries, directory layout, dependency
injection points, or cross-module interfaces — anything shaping how multiple
files/modules relate; a component-level change or single-file logic fix does not.
Skipping is always stated explicitly ("no structural surface: straight to
planning-projects"), never silent.

---

## Checklist

Create a task for each of these and work them in order.

1. **Ground** — design doc, codebase, notes, backlog
2. **Derive candidates** — 2–4 stack-concrete architecture options
3. **Research in parallel** — one `architecture-researcher` agent per candidate
4. **Compare and recommend** — matrix + named recommendation; user approval gate
5. **Write the architecture document** — parser-safe, ARCH-NN sections
6. **Hand off to planning-projects**

---

## Phase 1 — Ground

Before deriving any candidate:

- Read the **design doc** from `brainstorming` (usually
  `<records home>/plans/YYYY-MM-DD-<topic>-design.md`) — its constraints and
  success criteria bound every candidate. Directly-invoked with no design doc: distill
  the same facts (problem, constraints, stack, scale) from the user's brief and
  confirm them in one message before proceeding.
- Read the **codebase** if one exists: manifests, current layout, established
  dependencies, test framework. An existing project constrains candidates hard —
  re-architecture candidates must state their migration surface.
- Check **linked notes** (notes the project already uses) for prior architecture
  decisions and gotchas on this stack.
- Scan the **backlog** for open structural items the architecture should resolve or
  respect; note matches for the eventual plan's fold-in.

## Phase 2 — Derive candidates

Produce **2–4 candidates**. Each candidate is a named pattern **plus** a one-line
module-layout sketch concrete to this language/framework — "hexagonal: `core/` domain
crates, `adapters/` per port, binary in `cli/`" — never a pattern name alone.
Generic candidates ("monolith vs microservices") with no stack-level shape are the
failure mode this skill exists to prevent.

Fewer than 2 defensible candidates? Then the architecture is genuinely forced —
say so, present the single option with its evidence as a degenerate matrix, and still
get explicit approval before writing the doc.

## Phase 3 — Research in parallel

Dispatch **one `architecture-researcher` agent per candidate, concurrently**. Each
dispatch carries: the candidate (name + layout sketch), the stack (with pinned
versions where known), the constraints from Phase 1, and the codebase path or an
explicit greenfield flag.

On return, **discard uncited claims** — a finding with no doc URL, named real project,
or codebase file behind it does not enter the matrix. Then:

- An agent that fails or returns only uncited prose: drop that candidate and flag the
  gap in the matrix ("Candidate C: research failed — excluded").
- **Fewer than 2 evidenced candidates survive: stop.** Tell the user rather than fake
  a comparison; a single-survivor matrix is presented as the forced-choice case from
  Phase 2, with the failure noted.
- No web access this session: proceed on codebase/notes evidence, and carry the
  agents' `[web-unverified]` markers into the matrix and the final doc.

## Phase 4 — Compare, recommend, approve

Present a **comparison matrix** — one row per surviving candidate, columns: fit
against each named constraint, complexity, evolution paths, migration surface (for
existing code), evidence quality. Below it, a **named recommendation with a specific
reason**, exactly like `brainstorming` Phase 3.

Then the **approval gate** (the HARD-GATE above):

- User approves an option → Phase 5.
- User rejects all options → loop back to Phase 2 with the rejection reasons as new
  constraints. **Maximum 2 loops**, then escalate: present what was tried and ask for
  a direction rather than generating a third round unprompted.

## Phase 5 — Write the architecture document

Resolve the output location exactly as `planning-projects` → "## Output location" does:
run `python3 <planning-plugin>/lib/records_home.py --project <repo> --for-write` and obey its exit code: 0 or 3, use the printed records home (on 3 it is the repo's `docs/`, warn once); 2, stop and show the message, creating nothing. Passing `--for-write` matters here: on a direct invocation this skill can
be the first to write a record for a brand-new project, and a configured resolver sets the
project up on that call.

> **On Cursor, check that the command ran.** `<planning-plugin>` is written out as the
> installed folder (`~/.cursor/plugins/local/planning` for a local install), because Cursor
> gives a skill no plugin-root variable, so a wrong path is easy to type. Python also exits
> **2** when it cannot open the file, which looks exactly like *"stop, create nothing"*. A
> **2** whose stderr does not start with `records_home:` is a **broken invocation**, not an
> answer: fix the path and rerun. The exit-code contract itself stays in
> `../../references/records-resolver.md`.

Save as:

```
<records home>/plans/YYYY-MM-DD-<topic>-architecture.md
```

### Record the decision in the register

An architecture doc is **event-shaped**: it captures one architecture exercise and
is rarely reopened once its plan has executed. The decision it encodes outlives it
— and binds projects that will never read this file. So after the doc is written
and approved, append a `DEC-NNN` entry to `<records home>/decisions.md` via the
`decisions` skill (`add`), with:

- `Source:` this architecture doc's filename plus the `ARCH-NN` sections that carry
  the decision (`2026-07-25-storage-architecture.md — ARCH-02, ARCH-03`);
- `Reason:` the `## Decision` rationale *and* the discarded candidate from
  `## Alternatives rejected` — a reason with no rejected alternative is a
  restatement, not a reason;
- `Domains:` the platform/stack slugs the decision binds (`android`, `rust`,
  `ubuntu`, …), or `none` if it is genuinely project-local.

Format: `../decisions/references/decisions-format.md`. This is the step that keeps an
architectural choice findable long after the architecture doc stops being read.

### Parser-safety rules (MUST)

The doc lands in the same `plans/` directory the plan parser scans, so it is
parser-safe **by construction**:

- The filename MUST NOT match `*-plan.md` (the `-architecture.md` suffix is the rule).
- The doc MUST NOT contain raw unchecked bullets (`- [ ]`) anywhere — lists use plain
  `-` bullets.
- The doc MUST NOT contain `- **Status:**` fields.

An architecture doc that emits backlog candidates is malformed; the fixture suite
(`core/lib/tests/fixtures/plan-parser/sample-architecture.md`, run by
`core/lib/tests/test-plan-parser.py`) locks this invariant.

### Document format

```markdown
# Architecture: <Topic>
Date: YYYY-MM-DD
Design: ./<design-doc-filename>          (when one exists)
Status: Approved <YYYY-MM-DD>

## Decision
<chosen option, one paragraph, ADR-style: context → decision → consequences>

## Alternatives rejected
- <candidate>: <why not, from the matrix — cited>

## ARCH-01 Directory layout
<fenced tree, concrete names — the tree the plan's scaffold tasks create>

## ARCH-02 Module boundaries
<per-module responsibility and allowed dependencies>

## ARCH-03 Key interfaces
<the boundary signatures, per the winning candidate's research>

## ARCH-04 Data flow
<main-use-case sequence through the modules>

## ARCH-05 Library choices
<lib + version + role, citations carried from research>

## Risks
- <risk>: <mitigation or explicit acceptance>

## Evidence
- <the citations backing the decision, carried from the researcher returns>
```

Number further sections `ARCH-06` onward as needed; never renumber existing IDs in a
later revision — plans cite them.

## Re-architecture mode (existing codebases)

When the project has an existing codebase with significant structure (a module tree
beyond a handful of files — not a scratch dir or a single-crate stub), the flow
deepens; it does not change shape:

- **Phase 1 additionally inventories the current structure**: the real module map
  (directories, crates/packages, who-depends-on-whom), captured as a compact tree +
  dependency list. This inventory rides every researcher dispatch.
- **Phase 3 dispatches carry the inventory**, and each researcher's Risks/Fit
  sections must address the migration explicitly: what moves, what splits, what the
  intermediate states are. A re-architecture candidate whose research ignores the
  current layout is uncited-by-construction — treat it like any uncited claim.
- **Phase 4's matrix weighs migration surface as a first-class column** (it is
  already listed there) — for large codebases it often dominates the decision.
- **Phase 5's doc gains a Migration map section** (numbered like any other, e.g.
  `ARCH-06 Migration map`): a current→target mapping per module plus an ordered
  sequence of migration steps, each leaving the build green. `planning-projects`
  turns those steps into staged tasks — the migration order in the doc is the
  skeleton of the plan's stage order. Same parser-safety rules apply: plain `-`
  bullets only.

Greenfield projects skip all of this — the greenfield flag in the dispatch is what
tells the researcher no inventory is coming.

## Phase 6 — Hand off to planning-projects

Say to the user:

> Architecture approved and saved to `<path>`. Handing off to the `planning-projects`
> skill — the plan's structure-creating tasks will cite these ARCH-IDs, and its final
> stage gate will carry the architecture-conformance check.

Then invoke `planning-projects` with both the design doc and the architecture doc as
input. The **only** skill invoked after this one is `planning-projects` — scaffolding
the tree directly is `executing-plans`' job, gated by the plan.

---

## Key principles

- **Research is per-candidate and parallel** — one dedicated researcher each, blind to
  the other candidates.
- **Uncited claims are discarded** — the matrix holds evidence, not vibes.
- **The user chooses** — the skill recommends, the approval gate decides.
- **Parser-safe by construction** — no unchecked bullets, no Status fields, no
  `*-plan.md` filename.
- **ARCH-IDs are stable** — downstream plans cite them; revisions append, never
  renumber.
- **Terminal state is `planning-projects`** — never scaffold, never execute.
