# Plan Parser Reference

This document defines the deterministic rules for parsing planning-projects plan files (any `plans/*.md` in a project's records home, by default `<repo>/docs/plans/`) to identify unexecuted work that should become backlog candidates, and to read a plan's Status, gate and terminal markers. All detection is regex plus a state machine; no LLM is invoked at any point.

The rules are implemented once, in the plugin's shared library `lib/plan_parser.py` (source: `core/lib/plan_parser.py`). It is pure functions and compiled regexes, stdlib only, with no I/O on import. Scripts load it by file path from the plugin root and never restate its regexes: a change to one pattern changes done/total math, gate state and backlog candidates in every consumer at once, so one definition is the only way they stay in agreement. Its consumers include the backlog `unify` operation, the plan-progress status line and the master-register check.

The regression suite is `core/lib/tests/test-plan-parser.py`. Every fixture it uses is synthetic: the plans are inline, and the architecture-doc fixture is read from `core/lib/tests/fixtures/plan-parser/sample-architecture.md`.

## Input signals

### 1. Unchecked task checkboxes

Plan files written by the planning-projects skill use `### Task N.N:` section headers, preflight/stage-gate bullets, and sub-task bullets. The parser reads these as a state machine: when a `### Task N.N:` header is entered, it collects all subsequent list items until the next `###`-or-higher heading or a `---` boundary.

Relevant patterns:

- **Task section header:** `^### Task \d+\.\d+:`
- **Unchecked bullet:** `^- \[ \]\s+`
- **Checked bullet:** `^- \[x\]\s+`

A Task N.N section is considered "unchecked" (and therefore a candidate) when either of the following is true:

- The section header is present and the body contains at least one `- [ ]` bullet and zero `- [x]` bullets.
- The section header is present and the body contains no bullets at all (i.e. the task was never started — an orphan header is logged and skipped per the malformed-plan rule in § Hard rules, not emitted as a candidate).

A section with a mix of `- [ ]` and `- [x]` bullets is partially done; each remaining `- [ ]` bullet is its own candidate, attributed to that Task N.N section.

Stage gate sections are **excluded** as candidate sources by design.

- **Stage gate header:** `^### Stage \d+ Gate` — its bullets are integration checks that restate task completion. Emitting them as separate backlog items would double-count work whose root task is already (or will be) a candidate.
- Treat the gate block as terminating the previous Task N.N's scope and otherwise skip its bullets entirely. If a stage gate's bullets are all unchecked, that signals the stage isn't done — but the unchecked Task N.N sections within the same stage already surface that.

`## Preflight` and `## Decisions in force` bullets are excluded the same way. The decisions format mandates non-checkbox bullets, but a convention the parser does not enforce is one an author eventually breaks, and a stray `- [ ]` there would become a false candidate on every plan that records a decision.

On this legacy path the caller passes `done_stages`, the set of stage numbers it found confirmed executed (for example by commits dated on or after the plan's filename stamp). Unchecked bullets inside such a stage are suppressed. The library never runs git itself.

### 2. Explicit Deferred sections

Any heading matching `^## Deferred$` or `^### Deferred$` (case-sensitive, no trailing text) opens a Deferred block. All bullet items (both `- [ ]` and bare `- ` items, regardless of checkbox state) under that heading until the next `^## ` heading or a `^---$` boundary are emitted as candidates. Checkbox state is intentionally ignored here — items were explicitly parked and all of them surface.

Pattern for heading detection: `^#{2,3} Deferred$`

Boundary patterns that close the block: `^## ` (any level-2 heading) or `^---$`.

### 3. Stale-plan candidates (opt-in via `--include-stale`)

A plan authored long ago that still carries unresolved items is quiet debt: no
one is working it, and nothing else surfaces it. This signal finds those, and is
**off by default** because across many plans it would otherwise flood the sweep.
The library supplies the age (`stale_age_days()`, `STALE_DAYS`); the caller decides
whether to run the signal.

**Staleness comes from the plan's filename date stamp**, not from git and not
from mtime:

```
2026-04-15-foo-plan.md   ->   authored 2026-04-15
```

A plan is stale when `today - <filename stamp> > 90 days`.

**Why not git.** A records home need not be a git repository, so a plan's last
commit may not exist. Read from git, every such plan's staleness would be
permanently unknown.

**Why not mtime.** mtime records the last *write*, which a migration, a `cp`, or
an `executing-plans` Status flip all trigger. A plan executed yesterday and one
bulk-copied last month become indistinguishable.

**Why the filename stamp works.** It is assigned at authoring, survives copies
and migrations, and is already load-bearing (`unify --write` tags new entries
with it). It measures age-since-authored, which is the question this signal asks.

**Unstamped filename → staleness unknown.** A file whose name does not begin
`YYYY-MM-DD-` is excluded from signal 3; it is still parsed for signals 1 and 2.
`stale_age_days()` returns `None` for it, never a number.

The exclusion is **silent** — there is no per-file log line, because per-file
output would change the default path's stdout, which must stay byte-identical
with the flag off. Note the consequence: an unstamped legacy plan is *doubly*
invisible, because `plan_date()`'s `0000-00-00` sentinel also makes every commit
count as later and so suppresses its items on the legacy path. `--include-stale`
can never reach such a plan. Renaming it with a date stamp is the fix.

**No duplication.** An item already emitted by signal 1 or 2 is never re-emitted
as `stale-plan-unchecked`. The flag *adds* candidates from plans the normal
heuristics skip; it never relabels ones they already found.

**Scope: signal 3 only ever fires on legacy plans.** It surfaces what the
git-stage suppression hid, and that suppression exists only on the legacy
heuristic path — `parse_plan_status()` never consults `done_stages`, so a plan
carrying `- **Status:**` fields (every modern plan, Light plan, sub-plan and
master register) already surfaces all its open work unconditionally through
signals 1 and 2. For those plans `--include-stale` is a structural no-op, and
that is correct: there is nothing hidden for it to reveal.

## Candidate output shape

`parse_plan(text, plan_rel, done_stages)` returns a list of records:

```
{"source": "plans/2026-05-22-foo-plan.md — Stage 2 / Task 2.3",
 "title":  "Add retry logic to the upload handler",
 "signal": "status-unexecuted"}
```

Field definitions:

- **`source`** — `<plan_rel> — <locator>`. `plan_rel` is the path the caller passes, relative to the records home (never absolute), e.g. `plans/2026-05-22-foo-plan.md`. The locator varies by signal:
  - Status task: `Stage N / Task N.N` (if a stage grouping is detectable from context) or `Task N.N` alone.
  - Legacy unchecked bullet: `Stage N / unchecked: <first 50 characters>` (or `checklist / unchecked: …` outside any stage).
  - Deferred bullet: `Deferred / bullet K` (K is 1-based index within the Deferred block).
- **`title`** — the item text, stripped of its structural prefix. For a task header the `### Task N.N: ` prefix is removed; for a bullet the `- [ ] ` or `- ` prefix is removed. No further transformation.
- **`signal`** — one of five values, and these are the complete set:
  - `status-unexecuted` — a task whose `- **Status:**` field is `[ ]`.
  - `status-partial` — a task whose `Status` is `[~]`: started but unfinished. Distinct from `status-unexecuted` because residual work is still open work, but the task is not untouched.
  - `unchecked-open` — an unchecked `- [ ]` bullet inside a Task N.N section. Preflight, Decisions and Stage Gate bullets are NOT a source.
  - `deferred-section` — any bullet under an explicit Deferred heading.
  - `stale-plan-unchecked` — an unresolved item in a plan older than 90 days by filename stamp, emitted by the caller **only** under `--include-stale` and only for items the other signals did not already emit.

## Hard rules

1. **Default scope is signals 1 and 2 only.** Signal 3 (staleness) activates only when `--include-stale` is passed. This keeps backlog churn away from plans that are simply old but already complete.

2. **Source field format in `backlog.md`.** When an accepted candidate is written into a project's backlog by the `backlog add` operation, the `Source:` field MUST be formatted as:

   ```
   Source: <plan_rel> — <locator>
   ```

   That is: the relative plan path, a space, an em-dash (`—`, U+2014), a space, then the locator string. Example:

   ```
   Source: plans/2026-05-22-foo-plan.md — Stage 2 / Task 2.3
   ```

   The backlog skill's dedup logic compares this string byte-for-byte. Any variation in spacing, dash character (hyphen vs en-dash vs em-dash), or path format will cause a duplicate entry to be created. The em-dash and single space on each side are mandatory. The legacy locator's 50-character snippet is right-stripped for the same reason.

3. **No LLM in parsing decisions.** Every detection step — header matching, checkbox state, Deferred boundary detection, staleness computation — is pure regex and state machine. The parser must produce deterministic output given identical input files and stage evidence.

4. **Malformed plans are skipped, never aborted.** If a plan file cannot be parsed (e.g. a `### Task N.N:` header with no body before the next heading, a Deferred section with no bullets, a binary file, or a UTF-8 decode error), the caller emits nothing for that file and logs one line:

   ```
   Skipped 1 plan: plans/2026-05-22-broken-plan.md (reason: orphan Task header with no body)
   ```

   The run continues with all other plan files. Skipped-plan counts are aggregated into the final report summary. Nothing in the parser raises an exception that stops the enclosing run.

## Authoritative signal: per-task `Status:`

Plans carry a per-task `- **Status:** [ ]` field that `executing-plans` flips to
`[x]` on green. When a plan has `Status:` fields, they are **authoritative** — no
heuristic, no git archaeology. Implemented by `parse_plan_status()` in
`lib/plan_parser.py`:

- **Detection:** any line matching `^\s*-\s*\*\*Status:\*\*\s*\[[ xX~]\]` puts the
  whole file on the authoritative path. The checkbox is required: a
  checkbox-less field like `- **Status:** Draft` does NOT trigger the
  authoritative path — the file degrades gracefully to the legacy heuristic
  instead of silently losing its candidates. The character class must stay in
  lockstep with `STATUS_RE`'s: with `~` in one and not the other, an all-partial
  plan would match neither, fall to the legacy heuristic, and emit its gate
  bullets instead of its tasks.
- Task with `- **Status:** [x]` → DONE, never a candidate — including any stray
  raw `- [ ]` bullet left in its body (suppressed; Status is the only
  task-state source).
- Task with `- **Status:** [ ]` → unexecuted → exactly ONE candidate per task,
  with `signal: status-unexecuted`, `title` = the task description from its
  `### Task N.N:` header, and locator `Stage N / Task N.N` (or `Task N.N` when no
  enclosing stage is detectable). The task's body bullets are never emitted as
  separate candidates.
- Task with `- **Status:** [~]` → **partial / in flight** → exactly ONE
  candidate per task, identical in shape to the unchecked case but with
  `signal: status-partial`. A partial task counts toward a plan's `total` and
  never toward its `done`: counting it done would let a plan report 100% with
  work outstanding, and dropping it would make the plan look smaller instead of
  less finished. Consumers classify via `status_state()` — testing the captured
  character with `!= " "` reads a partial task as DONE and is never correct.
- **Out-of-contract markers are reported, never guessed.** A marker outside the
  class (`[!]`, `[~ N/A]`, a bare `- **Status:** done`) matches `STATUS_RE` not
  at all, so its task counts toward neither done nor total and the plan reads
  as more finished than it is. `ANY_STATUS_RE` and `STATUS_LINE_RE` exist so
  consumers can take the difference against `STATUS_RE`, and
  `contract_warnings()` reports each such line (see § Contract warnings).
- **Gate checkbox `- [~]` → BLOCKED.** A gate check is a different marker from a
  task `Status:` and carries its own state set — read it with `gate_item_state()`,
  never with `status_state()`. `[ ]` is open, `[x]` done, and `[~]` means **the
  check could not be run in this environment**: not "partly done", not a softer
  `[x]`. The vocabulary is deliberately not shared with a task's `partial`,
  because a task is partial while work proceeds and a gate is blocked because a
  command would not run — the same word would invite the same treatment.
  `honest-gates` makes the split load-bearing (GREEN ran-and-passed / RED
  ran-and-failed / BLOCKED could-not-run); only BLOCKED needs a marker, since a
  RED gate is repaired rather than recorded. **A plan with any `[~]` gate check
  can never classify as completed**, whatever its close-out line says:
  `**Completed:**` is the author's claim about the work, the gate box is the
  record of what was proven, and the second outranks the first.
  `plan_has_blocked_gate()` reads a plan's OWN gate blocks, scoped from a
  `### Stage N Gate` heading to the next `###`, so a Preflight checklist is never
  gate state.
- **`**Blocked-accepted:** <date> — <why>` → the author's answer to a blocked
  gate**, and a terminal marker like `**Completed:**` and `**Abandoned:**`. It
  does not claim the gate ran; it records that someone looked, understood, and
  closed the plan anyway. A plan carrying one is **not** blocked: it classifies
  on its close-out line again. Without it the `[~]` rule would be correct and
  unliveable: `**Completed:**` would no longer retire such a plan,
  `**Abandoned:**` would be untrue, and editing the `[~]` to `[x]` would falsify
  the record the convention exists to keep. It would penalise hardest the plans
  that used `[~]` most honestly, which is how a convention dies. The marker is
  read only at column 0.
- **A master inherits its sub-plans' blocked state.** A master plan carries no
  `### Stage N Gate` section of its own — its gate boxes live in its sub-plan
  files — so reading only its own text could never find its blockage.
  `plan_blocked(text, path)` resolves each `- **Plan:** <path>` link against the
  master's own directory and is blocked when any linked sub-plan is. Acceptance
  propagates upward the same way: a master whose sub-plans are all accepted is
  not blocked, and a master's own acceptance closes it whatever its sub-plans
  say. An unresolvable link is not evidence of blockage, and the function never
  raises on one. Each link is read through `read_capped()`: a regular file of at
  most `PLAN_READ_CAP` (1 MiB) bytes, opened without blocking, so a link to a FIFO
  or a runaway file is not blockage either. The two are the only functions in the
  library that read files.
- **Consumers call `plan_blocked()`, never `plan_has_blocked_gate()` directly.**
  The raw predicate answers "does this file contain a `[~]` box", which is a
  different question — it misses a master and ignores acceptance — and
  consumers that each asked it would disagree about the same plan.
- Raw unchecked bullets outside task bodies (gates, ad-hoc checklists) are
  likewise ignored — in authoritative mode the ONLY candidate sources are
  `Status: [ ]` / `[~]` fields and Deferred blocks.
- **Deferred sections remain active in both modes.** They are an explicit
  parking register, not a task-state heuristic; their bullets surface with
  `signal: deferred-section` exactly as in legacy plans.
- **Git stage evidence is not consulted** on the authoritative path
  (`done_stages` applies only to the legacy heuristic).
- A `- **Status:**` field without a preceding `### Task N.N:` header in its
  section (e.g. a master plan's `### Sub-plan N:` register entries) has no task
  context and emits nothing.
- A plan with a `**Completed:** <date>` close-out line and all `[x]` is fully
  done (and, by the rules in this section, yields zero task candidates).
  `COMPLETED_RE` reads that line at line start, in both the bold form and the
  `## Completed:` heading form; a `Completed:` mid-sentence is prose.

### Abandonment: `**Abandoned:**` (terminal state, parsed — not prose)

A plan that will never be finished carries a column-0 marker mirroring the
`**Completed:**` close-out line:

```
**Abandoned:** YYYY-MM-DD — <reason>
```

Parsed by `plan_terminal_state()`, which returns `(abandoned, advisory, reason)`. Rules:

- The **marker is the only authoritative signal**, and it affects **ranking
  only**: an abandoned plan is never recommended as next work, but stays
  visible in a full listing and still yields its open-task candidates for human
  triage in `unify`. Suppressing those would let a one-line marker silently
  delete work from the only view that still lists it. `parse_plan()` therefore
  never calls `plan_terminal_state()`.
- **Prose banners are advisory, never authoritative.** Text like
  `OBSOLETE — DO NOT IMPLEMENT` is detected and surfaced as a note ("looks
  abandoned … not suppressed") so the author can add the real marker, but it
  never suppresses anything. A deterministic parser must not treat unbounded
  natural language as a gate: a false positive there hides live work, which is
  a worse and quieter failure than the missing suppression it would fix.

The heuristic § Input signals (unchecked `[ ]` bullets, git-stage evidence)
remain the fallback for **legacy plans** that carry no `Status:` field.

### Contract warnings

Authors write a marker several ways; the parser accepts one. The parser stays
strict, and `contract_warnings(text, path)` reports each line it cannot read, as
`(code, line_no, excerpt)`. Widening the regexes instead would trade a rare miss
for a routine false read in the optimistic direction: an indented
`**Blocked-accepted:**` accepted everywhere would also let one inside a quoted
example close a plan, and accepting more close-out spellings would also match
prose that merely mentions them.

The warnings are a difference against the authoritative regexes, never a list
of known-bad spellings, so a form nobody predicted is still caught:

- `STATUS-OUT-OF-CONTRACT` — a Status line `STATUS_RE` does not read.
- `ACCEPTANCE-INDENTED` — a `**Blocked-accepted:**` not at column 0.
- `CLOSE-OUT-DIALECT` — a line presenting itself as a close-out (`**Completed (…):**`,
  `**Close-out (YYYY-MM-DD):**`) that `COMPLETED_RE` does not read. A bare
  `**Close-out …:**` section label is not one: labelling a section is not claiming
  the plan is finished.
- `REGISTER-DIALECT` — in a master, a bare-ordinal heading (`### 01. Foundation`)
  that `SUBPLAN_RE` does not read, so the master would count 0/0.
- `MARKER-IN-FENCE` — a marker inside a ``` fence. No parser is fence-aware, so a
  literal example parses as real; the warning says so instead of teaching every
  regex about fences.

## Master plans

Large projects decompose into one **master plan** plus 2–7 **sub-plans** in the same
`plans/` directory (format: `master-plan-format.md` in this folder).
Parsing rules:

- **Detection:** `is_master_plan(text, path)` — the filename ends in
  `-master-plan.md`, OR the first heading is `# Master Plan:`. Either alone suffices.
- **Register entries are pointers, never candidates.** A master's `### Sub-plan N:`
  sections are links to sub-plan files, not tasks. They MUST NOT be emitted as backlog
  candidates — the sub-plan's own tasks are the sole candidate source. Emitting both
  would double-count every piece of work. `SUBPLAN_RE` reads a register heading
  (bare or zero-padded number, colon or dash: `### Sub-plan 01 — maintenance lane`).
- **Links, one per direction:** `SUBPLAN_LINK_RE` reads a register's
  `- **Plan:** ./<sub-plan>.md`, and `MASTER_BACKLINK_RE` reads a sub-plan's
  `Master: ./<master>.md` line. `link_target()` normalises both the bare path and the
  `[name.md](./name.md)` form to one relative path, and returns `None` rather than a
  guess, so an unresolvable link leaves a sub-plan ungrouped, never grouped under the
  wrong master.
- **Register `- **Status:** [x]` is authoritative for sub-plan done-ness at master
  level** (it mirrors the sub-plan's `**Completed:**` close-out line, which remains
  authoritative inside the sub-plan itself).
- **Master `**Gate:**` bullets are excluded** exactly like stage-gate bullets — they are
  integration checks, not deferred work.
- **Sub-plan files parse as normal plans** (they are standard planning-projects plans
  with a `Master:` backlink below `Date:`); all existing signals apply to them
  unchanged.
- A master plan with a `**Completed:** <date> — sub-plans: <list>` close-out line and
  all register entries `[x]` is fully done.

**Format guarantee (parser safety, locked by `core/lib/tests/test-plan-parser.py`):** a
master plan yields **zero** candidates without master-specific code, on both paths. Its
register `- **Status:**` fields put it on the authoritative path, where its lack of
`### Task N.N:` headers means no task context and no candidates; and even under the
legacy heuristic it contains no raw `- [ ]` bullets outside `**Gate:**` blocks. The
rules above are therefore a documented invariant of the format, and the suite is the
regression guard that keeps parser and format in lockstep.

## Architecture docs

`*-architecture.md` files land in the same `plans/` directory and are scanned like
any other file — there is no filename-based exclusion for them in `parse_plan()`.
Their safety is **by construction**, exactly like master plans: the
architecting-projects Document format forbids raw `- [ ]` bullets and
`- **Status:**` fields, so the doc emits nothing on either parse path (no Status
field → legacy heuristic → no unchecked bullets to match; lists are plain `-`
bullets, which only surface inside Deferred sections that the format doesn't use).

**Format guarantee (locked by `core/lib/tests/test-plan-parser.py`):** a sample
architecture doc with ARCH-NN sections, plain-bullet lists, and a fenced directory
tree yields **zero** candidates, and its mutation twin (one smuggled `- [ ]`) yields
exactly one, proving the invariant is falsifiable.

Status-counting consumers that must not count non-plans use `is_not_a_plan(path)`:
the `-design.md`, `-architecture.md` and `-done.md` suffixes, anchored on the hyphen
so a plan with `design` inside its name (`…-gui-redesign-plan.md`) is still a plan.

## Light plans

A **Light plan** (`*-light-plan.md`, format: `light-plan-format.md` in this folder) is
the smallest staged artifact the pipeline produces: one `## Stage 1:` of 2–5
`### Task 1.N:` tasks, each carrying a `- **Status:** [ ]` field, plus one
`### Stage 1 Gate`. It drops the long-horizon fields (Preflight section,
Risk/Rollback, Blocks/Parallel) but keeps the three line shapes the parser keys on.

- **Detection:** `is_light_plan(text, path)` — the `-light-plan.md` suffix or the
  `# Light Plan:` first heading, the same two signals as master detection. The
  candidate parser never needs it: a Light plan is just a Status-field plan, so any
  line matching the `Status:` checkbox regex puts it on the **authoritative path**
  (`parse_plan_status`) exactly like a Standard plan or a sub-plan. `executing-plans`
  and the format checks are the consumers that ask.
- **In progress:** exactly one `status-unexecuted` candidate per `- **Status:** [ ]`
  task (title = the `### Task 1.N:` description, locator = `Stage 1 / Task 1.N`); its
  `### Stage 1 Gate` bullets are excluded like any gate, a stray `- [ ]` left in a done
  task's body is suppressed, and any `## Deferred` bullets surface as `deferred-section`.
- **Completed:** a Light plan with a `**Completed:** <date>` close-out line and all
  `[x]` tasks yields **zero** candidates — identical to a completed Standard plan.

**Format guarantee (locked by `core/lib/tests/test-plan-parser.py`):** an in-progress
Light fixture (mixed statuses, a gate, a stray bullet in a done task, a Deferred
bullet) yields exactly one candidate per undone task plus its Deferred bullet, and a
completed one yields zero — so the Light format is parser-safe **by construction,
with no parser code**.
