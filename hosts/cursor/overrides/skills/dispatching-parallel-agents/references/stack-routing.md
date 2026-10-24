# Stack routing — which subagent (and stack skill) gets a task

Shared by `dispatching-parallel-agents` (Phase 3 brief / Phase 4 dispatch) and
`executing-plans` (Step 3.2). It answers two questions for a ready task: **should
this go to a subagent at all**, and if so **which subagent type, and which stack
skill should that subagent load first**.

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
`generalPurpose` when nothing does.

Agent names are written as Cursor dispatches them: by **bare name**, because Cursor has
no plugin namespace — this plugin's agents are `code-reviewer`, `claim-verifier`,
`architecture-researcher` and `design-handoff-reproducer` (the table routes all but
`claim-verifier`), every local plugin sits side by side under
`~/.cursor/plugins/local/`, and an installed agent is addressed by the name the session
lists. `explore` is Cursor's built-in search agent and `generalPurpose` its general agent
(the names Cursor's `Task` call carries; the role is written `general-purpose` on other
hosts). The table names no other plugin's agent or skill. Stack work goes to whatever is **installed**: read
the subagent types and skills the session lists, and pick the one whose description
matches the task's stack. When none matches, dispatch `generalPurpose` working from the
task brief alone, and say so in the brief. `../scripts/validate-stack-routing.py` fails on
any row naming an agent or skill this plugin does not ship.

| Task / stack signal | Subagent type | Stack skill the subagent loads first |
|---|---|---|
| A language, framework, platform or domain stack — source files, build files, UI screens, game design, catalog translation | an installed agent whose description matches the stack; otherwise `generalPurpose` | the stack's skill, if one is installed |
| Reproduce a Claude Design handoff pack (redesign to spec, any stack) | `design-handoff-reproducer` | `applying-design-handoff` |
| Research ONE architecture candidate — evidence, layout, libraries (any stack) | `architecture-researcher` | `architecting-projects` (dispatching context only — the skill orchestrates, the agent researches) |
| Find-and-fix investigation, unknown location | `explore` then `generalPurpose` | — |
| Independent review of an integrated diff | `code-reviewer` | — |
| Nothing above fits | `generalPurpose` | — |

When the table names a stack skill, put it in the dispatched agent's prompt
(`## Stack skill — invoke <skill> first`) so the delegate authors to the stack's
conventions instead of generic defaults.

**A row earns its place by adding something the fallback doesn't.** One stack row covers
every stack, because its rule is the same for all of them. A per-stack row reading
`generalPurpose` / `—` says exactly what the final *Nothing above fits* row already says.
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
agent may not be able to do that**. On Cursor an agent file has no per-tool grant: its
only restriction is `readonly: true`, which withholds file edits and state-changing shell
commands. Read the matched agent's frontmatter before dispatch:

| Routed agent | Can run a test? | Can commit? |
|---|---|---|
| `design-handoff-reproducer` | yes | **yes** — not `readonly`, so unrestricted |
| an installed stack agent | yes, unless `readonly: true` stops the test's command (a test that writes files or state) | yes, unless it is `readonly: true` — a read-only agent cannot commit |

Rows this table routes for *research or review* rather than for a task — `architecture-researcher`, `code-reviewer` — are deliberately out of scope for this table: they never carry a `Status:` or a commit obligation, so commit capability is not a property they need. Their absence is a scoping decision, not a gap.

This is a capability boundary, not a bug in those agents: a domain expert marked
`readonly` is a deliberately safe tool. What it needs is a handoff between the agent and the orchestrator.

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
   `Executor: dispatched — <agent>`, the bare name Cursor dispatched. The trailer records **who did the
   work**, not who typed `git commit` — that is what makes it answer "5 marked YES, 0
   dispatched". Say in the commit body that the agent lacked commit capability and the
   orchestrator completed it, so the split is on the record.

**What you may not do** is call the task inline because the agent could not finish it, or
mark the trailer `inline` when an agent wrote the diff. Both convert a capability boundary
into a false record of who did the work.

## Resolving a capability whose plugin isn't enabled

The routing table names agents and skills by the identity Cursor registers **when their
plugin is installed** — an addressable agent, an invocable skill. But a task can need a
capability whose plugin isn't installed in this workspace (a fresh project, a trimmed
plugin set). The component files may still be on disk. So resolve the capability from
disk instead of assuming it's registered.

**There is no capability index on Cursor.** A Cursor install copies only the plugin
folder, so no `capability-index.json` sits beside it, and nothing here generates one. Do
not follow an instruction to read one; it will not be there. Resolve by the installed
layout instead, which is fixed and needs no index:

```
~/.cursor/plugins/local/<plugin>/skills/<skill-name>/SKILL.md
~/.cursor/plugins/local/<plugin>/agents/<agent-name>.md
```

The `<plugin>` is the plugin that ships the capability and `<name>` its name. If the file
is not at that path, the plugin is not present: **do the work inline without it and say
so in the result** — never silently substitute a different skill.

Then, by kind:

- **Skill** — put an explicit instruction in the delegate's prompt to **Read the SKILL.md**
  at that path and follow it (load its `references/` the same way the skill's own body
  directs). Caveat: a skill reached this way runs **outside Cursor's own skill
  invocation**, so frontmatter Cursor would otherwise honor does not apply. If the skill
  relies on that, say so in the brief or prefer installing the plugin.
- **Agent** — the agent isn't registered, so you can't address it by name. Instead
  dispatch a `generalPurpose` subagent and **inject the agent's `.md` body** (below its
  frontmatter) into the prompt as its operating instructions. This is the same content the
  agent would carry; only the delivery differs. There is no model to carry across —
  Cursor chooses the model.
- **Hooks or a bundled MCP server** — the component depends on machinery that only
  activates when its plugin is installed, so it **cannot** be faithfully lazy-loaded. Do
  **not** Read-and-follow it. Stop and tell the user which plugin to install and why (e.g.
  "this task needs the device-emulator plugin's MCP server — install that plugin for this
  session"). With no index to flag it, judge it from the component itself: a skill whose
  body drives `hooks/` or an MCP server is in this class.

This disk-resolution path is a fallback layered **under** the field-decides rule
above, not a replacement for it: the plan's `Dispatch:` field already decided
*whether* the task is delegated; if the chosen capability's plugin happens to be
absent, resolve it from disk. When the plugin **is** installed, use the normal
registered agent name / skill invocation; the disk path is only for the
not-installed case.

---

## Keeping this table honest

Every agent and skill this table names must resolve to a built-in or an agent or skill
this plugin ships, written by the bare name Cursor dispatches. The Cursor copy of
`../scripts/validate-stack-routing.py` checks this and fails on drift (renamed/removed
agent, typo, a name from another plugin, or a namespaced `<plugin>:<name>` form Cursor
cannot dispatch). It reads the agents and skills of the plugin it sits in; run it with:

```
python3 "<planning-plugin>/skills/dispatching-parallel-agents/scripts/validate-stack-routing.py"
```

---

## Sources

- Anthropic — "Create custom subagents" (code.claude.com/docs/en/sub-agents): isolated
  context windows; subagents for context preservation; choose main conversation for
  coupled/iterative/quick/latency-sensitive work.
- Anthropic — "Effective context engineering for AI agents"
  (anthropic.com/engineering/effective-context-engineering-for-ai-agents): subagents
  return condensed summaries; specialized agents with clean context windows.
