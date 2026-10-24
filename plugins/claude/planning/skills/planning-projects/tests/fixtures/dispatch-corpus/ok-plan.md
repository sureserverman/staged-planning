# Project Plan: Dispatch fixture — clean
Date: 2026-09-23

Fixture for `test-validate-dispatch.py`: every field is consistent, so the validator exits 0.
It also carries the two shapes that must NOT be read as a shared scope (two different
`GUIDE.md` full paths; backticked prose inside a parenthetical), and exactly one NO task
that could be YES (Task 2.1) next to one that could not (Task 1.3).

## Stage 1: Two independent edits, then a join

**Goal:** exercise the YES/NO rules.
**Depends on:** none
**Blocks:** Stage 2

### Task 1.1: Edit the setup guide
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.3
- **Dispatch:** YES
- **Scope:** `widget/docs/setup/GUIDE.md` (§ `## Install`; `KNOWN_MODES` wording), `widget/docs/setup/options.md`
- **Test:** `grep -c 'KNOWN_MODES' widget/docs/setup/GUIDE.md` ≥ 1

### Task 1.2: Edit the usage guide
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.3
- **Dispatch:** YES
- **Scope:** `widget/docs/usage/GUIDE.md` (§ `## Install`), `widget/docs/usage/examples.md`
- **Test:** `grep -c 'KNOWN_MODES' widget/docs/usage/GUIDE.md` ≥ 1

### Task 1.3: Doc test pins both
- **Status:** [ ]
- **Depends on:** Task 1.1, Task 1.2
- **Blocks:** Stage 2
- **Dispatch:** NO (blocked by 1.1, 1.2)
- **Scope:** `widget/tests/test_docs.py`
- **Test:** `pytest widget/tests/test_docs.py` exits 0

### Stage 1 Gate
- [ ] `pytest widget/tests/test_docs.py` exits 0

## Stage 2: Release

**Goal:** bump and document.
**Depends on:** Stage 1 gate passing
**Blocks:** none

### Task 2.1: Write the changelog entry
- **Status:** [ ]
- **Depends on:** Task 1.3
- **Blocks:** none
- **Dispatch:** NO (blocked by 1.3)
- **Scope:** `widget/CHANGELOG.md`, `widget/README.md`
- **Test:** `grep -c '2.4.0' widget/CHANGELOG.md` ≥ 1

### Task 2.2: Bump the version
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Scope:** `widget/pyproject.toml`, `widget/src/widget/__init__.py`
- **Test:** `grep -c '2.4.0' widget/pyproject.toml` ≥ 1

### Stage 2 Gate
- [ ] `pytest widget/tests/` exits 0
