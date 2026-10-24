# Project Plan: context-usage dead-weight fixture
Date: 2026-09-22

## Stage 1: Parser

### Task 1.1: Parse entries
- **Status:** [x]
- **Scope:** `src/parse/entries.py`, `tests/test-entries.py`
- **Test:** `python3 tests/test-entries.py` exits 0

## Stage 2: Parser errors — shares a file with Stage 1

### Task 2.1: Error paths
- **Status:** [ ]
- **Scope:** `src/parse/errors.py`
- **Test:** `python3 tests/test-entries.py` exits 0 with the error cases

## Stage 3: Docs — disjoint from Stage 1

### Task 3.1: README section
- **Status:** [ ]
- **Scope:** `docs/usage.md`
- **Test:** `grep -c 'entries' docs/usage.md` ≥ 1

## Stage 4: Release — no Scope anywhere

### Task 4.1: Bump the version
- **Status:** [ ]
- **Test:** the version mirror check exits 0
