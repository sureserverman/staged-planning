# Project Plan: Dispatch fixture — two YES tasks share a file
Date: 2026-09-23

Negative fixture: Tasks 1.1 and 1.2 are both `Dispatch: YES` in one stage and both
touch `cache-sync.py` — one names it by full path, the other by bare filename.

## Stage 1: One stage

**Goal:** trip YES-SHARED-SCOPE.
**Depends on:** none
**Blocks:** none

### Task 1.1: Add the retry window
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `widget/scripts/cache-sync.py`, `widget/tests/test_cache_sync.py`
- **Test:** `pytest widget/tests/test_cache_sync.py` exits 0

### Task 1.2: Add the dry-run flag
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `cache-sync.py` (`--dry-run`), `widget/docs/usage/sync.md`
- **Test:** `python3 widget/scripts/cache-sync.py --dry-run` exits 0

### Stage 1 Gate
- [ ] `pytest widget/tests/test_cache_sync.py` exits 0
