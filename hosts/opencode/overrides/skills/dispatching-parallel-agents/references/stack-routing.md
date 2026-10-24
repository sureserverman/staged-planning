# Stack routing — which subagent (and stack skill) gets a task

Shared by `dispatching-parallel-agents` (Phase 3 brief / Phase 4 dispatch) and
`executing-plans` (Step 3.2). It answers two questions for a ready task: **should
this go to a subagent at all**, and if so **which agent, and which stack skill should
that agent load first**. On OpenCode a subagent is dispatched by a task-tool call naming
the agent; the calling agent needs the `task` permission.

The point is *context hygiene*, not speed or token thrift. A subagent runs in its
own context window and returns only a condensed result, so the orchestrator's
window stays focused on plan state and stage gates instead of filling with file
dumps, build logs, and search noise. (Anthropic, "Create custom subagents" and
"Effective context engineering for AI agents".)

---

## Decision rule — the field decides

**Caveats (don't oversell delegation):**

- It is **not** a token saving. The subagent's intermediate tokens still burn against
  the budget; you trade a higher total count for a cleaner main window. Parallel
  subagents compound the burn.
- Subagents start fresh: no conversation history, no previously-read files, no
  already-invoked skills. Brief them completely (see the Phase 3 prompt template).
- Subagents can't talk to each other — only the orchestrator integrates their results.

`Dispatch: YES` tasks are *already* delegated (that's what this skill does), and they
are the only tasks this table routes. **A `Dispatch: NO` task runs inline** —
no rule sends independent, output-heavy sequential tasks here, because that would be
a discretionary third execution mode that no
reader of the plan can predict and that saves nothing (the subagent's tokens burn
either way). A task that should be dispatched is marked `Dispatch: YES` in the plan,
where the roster and the gate's reconciliation can see it.

---

## Routing table

Match by what the task touches. Pick the most specific row that fits; fall through to
`general` when nothing does.

Agent names are written as OpenCode dispatches them, bare: this package's agents
(`code-reviewer`, `architecture-researcher`, `design-handoff-reproducer`,
`claim-verifier`) are registered by their file names, and OpenCode's built-ins (`general`,
`explore`) are bare too. OpenCode has no plugin namespacing, so the table names no other
plugin's agent or skill. Stack work goes to whatever is **installed**: read the agents
OpenCode lists and the skills the session can load, and pick the one whose description
matches the task's stack. When none matches, dispatch `general` working from the task
brief alone, and say so in the brief. `../scripts/validate-stack-routing.py` fails on any
row naming an agent or skill this package does not ship.

| Task / stack signal | Agent | Stack skill the agent loads first |
|---|---|---|
| A language, framework, platform or domain stack — source files, build files, UI screens, game design, catalog translation | an installed agent whose description matches the stack; otherwise `general` | the stack's skill, if one is installed |
| Reproduce a Claude Design handoff pack (redesign to spec, any stack) | `design-handoff-reproducer` | `applying-design-handoff` |
| Research ONE architecture candidate — evidence, layout, libraries (any stack) | `architecture-researcher` | `architecting-projects` (dispatching context only — the skill orchestrates, the agent researches) |
| Find-and-fix investigation, unknown location | `explore` then `general` | — |
| Independent review of an integrated diff | `code-reviewer` | — |
| Nothing above fits | `general` | — |

When the table names a stack skill, put it in the dispatched agent's prompt
(`## Stack skill — invoke <skill> first`) so the delegate authors to the stack's
conventions instead of generic defaults.

**A row earns its place by adding something the fallback doesn't.** One stack row covers
every stack, because its rule is the same for all of them. A per-stack row reading
`general` / `—` says exactly what the final *Nothing above fits* row already says.
Don't add informational rows that carry no routing signal.

The **design-handoff redesign** row carries the redesign path on its own: the
`applying-design-handoff` skill orchestrates and dispatches
`design-handoff-reproducer` for precise per-slice reproduction. Platform idiom
is the dispatched agent's job, informed by an installed skill matching the TARGET
stack — not this row, which names `applying-design-handoff`. When none is installed, the
agent works from its own judgment; there is no separate per-surface UI agent to pair it
with.

**Exception — Garmin Connect IQ / Monkey C** (`*.mc`, `monkey.jungle`, `manifest.xml`, watch
face / data field / widget / glance). A Claude Design handoff pack is a visual
HTML/component spec; it does **not** map onto Monkey C's resource-layout / `Dc` model. Do
not drive Connect IQ work through `applying-design-handoff` for precise reproduction —
treat a handoff pack there as loose visual inspiration, not a fidelity target.

---

## Not every routed agent can commit — the orchestrator finishes the task

`executing-plans` Step 3.3 requires every dispatched task to run its `Test:`, flip its
`Status:` to `[x]`, and land a commit ending in an executor trailer. **An installed stack
agent may not be able to do that**, because its grant withholds what it takes. An OpenCode
agent declares a `permission:` map (`edit`, `bash`, `webfetch`, …), not a tool list, so
read the matched agent's `permission:` map before dispatch (`opencode agent list` prints
every agent's resolved rules):

| Routed agent | Can run a test? | Can commit? |
|---|---|---|
| `design-handoff-reproducer` | yes | **yes** — edits and shell allowed |
| `general` (built-in) | yes | **yes** — edits and shell allowed |
| an installed stack agent | only if its map lets `bash` run the test's command | only if its map allows `edit` and lets `bash` run a git write; an `edit: deny` map, or a `bash` map that allows only read-only git, cannot |

Rows this table routes for *research or review* rather than for a task — `architecture-researcher`, `code-reviewer` — are deliberately out of scope for this table: they never carry a `Status:` or a commit obligation, so commit capability is not a property they need (both deny edits). Their absence is a scoping decision, not a gap.

This is a capability boundary, not a bug in those agents: a domain expert with a read-only
grant is a deliberately safe tool. What it needs is a handoff between the agent and the orchestrator.

**So when the routed agent cannot commit, the task is still dispatched** — the delegation
directive is unchanged, and inlining it instead would be the exact substitution
`../../executing-plans/references/dispatch-fidelity.md` exists to prevent. Split the work:

1. **The agent does the work** and returns its report, including what it could not verify.
   Brief it that way up front rather than letting it discover the gap: tell it to make the
   edits and report, and that the caller will run the test and commit.
2. **The orchestrator runs the task's `Test:` itself**, from the main session. This is the
   same trust-but-verify re-run Phase 6 already requires for a GREEN return, so it costs
   nothing new — it just becomes the only run rather than the second one.
3. **The orchestrator writes the commit**, and **the trailer still names the agent**:
   `Executor: dispatched — <agent>`, the name the task was dispatched to. The trailer records **who did the
   work**, not who typed `git commit` — that is what makes it answer "5 marked YES, 0
   dispatched". Say in the commit body that the agent lacked commit capability and the
   orchestrator completed it, so the split is on the record.

**What you may not do** is call the task inline because the agent could not finish it, or
mark the trailer `inline` when an agent wrote the diff. Both convert a capability boundary
into a false record of who did the work.

## No capability index on OpenCode — an agent is listed or it does not exist

On Claude Code a plugin can be installed but not enabled, and a capability index at the
marketplace root lets a skill load a disabled plugin's component from disk. OpenCode has
neither: an installed package has no enablement switch, and no capability index sits
beside an install. So that load-from-disk branch **cannot fire here**, and no brief names
a path to load a component from. An agent either appears in OpenCode's agent list (this
package's four, the built-ins, whatever the user installed) or it does not exist: a task
whose stack has no installed agent goes to `general` with the stack skill, if any, named
at the top of its prompt. One of this package's own agents missing from the list is a
broken install — stop and say so, rather than degrading to `general` silently.

---

## Keeping this table honest

Every agent and skill this table names must resolve to an OpenCode built-in (`general`,
`explore`) or an agent or skill this package ships. `../scripts/validate-stack-routing.py` checks this and fails on drift
(renamed/removed agent, typo, a name from another plugin).
It ships in this package; from the package root, run it with:

```
python3 skills/dispatching-parallel-agents/scripts/validate-stack-routing.py
```

The source repository's CI runs only the host-neutral copy of this check.

---

## Sources

- Anthropic — "Create custom subagents" (code.claude.com/docs/en/sub-agents): isolated
  context windows; subagents for context preservation; choose main conversation for
  coupled/iterative/quick/latency-sensitive work.
- Anthropic — "Effective context engineering for AI agents"
  (anthropic.com/engineering/effective-context-engineering-for-ai-agents): subagents
  return condensed summaries; specialized agents with clean context windows.
