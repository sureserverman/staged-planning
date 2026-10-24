# Master Plan: Decisions Section at Master Level
Date: 2026-07-25

## Research Summary

Fixture: a master plan carrying `## Decisions in force` above its register.

## Decisions in force

- DEC-NNN — MASTERDEC-MARKER entry (accepted; security) — constraint in one line
- DEC-NNN — MASTERDEC-MARKER listed-register entry (accepted; security; from a resolver-listed register) — constraint in one line

**Registers consulted:** `decisions.md`; one resolver-listed register

## Sub-plans

### Sub-plan 1: First
- **Status:** [ ]
- **Plan:** ./2026-07-25-decisions-standard-plan.md
- **Goal:** fixture entry
- **Depends on:** none
- **Blocks:** Sub-plan 2
- **Parallel:** YES

**Gate:**
- [ ] MASTERDECGATE-MARKER integration check

### Sub-plan 2: Second
- **Status:** [ ]
- **Plan:** ./2026-07-25-decisions-light-plan.md
- **Goal:** fixture entry
- **Depends on:** Sub-plan 1
- **Blocks:** none
- **Parallel:** NO (blocked by Sub-plan 1)

**Gate:**
- [ ] MASTERDECGATE-MARKER cross-plan check
