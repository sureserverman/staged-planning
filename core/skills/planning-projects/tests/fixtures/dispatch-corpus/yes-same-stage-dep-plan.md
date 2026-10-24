# Project Plan: Dispatch fixture — YES task with a same-stage dependency
Date: 2026-09-23

Negative fixture: Task 1.2 is `Dispatch: YES` but depends on Task 1.1 in its own stage,
so it is not ready when the stage opens.

## Stage 1: One stage

**Goal:** trip YES-SAME-STAGE-DEP.
**Depends on:** none
**Blocks:** none

### Task 1.1: Write the parser
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Dispatch:** YES
- **Scope:** `src/parser.py`
- **Test:** `pytest tests/test_parser.py` exits 0

### Task 1.2: Write the renderer on the parser
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `src/render.py`
- **Test:** `pytest tests/test_render.py` exits 0

### Stage 1 Gate
- [ ] `pytest tests/` exits 0
