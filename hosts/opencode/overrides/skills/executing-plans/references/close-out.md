# Phase Close-out — after the last stage

Reached once, at the end of a plan, and only when every stage is green — **or when a stage
gate is BLOCKED (`[~]`) and cannot be unblocked here**, which is not a green stage and is
routed here anyway: § Closing a plan whose gate could not be run is the procedure for it, and
lives in this file because closing out is what it governs. The trunk
(`../SKILL.md` § Phase Close-out — After the last stage) points here; this file is the
procedure. Work the steps in order.

1. Run the plan's **sole plan-scope pass** — the only `clean` and the only full
   expensive-suite run in the whole execution (intermediate gates ran stage-scope), including
   any quarantined slow tests. Use the plan's declared `plan-scope:` command when present. If
   the final stage gate already ran this exact plan-scope pass and no commits landed after it,
   that pass counts — don't run it twice. **Run it last**: steps 2a and 3 read the committed
   diff and land their fixes first, so the tree the pass proves is the tree that merges. A
   commit a Material fix lands after it is proven at fix-scope, never by another plan-scope
   pass (`stage-gate.md` § A review fix does not re-earn the full pass, item 3).
2. Run any integration / e2e tests the plan flagged.

2a. **The tier's Tier-2 pass, if it lands here rather than at a gate.** At `light` the deep
   review is **one `code-reviewer` (read-only) pass over the whole plan diff**
   (`<plan-base>..HEAD`), and this is where it runs — the stage gates deliberately ran none.
   At `standard` and `high` the Tier-2 passes already ran per stage gate, so nothing is owed
   here except `high`'s second independent pass. At `none`, nothing. Handle the verdict by the
   same rules a gate uses: a **Critical blocks the merge** (fix, re-run at fix-scope,
   re-dispatch — and that re-dispatch counts a remediation round), and every **Important**
   leaves close-out **fixed** per the exit criterion. Report it in the close-out list with the
   agent and the diff range, exactly as a gate report would. This step exists because
   `light`'s single review is the whole plan's only white-box pass; a close-out that forgot it
   would ship a tier that reads as reviewed and was not.

3. **Independent evaluator pass.** **Whether it runs comes from `../references/review-scope.md`**
   — never at `none`; at `light` and `standard` when the final gate carries a `(judgment)`
   check or any stage has `**Outcomes:**`; always at `high`. When it runs, dispatch a fresh
   evaluator (OpenCode's `general` agent, in the goal-evaluator role) briefed ONLY with the plan's stated goals, the per-stage Goal lines and the gate
   criteria — never the implementation transcript. Where stages have Outcomes, also give it
   the brief `stage-brief.py demo --stage <the last stage with Outcomes>` prints, and tell it
   to demo every earlier stage's `demo.md` Outcomes again on the finished build, the way its
   users use it.
   It verifies the goal against the artifact itself and grades every
   finding Blocking / Material / Minor, as at the stage gate, and **each finding is repaired as
   a class** per `../SKILL.md` § A bug found during execution is a class — sweep it, fix every
   instance — a close-out evaluator reads the whole plan diff, which is the widest view any
   reader gets and therefore the one most likely to name one instance of something true of
   several. **A Blocking finding is the stop condition** — surface it before merge. A FAIL
   carrying only **Material** findings is *not* a merge blocker — but it is not a filing
   exercise either: **fix each Material finding**, sweeping its class, and report what was
   fixed. Only a Material finding you genuinely cannot fix here escalates with its blocker
   named, per the exit criterion's fourth row
   (`../references/stage-gate.md` § Exit criterion — the dispositions behind it). The
   distinction matters because "the evaluator returned no adverse findings" is not a reachable
   state for a fresh reader of a real artifact; treating any FAIL as blocking is what makes the
   final gate oscillate. The evaluator is dispatched **once**: a Material fix is proven at
   fix-scope by the executor, not by re-dispatching it (`stage-gate.md` § Independent
   evaluator for non-command checks). Where the tier mandates it, skip only on an
   **evidenced** user opt-out; where the tier does not, report it as scope rather than as an
   opt-out.
4. **Bump versions for what changed**, as part of close-out rather than a follow-up.
   Breaking/removed → major; new capability → minor; fix/docs/internal → patch. Bump it
   wherever the project records it **and every place that mirrors it** — grep the old version
   string to find them. In a Claude Code plugin marketplace, for example, that is a plugin's
   `.claude-plugin/plugin.json` **and** its root `.claude-plugin/marketplace.json` entry,
   plus `metadata.version` when the marketplace set itself changed. Add a `CHANGELOG.md` entry if the project keeps one, and
   commit the bumps (`"chore: bump <component> to <version>"`). When the right bump is
   genuinely ambiguous, state your call and let the user override — don't silently skip.
   **On a sub-plan, skip this step entirely** — version bumps defer to the master close-out,
   because one feature landing across five sub-plans is one release event and not five
   (`master-plans.md` § *Version bumps are deferred to the master close-out*). Note the
   deferral in the sub-plan's close-out report. Every other step here runs as written.
5. Update the plan document with a closing note: append `**Completed:** YYYY-MM-DD — commits:
   <list>` at the end. **If any gate check in this plan is `[~]`, read
   § Closing a plan whose gate could not be run before you write this line** — a bare
   `**Completed:**` over a blocked gate is the one form of this line that is wrong, and this
   step is where it gets written. Also confirm every task's `- **Status:**` is `[x]` (any remaining `[ ]`
   task was not executed — either finish it or note it as deferred). The close-out line +
   all-`[x]` statuses make the plan's done-state unambiguous for any downstream reader.
   Close-out writes no `RESUME HERE` block and runs no `context-usage.py` stop rule — there is
   no next task to hand off to (`session-handoff.md`).
6. **Reconcile the backlog.** Scan the plan for `Closes BL-NNN` references and any tasks that
   implemented an open backlog item. Call the `backlog` skill (`remove`) with that ID list.
   Reference each removed ID in the close-out commit message.

6a. **Run the decisions-conformance check over the plan's whole diff.** This is the second
   of its two runs (the other is the final stage gate) and it is a **close-out criterion, not
   a formality**: a contradiction found here without a `Supersedes` citation blocks the merge
   exactly as it fails a gate, with the same two legal resolutions — re-scope the
   change, or record a deliberate supersede and cite it. It runs here rather than only at the
   gate because close-out itself lands commits the final gate never saw: version bumps, the
   `**Completed:**` line, backlog and register reconciliation. State which IDs were checked
   against which parts of the diff rather than asserting blanket conformance. Skip only when
   the diff is genuinely non-code and no decision in force bears on documentation.

7. **Reconcile the decisions register**, in both directions — this is the *recording* half
   and does not substitute for the sweep in step 6a:
   - **Supersedes citations → record them.** For each `Supersedes DEC-NNN` on a task, call
     the `decisions` skill's `supersede` operation. Until this runs the register still asserts a constraint the code
     no longer honors, and the *next* plan will be written against it.
   - **New constraints created → record them.** Execution discovers what planning couldn't:
     an approach that turned out blocked, a platform limit, a cost knowingly accepted to get
     a stage green. Call `decisions add` with the reason — constraint, evidence, rejected
     alternative, accepted cost. If you cannot name a rejected alternative or a cost, it
     probably wasn't a decision; don't pad the register.
   - Reference the recorded IDs in the close-out report and commit message.

8. **Audit workflow specs.** If `docs/workflows/` exists, call the `workflow-spec` skill
   (`audit`) against the plan's cumulative diff. For every WF-ID the plan declared (`Changes
   WF-NNN`, `Removes WF-NNN`), verify the corresponding block was updated or deleted in this
   branch. **Any `Removed` finding the audit reports that the plan did not declare is a
   regression — stop and escalate before merge.** Surface every `Moved`/`Modified` finding for
   explicit user review.
   **Then, before the report — background work this run started.** List the background tasks
   and agents this run started, by the id each launch result and completion notification
   carried — on OpenCode the pid or child session id noted at launch
   (`task-execution.md` § Waiting on background work) — stop each whose result was
   used (on OpenCode by `kill` of its pid or process group), and name each one still running in the report, the way a `[~]` gate is
   named. Then, from the
   repo root, run
   `python3 <planning-plugin>/skills/executing-plans/scripts/review-ledger-check.py --unstopped --repo <repo root>`.
   It lists each agent the dispatch log shows starting and never stopping. Exit 1 → name each
   one in the report by id and type, the way a `[~]` gate is named. Exit 3 (no log) → the
   report says `unstopped: NOT RUN`.

9. Report to the user with:
   - Stages completed
   - Total commits
   - Version bumps applied (component → old → new)
   - Plan location for future reference
   - Reviews that ran: each tier, the agent that ran it, and the diff range it saw — or, for
     one that did not, the same three reasons the gate report uses: the declared tier did not
     mandate it (named as scope, not as an excuse), or an evidenced opt-out or trivial diff
     where it did. Same requirement as the stage gate's, at plan scope: a close-out that says
     the work was reviewed without saying by what, over what, is the claim this list exists to
     stop being unfalsifiable. For a master plan this bullet is the per-sub-plan reconciliation
     `master-plans.md` step 5 defines, in the `reviews: <n> of <owed>` form — one line per
     sub-plan, then the total.
   - **Dispatch reconciled against Preflight's roster, plan-wide.** This is a gate. From the
     repo root run `python3 <planning-plugin>/skills/executing-plans/scripts/plan-progress.py
     --dispatch-check <plan> --since <plan-base>` — by the package path, not `scripts/…`: the
     short form finds nothing from a repo root, and Python's `can't open file` exits 2 like a
     real failure. So decide by what it printed: a `dispatch:` or `FAIL:` line is a result;
     neither is a broken invocation — fix the path and re-run. Exit 0 → state its `dispatch:`
     line. Exit 2 → an `ACTION NEEDED:` block naming each inlined `Dispatch: YES` task it lists, with its
     reason. Close-out does not finish until, per listed task, the user authorises the inline
     run (its trailer is amended to `inline (user authorised)`) or the task is re-dispatched.
     The roster is declared once for the whole plan; this is where it is answered.
   - Backlog items closed (by ID) and any new ones opened during execution
   - Decisions recorded or superseded during close-out (by ID)
   - Workflow audit triage: blocks updated, blocks removed, undeclared changes (if any
     survived escalation)
10. Carry out the merge the plan's `## Owner decisions` records — merge, pull request, branch
    deletion, push, tag, each only where an entry applies (every qualifier of its `applies to:` holds,
    `../SKILL.md` § Stop conditions) — and report what was done.
    Run `plan-state.py finish` (this file's last section) before any of it switches
    off or deletes the run's branch: the run is owned by its branch, and `finish` is
    refused from anywhere else.
    With none recorded, offer merge / finalize options (worktree cleanup, PR creation, branch
    merge). Do not merge without explicit confirmation; an owner decision naming the merge
    is one.

## ACTION NEEDED — the one place the close-out report asks for something

Same form as the gate report's (`stage-gate.md` § ACTION NEEDED), and it binds here for the
same reason: a close-out usually ends with a merge offer, which is itself a decision, so a close-out
that also carries an unresolved question is the report most likely to bury one.

```
ACTION NEEDED: <one line naming the decision>
  1. <option>
  2. <option>
```

One block, last, options numbered. **A close-out report carrying an `ACTION NEEDED:` block
does not also announce that it is proceeding** — to a merge, a tag, or anything else.

**Step 10's merge offer is the block whenever no owner decision settles the merge.** The
close-out then ends in a decision the user owns, so the block is present: with no other
decision it carries the merge options alone, and with one it carries both, numbered
together. When an owner decision settled the merge and nothing else needs the user, the
close-out carries no block and says what it did. What may never happen is a separate `ACTION NEEDED:` block for some other decision
*plus* a freestanding merge offer elsewhere in the report — that reconstructs the pairing this
form exists to forbid, out of two individually well-formed halves. Anything the user does not
have to decide is not an `ACTION NEEDED:` item at all.

**On OpenCode, record the state before the report, and do not finish early to force the
stop.** No Stop hook runs on OpenCode, so nothing resumes the session over the block: the
report ends the turn on its own and the ask stands. What the state write buys is the
*record* — move the run to close-out with `plan-state.py transition` when close-out
starts, so the next session, or the user coming back to the question, sees where the run
stands rather than a `gate` phase that looks mid-flight. `plan-state.py finish` stays the
last step: where the block asks something the user must answer before the merge, it waits
until their answer has been acted on.

**Tier: untiered.** This mandate costs a line of text, not an agent dispatch, so it
runs at every review scope including `none` — named here because a new mandate states the
rule that gates it rather than leave it inferred: an inferred tier gets guessed differently
by each reader.

## Closing a plan whose gate could not be run

A `[~]` gate check outranks the close-out line: the plan classifies `blocked`, stays in
flight for every reader of the plan-status contract, because a check that could not
run means completion was never proven. That is correct and it is not the end of the story —
a plan can be genuinely finished with a check that will never run here.

**Write `**Blocked-accepted:** <date> — <why>` beside the `**Completed:**` line.** It records
that someone looked, understood, and closed the plan anyway; it does not claim the gate ran.
Short of abandoning the plan outright, it is the only thing that retires one — `**Abandoned:**`
is terminal over a `[~]` too (`master-plans.md` step 3's third marker), but that closes the plan
by giving up on it rather than by accepting the block.

**"Someone" is the user, not the executor.** A BLOCKED gate is already a Stop condition that
escalates, so the acceptance is theirs to give and this line is where their answer is written
down. An executor that writes its own `Blocked-accepted:` has not recorded a decision; it has
recorded that it decided, and that is refused here as everywhere else.

**Do not edit the `[~]` to `[x]`.** That is the falsification the marker exists to prevent:
the plan would read as finished over a check nobody ran. The block is the record; the acceptance is the decision.

**On OpenCode no bar is drawn from the marker.** OpenCode has no status line, so no
`⊘ GATE BLOCKED` glyph will catch a `[~]` nobody escalated, and the package's
`plan-progress.py` ships only its gate checks. The plan-status contract's readers and this
section are the whole mechanism, and a `[~]` quietly promoted to `[x]` is caught only where
`plan-flip-audit.py`'s findings reach: a `(judgment)` box with no evaluator artefact, or a box
whose own text voids it.

**Unless the check has since actually run and passed — then tick it, and say why you could.**
This is the one case where the box moves, and it is not the falsification this section
forbids: editing a still-unrunnable check claims a proof nobody has, whereas here the proof
exists and can be named.
Write `- [x] <the check> *(ran YYYY-MM-DD — <the evidence>)*` and name what made it runnable,
usually a sibling sub-plan landing. `**Blocked-accepted:**` is the wrong marker for it — that
one says the gate was accepted UNRUN, so writing it over a check that ran is false in the
other direction, and the plan would carry an acceptance it never needed. A careful author hits
this whenever a master's forward-looking check (*"verified when sub-plan 02 runs"*) comes true;
without this case the contract could express that state only by choosing between two wrong
answers.

**Write it at column 0, flush with the `**Completed:**` line**, and name the blocked gate check
in its text.

**The natural-seeming place does not parse.** Indented two spaces under the `[~]` item it
accepts — where it would sit right beside the box it explains — `**Blocked-accepted:**` is
invisible to `BLOCKED_ACCEPTED_RE`, which anchors to line start. `plan_blocked()` then
stays true and the plan stays on the in-flight board, having done everything right.

### On a sub-plan, this line is load-bearing for the master

**A sub-plan's close-out line is what authorizes flipping its master register entry** to `- **Status:** [x]`
(`master-plans.md` step 3), so on a sub-plan it is not only this plan's record — it is the
master's precondition. That makes deferring it a different act here than on a standalone plan:
a sub-plan whose close-out is postponed leaves the master with no legal way to advance.

**So when the gate is blocked, write both markers now rather than deferring the close-out.**
The pairing — `**Completed:**` plus `**Blocked-accepted:**` — is the whole point: it lets the
register flip on an honest record instead of forcing the choice between an unearned `[x]` and a
sub-plan that cannot unblock its dependents. Deferring "until the gate can be run" fails in a
predictable way: the register gets flipped anyway to let the next sub-plan start, the
close-out is never written, and the master then declares the decomposition done over a
sub-plan that never closed.

## Last step, every close-out

Run `plan-state.py finish` with actual close-out evidence; retain the
terminal snapshot, pointer and receipts. The terminal run is immutable; init refuses
to overwrite it. The current contract has no automatic archive/reset operation; an
independent owning worktree can initialize a separate run. Unowned legacy state may still be deleted. Archive `.claude/dispatch-log.jsonl`
beside it, so the next plan's review claims are checked against a log of its own run. This applies to every close-out,
blocked or clean — it is a `##` section rather than a trailing line because a line inside the
blocked-gate section is one a reader working an unblocked plan never reaches.
