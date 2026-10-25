# planning

An eleven-skill pipeline (v1.0.0) that turns a vague idea into executed work — including redesigning an app to a Claude Design handoff — and keeps each project's contracts and records honest. Each skill hands off to the next; they were designed as a unit.

This is the **Cursor** build. Beside the eleven skills it ships two Cursor-only skills, `hooks` and `plan-statusline`, four agents, and the plugin's hooks (`hooks/hooks.json`). Skills are invoked by their bare names (`/executing-plans`, `/backlog`, …); Cursor does not trigger a skill reliably from prose, so name the one you want.

## Highlights

- **A plan's goal is a gate check from the first gate.** Every Standard plan, Light plan and master register entry carries at least one gate check marked `(goal)`: the plan's goal as one cheap sweep over the whole artifact it is about, never a subset by category, in every gate from the first one whose artifact exists (`planning-projects/references/gate-authoring.md` § The plan's goal is a check from the first gate). The gate evaluator is briefed with the plan goal as well as the stage goal, so a stage whose output already falls short of the plan goal, with no later stage planned to change it, is a Blocking finding.
- **Advisory validator notes carry a measured trigger rate.** `validate-gate-checks.py` reports `GOAL-CHECK-MISSING` when a plan, or a master entry, has no `(goal)` check, and `FILTERED-SUBSET` when a sweep is restricted by a category filter, such as an awk field match or a grep narrowing what `git ls-files`, `find` or `ls` printed; `(scoped)` answers it. Both are advisory because most hits are legitimate: measured 2026-10-08 over 800 plans in one owner's records homes, `FILTERED-SUBSET` fired 13 times and 1 was a true positive. Every gate heuristic ships with a severity and such a rate.
- **Proof by tool.** A task's mutation proof is a record written by a tool, not a sentence in the commit. `prove-claim.py` (`skills/executing-plans/scripts/`) writes `proof/<plan>/<task>/claim-K.json` only after it watched the plan's own `Test:` pass, fail under your break, and the tree come back exactly. Self-reported breaks are not enough: of 26 self-reported mutants in 11 task commits (one owner's commits, undated), re-run by performing each stated break, 1 was caught by no test at all (a small sample — roughly 0.1–20% false at 95%). On Cursor the proof is made once per stage, at the gate, by one `claim-verifier` dispatch over the final staged tree; `plan-flip-audit.py --repo` checks the records at every stage gate, and a commit gate, on by default, refuses a `Stage N green` commit without them — see [Hooks](#hooks).
- **A claimed review is checked against the dispatches.** `hooks/dispatch-log.sh` logs every subagent launch (Cursor's `Task` tool) while a plan is in flight, and `review-ledger-check.py` fails a gate whose `review:` or `evaluator:` line claims a dispatch the log does not hold. No log is NOT RUN, never green.
- **Handoffs on a stated rule, never by eye.** A run stops for a fresh session only at a gate, on a stop rule with a `reason:` line, and writes a `RESUME HERE` block a new session resumes from. On Cursor nothing measures the context a session uses (no store Cursor writes records it), so the measuring script does not ship and only a dated external wait hands off; supervised handoff is not carried either.
- **Dispatch is checked, not trusted.** `Dispatch: YES` means the task must go to a sub-agent. `validate-dispatch.py` fails a plan whose dispatch fields are wrong, before the plan is presented and again at Preflight. `plan-progress.py --dispatch-check` makes roster reconciliation a close-out gate, and `--stage-order-check` stops a stage from opening before the gate it depends on.
- **Bounded verification cost.** On a plan that declares test-scope commands, a task's `Test:` runs under a 300 s budget (a Preflight `task-test budget: N s` line overrides it); going over is a Stop, and the test is never narrowed to fit. Before a remediation round re-runs a live or device-bound check, the fix is proven against every real capture and recorded as a `fixture-sweep:` commit trailer.
- **Planning-authoring rules.** A `Test:` asserts the outcome, and each claim could go red. A sweep that forbids a call matches the bare name. A name a later task, gate or rollback uses is fixed by the task that creates it. Tool checks look where the build looks. No task re-does execution's Preflight.

## Installation

There is no `/plugin install` command for a local Cursor plugin. Sync the built plugin into
Cursor's local plugins folder (`--delete` drops files a newer build no longer ships; a plain
`cp -r` onto an existing folder would nest a second copy inside it) and reload:

```bash
rsync -a --delete plugins/cursor/planning/ ~/.cursor/plugins/local/planning/
```

Then **Reload Window** (or start a new `cursor-agent` session) so Cursor picks up the skills,
agents and hooks, and run the `hooks` skill (`/hooks`) in each project you plan in: it checks
that the hooks are wired and installs the proof-record git hook, without which the commit
gate denies git while a plan is in flight.
Every hook is on the plugin route (`hooks/hooks.json`); nothing is written into
`~/.cursor/hooks.json`, because an event wired on both routes runs twice.

If the Claude Code build of this plugin is also installed, Cursor runs its hooks too; each of
them exits quietly on a Cursor payload, so only this build's hooks answer under Cursor.

Cursor also reads skills from `~/.agents/skills`, `~/.claude/skills` and the Claude Code
plugin cache. With one skill name in all four places, Cursor served the `~/.agents/skills`
copy (measured), so a same-named skill there replaces this plugin's. Which of the Claude
Code cache copy and this plugin's copy Cursor serves, with no `~/.agents/skills` copy, is
not measured.

## The pipeline

```
vague idea
    │
    ▼
brainstorming           ── validate the design via Q&A: purpose, constraints,
    │                      alternatives, risks. One question at a time.
    ▼
architecting-projects   ── (designs with a structural surface) research 2–4
    │                      architecture candidates via parallel researcher
    │                      agents, user approves one, write the ARCH-ID doc.
    ▼
planning-projects       ── triage a format first (Direct / Light / Standard /
    │                      Master), then stage the work: tasks with Depends on /
    │                      Blocks / Dispatch fields, Red-Green cycles, gates.
    ▼
executing-plans         ── drive the plan: Red-Green loops, tiered test-scope
    │                      gates, fan independent tasks out for parallel run.
    ▼
dispatching-parallel-agents  ── one agent per task marked Dispatch YES whose
                               dependencies are all green; integrate results
                               respecting the dependency graph.

  ┌─ cross-cutting, no fixed position in the flow ────────────────────────┐
  │ honest-gates       ── the integrity contract every gate above obeys.  │
  └───────────────────────────────────────────────────────────────────────┘
```

## Skills

### `brainstorming`

Use **before** any non-trivial creative or implementation work — new features, refactors, migrations, behavior changes. Turns a vague idea into a validated design by exploring purpose, constraints, alternatives, and risks one question at a time. Terminal handoff is to `architecting-projects` (designs with a structural surface) or straight to `planning-projects`.

**Triggers:** "I'm thinking about adding X", "what's the best way to", "should I refactor", "design a new", "let's brainstorm".

### `architecting-projects`

Use after a design is validated (or on a direct architecture request) to produce a researched, user-approved architecture document that `planning-projects` consumes. Derives 2–4 stack-concrete candidates, fans out one `architecture-researcher` agent per candidate in parallel (uncited claims are discarded), presents a comparison matrix for explicit approval, then writes a parser-safe `*-architecture.md` with stable `ARCH-NN` section IDs beside the plan. Plans cite the ARCH-IDs on structure-creating tasks and carry an architecture-conformance check in their final stage gate. On existing codebases, **re-architecture mode** inventories the current module map, requires each candidate's research to address the migration explicitly, and adds an `ARCH-NN Migration map` section whose ordered, build-green steps seed the plan's stage order.

**Triggers:** "design the architecture", "architecture options", "how should the codebase be structured", "compare architecture candidates", "pick an architecture".

### `planning-projects`

Produces a staged plan for a non-trivial project with phase gates before execution. Plans use a strict format with Stages, Tasks, `Depends on` / `Blocks` / `Dispatch` fields, Red-Green max cycles, and Stage gates that `executing-plans` can drive mechanically.

**Format ladder.** Every request is triaged to a format *first*, so the apparatus scales to the size of the job — and a trivial request may be declined a plan file entirely:

| Format | Shape | Use when |
|---|---|---|
| **Direct** | no plan file — just do it | the job is trivial and self-evident |
| **Light** | one stage, 2–5 tasks, one gate (`*-light-plan.md`) | small but worth a test-and-gate backbone |
| **Standard** | multiple stages, full task fields, per-stage gates | the default for non-trivial work |
| **Master** | 2–7 sub-plans linked by a register (`*-master-plan.md`) | >~6 stages / >~25 tasks, or several independently shippable workstreams |

The Light and Master formats are specified in `skills/planning-projects/references/light-plan-format.md` and `master-plan-format.md`; both are parser-safe by construction (zero backlog unify candidates, locked by the plan-parser fixture suite, `core/lib/tests/test-plan-parser.py`).

For big projects (roughly >6 stages / >25 tasks, or multiple independently shippable workstreams) it **decomposes** the work into 2–7 independently executable **sub-plans** linked by one **master plan**: the master holds the shared research, a sub-plan register (Status / plan link / Goal / cross-plan `Depends on`+`Blocks` / `Parallel`), and a `**Gate:**` block of integration checks per entry. The canonical format lives in `skills/planning-projects/references/master-plan-format.md` and is parser-safe by construction — a master plan yields zero backlog candidates in backlog unify (locked by the same fixture suite); the sub-plans carry the real tasks.

**Triggers:** "plan", "roadmap", "how should I build", "break this down", "what are the steps", "create a plan", "what order should I do this".

### `executing-plans`

Takes a plan file produced by `planning-projects` and executes it. The skill is a **trunk plus references**: what fires on every run stays in `SKILL.md`, while the master-plan and light-plan execution models, the review-scope and opt-out rules, the dispatch-fidelity rationale, the gate-failure procedure, the progress-state schema and the sources load from `skills/executing-plans/references/` only when their condition is met. `planning-projects` is split the same way (plan template, task-field specs, set-valued-check rules). Drives Red-Green loops, respects the stage-gate model, and dispatches independent tasks through `dispatching-parallel-agents` — **without a confirmation turn, because approving the plan was the request** (a standing caution against calling the Task tool is conditional, not absolute; with no plan in play it still applies and you still ask). **A bug found anywhere during a run is treated as a defect class**: diagnose, name the set, enumerate it with a command, and fix every member — the whole project is the search space, not the plan's blast radius, and the sweep costs a command rather than a dispatch, so no review tier gates it. It executes every rung of the format ladder — a **light plan** runs with proportionate machinery (Preflight-lite, inline no-parallel execution, one whole-diff review instead of per-task Tier-1, a single stated version bump; whether an evaluator runs beside that review comes from the review tier, not the format — see the composition rule below). Also executes **master plans** (`*-master-plan.md`): sub-plans run in register dependency order, each via the normal single-plan flow (on Cursor they continue in one session unless a dated wait hands off; the master file is the cross-session handoff artifact, so you can start a fresh session at any `"Sub-plan N green"` commit); each sub-plan completion flips its register `Status`, runs that entry's cross-plan `**Gate:**` checks, and commits `"Sub-plan N green"`; version bumps are deferred from sub-plan close-outs to the single master close-out.

Preflight includes a **git bootstrap** — if the project isn't a repo it runs `git init` (and offers a GitHub remote) so the per-task commits have somewhere to land. Execution **runs to completion**: stage gates are checkpoints, not approval gates, so it doesn't pause between green stages to ask permission — only the documented stop conditions halt it. At each stage gate it invokes a matching **platform stage-verify skill**, if one is installed whose description matches the project type (e.g. an Android build-and-smoke-test skill: build the debug APK, and if an adb device is attached, install + smoke-launch + run instrumented tests). At close-out it **bumps versions** for whatever the plan changed, across every mirror of the version string (e.g. a plugin's `.cursor-plugin/plugin.json` and the root marketplace entry).

**Test-first Red-Green.** The task's test is written and run **before** the implementation, and must go RED for the reason the task names. A RED that means something else is a defective test, diagnosed as such on the spot rather than debugged against code the executor already believes correct — and repairing it doesn't spend the `Red-Green max cycles` budget, which bounds failed hypotheses about the product. Where the task's `Test:` names a `-k` selector, that selector is a naming constraint applied as the test is written, not a rename discovered after it passes.

**Tiered test-scope gates.** Gates run the tests their tier warrants rather than the whole suite every time — cheap host-side checks always run in full, expensive suites (device / instrumented / e2e) are scoped:

- **task-scope** — inside a task: the task's own `Test:` and nothing wider. The `stage-scope:` command never runs "for Task 2.3" — a break in a sibling module surfaces at the stage gate, which is the one place that sweep is scheduled.
- **fix-scope** — after a review fix inside a Red-Green cycle: the task's own `Test:` plus the test classes the fix touched.
- **stage-scope** — at an intermediate stage gate, **once per gate entry**: restricted to the modules the stage's commits touched, never `clean`.
- **plan-scope** — exactly one clean full pass, at close-out (the final stage's gate runs at this tier).

A scoped gate report always discloses what actually ran. Policy lives in `skills/planning-projects/references/test-scope-tiers.md`, shared with `planning-projects`.

**Tiered verification scope.** The same idea applied to the *verification* machinery, so its weight follows what it reviews. The plan declares a tier at Preflight from its cumulative diff and repeats it in every gate report, so a downgrade is on the record rather than silent:

| Tier | When | What runs |
|---|---|---|
| **none** | docs / config / version-bump / comment-only | the plan's own tests and gate checks, nothing else |
| **light** | no new executable behavior, **or** under ~200 changed lines across ≤ ~5 files, and nothing risk-listed | + **one** whole-plan-diff review, at close-out |
| **standard** | multi-file code with new behavior — the default, and what an undeclared run gets | + one Tier-2 review per stage gate; an evaluator only at gates carrying a `(judgment)` check or whose stage has Outcomes (there it demos them as their user), plus a close-out evaluator when the final gate carries one or any stage has Outcomes |
| **high** | security / auth, data-destructive, public API, schema / migration | the full apparatus: per-task Tier-1, per-gate Tier-2 + evaluator, a second independent close-out pass |

**What the tier gates** is every mandate that costs an agent dispatch: both review tiers, the gate and close-out evaluators, the Preflight dispatch probe, and the design-fidelity verify loop's evaluator. What it never gates is the cheap-but-load-bearing half — the dispatch roster, the executor trailer, the dispatch reconciliation, honest-gates disclosure, the class sweep run on any bug found during execution, and the plan's own tests. Concretely, counting **verification** dispatches only — the plan's own `Dispatch: YES` task dispatches are execution, not verification, and are never tiered — a Standard 3-stage / 9-task plan whose gates each carry a `(judgment)` check costs **7** at `standard` (3 Tier-2, 3 gate evaluators, 1 probe; 8 if its close-out evaluator is a separate dispatch, 4 if its gates are all executable sweeps). Running every mandate on the same plan would cost **17** (9 Tier-1, 3 Tier-2, 3 gate evaluators, 1 close-out, 1 probe) before any re-dispatch after a fix — and an unbounded re-dispatch is the larger cost the tiers remove.

The `light` bar is a size the diff can be measured against, with escalation carried by the risk list. A criterion nothing can satisfy is a dead branch, not a conservative default: a bar of **a single file** excludes any real multi-file plan, and one that turns on a judgment ("new executable behavior") is resolved upward every time by an executor told never to take the lighter option.

**Escalation is by risk, not by size.** The format ladder and the review tier answer different questions and a plan carries both, so: **the format decides the review's shape** (Direct/Light → one whole-diff pass; Standard/Master → per stage gate), **the tier decides its depth** (how many passes, and whether an independent evaluator runs). Ambiguity resolves by the **risk floor**: touching a risk-listed area sets `high` whatever the size, and size alone never escalates — a large prose or mechanical-rename diff is a big `light` change, not a `standard` one. A blanket "never take the lighter option" rule is right for the dangerous case (a Light plan touching auth still gets whole-diff shape *and* `high`'s depth) and wrong for every other: it makes small prose plans pay `standard` for no protection. Master plans declare a tier per sub-plan, and the master's own close-out takes the highest any sub-plan declared.

**Two-tier code review.** Execution wires in the bundled read-only `code-reviewer` agent on a distinct axis from the goal-evaluator (*code quality* vs *goal attainment*). **Tier 1** reads one green task's diff before its commit, where a Critical blocks the task and is fixed within the same Red-Green cycle budget — it runs **only at `high`**, or on a task the plan annotated `Review: required`. **Tier 2** is the deep pass: one review over the whole plan diff at `light`, one per stage gate at `standard` and `high`, where a Critical is a gate failure and every Important leaves the gate **fixed** — the backlog is not a disposition for a defect. Trivial/non-code diffs are auto-skipped at either tier. Unconditional per-task review would make a nine-task plan pay nine review dispatches plus a re-dispatch after every fix; Tier 2 still reads every line of the same diff, so what a `standard` plan gives up is latency, not coverage.

**Live progress.** Execution state is mirrored to `.claude/plan-progress.json` at every transition, and `skills/executing-plans/scripts/plan-progress.py` renders it as a statusline progress bar (`⚙ plan ▐██████░░░░▌ 3/6 (50%) · S2/3 ▶ T2.2 …`). It chains after an existing statusline invoked as a plain `bash <script>` and prints nothing when no plan is executing; done/total are derived from the plan's authoritative `Status:` fields, so a missed update shows a wrong CURRENT-TASK label rather than wrong counts — and a `⚠ status lag N` marker when the markers themselves stop moving.

**The band and the plan pane are Claude Code only.** The Claude Code build also draws the bars as a band above the prompt and opens a plan pane; that is a Claude Code mod, and Cursor has no such surface, so the status-line bar is the only display here.

**Wiring it — `/plan-statusline`.** The Cursor-only `plan-statusline` skill writes the one `statusLine` entry in your global `~/.cursor/cli-config.json`, the one piece a plugin cannot ship: a Cursor plugin manifest has no status-line contribution point. The entry points at `statusline-chain.sh`, which runs a statusline command you already had first and appends the bar on the next line. **It costs Cursor's own footer:** a configured status line replaces Cursor's native footer rows (model and context, working directory, branch) rather than adding one, until `/plan-statusline remove` takes it back out. Wiring is **global and one-time**, not per project. A hand-written wrapper is what this avoids: it hard-codes a checkout path and keeps running that copy after the plugin moves.

**No supervised handoff on Cursor.** The supervisor rollover protocol other hosts carry (`handoff-envelope.py`, `--adopt-handoff`) does not ship here. A Cursor handoff writes no envelope and is resumed by hand: start a fresh session pointed at the plan, which resumes from its last `RESUME HERE` block (`skills/executing-plans/references/session-handoff.md`).

**Triggers:** "execute this plan", "run the plan", "drive this plan to green", "work the plan in plan.md".

### `applying-design-handoff`

Redesigns an app to **precisely reproduce a Claude Design handoff pack** (the spec bundle from claude.ai/design — tokens, components, layout, assets), reshaping functionality to fit the design where they conflict. Detects the input — a local exported bundle; Claude Design's live `DesignSync` tool is a Claude Code connector, absent on Cursor, so with no bundle it asks you for one — inventories the app and its `workflow-spec` contracts, builds a design→app fidelity map, and writes a **reconciliation report** — the design wins, but every behavior change is declared via `workflow-spec` (`Changes`/`Removes WF-*`) and destructive changes require user sign-off. Implementation is cross-platform: it delegates to the **`design-handoff-reproducer`** subagent for precise per-slice reproduction, briefed with whatever stack skill the routing table names for the surface, then runs a fidelity verify loop (separate evaluator, rubric-graded, max 3 iterations). `executing-plans` drives it for a design-handoff/redesign task and fires the fidelity loop as a stage-gate hook.

**Triggers:** "reproduce this design", "apply the handoff pack", "redesign to match the design", "implement the Claude Design spec".

### `dispatching-parallel-agents`

Used by `executing-plans` (or directly) when a task is marked `Dispatch YES` and its dependencies are green — one such task or many. Dispatches one agent per task, runs them concurrently, integrates results respecting the plan's dependency graph.

**Triggers:** "dispatch these tasks in parallel", "run these in parallel", "fan out the parallel-marked tasks".

Routing is table-driven: `references/stack-routing.md` routes each `Dispatch: YES` task to a subagent. This plugin's own work goes to its agents (`design-handoff-reproducer`, `architecture-researcher`, `code-reviewer`); stack work goes to a stack-specialist agent, if one is installed whose description matches the stack, otherwise `generalPurpose`, with the stack's skill if one is installed. The table routes nothing else: a `Dispatch: NO` task runs inline. On Cursor every agent is dispatched by its bare name through the `Task` tool; there is no plugin namespace. A Cursor install copies only the plugin folder, so no capability index sits beside it: a capability whose plugin is not installed is found on disk by the routing table's plugin and name (`stack-routing.md` § *Resolving a capability whose plugin isn't enabled*). A CI-enforced `validate-stack-routing.py` check reads every cell of the file's tables and fails the build on any agent or skill this plugin does not ship, and on any `<plugin>:<name>` id, backticked or not, from another plugin.

### `honest-gates`

The integrity contract behind every gate in this plugin — and any acceptance check, test command, or "done" claim elsewhere. A gate is **GREEN** only when its real command ran *here* and passed; otherwise it is **RED** or **BLOCKED**. Never a stubbed task, fabricated evidence, a hidden exclusion, or a self-graded miss. Includes escalation rules for a genuinely blocked gate, so "I couldn't run it" stays distinguishable from "it passed". Applies eagerly — it does not wait to be asked.

**Triggers:** any point where something must pass, build, run, or be measured — before reporting a gate green, registering a build/test task, or recording test/benchmark evidence.

### `backlog`

Owns the per-project deferred-work register at `<records home>/backlog.md` (the repo's `docs/` unless a records resolver is configured; an unreachable records home stops the command). Append on defer, remove on implement, list on plan research. **It admits three kinds and refuses a fourth:** a significant improvement, a non-urgent decision the user must make, and work the user explicitly chose to defer — never a defect found during plan execution, which is fixed and its class swept instead. `add` refuses those rather than filing them, so the rule does not depend on the executor's self-discipline under gate pressure. It also has:

- `unify <project-path>` — derive backlog candidates from this project's plans via the parser rules in `planning-projects/references/plan-parser.md` (`backlog/scripts/backlog-unify.py`). Dedups by exact `Source` string equality. Dry-run by default.
- `complete <BL-NNN> --summary "<text>"` — archive a backlog item as a short `<records home>/plans/YYYY-MM-DD-<slug>-done.md` plan-summary and remove the entry. Commit convention `Closes BL-NNN` remains the audit trail.

**Triggers:** "add to backlog", "defer this", "what's in the backlog", "BL-NNN is done", "unify plans and backlog for this project".

### `decisions`

Owns the project's architectural-decision register, `<records home>/decisions.md`
(`DEC-NNN`). Every entry carries the **reason** behind the choice: the constraint,
the evidence, the rejected alternative, the accepted cost.

- `add` / `list` / `read` — record and consult decisions for one project.
- `relevant` — **the question planning and execution actually ask:** which recorded
  decisions constrain the work in front of me? Returns a digest of the project's register
  and of any register the configured records resolver lists, rather than raw files.
  Superseded entries come back **marked, not filtered** — "we believed X and stopped" is
  what stops the rejected approach being re-proposed; malformed blocks come back
  **flagged, not dropped**.
- `supersede` — replace a decision that no longer holds. The old entry stays, marked
  `superseded by DEC-NNN`; its reason is the record of what was believed and why.

Underneath `relevant` is a deterministic script you can also run directly:

```bash
python3 ~/.cursor/plugins/local/planning/skills/decisions/scripts/decisions-relevant.py --project <repo> --format json
```

An unreachable records home is exit 2, never an empty digest. A brand-new project with no
`decisions.md` yet gets `project_register: absent` and still receives any register the
resolver lists: an absent register never means "no decisions apply".

### `project-maturity`

Scaffolds and audits a per-project `<records home>/MATURITY.md` checklist across six publishing-readiness axes: Documentation, Security, Packaging, UI/UX, i18n, Testing & CI. Three subcommands:

- `init <project-path>` — scaffold MATURITY.md from a template.
- `audit <project-path> [--write]` — run deterministic auto-detectors (file globs, security-report findings parse, packaging-recipe presence, locale dirs, CI workflow detection). Dry-run by default. Never overwrites manual `[x] claim:` lines.
- `get <project-path>` — return parsed state as JSON for a caller (for example a cross-project plugin, if one is installed).

**Triggers:** "scaffold maturity", "is this ready to publish", "ship-readiness", "init MATURITY.md".

The UI/UX icon auto-detector recognizes the WebExtension layout — an `icons/` dir holding `icon*.{png,svg}` beside a `manifest.json` (e.g. `mozilla/icons/`, `chrome/icons/`, or root `icons/`) — in addition to root-level `icon.*`/`app-icon.*` and Android `res/mipmap-*`.

## Agents

Four subagents ship with the plugin, each dispatched by its bare name. Their owning skills dispatch them — you don't normally invoke them directly, though you can. Their frontmatter carries no model or tool list: Cursor chooses the model, and an agent that only reads is `readonly: true`.

### `code-reviewer`

Reviews a completed task, a commit or a set of changes against the plan and coding standards, and reports findings graded Critical / Important / Suggestion. `executing-plans` dispatches it for Tier-1 and Tier-2 reviews. It never edits, commits or switches branches.

**On Cursor:** `readonly: true`; Cursor chooses the model.

### `architecture-researcher`

Researches **one** candidate architecture (a pattern plus a concrete module layout) and returns cited findings: evidence, a directory tree, boundary definitions, and risks. `architecting-projects` fans out one per candidate, in parallel, then discards any uncited claim before building the comparison matrix.

**On Cursor:** `readonly: true` — it researches, it does not write code; Cursor chooses the model.

### `design-handoff-reproducer`

Reproduces **one** slice of a Claude Design handoff pack (a component or screen, plus its tokens and assets) precisely in the target stack, self-checking against the fidelity rubric. Dispatched per slice by `applying-design-handoff`. It reproduces; it does not design — and it **FLAGs** a behavior change back to the caller rather than applying one.

**On Cursor:** not read-only — it writes code and runs builds; Cursor chooses the model.

### `claim-verifier`

Proves a task's `Test:` claims and requirements with `prove-claim.py` from a clean context: for each claim it writes the break that would make the claim false, and the tool records the claim only after watching the test go red under that break and the tree come back. It takes one task, a list of tasks, or every task of a stage. On Cursor `executing-plans` dispatches it once per stage, at the gate, for every task of the stage; you can also invoke it yourself. It never fixes what it verifies and never commits.

**On Cursor:** not read-only — it applies and reverts breaks and runs builds, tests and `prove-claim.py`; Cursor chooses the model.

## Hooks

Every hook is wired by the plugin's own `hooks/hooks.json`, on Cursor's camelCase events.
The installer writes no `~/.cursor/hooks.json` entry: an event wired on both routes runs
twice. The `hooks` skill (`/hooks`) reports what is wired.

### `plan-continue` — on `stop`, interactive sessions only

A `stop` hook (`hooks/plan-continue.sh`, `loop_limit: 25`) that continues a run while a plan
is in flight, so an authorized run doesn't sit waiting for you to say "carry on". On Cursor an
assistant message with no tool call ends the turn, so the hook has no classifier over the
last message: any completed turn while `.claude/plan-progress.json` reads
`preflight`/`task`/`gate` is continued with a follow-up message, and a stop on purpose is a
state-file write (`blocked` or `handoff`). Cursor runs `stop` hooks only in an interactive
session; a headless `cursor-agent -p` run gets no backstop. It fails open on every unexpected
condition and always exits 0. Full contract:
`skills/executing-plans/references/plan-continue-hook.md`.

### Proof-record commit gate — **on by default**

A git `reference-transaction` hook (`hooks/git-ref-gate.sh`) that refuses a `Stage N green`
commit whose tree lacks valid `prove-claim.py` records for the stage's tasks, while a plan is
in flight. On Cursor proof is made once per stage, at the gate, so task commits carry code
only and the gate does not check them. It reads the finished commit, so `--no-verify`, `-a`,
`--amend`, `commit-tree` + `update-ref`, cherry-pick and a detached HEAD all pass through it. A
record must match the commit's own tree and the plan's current wording. With no plan in
flight (no execution state, or one naming no plan or a plan that is gone) it refuses a
`Stage N green` commit outright, since that stage could never be checked; the refusal names
`plan-state.py init`. A snapshot the gate cannot read or that names another branch (`state_error`) and a
finished run are not "no plan": the gate allows them, so a new plan started after a finished
one is ungated until `plan-state.py init` records it.

`executing-plans` installs it into the project when a plan loads, through
`scripts/hooks-install.py` in this plugin. The installer refuses to replace someone else's
`reference-transaction` hook, and refuses a hooks directory outside the repo (a shared or
global `core.hooksPath`), since a shim there would gate every repo that uses it.

A `beforeShellExecution` hook (`hooks/commit-gate.sh`) keeps the gate on: in a repo with a plan
in flight it denies a shell command that would switch the git hook off. It is a rail, not a
sandbox.

### Dispatch log — **on, inert outside a plan run**

A `preToolUse` hook, matcher `Task` (`hooks/dispatch-log.sh`). While
`.claude/plan-progress.json` exists it appends one `dispatch` line per subagent launch, with
its agent name and description, to `.claude/dispatch-log.jsonl`. Cursor fires no subagent
start or stop event, so the log holds dispatch lines only. With no plan in flight it writes
nothing. It never blocks. It only gathers;
`skills/executing-plans/scripts/review-ledger-check.py` decides.
Close-out archives the dispatch log. Owned v2 execution snapshots and receipts remain terminal evidence; only unowned legacy progress may be deleted.

## Where artifacts live

Records live in the project's **records home**: the repo's `docs/` when nothing is
configured, or wherever a configured records resolver says
(`docs/configuration.md`, `references/records-resolver.md`). Every skill asks
`lib/records_home.py`; an unreachable records home stops the skill and creates nothing.

| Artifact | Path | Written by |
|---|---|---|
| Plans (all rungs) | `<records home>/plans/YYYY-MM-DD-<topic>-plan.md` | `planning-projects` |
| Architecture docs | `<records home>/plans/YYYY-MM-DD-<topic>-architecture.md` | `architecting-projects` |
| Backlog | `<records home>/backlog.md` | `backlog` |
| Decisions | `<records home>/decisions.md` | `decisions` |
| Maturity | `<records home>/MATURITY.md` | `project-maturity` |
| Behavior contracts | `<repo>/docs/workflows/` | `workflow-spec` |
| Live execution state | `<repo>/.claude/plan-progress.json` | `executing-plans` (private, gitignored; owned v2 terminal evidence retained) |

## Worked example

```text
(copy the plugin into ~/.cursor/plugins/local/planning, then Reload Window)

"/brainstorming I want to add offline sync"
```

`brainstorming` fires and works through purpose, constraints, and alternatives one question at a time. Because the design has a structural surface, it hands off to `architecting-projects`, which fans out `architecture-researcher` agents over 2–4 candidates and presents a comparison matrix for your explicit approval, then writes the `ARCH-NN` doc.

```text
"plan it"
```

`planning-projects` triages a format first, runs its research phase (online sources, backlog scan, workflow specs, the architecture doc, and the **decisions scan**), and writes a staged plan whose structure-creating tasks cite `ARCH-NN` and whose constrained tasks cite `Honors DEC-NNN`.

```text
"execute the plan"
```

`executing-plans` re-checks the decisions for staleness at Preflight, drives Red-Green loops with a commit per green task, fans independent tasks out through `dispatching-parallel-agents`, runs tiered gates with two-tier review, and at close-out bumps versions across every mirror, reconciles the backlog, and records any supersede the plan declared.

## Why a separate plugin

All eleven skills reference each other by name, and so do the two Cursor-only ones (handoffs from brainstorming → architecting-projects → planning-projects → executing-plans → dispatching-parallel-agents; executing-plans → applying-design-handoff for redesign tasks; executing-plans → plan-statusline, whose installer wires the bar that renders the executing plan's state file, and → hooks, which checks the hooks a run relies on; planning-projects/executing-plans ↔ backlog, decisions and workflow-spec; and honest-gates binding every gate the pipeline reports). Splitting them across plugins would break the handoffs. They have no transitive runtime dependencies and can be installed alongside any other plugin without conflict.

## Owned execution protocol (development contract)

`skills/executing-plans/scripts/plan-state.py` and its required sibling `plan_state.py`
implement the versioned state API. Use expected revision and operation id; preserve
completed versus reserved repair and scoped owner amendments. Readers and Stop
adapters consume the same validated state. The contract is
[execution-state-contract.md](skills/executing-plans/references/execution-state-contract.md).
`evaluation-ledger.py` records metadata-only original comparison evidence, with
separate denominators and identity-checked reuse; see
[evaluation-evidence-contract.md](skills/executing-plans/references/evaluation-evidence-contract.md).

The [protocol manifest](skills/executing-plans/scripts/workflow-recovery-manifest.json)
names the protocol's operations, exits, limits and test groups, and points at the
frozen scenario corpus. Its suites run from the source repository's root, where
`bash scripts/run-tests.sh` discovers and runs every suite; neither it nor the tests are
part of the installed plugin. The checks establish
local protocol behavior; neither they nor advisory observations establish owner
product acceptance.

## License

MIT
