# Master Plan: Dispatch fixture — clean master
Date: 2026-09-23

Fixture: a clean register. Sub-plan 1 runs in its own session (`Parallel: YES` — the
register field keeps that spelling and must never earn a note); Sub-plan 2 waits on it,
and only a NO entry's gate may name a sibling.

## Sub-plans

### Sub-plan 1: Alpha
- **Status:** [ ]
- **Plan:** ./ok-master-sub-01-plan.md
- **Goal:** ship alpha.
- **Depends on:** none
- **Blocks:** Sub-plan 2
- **Parallel:** YES

**Gate:**
- [ ] `pytest alpha/tests/` exits 0 — Sub-plan 1's module imports cleanly

**Sub-plan 1 handoff:** Sub-plan 2 inherits the alpha module; prose after the gate
block is not part of the gate.

### Sub-plan 2: Beta
- **Status:** [ ]
- **Plan:** ./ok-master-sub-02-plan.md
- **Goal:** ship beta on alpha.
- **Depends on:** Sub-plan 1
- **Blocks:** none
- **Parallel:** NO (blocked by Sub-plan 1)

**Gate:**
- [ ] `pytest alpha/tests/ beta/tests/` exits 0 — beta consumes Sub-plan 1's module

## Master gate

- [ ] `pytest` exits 0 across Sub-plans 1 and 2
