---
name: workflow-spec
description: Use to capture, audit, or refresh behavior contracts (docs/workflows/) — user-visible flows with stable IDs, steps, and invariants. Triggers on "document the app's workflow", "capture the auth flow", "audit this diff against the workflow spec". Regression checklist after a non-trivial change.
---

# Workflow Spec

A workflow spec is a frozen, human-readable description of what an app *does* — entry points, flows, invariants, side effects — kept in `docs/workflows/`. It exists for one reason: to detect when a change silently drops or alters a behavior. Tests cover correctness of code that exists; the workflow spec covers existence of code that should.

**Announce at start:** "Using the workflow-spec skill — <capture|audit|refresh|list> on docs/workflows/<scope>."

---

## File layout

```
docs/workflows/
├── README.md          # index — one line per scope file
├── auth.md            # one file per logical scope (module, app, feature area)
├── billing.md
└── ...
```

One file per scope. Pick the scope at the level a human can hold in their head — "auth", "checkout", "admin-panel". Not per-endpoint (too fine), not per-app (too coarse for any non-trivial app).

`README.md` is a flat index — each entry is one line: `- [auth](auth.md) — login, signup, password reset, session handling.`

---

## Entry format

Every behavior is one block. IDs are stable and never reused.

```markdown
## WF-AUTH-003 — User logs in with email and password

- **Entry:** `POST /api/auth/login` → handler `src/auth/controller.ts::loginUser`
- **Preconditions:** User row exists; account not locked (`failed_attempts < 5`).
- **Steps:**
  1. Validate body against `LoginSchema` (zod).
  2. Look up user by email, case-insensitive.
  3. `bcrypt.compare` password vs stored hash.
  4. On mismatch → increment `failed_attempts`, return 401.
  5. On match → reset `failed_attempts`, mint JWT, set httpOnly cookie `session`, return 200 with `{ userId, displayName }`.
- **Postconditions:** Cookie `session` set (HttpOnly, Secure, SameSite=Lax, 7d TTL); `users.last_login_at` updated.
- **Side effects:** Audit log entry — `auth.login.success` or `auth.login.fail` with IP and user-agent.
- **Invariants:**
  - Password hash is never present in any response body.
  - `failed_attempts ≥ 5` → account locked for 15 minutes; further attempts return 423.
- **Last verified:** 2026-05-17 against commit `abc1234`
```

**ID rules:**

- Format `WF-<SCOPE>-<NNN>`. Scope is uppercase letters matching (or close to) the file name. NNN is zero-padded.
- IDs are immutable. If a behavior is removed, remove its block — don't recycle the ID.
- Plans reference IDs when they intentionally alter behavior: `Changes WF-AUTH-003 — passwordless login replaces bcrypt branch`.

**Required fields:** Entry, Steps, Postconditions, Last verified. The rest are encouraged but optional when genuinely empty (a read-only GET with no side effects can omit Side effects).

---

## Operations

### `capture` — generate a draft for a scope

Inputs: scope name, target paths (one or more directories or files), optional list of entry-point patterns (routes, CLI commands, IPC handlers, exported functions).

1. **Refuse to overwrite.** If `docs/workflows/<scope>.md` already exists, exit and tell the user to use `refresh` instead — capture is for greenfield documentation only.
2. **Inventory entry points.** Read the target paths and list everything that an external caller can invoke: HTTP routes, CLI subcommands, public exports, IPC handlers, scheduled jobs. Note source location for each.
3. **Trace each entry point** to its handler. For each distinct *flow* (not each branch — branches are encoded under Steps), draft one WF block with sequential IDs starting at 001.
4. **Mark uncertainty with `[?]`.** If a step can't be confidently traced (dynamic dispatch, runtime config, missing context), write the step with `[?]` and a one-line note. Don't guess silently.
5. **Save** `docs/workflows/<scope>.md` and append to `docs/workflows/README.md`.
6. **Stamp every block** with `Last verified: <today> against commit <current HEAD>`.
7. **Report to the user:** entry-point count, block count, `[?]` count. Tell them this is a *draft* — captured docs must be hand-reviewed before they become canonical. The skill produced a starting point, not a verified contract.

**Capture is read-only against the codebase.** It writes only to `docs/workflows/`.

### `audit` — regression checklist against a diff

Inputs: a diff scope (uncommitted, staged, branch vs base, or PR), and optionally a subset of workflow files (default: all of `docs/workflows/`).

1. **Compute the changed-files set** for the diff.
2. **For each WF block in scope:** identify the source symbols it names (`Entry` handler, files mentioned under `Steps`). Skip blocks whose symbols don't touch any changed file (mark them `Untouched`).
3. **For each block whose symbols touch a changed file**, classify:

   | Status | Meaning | Action |
   |---|---|---|
   | **Present** | Named entry and handler still exist; signature unchanged | Mark for manual review only if Steps reference changed lines |
   | **Moved** | Symbol exists but at a new path or with a new name | Surface old → new, ask the user to confirm + update the block |
   | **Modified** | Symbol exists, handler body changed | Manual review — does the change preserve documented Steps, Postconditions, Invariants? |
   | **Removed** | Named symbol no longer exists anywhere | **Likely regression.** Surface for explicit user confirmation — was this intentional? |
   | **Unverifiable** | Block uses `[?]` or symbol is dynamic | Note and skip; don't pass or fail |

4. **Output a triage table** keyed by WF-ID with Status, Evidence (file:line), and recommended Action.
5. **Do not edit any workflow file during audit.** Audit reports; the user (or `refresh`) writes.

**Audit is the regression-checklist pass.** Run it before merging any non-trivial change. `executing-plans` Phase Close-out invokes it automatically.

### `refresh` — re-verify and update timestamps

Inputs: one WF-ID, one file, or `--all`.

1. For each target block, walk the same trace `capture` would and compare to the block:
   - If the block still matches the code → update `Last verified: <today> against commit <current HEAD>`. No other edits.
   - If there's drift (steps don't match, signature changed) → surface the diff between block and code; ask the user whether to (a) update the block to match new code, (b) update the code to match the block, or (c) split into a new WF-ID and remove the old block.
2. Save only after user confirmation. Don't auto-resolve drift.

### `list` — show known workflow specs

Output: scope file, block count, oldest `Last verified` date, count of `[?]` items. Sorted by oldest verification first — that's the staleness leaderboard.

---

## Drift defense

The spec rots if it's never re-checked. Two mechanisms keep it honest:

1. **`Last verified` per block.** `list` surfaces the oldest. A heuristic threshold (default: any block older than 60 days OR older than 50 commits on the file it covers) is flagged as stale.
2. **Audit's `Removed` finding.** A behavior documented but no longer in the code is either an unintentional regression (fix the code) or an intentional removal (delete the block). Audit forces the choice — it never silently passes a `Removed`.

What the skill never does on its own:

- Never auto-edit a spec block to match drifted code. The spec is the contract; the code drifting from it is a finding, not a sync target.
- Never delete a block silently. Removal is always user-confirmed and traceable in git.
- Never extend the spec to cover code the user didn't ask to capture — scope is set by the user, not inferred from "well, this related thing also exists."

---

## Integration

- **planning-projects** — Phase 0 (Research) reads `docs/workflows/<scope>.md` files relevant to the plan's scope. New tasks that intentionally change a documented behavior reference the WF-ID: `Changes WF-AUTH-003`. New tasks that add behavior schedule a capture/extend step.
- **executing-plans** — Phase Close-out invokes `audit` against the cumulative diff of the executed plan. Findings are surfaced in the close-out report. Any `Changes WF-NNN` task is expected to update or replace the named block (verify in close-out); any `Removed` finding without a `Changes`/`Removes` declaration in the plan is treated as a regression and escalated before merge.
- **code-reviewer agent** — optional pre-merge invocation. Pass the audit triage table alongside the diff for an independent read.
- **backlog** — if `audit` surfaces drift the user defers, capture a `BL-NNN` entry naming the WF-IDs involved.

---

## Safety rails

- Workflow files are git-tracked human contracts. Treat them like prose, not like generated artifacts — preserve unrelated blocks byte-for-byte during any edit.
- Don't run `capture` on a scope that already has a file. Force `refresh` for updates so existing IDs and `Last verified` stamps survive.
- Don't infer Postconditions or Invariants from training intuition. If the code doesn't prove it, write `[?]` and leave the human reviewer to confirm.
- Audit reads code and reports; it does not modify code, tests, or workflow files.

## Remember

- One file per scope, one block per behavior, stable IDs, never reused.
- Capture is a draft; the human review makes it canonical.
- Audit triages a diff — Present / Moved / Modified / Removed / Unverifiable. `Removed` is the regression alarm.
- Drift is surfaced, not auto-resolved.
- Plans that change behavior must declare it (`Changes WF-NNN`); close-out verifies the block was updated.

---

## Sources and rationale

- **Behavior-as-contract** — Bertrand Meyer, *Object-Oriented Software Construction* (1997); preconditions/postconditions/invariants as the unit of specification, lifted from code to docs.
- **Stable IDs over prose** — same logic as test-case IDs in regulated industries (IEC 62304, ISO 26262): a triage that says "WF-AUTH-003 removed" is mechanically actionable; "the login flow changed" is not.
- **Capture is a draft, audit is the gate** — Karl Wiegers, *Software Requirements* (3rd ed.); spec docs that aren't reviewed by a human are decoration. The skill explicitly stops at draft and hands off.
- **`Last verified` stamps** — borrowed from runbooks / SOC2 evidence practice; a doc with no recency stamp is assumed stale.
