# Project Plan: Dispatch fixture — the retired `Parallel:` spelling
Date: 2026-09-10

Fixture: a clean plan written with the task-level `Parallel:` field. Dated before the
default cutover, so it is silent by default; run with an earlier `--cutover` it earns
the retired-spelling note. Either way it exits 0 — the old spelling is still read.

## Stage 1: One stage

**Goal:** exercise the old spelling.
**Depends on:** none
**Blocks:** none

### Task 1.1: Write the parser
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Parallel:** YES
- **Scope:** `src/parser.py`
- **Test:** `pytest tests/test_parser.py` exits 0

### Task 1.2: Write the renderer on the parser
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Parallel:** NO (blocked by 1.1)
- **Scope:** `src/render.py`
- **Test:** `pytest tests/test_render.py` exits 0

### Stage 1 Gate
- [ ] `pytest tests/` exits 0
