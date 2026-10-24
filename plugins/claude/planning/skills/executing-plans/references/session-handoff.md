# Session handoff — a measured stop, never an eyeball call

The executor decides when a plan continues in a fresh session, and it decides by
measurement. Without one, a mid-plan stop waits for the user to notice a full context —
measured over five executions (one owner's plans, undated), the executor proposed a handoff
zero times — and advice to reset on large plans, with nothing to measure against, is never
taken on purpose. Every executing-plans file that mentions a fresh session cites this one,
`session-handoff.md`, as the rule that decides it.

## The measurement

`../scripts/context-usage.py` reads this session's transcript
(`~/.claude/projects/<cwd-slug>/<session>.jsonl`) and reports the exact context in use — the
last main-thread turn's `input + cache_read + cache_creation` tokens, not a guess — against
the model's window, plus the context each `Stage N green` commit in this session cost:

```
python3 <planning-plugin>/skills/executing-plans/scripts/context-usage.py \
  --plan <plan path> --next-stage <N+1> [--sub-plan-boundary]
```

**The window.** `--window N` wins. Next comes the live window: on Claude Code 2.1.288+ the
planning mod has `.claude/plan-context.json` written beside the state file at the end of each
main-loop turn, and just before a main-loop Bash call that runs this script, while the
pinned plan is in `preflight`, `task` or `gate` and not stale
(`../../../hooks/mod/context.ts`, through `context-usage.py --write-sidecar`, which never
follows a link the repo planted). Gitignore it with the state file.
The script uses it only when its `session_id` equals `CLAUDE_CODE_SESSION_ID`, its `window`
is a positive integer, and its `updated` is under 15 minutes old. Below the state root the
read refuses links and non-regular files. The `reason:` then says `window from live session`. Otherwise the model
table decides, and an unlisted model is `unknown`. The sidecar supplies only the
window: the tokens still come from the transcript, and rules 1–4 of § The five stop rules are the
script's alone (rule 5, the dated wait, is the executor's): the band and hooks display, the script decides. The band's `context NN%` on the pinned row is a display of the
same engine figure, never a verdict.

**When.** Once per stage gate and once per sub-plan gate, **after** the
gate commit, **in a separate Bash call**. The turn that is running is not in the transcript
until its tool returns, so a `context-usage.py` chained onto the `Stage N green` commit does
not see that commit and reports the previous stage's cost. At a master plan's sub-plan
close-out, add `--sub-plan-boundary`.

**What it reads for per-stage cost.** A stage boundary is the turn whose Bash call runs a
real `git commit` whose *subject* is `Stage N green`. A compaction (`isCompactSummary` row)
resets the baseline, so no cost spans one. `last_stage_cost` is the most recent stage's cost.

## The five stop rules

Evaluated in this order; the script names the rule that fired and its numbers in `reason:`.

1. **Owner request** (`rule requested`): handoff when the owner's rollover request through
   the supervisor names this session. `context-usage.py` reads it at the gate, through
   `handoff-envelope.py`'s reader, and its `reason:` is `rule requested: owner asked for a
   rollover`. It wins over the first-stage exception and over an `unknown` measurement, but
   it is still evaluated only at a gate: a request that arrives mid-stage waits for the
   stage's gate commit. At the final gate there is no next task to hand off: the run goes
   on to close-out, which writes no `RESUME HERE`, and its report says the request arrived.
2. **Sub-plan boundary** (master plans, `--sub-plan-boundary`): handoff, unless the context is
   under 25% of the window. A sub-plan boundary is the natural reset point; below 25% the fresh
   session buys too little to be worth the resume.
3. **Context**: handoff when `now > 50` percent of the window, or when now plus
   `last_stage_cost` would pass 50%. Exactly 50% continues. **The first stage of a session
   always runs** — with no `Stage N green` commit in this session there is no cost history,
   and the verdict is `continue` whatever the percentage.
4. **Dead weight**: handoff when the next stage's `Scope:` / `Test:` paths are `disjoint`
   from every stage finished in this session **and** the context is above 25%. Nothing the
   session holds helps the next stage, so it pays for context it does not use. A stage with
   no `Scope:` field makes `disjoint` `unknown`, and `unknown` is never a stop.
5. **Dated external wait**: a gate check that cannot run before a named future date (a
   release, a store review, a device delivery) is written `- [~]` with the date, and the run
   hands off naming it. This rule's `reason:` is the dated check, quoted; paste the
   `context-usage.py` line beside it.

**Post-compaction re-grounding — not a stop.** When the session has compacted (the script's
`compactions` count rose), re-read the plan's `Status:` flips and handoff notes before the
next tool call. A compaction summary is not a source for task state.

## The bounds

Stated with the rules, not after them: every dispatch rule states its bound in the same
breath, because a rule without one gets over-corrected into its inverse. A stop
rule has the same failure shape, so the same discipline applies here.

- **`unknown` never stops.** A missing transcript, an unlisted model, a stage without
  `Scope:` — the script says `unknown`, the gate report says so, and execution continues.
  The one exception is the owner's request (rule 1): a missing measurement does not cancel it.
- **No rule applies before a gate.** A handoff happens at a stage or sub-plan gate, after its
  commit — never mid-stage and never mid-task.
- **A stop without the script's `reason:` line is not a legal stop.** "Context feels large"
  is the eyeball call this rule replaces. The Stop hook (`plan-continue-hook.md`) nudges
  through a `RESUME HERE` block that lacks a `reason:` line.

## On `continue`

Paste the verdict line verbatim into the handoff note as its `context:` line, and issue the
next stage's first tool call in the same turn (`stage-gate.md` § If the gate passes). The
gate report is already committed by then — the script runs after that commit — so the line
goes in the plan, not the report, and rides the next commit that carries the plan (a
plan outside the repo rides none).

## On `handoff`

`<repo root>` below is the git top level (`git rev-parse --show-toplevel`) — the one
handoff root (`../../../references/handoff-protocol.md`): where every envelope is written and where `context-usage.py` reads
the owner's request. A supervisor must resolve its project directory to the same root.

0. Mint the handoff id once, before the handoff commit, and keep it for steps 1, 3 and 4:

   ```
   python3 <planning-plugin>/skills/executing-plans/scripts/handoff-envelope.py new-id --root <repo root>
   ```

   (`../scripts/handoff-envelope.py`; it prints `h-` and 20 hex characters.)
1. Append a `RESUME HERE` block under the stage's handoff note. Write its heading in column
   0: a successor's `handoff-envelope.py verify` reads the plan's last such block and checks
   its `handoff_id:`, `cwd:` and `branch:` against the handoff.

   ```
   **RESUME HERE (<YYYY-MM-DD>):**
   handoff_id: <id>
   reason: <the script's reason: line, verbatim>
   plan: <absolute plan path>   cwd: <repo root>   branch: <branch>
   next: Task <N.M> — <title>
   `dispatch: …`  `review: …`  `residuals: …`   (the gate report's lines, verbatim)
   **Decisions in force:** <IDs>
   ```

   Before writing it, list the background tasks and agents this run started, by the id each
   launch result and completion notification carried, stop each whose result was used
   (`TaskStop`), and name each one still running in the block's `running:` line. Then run `python3 <planning-plugin>/skills/executing-plans/scripts/review-ledger-check.py --unstopped --repo <repo root>`
   and add to that line each agent it lists (exit 1) by id and type; with nothing from
   either, `running: none`; with no log (exit 3), `running: NOT RUN` beside the ids
   noted at launch. The successor must
   know what is still working before it starts anything of its own.
2. Commit it as its own `"Stage N handoff"` commit, whose body carries the same `reason:`
   line — the gate commit is already made, since the script runs after it. When the plan
   lives outside the repo, write the block at the plan's absolute path and make the same
   commit empty (`--allow-empty`), so the repo records why the run stopped.
3. Run `plan-state.py set-blocker` with disposition handoff, the
   prevented next operation, original measurement evidence, fresh-session dependency,
   remaining work, the script's verbatim reason and the minted `handoff_id`. The writer projects
   `phase: "handoff"`. Keep the handoff id in the
   RESUME HERE block and v1 envelope from step 0; that envelope protocol is unchanged.
   Unowned legacy display files retain phase/reason/handoff_id (`progress-state-file.md`).
4. Tell a supervisor the handoff is ready:

   ```
   python3 <planning-plugin>/skills/executing-plans/scripts/handoff-envelope.py ready \
     --root <repo root> --handoff-id <id> --plan <absolute plan path>
   ```

   With no supervisor present (no `PLANNING_SUPERVISOR_ID_CMD`, or a command that gives no
   valid id; `../../../references/handoff-protocol.md`) it writes nothing, prints
   `unsupervised` and exits 0: the id still rides the block and the state file, and the
   manual resume (**Resuming**, below) works as it does without a supervisor. A command that is set but gives no id also
   prints one line on stderr naming why (`PLANNING_SUPERVISOR_ID_CMD is set but gave no
   session id: <reason>`): the supervisor setup is broken and will not act on this
   handoff. The command runs with `PLANNING_HANDOFF_ROOT` set in its environment to the
   resolved `--root`, where the envelope is written or the request read; a supervisor may
   record it as where this session's envelopes appear, one that ignores it loses nothing,
   and a command that takes no arguments still works. If that line appears, or it exits 1 (`refused`), say so in step 5's line, so
   the user resumes by hand.
5. End the turn with the reason and one line telling the user to resume in a fresh session
   pointed at the plan path. That line is not an `ACTION NEEDED:` block — nothing is being
   decided.

**From step 3 on, the session owns nothing.** Its only remaining actions are step 4's
envelope and step 5's last line. It starts no task or gate, flips no `Status:`, and edits no
decision. The
plan now belongs to whoever resumes it; a supervisor may start that session as soon as the
`ready` envelope lands, and two concurrent sessions writing one plan would race.

**Resuming.** The new session reads the plan in full, finds the last `RESUME HERE` block, and
starts at the task it names; the Research Summary, `Status:` flips and handoff notes carry
everything else. A block too thin to resume from is the bug to fix. Close-out writes no
`RESUME HERE` — there is no next task.

## Adopting a handoff (`--adopt-handoff <id>`)

A supervisor starts the next session by typing
`/planning:executing-plans --adopt-handoff <id>` into it. That session proves it resumed the
handoff it was sent **before it owns anything**: no state file, no task, no `Status:` flip
until step 5.

**Any exit other than the ones each step names** — 2 for a malformed id, 1 for a refused
write, a missing interpreter — ends the turn with one `ACTION NEEDED:` line naming the
command and its exit, and no state file.

1. **Find the plan.**

   ```
   python3 <planning-plugin>/skills/executing-plans/scripts/handoff-envelope.py plan \
     --root <repo root> --handoff-id <id>
   ```

   It prints the plan the `ready` envelope names. On exit 3 (`no-ready`) run `fail --root
   <repo root> --handoff-id <id> --code no-ready` (no `--plan`: none is known) and end the
   turn as step 2 does.
2. **Verify.**

   ```
   python3 <planning-plugin>/skills/executing-plans/scripts/handoff-envelope.py verify \
     --root <repo root> --handoff-id <id> --plan <plan>
   ```

   Exit 0 means the `ready` envelope is there, and the plan's last `RESUME HERE` block names
   this id, this repo root and the branch checked out. On exit 3, record the printed code:

   ```
   python3 <planning-plugin>/skills/executing-plans/scripts/handoff-envelope.py fail \
     --root <repo root> --handoff-id <id> --code <printed code> --plan <plan>
   ```

   Then end the turn with one `ACTION NEEDED:` line naming the code. Write no state file and
   run no task: a session that cannot prove which handoff it holds must not touch the plan.
3. **Run Phase 1 in full**: the Research Summary, the `Status:` flips, `## Decisions in
   force`, and the last `RESUME HERE` block. A concern Phase 1 raises about the plan does not
   fail the adoption — the handoff is already proven yours: run step 5's `accept`, then
   surface the concern as Phase 1 step 4 does, before Preflight.
4. **Re-ground the task that block names** — read its fields and the files in its `Scope:`
   as they stand now, not as the block remembers them.
5. **Accept, then own.**

   ```
   python3 <planning-plugin>/skills/executing-plans/scripts/handoff-envelope.py accept \
     --root <repo root> --handoff-id <id> --plan <plan>
   ```

   Only then resume through the owned state API with dependency-resolution evidence
   (or initialize/migrate an evidenced legacy run) and continue normal Preflight. The
   supervisor stops the predecessor only after this envelope lands. `accept` and `fail` are
   one-shot per id: exit 1 here means another session already accepted or failed this
   handoff, so this one owns nothing — `ACTION NEEDED:`, no state file.

The manual path (**Resuming**, above) needs none of this: a session the user points at the
plan runs no `verify` and writes no envelope.
