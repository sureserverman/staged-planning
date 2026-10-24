# Light Plan: Decisions Context Line Parser Safety
Date: 2026-07-25
Format: Light — single stage, 2 tasks, one session

**Context:** Fixture proving a Light plan carries decisions inline. DEC-NNN binds this —
LIGHTCTX-MARKER constraint stated in half a line.

## Stage 1: Only stage

### Task 1.1: LIGHT-CANDIDATE-MARKER first task
- **Status:** [ ]
- **Test:** `true`

### Task 1.2: LIGHT-DONE-MARKER second task
- **Status:** [x]
- **Test:** `true`

### Stage 1 Gate
- [ ] LIGHTGATE-MARKER goal proven end-to-end
- [ ] Full existing test suite passes (regressions check)
- [ ] No change contradicts a decision in force (DEC-NNN)
