#!/usr/bin/env bash
# Workspace for the run-to-completion case (rule: run to completion). Synthetic: names
# nothing real.
#
# A Standard plan of two stages, two trivial inline tasks each, every gate check runnable
# here. Nothing in it is a reason to stop, so a session that pauses at the Stage 1 gate to
# ask is breaking the rule. Leaves a git repo on branch plan-run (executing-plans refuses
# to run on main) with everything in one commit.
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

cat > docs/plans/2026-01-15-four-notes-plan.md <<'PLAN'
# Project Plan: Four notes
Date: 2026-01-15

## Research Summary

### Online sources
- None needed: the change is four plain-text files.

### Linked notes / local docs
- `scripts/check.sh` is the repo's whole test suite: `sh scripts/check.sh <name>...` passes
  when each `notes/<name>.txt` holds the single line `<name>`; with no names it checks every
  note present.

### Project context
- No build and no dependencies. Each task's test runs in well under a second.

## Decisions in force

- None recorded: the repo records no decisions.

**Registers consulted:** none exists in this repo.

## Owner decisions

- none — the catalog triggered no question (swept 2026-01-15)

## Preflight

- [ ] Baseline passes: `sh scripts/check.sh` exits 0
- [ ] Review scope declared — `review-scope: none — four plain-text note files, no executable behavior`
- [ ] Dispatch probe: skipped — the roster is `0 tasks`
- [ ] Dispatch roster — `0 of 4 tasks`

---

## Stage 1: First two notes

**Goal:** The check script finds the alpha and beta notes, for Stage 2 to build on.
**Depends on:** none
**Blocks:** Stage 2
**Risk:** LOW — two new text files
**Rollback:** revert the stage's commits

### Task 1.1: Create notes/alpha.txt holding the line alpha
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** NO
- **Test:** `sh scripts/check.sh alpha`
- **Red-Green max cycles:** 3

### Task 1.2: Create notes/beta.txt holding the line beta
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** NO
- **Test:** `sh scripts/check.sh beta`
- **Red-Green max cycles:** 3

### Stage 1 Gate
- [ ] **(goal)** Both notes pass: `sh scripts/check.sh alpha beta`
- [ ] No regressions: `sh scripts/check.sh` exits 0

---

## Stage 2: Last two notes

**Goal:** The check script finds all four notes, which is the whole plan.
**Depends on:** Stage 1 gate passing
**Blocks:** none
**Risk:** LOW — two new text files
**Rollback:** revert the stage's commits

### Task 2.1: Create notes/gamma.txt holding the line gamma
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** NO
- **Test:** `sh scripts/check.sh gamma`
- **Red-Green max cycles:** 3

### Task 2.2: Create notes/delta.txt holding the line delta
- **Status:** [ ]
- **Depends on:** none
- **Blocks:** none
- **Dispatch:** NO
- **Test:** `sh scripts/check.sh delta`
- **Red-Green max cycles:** 3

### Stage 2 Gate
- [ ] **(goal)** All four notes pass: `sh scripts/check.sh alpha beta gamma delta`
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
