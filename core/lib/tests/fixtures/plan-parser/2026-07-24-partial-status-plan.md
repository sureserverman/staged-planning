# Project Plan: Partial-status contract
Date: 2026-07-24

Fixture for the `[~]` partial state. Covers all three Status
characters in one plan so the done/open/partial split is asserted together:
`[x]` emits nothing, `[ ]` emits `status-unexecuted`, `[~]` emits
`status-partial`. A parser that matches nothing for `[~]` drops the task from
both done and total.

## Stage 1: Mixed states

### Task 1.1: PARTIAL-DONE: finished task
- **Status:** [x]
- **Test:** `true`

### Task 1.2: PARTIAL-OPEN: never started
- **Status:** [ ]
- **Test:** `true`

### Task 1.3: PARTIAL-INFLIGHT: started but unfinished
- **Status:** [~]
- **Test:** `true`

### Stage 1 Gate
- [ ] PARTIAL-GATE-MARKER: must never surface as a candidate
