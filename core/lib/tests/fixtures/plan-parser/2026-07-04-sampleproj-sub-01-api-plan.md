# Project Plan: Sampleproj API service
Date: 2026-07-04
Master: ./2026-07-04-sampleproj-master-plan.md

## Research Summary

Scoped to the API sub-plan.

## Preflight

- [ ] PREFLIGHT-MARKER: toolchain installed

---

## Stage 1: Contract

**Goal:** v2 contract implemented.
**Depends on:** none
**Blocks:** none
**Risk:** LOW — prior art.
**Rollback:** revert commits.

### Task 1.1: Implement v2 endpoint
- **Status:** [x]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Parallel:** YES
- **Test:** `pytest tests/test_v2.py`
- **Red-Green max cycles:** 3
- [x] scaffold the handler
- [x] wire the router
- [ ] STRAY-LEFTOVER: forgotten body bullet in a DONE task — Status [x] must suppress it

### Task 1.2: Harden the endpoint
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Parallel:** NO (blocked by 1.1)
- **Test:** `pytest tests/test_v2_hardening.py`
- **Red-Green max cycles:** 3
- [ ] SUB1-CANDIDATE-A: add retry logic to the upload handler
- [ ] SUB1-CANDIDATE-B: rate-limit the v2 endpoint

### Stage 1 Gate
- [ ] GATE-MARKER-SUB1: full suite passes

## Deferred

- SUB1-DEFERRED-A: telemetry for the retry path
