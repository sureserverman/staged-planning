# Light plans

How `executing-plans` runs a `*-light-plan.md`. Format: `../../planning-projects/references/light-plan-format.md`.

A **light plan** (`*-light-plan.md`, format:
`../../planning-projects/references/light-plan-format.md`) is a single stage of 2–5
Status-carrying tasks with one gate. Execute it through the normal single-plan flow
below, with these deltas — the machinery **scales to the size of the job** rather than
running at full weight:

1. **Preflight is git-bootstrap + baseline tests only.** A light plan has no Preflight
   section; the "baseline tests pass" check lives in its single gate. Still do the git
   bootstrap (Phase 2 — a repo must exist for commit-per-task) and confirm the baseline
   is green before Stage 1. Nothing else to verify.
2. **No parallel dispatch.** Every task runs **inline in the main session**, in listed
   order, through the normal Red-Green loop. A light plan has no `Dispatch` field and no
   fan-out — do not invoke `dispatching-parallel-agents`. (A task may carry an optional
   `Depends on`; honor it as ordering.)
3. **One review, not per-task.** **Skip the Tier-1 per-task review** — unless the declared
   tier is `high`, which runs Tier-1 in every format for the **risk-listed tasks its
   declaration names** (see the note at the end of this item), or a task carries
   `Review: required`, the per-task opt-in that buys one task a review without raising the
   whole plan's tier. Instead, after the
   last task goes green and **before** the gate (this is a pre-gate check, not the gate
   itself — a light plan still has exactly one gate, its Stage 1 Gate), run **one**
   `planning:code-reviewer` (read-only) pass over the **whole plan diff** (`git diff`
   across all the light plan's commits). Handle its verdict exactly like the Tier-2 stage
   review: a **Critical** blocks close-out just as a Tier-2 Critical fails a gate (fix
   within the same discipline, re-run test + review), and Important findings are bound by the **exit criterion** (Step 3.5), so each one leaves the
   gate **fixed**, its class swept. A light
   plan is a small plan, not one where findings evaporate — and not one where they are filed
   instead of fixed, since a small diff is the cheapest place there is to repair a defect. Skip only on the usual opt-out /
   trivial-diff rules — so an entirely docs-only light plan skips it too (zero reviews is
   correct there, exactly as a docs-only task auto-skips Tier-1 in a Standard plan); the
   one review is guaranteed only when the plan's diff carries reviewable code. **This
   single pre-gate review IS the light plan's Tier-2 — do not also run a separate Step 3.5
   Tier-2 pass.** It keeps one real review in the loop without paying per-task review
   overhead on a handful of tasks.

   **This rule sets the review's *shape* only.** How many passes run, and whether an
   evaluator runs beside them, comes from the declared review-scope tier — see
   `../references/review-scope.md` § *Composing with the plan format*. A light plan whose diff is `high`
   still gets the second independent pass; it just gets it over the whole diff, and its demo
   evaluator at the gate when its stage has Outcomes. **And it
   still gets Tier-1 on the tasks its `high` declaration names**: Tier-1 belongs to the
   tier, not the format, so the "skip it" above is this item describing the
   `light`/`standard` case, not the format overriding `high`. A small
   plan doing a dangerous thing is the one case where a Light plan reviews per task — and
   even there it reviews the dangerous *task*, not all five.
4. **The evaluator follows the tier, not the format.** Whether the independent
   goal-evaluator runs — at the gate (Step 3.5) and at close-out (Phase Close-out step 3) —
   is decided by the review-scope table, not by this plan being Light: off at `none`, on at
   `light` and `standard` wherever a gate check carries `(judgment)` or the stage has
   `**Outcomes:**`, always on at `high`. A Light plan whose result nobody outside the code
   meets has no Outcomes and an all-command gate, so it runs no evaluator — but that is a
   consequence of what the plan contains, not an exemption the format grants. A `(judgment)` check is a check that needs a reader; being in a small
   plan does not make it need one less.
5. **Close-out is one stated bump.** Run the full suite one final time — unless the
   single gate's full-suite run was the last thing to execute with no commits landed
   after it, in which case that run counts as the close-out run (one full pass, not
   two). **Order the run so that exemption applies**: finish every review round and land
   every fix *before* the full pass, rather than running it and then invalidating it. A
   full run that a later fix invalidates was the wrong run to have started, and the
   repair is not another full run — a review fix re-verifies at **fix-scope**
   (`../../planning-projects/references/test-scope-tiers.md`), and the gate stands on that
   plus the full result already recorded. Read as a description rather than an
   instruction, this clause turns one required full pass into several. — reconcile the backlog (`Closes BL-NNN`), and append the `**Completed:**`
   line. For version bumps,
   apply a **single stated SemVer bump** to what changed and its mirror — in this repo,
   name the plugin's `.claude-plugin/plugin.json` **and** the root marketplace entry
   explicitly (that pair) rather than running the full mirror-grep ritual. State your call
   so the user can override.

**Everything else is unchanged from a Standard plan:** Status flips the moment a test is
green, a commit per green task, the Red-Green cycle budget and all Stop conditions,
run-to-completion (don't pause at the gate to ask permission), one handoff note at the
single gate, and the honest-gates integrity contract. A light plan is a small plan, not a
sloppy one.
