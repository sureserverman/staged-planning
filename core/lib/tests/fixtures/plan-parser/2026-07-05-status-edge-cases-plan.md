# Project Plan: Status-path edge cases
Date: 2026-07-05

Edge-case fixture for the authoritative path: a task with no enclosing Stage
header (locator must be the bare `Task N.N` form) and a malformed task carrying
two Status lines (must emit exactly one candidate).

### Task 0.1: EDGE-NOSTAGE: task before any stage header
- **Status:** [ ]
- **Test:** `true`

## Stage 1: Real stage

### Task 1.1: EDGE-DOUBLE: malformed task with two Status lines
- **Status:** [ ]
- **Status:** [ ]
- **Test:** `true`
