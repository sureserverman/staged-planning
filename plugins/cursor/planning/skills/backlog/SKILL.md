---
name: backlog
description: Use to read, append, or remove entries in docs/backlog.md — the register for deferred improvements and decisions, not defects. Triggers on "add to backlog", "defer this", "what's in the backlog", "BL-NNN is done — remove it". Append on defer, remove on implement, list on research.
---

> On Cursor, `<planning-plugin>` is this plugin's installed folder: the folder that holds `skills/` and `.cursor-plugin/` (`~/.cursor/plugins/local/planning` for a local install), which is `../..` from this SKILL.md. In a shell command use its absolute path, quoted.

# Backlog

The backlog is a single file — `backlog.md` — that holds work the project chose not to do *right now*. Items are appended when deferred, removed when implemented, and consulted when a new plan is being researched.

## Where the file lives (resolver)

The backlog lives in the project's records home:

```
<records home>/backlog.md
```

Find the records home with `python3 <planning-plugin>/lib/records_home.py --project <repo>` (add `--for-write` before writing). **Exit 0 or 3:** use the printed directory (on 3 it is the repo's `docs/`; warn once). **Exit 2:** stop and show the message, and create nothing. Every `docs/backlog.md` reference below means `<records home>/backlog.md`.

**Announce at start:** "Using the backlog skill — <add|list|remove|read|unify|complete> on <records home>/backlog.md."

---

## File format

`docs/backlog.md` is plain markdown. One header, then one section per entry, newest at the top:

```markdown
# Backlog

Deferred items from plan execution, code review, or ad-hoc capture. Entries are removed when implemented; git history is the audit trail.

---

## BL-NN2 — Add retry on server 5xx

- **Opened:** 2026-05-17
- **Source:** plans/2026-05-13-offline-sync-plan.md — Stage 2, Task 2.3
- **Reason:** Out of scope for current PR; the happy path was enough to unblock Stage 3.
- **Next step:** Standalone plan; depends on the server migration landing first.
- **Tags:** android, sync, resilience

Optional 1–3 sentence body for context that doesn't fit the bullets.

---

## BL-NN1 — ...
```

An entry may additionally carry a **parking annotation** among its bullets:

```markdown
- **Parked:** 2026-08-01 — waiting for dry season
```

`- **Parked:** <YYYY-MM-DD or free-text reason>` marks the item as
deliberately not-now: a tool that ranks work (a cross-project plugin, if one
is installed) excludes parked items from its "what next" recommendations,
surfacing them only in a review or once a parked date has passed. Parking is
not completion — the entry stays open and is still removed only when implemented. Add the line when deferring an item
you keep getting nagged about; remove the line to unpark.

**ID rules:**

- Format `BL-NNN`, three digits, zero-padded.
- Next ID = `max(existing BL-NNN) + 1`. **Never reuse a removed ID.**
- IDs are referenced from plan files and commit messages: `Closes BL-NNN`.

**Required fields:** `Opened`, `Source`, `Reason`, `Next step`. `Tags` is optional.

---

## What belongs here

The backlog admits exactly three kinds of entry:

1. **A significant improvement** — a refactor, a new capability, performance work with no bug behind it. Nothing is broken; this is work someone should choose to schedule.
2. **A non-urgent decision** the user must make — a change needing sign-off, a trade-off with no obviously right answer, an editorial call.
3. **Work the user explicitly chose to defer** — including a task skipped after a Red-Green cycle budget exhausted, where the user chose skip over re-plan.

**Refuse the fourth kind: a defect found during plan execution.** A defect is fixed, and its class swept, per `planning/skills/executing-plans/SKILL.md` § *A bug found during execution is a class* and § *Exit criterion*. The one exception: a defect that genuinely cannot be fixed in the session — because the fix needs a device, a credential, an upstream release, or an environment the session lacks — is escalated to the user with the blocker named. If the user then chooses to file it, that is an admissible entry of kind 3, because the user decided it, not the executor. **That decision is evidenced, not asserted:** the entry quotes the user's words and names the blocker that forced the escalation, the same bar `planning/skills/executing-plans/references/integration.md` § *Review opt-out* sets for a skipped review. An entry whose only justification is the executor's own report that it escalated is an executor decision wearing a user's clothes — refuse it.

**Why refuse.** Recording is frictionless and fixing is not, so an executor under gate pressure drifts toward filing everything, and each deferral reads as scope discipline rather than the avoidance it is. A deferred defect stays broken, and can leave the project's own suite failing while the entry waits.

`unify` (below) derives candidates from *unexecuted plan tasks* — deferred work, kind 3 above — so it is unaffected by this refusal.

## Operations

### `add` — append a new entry

Inputs: title, source (plan path + stage/task, or `ad-hoc`), reason, next step, optional tags, optional body.

0. **Classify before doing anything else.** Check the item against § What belongs here. If it is a defect found during plan execution (not kind 1, 2, or 3), **Refuse**: compute no ID, write nothing. Report the refusal, name the rule (`backlog admits improvements and decisions, not defects — see § What belongs here`), and tell the caller to fix the defect and sweep its class instead. A caller who insists is told that only the user can decide to file it — that requires the user's own instruction, not the executor's judgment call.
1. Read `docs/backlog.md`. If the file doesn't exist, create it with the header block above (no entries yet).
2. Compute the next ID: scan for `BL-\d{3}`, take max, add 1.
3. Insert the new entry block immediately below the top `---` separator (newest first).
4. Save.
5. Report: `Appended BL-NNN — <title>.`

**Duplicate guard.** Before writing, scan open entries. If one shares the same `Source` (same plan + same stage/task) OR has ≥80% title token overlap, surface it and ask whether to update that entry instead of opening a new one. Don't silently create a duplicate.

### `remove` — delete an implemented or rejected entry

Inputs: one or more BL-IDs.

1. Read the file. **Count the entries first** — `grep -c '^## BL-'` — and hold that number.
2. For each ID:
   - If no block matches the exact ID header, report `BL-NNN not found` and skip.
   - Else delete the entry block — from its `## BL-NNN — ...` heading **up to the next line beginning `## BL-`, or end of file** — then drop any `---` separator and blank lines the deletion stranded.
3. **Before saving, count again: the total must have dropped by exactly the number of IDs removed.** If it dropped by more, discard the edit, save nothing, and surface it.
4. Save.
5. Report: `Removed BL-NNN (22 entries → 21).` The calling commit message should include `Closes BL-NNN` so the rationale is recoverable from `git log`.

**Why the boundary is the next heading and not the next `---`.** An entry ends where the next entry begins. That is true of every backlog file. "There is a `---` before the next one" is true only of files that kept their separators, and real ones drift. On a file whose next separator is several entries away, deleting "through the next `---`" removes the target *and every entry before that separator*.

**And why step 3 exists rather than trusting step 2.** A file carrying separators on its older entries and not its newer ones does not look corrupt; it looks tidy. A guard that depends on noticing something looks wrong is not a guard. Counting is: one `grep -c`, no judgment about the file, and it fails loudly on an over-wide delete.

**Assume the register cannot be restored.** The records home may not be a git working tree, so the closing commit (`Closes BL-NNN`) is the audit trail, and "git is the archive" may not hold where the file actually is. An over-wide delete there is permanent; an entry carries inline whatever it needs from another entry.

**Hard rules:**

- Only remove by explicit ID. Never bulk-remove by tag, source, or "looks done."
- Implementation status is asserted by a user or by a plan's Close-out — never inferred from a heuristic.
- Don't move entries to an archive section. Removal is removal.

### `list` — show open entries

Optional filters: `tag:<name>`, `source:<plan-path-substring>`, `since:<YYYY-MM-DD>`.

Output a compact table — `ID | Title | Source | Opened` — sorted newest first.

### `read` — return raw file content

For ingestion by other skills (e.g. `planning-projects` Phase 0 research). Returns the whole file as text; the caller does its own parsing.

### `unify` — derive backlog candidates from this project's plans

Inputs: optional `--project <absolute-repo-path>` (default: the git top level), optional `--include-stale` (off by default — see the signal list below), optional `--write` (off by default — dry-run is the default behavior). There are no other flags.

**Plans source.** Always `<records home>/plans/`. There is no plans-dir override: the records home is the one place plans live.

It prints one line:

```
DRY-RUN|WRITE: N new entries, D duplicates skipped, C candidates
```

With `--write` it also appends the N new entries to `<records home>/backlog.md`.

**Do not execute this by hand.** `scripts/backlog-unify.py` implements it:

```bash
python3 "<planning-plugin>/skills/backlog/scripts/backlog-unify.py" --project <abs-path> [--write]
```

Reading plan files and comparing `Source` strings is decidable, so it is a script; the judgment left for a model is presenting the candidates and taking the user's decision.

The rest of this section is the CONTRACT the script implements, kept because an author reading a candidate needs to know where it came from. A missing `plans/` yields zero candidates, not an error. Each candidate's `Source` is `plans/<plan-filename> — <source_locator>` (em-dash, single space each side), and dedup drops any candidate whose `Source` is byte-identical to an existing entry's — exact equality, no fuzzy match, no token overlap; `add`'s duplicate-guard handles fuzzy titles. Parser rules: `../planning-projects/references/plan-parser.md`. Nothing is written without `--write`.

When `--write` is set, every new candidate is appended as a BL entry, with auto-filled fields:

- `Source:` the constructed `Source` string above
- `Opened:` today's ISO date
- `Reason:` one-line auto-summary including the signal — one of `status-unexecuted` (a task whose `Status:` is `[ ]`), `status-partial` (`[~]` — started but unfinished; residual work is still open work), `unchecked-open` (in a plan with no Status fields, an unchecked bullet outside Preflight, Decisions-in-force and gate blocks, in a stage not shown executed), `deferred-section` (a bullet under an explicit Deferred heading), or `stale-plan-unchecked` (an unresolved item in a plan older than 90 days by filename stamp, emitted only under `--include-stale`)
- `Next step:` `TBD — opened by unify on <date>; review and refine.`
- `Tags:` `auto-unified` plus the plan's filename date stamp as a tag (e.g. `2026-04-15`)

**Hard rules for `unify`:**

- Dry-run (no `--write`) is the default. Writes only happen on explicit confirm or `--write`.
- Dedup is exact `Source` equality. Never fuzzy. Never re-summarize an existing entry's text.
- `--include-stale` is **off by default**. Staleness comes from the plan's filename `YYYY-MM-DD` stamp — not git (the records home may not be a git working tree) and not mtime (a copy or rewrite resets it) — and a filename with no stamp is *unknown age*, never assumed stale. The flag only adds items the git-stage suppression hid; it never relabels ones the other signals already found. Full rules: `../planning-projects/references/plan-parser.md` § 3.
- Malformed or unparseable plan files are skipped with a one-line log entry; the run continues.
- Re-running `unify --write` immediately after the previous accept produces zero new candidates (idempotency by construction, because every accepted candidate's `Source` now lives in `docs/backlog.md` and matches by exact `Source` equality).

### `complete` — mark a backlog item implemented and archive a short summary

Inputs: `<BL-NNN>` (one ID at a time), `--summary "<one-paragraph text>"` (required, non-empty).

Operation:

1. Read `docs/backlog.md` and locate the `## BL-NNN` block. If absent: report `BL-NNN not found` and abort.
2. Capture the block's title from the heading line (`## BL-NNN — <title>`).
3. Slugify the title for the filename: lowercase, alnum + `-`, max 40 chars.
4. Write a new file at `<records home>/plans/YYYY-MM-DD-<slug>-done.md` (today's date; same records home as the backlog) with this template:
   ```markdown
   # Done: <title>
   Date: <YYYY-MM-DD>
   Source backlog ID: BL-NNN (removed in the same commit)

   ## Summary
   <the --summary text, verbatim>

   ## Context
   - **Opened:** <Opened field from BL block>
   - **Originating source:** <Source field from BL block>
   - **Tags:** <Tags field from BL block, if present>
   ```
5. Invoke the existing `remove` op on `BL-NNN` to delete the block from `docs/backlog.md`.
6. Report: `Completed BL-NNN — wrote <records home>/plans/<filename>-done.md, removed from backlog.`

**Hard rules for `complete`:**

- `--summary` is required and must be non-empty after whitespace trim. Reject the call otherwise.
- One BL-ID per call. Never batch.
- The commit that lands this work should include `Closes BL-NNN` so the audit trail in `git log` is consistent with the existing convention.
- The `*-done.md` file lives in `<records home>/plans/` so it is co-located with active plans but visually distinguished by the `-done.md` suffix. It is *not* an active plan; orchestrator tools should treat it as a historical record (parsers may skip files matching `*-done.md`).
- Never re-open: if a `*-done.md` exists for a slug and `complete` is invoked again with the same slug, append a numeric suffix (`-done-2.md`) rather than overwriting.

---

## Integration

- **executing-plans** — calls `add` for what § What belongs here admits: a significant improvement, a non-urgent decision, or a task the user chose to skip after a Red-Green cycle budget exhausted. A stage gate exposing a defect is never routed here — that gets fixed and its class swept, per `../executing-plans/SKILL.md` § *A bug found during execution is a class* and § *Exit criterion*. Calls `remove` in Phase Close-out for every backlog item the executed plan implemented (the closing report should list them by ID).
- **planning-projects** — calls `read` in Phase 0 (Research). Open entries whose `Tags` or `Source` touch the new plan's scope are surfaced to the user; they decide which fold into the new plan vs. remain deferred. Plan tasks that resolve a backlog item should reference it (`Closes BL-NNN`) so executing-plans knows what to remove on close-out.
- **Ad-hoc** — invoke directly via natural language ("add to backlog: ...", "list backlog", "BL-NNN is done, remove it").

---

## Safety rails

- **Do not assume the file is recoverable.** The records home may not be a git working tree, so the closing commit (`Closes BL-NNN`) is the audit trail and there may be no archive where the file sits.
- Don't `rm` it, don't rewrite it whole — only append/remove discrete blocks.
- Never auto-remove from a "looks implemented" heuristic — only on explicit instruction or `Closes BL-NNN` declared in a plan's Close-out.
- Preserve unrelated entries byte-for-byte during any edit. **Prove it by counting** (`remove` step 3) rather than by inspecting: missing `---` separators are the normal state of a file that has been appended to for a while, not a sign of corruption, so a guard that waits for them to look wrong never fires. Duplicate IDs are still worth stopping on.

## Remember

- Append on defer, remove on implement, list on research.
- The backlog admits improvements, non-urgent decisions, and explicitly-deferred work — never a defect found during plan execution. `add` refuses those; see § What belongs here.
- IDs are immutable and never reused.
- The closing commit — not an in-file archive — records what was closed and why.
