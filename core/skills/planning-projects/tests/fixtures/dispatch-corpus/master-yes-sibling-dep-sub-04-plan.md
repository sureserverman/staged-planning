# Project Plan: sibling-dep master — sub-plan 4
Date: 2026-09-23
Master: ./master-yes-sibling-dep-master-plan.md

## Stage 1: Build it

**Goal:** sibling-dep master — sub-plan 4.
**Depends on:** none
**Blocks:** none

### Task 1.1: Write the module
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Dispatch:** YES
- **Scope:** `four/module.py`, `four/tests/test_module.py`
- **Test:** `pytest four/tests/test_module.py` exits 0

### Task 1.2: Wire it into the CLI
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Dispatch:** NO (blocked by 1.1)
- **Scope:** `four/cli.py`
- **Test:** `pytest four/tests/` exits 0

### Stage 1 Gate
- [ ] `pytest four/tests/` exits 0
