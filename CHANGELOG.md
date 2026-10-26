# Changelog

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
