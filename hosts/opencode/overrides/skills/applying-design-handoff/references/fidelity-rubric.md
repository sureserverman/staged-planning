# Fidelity rubric — "reproduced precisely"

How a redesign is graded against the handoff pack after implementation. Generation and
evaluation are **separated on purpose**: the session that wrote the code grades its own
work too generously. The evaluator sees only the **normalized pack**
([handoff-pack-format.md](handoff-pack-format.md)), this rubric, and the captured result —
never the implementation transcript. Captures are real renders: **Playwright screenshots
per breakpoint** on browser-renderable stacks (plus the pack's reference render alongside
where it carries one — see [playwright-capture.md](playwright-capture.md)), the platform's
own capture on native stacks, and the final code/state only when no render path exists.

Grade only the dimensions the pack can support: if the pack carried no `layout`, layout
fidelity is *N/A* and its weight is redistributed proportionally across the gradeable
dimensions. Record which dimensions were gradeable.

## Dimensions and weights

| # | Dimension | Weight | What it measures |
|---|-----------|--------|------------------|
| 1 | **Token fidelity** | 30 | Rendered colors, type scale, spacing, radius, shadow match the pack's `tokens` — exact values, not "close". Hardcoded one-offs that bypass tokens are deductions. |
| 2 | **Layout fidelity** | 30 | Region tree, ordering, alignment, and responsive breakpoints match the pack's `layout` per screen. |
| 3 | **Component fidelity** | 25 | Each component's anatomy, variants, and states match the pack's `components` spec. Missing variant/state = deduction. |
| 4 | **Behavior-reconciliation completeness** | 15 | Every design/behavior conflict was resolved per the *design-wins-with-gates* rule: reconciliation report exists, each destructive change is declared (`Changes/Removes WF-*`) and signed off, nothing silently dropped. |

Weights sum to **100**.

## Scoring and threshold

- Score each gradeable dimension 0–100, then take the weighted average (renormalizing
  weights if any dimension is N/A).
- **Pass threshold: 85.** Below threshold → produce a fix list (smallest change that
  raises the lowest-scoring dimension first), re-implement, re-capture, re-grade.
- **Max 3 iterations.** If still below 85 after 3, present to the user with per-dimension
  scores and the remaining fix list instead of looping — do not silently continue.

## Fix-list format

Each item: `dimension → exact-deviation → smallest-fix → file:locus`. Order by
(lowest dimension score first, then largest single deviation). One fix targets one
deviation; re-grade after the batch, not after each item.

This is the generator–evaluator loop shape:
four weighted dimensions, a pass threshold, a capped iterate loop, and an evaluator
that never sees the generator's work. On OpenCode this file is the only grading rubric
the package ships, and the evaluator (a fresh `general` agent) is briefed with it.
