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
`general-purpose` when nothing does.

Agent names are written as Claude Code dispatches them: this plugin's agents use their
`planning:<agent>` form and built-ins (`general-purpose`, `Explore`) are bare. The table
names no other plugin's agent or skill. Stack work goes to whatever is **installed**: read
the subagent types and skills the session lists, and pick the one whose description
matches the task's stack. When none matches, dispatch `general-purpose` working from the
task brief alone, and say so in the brief. `../scripts/validate-stack-routing.py` fails on
any row naming an agent or skill this plugin does not ship.

| Task / stack signal | Subagent type | Stack skill the subagent loads first |
|---|---|---|
| A language, framework, platform or domain stack — source files, build files, UI screens, game design, catalog translation | an installed agent whose description matches the stack; otherwise `general-purpose` | the stack's skill, if one is installed |
| Reproduce a Claude Design handoff pack (redesign to spec, any stack) | `planning:design-handoff-reproducer` | `applying-design-handoff` |
| Research ONE architecture candidate — evidence, layout, libraries (any stack) | `planning:architecture-researcher` | `architecting-projects` (dispatching context only — the skill orchestrates, the agent researches) |
| Find-and-fix investigation, unknown location | `Explore` then `general-purpose` | — |
| Independent review of an integrated diff | `planning:code-reviewer` | — |
| Nothing above fits | `general-purpose` | — |

When the table names a stack skill, put it in the dispatched agent's prompt
(`## Stack skill — invoke <skill> first`) so the delegate authors to the stack's
conventions instead of generic defaults.

**A row earns its place by adding something the fallback doesn't.** One stack row covers
every stack, because its rule is the same for all of them. A per-stack row reading
`general-purpose` / `—` says exactly what the final *Nothing above fits* row already says.
Don't add informational rows that carry no routing signal.

The **design-handoff redesign** row carries the redesign path on its own: the
`applying-design-handoff` skill orchestrates and dispatches
`planning:design-handoff-reproducer` for precise per-slice reproduction. Platform idiom
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
agent may not be able to do that**, because its `tools:` grant withholds what it takes.
Read the matched agent's `tools:` line before dispatch:

| Routed agent | Can run a test? | Can commit? |
|---|---|---|
| `planning:design-handoff-reproducer` | yes | **yes** — unrestricted shell |
| an installed stack agent | only if its grant runs the test's command | only if its grant includes a shell or a git write; a read-only git grant (status, diff, log, show, blame) cannot |

Rows this table routes for *research or review* rather than for a task — `planning:architecture-researcher`, `planning:code-reviewer` — are deliberately out of scope for this table: they never carry a `Status:` or a commit obligation, so commit capability is not a property they need. Their absence is a scoping decision, not a gap.

This is a capability boundary, not a bug in those agents: a domain expert with a read-only
git grant is a deliberately safe tool. What it needs is a handoff between the agent and the orchestrator.

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
   `Executor: dispatched — <plugin>:<agent>`, the matched agent's type. The trailer records **who did the
   work**, not who typed `git commit` — that is what makes it answer "5 marked YES, 0
   dispatched". Say in the commit body that the agent lacked commit capability and the
   orchestrator completed it, so the split is on the record.

**What you may not do** is call the task inline because the agent could not finish it, or
mark the trailer `inline` when an agent wrote the diff. Both convert a capability boundary
into a false record of who did the work.

## Resolving a capability whose plugin isn't enabled

The routing table names agents and skills by the identity Claude Code uses **when
their plugin is enabled** — a registered `<plugin>:<agent>` type, an invocable skill.
But a task can need a capability whose plugin isn't in the current session's
loadout (a fresh project, a narrow task profile). Enablement only controls what
Claude Code *injects and registers* at session start; the component files are on
disk regardless. So resolve the capability from disk instead of assuming it's
registered.

**Find the index.** `capability-index.json` lives at the marketplace repo root and
lists every component: `plugin`, `kind` (skill/agent/command), `name`, repo-relative
`path`, `description`, `model`, `disable_model_invocation`, `requires_enablement`.
There is no absolute `root` field — resolve each component's `path` **against the
directory that contains the index file** (that directory *is* the marketplace root
by construction, so the index is machine-independent). Match the task against
`description`/`name` to pick the component the routing table points at.

Then, by `kind`:

- **Skill** — put an explicit instruction in the delegate's prompt to **Read the SKILL.md**
  at that `path` and follow it (load its `references/` the same way the skill's own
  body directs). Caveat: a skill reached this way runs **without its
  frontmatter `allowed-tools` scoping** — that scoping only applies when Claude Code
  invokes the skill as a registered skill. If the skill relies on a restricted tool
  set, say so in the brief or prefer enabling the plugin.
- **Agent** — the agent isn't a registered subagent type, so you can't set
  `subagent_type` to it. Instead dispatch a `general-purpose` subagent and **inject
  the agent's `.md` body** (below its frontmatter) into the prompt as its operating
  instructions, and pass the agent's frontmatter **`model`** as the subagent's model
  so the pin is preserved (e.g. a `model: sonnet` agent still runs on Sonnet). This
  is the same content the agent type would carry; only the delivery differs.
- **`requires_enablement: true`** — the component depends on machinery that only
  activates on enablement (native hooks, a native or bundled MCP server), so it
  **cannot** be faithfully lazy-loaded. Do **not** Read-and-follow it. Stop and tell
  the user which plugin to enable and why (e.g. "this task needs the device-emulator
  plugin's MCP server — enable that plugin for this session").

This disk-resolution path is a fallback layered **under** the field-decides rule
above, not a replacement for it: the plan's `Dispatch:` field already decided
*whether* the task is delegated; if the chosen capability's plugin happens to be
disabled, resolve it from the index. When the plugin **is** enabled, use the normal
registered `subagent_type` / skill invocation; the index path is only for the
disabled case.

---

## Keeping this table honest

Every agent and skill this table names must resolve to a built-in or an agent or skill
this plugin ships. `../scripts/validate-stack-routing.py` checks this and fails on drift
(renamed/removed agent, typo, a name from another plugin).
In the source repository it runs in CI as one of the validators `scripts/run-tests.sh`
runs (the script is not part of the installed plugin); from that repository's root, run
it with:

```
python3 core/skills/dispatching-parallel-agents/scripts/validate-stack-routing.py
```

---

## Sources

- Anthropic — "Create custom subagents" (code.claude.com/docs/en/sub-agents): isolated
  context windows; subagents for context preservation; choose main conversation for
  coupled/iterative/quick/latency-sensitive work.
- Anthropic — "Effective context engineering for AI agents"
  (anthropic.com/engineering/effective-context-engineering-for-ai-agents): subagents
  return condensed summaries; specialized agents with clean context windows.
