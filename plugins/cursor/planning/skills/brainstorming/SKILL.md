---
name: brainstorming
description: Use before any non-trivial creative or implementation work — new features, components, services, migrations, or behavior changes — to turn a vague idea into a design the user has approved. Triggers on "I want to build", "let's design", "brainstorm", "help me think through".
---

> On Cursor, `<planning-plugin>` is this plugin's installed folder: the folder that holds `skills/` and `.cursor-plugin/` (`~/.cursor/plugins/local/planning` for a local install), which is `../..` from this SKILL.md. In a shell command use its absolute path, quoted.

# Brainstorming Ideas Into Designs

Turn an idea into a design the user approves. The design document is the input of the next skill: `architecting-projects` when the design has a structural surface, otherwise `planning-projects`.

Work that `planning-projects` would triage as Direct (about two tasks, one session) needs no brainstorm.

**Announce at start:** "Using the brainstorming skill to turn this idea into a validated design."

<HARD-GATE>
Do NOT invoke `architecting-projects` or `planning-projects`, write production code, scaffold a project, or run an implementation skill until you have presented a design and the user has said yes. The design may be three sentences for a small task — but it must be presented and approved before handoff.
</HARD-GATE>

## Ground the idea in the repo

Read before you ask. Do not ask what the repo already answers.

- Read the root manifests, the README and recent commits (`git log -30 --oneline`).
- Run the `decisions` skill's `relevant` operation. Its accepted decisions bind the design (`../decisions/references/decisions-format.md`). A design that contradicts one supersedes it explicitly or is re-scoped.
- Look for earlier design notes on this topic in `<records home>/plans/` and in the repo.
- Match the patterns already in the code. Do not add a second HTTP client, test framework or auth flow.

If you hand any of this reading to an agent, its brief says: wait on a background job by its own completion (`../executing-plans/references/task-execution.md` § Waiting on background work), and an agent returns only after its own background work has finished or been stopped, and says which.

## Ask what you cannot infer

- Ask only what would change the design and the repo cannot answer.
- Batch the questions in one round, with the host's question tool.
- Prefer multiple choice when the answers are few.
- When you can infer an answer, state it as an assumption for the user to confirm.
- Stop asking when you have enough to design.

## Propose alternatives

Propose two or three approaches. Give each its tradeoff, and name the one you recommend and why. Cut what the problem does not need. The simpler option wins unless a concrete need justifies more.

## Present the design once

Present the whole design in one message, scaled to the work. Cover each section the design document lists (§ Write the design document). Say so plainly when a section does not apply. End by asking the user to approve it.

Only an explicit yes approves the design. A reply that asks for changes is not a yes, even when it also says some part is fine. Revise, present the revised design, and ask again. The user approves the design once, as a whole.

## Write the design document

**Output location.** Design docs live in the project's records home, resolved exactly as `planning-projects` → "## Output location" does: run `python3 <planning-plugin>/lib/records_home.py --project <repo> --for-write` and obey its exit code: 0 or 3, use the printed records home (on 3 it is the repo's `docs/`, warn once); 2, stop and show the message, creating nothing. Save to `<records home>/plans/YYYY-MM-DD-<topic>-design.md`.

> **On Cursor, check that the command ran.** `<planning-plugin>` is written out as the
> installed folder (`~/.cursor/plugins/local/planning` for a local install), because Cursor
> gives a skill no plugin-root variable, so a wrong path is easy to type. Python also exits
> **2** when it cannot open the file, which looks exactly like *"stop, create nothing"*. A
> **2** whose stderr does not start with `records_home:` is a **broken invocation**, not an
> answer: fix the path and rerun. The exit-code contract itself stays in
> `../../references/records-resolver.md`.

Structure:

```markdown
# Design: <Topic>
Date: <YYYY-MM-DD>

## Problem
## Alternatives considered
## Architecture
## Components
## Data flow
## Error handling
## Testing strategy
## Rollout / rollback
## Risks
```

`## Problem` states why, the constraints and the success criteria: `architecting-projects` bounds every candidate by them.

Commit the design document before handoff so future sessions can find it.

## Hand off

Brainstorming has two next hops. It never hands off to `executing-plans` or an implementation skill.

- **The design has a structural surface** (module boundaries, directory layout, injection points, or cross-module interfaces) → hand off to **`architecting-projects`**. Say:

  > Design approved and saved to `<records home>/plans/<filename>-design.md`. This design has a structural surface, so handing off to the `architecting-projects` skill to research and validate the architecture before planning.

- **No structural surface** (a config change, a single-file fix, a doc update) → skip the architect explicitly: say "no structural surface: straight to planning-projects". Then hand off to **`planning-projects`**. Say:

  > Design approved and saved to `<records home>/plans/<filename>-design.md`. No structural surface — handing off to the `planning-projects` skill to produce the staged implementation plan.

Then invoke the chosen skill with the design document as input. Skipping the architect is never silent — the routing sentence is part of the handoff.
