---
type: regex
target:
  source: file
  path: docs/plans/2026-01-15-four-notes-plan.md
pattern: '^\s*-\s*\[[xX]\][^\n]*check\.sh alpha beta gamma delta'
flags: m
---

The Stage 2 gate's goal check is ticked `[x]`: the run reached and passed the last gate,
not only the last task.
