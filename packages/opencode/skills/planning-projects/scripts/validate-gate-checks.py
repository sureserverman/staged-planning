#!/usr/bin/env python3
"""Classify a plan's stage-gate checks and audit its task `Test:` fields.

Why this exists: a gate check asserting a property of a *set* — "no file still
claims X", "every example sets Y" — must be written as the command that sweeps
the set. An instance-shaped check names one member, so it CANNOT fail on the
siblings that make the defect class; they survive the gate and each one costs
another remediation round, so one defect class can take as many gate rounds as it
has members.

Every legitimate check has one of three shapes:

    EXECUTABLE  a command that sweeps the set it is claiming over
    JUDGMENT    marked `(judgment)`, because a reader genuinely must verify it
    SCOPED      marked `(scoped)`, because one artifact really is the whole set — a
                backlog ID unique within one register, a single generated manifest.
                The author asserts it in the check so a reviewer can disagree; syntax
                cannot tell this from the harmful narrow form, and widening it anyway
                produces a check that cannot pass at all rather than a stricter one.

Two failure shapes:

    INSTANCE-SHAPED  names one concrete artifact with no sweep and no marker.
                     Includes a command scoped to a single literal path — being
                     a shell command is not the point, scope is.
    PROSE            neither executable nor marked, and names no artifact. Weaker
                     signal (reported, not failed): often a judgment check that
                     lacks its `(judgment)` marker.

One further failure, on a SEPARATE axis from shape — a well-shaped check can still be
impossible to run:

    SELECTOR-UNMATCHED  a gate check whose `pytest <file>.py -k <expr>` selector matches
                        no task `Test:` field in the same plan. The gate cannot pass as
                        authored, and nobody finds out until execution. A typical case: a gate
                        names an e2e file with a filter collecting zero tests in it.
                        Reported and counted separately
                        so the shape calibration below stays comparable; `(judgment)` and
                        `(scoped)` exempt, and a bare `pytest <file>.py` with no `-k` is
                        never a selector (a whole-file regression run is legitimate, and
                        syntax cannot tell it from the defect).

    SELECTOR-UNMATCHED (gradle/cargo)  the same cross-reference for a Gradle `--tests
                        '<pattern>'` and a `cargo test <filter>`. ADVISORY, never failed:
                        measured 2026-10-06 over 595 plans (every plan in one owner's records homes): 36 Gradle/cargo
                        gate selectors in 23 plans, 24 hits in 18 plans. The hits include
                        a selector naming a test that already exists outside its plan
                        — the false-positive shape the pytest form documents — so
                        not every hit is a defect, and a check is blocking only when every
                        measured hit was (gate-authoring.md § A gate heuristic ships with a
                        severity axis and a measured trigger rate). Preflight's probe
                        settles each one at run time.

A FOURTH axis — REPORTED, NEVER FAILED, and the reason why is the interesting part:

    PROSE-BLIND-SWEEP   a negated recursive grep over a source tree, for a pattern of
                        bare words. grep cannot tell a string the code *sends* from a
                        paragraph *about* that string, so such a check fails the moment
                        somebody documents the thing it forbids — which is exactly when
                        the codebase is behaving well. Measured over one owner's
                        plans (undated): four checks of this shape all failed on comments and docstrings, none on a
                        defect. The repair is an
                        architecture test that reads VALUES rather than text.

                        A NOTE rather than a failure, because the same syntax has a
                        legitimate twin this script cannot distinguish from the defect.
                        Measured by 2026-09-11, before choosing, over 682 plans from one owner's records
                        homes: 203
                        instances across 110 of them, and the most frequent patterns include
                        `sk-ant-` (a committed-secret scan) and `TODO`. For those,
                        matching a comment is the POINT — a secret in a comment is still
                        a secret — and grep is exactly the right instrument. The defect
                        and the correct use differ only in what the author meant by the
                        pattern, which is not syntactic, so this follows PROSE and the
                        `Scope:` advisory rather than INSTANCE-SHAPED. An advisory that
                        is wrong on its own stated criteria teaches authors to route
                        around it; failing 16% of the corpus on a judgment the script
                        cannot make would be exactly that.

                        Narrow anyway, so the note stays worth reading: negated AND
                        recursive AND bare-word-patterned (`ALLOWED = frozenset`
                        carries an `=` and is left alone), with a comment-excluding
                        pipeline exempt and
                        `(judgment)`/`(scoped)` exempt as elsewhere.

A THIRD axis, and the only one that leaves the gate section entirely — it reads the
plan's TASK fields:

    TASK-TEST-UNSCOPED  on a plan that declares expensive-suite tiering, a task whose own
                        `Test:` command collects the whole suite: no path, no filter, and
                        no explicit `full-suite: accepted` on the task. Measured over one owner's
                        plans (undated): one such task `Test:`, a marker deselector with no path, ran ~3.5 h
                        against a 3132-test collection inside one Red-Green loop, while
                        the declared stage-scope command took ~7 min.
                        Armed only by a plan declaring stage-scope AND plan-scope
                        commands — below guard rail 1's ~5 min threshold there is nothing
                        to bound. Master plans are skipped: they carry no tasks.

    STAGE-SCOPE-WIDE    a declared `stage-scope:` command naming four or more test trees or
                        modules with no `justified:` clause giving one reason per tree
                        (`justified: tests/a — Stage 1 edits it; tests/b — Stage 2 imports
                        it`); the note names each unjustified tree. ADVISORY, measured
                        2026-10-06 over the 119 plans in one owner's records homes that declare stage-scope: 49
                        hit, and the hits include a `:app:lintDebug
                        :app:assembleDebug`, which the tree count reads as test trees — so
                        not every hit is a defect, and the finding stays a note
                        (gate-authoring.md § A gate heuristic ships with a severity axis and
                        a measured trigger rate). Cost is not decidable from text either,
                        but a stage-scope that lists most of the project is the full suite
                        under another name and pays plan-scope cost at every gate. Measured: a
                        seven-tree declaration at 10.5 min ran 40 times in four sessions (one owner's, undated). test-scope-tiers.md says narrow it
                        to the trees the stages touch or depend on when it crosses ~5 min.

    GOAL-CHECK-MISSING  a Standard or Light plan with no gate check marked `(goal)`, or a
                        master register entry whose `**Gate:**` block has none. `(goal)` marks
                        the check that sweeps the plan's goal over the WHOLE artifact the goal
                        is about; it is orthogonal to shape, so a `(goal)` check is still
                        classified (an instance-shaped one is still INSTANCE-SHAPED). Why: when
                        each stage's checks cover only part of the goal, every gate passes,
                        and the gap surfaces only at the first reader of the plan goal,
                        usually the close-out evaluator. It checks
                        presence, not placement: one `(goal)` check in the final gate reports
                        zero, so placement from the first gate is the author's to check.
                        ADVISORY, because the corpus plans were written without the marker:
                        goal-check-missing: measured 2026-10-08 over 800 plans in one owner's records
                        homes: 735 hits (512 plans and 223 master register entries; 2 plans
                        already carried the marker). The 800 are every .md in the corpus's
                        plans folders, about 190 of them design or architecture files; 610
                        match `*-plan.md`. The marker is matched anywhere in a check's
                        text, so a prose
                        mention of `(goal)` also counts as presence. No hit was authored under the rule, so the rate says nothing about
                        precision yet. planning-projects' authoring checklist requires zero on
                        a NEW plan, as it does for INSTANCE-SHAPED.

    FILTERED-SUBSET     an EXECUTABLE sweep restricted by a category filter: an awk field
                        match (`$4 ~ /public/`, `$2 == "x"`), or a grep narrowing the rows of a
                        command that enumerates the set (`git ls-files | grep -v …`). A check
                        such as `awk -F'|' '$4 ~ /public/'` sweeps the `public` rows only
                        while `internal` rows may need the same check, and shape classification alone
                        reads it as a plural sweep. The note asks the author to state
                        why the excluded members need no check — `(scoped)` is that
                        statement — or to widen the sweep. Not noted: `grep -q` (an assertion),
                        a positive grep closing the command or followed only by counting
                        stages (`| wc -l`; the check's own predicate), unless a `)` closes a
                        substitution after it, whose output IS the outer set; an
                        anchors-only pattern (`grep .`), and a grep after a stage that changes
                        what the rows are (`xargs grep -c`, `while read`). ADVISORY:
                        filtered-subset: measured 2026-10-08 over the same 800 plans:
                        13 hits in 10 plans; sampled 13 hits: 1 true positive. The
                        other 12
                        exclude by design — the current dated window from a "no prior record
                        changed" diff (6), a sandbox, a test run separately in the same check —
                        and most say so in prose. So a hit is a question, rarely a defect.
                        Limits: a `"$(…)"` span is read through to its matching `)`, and a
                        `"…"` with `$(` later inside it is treated as quoted; a backslash-escaped
                        `\\|` is read as a pipe, which splits a filter wrongly; and three lists are
                        fixed: enumerators (ls, find, fd, rg --files, git ls-files / ls-tree /
                        diff --name-only), row-preserving stages (sed sort uniq cut tr awk
                        grep — `head`, `tee`, `egrep` and a leading `cd …&&` are missed), and
                        counting stages (wc head sort uniq). `--invert-match` is not read as
                        `-v`. Each list member missing is a false negative.

Exit 0 when no INSTANCE-SHAPED, no SELECTOR-UNMATCHED and no TASK-TEST-UNSCOPED finding
is present, 1 otherwise, 2 on bad usage. PROSE-BLIND-SWEEP, STAGE-SCOPE-WIDE,
GOAL-CHECK-MISSING and FILTERED-SUBSET never change the exit code. Always prints a per-class count and the total
examined: an empty sweep must not read as a pass (honest-gates).

Known limits, stated rather than implied (honest-gates). CALIBRATION is measured over a
frozen corpus of real plans kept outside this repo, because real plans hold their owner's
data; scripts/corpus-regress.py re-runs this script over it and fails on any per-plan
change. In the repo, tests/test-validate-gate-checks.py group 9 pins every class against
the synthetic tests/fixtures/gate-shapes/every-class-plan.md, so the branches are
exercised wherever the suite runs, CI included. Every figure below is measured over that
frozen corpus — except where a bullet says otherwise, which is the one thing worth
reading carefully here:

  - Calibrated against 53 gate checks in a corpus of 4 plans (3 real, plus 1 authored
    in the `Dispatch:` spelling that adds 5 EXECUTABLE): 26 EXECUTABLE, 7 JUDGMENT,
    3 INSTANCE-SHAPED, 17 PROSE. The figures move only when someone deliberately
    re-records that corpus. Those 3 INSTANCE-SHAPED are non-compliant existing plans,
    which is why `executing-plans` treats this as advisory on existing plans and mandatory
    only for newly authored ones.
  - A check carrying BOTH a narrow command and explicitly plural language ("`grep -c x
    one.md` = 1 and no stray refs remain") classifies EXECUTABLE. That branch carries 3
    corpus checks ("command plus set-quantified claim"), so it is deliberate — but it IS
    a way for a narrow command to pass, and a human reviewer is the only backstop.
  - PROSE is reported, never failed. 7 corpus checks are set-quantified claims that
    simply aren't executable yet; failing them would retro-fail existing plans.
  - Classification is syntactic. It cannot know that a directory argument happens to
    hold one file, nor read a script to see what it really asserts.
  - NOT MEASURED OVER THE FROZEN CORPUS — this one bullet is a MANUAL read (no script,
    so nothing re-runs it) of the 23 INSTANCE-SHAPED checks found across 12 plans of a
    corpus of 44 real plans (one project's plans folder) kept outside this repo,
    kept because the qualitative point holds and nothing in the
    repo reproduces it. Roughly a quarter were set-valued claims narrowed to one member
    (the harmful form); about a third were live/manual judgment checks lacking the
    `(judgment)` marker, wanting the marker rather than a sweep; the rest were
    single-file facts where one file really is the whole set. All are non-compliant with
    the rule as written, but the class name oversells how many are dangerous. Treat the
    proportions as an unpinned observation, not a figure you can re-derive from here.
  - A nested `- [ ]` sub-item under a gate bullet counts as its own top-level check.
    No real plan does this today; a sub-checklist would be double-counted.
  - An extension-less path (`plugins/foo`) is read as a directory, because syntax cannot
    distinguish it from an extension-less file. A check inspecting one such file reads
    EXECUTABLE.
  - `INLINE_SCRIPT`'s quote matching is not escape-aware, so an interpreter payload
    containing an escaped copy of its own delimiter truncates early.
  - SELECTOR-UNMATCHED has one known false-positive shape, measured: a gate selector
    satisfied by tests that **already exist** in the tree — written by an earlier sub-plan,
    or predating the plan entirely — reads as unmatched, because the cross-reference is
    against the plan's own task `Test:` fields and nothing else. Measured on 5 flagged
    checks (one owner's plans, undated): 2 collected
    (1 and 2 tests) when probed, while the other 3 collected zero and were real. This is why
    `executing-plans` pairs the static check with a `pytest --collect-only` probe at
    Preflight, where the tree is real: the static half runs at authoring, when the tests
    usually do not exist yet and only the plan can vouch for them; the runtime half settles
    it. **A flagged selector that collects is not a defect** — record the collection count
    and proceed. Narrowing the static check to avoid this would cost the true positives,
    since at authoring time "no test yet" and "no test ever" look identical.
  - SELECTOR-UNMATCHED is SKIPPED entirely on a master plan. A master carries no tasks by
    construction, so it has no `Test:` fields and every selector in its cross-plan gates
    would flag. Its gates legitimately name tests its sub-plans build, in documents this
    script does not see when handed the master alone; the sub-plan that owns the task is
    where the check runs against a real corpus. Master detection reuses lib/plan_parser.py's
    two signals (filename suffix, `# Master Plan:` heading) so the two cannot drift.
  - The `Scope:`-advisory (`unswept_scopes`) is REPORTED, never failed, and only for
    stages that declare the field — so a plan without it classifies identically. It
    accepts either sanctioned shape (a sweep or a `(judgment)` marker) as covering the
    declared set; it cannot tell whether the sweep actually covers the set the `Scope:`
    names, only that the stage has one.

Usage:
    validate-gate-checks.py <plan.md> [<plan.md> ...]
    validate-gate-checks.py --quiet <plan.md>     # counts + failures only
"""
import argparse
import pathlib
import re
import shlex
import sys

# INVOKERS run a program whose scope is genuinely opaque: `pytest tests/one_test.py`
# may assert over a thousand files, so second-guessing it is not this script's job.
INVOKERS = (
    "python3", "python", "bash", "sh ", "pytest", "make ", "npm ", "cargo ",
    "podman", "docker", "gradlew", "node ",
)
# INSPECTORS read exactly the paths they are given, so their scope IS the check's
# scope. `git`, `sed`, `jq`, `awk`, `cat`, `head`, `tail`, `adb` and `curl` belong here,
# not above: `git grep -q x -- one.md` and `sed -n 1,5p one.md` inspect one file, and
# treating them as opaque runners would let them launder the exact shape SKILL.md calls
# "ALSO BAD".
INSPECTORS = (
    "grep", "rg ", "ls ", "find ", "diff ", "git ", "sed ", "jq ",
    "cat ", "head ", "tail ", "adb ", "curl", "wc ",
)
# `for` and `awk` are ordinary English substrings ("wait for confirmation",
# "awkward phrasing"), so they only count as commands at the start of the span.
LEADING_ONLY = re.compile(r"^\s*(for|awk|while|if|test)\b")
RUNNERS = INVOKERS + INSPECTORS

# An inline-script flag turns an invoker into an inspector wearing its coat:
# `bash -c "grep -q x one.md"` is perfectly readable off the command line, so its
# scope must be judged from the payload rather than waved through.
#
# The interpreter must be named: `-c` is also grep's --count flag, and matching it
# bare would make `grep -c 'x' a.md b.md c.md` recurse into 'x' and stop being a sweep.
INLINE_SCRIPT = re.compile(
    r"\b(?:bash|sh|zsh|python3?|perl|ruby|node)\s+(?:-\w+\s+)*-c\s+(['\"])(.*?)\1", re.S)
SHELL_OPS = ("&&", "||", " | ", "$(", ">/dev/null", "; ")

# Language that shows the claim is quantified over a set rather than one artifact.
# "no" must be a quantifier over a noun ("no file", "no plugin") — NOT the negation
# in "no longer" / "no more"; reading that negation as a quantifier lets the canonical
# BAD example ("the README no longer claims X") pass as PROSE through a gate it should fail.
SET_WORDS = re.compile(
    r"\bno (?!longer\b|more\b)\w"
    r"|\b(none|every|all|each|any|zero|both|neither|across|everywhere)\b"
    r"|\bper-\w", re.I)

# A concrete artifact: a path or filename carrying a known extension, or a path
# ending in a directory separator. Deliberately narrow, and it must NOT match a bare
# slash in prose — measured over 357 gate checks from one owner's plans (undated), a bare slash alone matches only
# false positives: "pass/fail", "4/4", "skill/agent" and "scan/rollup".
EXT = r"(?:md|py|sh|ya?ml|json|toml|kts?|gradle|txt|mjs|js|ts)"
ARTIFACT = re.compile(rf"[\w.\-]+(?:/[\w.\-]+)*\.{EXT}\b|[\w.\-]+/(?=\s|$|`)")

# "the README", "the manifest" — a definite article plus a file-ish noun is an
# artifact reference even without an extension.
DEFINITE_ARTIFACT = re.compile(
    r"\bthe (README|manifest|changelog|compose file|plugin\.json|marketplace entry|"
    r"SKILL\.md|workflow|index)\b", re.I)

# The heading must START with an optional "Stage N" and then "Gate", matching the
# documented contract. A looser `\bGate\b` anywhere would also match task headings such as
# "### Task 1.1: Gate `podman compose build` on image presence", which would vacuum
# unrelated task checklist items in as gate checks.
GATE_HEADING = re.compile(r"^#{2,4}\s+(?:Stage\s+\d+\s+)?Gates?\b[^\n]*$", re.M)
# Master plans carry their cross-plan checks under a `**Gate:**` bold marker rather than a
# heading — a deliberate second form, documented in master-plan-format.md, because a master
# is parser-safe by construction. Recognising only the heading would leave every master
# plan's gate checks structurally invisible.
GATE_MARKER = re.compile(r"^\s*\*\*Gates?:?\*\*\s*$", re.M)
ANY_GATE_START = re.compile(
    r"^(?:#{2,4}\s+(?:Stage\s+\d+\s+)?Gates?\b[^\n]*|\s*\*\*Gates?:?\*\*\s*)$", re.M)
# `~` included: a `- [~]` BLOCKED gate check is a gate check like any
# other and must be classified, not silently dropped. Omitting it would make this a
# consumer of the gate-checkbox contract that reads only two of its three
# states — invisible, because an unmatched line is simply not extracted.
BULLET = re.compile(r"^(\s*)- \[[ xX~]\] (.*)$")
NEXT_HEADING = re.compile(r"^#{2,4} ", re.M)


def backticked(text):
    return re.findall(r"`([^`]+)`", text)


SCRIPT_ONLY = re.compile(r"^[\w./\-]+\.(?:py|sh)$")


def is_command(span):
    s = span.strip()
    if any(op in s for op in SHELL_OPS):
        return True
    if s.startswith("!"):
        return True
    if any(r in s for r in RUNNERS) or LEADING_ONLY.match(s):
        return True
    # A script path, with or without arguments. Bare `validate-stack-routing.py` in a
    # gate check means "run it" — measured on the real corpus, requiring an explicit
    # `python3` prefix mis-flags every check that names its script that way.
    return bool(SCRIPT_ONLY.match(s) or re.match(r"[\w./\-]+\.(?:py|sh)\s+\S", s))


def command_sweeps_a_set(span):
    """True when the command's scope is plural, or opaque because it runs a program.

    An INVOKER always qualifies: `python3 tests/test-foo.py` names one path but the
    suite behind it may assert over any number of things, and second-guessing that
    is not this script's job. Only an INSPECTOR — grep, ls, find, test, diff — has a
    scope we can read off the command line, so only those must show plurality.
    """
    s = span.strip()

    # Scope signals that don't depend on trusting an invoker.
    def scoped_plural(text):
        if any(t in text for t in ("-r", "--recursive", "*", "?", "$(")):
            return True
        # A pipe only proves plurality if the SOURCE side is plural. `cat one.md | bash
        # -c "grep -q x one.md"` is a single-file inspection wearing a pipeline, and
        # accepting the bare "|" character would reopen the loophole from the other end.
        if "|" in text:
            head = text.split("|", 1)[0]
            if any(t in head for t in INVOKERS) or SCRIPT_ONLY.match(head.strip()):
                return True
            if any(t in head for t in ("-r", "--recursive", "*", "?", "$(")):
                return True
            if re.search(r"\s[\w.\-]+/[\w\-]*(\s|$)", head):
                return True
            if len(set(re.findall(rf"[\w./\-]+\.{EXT}\b", head))) > 1:
                return True
        if LEADING_ONLY.match(text.strip()):
            return True
        # A directory argument, with or without a trailing slash. `plugins/foo` is
        # ambiguous between a dir and an extension-less file and syntax cannot tell;
        # treating it as a dir keeps `ls plugins/foo | wc -l` correctly EXECUTABLE, at
        # the cost of the ambiguous-file case (disclosed in the limits above).
        if re.search(r"\s[\w.\-]+/[\w\-]*(\s|$)", text):
            return True
        return len(set(re.findall(rf"[\w./\-]+\.{EXT}\b", text))) > 1

    # An inline script (`bash -c "…"`, `python3 -c "…"`) must not let an invoker launder
    # a narrow inspector. But it must not veto a command that is plural for its OWN
    # reasons either — a pipeline containing `python3 -c` still sweeps whatever the
    # pipeline reads, and treating the payload as the whole story wrongly flags it.
    inline = INLINE_SCRIPT.search(s)
    if inline:
        return scoped_plural(inline.group(2)) or scoped_plural(s)

    if any(t in s for t in INVOKERS) or SCRIPT_ONLY.match(s):
        return True
    return scoped_plural(s)


def names_artifact(text):
    stripped = re.sub(r"`[^`]*`", " ", text)          # names inside backticks too
    return bool(ARTIFACT.search(text) or DEFINITE_ARTIFACT.search(stripped)
                or DEFINITE_ARTIFACT.search(text))


def classify(check):
    """-> (class, reason)"""
    if re.search(r"\(judgment\)", check, re.I):
        return "JUDGMENT", "explicitly marked for a reader"
    if re.search(r"\(scoped\)", check, re.I):
        # The third sanctioned shape: a single-file fact where one file really is the
        # whole set. Without it, an author writing the correct narrow check is told to
        # widen it. Widening a claim past the set it is over does not make it stricter, it
        # makes it unpassable: suppose a check sweeps many projects' records for a backlog
        # ID that is unique only within one project's register — it matches unrelated
        # entries and can never go green whatever the plan does.
        #
        # A marker rather than a cleverer classifier, because the judgment is not syntactic.
        # No amount of reading `grep -l X one/file.md` reveals whether that file is the whole
        # set; only the author knows. So the author asserts it, in the check, where a reviewer
        # can see the sentence and disagree with it — the same bargain `(judgment)` makes.
        return "SCOPED", "author asserts one artifact is the whole set"

    cmds = [s for s in backticked(check) if is_command(s)]
    if cmds:
        # A command plus a SEPARATE prose claim about a different artifact is the same
        # defect arriving by conjunction: the command cannot fail on the prose half, so
        # that half is unverified and rides along on an unrelated green.
        prose = re.sub(r"`[^`]*`", " ", check)
        prose_arts = set(ARTIFACT.findall(prose)) | set(
            m.group(0) for m in DEFINITE_ARTIFACT.finditer(prose))
        cmd_text = " ".join(cmds)
        uncovered = {a for a in prose_arts if a.strip("`") not in cmd_text}
        if uncovered and not SET_WORDS.search(prose):
            return ("INSTANCE-SHAPED",
                    f"command does not cover the artifact claimed in prose "
                    f"({sorted(uncovered)[0]}) — split the check or mark it (judgment)")
        if any(command_sweeps_a_set(c) for c in cmds):
            return "EXECUTABLE", "command sweeps a set"
        if SET_WORDS.search(re.sub(r"`[^`]*`", " ", check)):
            # e.g. "`python3 suite.py` and all five guards green" — the command is
            # narrow but the claim is explicitly plural and command-backed.
            return "EXECUTABLE", "command plus set-quantified claim"
        if names_artifact(check):
            return ("INSTANCE-SHAPED",
                    "command inspects a single literal path — scope it to the set")
        return "EXECUTABLE", "command, no single-artifact claim"

    if names_artifact(check):
        if SET_WORDS.search(re.sub(r"`[^`]*`", " ", check)):
            return "PROSE", "quantified over a set but not executable — write the sweep"
        return ("INSTANCE-SHAPED",
                "names one artifact with no sweep and no (judgment) marker")

    return "PROSE", "no artifact named; not executable"


def _is_continuation(accumulated, line):
    """Is `line` a wrap of the check so far, rather than new content beneath it?

    Joining too eagerly is its own bug: an indented explanatory paragraph or a fenced
    code block under a bullet would be glued onto the check and change its class. The
    discriminator is an *unterminated* command: a check whose backticks are still open
    is mid-command, so the next line is its wrap. Beyond that, accept a
    trailing shell/prose continuation operator, or a fragment that does not begin like
    a new sentence.
    """
    if not line.strip() or not re.match(r"^\s+\S", line):
        return False
    stripped = line.strip()
    if stripped.startswith(("```", "~~~", "- ", "* ", "+ ", "> ", "#", "|")):
        return False
    if accumulated.count("`") % 2 == 1:            # mid-command, definitely a wrap
        return True
    if accumulated.rstrip().endswith(("&&", "||", "|", "\\", ",", ":", "(")):
        return True
    # a fragment continues; a new sentence or a labelled note does not
    return bool(re.match(r"[a-z`'\"/.\-]", stripped)) and not re.match(
        r"(Note|NOTE|TODO|Why|See|Rationale|Evidence)\b", stripped)


# `*(amended … — was: …)*` — the annotation preflight-checks.md § Amending authored
# ceremony REQUIRES on an amended check: it cites the rule (naming a reference file) and
# keeps the was-value (often the old command). Neither is the check; read as the check,
# they would make every properly amended sweep INSTANCE-SHAPED. A backticked span
# is consumed whole, so a `)*` inside the was-value's command (a regex quantifier) cannot
# close the note early and splice its remainder onto the check.
AMENDMENT = re.compile(r"\s*\*\(amended\b(?:`[^`]*`|[^`])*?\)\*", re.I | re.S)


def gate_checks(text):
    """Extract gate checks, joining wrapped continuation lines.

    A long check routinely wraps onto an indented continuation line, and reading only
    the first line silently changes the verdict in BOTH directions: an unterminated
    backtick hides a real command (a valid check flagged), and a path that lives on the
    second line hides a real single-artifact claim (an invalid check missed).
    """
    out = []
    for m in ANY_GATE_START.finditer(text):
        seg = text[m.end():]
        # A block ends at the next heading or the next gate marker, whichever comes first.
        ends = [x.start() for x in (NEXT_HEADING.search(seg), GATE_MARKER.search(seg)) if x]
        if ends:
            seg = seg[:min(ends)]
        current = None
        for line in seg.splitlines():
            b = BULLET.match(line)
            if b:
                if current:
                    out.append(current)
                current = b.group(2).strip()
            elif current is not None:
                if _is_continuation(current, line):
                    current += " " + line.strip()
                else:
                    out.append(current)
                    current = None
        if current:
            out.append(current)
    return [AMENDMENT.sub("", c).strip() for c in out]


SCOPE_FIELD = re.compile(r"^\s*[-*]\s+\*\*Scope:\*\*\s*(.+)$", re.MULTILINE)

TEST_FIELD = re.compile(r"^\s*[-*]\s+\*\*Test:\*\*\s*(.+)$", re.MULTILINE)
# `pytest <path> -k <expr>` in either order, inside a backticked command. The path must
# carry an extension: a bare directory with -k is a legitimate wide sweep, not a selector.
#
# The body stops at the NEXT `pytest`, so a chained command keeps each invocation's path
# with its own filter. A greedy body reads `pytest a.py -k foo && pytest b.py -k bar` as one
# invocation owning both paths, and then pairs b.py with foo — a false positive on a gate
# whose every invocation is correctly task-declared.
PYTEST_SELECTOR = re.compile(r"pytest\b(?P<body>(?:(?!pytest\b)[^`])*)")
# A positional test-file argument only. `(?<![=\w/.-])` is what keeps a flag VALUE out:
# `--cov=src/mod.py` names a module being measured, not a test file being selected, and
# flagging it invents an unmatched selector on a gate that runs exactly what a task declared.
SELECTOR_PATH = re.compile(r"(?<![=\w/.-])([\w./-]+\.py)\b")
SELECTOR_FILTER = re.compile(r"-k\s+(?P<q>['\"]?)(?P<expr>[^'\"`]+?)(?P=q)(?=\s|$)")


def pytest_selectors(text):
    """-> [(path, k-expression)] for every filter-narrowed pytest invocation in `text`.

    A bare `pytest tests/foo.py` is deliberately NOT a selector: running an existing file
    as a regression sweep is legitimate, and syntax cannot tell it from the defect. Only
    the `-k`-narrowed form is checkable, and it is also the form an unpassable selector
    gate takes.
    """
    found = []
    for span in backticked(text):
        for m in PYTEST_SELECTOR.finditer(span):
            body = m.group("body")
            kf = SELECTOR_FILTER.search(body)
            if not kf:
                continue
            for p in SELECTOR_PATH.findall(body):
                found.append((p, kf.group("expr").strip()))
    return found


# The same cross-reference for the two other runners gates commonly use. `cargo test
# <filter>` (or `cargo nextest run <filter>`): the first positional argument, after flags and
# their values, before `--`. Gradle: the value of `--tests` / `--tests=`.
CARGO_SELECTOR = re.compile(r"\bcargo\s+(?:nextest\s+run|test)\b"
                            r"(?P<body>(?:(?!\bcargo\b|&&|\|\||;)[^`])*)")
GRADLE_SELECTOR = re.compile(r"--tests(?:=|\s+)(?P<q>['\"]?)(?P<pat>[^'\"`\s]+)(?P=q)")
# cargo flags that take a value, so the token after them is not the filter.
CARGO_VALUE_FLAGS = {"-p", "--package", "--test", "--bin", "--example", "--bench",
                     "--features", "-F", "--manifest-path", "--target", "-j", "--jobs",
                     "--profile", "--color", "--message-format", "--target-dir", "-Z",
                     "--config", "--exclude"}


def runner_selectors(text):
    """-> [(runner, filter)] for every Gradle `--tests` and filtered `cargo test` in `text`.

    A cargo run with no filter is not a selector, for the same reason a bare pytest file run
    is not: a whole-suite run is a legitimate regression sweep."""
    found = []
    for span in backticked(text):
        for m in CARGO_SELECTOR.finditer(span):
            body = re.split(r"\s--(?:\s|$)", m.group("body"), maxsplit=1)[0]
            skip = False
            for tok in body.split():
                if skip:
                    skip = False
                    continue
                if tok in CARGO_VALUE_FLAGS:
                    skip = True
                    continue
                if tok.startswith("-"):
                    continue
                if re.fullmatch(r"[\w:.*-]+", tok):
                    found.append(("cargo", tok))
                break
        # cargo has its own `--tests` flag (all test targets), so a span that runs cargo is
        # never read as Gradle. A Gradle span need not name gradlew: `:data:test --tests X`.
        if not re.search(r"\bcargo\b", span):
            for m in GRADLE_SELECTOR.finditer(span):
                if not m.group("pat").startswith("-"):
                    found.append(("gradle", m.group("pat")))
    return found


def unmatched_runner_selectors(text, path=None):
    """-> [(check, runner, filter)] Gradle/cargo gate selectors no task `Test:` declares.

    ADVISORY — reported, never failed. Measured over a real plan corpus (see the module
    docstring): the flagged set includes a test that already exists outside its plan, the
    same false-positive shape the pytest form documents, so its hits are not all true
    defects (gate-authoring.md § A gate heuristic ships with a severity axis and a measured
    trigger rate). Same exemptions as the pytest form: a master plan, `(judgment)`,
    `(scoped)`."""
    if is_master_plan(text, path):
        return []
    declared = set()
    for m in TEST_FIELD.finditer(text):
        declared.update(runner_selectors(m.group(1)))
    out = []
    for c in gate_checks(text):
        if re.search(r"\((judgment|scoped)\)", c, re.I):
            continue
        for sel in runner_selectors(c):
            if sel not in declared:
                out.append((c, *sel))
    return out


MASTER_HEADING = re.compile(r"^#\s+Master Plan:", re.MULTILINE)


def is_master_plan(text, path=None):
    """Whether this document is a master plan (a register of sub-plans).

    Same two signals `lib/plan_parser.py` uses — the filename suffix and the heading —
    deliberately, so the two do not drift into disagreeing about what a master is.
    """
    if path is not None and str(path).endswith("-master-plan.md"):
        return True
    return bool(MASTER_HEADING.search(text))


def unmatched_selectors(text, path=None):
    """-> [(check, path, k-expr)] gate selectors no task in this plan builds toward.

    The defect: a gate check names a real test file and a `-k` filter that collects zero
    tests, so the gate cannot pass as authored and nobody learns that until execution. A
    typical case: a gate names an e2e file with a filter matching nothing in it.

    Why a cross-reference rather than running pytest: at authoring time the selected tests
    usually do not exist yet — the plan's own tasks create them. So the checkable invariant
    is not "does this collect now" but "does any task in this plan declare it". A gate
    selector no task builds toward is either a typo or a check pointed at the wrong file,
    and both are unpassable. `executing-plans` runs the runtime half at Preflight, where
    the tests DO exist (`pytest --collect-only`), and the two together cover the class.

    Orthogonal to the shape classes: a selector-unmatched check is usually a perfectly
    well-shaped EXECUTABLE sweep. It is reported and failed separately for that reason, and
    kept out of the shape totals so the calibration corpus figures stay comparable.

    A `(judgment)` or `(scoped)` marker exempts the check, on the same bargain as
    elsewhere: the author is asserting something syntax cannot see, where a reviewer can
    disagree with it.
    """
    # A MASTER plan carries no tasks by construction (master-plan-format.md), so it has no
    # `Test:` fields to cross-reference and EVERY selector in its cross-plan gates would flag.
    # Its gates legitimately name tests its SUB-plans build, and those are separate documents
    # this function cannot see. Skipping is therefore the correct answer, not a concession:
    # the sub-plan that owns the task is where the same check runs with a real corpus.
    if is_master_plan(text, path):
        return []

    declared = set()
    for m in TEST_FIELD.finditer(text):
        for pair in pytest_selectors(m.group(1)):
            declared.add(pair)
    declared_paths = {p for p, _ in declared}

    out = []
    for c in gate_checks(text):
        if re.search(r"\((judgment|scoped)\)", c, re.I):
            continue
        for path, expr in pytest_selectors(c):
            if (path, expr) in declared:
                continue
            # A task declares the file but a different filter: still unmatched, and worth
            # naming distinctly — this is the typo case rather than the wrong-file case.
            why = ("no task declares this file at all" if path not in declared_paths
                   else f"a task declares {path} but with a different -k filter")
            out.append((c, path, expr, why))
    return out


def unswept_scopes(text):
    """Stage numbers whose tasks declare a `Scope:` but whose gate sweeps nothing.

    `Scope:` names the set at authoring time; the gate check is what proves the set was
    swept. Declaring one without the other is the failure the field exists to prevent,
    dressed up as compliance — the author enumerated the class and then verified one
    member of it.

    Reported, never failed, and ONLY for stages that declare the field. A plan with no
    `Scope:` anywhere is classified exactly as if the field did not exist, so every
    plan without the field reports identically — the same
    advisory-on-existing-plans asymmetry `executing-plans` applies to INSTANCE-SHAPED, and for
    the same reason: a check executors learn to route around protects nothing.
    """
    out = []
    stages = re.split(r"\n(?=## Stage )", text)
    for seg in stages:
        m = re.match(r"## Stage (\S+)", seg)
        if not m:
            continue
        if not SCOPE_FIELD.search(seg):
            continue
        checks = gate_checks(seg)
        if not checks:
            continue
        # EXECUTABLE **or** JUDGMENT. The class-predicate rule sanctions exactly two
        # shapes for a set-valued check — the sweep, or the `(judgment)` marker for a
        # claim a reader must genuinely verify. Accepting only the first would make this
        # advisory contradict the rule it exists to support, flagging a stage that
        # covers its Scope: the sanctioned second way. An advisory that is wrong on
        # its own stated criteria teaches authors to route around it.
        if not any(classify(c)[0] in ("EXECUTABLE", "JUDGMENT", "SCOPED") for c in checks):
            out.append(m.group(1).rstrip(":"))
    return out


# --- PROSE-BLIND-SWEEP -------------------------------------------------------------
#
# A FOURTH axis, and the same kind of thing as SELECTOR-UNMATCHED: not "is this check
# well shaped" but "can this check ever go green". A negated recursive grep over a
# source tree asserts that a string appears NOWHERE in it — and grep cannot tell a
# string the code *sends* from a paragraph *about* that string. So the check fails the
# moment somebody documents the thing being forbidden, which is precisely when the
# codebase is behaving well. The property is real; the instrument cannot measure it.
#
# Measured over one owner's plans (undated): four checks of this shape, every one of them failed on prose and none on a
# defect. Suppose `! grep -rn '"git"' src/app/` guards against a hard-coded dependency:
# it matches a docstring explaining a prompt, a comment explaining a layout choice, and
# the dependency list `REQUIRED = ("git", "make")` itself. The repair this rule points at
# is an architecture test that reads VALUES rather than text, excludes docstrings, is
# mutation-checked, and runs on every commit rather than on the day somebody runs the plan.
#
# Deliberately narrow, because the shape is not always doomed. Three conditions, all
# required, each one needed:
#
#   NEGATED       `! grep …`. A positive grep asserting presence is a different and
#                 weaker problem (prose can satisfy it spuriously); only the absence
#                 assertion is *unpassable*, which is what this axis is for.
#   RECURSIVE     `-r`/`-R`, or a directory target. The frozen corpus's one negated
#                 grep reads a single `.md` file, which is a scoped fact about one
#                 artifact and stays green; flagging it would be wrong.
#   PROSE-ABLE    at least one alternative in the pattern is bare words — no regex or
#                 code structure. `ALLOWED = frozenset` carries an `=` and is
#                 left alone; `^## BL-02[0-7] ` carries an anchor and a class and is
#                 left alone. `flush-cache`, `"git"`, `Try again` and `Disk
#                 full` are all bare words and are all flagged.
#
# A pipeline that already excludes comments is exempt — that author solved the problem
# rather than walking into it. Excluding a *directory* is not excluding comments: a check
# carrying `| grep -v '<dir>/'` still matches every comment and docstring outside <dir>.
#
# `(judgment)` and `(scoped)` are exempt, for consistency with SELECTOR-UNMATCHED
# rather than because the grep would work: a marked check is already routed to a human.
# None of the four measured checks carries a marker, so the exemption costs nothing
# that has been measured.

# A `grep -v` whose own pattern is comment syntax: the author is already stripping prose.
_COMMENT_FILTER = re.compile(r"grep\s+-\w*v\w*\s+(['\"])[^'\"]*(?:#|//|\\\*|\"\"\")")

_SWEEP = re.compile(
    r"(?P<tool>grep|rg)\b(?P<flags>(?:\s+-{1,2}[\w-]+)*)\s+(?P<q>['\"])(?P<pat>.*?)(?P=q)")

# Regex metacharacters and code punctuation. Either one means the pattern is anchored to
# syntax rather than to words, and a comment is unlikely to reproduce it by accident.
_STRUCTURE = re.compile(r"[=(){}\[\];:<>^$*+?\\]")
# What is left must read as language: words, digits, spaces and the punctuation that
# shows up inside a user-facing string or a hyphenated command verb.
_WORDS = re.compile(r"[\w\s,.'\u2019\"\-\u2014\u2026!?]+")


def _prose_able(alternative):
    """Is this pattern alternative bare words that a comment could easily contain?"""
    alt = alternative.strip()
    if not alt:
        return False
    if _STRUCTURE.search(alt):
        return False
    return bool(_WORDS.fullmatch(alt))


def prose_blind_sweeps(text):
    """-> [(check, command, the prose-able alternative)] for unpassable absence greps."""
    out = []
    for check in gate_checks(text):
        if re.search(r"\(judgment\)|\(scoped\)", check, re.I):
            continue
        for span in backticked(check):
            cmd = span.strip()
            if not cmd.startswith("!"):
                continue
            m = _SWEEP.search(cmd)
            if not m:
                continue
            # `rg` recurses by default; `grep` must be told to. Asked of the tool rather
            # than guessed from the target, because a path containing a slash is not a
            # directory — `src/one.py` is one file, and reading it as a tree would make
            # this rule flag a scoped single-artifact check.
            flags = m.group("flags") or ""
            if m.group("tool") != "rg" and not re.search(r"-\w*[rR]", flags):
                continue
            if _COMMENT_FILTER.search(cmd):
                continue
            # BRE `\|` and ERE `|` both separate alternatives; one bare-word alternative
            # is enough to doom the check, so the first is reported rather than all.
            hits = [a for a in re.split(r"\\\||\|", m.group("pat")) if _prose_able(a)]
            if hits:
                out.append((check, cmd, hits[0].strip()))
                break
    return out


# --- TASK-TEST-UNSCOPED ------------------------------------------------------------
#
# A THIRD axis, separate from shape and from selector-matchability: not "is this gate
# check well formed" but "can this task's own test command finish". Measured over one owner's plans
# (undated): one
# task `Test:`, a marker deselector with no path, ran ~3.5 h against a 3132-test
# collection inside one Red-Green loop, while the declared stage-scope command took
# ~7 min. Nothing in the tier policy can detect
# it — the tiers govern GATES, `fix-scope` is derived per fix, and a task field is the one
# place with no upstream check.
#
# Armed ONLY by a plan that declares stage-scope AND plan-scope commands — i.e. a project
# over guard rail 1's ~5 min threshold. Below it there is nothing to bound, and a check
# that fired anyway would be pure ceremony on a 90-second suite.

# The DECLARATION form, not the words. `- stage-scope: <command>` declares a tier;
# `- Stage-scope pass green` is a gate bullet, and arming on it would arm the whole check
# on a gate result. A checkbox line is a gate check and never a declaration, so it is excluded outright.
TIERS_STAGE = re.compile(r"^\s*(?![-*]\s*\[)[-*]?\s*`?\*{0,2}stage-scope\*{0,2}`?\s*:",
                         re.MULTILINE | re.IGNORECASE)
TIERS_PLAN = re.compile(r"^\s*(?![-*]\s*\[)[-*]?\s*`?\*{0,2}plan-scope\*{0,2}`?\s*:",
                        re.MULTILINE | re.IGNORECASE)

# The block HEADING is deliberately not the trigger. A plan may carry it to record the
# opposite conclusion, e.g. "**Test-scope commands:** not tiered — the whole suite runs
# in 40 s, far below the ~5 min threshold". Arming on the heading would
# fire hardest on the author who documented the threshold decision most carefully.
def declares_tiering(text):
    return bool(TIERS_STAGE.search(text) and TIERS_PLAN.search(text))


# --- STAGE-SCOPE-WIDE ----------------------------------------------------------------
# A test TREE or MODULE token in a command: a path with `test` in it, a gradle `:module:`
# task, or a bare `tests`/`test` directory. Counting tokens is decidable from text; cost
# is not, which is why this is a note and the ~5 min rule lives in test-scope-tiers.md.
TREE_TOKEN = re.compile(r"(?<![\w./-])(?:[\w.-]*/)?tests?(?:/[\w.-]+)*(?![\w-])|"
                        r"(?<![\w])(?:tests?_[\w]+)(?![\w-])|"
                        r"(?<![\w])(?::[\w-]+)+:[\w]+")
STAGE_SCOPE_WIDE_MIN = 4


JUSTIFIED = re.compile(r"\bjustified\s*:", re.I)


def _justified_trees(clause):
    """Trees a `justified: <tree> — <reason>; <tree> — <reason>` clause gives a reason for.
    A tree listed with an empty reason is not justified."""
    out = set()
    for item in clause.split(";"):
        parts = re.split(r"\s+(?:—|–|--?)(?:\s+|$)", item.strip(), maxsplit=1)
        if len(parts) == 2 and parts[1].strip().strip("`"):
            out.add(_tree_key(parts[0]))
    return out


def _tree_key(tree):
    """`tests/unit/`, `./tests/unit` and `tests/unit` name one tree."""
    tree = tree.strip().strip("`").strip()
    return (tree[2:] if tree.startswith("./") else tree).rstrip("/")


def wide_stage_scopes(text, min_trees=STAGE_SCOPE_WIDE_MIN):
    """-> [(command, tree_count, unjustified)] for every `stage-scope:` declaration naming
    `min_trees` or more test trees/modules that a `justified:` clause does not cover tree by
    tree (`justified: tests/a — Stage 1 edits it; tests/b — Stage 2 imports it`).
    `unjustified` names the trees with no reason. Reads the declaration line plus any
    wrapped continuation lines (indented, not a new bullet). Advisory only — see the
    module docstring for the measurement."""
    out = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not TIERS_STAGE.match(line):
            continue
        cmd = line.split(":", 1)[1]
        j = i + 1
        while j < len(lines) and lines[j].strip() and re.match(r"\s{2,}", lines[j]) \
                and not re.match(r"\s*[-*]\s", lines[j]):
            cmd += " " + lines[j]
            j += 1
        jm = JUSTIFIED.search(cmd)
        command, clause = (cmd[:jm.start()], cmd[jm.end():]) if jm else (cmd, "")
        trees = set(t for t in TREE_TOKEN.findall(command))
        if len(trees) < min_trees:
            continue
        missing = sorted(t for t in trees if _tree_key(t) not in _justified_trees(clause))
        if missing:
            out.append((command.strip().strip("`").strip(), len(trees), ", ".join(missing)))
    return out


# --- GOAL-CHECK-MISSING --------------------------------------------------------------
# A FIFTH axis, orthogonal to shape: not "is this check well formed" but "does any check
# test what the plan is FOR". `(goal)` marks the check that sweeps the plan's goal over the
# whole artifact it is about; it is classified like any other check, so an instance-shaped
# goal check is still INSTANCE-SHAPED. See the module docstring for the reason and rate.
GOAL_MARKER = re.compile(r"\(goal\)", re.I)
SUB_PLAN_HEADING = re.compile(r"^###\s+Sub-plan\s+(\S+?):?\s", re.MULTILINE)


def goal_check_missing(text, path=None):
    """-> ["plan"] for a plan with no `(goal)` check in any gate, or the `Sub-plan N` label of
    every master register entry whose `**Gate:**` block has none. A plan with no gate checks
    at all is left to the existing 0-checks note rather than reported twice, and a master
    entry with no gate checks at all is likewise not reported (measured 2026-10-08 over
    230 master register entries in one owner's records homes: 7 have none): the authoring checklist's "every register entry ends with a `**Gate:**` block"
    item owns that, and no script checks it."""
    if is_master_plan(text, path):
        heads = list(SUB_PLAN_HEADING.finditer(text))
        out = []
        for i, m in enumerate(heads):
            # An entry ends at the next entry or the next `#`/`##` heading — a master-level
            # gate after the register must not lend the last entry its `(goal)` check.
            nxt = re.compile(r"^#{1,2}\s", re.M).search(text, m.end())
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            if nxt and nxt.start() < end:
                end = nxt.start()
            seg = text[m.start(): end]
            checks = gate_checks(seg)
            if checks and not any(GOAL_MARKER.search(c) for c in checks):
                out.append(f"Sub-plan {m.group(1).rstrip(':')}")
        return out
    checks = gate_checks(text)
    if checks and not any(GOAL_MARKER.search(c) for c in checks):
        return ["plan"]
    return []


# --- FILTERED-SUBSET -----------------------------------------------------------------
# A SIXTH axis, read only on EXECUTABLE checks: the sweep is plural, but restricted to a
# category of the set. Nothing is wrong with a filter as such; what is missing is the
# author's statement of why the excluded members need no check. `(scoped)` is that statement.
# An awk FIELD match (`$4 ~ /public/`, `$2 == "x"`). `$0` is the whole row, which is a grep, not
# a category, so the field number starts at 1.
AWK_FIELD_FILTER = re.compile(r"\$[1-9]\d*\s*(?:!~|~|==|!=)\s*(?:/[^/]*/|\"[^\"]*\"|'[^']*'|\S+)")
# Commands whose output IS the set: a filter after one of these narrows the set itself.
# Matched at the head of a stage's source (`_stage_source`), never anywhere in it.
ENUMERATOR = re.compile(
    r"^(?:ls|find|fd|rg\s+--files|"
    r"git(?:\s+-C\s+\S+)?\s+(?:ls-files|ls-tree|diff\b[^|]*--name-only))\b")
# Stages that pass the enumerated rows through as rows. Any other stage (`xargs grep -c`,
# `while read`, `diff`) turns the set into something else, and a grep after it filters
# results, not members — measured: those stages are where the false positives come from.
ROW_PRESERVING = re.compile(r"(?:sed|sort|uniq|cut|tr|awk|grep)\b")
# A pattern of anchors and wildcards only (`grep .`, `grep -v '^$'`) drops blank lines; it
# names no category.
TRIVIAL_PATTERN = re.compile(r"""^['"]?(?:\.|\^|\$|\s|\.\*)*['"]?$""")


# Stages that only count or order what reaches them. A positive grep followed by these alone
# is still the check's predicate.
COUNTING = re.compile(r"(?:wc|head|sort|uniq)\b")


def _pipe_stages(span):
    """Split a command at single `|` outside quotes — `grep -E 'a|b'` is one stage. A double
    quote opening `"$(… | …)"` is not quoting: those pipes are real, so the span is read
    through to its matching `)` (`sed "s|a||"` inside it still protects its own `|`)."""
    stages, cur, quote = [], "", None
    read_through = set()       # closing quotes of `"$(…)"` spans, which open nothing
    i = 0
    while i < len(span):
        ch = span[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch == "'":
            quote = ch
        elif ch == '"' and i not in read_through:
            if span.startswith("$(", i + 1):
                # Read through to the `)` matching this `$(` (single-quoted text skipped);
                # the `"` after it closes the span and opens nothing.
                depth, j = 0, i + 1
                while j < len(span):
                    c = span[j]
                    if c == "'":
                        k = span.find("'", j + 1)
                        j = k if k != -1 else len(span)
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                if span[j + 1: j + 2] == '"':
                    read_through.add(j + 1)
            else:
                quote = ch
        elif ch == "|":
            if span[i + 1: i + 2] == "|" or span[i - 1: i] == "|":
                cur += ch
                i += 1
                continue
            stages.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    stages.append(cur)
    return stages


def _stage_source(stage):
    """The command whose output a stage passes on. A `$(…)` closed inside the stage became
    ARGUMENTS (`grep -rn x $(git ls-files)` prints matches, not files), so it is dropped;
    an unclosed `$(`/`<(` opens a pipeline whose head is what follows it."""
    prev = None
    while prev != stage:
        prev, stage = stage, re.sub(r"[$<]\([^()]*\)", " ", stage)
    opened = list(re.finditer(r"[$<]\(", stage))
    return (stage[opened[-1].end():] if opened else stage).strip().lstrip("!(").strip()


def _grep_filter(stage):
    """-> the grep's text up to its pattern, when `stage` is a narrowing grep; else None."""
    try:
        toks = shlex.split(stage, posix=True)
    except ValueError:
        toks = stage.split()
    if not toks or toks[0] != "grep":
        return None
    flags = [t for t in toks[1:] if t.startswith("-")]
    if any(re.fullmatch(r"-\w*q\w*", f) or f == "--quiet" for f in flags):
        return None                      # an assertion over the output, not a filter
    rest = [t for t in toks[1:] if not t.startswith("-")]
    if not rest or TRIVIAL_PATTERN.match(rest[0]):
        return None
    # Shown as written, cut at the first shell terminator after the pattern.
    shown = re.split(r"\)\s*;|\)\s*$|;\s", stage.strip(), maxsplit=1)[0]
    return shown.strip()


def filtered_subsets(text):
    """-> [(check, command, filter)] for every EXECUTABLE gate check whose sweep is restricted
    by a category filter: an awk field match, or a grep narrowing the rows a command that
    enumerates the set printed (only row-preserving stages between them). `grep -q` is an
    assertion over output, not a narrowing of the set, and an anchors-only pattern names no
    category. `(scoped)` and `(judgment)` exempt. One entry per check — the first filter."""
    out = []
    for check in gate_checks(text):
        if classify(check)[0] != "EXECUTABLE":
            continue
        found = None
        for span in backticked(check):
            if not is_command(span):
                continue
            if "awk" in span:
                m = AWK_FIELD_FILTER.search(span)
                if m:
                    found = (span, m.group(0).strip())
                    break
            seen_enum = False
            stages = _pipe_stages(span)
            for i, stage in enumerate(stages):
                st = stage.strip().lstrip("(").strip()
                if seen_enum:
                    filt = _grep_filter(st)
                    # A positive grep closing the whole command is the check's predicate
                    # (`! git ls-files | grep keystore`), not a narrowing of the set; `-v`
                    # excludes members wherever it sits.
                    # Counting stages after it (`| wc -l` → "prints 0") keep it the
                    # predicate; a `)` closes a substitution whose output the outer command
                    # reads as the set, so a grep inside one narrows it.
                    tail = [re.sub(r"'[^']*'", "", x) for x in stages[i:]]
                    last = (all(COUNTING.match(x.strip()) for x in stages[i + 1:])
                            and not any(")" in x for x in tail))
                    if filt and (not last or re.search(r"(?:^|\s)-\w*v", st)):
                        found = (span, filt)
                        break
                    if not ROW_PRESERVING.match(st):
                        seen_enum = False
                if ENUMERATOR.match(_stage_source(st)):
                    seen_enum = True
            if found:
                break
        if found:
            out.append((check, *found))
    return out


TASK_HEADING = re.compile(r"^#{2,6}\s+(?:\*\*)?Task\b", re.MULTILINE)
ANY_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)

# Suite runners whose default scope is "everything". The list is FIXED and short, and
# that is a stated limit rather than an oversight: a runner absent from it is not
# checked, so this catches the shapes that have actually cost hours, not every possible
# one. Adding a runner is a one-line change with a fixture.
RUNNER = re.compile(
    r"(?:\./[\w./-]*)?(?<!\.)\b(pytest|gradlew|gradle|jest|vitest|xcodebuild)\b"
    # `npm run test` is at least as common as `npm test` in a package.json project, and
    # an adjacency requirement would make the more common shape invisible. `cargo nextest
    # run` is the default cargo runner in many projects.
    r"|\b(?:go|cargo)\s+test\b|\bcargo\s+nextest\s+run\b"
    r"|\b(?:npm|yarn|pnpm)\s+(?:run\s+)?test(?=\s|$)"
)
SEPARATOR = re.compile(r"&&|\|\||;|\|")

# Flag values are parsed, once here rather than per symptom. Dropping a token beginning with
# `-` and keeping the token after it makes a FLAG'S VALUE read as a positive path argument:
# `pytest -p no:randomly -m 'not needs_network'` would pass as scoped, and `--ignore
# tests/slow` or `--deselect tests/x.py` would pass while `--ignore=tests/slow` is caught, so
# an `=` fixture alone proves less than it looks. Parse the values, and "a positional argument
# bounds the run" becomes true for every runner instead of being approximated per runner.
VALUE_FLAGS = {
    "-k", "-m", "-p", "-t", "-n", "--tests", "--test", "--testNamePattern", "--package",
    "--deselect", "--ignore", "--run", "-run", "--project", "--testPathPattern",
    "-scheme", "-destination", "-sdk", "-configuration", "-workspace", "-project",
}
# Flags whose VALUE, when it is a real expression, bounds the run. `-p` is deliberately NOT
# here for pytest: in pytest `-p` loads a plugin and bounds nothing, while in cargo/go it
# names a package. That collision is why it is runner-gated below.
NARROWING_FLAGS = r"-k|--tests?|-t|--testNamePattern|--testPathPattern|--run|-run|--project"
EXPR_FLAG = re.compile(
    r"(?:^|\s)(?:" + NARROWING_FLAGS + r")(?:\s+|=)(?P<q>['\"]?)(?P<expr>[^'\"`]*?)(?P=q)(?=\s|$)")
# xcodebuild joins its selector with a colon, so it needs its own shape. `-skip-testing:` is
# deliberately absent: it subtracts, and subtracting from everything is still everything.
ONLY_TESTING = re.compile(r"-only-testing:\S+")
CARGO_PKG = re.compile(r"(?:^|\s)(?:-p|--package)\s+\S+")
# Cargo's TARGET selectors take no value and are real bounds: `--lib` runs only the library
# target, `--doc` only doc-tests. A value-parsing flag list alone misses them and turns
# `cargo test --lib` — 11 occurrences in one owner's plans (undated) — into a false positive; a corpus
# sweep catches that where a unit table with no `--lib` cell cannot.
CARGO_TARGET = re.compile(r"(?:^|\s)--(?:lib|bins?|doc|examples?|benches?|all-targets)\b")
INSTRUMENTATION = re.compile(r"-Pandroid\.testInstrumentationRunnerArguments\.")
# `-m <expr>` is a scope when it SELECTS and not when it DESELECTS (`-m 'not slow'`).
MARKER = re.compile(r"(?:^|\s)-m(?:\s+|=)(?P<q>['\"]?)(?P<expr>[^'\"`]+?)(?P=q)(?=\s|$)")
# Whole-tree arguments. A path naming the root is not a bound, however path-shaped.
WHOLE_TREE = {".", "./", "...", "./...", "*"}

# Gradle is the one family where the DEFAULT is bounded and the exceptions are not.
# `./gradlew apiCheck` names a specific task, and the name IS the scope; so do `detekt`,
# `jacocoTestReport`, `lintRelease`. Only the
# aggregate lifecycle tasks below collect everything. Matched by SHAPE, not by a literal
# list: the flavour/build-type matrix generates names no list can enumerate, and the
# flavour infix is OPTIONAL because bare `connectedAndroidTest` is the commonest member.
#
# Measured 2026-10-19 over the 867 files scripts/corpus-regress.py recorded (every .md in
# one owner's records-home plans folders, plus the corpus's own frozen plans; it records each
# file's task-test-unscoped count): 6
# task-test-unscoped findings in 4 plans, one of them Gradle (`./gradlew check
# assembleDebug`), so the family is read correctly rather than disarmed.
#
# The direction of error is what matters: this check is wired into a MANDATORY
# pre-presentation checklist, so a false positive blocks a correct plan from being presented,
# which is worse than a miss.
GRADLE_AGGREGATE = re.compile(
    r"\A(?:test|tests|check|build|allTests|testAll|jvmTest|cleanTest|connectedCheck|androidTest"
    r"|test(?:[A-Z]\w*)?UnitTest|connected(?:[A-Z]\w*)?AndroidTest)\Z"
)


def _split(body):
    """Shell-ish tokens, quotes respected. Falls back to whitespace on unbalanced quotes —
    a plan's `Test:` field is prose-adjacent and may not be a valid shell word list."""
    try:
        return shlex.split(body)
    except ValueError:
        return body.split()


def _positional(body):
    """Tokens that are neither flags NOR the values of flags.

    The second half is the whole point; see VALUE_FLAGS above."""
    toks = _split(body)
    out, i = [], 0
    while i < len(toks):
        tok = toks[i]
        if tok.startswith("-"):
            i += 2 if (tok in VALUE_FLAGS and "=" not in tok) else 1
            continue
        out.append(tok)
        i += 1
    return out


def _expr_narrows(expr):
    """Whether a selector expression actually bounds the collection.

    Presence of the flag is not enough — `-k ''` collects everything, and the prose rule
    this implements says a selector must bound what the command COLLECTS."""
    expr = expr.strip().strip("'\"")
    if not expr or expr in WHOLE_TREE:
        return False
    if re.match(r"not\b", expr):
        return False        # subtractive: everything minus a slice is still everything
    return True


def _bounded(runner, body):
    """Whether one runner invocation's argument list bounds what it collects."""
    body = SEPARATOR.split(body)[0]

    if "gradle" in runner:
        toks = _positional(body)
        if any(tok.startswith(":") for tok in toks):
            return True                      # a module-qualified task path
        if INSTRUMENTATION.search(body) or any(
                _expr_narrows(m.group("expr")) for m in EXPR_FLAG.finditer(body)):
            return True                      # --tests '*Foo', the instrumentation filter
        # A named task is its own scope; only the aggregates are unbounded.
        return not any(GRADLE_AGGREGATE.match(tok) for tok in toks)

    if runner.startswith("xcodebuild"):
        if "test" not in _split(body):
            return True                      # it is building, not running a suite
        return bool(ONLY_TESTING.search(body))

    if re.search(r"(?:^|\s)--no-run\b", body):
        return True                          # compiles the tests, runs none

    if runner.startswith("cargo") and (CARGO_PKG.search(body) or CARGO_TARGET.search(body)):
        # `-p` means --package for CARGO only. In go it is the parallelism count
        # (`go test -p 4 ./...` still runs everything) and in pytest it loads a plugin
        # (`pytest -p no:randomly`). Ungated, both would disarm the check.
        return True

    if any(_expr_narrows(m.group("expr")) for m in EXPR_FLAG.finditer(body)):
        return True
    if ONLY_TESTING.search(body) or INSTRUMENTATION.search(body):
        return True
    m = MARKER.search(body)
    if m and _expr_narrows(m.group("expr")):
        return True

    # Any positional argument that is not the whole tree. True for every runner because
    # flag values are parsed out, so no per-runner path heuristic is needed.
    return any(tok not in WHOLE_TREE for tok in _positional(body))


# ONE placement for the exemption: a field of its own. Honouring the token inline on the
# `Test:` line as well would make the exemption a 2x2 of placement x polarity, and the fourth
# cell is a hole: a task saying it has NOT been marked contains the marker's own words, and
# so is exempted by the sentence denying it.
# Both checklists say "with a reason", so a bare marker is not accepted — otherwise the
# rule and its checker would disagree about what the exemption costs. The reason IS the exemption:
# a token with nothing after it records that someone typed the words, not that they priced
# the run.
FULL_SUITE_FIELD = re.compile(
    r"^\s*[-*]\s*\*{0,2}full-suite:\s*accepted\*{0,2}\s*[—:-]?\s*(?P<reason>[^\s*].*)$",
    re.MULTILINE | re.I)


def _accepts_full_suite(block):
    return bool(FULL_SUITE_FIELD.search(block))


def unscoped_task_tests(text, path=None):
    """-> [(task, command, why)] task `Test:` commands that collect the whole suite.

    Only on a plan that declares tiering (`declares_tiering`), and never on a master
    plan, which carries no tasks by construction — the same skip the selector check
    makes, for the same reason.

    Two ways a task satisfies the rule (references/test-scope-tiers.md § A task-level
    `Test:` is task-scope only when the author scoped it): the command is path- or
    suite-scoped, or the task carries an explicit `full-suite: accepted`, which records
    that the author priced the full run and chose it.

    **The question this answers is deliberately narrow, and closed.** Not "is this command
    cheap" — that is open-ended, unanswerable from text, and chasing it yields fixes that
    each need fixing in turn. It answers: *does
    anything in this command narrow what it collects?* A command carrying any positive
    selector — a path, a filter, a package, a module task — is NOT JUDGED, however expensive
    it really is. What is flagged is a command that starts from everything and either adds
    nothing or only subtracts (`-m 'not x'`, `--ignore=`), because subtracting from
    everything is still everything. That is decidable from the text; cost is not.

    **Arming reaches every format, but only through a declaration.** The trigger is a
    `stage-scope:` / `plan-scope:` pair anywhere in the document. A **Light** plan has no
    Preflight section, so `references/light-plan-format.md` sanctions the declaration block
    explicitly; without it this check cannot fire on a Light plan at all, and the defect
    passes silently for the entire format. An undeclared
    plan of any format is still not checked, which is guard rail 1 working as designed.

    Known limits, stated rather than implied (honest-gates), each one left rather than
    fixed:

      * A `Test:` field is read one line at a time and only inside backticks, so a command
        on a wrapped continuation line, or one written without backticks, is never examined.
        No live corpus instance; fixing it means changing how every axis in this file reads
        a task field.
      * A tautological selector (`-k 'x or not x'`) and a root-relative path
        (`pytest tests/../`) both read as narrowing. The prose rule excludes them; the
        checker cannot see it. The rule is stricter than its checker here, which is the
        right direction but is a real divergence.
      * `cargo test --workspace` flags while a workspace really is this project's whole
        world — correct under the rule, and worth knowing before reading a finding.

    A command is judged on its
    own text, with no reference to the plan's declared tiers — so a task `Test:` that is
    verbatim the plan's own `stage-scope:` command still flags. Two of the six findings
    measured beside GRADLE_AGGREGATE are that shape (a multi-crate project whose stage-scope runs one crate's suite
    as plain `cargo test`), and
    they are correct under the rule as written: the rule asks the author to say
    `full-suite: accepted` and price it, which is exactly the sentence such a plan is
    missing. A stage-scope match is not treated as bounded: most plans declare a
    plan-scope command that IS the full suite, and the equivalence would gut the check
    on the projects it exists for. The runner list is fixed,
    so a suite runner not in `RUNNER` is not checked at all. And "bounded" is judged
    from the command's SYNTAX: `pytest tests/` is accepted as scoped even where that
    directory holds the entire suite. Both are deliberate — this check exists to catch
    the unbounded default, and a stricter reading would flag correct plans, which on a
    mandatory pre-presentation checklist blocks authoring rather than merely nagging.
    """
    if not declares_tiering(text) or is_master_plan(text, path):
        return []
    out = []
    for m in TASK_HEADING.finditer(text):
        nxt = ANY_HEADING.search(text, m.end())
        block = text[m.start(): nxt.start() if nxt else len(text)]
        label = block.splitlines()[0].lstrip("# ").strip()
        if _accepts_full_suite(block):
            continue
        flagged = False
        for tf in TEST_FIELD.finditer(block):
            for span in backticked(tf.group(1)):
                for r in RUNNER.finditer(span):
                    nr = RUNNER.search(span, r.end())
                    body = span[r.end(): nr.start() if nr else len(span)]
                    if _bounded(r.group(0), body):
                        continue
                    # The INVOCATION, not the span. A chained command is usually mostly
                    # fine and unbounded in one link; naming the span sends the author
                    # hunting through a line they have to re-derive the fault in.
                    out.append((label,
                                (r.group(0) + SEPARATOR.split(body)[0]).strip(),
                                "collects the whole suite — no path, no filter, and the "
                                "task carries no `full-suite: accepted`"))
                    flagged = True
        # No early break: a task with two unbounded commands reports both. Stopping at the
        # first is the instance-shaped habit this whole check exists to catch, inside the checker.
        _ = flagged
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="validate-gate-checks")
    ap.add_argument("plans", nargs="+", type=pathlib.Path)
    ap.add_argument("--quiet", action="store_true",
                    help="print counts and failures only")
    args = ap.parse_args(argv)

    totals = {"EXECUTABLE": 0, "JUDGMENT": 0, "SCOPED": 0, "INSTANCE-SHAPED": 0, "PROSE": 0}
    failures = []
    selector_failures = []
    task_test_failures = []
    runner_selector_notes = []
    prose_blind_failures = []
    wide_stage_notes = []
    goal_notes = []
    filtered_notes = []
    examined_files = 0
    empty_files = []
    scope_notes = []

    for path in args.plans:
        if not path.is_file():
            print(f"error: not a file: {path}", file=sys.stderr)
            return 2
        raw = path.read_text(encoding="utf-8")
        checks = gate_checks(raw)
        unswept = unswept_scopes(raw)
        if unswept:
            scope_notes.append((path, unswept))
        for c, sel_path, expr, why in unmatched_selectors(raw, path):
            selector_failures.append((path, c, sel_path, expr, why))
        for c, runner, filt in unmatched_runner_selectors(raw, path):
            runner_selector_notes.append((path, c, runner, filt))
        for task, cmd, why in unscoped_task_tests(raw, path):
            task_test_failures.append((path, task, cmd, why))
        for cmd, n, missing in wide_stage_scopes(raw):
            wide_stage_notes.append((path, cmd, n, missing))
        for c, cmd, word in prose_blind_sweeps(raw):
            prose_blind_failures.append((path, c, cmd, word))
        for c, cmd, filt in filtered_subsets(raw):
            filtered_notes.append((path, c, cmd, filt))
        for where in goal_check_missing(raw, path):
            goal_notes.append((path, where))
        examined_files += 1
        if not checks:
            empty_files.append(path.name)
        per = {k: 0 for k in totals}
        for c in checks:
            kind, why = classify(c)
            per[kind] += 1
            totals[kind] += 1
            if kind == "INSTANCE-SHAPED":
                failures.append((path, c, why))
        if not args.quiet:
            print(f"{path.name}: {len(checks)} check(s) — "
                  + ", ".join(f"{k.lower()} {v}" for k, v in per.items() if v))

    total = sum(totals.values())
    if total == 0:
        print(f"error: swept {examined_files} file(s) and found 0 gate checks — "
              f"the extraction is broken, or these are not plans", file=sys.stderr)
        return 2

    if failures:
        print(f"\nFAIL: {len(failures)} instance-shaped check(s):", file=sys.stderr)
        for path, c, why in failures:
            print(f"  {path.name}: {c[:96]}\n      → {why}", file=sys.stderr)

    # Reported separately from the shape classes, and deliberately NOT folded into the
    # totals line: this is a different axis (can the check run at all) and merging it
    # would move calibration figures that are pinned to the frozen corpus.
    if selector_failures:
        print(f"\nFAIL: {len(selector_failures)} selector-unmatched check(s) — the gate "
              f"names a pytest selector no task in the plan builds toward:", file=sys.stderr)
        for path, c, sel_path, expr, why in selector_failures:
            print(f"  {path.name}: {c[:96]}\n      → `{sel_path} -k {expr}` — {why}",
                  file=sys.stderr)

    # Third axis again: reported under its own name and kept out of the shape totals,
    # so the frozen-corpus calibration stays comparable.
    if task_test_failures:
        print(f"\nFAIL: {len(task_test_failures)} task-test-unscoped field(s) — the plan "
              f"declares expensive-suite tiering and a task's own Test: runs the whole "
              f"suite:", file=sys.stderr)
        for path, task, cmd, why in task_test_failures:
            print(f"  {path.name}: {task[:80]}\n      → `{cmd[:96]}` — {why}",
                  file=sys.stderr)

    # Advisory, never a failure: it changes no exit code. See the docstring for the
    # measurement that settled that — the identical syntax is correct for a secret or
    # TODO scan, where matching a comment is the point, and no rule here can tell which
    # one the author meant. Kept out of the shape totals so the frozen-corpus
    # calibration stays comparable.
    for path, c, cmd, word in prose_blind_failures:
        print(f"\nnote: {path.name}: `{cmd[:72]}` sweeps a source tree for {word!r}, "
              f"which grep will also match in a comment or docstring about it — so the "
              f"check goes red the day somebody documents it. If the property is about "
              f"what the code DOES, assert it as values in a test; if you do mean any "
              f"occurrence at all (a secret or TODO scan), this note is not for you.")

    # Advisory, never a failure: cost is not decidable from text, so this names the shape
    # and leaves the ~5 min judgment to the author and to Preflight's timing step.
    for path, cmd, n, missing in wide_stage_notes:
        print(f"\nnote: {path.name}: stage-scope names {n} test trees/modules "
              f"(`{cmd[:72]}`) with no `justified:` reason for {missing} — add "
              f"`justified: <tree> — <reason>; …` naming why each tree is in, or narrow it. "
              f"A stage-scope that lists most of the project is the "
              f"full suite under another name and pays plan-scope cost at every gate; "
              f"narrow it to the trees the stages touch or depend on if it crosses ~5 min "
              f"(test-scope-tiers.md § A declared stage-scope command is subject to the "
              f"same cost threshold).")

    # Advisory, never a failure: measured to include an existing-test false positive.
    for path, c, runner, filt in runner_selector_notes:
        print(f"\nnote: {path.name}: {runner} filter `{filt}` in a gate check matches no task "
              f"Test: in the plan — {c[:72]} — if no existing test matches it either, the "
              f"gate cannot pass (Preflight probes it: preflight-checks.md § Gate-selector probe)")

    # Name the files that yielded nothing. A batch total hides a file the extractor
    # cannot see — a master plan's unrecognised `**Gate:**` blocks, say, stay invisible
    # while the aggregate looks healthy.
    if empty_files:
        print(f"\nnote: {len(empty_files)} file(s) yielded 0 gate checks — "
              f"verify they genuinely have no gate: {', '.join(empty_files)}")

    # Advisory, never a failure: it changes no exit code, so an existing plan is
    # unaffected and a new plan gets told.
    for path, stages in scope_notes:
        print(f"\nnote: {path.name}: stage(s) {', '.join(stages)} declare a Scope: "
              f"but their gate has no executable sweep — the set was named, not swept")

    # Advisory, never a failure: a filter is often right. What the note asks for is
    # the sentence saying why the excluded members need no check, or a wider sweep.
    for path, c, cmd, filt in filtered_notes:
        print(f"\nnote: {path.name}: `{cmd[:72]}` restricts its sweep by a category filter "
              f"(`{filt}`) — state why the excluded members need no check and mark it "
              f"(scoped), or widen the sweep to the whole set (set-valued-checks.md)")

    # Advisory, never a failure: existing plans lack the marker. A new plan must
    # report zero (planning-projects' authoring checklist), as it must for INSTANCE-SHAPED.
    for path, where in goal_notes:
        whose = ("no gate check" if where == "plan"
                 else f"{where}'s **Gate:** block has no check")
        print(f"\nnote: {path.name}: {whose} marked (goal) — add one that sweeps the "
              f"goal over the whole artifact it is about, in every gate from the first one "
              f"whose artifact exists (gate-authoring.md § The plan's goal is a check from "
              f"the first gate)")

    print(f"\n{total} gate check(s) across {examined_files} file(s): "
          + ", ".join(f"{k.lower()} {v}" for k, v in totals.items()))
    if selector_failures:
        print(f"selector-unmatched {len(selector_failures)} (separate axis — see above)")
    if task_test_failures:
        print(f"task-test-unscoped {len(task_test_failures)} (separate axis — see above)")
    if prose_blind_failures:
        print(f"prose-blind-sweep {len(prose_blind_failures)} (advisory — see notes above)")
    if wide_stage_notes:
        print(f"stage-scope-wide {len(wide_stage_notes)} (advisory — see notes above)")
    if runner_selector_notes:
        print(f"selector-unmatched (gradle/cargo) {len(runner_selector_notes)} "
              f"(advisory — see notes above)")
    if filtered_notes:
        print(f"filtered-subset {len(filtered_notes)} (advisory — see notes above)")
    if goal_notes:
        print(f"goal-check-missing {len(goal_notes)} (advisory — see notes above)")
    return 1 if (failures or selector_failures or task_test_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
