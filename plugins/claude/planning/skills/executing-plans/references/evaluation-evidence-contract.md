# Evaluation evidence contract v1

Use this ledger only for experiments that compare alternatives. Ordinary build tasks
do not need experiment receipts. The executor supplies an original metadata receipt;
the tool validates its format and byte identity, records it, and counts observations.
It neither runs inference nor judges semantic support, usefulness or owner acceptance.

## Original receipt and trust

Invoke `python3 scripts/evaluation-ledger.py record --repo ROOT --plan PLAN
--experiment EXPERIMENT` with JSON stdin `{ "original_receipt":
"proof/PLAN/originals/RESULT.json", "original_sha256": "<SHA256 of original bytes>" }`.
Paths are relative to the owning Git worktree; the original receipt must be exactly
`proof/PLAN/originals/RESULT.json`. Identifiers are bounded ASCII slugs;
no private payload, prompt, answer or free-text exception is accepted. Receipts must
be regular, singly linked, owned files reached without symlinks.

The original JSON has exactly these fields:

```json
{
  "schema_version": 1,
  "original_receipt_id": "result-1",
  "experiment_id": "experiment-1",
  "identity": {
    "candidate": {"id": "candidate", "sha256": "<64 lowercase hex>"},
    "baseline": {"id": "baseline", "sha256": "<64 lowercase hex>"},
    "evidence_hash": "<64 lowercase hex>",
    "split_hash": "<64 lowercase hex>",
    "rubric_hash": "<64 lowercase hex>",
    "dependencies": {"configuration": "<64 lowercase hex>"}
  },
  "evidence_class": "synthetic",
  "outcomes": {
    "candidate": {"availability": "available", "schema": "pass", "support": "pass", "useful": "unknown", "environment": "normal"},
    "baseline": {"availability": "available", "schema": "pass", "support": "pass", "useful": "unknown", "environment": "normal"}
  },
  "owner_preference": "unknown",
  "comparison": "tie"
}
```

The trusted experiment runner must compute the candidate, baseline, evidence, split,
rubric and dependency identities from the actual inputs and declare measured results.
This tool cannot authenticate a caller's assertions, owner identity, or source hashes
against arbitrary external systems. A checksum chain detects accidental ledger
changes; it is not a signature against a malicious owner who can rewrite everything.
Do not promote invented hashes or automated semantic labels into verified observations.

Evidence class is one of `synthetic`, `retrospective`, `prospective`, or
`live_local_protocol`. Keep each experiment's class and identity fixed. A disposable
application exercise establishes local protocol behavior, not live AI quality.

## Denominators

`summarize` takes empty JSON stdin and returns separate counts for each alternative:

| Observation | Eligible denominator | Values |
|---|---|---|
| Availability | All original results | available, unavailable, unknown |
| Parse/schema | Available outputs | pass, fail, unknown |
| Supported output | Available outputs with schema pass | pass, fail, unknown |
| Useful output | Available, schema-valid, supported outputs | pass, fail, unknown |
| Owner preference | Both alternatives available and schema-valid | candidate, baseline, tie, unknown |

Each metric reports eligible, observed, passed/failed, unknown and ineligible counts;
preference reports eligible, observed, ineligible and its four value counts. Missing
observations are explicit `unknown`, never omitted or counted as a failure. Unavailable
outputs require unknown schema/support/usefulness; schema failure requires unknown
support/usefulness. A usefulness pass requires support pass. Preference eligibility
does not itself establish actual owner input or acceptance.

Environment is explicitly `normal`, `failure`, or `unknown`, counted separately for
each alternative. The tool never classifies an outage from error-message wording.
Comparison is the original caller observation: candidate_win, baseline_win, tie or
unknown. Failed and tied comparisons remain in totals.

## Storage, reuse and failure

Writes are serialized by a lock on the evaluation directory itself, and are private,
fsynced atomic generations under `proof/PLAN/evaluation/EXPERIMENT.jsonl`. No lock file
is kept; a temporary file a killed writer leaves is removed by the next write. The
ledger and the original receipts are the only files the tool keeps under `proof/`, and
both are proof records a committed `proof/` admits. Both input and ledger are bounded
to 8 MiB; a deeply nested input is a `state_error`.
Every row retains the original byte hash, attribution and integrity chain. Duplicate
original IDs with unchanged bytes are idempotent; changed bytes or identities conflict.
Invalid/corrupt files remain available for diagnosis and are never reset.

`check-reuse --experiment TARGET` takes `{ "from_experiment": "ORIGINAL",
"original_receipt_id": "RESULT", "identity": { ...same complete identity... } }`.
Every bound identity must match. Reuse returns `reused` with original attribution and
comparison; it does not append a fresh result or alter a failed/tied observation.
Changed dependencies require a new experiment and new evaluation, not reuse.
If the target experiment already exists, its frozen identity and evidence class
must also match. A corrupt target refuses reuse and is preserved for diagnosis.

Every operation returns JSON: ok/reused exit 0, state_error exit 3, conflict exit 4.
No operation changes authorization, adoption, round accounting or product acceptance.
