# Progress state file

`<repo-root>/.claude/plan-progress.json` is the run's execution state. On Codex nothing
draws it: Codex's status line takes only predefined items and runs no command, so the core
plugin's status-line bar, its installer and the Claude Code band have no Codex surface, and
nothing here runs them. The file is still written at every transition, because the Stop hook, the
gate checks and the next session read it to learn where the run got to.

Every run is an owned v2 run, started by `init` at Preflight. The
[execution-state contract](execution-state-contract.md) operations are the only writers.
Keep the snapshot after finish; deleting it loses the owning pointer's required evidence.

## When to call each operation

Run `echo '<payload>' | python3 <planning-plugin>/skills/executing-plans/scripts/plan-state.py <op> --repo <repo root> --expected-revision <N> --operation-id <id>`.
`N` is the `revision` of the last receipt (0 for `init`). Make each `id` new and
descriptive (`s2-t2.3-start`). Re-sending the same id and payload after a lost reply
returns the original receipt.

| When | Operation | Payload |
|------|-----------|---------|
| Preflight starts, on the run's branch (after git bootstrap's branch or worktree) | `init` | `{"plan": "<plan path>", "source": "<the owner's request, quoted>", "scope": "plan"}` (optional `budget`, the plan's remediation budget) |
| A stage opens (Step 3.0, before its first task) | `transition` | `{"phase": "task", "stage": 2}` — no task, so `owner-decision.py match` reads the stage the run is in, not the last gate |
| A task starts | `transition` | `{"phase": "task", "stage": 2, "task": "2.3", "task_desc": "<title>"}` |
| A stage gate runs | `transition` | `{"phase": "gate", "stage": 2}` |
| A remediation round starts, is verified, ends | `begin-round`, `record-verification`, `complete-round` | see the contract; the gate must first be named in a `transition` `gate` field |
| A Stop condition halts execution | `set-blocker` | `disposition`, `prevented_operation`, `evidence`, `dependency`, `remaining_work` (contract) |
| A handoff at a gate | `set-blocker` | the five Stop-condition fields with disposition `handoff`, plus the measured `reason` and the minted `handoff_id` |
| Close-out starts | `transition` | `{"phase": "closeout"}` |
| Close-out's last step | `finish` | `{"evidence": "<the Completed line and its commit>"}` |

`show` (payload `{}`) prints the state and needs neither option.
Readers (the Stop hook, the gate checks, the next session) consume phase/task/plan
projections and structured blocker metadata.
Do not manually edit its schema, counters, authority or progress receipts.

## Unowned legacy display format (historical compatibility)

The table below describes existing unowned legacy files, not how to write a v2 run.
Migration requires original gate evidence. Legacy-only overwrite/delete instructions
never apply to an owned snapshot.

Historical legacy display transitions:

| When | Write |
|------|-------|
| Preflight starts | `phase: "preflight"` |
| A task starts (incl. re-entering its Red-Green loop) | `phase: "task"`, `stage`, `task` ("2.3"), `task_desc` |
| A stage gate runs | `phase: "gate"`, `stage`, and on a re-run `remediation_round` (+ `remediation_budget` if the plan overrode the default 2) |
| Close-out starts | `phase: "closeout"` |
| A Stop condition halts execution | `phase: "blocked"`, `stage`/`task` if known, `note` (one line, e.g. "cycle budget exhausted") |
| The executor stops at a stage gate on a `handoff` verdict from `context-usage.py` | `phase: "handoff"`, `stage`, `reason` (that script's `reason:` text verbatim, e.g. "context 52% > 50%"), `handoff_id` (the id minted in `session-handoff.md` § On `handoff` step 0, verbatim) |
| Close-out finishes (last step) | **delete the file** |

Schema (all on one line is fine):

```json
{"plan": "plans/foo-plan.md", "phase": "task", "stage": 2,
 "task": "2.3", "task_desc": "parse config entries",
 "updated": "<ISO-8601 UTC now>"}
```

`plan` is the plan file's path — absolute, or relative to the repo root.
Always refresh `updated` from the clock, never a placeholder: a reader marks state older
than 12h as stale, and on Codex the Stop hook then stops continuing the run.

`remediation_round` is optional and only meaningful with `phase: "gate"` — set it
when a gate is being re-run after a failure, so a loop that is quietly on its third
round is visible in the file rather than inferred. Omit it on a gate's first run.
`remediation_budget` is likewise optional and only changes the denominator.

`reason` and `handoff_id` are only meaningful with `phase: "handoff"`. Copy `reason`
verbatim from the `reason:` line `context-usage.py` printed with its `handoff` verdict — do
not paraphrase it, because it is the one record of which measured rule fired. Codex
draws no bar, so the field is read by the Stop hook, the next session and anyone who opens
the file.
Copy `handoff_id` verbatim from step 0's `handoff-envelope.py new-id` output — the same id
the `RESUME HERE` block and the `ready` envelope carry:

```json
{"plan": "plans/foo-plan.md", "phase": "handoff", "stage": 2,
 "reason": "rule requested: owner asked for a rollover",
 "handoff_id": "h-0123456789abcdef0123", "updated": "<ISO-8601 UTC now>"}
```

## Readers on Codex

**The Stop hook.** The plugin's Stop hook (`plan-continue-hook.md`) reads an owned run's
`disposition` to decide whether to continue it: `working` and `repairing` continue at every
phase, and a recorded blocker, owner decision, handoff or `finish` lets the turn end. On a
legacy state file it reads `phase` instead, where `blocked`, `closeout` and `handoff` let a
run stop on purpose. Either way a placeholder or hand-written `updated` reads as stale by
design. Codex runs a plugin hook only
after the user has trusted it in `/hooks`; until then nothing continues the run, and the
file is read only by the gate checks and the next session.

**The footer's task count — only when `update_plan` is listed.** Codex's footer can show
`Tasks n/m` from the `update_plan` tool, through its `task-progress` status-line item. The
tool is off by default; turning it on is the user's choice, in their Codex config:

```toml
[tools.update_plan]
enabled = true
```

and the count shows only when `task-progress` is also in their `tui.status_line` list. This
plugin never writes that config.
- **When `update_plan` is in this session's tool list**, call it at every transition this file
  records — task start, task green, gate open, gate green, close-out — with the current
  stage's tasks as its steps: `in_progress` on the task being executed, `completed` on each
  green one, the stage named in the explanation. It is a tool call, so it leaves the turn
  running, like the state write beside it.
- **When it is not listed, skip this rule.** Nothing draws the count; the state file and the
  plan's `Status:` fields stay the record. Never post the count as a message instead: that is
  noise in the turn, not a substitute.

Done/total counts are **not** in the file — they come from the plan's authoritative `Status:`
fields, so a forgotten update can never record wrong progress, only a wrong current-task
label. The file is private local derived state: never commit it — during the git bootstrap,
ensure `.claude/plan-progress.json` is gitignored (append it if the repo doesn't already
ignore it), together with `.claude/dispatch-log.jsonl`, which the plugin's dispatch-log hook
appends to while a plan is in flight (`prove-claim.py` does not count untracked files in the
top-level `.claude/`, so this is hygiene, not a proof prerequisite). For a master plan, the
state file always points at the **sub-plan** currently executing.
