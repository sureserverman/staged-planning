# Project Plan: Every task partial
Date: 2026-07-24

Lockstep guard for the authoritative-path detection regex. Every task here is
`[~]`. With that character missing from the detection class (but present in
STATUS_RE) this file would match nothing, fall through to the LEGACY heuristic,
and emit its gate bullet as a candidate instead of its task — a silent
mis-classification of the whole file, not just one line.

## Stage 1: Only partial tasks

### Task 1.1: ALLPARTIAL-A: in flight
- **Status:** [~]
- **Test:** `true`

### Stage 1 Gate
- [ ] ALLPARTIAL-GATE-MARKER: must never surface as a candidate
