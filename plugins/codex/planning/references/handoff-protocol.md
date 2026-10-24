# The planning handoff protocol

A long plan run hands off to a fresh session at a stage gate. Without a supervisor, a
person resumes it by hand. With one, the supervisor learns that a handoff is ready,
starts the fresh session, and learns whether it took the plan. This page is the contract
between planning and any supervisor. planning implements its side in
`skills/executing-plans/scripts/handoff-envelope.py`; nothing here depends on a
particular supervisor.

Protocol id `planning-handoff`, version `1`.

## The channel

Every file lives in `<root>/.claude/handoffs/`, where `<root>` is the project's git top
level (the handoff root). Callers pass it as `--root`; `handoff-envelope.py` trusts that
argument and does not look the root up itself. planning keeps `.gitignore` there holding exactly `*`, so no
envelope is ever committed.

| File | Written by | Meaning |
|---|---|---|
| `<id>.ready.json` | the session handing off | `HANDOFF_READY`: the plan's `RESUME HERE` block names this id |
| `<id>.accepted.json` | the fresh session | `HANDOFF_ACCEPTED`: it verified the handoff and owns the plan |
| `<id>.failed.json` | the fresh session | `HANDOFF_FAILED`: it could not take the plan; `failure_code` says why |
| `request.json` | the supervisor | the owner asks this session to hand off at its next gate |

A handoff id matches `^h-[0-9a-f]{20}$`. One id has one outcome: `accepted` and `failed`
each claim the id first by creating the empty file `.<id>.claim`, so a second outcome for
the same id is refused. A supervisor listing the directory sees these dotfiles too.

## Envelopes

Every envelope is one JSON object with exactly these keys:

```json
{"protocol": "planning-handoff", "version": 1, "event": "HANDOFF_READY",
 "handoff_id": "h-0123456789abcdef0123", "managed_session_id": "<session id>",
 "timestamp": "2026-01-01T00:00:00Z", "plan": "/abs/path/to/plan.md"}
```

- `event` is `HANDOFF_READY`, `HANDOFF_ACCEPTED` or `HANDOFF_FAILED`.
- `managed_session_id` is the id the supervisor gave the writing session (see
  **Identity**): 1–128 characters of `[A-Za-z0-9_-]`.
- `timestamp` is UTC, `YYYY-MM-DDTHH:MM:SSZ`.
- `plan` is an absolute path. In a `failed` envelope it may be `null`.
- A `failed` envelope adds `failure_code`: `no-ready`, `plan-missing`, `id-mismatch`,
  `cwd-mismatch` or `branch-mismatch`.

`request.json` is `{"protocol": "planning-handoff", "version": 1, "managed_session_id":
"<session id>", "requested_at": "<UTC timestamp>"}`. It is honoured only when its
`managed_session_id` is the reading session's own id.

A reader refuses, and treats as absent: a link, anything but a regular file, more than
4096 bytes, invalid JSON, another protocol id, another version, or an invalid id.

## Identity

planning never reads a session id from the environment: an inherited variable would
name the wrong session in a child process or a copied shell. It asks the supervisor.

- The supervisor sets `PLANNING_SUPERVISOR_ID_CMD` in the managed session's environment,
  to a command line. planning splits it with shell rules (`shlex`) and runs it with no
  shell, in a new session: no controlling terminal, stdin from `/dev/null`, stderr
  discarded. A command that needs a terminal therefore fails, and the session is
  unsupervised.
- The command must exit 0 within 5 seconds and print exactly one line, at most 256 bytes:
  the session's id. The final newline is optional; a carriage return, a second line or
  surrounding spaces make the output invalid.
- The 5 seconds bound the whole call, reading included. At the bound planning kills the
  command's process group and discards its output. A descendant that left that group
  (with `setsid`, say) is not waited for, and may outlive the call.
- Anything else means **unsupervised**: the variable is unset or blank, the command
  cannot start, exits non-zero, times out, or prints more than one line or an invalid id.

The command runs with `PLANNING_HANDOFF_ROOT` set in its environment to the call's resolved
root (the `--root` after `realpath`): the root where the envelope is written or the request
read. Its arguments and working folder are unchanged. A supervisor may record that root as
where this session's envelopes appear; one that ignores it loses nothing. The root travels
in the environment, not as an argument, so a command that takes no arguments still works.

Unsupervised, `ready`, `accept` and `fail` write nothing, print `unsupervised` and exit
0. The handoff id still goes in the plan's `RESUME HERE` block and the state file, and a
person resumes by hand. An unset or blank variable is silent. A command that is set but
gives no id is reported in one line on stderr, so a broken supervisor setup shows:
`PLANNING_SUPERVISOR_ID_CMD is set but gave no session id: <reason>`, where the reason is
`cannot start`, `exit N`, `timed out` or `no single valid id line`. `request-pending`
reads `request.json` first and runs the command only when a valid request is there.

## The sequence

1. At a gate, the session handing off mints an id, writes it into the plan's
   `RESUME HERE` block and `.claude/plan-progress.json`, then writes `<id>.ready.json`.
2. The supervisor starts a fresh session in the same project and sends it the
   executing-plans skill's adopt-handoff entry with `<id>` (on Claude Code,
   `$planning:executing-plans --adopt-handoff <id>`).
3. The fresh session checks the handoff (`verify`): the `ready` envelope exists for this
   id, the plan is readable, the plan's last `RESUME HERE` block names this id, its `cwd:`
   is the handoff root and its `branch:` is the current branch. It then writes `accepted`,
   or `failed` with the first failing check as `failure_code`.
4. Only after `accepted` does the supervisor stop the old session.

To ask for a rollover, the supervisor writes `request.json`. The session reads it at its
next stage gate and hands off there.

## Exit codes of `handoff-envelope.py`

| Code | Meaning |
|---|---|
| 0 | done (including `unsupervised`); `verify` passed; `request-pending` found a request |
| 1 | a write was refused (a link, wrong owner, or an id already claimed); `request-pending` found none |
| 2 | bad arguments |
| 3 | `verify` failed (the failure code is printed); `plan` found no `ready` envelope |
