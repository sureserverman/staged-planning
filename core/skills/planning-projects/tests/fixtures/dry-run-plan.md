# Project Plan: dry-run fixture — a Standard plan that records its dry run
Date: 2026-11-17

## Research Summary

A synthetic plan for test-validate-gate-checks.py: one HIGH-risk stage the dry run's
`Premises:` line names, and one LOW-risk stage it need not name.

## Preflight

- [ ] Tools: `python3 --version` answers
- [ ] Baseline: `python3 tests/run_all.py` exits 0

**Test-scope commands:**
- stage-scope: `python3 tests/run_all.py`
- plan-scope: `python3 tests/run_all.py`

**Dry run** (2026-11-17, at 0123abc on `main`):
- Preflight: 2 of 2 checks run now. `python3 --version` printed 3.12.3; the baseline exits 0.
- Commands: `python3 tests/test_widget.py` resolves and its file exists; `tests/test_gadget.py`
  is created by Task 2.1.
- Premises: Stage 1 — the vendor API answers a signed request — `curl -sf <endpoint>/health`
  returned 200 — holds.

---

## Stage 1: Talk to the vendor API

**Goal:** the widget reaches the vendor API.
**Depends on:** none
**Blocks:** Stage 2
**Risk:** HIGH — the vendor API is outside this code
**Rollback:** `git revert` the stage's commits

### Task 1.1: Call the API
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** Task 2.1
- **Dispatch:** NO (one task)
- Sends a signed request.
- **Test:** `python3 tests/test_widget.py` — the request is signed (red if the signature is dropped)
- **Red-Green max cycles:** 3

### Stage 1 Gate
- [ ] Every widget test passes: `python3 tests/run_all.py`

## Stage 2: Show the result

**Goal:** the gadget shows the reply.
**Depends on:** Stage 1 gate passing
**Blocks:** none
**Risk:** LOW — display only
**Rollback:** `git revert` the stage's commits

### Task 2.1: Show it
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Dispatch:** NO (one task)
- Shows the reply.
- **Test:** `python3 tests/test_gadget.py` — the reply is shown (red if it is not)
- **Red-Green max cycles:** 3

### Stage 2 Gate
- [ ] **(goal)** Every test passes: `python3 tests/run_all.py`
