# planning (Codex)

An eleven-skill pipeline that turns a vague idea into executed work and keeps each
project's contracts and records honest: brainstorm a design, write a plan whose stages end
in runnable checks, execute it Red-Green with honest gates and code review, and keep a
backlog and decisions. This is the Codex build of the plugin; the skills are invoked as
`$planning:<skill>`.

## Installation

Add the marketplace and install the plugin:
```bash
codex plugin marketplace add sureserverman/staged-planning
codex plugin add planning@staged-planning
```

Install the agent roles. A Codex plugin cannot ship roles, so this plugin keeps them as
templates and copies them into your Codex home on request. It never replaces a role file
that differs from its template:
```bash
python3 <plugin folder>/scripts/install-agents.py            # report
python3 <plugin folder>/scripts/install-agents.py --install  # copy the missing roles
```
`<plugin folder>` is the installed copy under `$CODEX_HOME/plugins/cache/` (by default
`~/.codex/plugins/cache/staged-planning/planning/<version>/`). The roles are
`planning:code-reviewer`, `planning:architecture-researcher`,
`planning:design-handoff-reproducer`, `planning:claim-verifier` and
`planning:goal-evaluator`.

Trust the hooks. Plugin hooks start untrusted on Codex; review and trust the four in
`/hooks` to turn them on.

## Skills

| Skill | For |
|---|---|
| `$planning:brainstorming` | a validated design before non-trivial work |
| `$planning:architecting-projects` | researched architecture options and an approved choice |
| `$planning:planning-projects` | a plan of the right size: Direct, Light, Standard or Master |
| `$planning:executing-plans` | running a plan through Red-Green loops and stage gates |
| `$planning:dispatching-parallel-agents` | spawning a plan's independent tasks at once |
| `$planning:applying-design-handoff` | reproducing a local design handoff pack |
| `$planning:honest-gates` | integrity rules for any check, gate or done claim |
| `$planning:backlog` | the deferred-work register |
| `$planning:decisions` | the decision register and its reasons |
| `$planning:workflow-spec` | behavior contracts and regression audits |
| `$planning:project-maturity` | the ship-readiness checklist |

## Hooks

- **plan-continue** (Stop). On Codex a final message ends the turn and nothing resumes it,
  so while a plan is in flight this hook continues every stop except a recorded one: a
  blocker recorded with `plan-state.py set-blocker` (an `ACTION NEEDED:` block comes after
  it), a finished run, a measured handoff, or stale state. A loop guard ends it after 25
  continuations with no movement (`CODEX_PLAN_CONTINUE_MAX`). It is opt-in per session:
  start the Codex session that executes a plan with `CODEX_PLAN_CONTINUE=1`.
- **proof-guard** (PreToolUse, shell commands). While a plan is in flight it denies a
  command that would switch off the proof-record commit gate.
- **dispatch-log** (SubagentStart, SubagentStop). Logs each spawned agent's role and id,
  so `review-ledger-check.py` can check a gate's claimed reviews against the agents that
  actually started.

The proof-record commit gate itself is a git hook, opt-in per project:
`python3 <plugin folder>/skills/executing-plans/scripts/proof-hooks-install.py --install --repo <repo>`. In an opted-in repo with no plan in flight it
refuses one commit, a `Stage N green` subject, and its refusal names `plan-state.py init`.

## Where artifacts live

Records live in the project's records home: the repo's `docs/` when nothing is configured,
or wherever a configured records resolver says. Every skill asks `lib/records_home.py`; an
unreachable records home stops the skill and creates nothing. Plans go to
`<records home>/plans/`, the backlog to `<records home>/backlog.md`, decisions to
`<records home>/decisions.md`, and the live execution state to
`<repo>/.claude/plan-progress.json` (private, gitignored).

## What differs from the Claude Code build

There is no status-line progress bar, no band or plan pane, and no slash command: Codex's
status line runs no command, and it has no surface for a plugin's panes. A design handoff
is read from a local export only. Context use is read from Codex's session rollout. The
repository's `docs/host-matrix.md` lists every feature's status on each host.

## License

MIT
