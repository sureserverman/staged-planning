#!/usr/bin/env bash
# Workspace for the dispatch-mandated case (rule: dispatch without asking). Synthetic:
# names nothing real.
#
# A one-stage Standard plan whose two independent tasks are both `Dispatch: YES`, at review
# tier none, so the only dispatches the plan funds are those two tasks: no probe, no review,
# no evaluator. Leaves a git repo on branch plan-run (executing-plans refuses to run on
# main) with everything in one commit.
set -euo pipefail

# The eval runs this in a fresh workspace. Anywhere inside an existing repo it would
# re-point that repo's HEAD, so refuse there.
if git rev-parse --git-dir >/dev/null 2>&1; then
  echo "scaffold: refusing to run inside an existing git repo ($(pwd)); run it in an empty folder" >&2
  exit 1
fi

mkdir -p docs/plans scripts

cat > scripts/check.sh <<'SH'
#!/bin/sh
# The repo's whole test suite. `sh scripts/check.sh <name>...` passes when each
# notes/<name>.txt holds exactly the single line <name>. With no names it checks every
# notes/*.txt present, and passes when there is none.
set -eu
if [ "$#" -eq 0 ]; then
  for f in notes/*.txt; do
    [ -e "$f" ] || continue
    set -- "$@" "$(basename "$f" .txt)"
  done
fi
for n in "$@"; do
  if [ "$(cat "notes/$n.txt" 2>/dev/null)" != "$n" ]; then
    echo "FAIL: notes/$n.txt must hold the single line '$n'"
    exit 1
  fi
  echo "ok $n"
done
echo "check: $# note(s) passed"
SH

cat > docs/plans/2026-01-15-dispatched-notes-plan.md <<'PLAN'
# Project Plan: Dispatched notes
Date: 2026-01-15

## Research Summary

### Online sources
- None needed: the change is two plain-text files.

### Linked notes / local docs
- `scripts/check.sh` is the repo's whole test suite: `sh scripts/check.sh <name>...` passes
  when each `notes/<name>.txt` holds the single line `<name>`; with no names it checks every
  note present.

### Project context
- No build and no dependencies. The two tasks write different files, so they can run at
  the same time.

## Decisions in force

- None recorded: the repo records no decisions.

**Registers consulted:** none exists in this repo.

## Owner decisions

- none — the catalog triggered no question (swept 2026-01-15)

## Preflight

- [ ] Baseline passes: `sh scripts/check.sh` exits 0
- [ ] Review scope declared — `review-scope: none — two plain-text note files, no executable behavior`
- [ ] Dispatch probe: skipped — tier none
- [ ] Dispatch roster — `2 of 2 tasks`: [Task 1.1 → general-purpose, Task 1.2 → general-purpose]

---

## Stage 1: Two notes

**Goal:** The check script finds the alpha and beta notes, which is the whole plan.
**Depends on:** none
**Blocks:** none
**Risk:** LOW — two new text files
**Rollback:** revert the stage's commits

### Task 1.1: Create notes/alpha.txt holding the line alpha
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Test:** `sh scripts/check.sh alpha`
- **Red-Green max cycles:** 3

### Task 1.2: Create notes/beta.txt holding the line beta
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** YES
- **Test:** `sh scripts/check.sh beta`
- **Red-Green max cycles:** 3

### Stage 1 Gate
- [ ] **(goal)** Both notes pass: `sh scripts/check.sh alpha beta`
- [ ] Full clean test pass (plan-scope): `sh scripts/check.sh` exits 0
PLAN

printf '.claude/\n' > .gitignore

git init -q
git symbolic-ref HEAD refs/heads/plan-run
git config user.name "Eval Runner"
git config user.email "eval-runner@example.com"
git config commit.gpgsign false
git add -A
git commit -q -m "Initial commit: check script and plan"
