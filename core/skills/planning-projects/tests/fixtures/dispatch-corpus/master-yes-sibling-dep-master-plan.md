# Master Plan: Dispatch fixture — YES entries that lean on a sibling
Date: 2026-09-23

Negative fixture for MASTER-YES-SIBLING-DEP. Sub-plan 2 hides a dependency:
`Depends on: none` with a prose excuse, `Parallel: YES`, but its gate reads a sibling's
output — a dependency the register never declared. Sub-plans 3 and 4 are the legal
fan-out shape and must NOT fail: `Depends on` orders the register (master-plans.md), so a
YES entry that depends on a shared prerequisite and gates on it (3), or on one reached
through its declared chain (4 → 3 → 1), runs in its own session once that lands.

## Sub-plans

### Sub-plan 1: One
- **Status:** [ ]
- **Plan:** ./master-yes-sibling-dep-sub-01-plan.md
- **Goal:** ship one.
- **Depends on:** none
- **Blocks:** Sub-plan 3, Sub-plan 4
- **Parallel:** YES

**Gate:**
- [ ] `pytest one/tests/` exits 0
- [ ] Sub-plan 3 can import `one/module.py` and call it unchanged.

### Sub-plan 2: Two
- **Status:** [ ]
- **Plan:** ./master-yes-sibling-dep-sub-02-plan.md
- **Goal:** ship two.
- **Depends on:** none (kept apart to keep the review small)
- **Blocks:** none
- **Parallel:** YES

**Gate:**
- [ ] `two/cli.py` prints the same count that Sub-plan 1's
      module returns for the sample input.

### Sub-plan 3: Three
- **Status:** [ ]
- **Plan:** ./master-yes-sibling-dep-sub-03-plan.md
- **Goal:** ship three.
- **Depends on:** Sub-plan 1
- **Blocks:** Sub-plan 4
- **Parallel:** YES

**Gate:**
- [ ] `pytest three/tests/` exits 0 against Sub-plan 1's shipped module
  <!-- amended per Sub-plan 2 review; the old value is kept in the log. Not a check. -->

### Sub-plan 4: Four
- **Status:** [ ]
- **Plan:** ./master-yes-sibling-dep-sub-04-plan.md
- **Goal:** ship four.
- **Depends on:** Sub-plan 3
- **Blocks:** none
- **Parallel:** YES

**Gate:**
- [ ] `pytest four/tests/` exits 0 against Sub-plan 1's module and Sub-plan 3's
