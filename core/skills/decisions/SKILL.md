---
name: decisions
description: Use to record, read, or look up the architectural decisions that bind a project and the reasons behind them. Triggers on "record this decision", "why did we choose X", "log this security review recommendation", "what decisions bind this project".
---

# Decisions

The decisions register answers *why the architecture is the way it is*: long after
the plan that decided it has been archived and the person who decided it has
forgotten. It is one file per project, `decisions.md`, holding `DEC-NNN` entries.

The full format (block grammar, field semantics, parser rules) is
`references/decisions-format.md`. **Read it before writing any entry**; this file
covers the operations, not the format.

## Where the file lives

The register is `<records home>/decisions.md`. Find the records home with:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/lib/records_home.py --project <repo>      # read
python3 ${CLAUDE_PLUGIN_ROOT}/lib/records_home.py --project <repo> --for-write   # before writing
```

- **Exit 0 or 3:** use the printed directory. On 3, records live in the repo's
  `docs/`; warn once and carry on.
- **Exit 2:** stop and show the message. Create nothing: a store that is configured
  but unreachable is not an empty one.

A configured records resolver may also list further registers that bind the project
(`records_home.py --project <repo> --decision-registers`), for example registers shared
by every project on one stack. `relevant` reads them after the project's own.

### A project with no register yet

A new project has no `decisions.md`. That is a **first-class supported state**:
`relevant` reports `project_register: absent` with the reason and still returns any
listed registers. The first `add` creates the file. Never treat an absent register as
"no decisions apply": the project with the least local context would then consult the
fewest constraints.

**Announce at start:** "Using the decisions skill — <add|list|read|relevant|supersede> on <path>."

---

## Operations

### `add` — record a new decision

Inputs: title, reason, domains, source.

1. Read `<records home>/decisions.md` (resolved with `--for-write`). If absent, create
   it with the header block from the format reference (no entries yet).
2. Next ID: scan `DEC-(?:[A-Z]{2,4}-)?\d{3}`, max + 1, keeping the tag form.
   **Never reuse an ID**, even a superseded one.
3. Insert the new block immediately below the top `---` separator (newest first).
4. Save, and report `Recorded DEC-NNN — <title>.`

**The `Reason` field is the deliverable.** An entry whose reason restates the
decision ("chose X because X is the right choice") is worthless six months later.
Capture the constraint that forced the choice, the evidence, the alternative rejected
and why, and the cost accepted. If you cannot state a cost or a rejected alternative,
question whether a decision was actually made.

**Duplicate guard.** Before writing, scan existing entries for the same `Source` or
≥80% title token overlap. Surface the match and ask whether to supersede that entry
instead of opening a parallel one: two live entries disagreeing about the same question
is the failure this register exists to prevent.

### `list` — show entries

Optional filters: `domain:<slug>`, `status:accepted|superseded`, `since:<YYYY-MM-DD>`.

Output a compact table (`ID | Title | Domains | Decided | Status`), newest first.

### `read` — return raw file content

For ingestion by other skills (`planning-projects` and `brainstorming` research
phases, `architecting-projects` prior-art scan). Returns the file as text; the caller
parses.

### `relevant` — digest what binds this project

The question a planner and an executor actually ask: *which recorded decisions
constrain the work in front of me?* Unlike `read`, this returns a compact digest of the
project's register and of every register the resolver lists, in that order.

1. **Run** `python3 ${CLAUDE_PLUGIN_ROOT}/skills/decisions/scripts/decisions-relevant.py
   --project <repo> [--format json]`.
2. **Read the digest as-is.** Superseded entries come back **marked, not filtered**:
   "we believed X and stopped" is what prevents the rejected approach being
   re-proposed. Malformed blocks come back **flagged, not dropped**; a decision that
   fails to parse is precisely the one to look at.
3. **Exit 2** means a configured records home could not be read. Stop and report it;
   never read it as "nothing binds this project".

| State | Meaning |
|---|---|
| `project_register: present` | The project's register was read. |
| `project_register: absent` | No `decisions.md` yet. Listed registers still bind the project. |

### `supersede` — replace a decision that no longer holds

Inputs: `<DEC-NNN>`, plus the fields of the replacement entry.

1. `add` the replacement entry, which gets a fresh ID.
2. Edit the old entry's `Status:` to `superseded by DEC-NNN`.
3. **Leave the old entry in place, unedited otherwise.** Its reason is the record of
   what was believed and why; deleting it destroys exactly the history the register
   exists to hold.

---

## Recording a security review recommendation

Security review is the most common producer of architectural decisions, and the one
with a hard constraint: **security review report files are local-only and never
committed.**

So an entry sourced from one:

- sets `Source:` to the report **filename and date only**, suffixed `(local-only)`;
- restates the finding's substance **in the entry's own words** under `Reason`: what
  the exposure was, what constraint it imposes, what was accepted;
- **never** pastes, quotes at length, or summarizes the report body, and never
  reproduces exploit detail.

The test is whether the entry is useful to a reader who cannot open the report. If it
is not, the `Reason` is too thin, which is not a reason to embed the report.

Set `Domains:` from the finding's scope, not the project's stack: a finding about a
network-layer assumption is `networking`, even in a mobile app.

---

## Integration

- **architecting-projects**: its approved `## Decision` section lands a `DEC` entry at
  the end of Phase 5, sourced to the architecture doc and its `ARCH-NN` sections. The
  architecture doc stays the place a decision is *made*; the register is where it stays
  findable afterwards.
- **planning-projects / brainstorming**: call `relevant` during research. A new plan
  that contradicts an accepted decision must either cite the supersede or be re-scoped;
  silently violating a recorded decision is the failure this closes.
- **A cross-project plugin, if one is installed**, may roll registers up across
  projects and list shared registers through the records resolver. It never writes into
  a project's register.
- **Ad-hoc**: invoke directly ("record this decision", "why did we pick X").

---

## Safety rails

- The register is a hand-authored declaration file. Append and edit discrete blocks;
  never rewrite the file whole, and preserve unrelated entries byte for byte.
- **Never delete an entry.** Decisions are superseded, not removed (unlike backlog
  items, which are removed on implementation). The register's value is cumulative.
- Never write a report body, credential, or exploit detail into the register.

## Remember

- The `Reason` is the artifact; the decision is just its title.
- IDs are immutable and never reused; supersede, don't delete.
