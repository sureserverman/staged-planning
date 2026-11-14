# Changelog

## 2.3.0 — 2026-11-14

- **A wrong script call is answered with a working one.** When a plugin script an executor
  or planner calls gets a missing or wrong argument, its stderr ends with an `example:`
  line holding a complete call that the same script accepts. `prove-claim.py` answers a
  claim's text passed to `--claim` with "--claim takes the claim's number". Exit codes and
  accepted input are unchanged.
- **The skill shows the calls it mandates.** Every host's `executing-plans` trunk carries a
  literal `prove-claim.py claim` call and the `plan-state.py` calls for `init`, a task
  `transition` and `finish`, each with its payload. After writing an owner's mid-run answer
  into `## Owner decisions`, the run checks it with `owner-decision.py check`.
- **The owner-decisions reference lists every refusal `owner-decision.py check` reports**: an
  `applies to:` word the reader cannot place, a code span that holds no command, and a line
  that voids the section. `check` already reported these; the run now calls it after writing
  a mid-run answer, so a refusal shows when the entry is written, not when `match` needs it.
  `check` and `match` accept the same input as before.
- **The recommended option is the smallest that meets the request.** A larger option says
  what it adds, in tasks or stages. It is marked Recommended only when the request asks for
  it.
- **Outcomes cover what the request's user can meet.** They name the person or program that
  uses the product. A failure line is written only for a failure that user can cause through
  the product. A stage whose result only a later stage or the project's own tests consume
  has no Outcomes.
- **The goal check is written once.** A plan carries one `(goal)` check, in its final gate.
  An earlier gate repeats it only when that stage's own tasks can make it fail.
  `validate-gate-checks.py` still checks only that one is present.
- **An existing plan needs no change.** A plan with a `(goal)` check in every gate, or with
  Outcomes for every way of failing, still validates and still runs.

## 2.2.0 — 2026-11-14

- **A task owes a proof only when its plan marks it `Proof: required`.** Any other task goes
  from a green test to its commit, with no `prove-claim.py` record. Planners write the new
  optional field on a task whose diff touches a risk-listed path, or whose product is a
  checker that produces a verdict. The record audit and the commit gate agree on which tasks
  owe one. A record that exists is still checked against its commit.
- **Proof drift and a stray file under `proof/` are reported, not refused.** A later task
  editing a proven file is an advisory in the record audit, and the `Stage N green` commit
  lands. `prove-claim.py` and the commit gate name a non-record file under `proof/` and carry
  on. One exception on Cursor: its ref hook still refuses a green commit whose record does
  not match that commit's own tree.
- **The demo evaluator runs once per plan, at the last gate.** At `standard` and `high` it
  demos every stage's Outcomes there. At `light` and `none` no gate owes one. A gate with a
  `(judgment)` line still funds an evaluator at `standard` and `high`. There is no second
  evaluator at close-out.
- **An Outcome the session cannot show is a residual.** Its verdict is `not shown here`,
  with what a person would need to show it. It goes in the gate report and in a close-out
  `ACTION NEEDED:` item, not a Blocking finding, and the owner is not stopped to reword it.
  `does not hold` stays Blocking.
- **A finished run no longer blocks the next one.** `plan-state.py init` over a `complete`
  run moves its snapshot to `.claude/plan-state-archive/<run_id>.json` and starts the new
  run, on the same branch or another. An unfinished run still refuses, naming its plan and
  branch. On another branch than a finished run's, or under a detached HEAD, the status line
  shows no run and the hooks treat it as the finished run it is (they stand aside), instead
  of a `state_error`.
- **An existing plan needs no change.** Its tasks simply owe no proof unless you add
  `Proof: required`.

## 2.1.0 — 2026-11-12

- **The progress display marks the live run as current, from any worktree.** A session with
  no fresh run of its own now pins the one fresh run held in another worktree of the repo.
  Two or more fresh runs elsewhere mark none current, and each plan shows as an ordinary row.
  A run not updated for 12 h elsewhere does not compete. Where a records resolver manages
  the repo, a linked worktree shows the main worktree's plans.
- **A finished run stops pinning.** A run the hooks call finished, or a run over
  a plan carrying **Completed:** or **Abandoned:** (outside a fresh close-out), no longer
  holds the current row. Its state file is left where it is.
- **A stage opens with no task on the bar.** A `task` transition naming a stage and no task
  empties `task` and `task_desc`, so the bar reads `S2/…` without the last stage's task. A
  gate transition keeps them.
- **A plan with every task done and no close-out line says `◌ close-out pending`.**
- **The live-window sidecar follows the pinned run (Claude Code build).** `context-usage.py` keeps
  `plan-context.json` in the worktree of the run the display marks current, so the Claude
  mod writes it where the executor reads it.

## 2.0.0 — 2026-11-11

- **Breaking: the `dispatching-parallel-agents` skill is gone.** Its rules now live in
  `executing-plans`, the one skill that dispatches. The procedure is
  `executing-plans/references/dispatch.md`, and the routing table and its validator are
  `executing-plans/references/stack-routing.md` and `executing-plans/scripts/validate-stack-routing.py`.
  Every host lists ten planning skills; Cursor lists its own two besides. A plan whose roster
  line cites the old routing path no longer resolves it; cite
  `planning/skills/executing-plans/references/stack-routing.md`.
- **brainstorming keeps its gate and drops its ceremony.** It asks only what it cannot infer,
  in batches, through the host's question tool, and states the rest as assumptions. It presents
  the design once, and only an explicit yes approves it. It no longer claims every project:
  work that `planning-projects` would triage as Direct needs no brainstorm.
- **planning-projects' Phase -1 is one paragraph.** Ask only what would change the plan and the
  repo cannot answer; state an inferred answer as an assumption; batch the questions.
- **Shipped skills carry no Sources sections.** The citations moved to `docs/sources.md`.
- **On Codex, both skills still wait for the answers.** A new test builds the Codex host and
  fails if either rewrite pattern stops matching.
- **New, on demand only: `evals/behaviour-rules/`.** Three `claude plugin eval` cases, each with
  a sabotage control, plus `scripts/eval-variants.py` (a with/without build per rule) and
  `scripts/eval-report.py` (pilot, matrix, table and tool-used checks). It does not run in
  `scripts/run-tests.sh` or any gate. The measurement itself has not been taken: an eval case
  needs Bash under the OS sandbox, and the release machine could not create its namespaces.

## 1.4.3 — 2026-11-10

- **On Codex, a plan waits for the owner's answers.** Outside Plan mode, Codex asks through
  `request_user_input_async`, which returns at once with no answer. Planning sessions took that
  as leave to go on: they wrote the plan seconds later on guessed answers, always the narrowest
  scope, so a plan for a full app came out as a bare first release. `planning-projects` on Codex
  now treats its scope and owner-decision questions as required. While one is open it only
  reads; with no reply it ends the turn and repeats the questions. No reply is not a decline, and
  a list of features does not cap how complete the product should be. `brainstorming` on Codex
  follows the same rule for its questions, its section checks and the design's approval. Other
  hosts are unchanged.

## 1.4.2 — 2026-10-31

- **A skipped repository check says so.** If a sub-plan boundary under a version-2 reader cannot
  tell where the next sub-plan runs, because `--plan` is missing or names the master, or more
  than one sub-plan could run next, the reason now names why. A helper that cannot load is said
  on stderr, and the measured rules decide, instead of a crash. The Codex fork's rule has tests.

## 1.4.1 — 2026-10-31

- **A sub-plan in another repository gets its own session.** Under a version-2 reader, a master
  plan's boundary now hands off whenever the next sub-plan runs elsewhere, at any context use.
  Before, a short plan under 25% stayed in one session: all its repositories ran under the first
  project, without their own folder trust. Pass the closed sub-plan as `--plan` beside
  `--sub-plan-boundary`. With no version-2 reader, or a plan that cannot be resolved, the 25%
  floor rules as before.

## 1.4.0 — 2026-10-30

- **A handoff can name where the work continues.** Destination-aware version 2 envelopes carry
  a master's next sub-plan to another repository, and a same-root stage can adopt its handoff. A
  reader asks for version 2; with no such request the writer keeps writing version 1, so a
  running supervisor is unaffected. A writer can also tell a supervisor that a plan finished.
- **An envelope is never too big for the reader.** Over the reader's
  4096-byte limit, every writer refuses before writing and prints the size and the limit.
- **One outcome per handoff, even through a kill.** A claim now holds the whole outcome and
  appears in one step. The next writer to reach it publishes what a killed writer left, so the reader learns
  it, and succeeds only if it asked for that same outcome. Any other session, plan, event or code
  is refused.
- **`plan-state.py` waits on stdin less.** `show` never reads it. A detached HEAD, a missing
  option or a corrupt snapshot is refused before it reads. Closed, blank or unreadable stdin is a
  missing document, and the refusal names the operation. Other refusals still read first, such as
  a stale revision or a snapshot owned by another branch, so an open silent stdin can hang those.
- **Known limits.** An empty claim from an older writer, or a malformed claim, refuses both
  outcomes, so that id gets neither. A filesystem without hard links gets an exclusive create,
  which a kill can leave partial. A kill can leave a `.tmp` dotfile. Near the limit, a version 1
  `ready` can fit while its `accept` does not. Every writer failure still says "already accepted
  or failed", even on an I/O error. A supervisor that deletes a consumed outcome but keeps the
  claim can see a late writer publish it again. A `null` snapshot reads as no snapshot, so such a call waits
  for its document. No live supervisor consumes version 2 yet.

## 1.3.0 — 2026-10-30

- **A run can come back from a lost snapshot.** `plan-state.py recover` rebuilds a snapshot lost
  from under its pointer, from cited evidence. The run keeps its id and spent rounds, starts
  blocked with qualification `blocked`, and names what it cannot know. It refuses when any
  snapshot exists, valid or not. It grants no round.
- **The owner reviews the history before work resumes.** `plan-state.py resolve-recovery` records
  that review, from a different source than the recovery's. Until then no round starts or
  finishes, the ceiling cannot rise, the run cannot finish, and `--budget-check` reports
  `conflict`.
- **Known limits.** A citation binds a claim to hashed bytes; it does not prove the claim. Owner
  sources are recorded text, not authentication. An operation id from before the loss is refused
  only if the recovery lists it. A gate the recovery does not list reads as fresh. The status
  display does not mark a recovered run. A reader older than 1.3.0 refuses a recovered snapshot.

## 1.2.1 — 2026-10-30

- **The hooks see a run held in another worktree.** With no run of its own, a worktree
  answers to the one run in flight among the others, not only the main worktree's. A run in a
  linked worktree now gates commits from the main worktree and from siblings, takes their
  dispatch lines, and guards `core.hooksPath` for them, on Claude, Codex and Cursor.
- **Two or more runs elsewhere are not guessed between.** The commit hook refuses a commit
  naming a task or stage and lets any other land. A dispatch goes in neither log. The guards on
  config shared by every worktree deny.
- **Known limits.** An unrelated commit whose subject names a task is judged against the one
  run. A stale run counts until it is finished or its state file is moved away. With two runs,
  a neutral-subject commit ticking a gate box lands. A worktree on a mount that is down reads
  as holding no run.

## 1.2.0 — 2026-10-30

A sweep of the code-fixable backlog. One planned item is not in this release: the handoff
writer's size cap, its atomic claim and `plan-state.py`'s stdin read. Neither is any
destination-aware handoff work.

- **Proofs and the plan audit.** `prove-claim` finds the runner behind shell syntax and runs
  bash Tests under bash. A record binds the blobs a task touched and witnessed, so it survives
  the edits a run must make. Known limit: a bare `pytest` or `cargo test` names no file to
  bind, so its record is checked at its task commit only, and a later change to the code does
  not show as drift. The audit adds ORPHAN-PROOF-DIR and STRUCTURE-SHRANK, reads
  `### Stage N Gate` strictly, and every gate runs it with `--require-all-checks`.
- **Run state and hooks.** The commit gates and dispatch logger read their own worktree's run,
  then the main worktree's. `owner-decision.py match` finds the plan's run from any worktree.
  A commit that ticks a gate box is a stage close whatever its subject. A Light plan closes
  out cleanly. Known limit: the hooks do not see a run held in another linked worktree.
- **Repo checks.** The capability index lists mod-registered commands, and its drift check
  fails a registration it cannot place. LOST-REFERENT checks each § pointer's referent.
  NEGATED-RULE screens retention markers. `project-maturity get` runs a script.
- **Status line and Cursor.** The renderer reads the records home in a forked child and waits
  at most about 3 s. That child also writes the cache, after the bars are out, so a stalled
  write never holds the caller. A stalled reader never writes the cache, and redraws do not
  pile up stuck readers. Reads are capped, and non-regular files are refused without blocking. Each Cursor
  script fork has its own test. macOS and a real stuck mount are untested.
- **Dispatch and review cost.** Every dispatching file carries the background-work rules.
  `Review: required` follows the risk list, and a re-review covers the fix diff. Only drifted
  records are re-proved. The gate evaluator is skipped when a recorded command at the stage's
  final tree decides the goal. Nothing proves that command actually ran, and no live agent on
  Codex, Cursor or OpenCode has yet acted on the narrowed rules.

## 1.1.1 — 2026-10-26

- **A script decides whether an owner decision applies.** `executing-plans/scripts/
  owner-decision.py match --plan P --at preflight|stage|closeout` with `--stage`, `--task`
  and `--command` for the case lists the `## Owner decisions` entries that apply and refuses
  the rest with the reason. Every place an entry's `applies to:` names (`Preflight`,
  `close-out`, `Stage N`, `Task N.M`, `Sub-plan N`, a backticked command) must exist in the
  plan and match the case. An entry for "the Stage 2 close-out" in a one-stage plan is now
  refused ("names Stage 2; the plan has no Stage 2"). An entry without the owner's dated,
  quoted words, or saying `ask at execution`, is refused. A sub-plan also reads its master's
  entries for its own `Sub-plan N`. Exit 0 applies, 1 asks the owner. This closes 1.1.0's
  known limit.
- **The executor acts only on what `match` lists.** § Stop conditions, § Safety rails,
  close-out step 10 and the gate's § ACTION NEEDED run `match` before acting on an entry, in
  every host copy. A command is covered only by an entry naming that exact command, with
  or without `--require-command`, and the executor runs exactly the command it checked.
- **The author checks the entries before presenting.** `owner-decision.py check <plan>`
  reports each entry that cannot be an answer, with its line, and exits 1. Both checklists
  require it to exit 0, and `owner-decisions.md` § The record lists the place words.
- **The section has a strict format.** One line per entry, starting `- **OD-N** — ` at column
  0, in plain printable text, with commands compared as exact text. Any other line, markup,
  raw HTML or a comment voids every entry in the section, so what the script reads is what a
  reader sees. The threat model is careless writing and reading, not a plan crafted to
  deceive. The three plan templates keep their guidance above the heading, so a copied
  template does not void itself.

## 1.1.0 — 2026-10-26

- **Planning asks what execution would stop for.** `planning-projects` § *Ask execution's
  questions now*: once the draft exists and before it is presented, the author sweeps it
  against `references/owner-decisions.md` and asks every triggered question in one batched
  round. Triggers include the branch, a destructive command, a secret's mechanism, a
  shared-infrastructure stage and the merge. Each answer goes in the plan's new
  `## Owner decisions` section as `OD-N`, quoted and dated. The Standard, Light and master
  templates carry the section, and both checklists carry the item. The Light checklist is
  twelve items.
- **Execution reads the owner's answers before it asks.** `executing-plans` § Stop conditions:
  an entry naming the case is the answer, acted on and cited by its `OD-N`. An entry covers
  only the case it names. `ask at execution` is no answer, and a case no entry names still
  stops. A destructive command is confirmed by an entry naming that command, never by the plan
  (a task, gate check or close-out step) saying to run it. Close-out step 10 carries out a
  recorded merge, running `finish` before anything leaves the run's branch, and offers one
  only when none is recorded.
- **A master's plan pane shows every sub-plan.** `plan-progress.py --json` gives a master's
  breakdown its whole register as `subplans`. Both the `/plan-view` pane and a master's own
  pane list every entry in register order: `✔ done`, the executing one's phase and task,
  `not started`, or `plan not found`. A model without `subplans` draws as before.
- **A wrapped stage field keeps its bullets.** `stage_fields()` dropped every Outcome under a
  `**Outcomes:**` line that wrapped onto a second line. A wrapped field line now joins the
  field's text.
- **A run starts its state on its own branch.** `plan-state.py init` runs once git bootstrap
  has put the run on its branch, which owns the run. Starting it on `main` first stopped runs
  mid-way on a tracker question.
- **Known limit: an entry naming a stage the plan does not have can still be applied.** The
  executor reads `applies to:` itself. In testing, an entry scoped to "the Stage 2 close-out"
  in a one-stage plan was applied at that plan's close-out in 3 of 3 runs. Naming the exact
  commands in `applies to:` held in 3 of 3 runs. 1.1.1 moves the matching into a script.

## 1.0.5 — 2026-10-25

- **Verification scales to the change.** `test-scope-tiers.md` § *Outside a plan, and proven
  trees*: a release or follow-up fix runs what its change kind needs (docs: build `--check`,
  validators, leak/portability; tests: the touched tests; code: the touched modules' suites),
  and CI runs the full suite. A tree that already passed is not run again: no pre-tag rerun,
  no detached-clone rerun, no repeat of a gate's full pass after a fix that fix-scope proved.
  The gate-position runs stay: measured over about 20 plans, they caught 47 new failures, 8 of
  them product defects; the unmandated reruns caught none of value.
- **Fix-scope includes the repo's validators** and every test that doubles a changed
  signature. Every failure caught after a fix in the sample was one of those.
- **A task that adds to a closed set updates its pins** (an enum, event list, migration count,
  snapshot baseline), in the same task. That was the most common reason a first full pass
  went red. The Light checklist is eleven items.

## 1.0.4 — 2026-10-25

- **The OpenCode README no longer says the package is on npm.** It said "From npm (published
  by 1.0.0)" and led with `{ "plugin": ["opencode-staged-planning"] }`, which loads nothing
  because the package was never published. It now leads with the clone-and-path install, as
  the repository README does, and says npm comes later. No code change.
- **The repository no longer carries a backlog or decisions register.** `docs/backlog.md` and
  `docs/decisions.md` were the maintainer's working records; they moved out of the repo and
  are gitignored. The plugin's own `backlog` and `decisions` skills are unchanged.

## 1.0.3 — 2026-10-25

- **The break patch keeps its fallback.** 1.0.2 wrote the shell redirect as `"$TMPDIR"`, which
  points at `/` where `TMPDIR` is unset. Rule 4a and the dispatch brief now say
  `"${TMPDIR:-/tmp}"`, still in a shell redirect, still never a literal path in a file tool.
  Rule 4a covers every scratch file; the dispatch brief covers the patch (1.0.2's note said
  both covered scratch files).
- **Scope checks leave out the executor's own files.** The authoring checklist (Standard and
  Light) says a gate check over what a commit range changed (`git diff --name-only`) must
  leave out the `proof/` records and any `.gitignore` the executor commits, or the plan's own
  bookkeeping fails it. A clean-machine run's toy plan failed its own gate this way.

## 1.0.2 — 2026-10-25

- **Scratch files stay in the session's temp folder.** Rule 4a and the dispatch brief now
  say the break patch is written by a shell redirect into `"$TMPDIR"`, and that every
  scratch file goes there, never to a literal `/tmp/` path. They said "a patch file in
  `${TMPDIR:-/tmp}`", and a model saving the patch with a file tool, which cannot expand
  the variable, wrote it to `/tmp`, outside the session; a scratch gate script followed
  it there. Measured on a clean-machine run, where any write outside the session counts.

## 1.0.1 — 2026-10-25

- **Cursor:** `scripts/hooks-install.py --status` reads the plugin's quoted hook commands.
  It took each command's last path part as written, closing quote included, so it
  reported all three hooks unwired and exited 1 although Cursor ran them. It now splits
  a command as the shell does and takes the script from its last word.

## 1.0.0 — 2026-10-24

The first release of the `planning` plugin, built from one host-neutral core for four
hosts:

- **Claude Code** — `planning@staged-planning` from this repository's marketplace, with the
  plan-progress band on 2.1.288 or later;
- **Codex** — `planning@staged-planning` from this repository's marketplace, its agent
  roles copied by the command its README gives;
- **Cursor** — a local plugin synced from `plugins/cursor/planning`;
- **OpenCode** — the `opencode-staged-planning` package in `packages/opencode`.

Skills: brainstorming, architecting-projects, planning-projects, executing-plans,
honest-gates, dispatching-parallel-agents, applying-design-handoff, backlog, decisions,
workflow-spec and project-maturity, plus the bundled code-reviewer and the other agents.

Two seams connect it to tools outside it, and neither is needed to use it:

- **The records-resolver hook** — with no configuration a project's plans, backlog,
  decisions and maturity live in its `docs/`; a configured resolver names another home
  (`docs/records-resolver.md`, `docs/configuration.md`).
- **The supervisor handoff protocol** — `planning-handoff` version 1, the envelopes a run
  writes when it hands off at a gate, for a supervisor that starts the next session
  (`docs/handoff-protocol.md`).
