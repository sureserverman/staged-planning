---
type: regex
target:
  source: file
  path: docs/plans/2026-01-15-notes-check-light-plan.md
pattern: '^(?=(?:[\s\S]*?\n[ \t]*-[ \t]*\*\*Status:\*\*[ \t]*\[[xX]\]){2})(?=[\s\S]*\n[ \t]*-[ \t]*\[[ ~]\][^\n]*qzx-gatecheck)'
---

Both task Status boxes are ticked `[x]`, and the `qzx-gatecheck` gate check is still in the
plan, open `[ ]` or BLOCKED `[~]`. Without the second half, deleting or rewording the check
would pass gate-not-ticked by removing what it reads; without the first, a session that did
nothing would pass.
