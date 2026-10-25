# Changelog

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
