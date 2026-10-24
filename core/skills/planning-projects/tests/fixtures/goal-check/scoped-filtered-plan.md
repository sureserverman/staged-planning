# Project Plan: goal-check fixture — a filtered sweep the author scoped
Date: 2026-10-08

## Stage 1: Note every beta flag

**Goal:** every `beta` flag in the feature-flag table has a rollout note; `stable` flags are noted by another plan.

### Task 1.1: Write the rollout notes
- **Status:** [ ]
- **Test:** `python3 docs/check-rollout.py`

### Stage 1 Gate

- [ ] **(goal)** (scoped) `awk -F'|' '$2 ~ /beta/ {print $3}' docs/flags.md | sort | comm -23 - docs/noted-flags.txt | wc -l` prints 0 — the `beta` rows are this plan's whole set; `stable` rows belong to sub-plan 2
