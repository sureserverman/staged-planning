# Project Plan: standing rules fixture
Date: 2026-11-17

A synthetic plan for `owner-decision.py`: one standing answer for each of the four kinds,
beside one position entry. `check` passes it with no `note:` line, and
`match --plan <this file> --rule <kind>` lists the entry for that kind.

## Owner decisions

- **OD-1** — list the Outcome in the close-out report and go on to the merge step — owner, 2026-11-17: "List it and go on (Recommended)" — applies to: Rule unshown-outcome
- **OD-2** — file it in the backlog and go on — owner, 2026-11-17: "File it and go on (Recommended)" — applies to: Rule outside-defect
- **OD-3** — one more round when the cause of what remains is known, then stop if anything Critical is open — owner, 2026-11-17: "One more round (Recommended)" — applies to: Rule spent-rounds
- **OD-4** — amend the command, keep the old one beside it and go on — owner, 2026-11-17: "Amend and go on (Recommended)" — applies to: Rule wrong-check
- **OD-5** — the run works on a new branch — owner, 2026-11-17: "New branch here (Recommended)" — applies to: Preflight (`git switch -c feat/x`)

## Stage 1: one stage

**Goal:** g

### Task 1.1: t
- **Status:** [ ]
- **Test:** `true`

### Stage 1 Gate
- [ ] `true`
