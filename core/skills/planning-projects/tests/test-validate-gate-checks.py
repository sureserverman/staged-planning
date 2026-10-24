#!/usr/bin/env python3
"""Fixture suite for scripts/validate-gate-checks.py — run directly (CI convention):
    python3 core/skills/planning-projects/tests/test-validate-gate-checks.py

Asserts the classifier's contract: every classification branch, the `(judgment)`
opt-out, the empty-sweep refusal, a gate-less plan refusing rather than passing,
and crash-resistance across the 18 plan-parser fixtures (and a live directory of
plans, when one is named).

Every plan this suite reads is synthetic: each case is proved by a plan in
tests/fixtures/gate-shapes/ built and named for it. A corpus of owner plans stays
outside this repo; scripts/corpus-regress.py re-checks one there.

It also pins the *measured* false-positive shapes. Measured over a corpus of 374 gate
checks (357 before master-plan `**Gate:**` blocks are recognised; the shapes are the
same in both counts). The entire false-positive population is (a) a slash
inside ordinary prose ("pass/fail", "4/4", "skill/agent", "scan/rollup") matching a
path pattern, and (b) a bare script name (`validate-route-table.py`) not being
recognised as invoking a program. Both are regression-guarded below, because both
are the kind of thing a later "tightening" of the regex would silently reintroduce.

Stdlib only.
"""
import importlib.util
import re
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "validate-gate-checks.py")

spec = importlib.util.spec_from_file_location("vgc", SCRIPT)
vgc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vgc)

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def kind(text):
    return vgc.classify(text)[0]


def run(plan_text, extra=()):
    """Run the script as a subprocess on a temp plan; return (rc, out+err)."""
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "x-plan.md"
        p.write_text(plan_text, encoding="utf-8")
        r = subprocess.run([sys.executable, SCRIPT, *extra, str(p)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


def plan(*checks):
    body = "\n".join(f"- [ ] {c}" for c in checks)
    return f"# Project Plan: x\n\n## Stage 1: x\n\n### Stage 1 Gate\n{body}\n"


print("group 1 — every classification branch")
check(kind("`! grep -rl 'stale claim' widget-kit/`") == "EXECUTABLE",
      "recursive grep over a directory is EXECUTABLE")
check(kind("`python3 scripts/check-doc-coverage.py` exits 0") == "EXECUTABLE",
      "invoking a program is EXECUTABLE")
check(kind("**(judgment)** reads coherently — a sweep cannot prove it") == "JUDGMENT",
      "the (judgment) marker classifies as JUDGMENT")
check(kind("**(scoped)** `! grep -l '^## ITEM-008 ' records/infra/proj/backlog.md` — ids are "
           "unique within one register") == "SCOPED",
      "the (scoped) marker classifies as SCOPED")
check(kind("the README no longer claims the installer requires root")
      == "INSTANCE-SHAPED",
      "prose naming one artifact is INSTANCE-SHAPED (the canonical BAD form)")
check(kind("`grep -q 'stale claim' widget-kit/README.md` exits 1") == "INSTANCE-SHAPED",
      "an inspector scoped to one literal path is INSTANCE-SHAPED (the ALSO-BAD form)")
check(kind("Integration holds end to end") == "PROSE",
      "a claim naming no artifact is PROSE")

print("group 2 — the scope-not-syntax rule the classifier must not bless")
check(kind("`ls widget-kit/README.md`") == "INSTANCE-SHAPED",
      "being a shell command does not make a single-path check compliant")
check(kind("`! grep -rl 'x' widget-kit/ widget-docs/`") == "EXECUTABLE",
      "a sweep over multiple directories is EXECUTABLE")
check(kind("`grep -c 'x' a.md b.md c.md`") == "EXECUTABLE",
      "an inspector over several paths is a sweep")

print("group 3 — measured false-positive shapes must never regress")
for text, why in [
    ("Each case reports pass/fail on its own line.", "slash in prose: pass/fail"),
    ("Smoke run is green (4/4 checks, no retries)", "slash in a fraction: 4/4"),
    ("`alpha-tool` and `beta-tool` document each skill/agent pair; every link resolves.",
     "slash in prose: skill/agent"),
    ("The nightly scan/rollup job finishes with no error",
     "slash in prose: scan/rollup"),
    ("`validate-route-table.py` exits 0.", "bare script name is an invocation"),
    ("`ledger-rollup.py` dry-run against the live store exits 0",
     "bare script name with prose args"),
]:
    check(kind(text) != "INSTANCE-SHAPED", f"no false positive — {why}")

print("group 4 — backticked names are not commands")
check(kind("Cross-skill coherence: `planning-projects` and `executing-plans` agree")
      == "PROSE",
      "backticked component names alone are not a command")
check(kind("`wait for confirmation` before merging README.md") == "INSTANCE-SHAPED",
      "backticked English prose is not a command ('for'/'awk' as substrings)")

print("group 4b — an invoker must not launder a single-path inspector")
check(kind('`bash -c "grep -q x one.md"` exits 0') == "INSTANCE-SHAPED",
      "bash -c wrapping a single-path grep is still INSTANCE-SHAPED")
check(kind("`python3 -c \"import json; json.load(open('one.md'))\"` succeeds")
      == "INSTANCE-SHAPED",
      "python3 -c wrapping a single-path read is still INSTANCE-SHAPED")
check(kind('`bash -c "grep -rl x plugins/"` finds nothing') == "EXECUTABLE",
      "bash -c wrapping a real sweep is EXECUTABLE")
# The inline-script rule must not VETO a command that is plural for its own reasons.
# Judging the payload as the whole story would flag a pipeline that merely ends in a
# `python3 -c` stage.
check(kind("`python3 scripts/dump.py --format json | python3 -c \"import sys; assert sys.stdin.read()\"`")
      == "EXECUTABLE",
      "an inline script inside a pipeline does not veto the pipeline's own scope")
check(kind("`grep -c 'x' a.md b.md c.md`") == "EXECUTABLE",
      "grep's -c count flag is not mistaken for an interpreter's -c")

print("group 4c — a command must not carry an unverified prose claim")
check(kind("`python3 scripts/smoke.py` exits 0 and the README.md changelog entry reads correctly")
      == "INSTANCE-SHAPED",
      "a command plus a claim about a DIFFERENT artifact is INSTANCE-SHAPED")
check(kind("`python3 scripts/smoke.py` exits 0") == "EXECUTABLE",
      "the same command alone stays EXECUTABLE")

print("group 4d — wrapped checks are joined before classifying")
# Reading only the first line changes the verdict in BOTH directions. Wrapped bullets are
# common: measured 28 wrapped bullets across 7 plans of a plan corpus.
wrapped_exec = (
    "### Stage 1 Gate\n"
    "- [ ] Docs index fresh: `python3 scripts/build-docs-index.py --write &&\n"
    "      git diff --exit-code docs-index.json`\n")
got = vgc.gate_checks(wrapped_exec)
check(len(got) == 1 and got[0].endswith("docs-index.json`"),
      "a wrapped command is joined into one check")
check(kind(got[0]) == "EXECUTABLE",
      "joined, the wrapped command is EXECUTABLE (truncated, it read INSTANCE-SHAPED)")
wrapped_inst = (
    "### Stage 1 Gate\n"
    "- [ ] Version mirrors consistent: `grep -c 'x'\n"
    "      widget/.config/manifest.json` = 1\n")
got2 = vgc.gate_checks(wrapped_inst)
check(len(got2) == 1 and "manifest.json" in got2[0],
      "the path on the continuation line is not lost")
check(kind(got2[0]) == "INSTANCE-SHAPED",
      "joined, the single-path inspector is caught (truncated, it read PROSE and passed)")
check(len(vgc.gate_checks("### Stage 1 Gate\n- [ ] a\n- [ ] b\n")) == 2,
      "consecutive bullets are not accidentally joined")

print("group 4e — the heading contract is not over-matched")
check(vgc.gate_checks("### Task 1.1: Gate the release job on a signed tag\n- [ ] a\n") == [],
      "a task heading merely containing the word Gate is not a gate section")
check(len(vgc.gate_checks("### Stage 2 Gate\n- [ ] a\n")) == 1, "Stage N Gate matches")
check(len(vgc.gate_checks("#### Gate\n- [ ] a\n")) == 1, "a bare Gate heading matches")

print("group 5 — exit codes and the empty-sweep refusal")
rc, out = run(plan("`! grep -rl 'console.log(' plugins/`"))
check(rc == 0 and "instance-shaped 0" in out, "a clean plan exits 0 and reports counts")
rc, out = run(plan("the README no longer claims X"))
check(rc == 1 and "instance-shaped 1" in out, "an instance-shaped check exits 1")
check("names one artifact" in out, "the failure names why, not just that")
rc, out = run("# Project Plan: x\n\n## Stage 1: x\n\nNo gate here at all.\n")
check(rc == 2 and "0 gate checks" in out,
      "a plan with no gate checks exits 2 — an empty sweep must not read as a pass")
rc, out = run(plan("`! grep -rl 'console.log(' p/`"), extra=("--quiet",))
check(rc == 0 and "gate check(s) across" in out, "--quiet still reports the totals")
r = subprocess.run([sys.executable, SCRIPT, "/nonexistent/nope.md"],
                   capture_output=True, text=True)
check(r.returncode == 2 and "not a file" in r.stderr, "a missing file exits 2 clearly")

print("group 6 — crash resistance across plan corpora")
plugin = pathlib.Path(HERE).parents[2]          # tests/ -> planning-projects/ -> skills/ -> plugin
fixtures = sorted((plugin / "lib/tests/fixtures/plan-parser").glob("*.md"))
check(len(fixtures) >= 18, f"plan-parser fixture corpus present ({len(fixtures)} files)")
r = subprocess.run([sys.executable, SCRIPT, "--quiet", *map(str, fixtures)],
                   capture_output=True, text=True)
check(r.returncode in (0, 1) and "gate check(s) across" in r.stdout,
      "the 18 plan-parser fixtures classify without a traceback")
check("Traceback" not in r.stderr, "no traceback on legacy/edge-case plan shapes")

# The synthetic plans, one per case (group 9 reads them).
SHAPES = pathlib.Path(HERE) / "fixtures" / "gate-shapes"

# Opt-in: a live directory of plans to classify, e.g. a project's plans/ folder. The
# suite's result must not depend on files outside this repo, so by default there is no
# live sweep — the synthetic plans in gate-shapes/ are what the branches are pinned against.
live = os.environ.get("GATE_CHECK_LIVE_CORPUS")
live_dir = pathlib.Path(live) if live else None
real = sorted(live_dir.glob("*.md")) if live_dir and live_dir.is_dir() else []
if real:
    r = subprocess.run([sys.executable, SCRIPT, "--quiet", *map(str, real)],
                       capture_output=True, text=True)
    check("Traceback" not in r.stderr,
          f"no traceback across {len(real)} live plans")
    tot = [l for l in r.stdout.splitlines() if "gate check(s) across" in l]
    check(bool(tot), "live-corpus run reports a total")
    if tot:
        # Informational, not asserted: such plans can predate the rule, so a nonzero
        # count is legacy non-compliance rather than a classifier defect. Printed so
        # a later precision regression is visible in CI output.
        print(f"       corpus rate (informational): {tot[-1].strip()}")
else:
    print("       live corpus: not requested (set GATE_CHECK_LIVE_CORPUS=<plans dir> to sweep one)")

print("group 6b — a path-inspecting tool must not launder single-path scope")
# `git`, `sed`, `jq`, `cat`, `head`, `tail` read exactly the paths given, so they are
# INSPECTORS, not opaque program runners. Classing them as runners would let them pass
# the very shape the rule calls "ALSO BAD".
for text, exp, why in [
    ("`git grep -q 'x' -- widget-kit/README.md` exits 1", "INSTANCE-SHAPED", "git grep on one file"),
    ("`sed -n '1,5p' widget-kit/README.md` no longer shows the claim", "INSTANCE-SHAPED", "sed on one file"),
    ("`git grep -rl 'x' -- widget-docs/`", "EXECUTABLE", "git grep over a directory still sweeps"),
    ("`pytest tests/test_one.py` passes", "EXECUTABLE", "a test runner's scope stays opaque"),
]:
    check(kind(text) == exp, f"{why} → {exp}")

print("group 7 — pipe plurality requires a plural SOURCE")
check(kind('`cat CHANGELOG.md | bash -c "grep -q x CHANGELOG.md"`') == "INSTANCE-SHAPED",
      "a single-file pipe source does not launder a single-path inspector")
check(kind('`echo hi | bash -c "grep -q x one.md"`') == "INSTANCE-SHAPED",
      "an opaque-but-scalar pipe source does not either")
check(kind('`python3 scripts/dump.py | python3 -c "import sys; assert sys.stdin.read()"`')
      == "EXECUTABLE",
      "a program on the source side of the pipe still sweeps")

print("group 8 — the join stops at content that is not a wrap")
para = ("### Stage 1 Gate\n"
        "- [ ] Some check here\n"
        "  Note: added because of X, see the discussion above for context.\n"
        "- [ ] Another check\n")
got = vgc.gate_checks(para)
check(len(got) == 2 and got[0] == "Some check here",
      "an indented explanatory Note: is not glued onto the check")
fence = ("### Stage 1 Gate\n"
         "- [ ] Some check here\n"
         "  ```bash\n  grep -q x one.md\n  ```\n")
check(vgc.gate_checks(fence)[0] == "Some check here",
      "an indented fenced code block is not absorbed as continuation")
check(vgc.gate_checks("### Stage 1 Gate\n- [ ] `grep -c 'x'\n      a/b.md` = 1\n")[0]
      .endswith("a/b.md` = 1"),
      "a genuine mid-backtick wrap is still joined")

# An amendment annotation is history the protocol REQUIRES (preflight-checks.md §
# Amending authored ceremony: cite the rule, keep the was-value). Read as part of the
# check, the cited reference file becomes an "uncovered artifact" and the was-value's
# old command a second command, so every properly amended check would go
# INSTANCE-SHAPED.
amended = ("### Stage 1 Gate\n"
           "- [ ] `grep -rn x widget-kit/docs --include='*.md'` prints nothing"
           " *(amended at Preflight 2026-01-15 per preflight-checks.md § Amending authored"
           " ceremony, user-approved — was: `grep -c x one/file.md` = 0)* — the tail stays\n")
got_am = vgc.gate_checks(amended)
check(len(got_am) == 1 and "amended" not in got_am[0] and "one/file.md" not in got_am[0]
      and got_am[0].endswith("the tail stays"),
      f"an amendment annotation is stripped, the check around it kept ({got_am!r})")
check(kind(got_am[0]) == "EXECUTABLE",
      "an amended sweep still classifies EXECUTABLE, not INSTANCE-SHAPED")
# A `)*` inside the backticked was-value (a regex quantifier) must not close the note
# early and splice its remainder onto the check.
quant = ("### Stage 1 Gate\n"
         "- [ ] `grep -rE '(foo)*' widget-kit/docs` prints nothing"
         " *(amended per preflight-checks.md — was: `grep -E '(bar)*' one/file.md`)* tail\n")
got_q = vgc.gate_checks(quant)
check(got_q == ["`grep -rE '(foo)*' widget-kit/docs` prints nothing tail"],
      f"a `)*` inside the was-value's backticks does not end the note ({got_q!r})")

print("group 8b — a declared Scope: must be swept, not merely named")


def scoped_plan(scope_line, *checks):
    """A one-stage plan whose task optionally declares a Scope:."""
    body = "\n".join(f"- [ ] {c}" for c in checks)
    scope = f"- **Scope:** {scope_line}\n" if scope_line else ""
    return ("# Project Plan: x\n\n## Stage 1: x\n\n### Task 1.1: t\n"
            "- **Status:** [ ]\n" + scope +
            "- **Test:** `python3 t.py`\n\n### Stage 1 Gate\n" + body + "\n")


rc, out = run(scoped_plan("every commands/*.md", "the README no longer claims X"))
check("was named, not swept" in out,
      "a stage declaring Scope: whose gate has no executable sweep is reported")

rc2, out2 = run(scoped_plan("every commands/*.md",
                            "`! grep -rl 'X' commands/`"))
check("was named, not swept" not in out2,
      "a stage declaring Scope: WITH an executable sweep is not reported")

# The sanctioned SECOND shape: a (judgment)-marked check covers a declared Scope: too.
rc_j, out_j = run(scoped_plan("every commands/*.md",
                              "**(judgment)** every command doc reads coherently"))
check("was named, not swept" not in out_j,
      "a Scope: covered by a (judgment) check is NOT flagged — both sanctioned shapes count")

# The asymmetry that must hold: a plan predating the field reports exactly as before.
legacy = plan("the README no longer claims X")
rc3, out3 = run(legacy)
check("was named, not swept" not in out3,
      "a plan with NO Scope: field anywhere is never given the scope note")
check(rc3 == 1 and "instance-shaped" in out3.lower(),
      "and it is still classified exactly as before (no retro-failure, no new failure)")

# The note is advisory: it must not change an exit code in either direction.
rc4, _ = run(scoped_plan("every commands/*.md", "`python3 sweep.py`"))
check(rc4 == 0, "the scope note alone never fails a plan whose checks are clean")
rc5, out5 = run(scoped_plan("every commands/*.md", "the README no longer claims X"))
rc6, _ = run(plan("the README no longer claims X"))
check(rc5 == rc6,
      "exit code is identical with and without the Scope: field — advisory, not a gate")

print("group 2b — (scoped) rescues the narrow-but-correct check without widening the default")
# The marker exists because widening a claim past the set it is over does not make the check
# stricter — it makes it unpassable. A check that sweeps many projects' records for a backlog ID
# unique to one project's register matches unrelated entries and can never go green. What must
# NOT happen is the marker becoming a general waiver, so both halves are pinned: the marked
# check passes, and the identical check without it still fails.
_scoped = "`! grep -l '^## ITEM-008 ' records/infra/proj/backlog.md`"
check(kind(f"**(scoped)** {_scoped} — one register is the whole set") == "SCOPED",
      "a marked single-path check is SCOPED, not INSTANCE-SHAPED")
check(kind(f"{_scoped} — one register is the whole set") == "INSTANCE-SHAPED",
      "the SAME check unmarked still fails — the marker is the assertion, not how the path looks")
check(run(plan(f"**(scoped)** {_scoped} — one register is the whole set"))[0] == 0,
      "a plan whose only check is (scoped) exits 0")
check(run(plan(f"{_scoped} — one register is the whole set"))[0] == 1,
      "the same plan unmarked exits 1")

print("group 8c — SELECTOR-UNMATCHED: a gate selector no task builds toward")
# The defect: a gate names an existing test file with a `-k` filter that collects zero tests
# in it. A gate nobody can pass is not caught by any shape rule — the check is a perfectly
# well-formed EXECUTABLE sweep. Hence a separate axis, pinned in BOTH directions here.


def plan_with_task(test_field, *checks):
    """A plan whose single task declares `test_field`, plus the given gate checks."""
    body = "\n".join(f"- [ ] {c}" for c in checks)
    return (f"# Project Plan: x\n\n## Stage 1: x\n\n"
            f"#### Task 1.1 — t\n\n- **Status:** [ ]\n- **Test:** {test_field}\n\n"
            f"### Stage 1 Gate\n{body}\n")


_unmatched = plan_with_task("`pytest tests/foo.py -k parses` — it parses",
                            "`pytest tests/foo.py -k nothing` — the goal, end to end")
_matched = plan_with_task("`pytest tests/foo.py -k parses` — it parses",
                          "`pytest tests/foo.py -k parses` — the goal, end to end")
check(len(vgc.unmatched_selectors(_unmatched)) == 1,
      "a gate -k selector no task declares is SELECTOR-UNMATCHED")
check(vgc.unmatched_selectors(_matched) == [],
      "the same selector passes when a task's Test: declares it")
check(run(_unmatched)[0] == 1, "a plan with an unmatched selector exits 1")
check(run(_matched)[0] == 0, "a plan whose selectors all match a task exits 0")
check("selector-unmatched" in run(_unmatched)[1],
      "the failure is reported under its own name, not folded into the shape classes")
# The wrong-file case and the typo case are distinguishable, and the message says which.
check("different -k filter" in run(_unmatched)[1],
      "a declared file with a different filter is named as the typo case it is")
# A bare whole-file run is legitimate — a regression sweep over an existing suite. Pinning
# this prevents the obvious over-tightening, which would flag every ordinary gate.
check(vgc.unmatched_selectors(
        plan_with_task("`pytest tests/foo.py -k parses`",
                       "`pytest tests/regression.py` — no regressions")) == [],
      "a bare pytest file run with no -k is never a selector")
# Both markers exempt, on the same bargain they make everywhere else in this script.
for marker in ("(judgment)", "(scoped)"):
    check(vgc.unmatched_selectors(
            plan_with_task("`pytest tests/foo.py -k parses`",
                           f"**{marker}** `pytest tests/bar.py -k later` — author asserts")) == [],
          f"a {marker} check is exempt from the selector cross-reference")
# False-positive shapes. These matter more than the true positives: this check is wired into
# the mandatory pre-presentation checklist, so a false positive does not merely miss a defect,
# it blocks a correct plan from being presented — the opposite failure from the one the class
# exists to fix.
check(vgc.pytest_selectors("`pytest tests/a.py -k foo && pytest tests/b.py -k bar`")
      == [("tests/a.py", "foo"), ("tests/b.py", "bar")],
      "chained invocations keep each path with its OWN -k filter")
check(vgc.unmatched_selectors(
        "# P\n\n## Stage 1: x\n\n"
        "#### Task 1.1 — a\n\n- **Test:** `pytest tests/a.py -k foo`\n\n"
        "#### Task 1.2 — b\n\n- **Test:** `pytest tests/b.py -k bar`\n\n"
        "### Stage 1 Gate\n- [ ] `pytest tests/a.py -k foo && pytest tests/b.py -k bar`\n") == [],
      "a chained gate check whose every invocation is task-declared is not flagged")
check(vgc.pytest_selectors("`pytest tests/x.py -k restart --cov=src/mod.py`")
      == [("tests/x.py", "restart")],
      "a .py value of a --flag= is not a selector path (coverage targets are not test files)")
check(vgc.unmatched_selectors(
        "# P\n\n## Stage 1: x\n\n"
        "#### Task 1.1 — a\n\n- **Test:** `pytest tests/x.py -k restart`\n\n"
        "### Stage 1 Gate\n- [ ] `pytest tests/x.py -k restart --cov=src/mod.py` with coverage\n") == [],
      "a coverage-annotated gate running the declared selector is not flagged")
# A master plan carries no tasks, so every selector in its cross-plan gates would flag —
# measured: 3 of 5 corpus-wide flags come from one master plan.
_master = ("# Master Plan: x\n\n## Sub-plans\n\n### 1. sub-01\n\n"
           "**Gate:** \n- [ ] `pytest tests/e2e/test_x.py -k restart` — the integrated proof\n")
check(vgc.unmatched_selectors(_master) == [],
      "a master plan's selectors are not flagged — its tasks live in its sub-plans")
check(vgc.is_master_plan("# Master Plan: x") and
      vgc.is_master_plan("", path="2026-01-01-topic-master-plan.md"),
      "both master signals are recognised (heading and filename), matching lib/plan_parser.py")
check(vgc.unmatched_selectors(_master.replace("# Master Plan: x", "# Project Plan: x")) != [],
      "the SAME document as a non-master still flags — the skip is the master's, not a waiver")

# The defect's full shape: the file exists in the plan's world, the filter matches nothing
# in it, and no task builds toward it.
check(len(vgc.unmatched_selectors(plan_with_task(
        "`pytest tests/integration/test_cache_store.py -k durable` — a durable entry",
        "`pytest tests/e2e/test_widget_sync.py -k restart` — a widget survives "
        "a restart"))) == 1,
      "a gate selecting a test no task builds is caught at authoring")

print("group 8d — SELECTOR-UNMATCHED for Gradle `--tests` and `cargo test <filter>` (advisory)")
# The same cross-reference as the pytest form, for the two other runners gates commonly
# use. ADVISORY: measured over a corpus of 595 plans, the flagged set includes a filter naming
# a test that already exists — the false positive the pytest form documents. So these forms
# are reported and never change the exit code (gate-authoring.md
# § A gate heuristic ships with a severity axis and a measured trigger rate).
_g_un = plan_with_task("`./gradlew :app:testDebugUnitTest --tests '*ParserTest*'` — parses",
                       "`./gradlew :app:testDebugUnitTest --tests '*NothingTest*'` — the goal")
_g_ok = plan_with_task("`./gradlew :app:testDebugUnitTest --tests '*ParserTest*'` — parses",
                       "`./gradlew :app:testDebugUnitTest --tests '*ParserTest*'` — the goal")
_c_un = plan_with_task("`cargo test -p core parser::` — parses",
                       "`cargo test -p core nothing_` — the goal")
_c_ok = plan_with_task("`cargo test -p core parser::` — parses",
                       "`cargo test -p core parser:: -- --nocapture` — the goal")
check(len(vgc.unmatched_runner_selectors(_g_un)) == 1,
      "an undeclared Gradle --tests filter is flagged")
check(len(vgc.unmatched_runner_selectors(_c_un)) == 1,
      "an undeclared cargo test filter is flagged")
check(vgc.unmatched_runner_selectors(_g_ok) == [],
      "a Gradle filter a task declares passes")
check(vgc.unmatched_runner_selectors(_c_ok) == [],
      "a cargo filter a task declares passes (arguments after -- are not the filter)")
for marker in ("(judgment)", "(scoped)"):
    check(vgc.unmatched_runner_selectors(
            plan_with_task("`cargo test parser::`",
                           f"**{marker}** `cargo test later_` — author asserts")) == [],
          f"a {marker} check is exempt from the Gradle/cargo cross-reference")
check(vgc.runner_selectors("`cargo test --workspace --offline`") == [],
      "a cargo test with no filter is never a selector (a whole-suite run is legitimate)")
check(vgc.runner_selectors("`cargo test -p core --test cli api_`") == [("cargo", "api_")],
      "flag values (-p core, --test cli) are not read as the filter")
check(vgc.runner_selectors("`cd engine && cargo test --lib a_ && cargo test --lib b_`")
      == [("cargo", "a_"), ("cargo", "b_")],
      "chained cargo invocations each keep their own filter")
check(vgc.runner_selectors("`./gradlew test --tests=com.x.FooTest`")
      == [("gradle", "com.x.FooTest")],
      "the Gradle `--tests=` form is read too")
# cargo's own `--tests` flag (all test targets) is not a Gradle filter.
check(vgc.runner_selectors("`cargo test --tests -- --nocapture`") == [],
      "cargo's `--tests` flag is not read as a Gradle selector")
check(vgc.runner_selectors("`cargo test -p core --tests api_`") == [("cargo", "api_")],
      "a cargo command with --tests yields its cargo filter only")
check(vgc.runner_selectors("`./gradlew test --tests -x`") == [],
      "a Gradle --tests value starting with `-` is a flag, not a pattern")
check(vgc.unmatched_runner_selectors(_c_un.replace("# Project Plan: x", "# Master Plan: x")) == [],
      "a master plan's Gradle/cargo selectors are skipped, as its pytest ones are")
rc_r, out_r = run(_c_un)
check(rc_r == 0, "the Gradle/cargo form is advisory — it never changes the exit code")
check("selector-unmatched (gradle/cargo) 1 (advisory" in out_r,
      "the advisory count is printed under its own name")
check(run(_c_ok)[1].count("gradle/cargo") == 0, "nothing is printed when every filter matches")
check(re.search(r"measured\s+2026-10-06\s+over\s+\d+\s+plans\s+\(every\s+plan\s+in\s+one\s+owner's\s+records\s+homes\):\s+\d+\s+Gradle/cargo"
                r"\s+gate\s+selectors?\s+in\s+\d+\s+plans,\s+\d+\s+hits\s+in\s+\d+\s+plans",
                vgc.__doc__) is not None,
      "the docstring states the measured trigger rate with its corpus and date")

print("group 10 — TASK-TEST-UNSCOPED: a task Test: that collects the whole suite")
# A task `Test:` such as `poetry run pytest -m 'not network'` subtracts one marker and still
# collects the whole suite, and it runs inside every Red-Green loop of its task. The plan's
# stage-scope command is the bounded run; a task Test: that bypasses it pays for the full
# suite on every loop.
#
# THE QUESTION IS CLOSED, AND THAT IS THE DESIGN. Not "is this command cheap" — unanswerable
# from text — but "does anything in it narrow what it collects?" A command with any positive
# selector is not judged. A command that starts from everything and only subtracts is still
# everything.
#
# WHY THIS GROUP IS A TABLE. A test derived from a fix can only confirm that fix: one
# assertion per known counterexample passes while each counterexample's sibling sits in a
# cell nobody wrote down. So the sets are enumerated first and the code answers to them.
# The sets are lettered in the order they appear here, so a reader scanning for a member
# finds one.


def tiered_plan(test_field, task_extra="", tiers=True):
    """A plan declaring expensive-suite tiering, with one task carrying `test_field`."""
    block = ("**Test-scope commands** (per references/test-scope-tiers.md):\n"
             "- stage-scope: `pytest tests/unit`\n"
             "- plan-scope:  `pytest`\n\n") if tiers else ""
    return (f"# Project Plan: x\n\n## Preflight\n\n{block}"
            f"## Stage 1: x\n\n"
            f"### Task 1.1: t\n\n- **Status:** [ ]\n- **Test:** {test_field}\n"
            f"{task_extra}\n\n"
            f"### Stage 1 Gate\n- [ ] `pytest tests/` passes\n")


def n_unscoped(text, path=None):
    return len(vgc.unscoped_task_tests(text, path))


# --- SET A: nothing narrows what it collects -> MUST FLAG ----------------------------
for cmd, why in [
    ("`pytest`", "bare"),
    ("`pytest -q`", "bare plus output noise"),
    ("`poetry run pytest -m 'not network'`", "the lead case — subtractive only"),
    ("`pytest --ignore=tests/slow`", "subtractive only"),
    ("`cargo test`", "bare"),
    ("`go test ./...`", "the whole module is not a bound"),
    ("`npm test`", "bare"),
    ("`npm run test`", "bare, the `run` spelling"),
    ("`./gradlew test`", "aggregate lifecycle task"),
    ("`./gradlew check assembleDebug`", "aggregate — `check` runs every test task, whatever sits beside it"),
    ("`./gradlew connectedAndroidTest`", "aggregate, UNFLAVOURED — no variant name still means every variant"),
    ("`./gradlew testProductionReleaseUnitTest`", "aggregate, flavoured"),
]:
    check(n_unscoped(tiered_plan(cmd)) == 1, f"flags: {cmd} — {why}")

# --- SET B: something narrows it, or it is not a suite run -> MUST NOT FLAG -----------
# These matter more than SET A. The check is wired into a MANDATORY pre-presentation
# checklist, so a false positive does not merely miss a defect — it blocks a correct plan
# from being presented.
for cmd, why in [
    ("`pytest tests/unit/test_x.py`", "positive path"),
    ("`pytest -k parses`", "positive filter"),
    ("`pytest -m unit`", "positive marker — unlike `-m 'not x'`"),
    ("`pytest tests/x.py::test_one`", "node id"),
    ("`cargo test -p mycrate`", "positive package"),
    ("`cargo test --workspace --no-run`", "compiles the tests and runs none"),
    ("`npm run test-utils`", "a DIFFERENT script — `test` is a prefix, not the name"),
    ("`yarn test-storybook`", "likewise"),
    ("`./gradlew --version`", "runs no tests at all"),
    ("`./gradlew verifyLayers`", "a specifically named task IS its own scope"),
    ("`./gradlew schemaTest`", "a name merely CONTAINING 'Test' is not an aggregate"),
    ("`./gradlew :app:test`", "module-qualified task path"),
    ("`./gradlew test --tests '*Foo'`", "an aggregate task with a filter is bounded"),
    ("`grep -q x README.md`", "not a suite runner"),
    ("`bash scripts/run-tests.sh`", "not a recognised runner — the list is fixed, and short"),
]:
    check(n_unscoped(tiered_plan(cmd)) == 0, f"does not flag: {cmd} — {why}")

# --- SET C: vacuous narrowing — the flag is present, its VALUE bounds nothing ---------
# The prose rule says a selector must bound what the command COLLECTS, so a flag's presence
# is not enough: its value must narrow the collection.
for cmd, why in [
    ("`pytest -k ''`", "an empty selector collects everything"),
    ('`pytest -k ""`', "the double-quoted spelling of the same"),
    ("`pytest -k 'not slow'`", "subtractive: everything minus a slice is still everything"),
    ("`pytest .`", "the repo root is not a bound"),
    ("`pytest ./`", "nor is it when spelled with a slash — both spellings must agree"),
    ("`./gradlew test --tests '*'`", "a universal wildcard bounds nothing"),
]:
    check(n_unscoped(tiered_plan(cmd)) == 1, f"flags vacuous filter: {cmd} — {why}")
for cmd, why in [
    ("`pytest -k parses`", "a real selector"),
    ("`pytest -k 'parse and not slow'`", "a positive term makes it narrowing, `not` and all"),
    ("`./gradlew test --tests '*ParserTest'`", "a wildcard with a stem narrows"),
    ("`pytest tests/`", "a subdirectory is a bound"),
]:
    check(n_unscoped(tiered_plan(cmd)) == 0, f"still does not flag: {cmd} — {why}")

# --- SET D: the SAME FLAG means different things to different runners ----------------
# `-p` must be read per runner. It is cargo's `--package`; in pytest it loads a plugin and
# in go it is the parallelism count. Read runner-blind, that one flag disarms the check on
# the lead case's own command.
for cmd, why in [
    ("`pytest -p no:randomly`", "pytest -p LOADS A PLUGIN — bounds nothing"),
    ("`poetry run pytest -p no:randomly -m 'not network'`",
     "the lead command plus one routine flag"),
    ("`go test -p 4 ./...`", "go -p is the PARALLELISM count"),
    ("`cargo test --workspace`", "--workspace widens; it does not narrow"),
    ("`xcodebuild test -scheme MyApp`", "a scheme is not a test selector"),
]:
    check(n_unscoped(tiered_plan(cmd)) == 1, f"flags: {cmd} — {why}")
for cmd, why in [
    ("`cargo test parse_rows`", "cargo's canonical positional filter"),
    ("`cargo test --lib`", "cargo TARGET selector — measured 11 corpus occurrences, each a "
     "false positive if this flagged"),
    ("`cargo test --doc`", "likewise, doc-tests only"),
    ("`cargo test --bin mytool`", "likewise, one binary target"),
    ("`pytest tests`", "a bare directory name, no slash"),
    ("`go test ./... -run TestFoo`", "-run is go's selector"),
    ("`xcodebuild test -only-testing:MyAppTests/FooTests -scheme MyApp`",
     "-only-testing: is the ONLY common way to scope xcodebuild, and it is colon-joined"),
    ("`vitest run --project unit`", "positive project selector"),
    ("`jest --testPathPattern=parser`", "positive path filter, `=` form"),
]:
    check(n_unscoped(tiered_plan(cmd)) == 0, f"does not flag: {cmd} — {why}")

# --- SET E: subtractive flags in SPACE form ------------------------------------------
# `--ignore=tests/slow` is enumerated in SET A; `--ignore tests/slow` and `--deselect` are
# its immediate siblings. In space form the flag's ARGUMENT can read as a positive path, so
# the `=` form alone proves less than it looks.
for cmd in ["`pytest --ignore tests/slow`", "`pytest --deselect tests/x.py`",
            "`pytest -m 'not network' --deselect tests/e2e/test_x.py`"]:
    check(n_unscoped(tiered_plan(cmd)) == 1, f"flags space-form subtractive flag: {cmd}")

# --- SET F: the exemption, enumerated as placement x polarity x reason ----------------
# ONE placement, so there is no fourth cell to forget, and a REASON is required because both
# checklists say "with a reason".
check(n_unscoped(tiered_plan("`pytest`", "\n- **full-suite: accepted** — cross-cutting")) == 0,
      "a `full-suite: accepted` FIELD with a reason exempts")
check(n_unscoped(tiered_plan("`pytest`", "\n- **full-suite: accepted**")) == 1,
      "a BARE marker does not — the reason IS the exemption, and the checklists say so")
check(n_unscoped(tiered_plan("`pytest`", "\n- **Note:** we did not mark `full-suite: accepted`")) == 1,
      "prose DENYING the exemption does not grant it")
check(n_unscoped(tiered_plan("`pytest`  (we are not using full-suite: accepted here)")) == 1,
      "nor does a denial on the Test: line itself")
check(n_unscoped(tiered_plan("`pytest`  (full-suite: accepted — cross-cutting)")) == 1,
      "and the inline form no longer exempts at all — one placement, deliberately")

# --- SET G: arming, across every plan format -----------------------------------------
check(n_unscoped(tiered_plan("`pytest`", tiers=False)) == 0,
      "a plan declaring NO tiering is not checked (guard rail 1: below the ~5 min threshold "
      "there is nothing to bound)")
check(n_unscoped("# Project Plan: x\n\n**Test-scope commands:** not tiered — the whole "
                 "suite runs in 40 s, far below the ~5 min threshold.\n\n## Stage 1: x\n\n"
                 "### Task 1.1: t\n\n- **Test:** `pytest`\n\n"
                 "### Stage 1 Gate\n- [ ] `pytest tests/` passes\n") == 0,
      "a 'not tiered' declaration does not arm — the stage-scope/plan-scope pair is the "
      "trigger, not the heading")
# Gate PROSE is not a declaration. A gate bullet reading `- Stage-scope pass green` has no
# colon and declares nothing, so it must not arm the check.
check(n_unscoped("# Project Plan: x\n\n## Stage 1: x\n\n### Task 1.1: t\n\n"
                 "- **Test:** `pytest`\n\n### Stage 1 Gate\n"
                 "- Stage-scope pass green\n- Plan-scope pass deferred\n") == 0,
      "gate prose mentioning the tiers does not arm the check — a declaration carries a colon")
check(n_unscoped("# Master Plan: x\n\n**Test-scope commands**\n- stage-scope: `pytest a/`\n"
                 "- plan-scope: `pytest`\n\n## Sub-plans\n\n### 1. sub-01\n\n"
                 "**Gate:** \n- [ ] `pytest` — integrated\n") == 0,
      "a master plan is skipped — its tasks live in its sub-plans")

# A LIGHT plan. A Light plan has no Preflight section, so the check reaches the format only
# through the declaration block light-plan-format.md sanctions; without it the bare
# `cargo test` below reports zero findings. Both directions pinned.
_light = ("# Light Plan: x\nFormat: Light — small\n\n{block}## Stage 1: x\n\n"
          "### Task 1.1: t\n\n- **Status:** [ ]\n- **Test:** `cargo test`\n\n"
          "### Stage 1 Gate\n- [ ] the full existing test suite passes\n")
check(n_unscoped(_light.format(block="")) == 0,
      "a Light plan declaring no tiering is not checked, same as any undeclared plan")
check(n_unscoped(_light.format(
        block="**Test-scope commands**\n- stage-scope: `cargo test -p a`\n"
              "- plan-scope: `cargo test`\n\n")) == 1,
      "a Light plan that DOES declare tiering arms the check — the format carries the "
      "block, and without it this whole format is unreachable")

# --- reporting ----------------------------------------------------------------------
rc, out = run(tiered_plan("`pytest` passes"))
check(rc == 1, "a plan with an unscoped task Test: exits 1")
check("task-test-unscoped" in out.lower(), "reported under its own name, on its own axis")
check(run(tiered_plan("`pytest tests/unit/test_x.py`"))[0] == 0, "a scoped task Test: exits 0")
_flag = vgc.unscoped_task_tests(tiered_plan("`make lint && pytest -q && make docs`"))
check(len(_flag) == 1 and _flag[0][1] == "pytest -q",
      "the message names the offending invocation, not the line it sits in")

print("group 9b — STAGE-SCOPE-WIDE: a stage-scope that is the full suite under another name")


def tiered_plan(stage_cmd):
    return ("# Project Plan: x\n\n## Preflight\n\n**Test-scope commands:**\n"
            f"- stage-scope: `{stage_cmd}`\n"
            "- plan-scope: `uv run pytest`\n\n## Stage 1: x\n\n### Stage 1 Gate\n"
            "- [ ] `! grep -rl 'X' commands/`\n")


rc_w, out_w = run(tiered_plan("uv run pytest tests/parser tests/storage tests/api "
                              "tests/render tests/cli -q"))
check("stage-scope names 5 test trees" in out_w,
      "a five-tree stage-scope declaration is noted, with its tree count")
check(rc_w == 0, "the note is advisory — it never changes the exit code")
rc_n, out_n = run(tiered_plan("uv run pytest tests/parser tests/api -q"))
check("stage-scope names" not in out_n, "a two-tree stage-scope is not noted")
rc_g, out_g = run(tiered_plan("./gradlew :app:testDebugUnitTest :core:test :cache:test "
                              ":sync:test verifyLayers"))
check("stage-scope names 4 test trees" in out_g,
      "gradle `:module:test` tasks count as trees, so an Android declaration is covered")
check(len(vgc.wide_stage_scopes("- stage-scope: `cargo test --lib`\n- plan-scope: `x`\n")) == 0,
      "a single-runner stage-scope with no tree list is not noted")
# A `justified:` clause giving one reason per tree silences the finding;
# a missing reason for any tree keeps it, naming the tree. The finding stays ADVISORY: measured
# 2026-10-06 over a corpus of 119 real plans declaring stage-scope, 49 hit, and the hits include
# lint and assemble tasks counted as test trees — not all defects.
_four = ("uv run pytest tests/parser tests/storage tests/api tests/render -q")
rc_j0, out_j0 = run(tiered_plan(_four))
check("stage-scope names 4 test trees" in out_j0 and "no `justified:`" in out_j0,
      "a 4-tree stage-scope with no `justified:` is reported, saying the clause is missing")
_just = (f"- stage-scope: `{_four}` justified: tests/parser — Stage 1 edits it; "
         "tests/storage — Stage 1 imports it; tests/api — Stage 2 changes the port; "
         "tests/render — Stage 2 adds a layer\n- plan-scope: `uv run pytest`\n")
check(vgc.wide_stage_scopes(_just) == [],
      "a 4-tree stage-scope with a reason for every tree is not reported")
_partial = (f"- stage-scope: `{_four}` justified: tests/parser — Stage 1 edits it; "
            "tests/storage — Stage 1 imports it; tests/api — Stage 2 changes the port"
            "\n- plan-scope: `uv run pytest`\n")
_pw = vgc.wide_stage_scopes(_partial)
check(len(_pw) == 1 and "tests/render" in _pw[0][2],
      "a justification missing one tree is reported, naming that tree")
# A tree written `tests/parser/` or `./tests/parser` in the clause is the same tree the
# command names.
_slash = _just.replace("justified: tests/parser — ", "justified: tests/parser/ — ").replace(
    "tests/storage — Stage 1", "./tests/storage — Stage 1")
check(vgc.wide_stage_scopes(_slash) == [],
      "a justified tree with a trailing slash or leading ./ matches the command's tree")
# A reason containing a dash, and the clause on a wrapped line.
_dash = _just.replace("Stage 1 edits it", "Stage 1 edits it - the parser")
check(vgc.wide_stage_scopes(_dash) == [], "a reason containing a dash still justifies its tree")
_wrapped = (f"- stage-scope: `{_four}`\n  justified: tests/parser — Stage 1 edits it; "
            "tests/storage — Stage 1 imports it;\n  tests/api — Stage 2 changes the "
            "port; tests/render — Stage 2 adds a layer\n- plan-scope: `uv run pytest`\n")
check(vgc.wide_stage_scopes(_wrapped) == [], "a justified: clause on wrapped lines is read")
_empty_reason = _just.replace("tests/render — Stage 2 adds a layer", "tests/render —")
check(len(vgc.wide_stage_scopes(_empty_reason)) == 1,
      "a tree listed with an empty reason is not justified")
check(vgc.wide_stage_scopes("- stage-scope: `uv run pytest tests/parser tests/storage "
                            "tests/api -q`\n- plan-scope: `x`\n") == [],
      "a 3-tree stage-scope is untouched (the threshold is still 4)")
check(run(tiered_plan(_four))[0] == 0,
      "STAGE-SCOPE-WIDE stays advisory — measured hits are not all defects")
check(re.search(r"measured\s+2026-10-06\s+over\s+the\s+\d+\s+plans\s+in\s+one\s+owner's\s+records\s+homes"
                r"\s+that\s+declare\s+stage-scope:\s+\d+\s+hit", vgc.__doc__) is not None,
      "the docstring states the measured trigger rate and why the finding is advisory")

print("group 10 — PROSE-BLIND-SWEEP: a negated recursive grep that cannot go green")

def gated(check):
    return "## Stage 1\n\n### Stage 1 Gate\n" + check + "\n"

# Four bare-word absence sweeps. Each one fails on any comment or docstring that names the
# words, defect or not.
for pat, target in [
        ("Payment failed\\|Card declined", "src/shop | grep -v 'adapters/web/'"),
        ("sync-now\\|sync-later", "src/shop | grep -v routes.py"),
        ('"redis"', "src/shop/core/"),
        ("Undo checkout\\|Can.t undo", "src/shop/core/")]:
    c = f"- [ ] `! grep -rn '{pat}' {target}`"
    check(len(vgc.prose_blind_sweeps(gated(c))) == 1,
          f"flagged: bare-word absence sweep for {pat[:28]!r}")

# A sibling sweep carrying `=` is anchored to syntax, so a comment is unlikely to reproduce
# it — flagging it would be a false positive on a check that can go green.
check(not vgc.prose_blind_sweeps(gated("- [ ] `! grep -rn 'RETRY_LIMIT = 3' src/`")),
      "not flagged: pattern carries code structure (`=`)")

# A negated grep over one .md file with a regex class and an anchor.
check(not vgc.prose_blind_sweeps(gated(
          "- [ ] `! grep -qE '^## FIX-1[0-9] ' docs/notes/known-issues.md`")),
      "not flagged: non-recursive, single artifact, anchored regex")

check(not vgc.prose_blind_sweeps(gated("- [ ] `! grep -rn 'Card declined' src/ | grep -v '^\\s*#'`")),
      "not flagged: the pipeline already excludes comments")
check(not vgc.prose_blind_sweeps(gated("- [ ] **(judgment)** `! grep -rn 'Card declined' src/`")),
      "not flagged: (judgment) exempt, as on the selector axis")
check(not vgc.prose_blind_sweeps(gated("- [ ] **(scoped)** `! grep -rn 'Card declined' src/`")),
      "not flagged: (scoped) exempt, as on the selector axis")
check(not vgc.prose_blind_sweeps(gated("- [ ] `grep -rn 'Card declined' src/` returns 3")),
      "not flagged: a positive grep is a different and weaker problem")
check(not vgc.prose_blind_sweeps(gated("- [ ] `! grep -n 'Card declined' src/one.py`")),
      "not flagged: not recursive and names one file")

# Excluding a DIRECTORY is not excluding comments — a directory filter leaves every comment
# inside the swept tree.
check(len(vgc.prose_blind_sweeps(gated(
          "- [ ] `! grep -rn 'Card declined' src/ | grep -v 'adapters/'`"))) == 1,
      "still flagged: a directory exclusion does not make grep prose-aware")

_rc, _out = run(gated("- [ ] `! grep -rn 'Card declined' src/shop/`"))
# ADVISORY, and this is the assertion that pins it. The identical syntax is correct for a
# secret or TODO scan (`! grep -rn 'sk-ant-' .`), where matching a comment is the point,
# and nothing syntactic separates that from the defect — so this must never move an exit
# code. Measured over a corpus of 682 real plans: 203 instances across 110.
check(_rc == 0, "a plan carrying one still exits 0 — advisory, never a failure")
check("prose-blind-sweep" in _out.lower(), "reported under its own name, on its own axis")
check("assert it as values in a test" in _out, "the message names the repair, not just the defect")
check("not for you" in _out, "the message concedes the legitimate twin rather than assuming the defect")
check(not vgc.prose_blind_sweeps(gated("- [ ] `! grep -rn 'sk-ant-' src/ | grep -v '^\\s*#'`")),
      "a secret scan that already strips comments is not flagged")
_n = vgc.prose_blind_sweeps(gated("- [ ] `! grep -rn 'Card declined' src/`"))
check(_n and _n[0][2] == "Card declined", "the message names the offending alternative")

print("group 9 — every class is exercised by a synthetic plan built for it")
# One synthetic plan carries every class at a known count — unconditional, so it runs
# wherever the suite runs, CI included, and a missing file is a failure rather than a skip.
# A corpus of owner plans stays outside the repo; scripts/corpus-regress.py re-checks one
# there.
EVERY = SHAPES / "every-class-plan.md"
check(EVERY.is_file(), f"the synthetic plan is present ({EVERY.name})")
import collections
shaped = collections.Counter()
checks9 = vgc.gate_checks(EVERY.read_text(encoding="utf-8")) if EVERY.is_file() else []
for c in checks9:
    shaped[vgc.classify(c)[0]] += 1
for label, n in (("EXECUTABLE", 4), ("JUDGMENT", 2), ("SCOPED", 1),
                 ("INSTANCE-SHAPED", 2), ("PROSE", 3)):
    # Every class must be represented, or the plan silently stops testing that branch.
    check(shaped[label] == n, f"every-class-plan.md exercises the {label} branch "
                              f"{n} time(s) (got {shaped[label]})")
# The docstring's "command plus set-quantified claim" branch (measured three times in the
# corpus): plural language lets a narrow command pass, and the command alone does not.
plural = [c for c in checks9 if "no stray copies remain" in c]
check(len(plural) == 1 and kind(plural[0]) == "EXECUTABLE",
      "every-class-plan.md: a narrow command plus a set-quantified claim is EXECUTABLE")
check(bool(plural) and kind(plural[0].split(" and ")[0]) == "INSTANCE-SHAPED",
      "and the same narrow command alone is INSTANCE-SHAPED")
# Read the figures from the calibration sentence only: "3 INSTANCE-SHAPED" also appears in
# the next sentence about those checks, so a whole-docstring match stays green with the
# calibration figure itself changed. The figures describe a corpus this suite cannot read,
# so what is pinned here is that they are stated, name their corpus, and add up.
_calm = re.search(r"Calibrated against.*?\bPROSE\.", " ".join(vgc.__doc__.split()))
doc = _calm.group(0) if _calm else ""
check(bool(doc), "the docstring's calibration sentence is present")
_tot = re.search(r"Calibrated against (\d+) gate checks in a corpus of \d+ plans", doc)
_fig = re.search(r"(\d+) EXECUTABLE, (\d+) JUDGMENT, (\d+) INSTANCE-SHAPED, (\d+) PROSE\.$", doc)
check(bool(_tot and _fig) and sum(map(int, _fig.groups())) == int(_tot.group(1)),
      "the calibration sentence names its corpus, and its four class figures add up "
      "to its stated total")
check("every-class-plan.md" in vgc.__doc__,
      "the docstring names the synthetic plan that pins the branches in the repo")

print("group 10b — the script compiles with no warning")
# A stray escape such as `\|` in the docstring raises SyntaxWarning on every run of a
# validator the authoring checklist tells every author to run.
_cw = subprocess.run([sys.executable, "-W", "error", "-c",
                      "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')", SCRIPT],
                     capture_output=True, text=True)
check(_cw.returncode == 0, f"compiles under -W error ({_cw.stderr.strip()[-80:]})")

print("group 11 — GOAL-CHECK-MISSING: a plan or master entry with no (goal) check")
# Every gate can pass while the plan's goal is never swept over the whole artifact, so a plan
# needs at least one (goal) check. A note, never an exit code, so a legacy plan is unaffected.
GOAL = pathlib.Path(HERE) / "fixtures" / "goal-check"
_missing = (GOAL / "missing-plan.md").read_text()
_present = (GOAL / "present-plan.md").read_text()
_master = (GOAL / "master-missing-plan.md").read_text()
check(vgc.goal_check_missing(_missing) == ["plan"],
      "a Standard plan with no (goal) check in any gate is reported once")
check(vgc.goal_check_missing(_present) == [],
      "a Standard plan carrying a (goal) check is not reported")
check(vgc.goal_check_missing(_master, GOAL / "master-missing-plan.md") == ["Sub-plan 2"],
      "a master entry whose **Gate:** block has no (goal) check is reported, by entry")
check(kind("**(goal)** `grep -q 'Triggers' skills/one/SKILL.md`") == "INSTANCE-SHAPED",
      "(goal) is orthogonal to shape: an instance-shaped goal check is still flagged")
check(kind("**(goal)** `! grep -L 'Triggers' skills/*/SKILL.md | grep -q .`") == "EXECUTABLE",
      "a (goal) sweep classifies EXECUTABLE like any other sweep")
rc, out = run(_missing)
check(rc == 0 and "goal-check-missing 1 (advisory" in out,
      "the note is advisory: exit 0, counted on its own summary line")
rc, out = run(_present)
check(rc == 0 and "goal-check-missing" not in out, "a plan with a (goal) check prints no note")
_r = subprocess.run([sys.executable, SCRIPT, str(GOAL / "master-missing-plan.md")],
                    capture_output=True, text=True)
check("Sub-plan 2's **Gate:** block has no check marked (goal)" in _r.stdout,
      "the master-entry note reads as a sentence, naming the entry")
check(re.search(r"goal-check-missing: measured 2026-10-08 over \d+ plans in one owner's records homes: \d+ hits",
                " ".join(vgc.__doc__.split())) is not None,
      "the docstring states the measured trigger rate")

print("group 12 — FILTERED-SUBSET: a sweep restricted by a category filter")
# The shape: an awk field filter such as `$2 ~ /beta/` keeps one category of a table's rows,
# so the sweep reads that category only while the other rows need the property too. Read as
# a plural sweep, it passes silently.
_filtered = (GOAL / "filtered-plan.md").read_text()
_scoped_f = (GOAL / "scoped-filtered-plan.md").read_text()
_fs = vgc.filtered_subsets(_filtered)
_noted = [c for c, _cmd, _f in _fs]
check(any("$2 ~ /beta/" in c for c in _noted) and
      any(f == "$2 ~ /beta/" for _c, _cmd, f in _fs),
      "an awk field-filtered sweep is noted, naming its filter")
check(any("grep -v '^docs/archive/'" in c for c in _noted),
      "a grep filtering an enumerating command's output is noted")
check(not any("grep -rL" in c for c in _noted), "an unfiltered sweep is not noted")
check(not any("check-rollout.py | grep -q" in c for c in _noted),
      "grep -q over a program's output is an assertion, not a filtered set")
check(len(_fs) == 2, f"exactly the two filtered sweeps are noted ({len(_fs)})")
check(vgc.filtered_subsets(_scoped_f) == [],
      "(scoped) silences it: the author states the subset is the whole set")
# False-positive shapes, each one measured in a plan corpus.
check(not vgc.filtered_subsets(plan("`! git ls-files | grep -E '\\.orig$|\\.rej$'` — no merge leftover is tracked")),
      "a positive grep as the LAST stage is the check's predicate, not a narrowed set")
check(not vgc.filtered_subsets(plan("`! grep -rn 'old_api(' $(git ls-files) | grep -v 'CHANGELOG'` — no old_api call is left")),
      "a grep over grep's RESULTS filters matches, not members of the set")
check(not vgc.filtered_subsets(plan("`find docs -name '*.md' | xargs grep -c x | grep -v ':0$'` — every doc")),
      "a grep after a stage that changes what the rows are (xargs) filters results")
check(not vgc.filtered_subsets(plan("`find docs -name '*.md' | grep . | wc -l` — every doc counted")),
      "an anchors-only pattern names no category")
check(len(vgc.filtered_subsets(plan(
      "`test -z \"$(git ls-files docs/ | grep -v '^docs/old/' | xargs grep -L x)\"` — every doc"))) == 1,
      "a double-quoted $(...) does not hide the pipes inside it")
check(len(vgc.filtered_subsets(plan(
      "`for f in $(ls tests/*.py | grep -E 'unit|fast'); do python3 $f || exit 1; done` — all pass"))) == 1,
      "a positive grep narrowing what a loop iterates is a filter, and `a|b` stays one pattern")
# The two exemptions above have no enumerator before them, so they would pass with the
# exemption deleted. These carry one, so each exemption is load-bearing.
check(not vgc.filtered_subsets(plan("`x=$(git ls-files | grep -q scratch) || true; test -z \"$x\"` — every file")),
      "grep -q after an enumerator, in a non-final stage, is an assertion, not a filter")
check(not vgc.filtered_subsets(plan("`git ls-files | grep scratch | wc -l` prints 0 — no scratch file is tracked")),
      "a positive grep followed only by a counting stage is still the check's predicate")
check(len(vgc.filtered_subsets(plan("`git ls-files | grep -v '^old/' | wc -l` prints 0 — every file"))) == 1,
      "a grep -v before a counting stage still excludes members")
check(len(vgc.filtered_subsets(plan(
      "`comm -23 <(git ls-files | grep -E '/docs/' | sort) <(ls pub)` is empty — every doc is published"))) == 1,
      "a positive grep inside a process substitution narrows the set the outer command reads")
check(len(vgc.filtered_subsets(plan("`git ls-files | grep -v '\\.$' | xargs wc -l` — every file"))) == 1,
      "an escaped literal (`\\.$`) is a real filter, not an anchors-only pattern")
check(vgc._pipe_stages('x "$(a | b)" | c "d|e"') == ['x "$(a ', ' b)" ', ' c "d|e"'],
      "the closing quote of a \"$(...)\" span is not read as an opening one")
check(len(vgc.filtered_subsets(plan(
      "`test -z \"$(git ls-files src | sed \"s|src/||\" | grep -v '^vendor/' | sort -u)\"` — every file"))) == 1,
      "a quoted sed pattern nested inside \"$(...)\" does not hide the filter after it")
_mm = """# Master Plan: x

## Sub-plans

### Sub-plan 1: A
- **Status:** [ ]
- **Goal:** every route has a schema.

**Gate:**
- [ ] `python3 docs/verify.py` exits 0

## Master gate

**Gate:**
- [ ] **(goal)** `python3 docs/verify.py --all` exits 0 — every route in every service
"""
check(vgc.goal_check_missing(_mm, "x-master-plan.md") == ["Sub-plan 1"],
      "a (goal) check after the register does not mask the last entry's missing one")
rc, out = run(_filtered)
check(rc == 0 and "filtered-subset 2 (advisory" in out,
      "the note is advisory: exit 0, counted on its own summary line")
check(re.search(r"filtered-subset: measured 2026-10-08 over the same \d+ plans: \d+ hits",
                " ".join(vgc.__doc__.split())) is not None
      and re.search(r"sampled \d+ hits?: \d+ true positives?", " ".join(vgc.__doc__.split())),
      "the docstring states the measured rate and a sampled true-positive count")

print()
if FAILURES:
    print(f"FAILED — {len(FAILURES)} check(s):")
    for f in FAILURES:
        print(f"  {f}")
    sys.exit(1)
print("OK — validate-gate-checks.py classifies every branch, honors the (judgment) "
      "opt-out, refuses an empty sweep, and holds its measured precision")
