# Task execution — parallelism, test-first, Tier 1, and the executor trailer

The trunk (`../SKILL.md` § Step 3.2 — Split by parallelism and § Step 3.3 — Red-Green loop
(per task)) carries the rules. This file carries what makes each of them hold up: the
reasons behind them, the machinery that only fires on a branch, and the failure modes
that appear when the reasoning is forgotten.

## Why a file conflict serializes rather than inlines

A file conflict is a fact about *scheduling*: it says two tasks cannot run at the same
moment, which is a different claim from "this task need not go to a subagent".
`Dispatch: YES` is a delegation directive (`../../planning-projects/SKILL.md` § Stage
structure), and nothing about a sibling touching the same file withdraws it. So the
conflicting task is dispatched on its own once the first returns, and its commit carries
`Executor: dispatched — <type>` like any other.

## An inlined `Dispatch: YES` task is a deviation

It is a deviation the user authorised. An unavailable dispatch *raises* the Stop condition
rather than resolving it: the run halts, the user chooses, and only then is there an inline
run to record. *"It seemed easier inline"* and *"I judged it unnecessary"* are not on that
list — `../SKILL.md` § The plan is the authorization
— dispatch without a confirmation turn is explicit that the substitution is not the
executor's call to make. When it does happen, run it, say so in the gate report's dispatch
line with the reason, and let the trailer record `Executor: inline (dispatch failed)` or
`Executor: inline (user authorised)` — the bare `Executor: inline` on a task the plan marked
`YES` is the shape that hides a silent downgrade.

One more inline shape is a routing outcome, not a deviation. On a host whose routing table
has no agent for a task's stack, Preflight's roster routes that task
`Task N.M → inline (routing table — no <stack> agent on this host)`, and its commits carry
`Executor: inline (routing table — no <stack> agent on this host)`. `--dispatch-check`
reconciles that trailer only on a task the roster routed so. It counts the task as its own
term (`; N table-routed inline`), never as dispatched. On a host whose table always names
an agent, the shape never occurs.

## Why there is no third execution mode

The `Dispatch: NO` rule leaves no room for a "delegate output-heavy sequential tasks for
context hygiene" nudge. Such a nudge is optional and discretionary, and it saves no tokens —
the subagent's burn simply moves. What it produces is a third execution mode nobody can
predict from the plan, since a reader of `Dispatch: NO` cannot tell whether a task will run
inline or dispatched, and the choice turns on the executor's judgment about its own context
window. A plan that wants
a task dispatched says `Dispatch: YES` and gets the roster, the reconciliation and the
file-conflict rules with it. **If an inline task really would flood the orchestrator's
context, that is a planning bug** — mark it `Dispatch: YES` in `planning-projects` and it
becomes a visible, reconciled dispatch instead of an invisible one.

**If the matched capability's plugin isn't installed**, don't fall through to `generalPurpose`
with no domain knowledge — resolve it from disk per
`../../dispatching-parallel-agents/references/stack-routing.md` § *Resolving a capability
whose plugin isn't enabled*. A Cursor install copies only the plugin folder, so no
`capability-index.json` is on disk beside it: the component's path comes from the routing
table's plugin and name (`../SKILL.md` § Step 3.2 — Split by parallelism carries the full
resolution order). A component that needs hooks or a bundled MCP server can't be
lazy-loaded: stop and ask the user to install or enable that plugin.

## Why test-first is a rule and not a preference

Written after the implementation, a test's first run cannot distinguish "the behavior is
missing" from "my test is wrong" — both print RED — so the executor debugs its own test
against code it already believes correct, and the task's early cycles are spent repairing
assertions rather than building: every RED is then as likely to be the test's own defect —
an assertion comparing tokens minted fresh per render, say — as anything about the feature.
Running the test **before** the implementation exists costs
one command and converts that ambiguity into information: a test that passes before the work
is done is testing nothing, and a test that fails for the wrong reason is defective *now*,
when it is cheap and unmistakable.

**Repairing a wrong RED is not an implementation cycle.** Fixing a test that failed for the
wrong reason does not consume the `Red-Green max cycles` budget — that budget bounds failed
*fix hypotheses about the product*, and spending it on test mechanics would make a careful
test-first task look like a failing one. Repairs are still bounded by honesty: never weaken an
assertion to reach green (`honest-gates`), and if the test cannot be made to fail for the named
reason at all, the task's `Test:` is wrong and that is a plan defect, not a debugging problem.

**The task's `Test:` selector is a naming constraint, applied when the test is written.**
When the plan names `pytest <file> -k <expr>` — or a gate check names a selector this task's
tests are meant to satisfy — **name the tests to match that expression as you write them**.
Sensible names written without it get run, then re-run and renamed once the selector turns
out to collect only half of them, though the constraint was in the task the whole time.
This is the same defect class the Preflight gate-selector probe catches one
phase earlier, and reading the selector before naming the test closes it at zero cost.

## Why the task's own `Test:` is the whole of its testing

Between the loop starting and the task's commit, the only other tests that may run are a
Tier-1 Critical's fix-scope. **Do not run the plan's `stage-scope:` command inside a task** —
not "for Task 2.3", not as a regression check across the suites the task touched. The stage
gate runs it once, at the gate, and that is where a break in a sibling module surfaces
(`../../planning-projects/references/test-scope-tiers.md` § *A stage-scope pass never runs
inside a task*, which measured, on one owner's plan (undated), a 297-second full regression
run for a single task whose own `Test:` was a one-file `-k` filter). Widening within the
task's own subject — the whole test file instead of one filter, or the class a fix touched —
is task-scope and needs no permission; a genuine class sweep (`../SKILL.md` § A bug found
during execution is a class — sweep it, fix every instance) is likewise untouched.

## After a task commits, the next one starts in the same turn

A committed task is not a place to hand the turn back. **The commit and the next task's
first tool call belong to one turn**, exactly as at a stage boundary (`stage-gate.md` § If
the gate passes, which carries the measurements). The shapes to recognise in your own draft:

| What is written | What it does |
|---|---|
| *"Next is Task 2.2 — parse the config entries."* | Nothing. The turn ends, and the user has to ask again. |
| *"Stage 2 … starting now with Task 2.1."* | Nothing. "Starting now" starts nothing. |
| *"Say the word and I'll start Task 2.4."* | An approval gate the plan already passed. |

The write-up is not the deliverable — the task is. Report the finished task in the same turn
that opens the next one, or defer the prose entirely; a handoff note is owed at a **stage**
boundary, not after every task.

**Waiting is different and is fine.** On Cursor, wait inside the turn: a dispatched
agent's result comes back in the turn that launched it, and a background suite is waited on
by its own completion. The stop hook reads no message text, so a turn ended "waiting" is
continued like any other stop (`plan-continue-hook.md`).

## Waiting on background work

Wait on a background job by its own completion: the harness notification that arrives when a
background command or agent finishes, `wait <pid>` for a job this shell started, or a
sentinel file the job writes as its last act. Each of those fires when *that job* ends.

A process-name search does not. This loop never returns:
`until ! pgrep -f run-tests.sh; do sleep 5; done` — the loop matches its own shell:
`pgrep -f` matches the shell whose command line holds the pattern, and the shell running this
loop is one, so the search always finds it. If a name search is
unavoidable (a job some other process started, with no pid and no sentinel), exclude the
searcher: match on a pattern its own command line cannot contain
(`pgrep -f '[r]un-tests.sh'`).

**What this run started, this run reaps.** At close-out and at a gate that hands off, list
the background tasks and agents the run started, stop each whose result was used, and name
each one still running in the report (`close-out.md`, `session-handoff.md` § On `handoff`).
The list is kept from the ids the launches returned (on Cursor, the `pid` below). No tool
lists them afterwards, so note each id when it is launched — in the gate report, and in the
`RESUME HERE` block's `running:` line at a handoff, since a successor session has no
transcript to recover them from.
A background subagent's own commands keep running after the subagent returns, so a result in
hand is not proof the work behind it stopped.

**On Cursor there is no `TaskStop`, and no other stop tool.** A background command is a
`Shell` call with `block_until_ms: 0`; its result carries the `pid` and `shellId`, and
`AwaitShell` waits on it. So note each `pid` when it is launched. To stop one, run `kill`
through `Shell` on the job's whole process tree, not only on that `pid`: killing the launched
wrapper alone leaves its children (the `bash -lc` and what it started) running. Then confirm
with `ps` that nothing of the job is left. No stop for a dispatched `Task` agent is known.
Cursor's dispatch log holds `dispatch` lines only (no agent start or stop event fires), so
`review-ledger-check.py --unstopped` has nothing to list here: keep the agents you launched
in your own notes.

## A task test has a time budget

A task's `Test:` is its whole testing
(§ Why the task's own `Test:` is the whole of its testing), and without a budget nothing bounds what it costs. Measured on one owner's plan
(undated): a task test that collected a 3,132-test suite ran 3.5 h inside one Red-Green loop.

**On a plan that declares test-scope commands, a task's `Test:` runs under a task-test budget:
300 s by default.** A plan overrides it with a Preflight line, `task-test budget: N s`
(`../../planning-projects/references/test-scope-tiers.md`). The budget is passed to the proof
as `prove-claim.py --timeout N`; every proof record carries the measured `elapsed_s` of its
baseline and break runs, so the cost is on record whether or not it runs over.

The budget bounds each run of the test, not their sum, and nothing applies it for you:
`prove-claim.py`'s own `--timeout` default is 3600 s, and no tool reads the Preflight line —
the executor passes the budget. **On Cursor the `claim-verifier` runs every proof** (once per
stage, at the gate), so it is the one that passes it: `agents/claim-verifier.md` reads the
plan's budget and runs each `claim` and `req` with `--timeout N`.

**A test over the budget is a Stop condition**, reported like a spent cycle budget:
record it with v2 `set-blocker` with the overrun evidence, prevented operation, dependency
and remaining work (legacy projection: `phase: "blocked"`, note `task test over N s`).
`prove-claim.py` exits 4 without a record when the run before the break goes over; a test that hangs only
under the break exits 1 ("hung … inconclusive") — a stop all the same, because the test
cannot be timed. The test is never narrowed to fit: cost is an argument
for re-planning the task, made to the user, never a licence to prove less. Position:
test-scope tier task, and only on a plan that declares test-scope commands, where
the suite is expensive enough for the budget to bind.

## Tier 1 — the quick per-task review

Whether it runs comes from `../references/review-scope.md`; do not re-derive it. **At `none`,
`light` and `standard` there is no per-task review**: a green task goes straight to its
commit, and the stage's Tier-2 pass is where its diff is read. Tier 1 runs when the declared
tier is `high` **and this task is one the declaration names** — a **risk-listed task**, whose
`Scope:`/diff touches the risk-listed area — or when *this* task carries `Review: required`,
the per-task opt-in that buys one risky task a review without raising the whole plan's tier.
A `high` declaration naming no tasks binds all of them; an ordinary task in a `high` plan
whose own diff touches nothing risk-listed does **not** run Tier 1, and the gate report
records that as scope (`Tier-1: not run — tier high, task not risk-listed`), never as an
opt-out. Describe a Tier-1 dispatch by its task (`Stage 2 Task 2.3 quick review`): the ledger
check never counts a dispatch naming a task toward the stage's Tier-2 claim
(`stage-gate.md` § Checked against the dispatch log).

**Why Tier 1 is not the default.** Unconditional per-task review makes a nine-task plan pay
nine review dispatches plus their re-dispatches after fixes, and the findings run
overwhelmingly to the verification apparatus rather than the product. What Tier 1 uniquely
buys is catching a Critical *before* it is built on — worth an agent when the change is risky,
not worth nine when it is prose. Tier 2 still reads every line of the same diff at the gate;
what a `standard` plan gives up is latency, not coverage. That is the trade, and it is why
`high` keeps Tier 1 and why a single dangerous task can buy it back by annotation.

When it does run: after the test is green and Status is flipped but **before** the commit,
dispatch `code-reviewer` (read-only) as a **fresh dispatch seeing only the task
diff** — never the executor self-reviewing — briefed with the task description and its
`Test:`. **Brief it to check behavioral claims too**: every sentence in the diff asserting
what the code does (a default, an exit code, a count, an "every") is verified against the
source or flagged, per `honest-gates`. Handle by severity:

- **Critical → blocking.** A Critical finding means the task is not actually done. Fix it
  inline (one fix per cycle, diagnose first — same discipline as the Red-Green loop),
  sweeping its class per `../SKILL.md` § A bug found during execution is a class — sweep it,
  fix every instance, then **re-run at fix-scope** — the task's own `Test:` plus the test
  classes the fix touched, never the full suite
  (`../../planning-projects/references/test-scope-tiers.md`) — **and re-dispatch the review over the fix diff only.** The re-review after a Critical
  fix covers the fix diff only: the commits made since its verdict, briefed with the finding
  they answer. The task's other lines were read once, and the gate's Tier-2 reads them again.
  Critical-review cycles count against the *same* `Red-Green max cycles` budget as test
  failures; on exhaustion, escalate like any other budget exhaustion (`../SKILL.md` § Stop
  conditions). The executor applies the fix; the reviewer only ever reports.
- **Important / Suggestion → advisory.** Important findings are carried to the gate as
  advisory: the gate's Tier-2 pass triages them with the stage diff, and its exit criterion
  is where each is fixed. Do not act on them now. Append them to the plan file
  as a note under the task (`**Review notes (Task N.M):** …`) so the stage gate's deep review
  can triage the batch. They never block the task.
- **Skip for trivial/non-code diffs.** Docs-only, config-only, pure version-bump, or
  comment-only diffs don't need Tier 1 even at `high` — note the skip and proceed. Honor a
  `Review: skip` task annotation and the global opt-out the same way — but an opt-out is
  **evidenced, not asserted** (`../references/integration.md` § Review opt-out): note the skip
  *with* the quote or the cited annotation, never as a bare "skipped". A task where the *tier*
  never called for Tier 1 needs none of this: that is scope, recorded once by the declared
  tier, not a per-task skip to evidence.

  **Exception — docs that assert executable behavior are not a trivial diff.** A docs change
  **asserting a fact about** commands, flags, env vars, exit codes, defaults, paths or
  invocation examples makes exactly the **behavioral claims** `honest-gates` governs under its
  rule that a behavioral claim is a gate too, and prose is where they go unchecked longest: no compiler, no
  test. Such a diff does **not** auto-skip Tier 1. The test is *asserting*, not *mentioning* —
  naming a flag in a heading or an unchanged sample claims nothing and still skips. The Tier-1
  dispatch is scoped to the task *diff*, which bounds what it reviews, not what it may read,
  so the reviewer opens the cited source to check the claim.

Tier 1 does **not** pause to ask the user — only to fix autonomously within budget,
preserving run-to-completion.

## The executor trailer — why it exists, and how it breaks

**Keep the trailer to one physical line.** Git folds a continuation into the preceding
trailer only when it is **indented**; an unindented wrap ends the block instead, so the
trailer vanishes from every `%(trailers:…)` query with no error at all. The rule in the trunk
is deliberately stricter than git — one physical line, never a folded continuation — because
"indent it and it still parses" is a detail nobody checks at commit time and the failure
is silent. Put the reason in the body; keep the trailer bare.

**A routed agent that cannot commit does not become an inline task.** When the routed
agent cannot commit (an installed stack agent marked `readonly: true`, for one), the agent
does the work and reports, this session runs the `Test:` and writes the commit, and **the
trailer still names the agent** — it records who did the work, not who typed `git commit`
(`../../dispatching-parallel-agents/references/stack-routing.md` § *Not every routed agent
can commit*).

Name the actual agent name that ran the work, not the routing table's suggestion, and
say so when a dispatch failed and finished inline: a substitution nobody can see is the
defect this trailer exists to end. **A trailer that misstates who ran the task is worse
than none** — it converts a visible gap into a false record. Why a trailer at all: every
other artifact is byte-identical whether a task ran inline or dispatched, so
`git log --format='%(trailers:key=Executor,valueonly)' <base>..HEAD` is the only check
that can read "5 marked YES, 0 dispatched" straight off the log.

## Committing a task whose plan lives outside the repo

Rule 7 mandates committing the work, the Tier-1 fixes and the flipped `Status: [x]` together,
which reads as one action and is two whenever the plan sits **outside the repo it plans**.
A configured records resolver can put the records home — and so `<records home>/plans/` —
outside the repo, often on storage that is not a git repository at all.

The two halves, and where each runs:

| The edit | The commit |
|---|---|
| The plan file, at its **absolute path**, from wherever you are | The **repo root**, with `git add`/`git commit` |

**Never change directory into the plan's directory to make the edit.** The failure this
prevents is a single chained command that moves into the plan's directory, edits the file
there, and then runs `git add -A && git commit`. The edit lands, the git command dies on `fatal: not a git repository`, and the task's work is left
uncommitted while the plan already reads `[x]`. That ordering is what makes it worth a rule:
the failure is not "the commit did not happen", it is "the marker and the commit disagree",
which is the one state the `Status:` flip exists to make impossible.

**What becomes of the flip.** For an in-repo plan the `Status: [x]` flip is part of the task's
commit, exactly as rule 7 says. For a plan **outside the repo** it rides no commit at all: the
flip is written to the plan file in the records home and is authoritative there, and the
task's commit carries only the work. Nothing is lost — `plan-progress.py` and backlog unify
(`../../backlog/scripts/backlog-unify.py`) both read the plan
file, not the log — but a gate report that claims the flip was committed is claiming something
that did not happen, so say which case the run is in.

## Comparison experiments

When a task evaluates candidate versus baseline, use
[evaluation-evidence-contract.md](evaluation-evidence-contract.md). Bind both
alternatives and every declared dependency before comparing outcomes. Keep runtime
availability, schema, support, usefulness and owner preference separate; preserve
unknown and failed/tied observations. Record metadata only. Reuse is attributed to
the original experiment and cannot supply a fresh success or owner acceptance.
