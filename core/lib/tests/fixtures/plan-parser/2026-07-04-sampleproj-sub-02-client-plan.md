# Project Plan: Sampleproj client migration
Date: 2026-07-04
Master: ./2026-07-04-sampleproj-master-plan.md

## Research Summary

Scoped to the client sub-plan.

## Preflight

- [ ] PREFLIGHT-MARKER: client toolchain installed

---

## Stage 1: Migrate calls

**Goal:** Client on v2.
**Depends on:** none
**Blocks:** none
**Risk:** LOW.
**Rollback:** revert commits.

### Task 1.1: Swap client to v2
- **Status:** [x]
- **Depends on:** none
- **Blocks:** none
- **Parallel:** YES
- **Test:** `npm test`
- **Red-Green max cycles:** 3
- [x] point client at v2
- [x] delete v1 shims

### Stage 1 Gate
- [x] GATE-MARKER-SUB2: e2e suite passes

**Completed:** 2026-07-04 — commits: abc1234
