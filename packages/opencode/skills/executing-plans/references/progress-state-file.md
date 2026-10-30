# Progress state file

`<repo-root>/.claude/plan-progress.json` is the run's execution state. On OpenCode nothing
draws it: OpenCode has no status line, so the core plugin's status-line bar, its installer
and the Claude Code band have no OpenCode surface, and this package ships none of them. The
file is still written at every transition, because it is the recoverable execution state:
the gate checks, the next session and any reader learn from it where the run got to.

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
| A handoff at a gate | `set-blocker` | the five Stop-condition fields with disposition `handoff`, plus the measured `reason` (no `handoff_id`: OpenCode ships no handoff envelope to mint one) |
| Close-out starts | `transition` | `{"phase": "closeout"}` |
| Close-out's last step | `finish` | `{"evidence": "<the Completed line and its commit>"}` |

`show` (payload `{}`) prints the state and needs neither option.
Readers (the gate checks, the next session) consume phase/task/plan projections and
structured blocker metadata.
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
| The executor stops at a stage gate on a `handoff` verdict from `context-usage.py` | `phase: "handoff"`, `stage`, `reason` (that script's `reason:` text verbatim, e.g. "context 52% > 50%") |
| Close-out finishes (last step) | **delete the file** |

Schema (all on one line is fine):

```json
{"plan": "plans/foo-plan.md", "phase": "task", "stage": 2,
 "task": "2.3", "task_desc": "parse config entries",
 "updated": "<ISO-8601 UTC now>"}
```

`plan` is the plan file's path — absolute, or relative to the repo root.
Always refresh `updated` from the clock, never a placeholder: it is the next reader's only
record of when the run last moved. Nothing on OpenCode acts on its age.

`remediation_round` is optional and only meaningful with `phase: "gate"` — set it
when a gate is being re-run after a failure, so a loop that is quietly on its third
round is visible in the file rather than inferred. Omit it on a gate's first run.
`remediation_budget` is likewise optional and only changes the denominator.

`reason` is only meaningful with `phase: "handoff"`. Copy it verbatim from the `reason:`
line `context-usage.py` printed with its `handoff` verdict — do not paraphrase it, because it
is the one record of which measured rule fired. OpenCode draws no bar, so the field is read
by the next session and anyone who opens the file:

```json
{"plan": "plans/foo-plan.md", "phase": "handoff", "stage": 2,
 "reason": "rule context: now=…", "updated": "<ISO-8601 UTC now>"}
```

## Readers on OpenCode

**No Stop hook reads it.** On a host with a Stop hook, `phase` decides whether a plan is in
flight and the hook continues a run that ends its turn early. OpenCode has no such hook
(`plan-continue-hook.md`), so a state write records where the run stands and never holds or
resumes the session. The `phase` values stay a contract all the same — `blocked`,
`closeout` and `handoff` are what a stop on purpose looks like to the next reader, and a
placeholder or hand-written `updated` misdates the run for that reader.

**The gate checks.** The package's `../scripts/plan-progress.py` is the core script without
its status-line renderer: it implements `--budget-check`, `--stage-order-check` and
`--dispatch-check`, and draws nothing. `--budget-check` reads the remediation accounts this
file records, so recording each round accurately is not bookkeeping on OpenCode: it is the
input to the one check that can stop a runaway remediation loop. Run it from the repo root by
the package path, and read it by what it printed (`gate-failure-procedure.md` § The read-only
budget projection). None of the core's bar markers (`⊘ GATE BLOCKED`, `⚠ status lag`,
`⊘ STAGE ORDER`, `↻N/M`, `⏸ HANDOFF`) is drawn here; `--stage-order-check` exits 2 with its
reason printed on the condition `⊘ STAGE ORDER` would show.

**The todo list — only when this session has the `todowrite` tool.** Where it is listed,
mirror each transition this file records into it — task start, task green, gate open, gate
green, close-out — with the current stage's tasks as its items. It is a tool call, so it
leaves the turn running, like the state write beside it. Where it is not listed, the state
file and the plan's `Status:` fields stay the record; never post the count as a message
instead.

Done/total counts are **not** in the file — they come from the plan's authoritative `Status:`
fields, so a forgotten update can never record wrong progress, only a wrong current-task
label. The file is private local derived state: never commit it — during the git bootstrap,
ensure `.claude/plan-progress.json` is gitignored (append it if the repo doesn't already
ignore it), together with `.claude/dispatch-log.jsonl`, which the package's dispatch logger
appends to while a plan is in flight (`prove-claim.py` does not count untracked files in the
top-level `.claude/`, so this is hygiene, not a proof prerequisite). For a master plan, the
state file always points at the **sub-plan** currently executing.

**Not shipped here:** the status-line renderer, its installer and chain script, the
Claude Code band and `/plan-view`, and the live-window sidecar `.claude/plan-context.json`
that only the Claude Code planning mod writes. There is nothing for a user to install.
