# Master plans

How `executing-plans` runs a `*-master-plan.md`. Format: `../../planning-projects/references/master-plan-format.md`.

A master plan links 2–7 **sub-plans** — each a standard planning-projects plan in the
same directory — through a `## Sub-plans` register carrying per-entry `Status`, `Plan`
link, `Goal`, `Depends on` / `Blocks`, `Parallel`, and a `**Gate:**` block of cross-plan
integration checks.

**Critique (master-level Phase 1).** Before executing anything: every register `Plan:`
link resolves to an existing file; register `Depends on` / `Blocks` fields are symmetric
and acyclic; every entry ends with a `**Gate:**` block; every sub-plan carries the
`Master:` backlink and is itself a valid planning-projects plan (critique each one on
load, as usual). Surface concerns before starting.

**Step 4a applies here too** — run `python3 <planning-plugin>/skills/planning-projects/scripts/validate-gate-checks.py` on the master itself, not only
on each sub-plan as it loads. A master's cross-plan checks live under `**Gate:**` markers
rather than `### Stage N Gate` headings, and those are precisely the checks that prove
integration *between* sub-plans, so an instance-shaped one there survives every sub-plan
gate and surfaces only at the master close-out — the most expensive place to find it.

**Execution model:**

1. **Order by the register graph.** A sub-plan is dispatchable when every entry in its
   `Depends on` is `[x]`. Execute it via the normal single-plan flow — its own
   Preflight, stages, Red-Green loops, gates, and close-out. `Parallel: YES` sub-plans
   with no repo/file overlap may run concurrently (separate sessions or worktrees), but
   the file-conflict rule applies at this level too: overlapping sub-plans run
   sequentially regardless of the graph. At each of the sub-plan's stage gates, a sub-plan's
   gate evaluator is also briefed with its master register Goal, beside the sub-plan's own
   goal (`stage-gate.md` § Independent evaluator for non-command checks): the register Goal
   is what the next sub-plan reads the output against.
2. **A sub-plan boundary continues on Cursor.** Each sub-plan is a natural context-reset
   boundary (the trunk's Context resets at stage boundaries, scaled up), and the measured
   rule hands off there unless context is under 25%. On Cursor nothing measures the
   context: `context-usage.py` does not ship, because no store Cursor writes records the
   context a session uses. So after the `"Sub-plan N green"` commit (item 3) the next
   sub-plan opens now, unless a dated wait (`session-handoff.md`, rule 5) hands off.
   **What this costs:** on Cursor a whole master plan runs in one session with no measured
   reset. A user who wants the reset starts a fresh session at any `"Sub-plan N green"`
   commit; the master file below is everything it needs. On a dated-wait `handoff`, write
   the `RESUME HERE` block under the register entry, set `phase: "handoff"` and stop,
   naming the master path for the fresh session (`session-handoff.md`). The master
   file — register `Status` flips plus its handoff notes — is the cross-session handoff
   artifact; a fresh session needs the master, the next sub-plan, and nothing else.
3. **On a sub-plan's close-out** — once the sub-plan file carries a terminal marker — flip the
   master register entry's `- **Status:** [ ]` to `[x]`, run that entry's `**Gate:**`
   checks (they prove integration with previously completed sub-plans — a failure here
   is handled like any stage-gate failure — same severity classification, remediation
   budget, and the same **exit criterion** — findings are not the only way a gate fails; of
   the findings, no Critical remains and each Important leaves the
   gate **fixed**, traced to the responsible sub-plan/task or to the defect class it belongs
   to; a defect this session cannot fix escalates with its blocker named rather than being
   filed, exactly as at a stage gate), append
   a short `**Sub-plan N handoff:**` note under the entry, and commit
   `"Sub-plan N green"`.

   **What flips the entry is a terminal marker in the sub-plan file, and the set has exactly
   three members:** `**Completed:**` alone; `**Completed:**` **together with**
   `**Blocked-accepted:** <date> — <why>` when one of that sub-plan's gate checks is `[~]`; or
   `**Abandoned:**`. All are written into the sub-plan **before** the entry flips. **An
   intention to close out later is not a member of that set.**

   **Why abandonment is in the set, though it is not completion.** The register's vocabulary is
   `[ xX~]` and has no abandoned state, so the only alternative is leaving the entry `[ ]`
   forever — and step 5 needs every entry `[x]` before a master can close, which strands the
   whole decomposition on one sub-plan that will never finish. `[x]` beside a sub-plan carrying
   `**Abandoned:**` is the least-lossy representation available: the register says the entry is
   resolved, and the sub-plan says how. What it must never mean is that the work was done — if
   an abandoned sub-plan's goal still matters, the master is what needs re-scoping.

   **Why the set needs `**Blocked-accepted:**`.** With a blocked gate, three rules collide and
   cannot all hold: this step wants the sub-plan's `**Completed:**` line first;
   `close-out.md` § *Closing a plan whose gate could not be run* forbids a clean
   `**Completed:**` over a `[~]`; and a dependent sub-plan cannot start until this entry reads `[x]`. Something gives,
   and what gives is the record — a register flipped to unblock the next sub-plan, a close-out
   never written, and a master that then declares the decomposition done without coming back.
   `**Blocked-accepted:**` is what dissolves the collision: without it there is no legal way
   through, and the executor has to break one of the three.
4. **Version bumps are deferred to the master close-out.** Sub-plan close-outs run all
   their usual steps (full suite, the evaluator **its own declared tier calls for**,
   backlog reconcile, workflow audit) EXCEPT step 4, **Bump versions for what changed** — one feature landing
   across five sub-plans is one release event, not five. Note the deferral in each
   sub-plan's close-out.
5. **Master close-out.** When every register entry is `[x]` and every gate passed: run
   the deferred version bumps once across everything the sub-plans touched (all mirrors),
   run the full suite, run the independent evaluator pass **that the master's tier calls
   for** (*Which tier the master close-out runs at*), reconcile the review ledger (*The
   master close-out reconciles the review ledger plan-wide*), then append to the master:
   `**Completed:** YYYY-MM-DD — sub-plans: <list>`.

   **"Every register entry is `[x]`" is re-derived from the sub-plan files, not read off the
   register.** The register records a flip somebody performed; it is not evidence the flip was
   earned, and the two come apart exactly when step 3 was hard to satisfy. So before the
   master's `**Completed:**` line goes in, check each `[x]` entry against the sub-plan it names:
   **it carries a terminal marker** — any of step 3's three, `**Completed:**`, `**Completed:**`
   with `**Blocked-accepted:**`, or `**Abandoned:**` — and, **for a sub-plan that claims
   completion, no gate check in it is `[~]` without that acceptance beside the close-out line**.
   The second clause does not bind an abandoned sub-plan: its gates are unrun by definition, so
   a `[~]` there is its natural state rather than an unproven claim. (Step 3 and this step must
   name the same set: a checker implementing one clause from each reports abandoned sub-plans
   as unproven — recreating the very deadlock the third marker exists to dissolve.) An entry failing either is not done — it is a flip that outran its
   sub-plan, and the master close-out is the last place it can be caught before the whole
   decomposition is declared finished over it. **The check is a command, not a reading:**
   `python3 <planning-plugin>/skills/executing-plans/scripts/check-master-register.py` reports every
   register/sub-plan disagreement in the records home's `plans/` (`--project <repo>`), in
   both directions, and exits non-zero on any. Run it here. It is deliberately not in the
   repo's validator set — its corpus is the records home, which may sit outside the repo, and
   a repo's build may not depend on plan hygiene stored outside it.

   This is the master's half of the gate-state check: without a cross-check of sub-plan **gate**
   state, a master can be marked `**Completed:**` while a sub-plan gate is `[~]`. Both
   halves are one condition and one check.

   **The master close-out reconciles the review ledger plan-wide,** the same way it
   reconciles dispatch: for each sub-plan, which review tiers ran, over which diff range,
   and a count against what that sub-plan's declared tier owed — written into the master's
   close-out report as `reviews: <n> of <owed>`, one line per sub-plan, then the total. A
   record of many gates and a single evaluator pass is then visible off the record rather
   than recoverable from prose. Measured over three master runs under `review-scope: high`
   (one owner's master plans, undated):
   two ran the gate evaluator for their first sub-plan only, across five and six further
   sub-plans, while every per-gate report was individually honest — the gap is
   one level up, where nothing sums them. This is a close-out rule, not a validator: no
   script sums the ledger across sub-plans (review-ledger-check.py checks one stage at a
   time), so the master's report is the only place the sum can be taken, and it is taken before `**Completed:**` goes in.

   **Which tier the master close-out runs at.** Tiers are declared *per sub-plan*
   (`../references/review-scope.md`), so none of them governs the master itself. The master takes the
   **highest tier any sub-plan declared** — its close-out is the only pass that sees the
   integrated result, and a `high` sub-plan's risk does not stop being the master's
   because a cheap sibling landed after it. Declare that tier in the master close-out
   report the same way a stage gate restates its own.

**Stop conditions are unchanged** and apply inside whichever sub-plan is executing; a
stopped sub-plan blocks its register dependents exactly as a failed task blocks its
`Blocks` list.
