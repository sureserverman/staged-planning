# Changelog

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
