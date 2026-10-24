# Project Plan: goal-check fixture — sweeps restricted by a category filter
Date: 2026-10-08

## Stage 1: Note every flag

**Goal:** every flag in the feature-flag table has a rollout note.

### Task 1.1: Write the rollout notes
- **Status:** [ ]
- **Test:** `python3 docs/check-rollout.py`

### Stage 1 Gate

- [ ] **(goal)** `awk -F'|' '$2 ~ /beta/ {print $3}' docs/flags.md | sort | comm -23 - docs/noted-flags.txt | wc -l` prints 0 — every beta flag has a rollout note
- [ ] `git ls-files 'docs/*.md' | grep -v '^docs/archive/' | xargs grep -L 'Status:' | wc -l` prints 0 — every doc carries a status
- [ ] `grep -rL 'Status:' docs/ | wc -l` prints 0 — every doc carries a status, unfiltered
- [ ] `python3 docs/check-rollout.py | grep -q 'OK'` — the checker reports OK
