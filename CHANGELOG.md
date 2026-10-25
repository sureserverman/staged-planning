# Changelog

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
