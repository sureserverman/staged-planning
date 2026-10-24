# Project Plan: example-app export formats
Date: 2026-03-02

A synthetic plan for `test-validate-gate-checks.py` group 9. Its gate checks are built so
that every classification the validator has is present at a known count: 4 EXECUTABLE,
2 JUDGMENT, 1 SCOPED, 2 INSTANCE-SHAPED, 3 PROSE. Every name in it is invented.

## Stage 1: Export writers

**Goal:** every export format writes through one writer.
**Depends on:** none

### Task 1.1: One writer for every format
- **Status:** [ ]
- **Depends on:** none
- **Test:** `python3 tests/test_writers.py` exits 0

### Stage 1 Gate
- [ ] **(goal)** `! grep -rl 'legacy_write(' src/ tools/` prints nothing — every format uses the writer
- [ ] `python3 tests/test_writers.py` exits 0
- [ ] `grep -c 'WRITER_VERSION' src/export/writer.py` = 1 and no stray copies remain anywhere
- [ ] **(judgment)** the writer's error messages read clearly to a user — a sweep cannot prove it
- [ ] **(scoped)** `! grep -q '^## FMT-004 ' /records/plans/example-app/formats.md` — the id is unique within its one register
- [ ] the README no longer claims CSV is the only export format
- [ ] Integration holds end to end

## Stage 2: Export docs

**Goal:** every format is documented.
**Depends on:** Stage 1 gate passing

### Task 2.1: Document each format
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Test:** `python3 tests/test_docs.py` exits 0

### Stage 2 Gate
- [ ] **(goal)** `python3 tests/test_docs.py --all-formats` exits 0 — every format has a page
- [ ] **(judgment)** the format pages agree with each other in tone
- [ ] (Optional manual spot-check) open docs/formats/csv.md and follow its example by hand
- [ ] Every format page links back to the index
- [ ] The docs build stays green for every format
