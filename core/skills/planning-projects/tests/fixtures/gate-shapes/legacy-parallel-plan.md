# Project Plan: example-app theme tokens
Date: 2026-06-01

A synthetic plan for `test-validate-dispatch.py` group 6, in the shape plans had before
the `Dispatch:` field: the task field is spelled `Parallel:`, its value carries prose,
and YES tasks declare no `Scope:`. Dated before the cutover, so it must exit 0 silently;
with an earlier `--cutover` the same file fails YES-NO-SCOPE. Every name is invented.

## Stage 1: Token source

**Goal:** colours and spacing come from one token source.
**Depends on:** none

### Task 1.1: Extract the colour tokens
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.3
- **Parallel:** YES (adds `tokens/colours.json`; nothing else reads it yet)
- **Test:** `python3 tests/test_colour_tokens.py` exits 0

### Task 1.2: Extract the spacing tokens
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 1.3
- **Parallel:** YES (adds `tokens/spacing.json`; touches no shared file)
- **Test:** `python3 tests/test_spacing_tokens.py` exits 0

### Task 1.3: Generate the stylesheet from the tokens
- **Status:** [ ]
- **Depends on:** Task 1.1, Task 1.2
- **Blocks:** Stage 2
- **Parallel:** NO (needs both token files; one generator serves both)
- **Test:** `python3 tools/build_styles.py --check` exits 0

### Stage 1 Gate
- [ ] `python3 tools/build_styles.py --check` exits 0

## Stage 2: Consumers

**Goal:** no stylesheet hard-codes a colour.
**Depends on:** Stage 1 gate passing

### Task 2.1: The header bar
- **Status:** [ ]
- **Depends on:** Task 1.3
- **Parallel:** YES (edits `src/ui/header.css` alone)
- **Test:** `python3 tests/test_header.py` exits 0

### Task 2.2: The footer
- **Status:** [ ]
- **Depends on:** none (the Stage 1 gate covers it)
- **Parallel:** YES (edits `src/ui/footer.css` and its snapshot)
- **Test:** `python3 tests/test_footer.py` exits 0

### Task 2.3: Remove the hard-coded colours
- **Status:** [ ]
- **Depends on:** Task 2.1, Task 2.2
- **Parallel:** NO (sweeps every stylesheet once the two edits land)
- **Test:** `! grep -rlE '#[0-9a-f]{6}' src/ui/` prints nothing

### Stage 2 Gate
- [ ] `python3 -m pytest tests/` exits 0
