# Task and stage field specs

The per-field rules a plan's tasks carry. `planning-projects` Phase 2 sets the
structure; this is the reference for each field's exact semantics.

### `Review:` — an authored field, never an executor's

**What the plan's declared review tier already decides, this field does not.**
`executing-plans` scales its review machinery to the plan's cumulative diff
(`../../executing-plans/references/review-scope.md`): at `none`, `light` and `standard`
there is **no per-task review at all**, and at `high` each risk-listed task gets one. So the common
case needs no annotation in either direction — the tier has already answered.

The field exists for the two exceptions, and it takes two values:

| Value | Means | Use when |
|---|---|---|
| `Review: skip` | do not review this task even though the tier would | the tier is `high` and this one task is non-code or throwaway |
| `Review: required` | review this task even though the tier would not | the plan is `light`/`standard` overall but *this* task's `Scope:` names a risk-listed path |

`Review: required` is what keeps a single dangerous task from dragging a whole plan up a
tier — the cheaper and more honest move than declaring `high` for nine tasks because one
of them touches auth.

**Grant it by path, never by word.** Mark `Review: required` only on a task whose `Scope:`
names a risk-listed path: the function that checks a credential, the statement that drops
or migrates a table, the signature a downstream caller binds to. The list and its reading
are in `../../executing-plans/references/review-scope.md` § Risk-listed names a path. A
task whose text mentions identity, permission or protocol, and whose diff
touches no such path, does not get it: the stage's Tier-2 pass reads that diff anyway.
Granted by those words, the field landed on 8 of 17 tasks in one master plan
(one owner's run, 2026-10-26), and each bought a review and a re-review that Tier-2 repeated.

**Both values are the user's to author, never the executor's.** The field exists in this
template precisely so the annotation has a provenance: it lands in the plan the user reads
and approves, before execution starts. Do not add `skip` on your own judgment that a task
looks trivial — `executing-plans` already auto-skips genuinely non-code diffs (docs-only,
config-only, pure version bumps) without any annotation, so the field is not needed for
that case. An executor that adds it mid-run is recording its own decision as the user's,
which is why `executing-plans` snapshots these annotations at Preflight and honors only
the ones present at the run's base commit (`../../executing-plans/SKILL.md` § Dispatch
roster and capability probe, and `../../executing-plans/references/integration.md` § Review opt-out).

Omit the field entirely on every task the user did not name. An absent field means "let
the tier decide", which is the right answer for almost every task; `Review: run` is not a
thing.

### `Test:` — the outcome, and a way to go red

A `Test:` is only evidence if it would fail when its claim is false. Two ways a test that
runs and passes still proves nothing:

**It asserts a side effect instead of the outcome.** Suppose a task is planned with "a report
with a chart renders with `CHART_SCRATCH` pointed at a test dir and leaves no file in the
default scratch dir". If the renderer deletes its scratch files as soon as it is done, "no file
left in the default scratch dir" is true whatever `CHART_SCRATCH` says. Worse, if a wrong
scratch folder makes the renderer skip the chart *silently* — leaving an empty frame in its
place and still reporting success — the test passes with `CHART_SCRATCH` unset and with
`CHART_SCRATCH` pointing at a folder that does not exist, while the defect it exists to catch
— a report shipped without its chart — stays possible. The outcome is "the chart is in the
report"; the test renders a known data series and asserts the report holds its chart.

So write each claim as the property a user would care about, and when it is not obvious how
the claim could fail, say so in the field: `— page 2 holds the sales chart (red if
CHART_SCRATCH is unset)`. That clause is what an executor breaks to prove the test can fail; without it
they break whatever is easiest, and the claim the task exists for is never tried.

**One command, before the first ` — `, covers every claim.** An executor runs only the
commands written before the field's first ` — `. Everything after it is read as claims.
Suppose a field reads "`python3 tests/test_x.py` — it parses; the doc says so:
`grep -q 'parses' docs/x.md`". The grep comes after the dash, so nothing runs it, and that
claim cannot be proven. Chain a claim's own command into the one before the dash with `&&`:
"`python3 tests/test_x.py && grep -q 'parses' docs/x.md` — it parses; the doc says so".
`validate-gate-checks.py` notes a field with a command after the dash
(TEST-COMMAND-AFTER-DASH, advisory).

**It never checks what the task was for.** A task that exists to prepare something for later
tasks — a scaffold that owns the build file so parallel siblings need not touch it — is done
when that preparation is there, not when the build passes. Suppose a scaffold's `Test:` is
"`npm run build` succeeds": it goes green without the test runner the next stage's parallel
tasks need, and both siblings then have to edit the one file the task exists to keep them
out of. Its `Test:` checks the content instead:
`grep -q '"vitest"' package.json`.

**It leaves a closed set's pins behind.** A task that adds a member to a closed set (an enum,
an event list, a migration count, a snapshot baseline) updates every test that pins that set,
in the same task. Otherwise the pin goes red at the next full run, far from the task that broke
it. Measured on 2026-10-25, this was the most common reason a plan's first full pass failed,
and no scoped run can see it.

### Scope marking (the set a task changes)

A task that changes a **class** of artifact declares the set it must sweep, on a `Scope:`
field:

```
Scope: every commands/*.md, each skills/*/SKILL.md, both scripts' --help
```

This is the authoring-time half of the class-predicate rule. The gate check proves the set
was swept; `Scope:` is where the set gets **named**, before anyone starts editing — so the
surfaces are enumerated once rather than discovered one gate round at a time.

**Conditional, not universal.** Declare it only when the task changes more than one
artifact. A task editing exactly one file has no set, and writing `Scope: this file`
everywhere is noise that trains readers to skip the field. No `Scope:` on a
single-artifact task is correct, not missing — except on a `Dispatch: YES` task, which always
carries one: it is how `validate-dispatch.py` proves no YES sibling edits the same file.

**Derive the set with a command; do not type it from memory.** This is the failure mode
worth naming, because it is not carelessness and it survives careful authors:

> Suppose a plan enumerates "every page documenting the retry settings" as three files,
> from a `find` listing that `| sed 3q` cut short, and a fourth page exists. The task
> covers three; only the stage gate's set-valued check finds the fourth. A `Scope:` line
> is only as trustworthy as the sweep behind it — paste the command you ran, not the
> answer you remember.

So: run the sweep, and prefer a `Scope:` that names the **command** (`Scope: every file
matching grep -rl 'X' src/ — 7 files at authoring time`) over one that names a
hand-copied list. A count is useful precisely because it is falsifiable later.

**There is an automated backstop.** `../scripts/validate-gate-checks.py` reports a stage that
declares a `Scope:` whose gate contains neither an executable sweep nor a `(judgment)`
marker — the set named but not swept. It is advisory (it never changes an exit code), so
treat it as a reminder, not a gate.

**Masters carry no `Scope:`.** A master plan has no tasks (`master-plan-format.md`),
so the field never appears there and its parser-safety invariant is untouched.

### Dependency marking

Every task and stage carries two dependency fields — this makes the graph navigable in both directions:

- **Depends on**: What must be green before this task/stage can start
- **Blocks**: What is waiting on this task/stage to finish

These fields are symmetric: if Task 2.1 depends on Task 1.3, then Task 1.3 must list Task 2.1 in its Blocks field. This redundancy is intentional — when a task finishes, you can immediately see what it unblocks without scanning the entire plan.

Mark each task's **Dispatch** field. It is a directive to the executor, not a description
of the task: `executing-plans` dispatches every `Dispatch: YES` task to a subagent (its
Step 3.2), it does not merely note that a subagent *could* handle it. The authority for
what the field MEANS is `../SKILL.md` § Stage structure, where it is defined; this section
is the authoring rule built on it.

The retired spelling of this field is `Parallel:`; parsers accept both.

> **Where else this rule is stated, and why that is not duplication.** The
> directive-not-description distinction reads as repeated prose across the repo, and a
> count of the sites taken against a narrower reading of the class than an entry uses
> comes out wrong and can close that entry wrongly. The class is therefore stated here
> rather than left to be re-counted. A site belongs to it when
> it restates the distinction as the **premise for a consequence that site alone draws**,
> and cites `../SKILL.md` § Stage structure. Every current site does:
>
> | Where | The consequence it draws |
> |---|---|
> | `../SKILL.md` § Stage structure | the definition itself — the authority |
> | `../SKILL.md`, load-bearing rules list | trunk summary of its own definition |
> | here | how to mark the field when authoring |
> | `../../executing-plans/references/dispatch-fidelity.md` | an ignored directive leaves no trace in the diff, so nothing later reveals it |
> | `../../executing-plans/references/task-execution.md` | a sibling touching the same file does not withdraw the directive |
> | `../../dispatching-parallel-agents/SKILL.md` | approval came with the plan, so do not re-confirm; and `|S| = 1` still dispatches |
>
> Six sites, six different consequences. What would NOT belong: a seventh site restating
> the distinction and drawing nothing new from it, or one that states it without citing
> the authority. Either is a duplicate to delete rather than a cross-reference to keep.
- **YES** if the task has no unfinished dependencies (all its `Depends on` items are green
  or "none") — it is dispatched, whether or not another ready task exists to run alongside
  it. A lone ready task with no concurrent sibling is still dispatched, not inlined for
  lack of one.
**A file conflict is expressed as a dependency, never as a downgraded `Dispatch` field.**
Two dependency-free tasks that touch the same file cannot both be `YES` (the checklist
forbids two parallel tasks modifying one file), but neither is `NO` in the field's own
terms, because `NO` means *blocked by a dependency* and there is none. Resolve it where it
belongs: add an explicit `Depends on` edge serialising the two at authoring time, then the
second task is `NO` for the ordinary reason. Downgrading the field instead would reintroduce
exactly the reading this section removes — that `Dispatch` describes whether things happen
to run side by side, rather than instructing the executor to dispatch.

- **NO** if it's blocked — list which dependency is blocking it. (Once unblocked, `NO`
  runs in the main session — there is no executor discretion to delegate it — that
  outcome doesn't depend on having a concurrent sibling either.)

### Names other tasks rely on

When a later task, a gate check or a rollback note names something — a path, a directory, an
API's behaviour — the task that **creates** it must name it too. Otherwise execution picks a
name of its own, and the plan's downstream references break where nobody is looking.

Suppose a plan says only that a task's `setup` points the service at "per-user dirs",
while a later gate reads `var/cache/<svc>/index.db` and the rollback deletes
`var/spool/…`. An executor that chooses `var/tmp` and `var/queue` is reasonable, and wrong
for both. Likewise a settings writer that drops unknown YAML keys breaks a later task whose
`Test:` requires them to survive a save. Neither mismatch shows until the later stage runs.

So when a downstream line names it, write it into the creating task:
"`setup` sets `CACHE_ROOT` to `var/cache`"; "`save_settings` keeps keys it does not
model". Sweep for it while authoring: every backticked path in a gate or rollback
should appear in the task that produces it.

### Ordering rules

1. **Stages are sequential.** Stage 2 does not start until Stage 1's gate passes
2. **Tasks within a stage follow their dependency graph.** If Task B needs output from Task A, Task A comes first — this isn't optional, it's structural
3. **Independent tasks are dispatched, and run in parallel.** If Tasks 2.3 and 2.4 have no dependency on each other and touch no common file, both are dispatched and run simultaneously — and if only Task 2.3 is ready, it is dispatched by itself. "Can" describes the schedule, not the obligation: whether they overlap in time is a scheduling consequence, whereas dispatching each to a subagent is the instruction their `Dispatch: YES` carries
4. A task cannot enter its Red-Green loop until every task it depends on is green

### Risk flags

Mark each stage with a risk level. This tells the user (and you) where to expect friction:

- **LOW**: Well-understood tech, clear path, prior art exists in the codebase
- **MEDIUM**: Some unknowns — unfamiliar API, complex integration point, limited docs
- **HIGH**: Novel territory, unreliable external dependencies, tight constraints, or no prior art

High-risk stages deserve extra care: consider a spike or prototype first, prepare the rollback plan in detail, and expect the Red-Green loop to cycle more than once per task.

### Rollback notes

Each stage documents what to undo if it fails beyond recovery. Half-built states with no way back are worse than not starting:

- Which files or changes to revert (`git` refs if applicable)
- Which migrations or schema changes to roll back
- Which services or infrastructure to restore to prior state
- Which side effects (messages sent, data written) cannot be undone — flag these explicitly
