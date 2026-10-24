# Set-valued gate checks — write the sweep that proves the property

The class-predicate rule and the `validate-gate-checks.py` contract.

### Write a set-valued check as the sweep that proves it

A check asserting a property of a **set** — "no file still claims X", "every example sets
Y", "all callers handle Z" — is written as the **command that sweeps the set**, never as
prose about one member of it:

- **BAD** — `- [ ] the README no longer claims the installer requires root`
- **ALSO BAD** — `` - [ ] `grep -q 'installer requires root' <plugin>/README.md` exits 1 ``
- **ALSO BAD** — `` - [ ] `grep -c 'x' <plugin>/README.md` = 1 and no stale claims remain`` — bolting plural-sounding prose onto a narrow command does not widen its scope; the sweep still never runs
- **GOOD** — `` - [ ] `! grep -rl 'installer requires root' <plugin>/` `` — no file in the plugin still carries the claim

The first form is not merely vaguer. **An instance-shaped check cannot fail on the siblings
that make the class**, so it passes while the other members of the defect class survive — and
each survivor costs another remediation round at the gate. Naming one file where the goal is a
property of many is how a single defect gets discovered three times.

The second form is the trap worth naming explicitly: **being a shell command is not the
point — scope is.** A command that inspects exactly one path is every bit as instance-shaped
as the prose, and it will pass a mechanical classifier that can only read syntax. Scope the
command to the set (a directory, a glob, a file list you generate), not merely to something
that looks executable.

So when writing a gate check, ask what set the claim is really over. If the answer is more
than one artifact, the check is a command **over that set**. If the claim genuinely needs a
reader — "reads coherently", "the flow works end-to-end", a conformance judgment over a diff
— mark it **`(judgment)`** and name why a sweep cannot prove it, so the executor routes it to
the evaluator instead of trying to make prose executable. Those two shapes cover every
legitimate check; anything else is an instance-shaped claim waiting to be rewritten.

### The opposite error: widening past the set the claim is over

Those pressures push one way, so the failure they produce is over-correction — and that one
is worse than the mistake it avoids, because the check does not merely fail to catch things,
it **cannot pass at all**. An example:

- **BAD (too wide)** — `` ! grep -rln 'BL-NNN' <records-root>/ --include='*backlog*.md' | grep . `` — "the entry is removed from every register that carries it"
- **GOOD** — `` ! grep -l '^## BL-NNN ' <records home>/backlog.md ``

Backlog IDs are unique **within one project's register**, not across projects. Every other
project numbers its own entries from the same first id, so the wide sweep matches unrelated
entries and reports failure whatever the plan does. It also matches any *mention* of the string
— a `Closes BL-NNN` in a neighbouring entry, a note explaining the removal — rather than the
entry itself, which is why the `^## ` anchor belongs in it too.

**One artifact is instance-shaped only when the claim is over many.** "Every file in this
plugin has stopped saying X" is a set of files and needs `-r`. "This project's register no
longer holds this entry" is a set of exactly one register, and naming it is correct rather
than lazy. The question is never how many paths the command touches; it is whether the paths
it touches are the ones the claim is about.

**A check nobody can pass is not a strict check, it is an absent one** — and it is worse than
absent when an executor takes it literally: a removal written against its premise deletes
unrelated entries, and a register with no version control cannot get them back. So
before writing a sweep wider than one file, **run it once against the current tree and read
what comes back.** If it returns matches the plan will never remove, the scope is wrong.

**Mark it `(scoped)` and say why.** The validator cannot tell a correct narrow check from the
harmful one — nothing in `grep -l X one/file.md` reveals whether that file is the whole set —
so without a marker it fails both, and an author obeying it widens a claim that should not be widened.
The marker is the third sanctioned shape beside `(judgment)`, and it carries the same bargain:
the author asserts the thing syntax cannot see, in the check, where a reviewer can read the
sentence and disagree with it.

```
- [ ] **(scoped)** `! grep -l '^## BL-NNN ' <records home>/backlog.md`
      — backlog ids are unique within one project's register, so this file is the whole set
```

Use it only when one artifact really is the set. It is not a waiver for a narrow check over a
wide claim — that is still INSTANCE-SHAPED, and the identical check without the marker still
fails, which `tests/test-validate-gate-checks.py` group 2b pins in both directions.

### The third error, orthogonal to both: the right set, swept in the wrong direction

Scope is not the only way a set-valued check can be structurally unable to do its job. A check
can sweep exactly the right set and still be blind for its whole life, because **it can only
fail in one direction and the hazard runs the other way.**

The common shape is an allow-list: *"X appears only at A, B and C."*

```
! grep -rn 'CacheStore(' src/ | grep -v 'bootstrap.py\|infra/cache.py'
```

That fails when a **new** member appears — a second constructor call, an unauthorised caller, a
leaked import. Where the hazard is an unwanted presence, it is exactly right, and most
allow-list checks are.

It is structurally blind when the hazard is an **absence** — a path that *should* do X and
doesn't. No missing call ever adds a line for a grep to find, so the check is green on the day
the defect ships and green every day after. Worse, it reads as rigorous: it names a set, it
sweeps a tree, it passes the validator.

**So name the hazard's direction before choosing the check's shape.** Ask what the defect
would look like in the tree:

| The hazard | Its shape in the tree | The check that can fail on it |
|---|---|---|
| an unwanted writer, caller, import, claim | a **new line** somewhere | an allow-list sweep (`! grep … \| grep -v …`) |
| a required call, guard, publish, invalidate that is **missing** | **nothing at all** | an invariant asserted over every operation — a test, not a grep |

Where they disagree, the check will be green for the entire life of the defect. This is the
authoring-time face of the same fact `executing-plans` records for repair time
(`../../executing-plans/references/bug-is-a-class.md` § *Two shapes*): an absence-shaped class
has no searchable fingerprint, so it is asserted as a property and never enumerated.

**The validator cannot help here, and the reason is worth stating.** Measured over one owner's
plans (undated): five gate checks share the allow-list shape to the character, and all five are
correct, because each one's hazard is a new presence. A sixth with identical syntax is blind
for its whole life because its hazard is a missing call. The syntax is the same; only
the hazard differs, and the hazard is not in the text. A classifier would have to reject all
six or accept all six. **This one is an authoring judgement, and the checklist item below is
the only thing enforcing it.**

A gate check whose claim is an absence — "every path that changes the cursor publishes it",
"every writer takes the lock", "no request leaves without the header" — belongs in a task's
`Test:` as an invariant test, with the gate check *running* that test. Writing it as a sweep of
the sites the plan chose produces a check that verifies the design against itself.

This is enforced mechanically rather than left to discipline. `../scripts/validate-gate-checks.py`
classifies every check in a plan as EXECUTABLE / JUDGMENT / SCOPED / INSTANCE-SHAPED / PROSE, and
`executing-plans` runs it at critique time (its Phase 1 step 4a). Run it on the plan before
you present it:

```bash
python3 <planning-plugin>/skills/planning-projects/scripts/validate-gate-checks.py <plan>
```

**A newly authored plan must come back clean** — zero INSTANCE-SHAPED. Existing plans are only
*reported* by `executing-plans`, never retro-failed; that asymmetry is
deliberate, because a check executors learn to route around protects nothing.

### The fourth error: grep cannot read prose, so the check dies when you document the thing

A sweep can have the right set, the right direction, and still be unable to go green — because
**grep matches a paragraph about the code exactly as readily as the code.**

```
! grep -rn 'Disk full\|Try again' src/ | grep -v 'ui/messages/'
```

The property meant here is real: *only the messages module carries user-facing error wordings.* The
instrument cannot measure it. The day someone writes a comment explaining when a user
sees "Try again", the check goes red — and nothing is wrong with the code. **The check fails
precisely when the codebase is at its best-documented.**

Measured over one owner's plans (undated), not supposed: four checks of this shape **all failed on comments and docstrings,
none on a defect**. A dependency check such as `! grep -rn '"git"' src/app/` matches
`REQUIRED = ("git", "make")` — the dependency's own name.

**Write it as a test that reads values, not text.** The repair is an architecture test that
collects the wordings each module *declares* and asserts the set; it excludes docstrings by
construction, is mutation-checked, and runs on every commit rather than on the day somebody
runs the plan. Reading values, it can also catch what a grep never can, such as one wording
declared twice.

**The tell:** ask whether your pattern could appear in a sentence *about* the code. `flush-cache`,
`Try again` and `"git"` all can. `ALLOWED = frozenset` mostly cannot — it carries syntax
— so a check for it is not tripped by prose.

**The legitimate twin, so you can tell them apart.** The identical syntax is right when you mean
*any occurrence at all*:

```
! grep -rn 'sk-ant-' .          # a committed secret is a secret in a comment too
! grep -rn 'TODO' src/          # a TODO in a comment is the only kind there is
```

There the prose match is the point. `validate-gate-checks.py` flags this shape as a **note, never
a failure**, because no rule can tell which one you meant — measured by 2026-09-11 over 682 plans from one owner's records homes: 203
instances across 110 of them, the most frequent being secret scans. The note is a question, not
a verdict: *is this about what the code does, or about what the bytes say?*

### The fifth error: a sweep that matches one spelling of a call

A gate that forbids a call — "the codec is reached only through its sandboxed entry
points" — is a sweep for the forbidden name. Written as the *qualified* spelling, it misses
every other spelling. Suppose this gate:

```
! (grep -rnE 'demo_codec::[a-z_:]*(decode_frame|encode_frame)[a-z_]*\(' src | grep -v '_sandboxed(')
```

Suppose the module it checks starts with `use demo_codec::{decode_frame_sandboxed, …};` and
then calls the functions bare. A `use demo_codec::decode_frame;` followed by
`decode_frame(&buf, &opts)` passes that gate: the forbidden call is there, and the sweep is
looking for the `demo_codec::` prefix that the import removed. Right code and wrong code look
the same to it: plant `use demo_codec::decode_frame;` and a bare `decode_frame(&buf)` and the
gate stays green.

So sweep for the **bare name** at a word boundary. `-w` treats `_` as part of a word, so the
permitted `decode_frame_sandboxed` is a different word and needs no exclusion — and an
exclusion such as `| grep -v '_sandboxed'` would be wrong, because it drops a line that
imports both names:

```
! grep -rnwE '(decode_frame|encode_frame|decode_frame_with_opts)' src
```

The same planted call fails this sweep on both lines, the import and the call.

The same holds in every language with imports or aliases: Python `from x import f`, Kotlin
imports, JavaScript destructuring. If the forbidden thing can be renamed on import
(`use a::b as c`), a name sweep cannot prove its absence at all — sweep the imports
(`use .*decode_frame\b`) as well, or make it structural (a test that the module exposes
nothing else).

### The sixth error: a sweep that filters the set down to one category

A sweep can read the right table and still check only part of it. Suppose this
gate:

```
awk -F'|' '$4 ~ /public/ {gsub(/[ `]/,"",$2); print $2}' docs/<inventory>.md | sort -u | while read p; do …
```

It proves every `public` endpoint row has an owner. If `internal` rows need owners too, the
filter keeps every one of them out of the sweep: the gate passes, and the gap is found only at
close-out.

The filter is not the defect. The unstated exclusion is: nothing in the check says why the
rows it drops need no check. So for a sweep restricted by a category — an awk field match
(`$3 ~ /…/`), or a grep narrowing what `git ls-files`, `find` or `ls` printed — either widen
the sweep to the whole set, or say why the subset is the whole set. `(scoped)` is the answer
for the second case: the author asserts it in the check, where a reviewer can disagree.

`../scripts/validate-gate-checks.py` reports this shape as FILTERED-SUBSET, an advisory note
(measured 2026-10-08 over 800 plans in one owner's records homes: 13 hits, 1 true positive — most filters are
right, and most say why in prose). A plan's `(goal)` check is never filtered this way
(`gate-authoring.md` § The plan's goal is a check from the first gate).

## Worked example — a sweep is not licence to sweep twice

The rules pull in opposite directions and both are right. This one says *widen the check to
the set*; the trunk's § *Every fact has one owner* says *don't verify what a task test
already decided*. What resolves them is that the gate owns the **class** and the task owns
its **instance** — so a gate sweep is legitimate exactly when the set it covers is strictly
wider than what any task proved, and the widening can be named.

Suppose one fact, *the CSV export is gone*, is verified four times:

| # | The check | Verdict |
|---|---|---|
| 1 | Task 1.1 `Test:` — the router serves no `export_csv` route | **Keep.** The task owns its instance; nothing else proves this router change is right. |
| 2 | Stage-1 gate — `! grep -rn 'export_csv\|text/csv\|csv_dialect' src/` | **Keep.** Strictly wider and nameable: the task proved one file, this sweeps the tree for the whole vocabulary. |
| 3 | Close-out gate — the same grep again | **Keep.** Same command and same *set*, but a **larger population**: two stages of commits landed since check 2 ran. A negative-existence sweep is a regression guard, and its whole value is re-running over a tree that has grown. |
| 4 | `(judgment)` — "no surviving claim that a report can be exported as CSV" | **Cut, or narrow.** As written it restates check 2 and spends an evaluator dispatch on it. It earns its place only against what a grep genuinely cannot decide — that the two surviving mentions of "CSV" are *denials* rather than assertions — and then it says so. |

Three of the four are coverage and one is cost.

**The boundary that decides rows 1 and 3 is the same one, read in two directions.** A task's
`Test:` is not re-proved *at that stage's gate*, because the task's commit is inside the
stage the gate is about to check — the population is genuinely identical. Across a **stage
boundary** it is not: later commits can reintroduce what an earlier sweep proved absent, and
nothing else is looking. So "one owner per fact" retires *repetition within a stage*, and
leaves *regression sweeps across stages* alone. A negative-existence check (`! grep -r …`) is
almost always the second kind.

Cutting row 3 for being "the same command, the same set, the same population" is wrong: the
first two are true and the third is not, and the cut removes the only guard against a late stage reintroducing the vocabulary — a rule against redundancy
deleting a real check, which is the failure mode this whole reference exists to prevent in the
opposite direction.

Be honest about where the "mandatory" half lives: it is **this checklist**, and nothing else.
No plan-file marker records that a plan was validated, so `executing-plans` cannot tell a
post-rule plan that skipped the check from a legacy one — it reports either identically. A plan
authored outside this skill, or hand-edited after authoring, reaches execution unenforced. If
that becomes a real leak, the fix is a marker the authoring check writes and the executor looks
for; today it is discipline with a mechanical *reporter*, not a mechanical *gate*. Calibrated
against a frozen corpus of real plans kept outside this repo; that corpus and its figures, its known limits, and both author-asserted
markers, are stated in the script's own docstring.
