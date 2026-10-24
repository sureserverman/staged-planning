# Project Plan: Dispatch fixture — stage dependency cycle
Date: 2026-09-23

Negative fixture: Stage 1 waits on Stage 3's gate and Stage 3 waits (through Stage 2)
on Stage 1's, so no stage can ever open.

## Stage 1: First

**Goal:** trip STAGE-CYCLE.
**Depends on:** Stage 3 gate passing
**Blocks:** Stage 2

### Task 1.1: Do the first thing
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `src/a.py`
- **Test:** `pytest tests/test_a.py` exits 0

### Stage 1 Gate
- [ ] `pytest tests/` exits 0

## Stage 2: Second

**Goal:** the middle link.
**Depends on:** Stage 1 gate passing
**Blocks:** Stage 3

### Task 2.1: Do the second thing
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `src/b.py`
- **Test:** `pytest tests/test_b.py` exits 0

### Stage 2 Gate
- [ ] `pytest tests/` exits 0

## Stage 3: Third

**Goal:** closes the loop.
**Depends on:** Stage 2 gate passing
**Blocks:** Stage 1

### Task 3.1: Do the third thing
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `src/c.py`
- **Test:** `pytest tests/test_c.py` exits 0

### Stage 3 Gate
- [ ] `pytest tests/` exits 0
