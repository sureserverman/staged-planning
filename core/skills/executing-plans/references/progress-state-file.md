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
| A stage opens (Step 3.0, before its first task) | `transition` | `{"phase": "task", "stage": 2}` — no task, so `owner-decision.py match` reads the stage the run is in, not the last gate |
| A task starts | `transition` | `{"phase": "task", "stage": 2, "task": "2.3", "task_desc": "<title>"}` |
| A stage gate runs | `transition` | `{"phase": "gate", "stage": 2}` |
| A remediation round starts, is verified, ends | `begin-round`, `record-verification`, `complete-round` | see the contract; the gate must first be named in a `transition` `gate` field |
| A Stop condition halts execution | `set-blocker` | `disposition`, `prevented_operation`, `evidence`, `dependency`, `remaining_work` (contract) |
| A handoff at a gate | `set-blocker` | the five Stop-condition fields with disposition `handoff`, plus the measured `reason` and the minted `handoff_id` |
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
| The executor stops at a stage gate on a `handoff` verdict from `context-usage.py` | `phase: "handoff"`, `stage`, `reason` (that script's `reason:` text verbatim, e.g. "context 52% > 50%"), `handoff_id` (the id minted in `session-handoff.md` § On `handoff` step 0, verbatim) |
| Close-out finishes (last step) | **delete the file** |

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

`reason` and `handoff_id` are only meaningful with `phase: "handoff"`. Copy `reason`
verbatim from the `reason:` line `context-usage.py` printed with its `handoff` verdict — do
not paraphrase it, because it is the one record of which measured rule fired. The
bar renders it after `⏸ HANDOFF`, clipped to the same width as a `blocked` note.
Copy `handoff_id` verbatim from step 0's `handoff-envelope.py new-id` output — the same id
the `RESUME HERE` block and the `ready` envelope carry:

```json
{"plan": "plans/foo-plan.md", "phase": "handoff", "stage": 2,
 "reason": "rule requested: owner asked for a rollover",
 "handoff_id": "h-0123456789abcdef0123", "updated": "<ISO-8601 UTC now>"}
```
**Markers the bar can append**, so an operator who sees one has somewhere to read:

| Marker | Means |
|---|---|
| `⊘ GATE BLOCKED` | a stage-gate check in the plan is `[~]` — a check that could not be run. Rendered on the executing bar and on a discovered plan's bar alike, because a blocked plan is blocked for whoever looks next. Never affects done/total: the counts are about tasks. |
| `⚠ status lag N` | the plan file's `Status:` markers trail the task this state file names by N sequential tasks. `Dispatch: YES` siblings are excluded — they are dispatched together and do not finish in document order. `[~]` counts as a marker that moved. |
| `⚠ not in plan` | this file names a task the plan does not contain. A worse divergence than a lag: the plan was edited under a run whose markers had already stopped. |
| `⊘ STAGE ORDER` | this file's `stage` depends (its `**Depends on:**` line) on a stage whose gate is not fully `[x]` — an open `[ ]` or a blocked `[~]`. The stage opened too early; `plan-progress.py --stage-order-check` exits 2 on the same condition. |
| `↻N/M` | a gate being re-run after a failure; see `remediation_round`. |
| `⏸ HANDOFF` | the executor stopped on purpose at a stage gate because a measured stop rule fired (or the owner asked, `rule requested`). Followed by `reason`. Not a failure: the next session resumes from the plan's `**RESUME HERE (<date>):**` block, whose `handoff_id: <id>` line names the handoff. |

**Two front ends draw it.** On Claude Code 2.1.288 or later the plugin's mod
(`../../../hooks/mod/`) draws the bars as a band over the prompt, sized to the band's own
width, and `/plan-view` opens the whole plan in a pane. It needs no wiring. It runs
`../scripts/plan-progress.py --json` — the same model the text bars come from, plus each
line's text after its bar as `tail` — when a tool call in this session writes this file
or a plan file, and every 30 s; never while drawing. Everywhere else, and on older builds, the status-line bar
is the display. Both read this file exactly as written here.

What `--json` adds for the band, beside each group's counts, markers and `tail`:

| Field | Where | What |
|---|---|---|
| `id` | each group | 8 hex of the sha1 of the plan's resolved path: the key into `details`, and the suffix of the plan's own pane, `planning-plan-<id>` |
| `tail_spans` | each group | `tail` split at the line's own colour codes, `[{text, color, dim}]`: `color` a `#rrggbb` from a `38;2;r;g;b` code or null, `dim` from code `2`. Each text is plain (no control or hidden character), and the texts join to `tail` |
| `palette` | the document | `{green, red, yellow, cyan, purple}` as `#rrggbb`, read from the colour constants the text uses |
| `details` | the document | every group's stage/task breakdown keyed by its `id` (null where it could not be built); `detail` stays the pinned plan's |

So the band draws each marker in the status line's own colour from `tail_spans` alone, and
takes its bar fill and pinned name from `palette` (the other three colours are there for a
front end that needs them), and a pane can show any plan in flight, not only the executing one.

**The renderer is not the file's only automated reader.** `../../../hooks/plan-continue.sh`
— the optional `Stop`-hook backstop, off unless the user sets `PLAN_CONTINUE=1` — reads
an owned run's `disposition` to decide whether to continue it (`working` and `repairing`
continue at every phase; a recorded blocker, owner decision, handoff or `finish` lets the
turn end), and on a legacy state file reads `phase`, where `blocked`, `closeout` and
`handoff` let a run stop on purpose. That is why these fields are a contract and not a
label, and why a placeholder or hand-written `updated` reads as stale by design. See
`plan-continue-hook.md`.

Done/total counts are **not** in the file — the renderer derives them from the
plan's authoritative `Status:` fields, so a forgotten update can never show
wrong progress, only a wrong current-task label. The file is private local derived
state: never commit it — during the git bootstrap, ensure
`.claude/plan-progress.json` is gitignored (append it if the repo doesn't
already ignore it), together with `.claude/plan-context.json`, the live-window
sidecar the planning mod rewrites while a plan is in `preflight`, `task` or `gate` (`session-handoff.md`), and `.claude/dispatch-log.jsonl`, which `../../../hooks/dispatch-log.sh`
appends to while a plan is in flight (`prove-claim.py` does not count untracked files in the top-level `.claude/`, so this is hygiene, not a proof prerequisite). For a master plan, the state file always points at the
**sub-plan** currently executing.

**One-time user setup** (only if asked to wire it, and only where the band is not
available): run `/planning:statusline install`.
That command is the invocation — do not hand a user a relative `../scripts/…` path, which
resolves only when the shell's cwd happens to be this file's own directory and fails
everywhere else. The command runs
`python3 "${CLAUDE_PLUGIN_ROOT}/skills/executing-plans/scripts/statusline-install.py"`,
which writes the single `statusLine` entry in `~/.claude/settings.json` pointing at the
shipped `statusline-chain.sh`; that script runs the user's existing statusline first and
appends this renderer's output on the next line when non-empty, both from the same stdin
JSON. `--status` reports what is wired; `--remove` takes it back out.

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

**The written pointer resolves the newest installed version at render time**, rather than
freezing today's path. A plugin installs to a version-pinned directory that changes on
every bump, and `statusLine` is not a plugin contribution point — so `/reload-plugins`,
which re-points hooks, MCP and LSP servers, cannot re-point it, and the stale directory is
removed after roughly two weeks. A frozen path would then take the user's *base* statusline
down with it, since the chain script is what invokes the base.

The wiring is **global and one-time** — it applies in every project, not per repo — and it
is the one piece that cannot ship with the plugin: `statusLine` is not a plugin
contribution point (a plugin's `settings.json` supports only `agent` and
`subagentStatusLine`), so exactly one entry must live in the user's global settings. The
installer exists so that entry is generated rather than hand-authored.

Do **not** tell a user to write their own wrapper script: a hand-written wrapper hard-codes an absolute path to a dev checkout, so it keeps executing that copy
after the plugin is installed somewhere else, and the shipped renderer and the running one
silently diverge. `statusline-chain.sh` resolves the renderer as its own sibling for that
reason, so it carries no hard-coded checkout path. (It does default the *base* statusline
to `$HOME/.claude/statusline.sh` — an absolute path, but an overridable default rather
than a baked-in location.)
