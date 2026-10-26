# Progress state file (live statusline bar)

Mirror execution state to `<repo-root>/.claude/plan-progress.json` so the
shipped statusline renderer (`../scripts/plan-progress.py`) can draw a live
progress bar (`⚙ plan ▐██████░░░░▌ 3/6 (50%) · S2/3 ▶ T2.2 …`). Maintain the
file on every run — it is cheap, and the renderer simply never fires for
users who haven't wired it.

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
| A task starts | `transition` | `{"phase": "task", "stage": 2, "task": "2.3", "task_desc": "<title>"}` |
| A stage gate runs | `transition` | `{"phase": "gate", "stage": 2}` |
| A remediation round starts, is verified, ends | `begin-round`, `record-verification`, `complete-round` | see the contract; the gate must first be named in a `transition` `gate` field |
| A Stop condition halts execution | `set-blocker` | `disposition`, `prevented_operation`, `evidence`, `dependency`, `remaining_work` (contract) |
| A handoff at a gate | `set-blocker` | the five Stop-condition fields with disposition `handoff`, plus the `reason` (on Cursor, the dated check rule 5 quotes; no `handoff_id` is minted here, `session-handoff.md`) |
| Close-out starts | `transition` | `{"phase": "closeout"}` |
| Close-out's last step | `finish` | `{"evidence": "<the Completed line and its commit>"}` |

`show` (payload `{}`) prints the state and needs neither option.
The renderer reads phase/task/plan projections and structured blocker metadata.
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
| The executor stops at a stage gate on a `handoff` verdict (on Cursor only rule 5, a dated wait, gives one: `context-usage.py` does not ship) | `phase: "handoff"`, `stage`, `reason` (the `reason:` text verbatim — on Cursor the dated check, quoted) |
| A stage's gate passed, its `Stage N green` commit landed, and the run stops there because the user asked it to | `phase: "stage-complete"`, `stage` |
| Close-out finishes (last step) | **delete the file** |

**A stage is done only when its `Stage N green` commit exists.** While this file names a
stage with phase `stage-complete` or `closeout`, or with any other phase outside
`preflight`, `task` and `gate` while the plan's `### Stage N Gate` boxes for that stage are
ticked, the Cursor `stop` hook does not let the turn end until HEAD's history has
`Stage N green`, the commit the git hook refuses without every task's proof records. It asks
`../scripts/plan-flip-audit.py`'s `unrecorded_gate()`, so the hook and the audit agree. In
`preflight`, `task` and `gate` the plan is in flight and a completed stop continues anyway.
`blocked` and `handoff` are recorded stops and are never held.

Schema (all on one line is fine):

```json
{"plan": "plans/foo-plan.md", "phase": "task", "stage": 2,
 "task": "2.3", "task_desc": "parse config entries",
 "updated": "<ISO-8601 UTC now>"}
```

`plan` is the plan file's path — absolute, or relative to the repo root.
Always refresh `updated` (the renderer marks state older than 12h as stale).

`remediation_round` is optional and only meaningful with `phase: "gate"` — set it
when a gate is being re-run after a failure, so the bar reads
`◆ S2 gate ↻2/2` and a loop that is quietly on its third round is visible rather
than inferred. Omit it on a gate's first run. `remediation_budget` is likewise
optional and only changes the denominator; with neither field the gate renders
with no `↻` marker.

`reason` is only meaningful with `phase: "handoff"`. Copy it verbatim from the handoff's
`reason:` line — on Cursor the dated check rule 5 quotes — and do not paraphrase it, because
it is the one record of which rule fired. The bar renders it after `⏸ HANDOFF`, clipped to
the same width as a `blocked` note. The `handoff_id` other hosts write here comes from
`handoff-envelope.py`, which does not ship on Cursor, so a Cursor handoff carries none:

```json
{"plan": "plans/foo-plan.md", "phase": "handoff", "stage": 2,
 "reason": "rule 5: gate check 3 cannot run before 2026-11-01 (store review)",
 "updated": "<ISO-8601 UTC now>"}
```
**Markers the bar can append**, so an operator who sees one has somewhere to read:

| Marker | Means |
|---|---|
| `⊘ GATE BLOCKED` | a stage-gate check in the plan is `[~]` — a check that could not be run. Rendered on the executing bar and on a discovered plan's bar alike, because a blocked plan is blocked for whoever looks next. Never affects done/total: the counts are about tasks. |
| `⚠ status lag N` | the plan file's `Status:` markers trail the task this state file names by N sequential tasks. `Dispatch: YES` siblings are excluded — they are dispatched together and do not finish in document order. `[~]` counts as a marker that moved. |
| `⚠ not in plan` | this file names a task the plan does not contain. A worse divergence than a lag: the plan was edited under a run whose markers had already stopped. |
| `⊘ STAGE ORDER` | this file's `stage` depends (its `**Depends on:**` line) on a stage whose gate is not fully `[x]` — an open `[ ]` or a blocked `[~]`. The stage opened too early; `python3 <planning-plugin>/skills/executing-plans/scripts/plan-progress.py --stage-order-check`, run from the repo root, exits 2 on the same condition, with its `FAIL:` reason printed. An exit 2 without one is a **BROKEN INVOCATION** (Python exits 2 when it cannot open the file), not a result. |
| `↻N/M` | a gate being re-run after a failure; see `remediation_round`. |
| `⏸ HANDOFF` | the executor stopped on purpose at a stage gate because a stop rule fired (on Cursor, rule 5's dated wait). Followed by `reason`. Not a failure: the next session resumes from the plan's `**RESUME HERE (<date>):**` block. |

**One front end draws it on Cursor: the status-line bar.** The band over the prompt and the
plan pane that Claude Code draws are a Claude Code mod; Cursor has no such surface, so they
do not ship here. `../scripts/plan-progress.py --json` still prints the band's model, and
nothing on Cursor reads it.

**The renderer is not the file's only automated reader.** `../../../hooks/plan-continue.sh`
— the `stop`-hook backstop, wired by the plugin's `hooks/hooks.json` and run in interactive
sessions — reads
an owned run's `disposition` to decide whether to continue it (`working` and `repairing`
continue at every phase; a recorded blocker, owner decision, handoff or `finish` lets the
turn end). On a legacy state file it reads `phase`: `blocked` and `handoff` let a run stop
on purpose, and `closeout` and `stage-complete` stop it only once that stage's
`Stage N green` commit exists. That is why these fields are a contract and not a label, and
why a placeholder or hand-written `updated` reads as stale by design. See
`plan-continue-hook.md`.

Done/total counts are **not** in the file — the renderer derives them from the
plan's authoritative `Status:` fields, so a forgotten update can never show
wrong progress, only a wrong current-task label. The file is private local derived
state: never commit it — during the git bootstrap, ensure
`.claude/plan-progress.json` is gitignored (append it if the repo doesn't
already ignore it), together with `.claude/dispatch-log.jsonl`, which
`../../../hooks/dispatch-log.sh` appends to on each subagent launch while a plan is in flight (`prove-claim.py` does not count untracked files in the top-level `.claude/`, so this is hygiene, not a proof prerequisite). For a master plan, the state file always points at the
**sub-plan** currently executing.

**One-time user setup** (only if asked to wire it): run `/plan-statusline install`, the
Cursor-only `plan-statusline` skill. That command is the invocation — do not hand a user a
relative `../scripts/…` path, which resolves only when the shell's cwd happens to be this
file's own directory and fails everywhere else. It writes the single `statusLine` entry in
`~/.cursor/cli-config.json` pointing at the shipped `statusline-chain.sh`; that script runs
the user's existing statusline command first and appends this renderer's output on the next
line when non-empty, both from the same stdin JSON. `status` reports what is wired; `remove`
takes it back out.

**Installing the bar costs Cursor's own footer.** A configured `statusLine` *replaces*
Cursor's native footer rows rather than adding one — the model and context readout, the
working directory, branch and PR indicators go while the bar is wired, and there is no
append mode. `remove` restores them. Say this before wiring anything: a user who asked for a
progress bar did not ask for that trade. The chain can keep a statusline command the user
configured, but the native footer is not a command and nothing can chain it.

**What "existing statusline" covers.** The installer preserves a displaced entry as the
chain's base only when it is a plain `bash <script>` invocation, which it records as a
`PLAN_STATUSLINE_BASE=<path>` prefix on the written command. A `node`/`deno`/`bun`
command, a pipeline, or a `bash` call carrying its own arguments cannot be chained
safely: without `--force` the install refuses, and with `--force` the old command is
replaced, echoed to stderr, and left in the timestamped backup. One shape is refused
deliberately even though it parses — a base script that itself runs `plan-progress.py`,
i.e. a hand-written wrapper, because chaining it would print the bar twice. `--remove` restores a preserved base rather than clearing the key.

**Both subprocesses are time-bounded**, so a base that blocks cannot freeze every redraw.
The bounds differ deliberately: the base defaults to 15s and the renderer to 5s, because a
base legitimately does slow work and bounds *itself* — a base that makes a
`curl --max-time 10` call is common, so a snug wrapper bound would
truncate a base working exactly as designed. The wrapper exists to catch an *unbounded*
hang, not to second-guess a self-bounded base. Override with
`PLAN_STATUSLINE_BASE_TIMEOUT` / `PLAN_STATUSLINE_BAR_TIMEOUT`. Where neither `timeout`
nor `gtimeout` exists (a stock macOS), both run unbounded rather than not running at all.

**The written path does not expire on Cursor.** Cursor installs a local plugin to
`~/.cursor/plugins/local/<plugin>` with no version segment, so the path written into the
config stays valid across updates; there is no versioned directory to resolve at render
time.

The wiring is **global and one-time** — it applies in every project, not per repo — and it
is the one piece that cannot ship with the plugin: a Cursor plugin manifest
(`.cursor-plugin/plugin.json`) has no status-line contribution point, so exactly one entry
must live in the user's global `~/.cursor/cli-config.json`. The installer exists so that
entry is generated rather than hand-authored.

Do **not** tell a user to write their own wrapper script: a hand-written wrapper hard-codes an absolute path to a dev checkout, so it keeps executing that copy
after the plugin is installed somewhere else, and the shipped renderer and the running one
silently diverge. `statusline-chain.sh` resolves the renderer as its own sibling for that
reason, so it carries no hard-coded checkout path. Where a base command comes from when the
user had none is the chain script's own header; on Cursor there is normally none, because
what the bar displaces here is the native footer, not a script.
