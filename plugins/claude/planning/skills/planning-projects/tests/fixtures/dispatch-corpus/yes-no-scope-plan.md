# Project Plan: Dispatch fixture — YES task with no Scope
Date: 2026-09-23

Negative fixture: Task 1.2 is `Dispatch: YES` and declares no `Scope:`, so nothing
proves it is disjoint from its sibling.

## Stage 1: One stage

**Goal:** trip YES-NO-SCOPE.
**Depends on:** none
**Blocks:** none

### Task 1.1: Write the parser
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `src/parser.py`
- **Test:** `pytest tests/test_parser.py` exits 0

### Task 1.2: Tidy the docs
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Test:** `grep -c parser README.md` ≥ 1

### Stage 1 Gate
- [ ] `pytest tests/` exits 0
