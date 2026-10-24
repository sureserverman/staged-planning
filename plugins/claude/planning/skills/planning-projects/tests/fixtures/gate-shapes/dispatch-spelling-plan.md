# Project Plan: example-app retry budget
Date: 2026-09-01

A synthetic plan for `test-validate-dispatch.py` group 6, in the `Dispatch:` spelling with
`Scope:` written as prose around its paths. Two YES tasks share a stage with disjoint
scopes, two NO tasks give their reason in prose, and Task 2.1 is a NO task with no
same-stage dependency and a disjoint scope — so it exits 0 and earns exactly one
could-be-YES note. Every name is invented.

## Stage 1: The budget

**Goal:** the worker retries within one budget.
**Depends on:** none

### Task 1.1: The budget setting
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.3
- **Dispatch:** YES
- **Scope:** `src/sync/config.py` and its schema test
- **Test:** `python3 tests/test_config.py` exits 0

### Task 1.2: The backoff helper
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.3
- **Dispatch:** YES
- **Scope:** new `src/sync/backoff.py`
- **Test:** `python3 tests/test_backoff.py` exits 0

### Task 1.3: Wire the budget into the worker
- **Status:** [ ]
- **Depends on:** Task 1.1, Task 1.2
- **Blocks:** Stage 2
- **Dispatch:** NO (blocked by 1.1, 1.2 — integrates both)
- **Scope:** the retry loop in `src/sync/worker.py`
- **Test:** `python3 tests/test_worker.py -k retry` exits 0

### Stage 1 Gate
- [ ] `python3 tests/test_worker.py -k retry` exits 0

## Stage 2: Reporting

**Goal:** the status command shows the budget.
**Depends on:** Stage 1 gate passing

### Task 2.1: Record the remaining budget
- **Status:** [ ]
- **Depends on:** none (opens with its stage)
- **Dispatch:** NO
- **Scope:** the state writer in `src/sync/state.py`
- **Test:** `python3 tests/test_state.py` exits 0

### Task 2.2: Show it in the status command
- **Status:** [ ]
- **Depends on:** Task 2.1
- **Dispatch:** NO (blocked by 2.1)
- **Scope:** `src/cli/status.py`
- **Test:** `python3 tests/test_status.py` exits 0

### Stage 2 Gate
- [ ] `python3 tests/test_status.py` exits 0
