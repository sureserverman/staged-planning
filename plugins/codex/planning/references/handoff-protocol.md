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
each claim the id first by linking `.<id>.claim` to a temp file holding the whole outcome,
so the claim appears complete or not at all and a second outcome for the same id is refused.
A writer killed after claiming left its outcome there. The next writer publishes those bytes,
so the reader learns the outcome, and succeeds only if it asked for that same outcome,
timestamp aside, whether or not it was already published; any other session, plan, event or
code is refused. A filesystem without hard links gets an exclusive create instead of each link,
which a kill can leave partial; a partial claim refuses later writers. An empty claim from an
older writer still refuses. A supervisor listing the directory sees these dotfiles too, and a
kill can leave a `.tmp` dotfile, which is never an outcome. A claim outlives its outcome, so
a supervisor that deletes a consumed outcome can see a late writer publish it again; correlate
by id and ignore an outcome for a handoff already settled. An envelope over the 4096-byte read limit is refused before anything
is written, with its size and the limit on stderr.

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


## Version 2: explicit destinations (reader-first deployment)

Version 1 above remains the exact same-root contract. A supervisor supporting both
versions advertises `PLANNING_HANDOFF_VERSIONS=1,2` to newly launched sessions. With
no advertisement a writer uses v1. An old reader refuses version 2; deploy the
new reader before enabling cross-root writing. Missing v2 capability on a cross-root
request means `manual-continuation` (exit 3), with no envelope and no fallback launch.
Cursor and OpenCode do not gain supervisor support from this protocol extension.

The channel always belongs to the **source root**. All ready, accepted and failed
files for one id remain in that root's `.claude/handoffs/`, even when the successor
runs elsewhere. The predecessor's identity is obtained there before publication. Its owned state
must already be held with disposition `handoff` and this exact `handoff_id`; a
runnable predecessor or an unrelated hold cannot publish v2 ready.
`PLANNING_HANDOFF_ROOT` still names that source channel; it does not change cwd.
The supervisor maps the frozen destination root to a registered project/worktree.
It must refuse unknown or ambiguous mappings, never register or fall back implicitly.

A v2 `HANDOFF_READY` has exactly the seven v1 common keys plus `source_root`,
`source_plan`, `predecessor_session_id`, `destination` and `selection`:

```json
{"protocol":"planning-handoff","version":2,"event":"HANDOFF_READY",
 "handoff_id":"h-0123456789abcdef0123","managed_session_id":"source-session",
 "timestamp":"2026-01-01T00:00:00Z","plan":"/records/next-plan.md",
 "source_root":"/work/orchard","source_plan":"/records/current-plan.md",
 "predecessor_session_id":"source-session",
 "destination":{"root":"/work/river","branch":"feature",
   "plan":"/records/next-plan.md","locator":"Task 1.1",
   "master_plan":"/records/journey-master-plan.md"},
 "selection":{"boundary":true,"subplan":2,"current_subplan":1}}
```

All paths are canonical absolute paths; `destination.master_plan` is null for a
standalone plan. `plan` equals `destination.plan`. A branch and an exact task locator
are mandatory. `selection.subplan` is the explicitly chosen executable entry or null;
`selection.current_subplan` names the completed current entry at a boundary (otherwise null);
`selection.boundary` says whether to resolve the next master entry. The source plan's
last RESUME HERE block names this id, destination `cwd:`/`branch:`, destination
`plan:` and `next: Task N.M`. It is the authoritative continuation checkpoint.

Use `ready --root SOURCE --plan SOURCE_PLAN --next 'Task N.M'`, with
`--sub-plan-boundary` and optional `--subplan N` at a master boundary.
When SOURCE_PLAN is the master itself, `--current-subplan N` is mandatory; it
names the completed current entry and is checked just like a sub-plan source. This resolves
and freezes the destination once. Reusing an id cannot change its destination or
predecessor. A restarted writer must reuse the existing ready envelope, not recompute
a new target under the same id. A plan change that disagrees with the frozen record
is a visible refusal, including a later edit of execution metadata.

Adoption receives `--handoff-root SOURCE` alongside `--adopt-handoff ID`. In the
helper CLI use `--root DESTINATION --handoff-root SOURCE` for `plan`, `verify`,
`accept` and `fail`. These are structured arguments, never shell fragments, and
never change the target working directory. Verification requires the actual cwd
and checked out Git branch to equal the frozen destination; the source plan, id,
resume plan, next locator, master linkage and resolved metadata must still agree.
Version mismatches, oversized records and stale metadata refuse without state writes.
The 4096-byte channel bound applies before publication as well as during reads.

A v2 accepted/failed outcome copies the ready record's destination, selection,
source paths and predecessor id, replaces `event`, `managed_session_id` and
`timestamp`, and adds `ready_sha256` (the SHA256 of the canonical sorted compact JSON
ready object). A failed outcome also adds `failure_code`. An outcome claims the same
source id once. Both acceptance and failure require the actual cwd and supplied
target root to equal the frozen destination, and a managed identity distinct from
the predecessor; the predecessor cannot terminate its own adoption outcome. A failure preserves the predecessor; only verified acceptance permits
its supervisor to stop it. A missing/malformed ready may be reported with the v1
`no-ready` failure, which carries no unverified destination data.

The adopting session initializes or resumes **destination-owned** state through
`plan-state.py`. It must obtain its authority from the actual owner's plan scope and
instructions, and re-read the parent master's constraints. It never copies the source
snapshot, authorization digest, run id, receipts or common-directory pointer. A target
already owned by a different run holds for explicit resolution. Acceptance follows
verification and successful destination ownership; ownership failure writes a correlated
failure, not acceptance. The envelope itself grants no authority.

### Execution metadata and selection

A sub-plan may declare, above its first level-two heading:

```text
Execution root: `/work/river`
Execution branch: `feature`
```

A master entry may declare the same pair as `- **Execution root:**` and
`- **Execution branch:**` fields. Each declaration must contain both fields;
if both entry and sub-plan declare it they must agree. The root must exist and be
the exact Git top level, including an already registered worktree; its current branch
must match. A plan's directory is never an execution root. Only a legacy plan with
neither declaration retains the supplied current root and branch.

At a sub-plan boundary the current entry must be completed, its sub-plan have a
Completed marker and green tasks/gates, and its master integration gates be green.
Completed dependency entries must satisfy those checks too. Select an unfinished
entry only when all dependencies are green; multiple eligible entries require an
explicit selection. Unknown dependencies, incomplete master gates, blocked/cancelled
runs and missing destinations refuse. No executable entry is a hold when unfinished
entries remain. All entries closed is distinct from whole-master close-out.

### Finished requests

A v2 supervisor request has exactly `protocol`, `version`, `managed_session_id`,
`requested_at` and `request_id` (the handoff-id syntax). Once the requested session's
entire single/master workflow and close-out are complete, `finished --root SOURCE
--plan PLAN` may write `<request_id>.finished.json`, event `HANDOFF_FINISHED`,
version 2, outcome `completed`. It has the seven common keys plus `source_root`,
`request_id`, `requested_at` and `outcome`; `handoff_id` equals `request_id`.
It answers that exact request only. No request or a request for another session
writes nothing. A sub-plan with an executable successor, an unfinished dependency,
a pending gate, or cancelled/failed execution cannot emit successful completion.
A replay reuses the same outcome; it creates no successor. Completion consumption
is a receiver obligation, separate from writer support.

The writer requires the Git/worktree's own validated execution state to name the
supplied plan and carry terminal `complete`/`closeout`. A single plan has a visible
Completed marker and every task and gate green. A master additionally requires all
registered sub-plans to have matching backlinks, Completed markers and green tasks
and gates, all entry integration gates green, and its own Completed marker. Blocked
acceptance and abandonment do not qualify as successful completion. For a sub-plan,
its parent master is checked too. Finish writes no state and never clears a request.

The outcome is published exclusively and atomically; a replay must match all fields
except its original timestamp. A conflicting or unreadable existing outcome is a
`stale-finished` refusal (exit 3), never overwritten. `oversized-envelope`, `workflow-incomplete`,
`run-not-runnable`, `state-ownership` and metadata refusal codes also exit 3.
`no-request` exits 0 with no file when there is no valid v2 request naming this
session, including legacy v1 requests. A receiver must correlate the request id,
requested_at, managed session id and source root before consuming completion; it
must not treat an older request's outcome as an answer to a newer request.
Completion integration remains unfinished until the receiving supervisor consumes this outcome.
