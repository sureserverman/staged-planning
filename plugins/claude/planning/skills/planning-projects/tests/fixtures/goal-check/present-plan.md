# Project Plan: goal-check fixture — (goal) check present
Date: 2026-10-08

## Stage 1: Build the thing

**Goal:** every skill file names its trigger.

### Task 1.1: Add triggers
- **Status:** [ ]
- **Test:** `python3 tests/test-triggers.py`

### Stage 1 Gate

- [ ] **(goal)** `! grep -L 'Triggers' skills/*/SKILL.md | grep -q .` — every skill file names its trigger
- [ ] No regressions: `bash scripts/run-tests.sh` exits 0
