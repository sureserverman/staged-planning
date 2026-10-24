# Execution state contract, version 2

This contract owns transitions; legacy phase fields are a read-only projection.
A snapshot is local metadata, never proof of product quality or authentication of
the operator.

## Interface and exits

`python3 scripts/plan-state.py OP --repo REPO --expected-revision N --operation-id ID`
reads a JSON object from stdin. `show` needs no mutation options. Payload fields below
are required unless marked optional. Unknown fields and operations are refused.
All responses are JSON objects containing `status`; mutation receipts also carry
`operation_id`, `run_id`, `revision` and `operation`. `show` returns `state`.

| Status | Exit | Meaning |
|---|---:|---|
| ok | 0 | Read or committed mutation; retry returns the original receipt |
| no_active_plan | 0 | No state and no owned active-run pointer |
| state_error | 3 | Corrupt, unsupported, insecure or ambiguous legacy state |
| conflict | 4 | Stale revision, ownership mismatch or changed operation payload |
| budget_exhausted | 2 | A new round exceeds recorded authority |
| strategy_review_due | 5 | Authored strategy checkpoint needs assessment |

The read-only `plan-progress.py --budget-check` does not reserve or consume a round.
An active round returns `ok` even at its ceiling. Missing state during an owned run
returns `state_error`, never `no_active_plan`. Stop hooks allow on instrument errors
with a diagnostic; mutation refusal stays independent of that escape behavior.
An owned run pointer prevents corrupt, missing or schema-removed snapshots from
being interpreted as idle/legacy state. Versioned continuation readers use the
shared 8 MiB snapshot bound; the earlier 256 KiB bound remains for legacy input.

## Snapshot and ownership

Required keys: `schema_version: 2`, UUID `run_id`, integer `revision`, `owner`
(canonical root, git-common-dir, git-dir, branch), `plan`, `phase`, `stage`, `task`,
`task_desc`, UTC `updated`, `gate`, `rounds`, `authorization`, `disposition`,
`qualification`, `blocker`, `strategy`, `receipts` and an integrity digest.
`rounds` contains `completed`, `budget` and nullable `active`. `gate` contains
`id`, `repair_revision` and nonempty declared `checks` while repairing.
A detached HEAD has no branch and owns no run: `show` there reports `no_active_plan`,
or `conflict` when this worktree's pointer names a run started on a branch, and every
other operation is a `state_error` until a branch is checked out.
Compatibility `remediation_round` is completed plus active; `remediation_budget`
is the current ceiling. Changing a gate cannot erase spent rounds: gate accounts
are retained. Disposition projects to existing public phase values.

One locked snapshot stores both state and receipts. Open the owning `.claude`
directory and files without following symlinks; use a 0600 lock and same-directory
0600 temporary snapshot, fsync the file, atomically replace, then fsync the directory.
No separate state/journal transaction is claimed. Refuse oversized, foreign-owned,
nonregular or multiply linked files. Integrity detects accidental manual edits; a
user who can forge all metadata is outside this tool's authentication boundary.

Common-dir run pointers are keyed by git worktree identity and contain only validated
owner identity and run id. Reconstruct the state path from the registered worktree;
never follow an arbitrary supplied state path. An unrelated worktree remains idle.
The common-dir pointer is discovery metadata, not a second authoritative journal.
Init and migrate write the snapshot first and the pointer second. An interruption
between them leaves a valid owned snapshot with no pointer: readers accept it, and the
next mutation, under the lock, republishes the pointer from that snapshot's validated
owner and run id, so a retried init returns its original receipt. A pointer without a
snapshot is never left by an interruption; it is a diagnosable state error. A deeply
nested payload or snapshot is a `state_error`, like any other unparseable input. `finish` retains the terminal snapshot/receipts until
explicit archival, and marks the run complete; no ambiguous counter is reset.

Every mutation compares expected revision under the lock. Operation ids bind the
operation and canonical payload digest. Retries match their original receipt before
checking a stale revision; a changed payload conflicts. A bounded receipt store never
evicts an id and later executes it again. The 256-receipt admission threshold refuses
new work with an explicit archive/new-run requirement. Already authorized verification,
re-verification, completion, structured blocking/owner amendments and `finish` remain
allowed; control metadata never bypasses admission of new work. The hard storage bound is
8 MiB; hitting it or a filesystem capacity limit reports an instrument error without
charging work or replacing the snapshot. Limits are published by the module.

## Operations

- `init`: plan, optional stage/task/description, budget (default 2), authorization
  source and scope. Revision 0 means absent; creates revision 1 and a new run id.
- `show`: validate and return the owned state without a mutation or receipt.
- `transition`: phase, optional stage/task/task_desc, optional gate (id,
  repair_revision, checks), optional qualification. Never accepts counters, receipts,
  authority or ownership from a caller. An active round prohibits switching gates.
  A changed repair revision clears active verification; completion binds the new one.
- `begin-round`: gate id; reserve exactly one round under recorded scope and ceiling.
  Concurrent beginnings cannot both succeed. Starting new work while waiting or
  complete is refused. The active round records the current authorization identity.
- `record-verification`: gate id, repair_revision, nonempty evidence reference,
  checks mapping declared check ids to passed/failed. Require exact check coverage;
  missing, wrong-gate and stale-code receipts cannot permit completion.
  The writer also binds a digest of raw tracked and untracked repair bytes,
  file modes, symlink targets, missing-file records and index identity;
  changed bytes invalidate completion even if the revision label is unchanged.
  Checked-out submodules are bound recursively (maximum depth 16); uninitialized,
  symlinked or unmerged submodules/indexes fail explicitly. Enumeration disables
  fsmonitor and never invokes diff or clean filters.
  Proof and `.claude` metadata are excluded; ignored dependencies require explicit
  declared checks. All hash record boundaries are length framed.
- `complete-round`: gate id; require current verification for every declared check.
  Failed verification is a completed assessment, recorded as failed, never green;
  completion advances the completed count once and retains its receipt and verdict.
- `authorize`: actual owner source (quote/reference), scope, optional explicit budget.
  A scope mismatch cannot extend the ceiling. No mutation can infer an extension
  from wording. Missing source or a ceiling smaller than spent/reserved work is refused.
  The ceiling covers this scope's current and saved gate accounts. A decrease
  below any account's completed/reserved work conflicts; an accepted amendment
  updates every account ceiling without resetting counts. Previous current/saved
  ceilings are retained in its receipt so switching gates cannot restore older authority.
- `set-blocker`: disposition, prevented operation, evidence, dependency and
  remaining_work (list of remaining runnable work). An external wait or owner decision is justified by these
  fields. A failed qualification alone is not a blocker. Cancellation is an explicit
  owner decision recorded with `cancelled: true` and `owner_source`. Resuming
  cancellation requires a fresh `authorize` source. `handoff` additionally requires
  the original measured `reason` and evidence reference, and may record the `handoff_id`
  that `handoff-envelope.py new-id` minted (`^h-[0-9a-f]{20}$`; optional, so a snapshot
  written before the field stays valid; refused on any other disposition). Resuming working/repairing
  clears the blocker with dependency-resolution evidence; ordinary transition
  cannot bypass it. Completing a reserved assessment does not clear a wait.
- `strategy-review`: authored checkpoint, typed observations (defect family,
  gain/false_rejection/cost or unknown), assessment and alternatives. Two completed
  rounds is the default checkpoint; already authorized diagnosis remains available.
  Assessment does not extend authority or reset spent work. Heuristics are advisory
  until independently calibrated; missing observations imply unknown.
  Payload fields are `gate_id`, `checkpoint: {after_completed, source}`,
  `observations: [{round, defect_families, verified_gain, false_rejections,
  cost_ms, evidence}]`, `assessment` and `alternatives: [{kind, scope, evidence}]`.
  Observation round numbers are unique and completed; numeric gain/cost must be
  finite and bounded in magnitude to 10^15, cost nonnegative, false-rejections a nonnegative count; absent measurements
  are null. Assessment is unknown, continue_repair, consider_redesign or owner_decision;
  alternative kind is repair/redesign/diagnosis and scope existing/new.
  An empty payload at two completed rounds returns strategy_review_due (exit 5)
  without changing state. Recording a reached authored checkpoint returns ok with
  an advisory summary; it never changes disposition, authority or round counts.
  A new-scope alternative flags owner_decision_required; it does not halt existing
  authorized diagnosis. Use set-blocker when the next actual operation needs that
  owner decision. Observation truth remains the trusted caller's responsibility.
  Empty-payload re-entry after that gate's recorded review returns its advisory
  assessment read-only instead of demanding a duplicate review.
  Advisory corpus audit-and-benign-v1 has two sequences (one audit trigger, one benign
  non-trigger; 1/2 trigger rate); this tiny deterministic corpus is not independent
  calibration and cannot justify raising severity or declaring a strategy impossible.
- `migrate`: legacy_evidence (source plus active/completed disposition and actual
  verification when completed), authorization and scope. Preserve counter/budget
  exactly; ambiguous positive counters refuse automatic migration. Unsupported v2
  or corrupt JSON cannot be migrated. No evidence means no fabricated verification.
  Legacy blocked/handoff phases additionally require `legacy_blocker` with original
  structured stop metadata (the set-blocker payload). They never migrate into runnable
  working state. The original blocker is retained in the migration receipt. All readers
  validate blocker shape and disposition/phase agreement even when integrity matches.
- `finish`: evidence of plan close-out; require no active round and explicit
  completion disposition. Publish terminal `complete`; leave qualification separate.

## Authority, experiments and premises

Dispositions: working, repairing, waiting_external, awaiting_owner_decision,
handoff, complete. Owner instructions survive interruption only in their recorded
scope. They do not authorize production changes, paid services or changed architecture.
Qualification is independent: pending/pass/no_go/blocked. No-go plus repairing is valid.
Measured handoff requires the original measurement reference and reason, and carries
its `handoff_id` when one was minted.

Experiment receipts keep candidate AND baseline, input/split/rubric identities,
dependency hashes, original receipt identity, evidence claim and separate runtime,
schema, semantic-support, useful-output and owner-preference denominator membership.
Synthetic/retrospective/prospective/live are separate claims. Environment failures
remain availability failures. Reuse requires every declared identity/hash unchanged
and labels attribution reused; ties/failures remain. No private payload belongs here.

An early premise record states the existing integration route, useful rendered output,
requirement origin and bounded evidence claim. A real local smoke demonstrates only
the local protocol; fixtures cannot close a live model-quality claim. The record stays on the
stage in the plan; Step 3.0 runs the early premise's smoke as a premise check and records it
in the worksheet. Unknown environment permits other
authorized runnable work while keeping the live claim open.
