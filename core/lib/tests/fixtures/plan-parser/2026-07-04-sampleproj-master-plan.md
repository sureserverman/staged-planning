# Master Plan: Sampleproj rollout
Date: 2026-07-04

## Research Summary

Shared findings for both sub-plans: the API contract is v2, the client pins it.

## Sub-plans

### Sub-plan 1: API service
- **Status:** [x]
- **Plan:** ./2026-07-04-sampleproj-sub-01-api-plan.md
- **Goal:** The v2 API serves the new contract end-to-end.
- **Depends on:** none
- **Blocks:** Sub-plan 2
- **Parallel:** YES

**Gate:**
- [ ] MASTER-GATE-MARKER-A: contract tests pass against the deployed API
- [ ] MASTER-GATE-MARKER-B: no regressions in v1 endpoints

### Sub-plan 2: Client migration
- **Status:** [ ]
- **Plan:** ./2026-07-04-sampleproj-sub-02-client-plan.md
- **Goal:** The client consumes v2 exclusively.
- **Depends on:** Sub-plan 1
- **Blocks:** none
- **Parallel:** NO (blocked by Sub-plan 1)

**Gate:**
- [ ] MASTER-GATE-MARKER-C: end-to-end flow green across API + client
