---
name: hooks
description: Check the planning hooks on Cursor, clear entries an older installer left in ~/.cursor/hooks.json, and install the proof-record git hook in a project. Triggers on "are the plan hooks set up", "install the commit gate", "check the stop hook", "clean up the hook entries".
disable-model-invocation: true
---

# /hooks

The planning plugin's three Cursor hooks ship in the plugin's own `hooks/hooks.json`,
so installing the plugin wires them. Nothing goes in `~/.cursor/hooks.json`:

| Event | Script | What it does |
|---|---|---|
| `stop` (`loop_limit` 25) | `hooks/plan-continue.sh` | keeps a plan in flight running across turn ends |
| `preToolUse`, matcher `Task` | `hooks/dispatch-log.sh` | logs each subagent launch of a plan run |
| `beforeShellExecution` | `hooks/commit-gate.sh` | keeps the proof-record git hook on |

One more hook is per project: the git hook that checks proof records. This skill runs
the installer for all of it, from the plugin root:

```
python3 scripts/hooks-install.py --status              report the wiring (exit 0 clean, 1 not)
python3 scripts/hooks-install.py --install [--dry-run] clear leftover entries; writes no new ones
python3 scripts/hooks-install.py --install --repo <dir> install the proof-record git hook
python3 scripts/hooks-install.py --status --repo <dir>  is it installed there
```

Map the user's words to one of these and report the script's own output.

## Why nothing goes in ~/.cursor/hooks.json

Cursor runs the plugin's `hooks.json` wherever the plugin is installed, and it also runs
any entry for the same script in `~/.cursor/hooks.json`. With both, one call fires the
hook twice: two dispatch lines for one launch, two follow-ups for one turn end. So each
event has one route, the plugin's. An older installer wrote user entries; `--status`
names any it finds, and `--install` removes them, touching nothing else in that file. A
file it cannot parse makes it exit 1 without writing; a file it rewrites is backed up
beside it first.

Cursor never sends `subagentStart` or `subagentStop`, so the dispatch log runs before
each `Task` call instead and logs dispatches only.

## The stop hook

On Cursor an assistant message ends the turn, so a run that narrates "Continuing Stage
3…" stops and waits for you. While a plan is in flight, the `stop` hook answers with a
`followup_message`, which Cursor submits as the next user message, so the run goes on
without you typing "carry on".

**It fires only in an interactive session.** A headless `cursor-agent -p` run never
calls `stop`, so it gets no continuation: drive a headless run one prompt at a time.

It reads `<repo>/.claude/plan-progress.json` (the repo of the workspace's first root)
and lets the turn end when:

| Condition | Behaviour |
|---|---|
| no state file, or the plan finished | turn ends normally |
| phase `blocked`, `closeout` or `handoff`, or a recorded blocker | turn ends, on purpose |
| the agent loop ended `aborted` or `error` | turn ends — it never fights an interrupt |
| state older than 12 h, or a timestamp in the future | turn ends |
| 25 continuations with no movement past one task | turn ends so you can look |
| `CURSOR_PLAN_CONTINUE=0` in Cursor's environment | disabled |
| anything unexpected — bad JSON, unreadable state | turn ends |

It reads no message text: a handoff note in the message does not end the run; the
`handoff` phase does. It fails open on every path and always exits 0. Cursor's own
`loop_limit` (25 here) is a second, independent bound. When a stage is marked done but
has no `Stage N green` commit, the follow-up says to run the gate.

Because it ships with the plugin, it is live in every interactive session whose repo
has a plan in flight — a second chat in the same repo is pushed to continue too. Set
`CURSOR_PLAN_CONTINUE=0` for a session that should not be.

## The commit gate

Proof is checked once per stage. A `Stage N green` commit needs a `prove-claim.py`
record for every claim of every task of stage N, bound to the code it commits. Task
commits carry code only. The check is git's `reference-transaction` hook
(`hooks/git-ref-gate.sh`), installed per repo with `--install --repo`: git runs it
whenever a branch moves — `--no-verify`, amend, cherry-pick and plumbing included — and
it refuses a `Stage N green` commit of the plan in flight that lacks a valid record,
listing what is missing. A claim deviation (`prove-claim.py deviation --claim`) is a
valid record, named on stderr, never proof. A commit already reachable from a branch or
a remote-tracking ref is not checked.

Proof is on by default. While a plan is in flight, `hooks/commit-gate.sh` denies:

- a command mentioning `hooksPath` (the one way to point git elsewhere);
- a command naming the hook file, other than the installer;
- the installer's `--remove` — switching the gate off is your call, made in your own
  terminal;
- any git command while the git hook is not installed in that repo, naming the
  `--install --repo` command that installs it.

With no plan in flight it denies one command: a git commit whose text names
`Stage N green`, since a stage closed with no execution state could never be checked. The
deny names `plan-state.py init`; the git hook, where installed, refuses the same commit
when its message comes from a file.

These are text rules, a rail and not a sandbox. The installer refuses to replace another
`reference-transaction` hook, and refuses a hooks directory outside the repo (a shared
`core.hooksPath` would gate every repo using it). If the plugin copy the shim points at
is gone, the shim lets every update through and says the gate is OFF: re-run
`--install --repo`.

The gate fails open on its own errors, except one: when its check of the repo's hooks
directory errors or times out, it cannot tell whether the gate is installed and denies
git. `CURSOR_COMMIT_GATE=0` in Cursor's environment disables the Cursor half.

## With the Claude Code planning plugin installed too

Cursor also runs a Claude Code plugin's hooks. The Claude Code planning plugin's hooks
see Cursor's payload (it carries `cursor_version`) and step aside, so only these Cursor
hooks answer a Cursor session.

## What it will not touch

`~/.cursor/cli-config.json`: the status line lives there and belongs to `/plan-statusline`.
