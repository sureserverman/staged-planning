# Project Plan: ok master — sub-plan 1 (alpha)
Date: 2026-09-23
Master: ./ok-master-plan.md

## Stage 1: Build it

**Goal:** ok master — sub-plan 1 (alpha).
**Depends on:** none
**Blocks:** none

### Task 1.1: Write the module
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Dispatch:** YES
- **Scope:** `alpha/module.py`, `alpha/tests/test_module.py`
- **Test:** `pytest alpha/tests/test_module.py` exits 0

### Task 1.2: Wire it into the CLI
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Dispatch:** NO (blocked by 1.1)
- **Scope:** `alpha/cli.py`
- **Test:** `pytest alpha/tests/` exits 0

### Stage 1 Gate
- [ ] `pytest alpha/tests/` exits 0
