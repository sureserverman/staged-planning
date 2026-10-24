# Light Plan: In-progress light plan fixture
Date: 2026-07-14

**Context:** Fixture for the Light plan format (`light-plan-format.md`). Proves a Light
plan takes the Status-authoritative path with zero parser changes: one candidate per
`[ ]` task, gate bullets excluded, a stray bullet in a done task suppressed, and Deferred
bullets still surfacing.

## Stage 1: Light lane

### Task 1.1: Author the reference doc
- **Status:** [x]
- **Test:** `grep -q 'Light Plan' light-plan-format.md`
- [ ] LIGHT-STRAY: leftover raw bullet inside a DONE task — must be suppressed

### Task 1.2: Add the parser fixture
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Test:** `python3 test-plan-parser.py`

### Task 1.3: Bump the version
- **Status:** [ ]
- **Depends on:** Task 1.2
- **Test:** `grep -c '"4.0.0"' plugin.json`
- **Red-Green max cycles:** 3

### Stage 1 Gate
- [ ] LIGHT-GATE-MARKER: integration check that must never surface as a candidate
- [ ] Full existing test suite passes

## Deferred

- LIGHT-DEFERRED-A: status badge for light plans
