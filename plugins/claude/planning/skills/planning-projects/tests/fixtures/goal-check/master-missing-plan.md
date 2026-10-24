# Master Plan: goal-check fixture — one register entry lacks a (goal) check
Date: 2026-10-08

## Sub-plans

### Sub-plan 1: Schemas
- **Status:** [ ]
- **Plan:** ./sub-01-plan.md
- **Goal:** every API route has a schema.
- **Depends on:** none

**Gate:**
- [ ] **(goal)** `python3 tools/check-schemas.py --all-routes` exits 0 — every API route has a schema

### Sub-plan 2: Client
- **Status:** [ ]
- **Plan:** ./sub-02-plan.md
- **Goal:** the generated client matches the schemas.
- **Depends on:** Sub-plan 1

**Gate:**
- [ ] `python3 tools/build-client.py --check` exits 0
