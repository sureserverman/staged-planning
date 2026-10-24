# Dispatch fidelity — why the roster, the probe and the snapshot exist

An inlined task and a dispatched one produce byte-identical artifacts: the same diff, the
same `Status: [x]`, the same commit subject. So a run that ignores its `Dispatch: YES`
directives leaves nothing for a later reader to notice. Everything in this file exists to
make that specific omission visible — including, below, why the omission happens in the
first place. `executing-plans` keeps the mechanics — the roster format, the probe, the
snapshot; this is the reasoning behind them. The executor trailer's rationale stays in the
trunk beside the trailer shapes themselves (Step 3.3 rule 7).

### Why a mandated dispatch gets skipped — the precedence rule

Two rules about dispatch live in different places, and nothing forces a session to
reconcile them: a standing session caution of the form *"do not call the Task tool
unless the user requested it,"* and the plan's own execution model naming dispatch points
— `Dispatch: YES` tasks, tier-mandated reviews, evaluators, the Preflight probe itself.
Nothing arbitrates between the two, so the more general, more recently read caution wins
by default. That is the whole failure — not carelessness, a genuine precedence question
that needs an answer in writing.

The resolution: the caution is **conditional, not absolute**. Approving a plan whose
execution model mandates dispatch **is** the request the caution is waiting for — the
confirmation already happened at plan approval. So a `Dispatch: YES` task, a
tier-mandated review, an evaluator, and the Preflight probe itself are dispatched without
a further confirmation turn: `../../dispatching-parallel-agents/references/stack-routing.md` § "Not
every routed agent can commit" states the same precedence for the handoff side of this rule.

The bound, stated with equal weight: with no plan in play and no mandate — a question
asked mid-session, a task that would merely *benefit* from fan-out — the caution stands
and you ask. A rule stated without its bound gets over-corrected into its own inverse.

The measured cost of getting it wrong (one owner's plan execution, undated): 37 commits with
zero Agent calls — every review tier and evaluator pass the plan specified silently skipped.
Nothing shows it, for the reason this whole file exists: an inlined task and a dispatched
one produce byte-identical artifacts. A skipped review leaves the defects it would have
found inside gates that read as passed.

The over-correction is a failure in its own right, at equal weight: a standing refusal to
dispatch subagents unless explicitly asked inverts the rule instead of scoping it, and
strips the same reviews for the opposite reason. Both errors produce the same artifact: a
plan that reads as reviewed and was not.

Where dispatch genuinely is unavailable, the answer is neither to fake it nor to quietly
inline: say so, and enumerate exactly which checks ran at each gate. **A failed probe is a
Preflight failure** — see below; this is the same rule read from the cause side rather
than the detection side.

| Situation | Dispatch? |
| --- | --- |
| user asks a question, no plan in play | No — inline |
| plan approved, execution model names dispatch points | YES — the approval is the request |
| plan approved, dispatch mechanically unavailable | **Stop** — a Preflight failure where the roster is non-empty, a gate Stop condition where it surfaces later; either way the user chooses, and the gate report lists what actually ran |
| no plan; a task merely *would benefit* from fan-out | No — ask first |

### Dispatch roster and capability probe

A `Dispatch: YES` task is a directive to dispatch, not a note about concurrency
(`../../planning-projects/SKILL.md` § Stage structure) — and an inlined task and a
dispatched one produce byte-identical artifacts. So a run that ignores the field leaves
no trace in the diff, the commits, or the gate: there is nothing for a later reader to
notice. The omission becomes visible only if the run wrote down what it was going to do
*before* it did anything. Preflight is where that happens, and Preflight is already a
hard stop.

1. **Enumerate the roster.** Sweep **every task in the plan**, across all stages, and
   list in the Preflight report each task whose `Dispatch:` field reads `YES`, with the
   agent name it routes to per
   `../../dispatching-parallel-agents/references/stack-routing.md`:

   ```
   Dispatch roster (Dispatch: YES) — <n> of <total> tasks
     Task <N.M> → <agent name>
     Task <N.M> → <agent name>
     …
   ```

   The roster is a **sweep over the task set**, never one worked example: a report
   naming a single task cannot fail on its siblings — the same instance-vs-class gap the
   trunk's gate rules close, arriving one phase earlier. A roster covering only the first
   stage is not a roster. An empty roster is a legitimate result — write `0 tasks`, so
   the absence is on the record as observed rather than as never examined. What the
   roster buys is contradiction: a run whose Preflight declared five dispatches and whose
   execution shows none now disagrees with a written list instead of disappearing.

2. **Probe the capability — only if the roster is non-empty and the declared tier is
   `standard` or `high`.** Dispatch one throwaway
   subagent — `generalPurpose`, whose entire task is to reply with a fixed string
   (`DISPATCH-OK`) — and confirm the string came back. One trivial dispatch proves the
   mechanism works in *this* session, while the finding can still change what happens
   next. Learning at Stage 3 that dispatch is unavailable is the same fact arriving after
   every decision it should have informed.

   **Roster first, probe second**, because the roster decides whether the probe is worth
   running: a plan with `0 tasks` on its roster will never dispatch, so a throwaway
   dispatch there proves a capability nothing in the run will use. Record `probe: skipped
   — empty roster` and move on. This is also why the failed-probe rule is conditioned on
   a non-empty roster; ordering the steps the other way makes that condition read as an
   afterthought.

   **The tier is the second conjunct**, and it works the same way: the probe also runs
   only when the declared tier is `standard` or `high` (`../references/review-scope.md`, the rule
   — this file is its rationale). At `none` and `light` nothing is dispatched but the
   rostered tasks themselves, and the first of those delivers the same news almost as
   early, so the probe is buying a shorter warning than it costs. Record `probe: skipped
   — tier <name>`. The accepted cost, stated because it is real: a `light` run with a
   non-empty roster learns about a dead dispatch path one task later than a `standard`
   run would.

3. **Snapshot the `Review: skip` annotations.** In the same sweep, list every task
   already carrying `Review: skip`, and record it in the Preflight report against the
   commit the run starts from:

   ```
   Review: skip annotations at <base-sha> — <n> task(s): <Task N.M>, …
   ```

   This is what makes the annotation usable as evidence later. `Review: skip` says *the
   user chose not to review this task* — but the executor writes to the plan file on
   every task (Status flips, review notes), so an annotation read at skip time cannot
   distinguish one the user authored from one the executor added ten minutes earlier.
   The snapshot fixes the reference point: an annotation in this list was there before
   the run touched anything, and one that is not **is not evidence of a user opt-out**,
   whatever it says. Cite the snapshot when you skip, not the task line.

   Same shape as the decisions re-check, and for the same reason: an artifact the
   run can modify is not evidence about the run unless you pin it first. Write `0 tasks`
   when there are none — an empty list observed beats an absent one.

**A failed probe is a Preflight failure.** When dispatch is unavailable or disallowed in
this session and the roster lists at least one task, Preflight fails and you stop — the
user decides whether to enable it, re-plan those tasks as `Dispatch: NO`, or accept
inline execution knowingly. Substituting inline execution on your own authority is not a
resolution; it takes a decision that belongs to the user and makes it silently, which is
the exact failure this check exists to surface.

**If Preflight fails, stop.** Report which check failed and how it failed. Do not proceed to Stage 1. A broken baseline makes every downstream Red-Green loop noise.

## Why an unperformable dispatch is a Stop condition

The dispatch entry in `../SKILL.md` § *Stop conditions* keeps a symmetry with the rest of
the list. "A test cannot be run" blocks, because an unrunnable check is not a passed
check — and a mandated dispatch or review that cannot be run is the same fact about a
different mechanism. What lets the asymmetry survive without a rule is that the substitute
looks like the work: an inlined task produces the same diff, and an unreviewed gate reads exactly like a
reviewed one. That is the reason it needs a rule rather than judgment — the failure is
invisible in the artifact, so nothing downstream will raise it. **The choice belongs to the
user**: they can enable dispatch, re-mark the tasks `Dispatch: NO` through
`planning-projects`, or accept inline execution knowingly. What the executor may not do is
make that call silently on their behalf. The other half of the symmetry: the Stop condition fires when a mandated
dispatch *cannot be performed*, never when the executor is merely unsure whether to perform
one — that question the plan already answered, and asking it again is the confirmation turn
the trunk's authorization rule deletes.
