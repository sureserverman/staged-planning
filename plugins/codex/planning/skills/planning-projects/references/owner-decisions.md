# Owner decisions — the questions execution would stop for, asked while planning

`executing-plans` stops to ask the owner at named points: a destructive command, a secret,
the branch, the merge. A run that halts on one of them mid-stage, often hours in, waits on a
question whose answer was known before Stage 1. So `planning-projects` asks those questions
while the plan is written (`../SKILL.md` § Ask execution's questions now), and records the
answers in the plan, where the executor reads them before it asks
(`../../executing-plans/SKILL.md` § Stop conditions).

This file is the catalog of those points and the format of the record. Consulted once per
plan, after the draft exists and before it is presented.

## The record

Every plan carries the section, directly below `## Decisions in force`. Its bullets are not
checkboxes: a raw `- [ ]` there would read as deferred work to the plan parser.

```markdown
## Owner decisions

- **OD-1** — <the decision, in one line> — owner, YYYY-MM-DD: "<their words>" — applies to: <one place: Preflight, close-out, Stage N or Task N.M> (`<each command it covers>`)
- **OD-2** — <the decision> — ask at execution — applies to: <the case>
- **OD-3** — <the answer> — owner, YYYY-MM-DD: "<their words>" — applies to: Rule spent-rounds
```

- **The owner's words, quoted, with the date.** An answer the author inferred is not an
  owner decision; it belongs in the Research Summary as an assumption, and the executor
  still asks.
- **`applies to:` names the case exactly** — the command (`git push origin main`), the stage,
  the task. An entry covers the case it names and nothing wider: a yes to one migration is
  not a yes to the next. It applies only when every qualifier of its `applies to:` holds — an
  entry naming Stage 2 does not cover a one-stage plan's close-out — and the executor never
  reinterprets it to fit; it asks.
- **`applies to:` uses the words `owner-decision.py` reads**: `Preflight`, `close-out`,
  `Stage N`, `Task N.M`, `Sub-plan N` (in a master), `Rule <kind>` (a standing rule, below),
  and a backticked command with its
  arguments (`git push origin main`); every code span there is a command, so name a branch
  in plain words in the decision. Only `and`, `only`, `the`, `at`, `in`, `of`, `on` and
  punctuation may sit between them. One entry covers one position: Preflight, close-out and
  a stage never combine. `applies to:` comes once, last, after the owner's quoted words.
  Commands match as exact text: `rm -rf '*'` is not `rm -rf *`, and `git merge x` is not
  `git merge --no-edit x`, so name the command exactly as the run will type it.
- **Each entry is one physical line**, starting `- **OD-N** — `, and there is nothing else in
  the section: no notes, headings, comments, sub-bullets or continued lines — only entries,
  blank lines and the `none` line. Put an amendment note before the `## Owner decisions`
  heading. The executor acts only on an entry `owner-decision.py match` lists, and it
  refuses any entry with another word in `applies to:`, and every entry in a section with
  another line: deny by default, so "except", "not" or "only if" can never widen one.
- **Every line of the section is plain printable text**: ASCII and the two dashes, no other
  character. Outside code spans an entry holds no `<`, `>`, `~`, `%`, `&` or backslash, and
  no adjacent or unbalanced backticks: struck-through, hidden or commented text would show a
  reader something other than what the script reads. Raw HTML, an HTML comment, an
  Obsidian `%%` comment or a `$$` math block anywhere before the section's end voids the
  section, and a plan with one before its `Master:` line inherits nothing.
- **What this guards against** is careless writing and careless reading — a scope stretched
  to fit, a restriction left where the reader does not look, a command almost the approved
  one. It is not against an author deliberately crafting a plan to deceive; the owner's
  answers are only as honest as the plan that records them. Before the
  plan is presented, run
  `python3 <planning-plugin>/skills/executing-plans/scripts/owner-decision.py check <plan>`:
  it reports, with its line, each entry `match` would refuse for its form, by `match`'s own
  rule: one naming a stage, task or sub-plan the plan lacks; one carrying neither the owner's
  words nor `ask at execution`; an `applies to:` word the reader cannot place, which it names
  (`gate` in "the Stage 1 gate"); a code span that holds no command; and a line that is not
  an entry, which voids every entry in the section. Exit 0 is clean.
- **A standing rule is `applies to: Rule <kind>`**, one of the four kinds in
  § Standing rules: asked in every plan, and nothing else beside it (in a master, `Sub-plan N` may sit beside it). It covers
  the whole plan, wherever the run meets that kind of event, and in a master every
  sub-plan. A sub-plan's own entry for the kind replaces the master's, and a master entry
  naming the sub-plan replaces one naming none. One entry decides a kind, or the run asks:
  an answer beside another entry for its kind there (a second answer, an `ask at
  execution`, a malformed entry) answers nothing. It never confirms a command:
  `match --rule <kind>` lists it, and a case passing `--command` or `--require-command`
  never does. `check` refuses an unknown kind, a `Rule` beside a position or a command, and
  an answer that shares its place with another entry; for each kind no entry names (an answer or an `ask at execution`) it
  prints `note: no entry for Rule <kind>`.
- **A declined question is recorded `ask at execution`**, so the executor knows it was asked
  and stops there as it would have.
- **A plan the catalog triggers nothing for** carries one bullet:
  `- none — the catalog triggered no question (swept YYYY-MM-DD)`, so "nothing to ask" reads
  differently from "nobody looked".

## How to ask

- **One batched round**, once the draft exists: the draft is what shows which points the
  plan reaches. Up to four questions per prompt, in the host's question tool where it has
  one; more questions take more prompts in the same round.
- **Each question is multiple choice**, the recommended option first, with what each
  option makes the run do. "Other" stays open for the owner's own words.
- **The option marked Recommended is the smallest one that meets the request as the owner
  wrote it.** An option that adds scope says what it adds, in tasks or stages, and carries
  the mark only when the request asks for it. The mark is advice; the answer stays the
  owner's.
- **A standing question offers, first, the answer the project's most recent plan recorded
  for that kind**, when there is one, so the owner confirms it rather than answers anew;
  with no earlier answer, the smaller option comes first. Offered first is not marked
  Recommended: the mark still goes to the smallest option that meets the request, and an
  earlier answer that adds scope says what it adds, as any larger option does.
- **A follow-up round only for what the answers raise** — a new branch name, a command the
  owner narrowed.
- **Scope questions are not in this round.** They come first, batched, in `../SKILL.md` § Phase -1
  — the plan cannot be drafted without them.

## The catalog

### Standing rules: asked in every plan

Four kinds of event recur across runs and stop them. An entry naming one position could
not answer them in advance, so the same question came back at the next gate or sub-plan. These are asked in every plan's batched round, at every
size, one question each. Each answer is one entry, `applies to: Rule <kind>`, and covers
the whole plan; in a master it covers every sub-plan. The kind names are the closed list
`owner-decision.py` reads (`KINDS`); a kind added to one is added to the other.

| Kind | The event | The question | One option | The other |
|---|---|---|---|---|
| `unshown-outcome` | at close-out, before the merge, an Outcome's demo verdict is `not shown here` | An Outcome the session cannot show (name each one whose bullet ends with a `*(needs: …)*` note): does the merge wait for it? | List it in the close-out report and go on to the merge step (the merge still needs its own answer) | Hold the merge until the owner has checked it |
| `outside-defect` | a defect turns up outside the plan's tasks | A defect outside this plan's tasks: what does the run do? | File it in the backlog and go on | Fix it in this run, its class swept (adds the fix and its sweep to this run's work) |
| `spent-rounds` | a gate has spent its fix rounds and findings remain | A gate out of fix rounds: what does the run do? | One more round when the cause of what remains is known, then stop if anything Critical is open | Stop and report |
| `wrong-check` | a written check cannot run as written (a wrong path, a wrong count, a selector that collects nothing) | A check that cannot run as written: what does the run do? | Amend the command, keep the old one beside it and go on | Stop and report |

### Where the executor stops: its Safety rails and Stop conditions

One row per bullet of `../../executing-plans/SKILL.md` § Safety rails and § Stop conditions, by its
opening words. **Ask while planning** means the answer can be known now; **stays a stop**
means the case turns on evidence that does not exist until the run produces it, so no
answer given in advance can cover it — planning lowers the odds instead, as the row says.
`tests/test-owner-decisions-contract.py` fails when a trunk gains a bullet this table
does not name.

| Execution point (opening words) | Class | When the plan reaches it | The question, or what planning does instead |
|---|---|---|---|
| Never start on main / master without explicit user consent | ask while planning | always | Which branch or worktree does the run use? (A yes to `main` is the consent the rail asks for.) |
| Destructive commands | ask while planning | a task, gate or close-out runs a schema migration, a data delete, a force push, a branch deletion, a release push or a production deploy | May the run do `<exact command>` at `<task or close-out>`? One question per command. |
| Secrets | ask while planning | a task reads or writes a credential | Which mechanism holds it — which environment variable, which secrets manager entry? |
| Shared infrastructure | ask while planning | a stage changes a staging or production-adjacent system | May Stage N change `<system>`? One question per stage. |
| The host's own footing | stays a stop | a gate needs a device on another network | Plan a second interface, a spare client or a remote agent; the rail is never waived. |
| Preflight fails | stays a stop | always | Check the tools, keys, devices and access the plan needs now (`../SKILL.md` § Phase 1), and ask for any that is missing; the dry run runs every check that only reads (`dry-run.md`). A Preflight check wrong as written is answered by `Rule wrong-check` (§ Standing rules: asked in every plan). |
| A task exhausts its Red-Green cycle budget | stays a stop | always | Give each task a `Test:` that can be run today. |
| A stage gate's remediation budget is exhausted | stays a stop | always | Shape gate checks so a class can fail them (`../SKILL.md` § Phase 4). What the run does then is answered by `Rule spent-rounds` (§ Standing rules: asked in every plan). |
| The plan contains an instruction you don't understand | stays a stop | an instruction still reads "A or B", "TBD" or "decide later" | Ask the choice now; a plan presented with an open choice has one of these built in. |
| A test cannot be run | stays a stop | a test needs a fixture, a service or a device | Check it exists now, by the dry run's probe of each `Test:` and gate command (`dry-run.md`); ask for access to any that does not. A test command wrong as written is answered by `Rule wrong-check` (§ Standing rules: asked in every plan). |
| A mandated verification or dispatch cannot be performed | ask while planning | the dispatch roster is non-empty | If dispatch is unavailable in the session, may those tasks run inline (`Executor: inline (user authorised)`), or does the run stop? |
| Verifying the test requires modifying shared infrastructure | ask while planning | a task's test touches a production DB or a live service | May `<task>`'s test change `<system>`? |
| An Outcome cannot be met as written | stays a stop | always | Write Outcomes the product can meet; one the session cannot show is a residual, not a stop (`../SKILL.md` § Phase 2); what the merge does about it is answered by `Rule unshown-outcome` (§ Standing rules: asked in every plan). |
| The plan's premise is false | stays a stop | a stage's Risk is HIGH or its Goal relies on something outside the code | Check the premise now, on the real environment, where it can be checked, and record it in the dry run's `Premises:` line (`dry-run.md`). |

### Other points where the executor asks

| Execution point | When the plan reaches it | The question |
|---|---|---|
| Close-out: the merge offer | always | What happens to the branch: merge into `<base>`, open a pull request, or leave it? Delete it after? Push? Tag? |
| Close-out: the version bump | the repo versions its releases | Which version, and which mirrors carry it? |
| Git bootstrap: the remote | the repo has no remote, or Preflight would create the repo | Create a remote? Private or public, and where? |
| A plugin that must be enabled (`requires_enablement`) | the dispatch roster routes to one | Enable `<plugin>` now? |
| `Review: skip` | the author judges a task's diff not worth a review | May `<task>` skip its review? Only the owner's yes writes the field. |
| A redesign's sign-off | a redesign stage applies a destructive behavior change | May the run apply `<change>`? (The stage keeps its sign-off task for changes not known yet.) |
| A check needing a person | a gate or close-out needs someone the session cannot reach | Who does it, and does close-out list it as `ACTION NEEDED:` or wait? |
