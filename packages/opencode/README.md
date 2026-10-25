# opencode-staged-planning

An eleven-skill pipeline that turns a vague idea into executed work and keeps each
project's contracts and records honest: brainstorm a design, write a plan whose stages end
in runnable checks, execute it Red-Green with honest gates and code review, and keep a
backlog and decisions. This is the OpenCode build of the planning plugin, one npm package.

## Installation

From npm (published by 1.0.0), add the package to the `plugin` array of your
`opencode.json`:
```json
{ "plugin": ["opencode-staged-planning"] }
```

Or load a local copy by its path:
```json
{ "plugin": ["/absolute/path/to/opencode-staged-planning/src/index.ts"] }
```

That is the whole install. The plugin registers its own skills, agents and commands from
its `config` hook: it adds its `skills/` folder to the config's skill paths, each
`agents/<name>.md` as an agent and each `commands/<name>.md` as a command. A name your own
config already defines is left alone, so your copy wins. Nothing is copied into
`~/.config/opencode`, `~/.claude/skills` or `~/.agents/skills`.

OpenCode also lists skills from `~/.claude/skills` and `~/.agents/skills`. With one skill
name in those two and `~/.config/opencode/skills`, only the `~/.config/opencode/skills`
copy was listed and served (measured); the others were hidden without a warning. Which of
this package's copy and a same-named copy in those roots OpenCode serves is not measured,
so keep no skill of the same name there.

## Invoke skills by name

OpenCode's matching of a request to a skill description is unreliable, so name the skill:
"use the `planning-projects` skill to plan this", "run `executing-plans` on
`docs/plans/<plan>.md`". Every skill's description says so too.

| Skill | For |
|---|---|
| `brainstorming` | a validated design before non-trivial work |
| `architecting-projects` | researched architecture options and an approved choice |
| `planning-projects` | a plan of the right size: Direct, Light, Standard or Master |
| `executing-plans` | running a plan through Red-Green loops and stage gates |
| `dispatching-parallel-agents` | dispatching a plan's independent tasks at once |
| `applying-design-handoff` | reproducing a local design handoff pack |
| `honest-gates` | integrity rules for any check, gate or done claim |
| `backlog` | the deferred-work register |
| `decisions` | the decision register and its reasons |
| `workflow-spec` | behavior contracts and regression audits |
| `project-maturity` | the ship-readiness checklist |

Commands: `/backlog`, `/decisions` and `/project-maturity` take the operation as their
first argument and hand off to the skill of the same name.

Agents, dispatched through the task tool by name: `code-reviewer`,
`architecture-researcher` and `claim-verifier` (all three deny edits), and
`design-handoff-reproducer`. A role with no agent of its own, such as the gate's goal
evaluator, runs on OpenCode's built-in `general` agent. The calling agent needs the `task`
permission; when it is denied, a plan run stops and says so rather than running the work
inline.

## No auto-continue at Stop

OpenCode has no Stop hook that can hold a turn, so nothing continues a plan for you. The
executor keeps going until the plan finishes or it stops on purpose: a recorded blocker, a
spent remediation budget, or a measured handoff. Those stops are written to the plan's
state for the next session to read; they cannot hold or resume the current one. To carry
on after a stop, start a session and name `executing-plans` again.

## Hooks

Two adapters run inside the plugin on OpenCode's tool events:
- **proof-guard** (`bash` calls). While a plan is in flight it blocks a command that would
  switch off the proof-record commit gate.
- **dispatch-log** (`task` calls). Logs each dispatch, with its agent and description, and
  each subagent start and stop, so `review-ledger-check.py` can check a gate's claimed
  reviews against the agents that actually ran. It never blocks a call.

The proof-record commit gate itself is a git hook, opt-in per project:
`python3 <package folder>/skills/executing-plans/scripts/proof-hooks-install.py --install --repo <repo>`. In an opted-in repo with no plan in flight it
refuses one commit, a `Stage N green` subject, and its refusal names `plan-state.py init`. A snapshot the gate cannot read or that names another branch (`state_error`) and a
finished run are not "no plan": the gate allows them, so a new plan started after a finished
one is ungated until `plan-state.py init` records it.

## Where artifacts live

Records live in the project's records home: the repo's `docs/` when nothing is configured,
or wherever a configured records resolver says (`references/records-resolver.md`). Every
skill asks `lib/records_home.py`; an unreachable records home stops the skill and creates
nothing. Plans go to `<records home>/plans/`, the backlog to `<records home>/backlog.md`,
decisions to `<records home>/decisions.md`, and the live execution state to
`<repo>/.claude/plan-progress.json` (private, gitignored).

### A records home outside the repo needs a permission entry

OpenCode asks before a tool touches a path outside the working directory, and
`opencode run` refuses that request without asking. When your records home is outside the
repo, allow it in `opencode.json`:
```json
{
  "permission": {
    "external_directory": {
      "/absolute/path/to/records-home/**": "allow"
    }
  }
}
```
The package's own folder is outside the repo too. The plugin allows reads there itself:
its config hook adds an `external_directory` allow for the package folder only. It adds
nothing when your config denies `external_directory` outright, and says so on stderr; then
allow the package folder yourself, or the skills cannot read their references or scripts.

A refused write does not fail the run: `opencode run` prints the refusal and still exits 0.
So never take a run's exit code as proof that its records were written. Check that each
record landed where the records home says, and treat a missing one as a failed run.

## What differs from the Claude Code build

There is no status-line progress bar, no band or plan pane, and no automatic continuation
at Stop. A design handoff is read from a local export only: OpenCode has no design tool.
The supervised session handoff is not carried. Context use is measured from OpenCode's own
session store and models cache. The repository's `docs/host-matrix.md` lists every
feature's status on each host.

## License

MIT
