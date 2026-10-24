# Format triage — why each boundary sits where it does

`../SKILL.md` § Phase -0.5 — Format triage carries the rule: the format table, *size each
request not the batch*, *Direct is the off-ramp*, *record the call*, and *round up per item,
never per batch*. This file carries the reasoning behind those, and a worked example of
the per-item rule.

## The ladder is a cost ladder

Matching the format to the job is what keeps a three-task chore from paying for a twelve-task
project's ceremony — and a genuinely large project from being crammed into too small a
container. It is the downward-and-upward symmetric partner of the decomposition rule in
`../SKILL.md` § Phase 2.5 — Decomposition decision (master plan + sub-plans): one rule stops a
plan being too big for its container, the other stops a container being too big for its plan.

## Per format

**Direct.** A plan file for a couple of tested edits is pure overhead. This is the answer to
"simple jobs shouldn't have to enter the machinery": the skill is allowed to *decline to plan*.
What Direct still owes is a test and a commit — those are invariants, not ceremony — plus a
quick backlog-title check before starting, because silently redoing a tracked item is the same
planning bug at any size. That backlog check is the one Phase 0 step Direct keeps.

**Light.** Real-but-small work: one coherent stage of a handful of tested tasks, no fan-out, no
cross-session handoff. It keeps the invariants (a `Test:` per task, `Status:` flips, a commit
per green task, honest gates) and drops the long-horizon artifacts (a mandated Research
Summary, the full Preflight, Risk/Rollback, Blocks/Dispatch fields). The full spec, and the
exact kept-vs-dropped split, is `light-plan-format.md`.

**Standard.** The default staged plan authored by Phases 0–5 of `../SKILL.md`. It is the
unmarked default, which is why a Standard plan may omit the `Format:` line.

**Master.** The decomposition path. `../SKILL.md` § Phase 2.5 — Decomposition decision (master
plan + sub-plans) is the **sole authority** on the Standard→Master decision; the triage table
points at it and does not restate the thresholds, so the two cannot drift apart.

## A batch is not a job

Suppose six asks in one prompt — one search feature and five layout fixes. Triaged **as a
batch**, they cross the Master threshold: several sub-plans, many stages and dozens of
checkboxes. Five of the six items are about an hour of Direct work, and each of them carries a
master plan's ceremony to get there.

Nothing in that triage is individually wrong: the batch really does contain more than 25 tasks'
worth of surface once every tweak is written up as a task with a test, a gate and a register
entry. The defect is that **a batch is not a job**. Sizing the batch is how one real feature
drags five one-line tweaks into its format — the tweaks are not larger for having arrived in
the same sentence as something that is.

Hence the split verdict: some items executed Direct, the remainder planned at whatever format
the *remainder alone* warrants.

```
Format: Split — items 2, 3, 4, 5, 6 Direct; item 1 Light
```

## Why "round up" does not transfer to a batch

Rounding up is right for a *single job* on a format boundary: the cost of slightly too much
structure is smaller than the cost of a container that cannot hold the work, and the failure it
prevents (a Light plan that grows a second stage mid-execution) is expensive to unwind.

That reasoning is about one job's shape. Applied to a batch it inverts: rounding up there means
charging **every** small item for the **largest** item's container, which is exactly what the
example above shows. So the trunk states the rule with its bound attached — *round up, per item,
never per batch* — because a rule stated without its bound is the one that gets over-applied.

## Split only where the items are genuinely independent

Items sharing a file, a migration, or a behavior contract are **one item** for triage purposes,
however separately they were phrased. Splitting those buys a merge conflict, not a saving. The
test is mechanical: if executing item A would make you re-open the file item B changes, they
are one item.
