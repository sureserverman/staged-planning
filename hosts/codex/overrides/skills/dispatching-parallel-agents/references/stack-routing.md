# Stack routing — which agent (and stack skill) gets a task

Shared by `dispatching-parallel-agents` (Phase 3 brief / Phase 4 dispatch) and
`executing-plans` (Step 3.2). It answers two questions for a ready `Dispatch: YES` task:
**which agent gets it, or whether the table routes it inline**, and **which stack skill is
loaded first**.

The point is *context hygiene*, not speed or token thrift. A spawned agent runs in its own
context window and returns only a condensed result, so the orchestrator's window stays
focused on plan state and stage gates instead of filling with file dumps, build logs, and
search noise.

**What Codex has to route to.** A Codex plugin cannot ship agent roles, so this plugin's
installer writes its five roles as TOML under `$CODEX_HOME/agents`. This table names three of
those five, and no other agent. Codex spawns an agent only when explicitly asked, with
`spawn_agent`; at most 6 run at once (`[agents] max_threads`, default 6), and a spawned
agent cannot spawn another (`max_depth` 1).

---

## Decision rule — the field decides

The plan's `Dispatch:` field decides *whether* a task is delegated; this table decides only
*how*. A `Dispatch: YES` task goes to the agent its row names — or, where the row says
*inline*, it runs as **table-routed inline execution** in this session, on the same Phase 3
brief and Red-Green rules. Nothing is decided by weighing the task at run time.

**Caveats (don't oversell delegation):**

- It is **not** a token saving. The spawned agent's intermediate tokens still burn against
  the budget; you trade a higher total count for a cleaner main window. Parallel agents
  compound the burn.
- Spawned agents start fresh: no conversation history, no previously-read files, no
  already-invoked skills. Brief them completely (see the Phase 3 prompt template).
- Spawned agents can't talk to each other — only the orchestrator integrates their results.

`Dispatch: YES` tasks are *already* delegated (that's what this skill does), and they
are the only tasks this table routes. **A `Dispatch: NO` task runs inline** —
no rule sends independent, output-heavy sequential tasks here, because that would be
a discretionary third execution mode that no reader of the plan can predict and that saves
nothing (the spawned agent's tokens burn either way). A task that should be dispatched is
marked `Dispatch: YES` in the plan, where the roster and the gate's reconciliation can see
it.

---

## Routing table

Match by what the task touches. Pick the most specific row that fits; fall through to
*inline* when nothing does.

Agent names are written as `planning:<agent>`: the plugin's name for the role the installer
writes as `planning-<agent>.toml` under `$CODEX_HOME/agents` (`~/.codex/agents` when `CODEX_HOME` is unset). Spawn the role by the name that file declares.
The table names no other plugin's agent or skill, and no agent Codex does not have. Stack
work has no agent here: Codex ships no general stack agent, and this plugin ships none, so
every stack routes *inline*, loading the stack's skill first when one is installed.

| Task / stack signal | Agent | Stack skill to load first |
|---|---|---|
| Research ONE architecture candidate — evidence, layout, libraries (any stack) | `planning:architecture-researcher` | `architecting-projects` (dispatching context only — the skill orchestrates, the agent researches) |
| Reproduce a Claude Design handoff pack (redesign to spec, any stack) | `planning:design-handoff-reproducer` | `applying-design-handoff` |
| Independent review of an integrated diff | `planning:code-reviewer` | — |
| A language, framework, platform or domain stack — source files, build files, UI screens, game design, catalog translation | *inline* | the stack's skill, if one is installed |
| Nothing above fits | *inline* | — |

When the table names a stack skill, put it at the top of the spawned agent's prompt
(`## Stack skill — invoke <skill> first`), or load it yourself before a table-routed inline
task, so the work follows the stack's conventions instead of generic defaults. If the named
skill is not installed, proceed without it and say so in the result.

**A row earns its place by adding something the fallback doesn't.** One stack row covers
every stack, because its rule is the same for all of them. A per-stack row reading
*inline* / `—` says exactly what the final *Nothing above fits* row already says. Don't add
informational rows that carry no routing signal.

The **design-handoff redesign** row carries the redesign path on its own: the
`applying-design-handoff` skill orchestrates and spawns
`planning:design-handoff-reproducer` for precise per-slice reproduction. Platform idiom
is the spawned agent's job, informed by an installed skill matching the TARGET
stack — not this row, which names `applying-design-handoff`. When none is installed, the
agent works from its own judgment.

**Exception — Garmin Connect IQ / Monkey C** (`*.mc`, `monkey.jungle`, `manifest.xml`, watch
face / data field / widget / glance). A Claude Design handoff pack is a visual
HTML/component spec; it does **not** map onto Monkey C's resource-layout / `Dc` model. Do
not drive Connect IQ work through `applying-design-handoff` for precise reproduction —
treat a handoff pack there as loose visual inspiration, not a fidelity target.

---

## *inline* is a routing outcome, not a dropped dispatch

Every *inline* cell in § Routing table is a **declared** answer to "which agent gets this task": none
exists on this host, so the orchestrating session runs it. It is not executor discretion,
not a fallback taken under time pressure, and not a failure. Three consequences:

1. **The task is still dispatched work.** It gets the full Phase 3 brief (including
   `## Decisions in force`), the plan's Red-Green cycle budget, and its own commit. Running
   inline removes the spawned agent, not the discipline.
2. **It carries its own roster entry and trailer.** Preflight's roster routes it
   `Task <N.M> → inline (routing table — no <stack> agent on this host)`, and its commits
   carry `Executor: inline (routing table — no <stack> agent on this host)` — never
   `inline (dispatch failed)`, which means the mechanism was unavailable. Here the mechanism
   worked and routed to inline. `plan-progress.py --dispatch-check` reconciles that trailer
   only on a task the roster routed so, and counts it as its own term.
3. **It is never a Stop condition.** "Dispatch unavailable" fires when a task the table
   routes **to an agent**, or a review the tier mandates, cannot be spawned. Firing it on a
   table-routed inline would halt nearly every run on this host and train the executor to
   route around a Stop condition.

---

## Not every routed agent can commit — the orchestrator finishes the task

`executing-plans` Step 3.3 requires every dispatched task to run its `Test:`, flip its
`Status:` to `[x]`, and land a commit ending in an executor trailer.

| Routed destination | Can run a test? | Can commit? |
|---|---|---|
| `planning:design-handoff-reproducer` | yes | yes — a spawned role runs with this session's sandbox and tools |
| *inline* (every stack row) | yes — it is this session | yes — it is this session |

Rows this table routes for *research or review* rather than for a task —
`planning:architecture-researcher`, `planning:code-reviewer` — are deliberately out of scope
for this table: they never carry a `Status:` or a commit obligation. Their absence is a
scoping decision, not a gap.

**When a routed agent does not commit, the task is still dispatched** — the delegation
directive is unchanged, and calling it inline instead would be the exact substitution
`../../executing-plans/references/dispatch-fidelity.md` exists to prevent. Split the work:

1. **The agent does the work** and returns its report, including what it could not verify.
2. **The orchestrator runs the task's `Test:` itself**, from the main session — the same
   trust-but-verify re-run Phase 6 already requires for a GREEN return.
3. **The orchestrator writes the commit**, and **the trailer still names the agent**:
   `Executor: dispatched — planning:<agent>`. The trailer records **who did the work**, not
   who typed `git commit`. Say in the commit body that the orchestrator completed it.

**What you may not do** is call the task inline because the agent did not finish it, or
mark the trailer `inline` when an agent wrote the diff.

## Resolving a capability that is not installed

Codex has no plugin-enablement switch and no capability index, so there is nothing to
resolve from disk. A stack skill the routing table names is either installed or it is not. If it is
not, do the work without it and say so in the result — do not silently substitute a
different skill. A planning role the installer has not written (no
`planning-<agent>.toml` under `$CODEX_HOME/agents`, `~/.codex/agents` when `CODEX_HOME` is unset; `python3 <planning-plugin>/scripts/install-agents.py --install` writes the missing ones) cannot be spawned: that is the dispatch Stop condition
for a task the table routes to it, and the fix is the user's (run the installer), never an
inline run on your own authority.

---

## Keeping this table honest

Every agent this table names must be one of this plugin's five roles, and every skill one
this plugin ships, or a stack skill that is only loaded if installed.
`../scripts/validate-stack-routing.py` checks the names against the plugin it sits in and
fails on drift (a renamed or removed agent, a typo, a name from another plugin):

```
python3 ../scripts/validate-stack-routing.py
```

---

## Sources

- Anthropic — "Create custom subagents": isolated context windows; subagents for context
  preservation; choose the main conversation for coupled/iterative/quick/latency-sensitive
  work.
- Anthropic — "Effective context engineering for AI agents": subagents return condensed
  summaries; specialized agents with clean context windows.
- Codex `[agents]` configuration: `max_threads` (concurrency cap, default 6) and
  `max_depth` 1 (a spawned agent cannot spawn).
