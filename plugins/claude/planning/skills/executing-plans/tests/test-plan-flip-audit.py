#!/usr/bin/env python3
"""Fixture suite for plan-flip-audit.py — run directly (repo convention):

    python3 core/skills/executing-plans/tests/test-plan-flip-audit.py

WHAT THIS SUITE IS REALLY GUARDING. Each finding this audit implements names a
way a gate goes green over work that has not happened. The fixtures below are
those shapes, each built to isolate one rule. If a fixture stops firing, a plan
of that shape passes the gate unseen.

The second thing it guards is the COVERAGE CLAIM. Findings 2 and 4 read the file
on disk; findings 1, 3 and 5 read git history, and a plans folder outside any repo
has no history to read. Answering "no findings" there would be a clean bill over
checks that never ran — the very failure the audit detects, made by the detector.
So the half that did not run must be reported, and these tests pin that report —
its two lists, its stderr banner AND its exit code — as hard as the findings.

MUTATION-GRADED. A negative fixture can miss for some cause other than the guard
it names, and then the suite stays green with that guard deleted. So every
negative case below states the mutation it catches: weaken a rule in the script
and a named test here goes red.
"""
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "plan-flip-audit.py"

passed = failed = 0
_tmpdirs = []


def ok(msg):
    global passed
    passed += 1
    print(f"  ok    {msg}")


def bad(msg, detail=""):
    global failed
    failed += 1
    print(f"  FAIL  {msg}")
    if detail:
        for line in str(detail).splitlines():
            print(f"        | {line}")
    if os.environ.get("SUITE_FAIL_FAST") == "1":   # the battery needs only the first FAIL
        for d_ in _tmpdirs:
            shutil.rmtree(d_, ignore_errors=True)
        sys.exit(1)


def run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd,
    )


def run_json(*args, cwd=None):
    r = run(*args, "--json", cwd=cwd)
    try:
        return r, json.loads(r.stdout)
    except json.JSONDecodeError as e:
        bad(f"--json did not emit parseable JSON ({' '.join(args)})",
            f"{e}\nstdout: {r.stdout[:400]}\nstderr: {r.stderr[:400]}")
        return r, None


def findings_of(doc, n):
    return [f for f in doc.get("findings", []) if f.get("finding") == n]


def newrepo(label):
    d = Path(tempfile.mkdtemp(prefix=f"flipaudit-{label}-"))
    _tmpdirs.append(d)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    # `--template=` (empty) skips any git template directory, and core.hooksPath
    # skips a global hooks dir. A template may install a pre-commit hook that
    # edits .gitignore and aborts the first commit; a fixture repo made the plain
    # way would then fail to commit, and the suite would go red over the machine's
    # git setup instead of the script under test.
    subprocess.run(["git", "init", "-q", "-b", "main", "--template=", str(d)],
                   check=True, env=env)
    subprocess.run(["git", "-C", str(d), "config", "core.hooksPath", "/dev/null"],
                   check=True, env=env)
    return d, env


def commit(repo, env, msg):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True, env=env)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          env=env, capture_output=True, text=True).stdout.strip()


def newdir(label):
    d = Path(tempfile.mkdtemp(prefix=f"flipaudit-{label}-"))
    _tmpdirs.append(d)
    return d


# ---------------------------------------------------------------- fixtures
# A plan body with N unticked boxes, parameterised so a "bulk flip" commit can
# tick them all at once. Deliberately carries NO finding-2 vocabulary, so a hit
# here is unambiguously finding 1.
def sub_plan(ticked=False):
    box = "[x]" if ticked else "[ ]"
    lines = [
        "# Project Plan: rig calibration",
        "",
        "## Stage 1: calibration",
        "",
        "### Task 1.1: sensor sweep",
        "- **Status:** [x]",
        "",
        "**Gate:**",
    ]
    for i in range(1, 22):
        lines.append(f"- {box} `make test-panel-calib-{i:02d}` passes.")
    return "\n".join(lines) + "\n"


# A gate box ticked with the amendment that voids it.
GATE_AMENDED = (
    "# Project Plan: fan controls\n"
    "\n"
    "## Stage 3: fan curve\n"
    "\n"
    "**Gate:**\n"
    # Control line: must stay clean of EVERY vocabulary word, so the assertion
    # "only the amended line fires" pins the rule rather than the fixture.
    "- [x] `make test-panel-fan-all` walks every fan widget through its presets.\n"
    "- [x] `make hil-panel-fan` spins the rig fan back up after a forced stall. "
    "*(amended: rig PSU tripped, exit 2, no board left to rerun on)*\n"
)

# A Preflight access line with NO finding-2 vocabulary, so a hit is
# unambiguously finding 3.
def preflight_plan(ticked=False):
    box = "[x]" if ticked else "[ ]"
    return (
        "# Project Plan: thermal logger\n"
        "\n"
        "## Preflight\n"
        "\n"
        f"- {box} Device access: the test rig at 192.0.2.10 is reachable over SSH "
        "and the owner credentials are valid.\n"
        "- [x] Bench supply reads 12.0 V on the panel meter.\n"
        "\n"
        "## Stage 1: logger\n"
        "\n"
        "### Task 1.1: logger\n"
        "- **Status:** [x]\n"
    )


# A (judgment) gate box, for finding 5.
def judgment_plan(ticked=False):
    box = "[x]" if ticked else "[ ]"
    return (
        "# Project Plan: sensor bus\n"
        "\n"
        "## Stage 1: bus\n"
        "\n"
        "**Gate:**\n"
        "- [x] `make test-panel-bus-all` passes.\n"
        f"- {box} **(judgment)** Each bus register has one owning widget, as the bus note asks.\n"
    )


# A master whose **Completed:** line stands over gate boxes that carry the
# amendment vocabulary.
MASTER_COMPLETED = (
    "# Master Plan: rig control panel\n"
    "\n"
    "## Sub-plans\n"
    "\n"
    "| # | Plan | Status |\n"
    "|---|---|---|\n"
    "| 1 | sub-01-sensor-bus-plan.md | [x] |\n"
    "| 6 | sub-06-field-trial-plan.md | [x] |\n"
    "\n"
    "**Gate:**\n"
    "- [x] `make panel-soak` keeps every widget responsive through the soak. "
    "*(amended: cold-start leg skipped, warm leg only)*\n"
    "- [x] `make hil-panel-burn` writes the dial firmware to the rig and reads it back. "
    "*(amended: burner never ran, no hardware on the bench that week)*\n"
    "\n"
    "**Completed:** 2026-01-16 — six sub-plans closed; dial firmware burn signed off.\n"
)

# A master whose own file is clean, but whose LINKED sub-plan carries the
# amendment vocabulary — finding 4 must follow the link.
MASTER_CLEAN_LINKING_DIRTY = (
    "# Master Plan: field trial\n"
    "\n"
    "## Sub-plans\n"
    "\n"
    "| # | Plan | Status |\n"
    "|---|---|---|\n"
    "| 6 | [sub-06](2026-01-09-sub-06-field-trial-plan.md) | [x] |\n"
    "\n"
    "**Completed:** 2026-01-16 — all sub-plans green.\n"
)

CLEAN_PLAN = (
    "# Project Plan: bench harness\n"
    "\n"
    "## Stage 1: harness\n"
    "\n"
    "### Task 1.1: widget harness\n"
    "- **Status:** [x]\n"
    "\n"
    "### Task 1.2: bench fixtures\n"
    "- **Status:** [x]\n"
    "\n"
    "**Gate:**\n"
    "- [x] `make test-harness` passes.\n"
    "- [x] `make hil-harness` proves the live path against the lab rig.\n"
)


print("plan-flip-audit.py — fixture suite")
print()

if not SCRIPT.exists():
    bad(f"script not found: {SCRIPT}")
    print()
    print(f"passed {passed}, failed {failed}")
    sys.exit(1)

# ------------------------------------------------------- finding 1: bulk flip
print("finding 1 — many boxes ticked by one commit that has no task commits behind it")
repo, env = newrepo("f1")
plan = repo / "sub-05.md"
plan.write_text(sub_plan(ticked=False))
base = commit(repo, env, "Sub-plan 5 authored")
plan.write_text(sub_plan(ticked=True))
commit(repo, env, "Sub-plan 5 green")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    hits = findings_of(doc, 1)
    if hits:
        ok(f"21-box bulk flip in one commit flagged ({len(hits)} finding)")
    else:
        bad("bulk flip NOT flagged", json.dumps(doc, indent=2)[:600])
    if r.returncode == 1:
        ok("exit 1 on a finding")
    else:
        bad(f"expected exit 1, got {r.returncode}", r.stderr[:400])

# The same flips spread across real per-task commits must NOT fire.
repo2, env2 = newrepo("f1-neg")
plan2 = repo2 / "sub-05.md"
plan2.write_text(sub_plan(ticked=False))
base2 = commit(repo2, env2, "Sub-plan 5 authored")
body = sub_plan(ticked=False).splitlines(keepends=True)
for i, idx in enumerate([i for i, l in enumerate(body) if l.startswith("- [ ]")]):
    body[idx] = body[idx].replace("- [ ]", "- [x]")
    plan2.write_text("".join(body))
    (repo2 / f"work-{i}.txt").write_text("real work\n")
    commit(repo2, env2, f"Stage 1 Task 1.{i + 1}: calibration check {i + 1}")
r2, doc2 = run_json(str(plan2), "--since", base2, cwd=repo2)
if doc2 is not None:
    if not findings_of(doc2, 1):
        ok("same flips spread across per-task commits not flagged")
    else:
        bad("finding 1 fired on an honest per-task history",
            json.dumps(findings_of(doc2, 1), indent=2)[:600])

# ------------------------------------------------- finding 2: amended tick
print()
print("finding 2 — a ticked box carrying the vocabulary that voids it")
d = newdir("f2")
p = d / "sub-03.md"
p.write_text(GATE_AMENDED)
r, doc = run_json(str(p))
if doc is not None:
    hits = findings_of(doc, 2)
    if len(hits) == 1 and "hil-panel-fan" in hits[0].get("text", ""):
        ok("`[x] ... *(amended: rig PSU tripped, exit 2, …)*` flagged, and only that line")
    else:
        bad("finding 2 wrong", json.dumps(doc, indent=2)[:800])
    if hits and isinstance(hits[0].get("line"), int) and hits[0]["line"] > 0:
        ok(f"finding carries a line number ({hits[0]['line']})")
    else:
        bad("finding 2 has no usable line number", json.dumps(hits, indent=2)[:400])
    if r.returncode == 1:
        ok("exit 1 on a finding")
    else:
        bad(f"expected exit 1, got {r.returncode}", r.stderr[:400])

# STRONG phrases void a tick alone: each says outright the work did not happen.
for vocab in ["soft residual", "BLOCKED", "not automated", "no device",
              "no hardware", "not run", "without hardware", "Not done: the reset"]:
    dd = newdir("f2v")
    pp = dd / "p.md"
    pp.write_text(f"# Plan\n\n**Gate:**\n- [x] `make hil-thing` proves it. *({vocab})*\n")
    _, dv = run_json(str(pp))
    hits = findings_of(dv, 2) if dv else []
    if hits and hits[0].get("severity") == "blocking":
        ok(f"strong phrase '{vocab}' voids the tick alone (blocking)")
    else:
        bad(f"strong phrase '{vocab}' NOT flagged blocking",
            json.dumps(hits, indent=2)[:300])

# A gate line is a claim about this gate; a finding quoted from another tool goes
# on the line after it (stage-gate.md § A gate line is a claim about this gate).
# The scan reads the checkbox line only, so the quote below is data, and neither
# the box nor a **Completed:** line over it is voided by it.
dd = newdir("f2next")
pp = dd / "p.md"
pp.write_text("# Plan\n\n**Completed:** 2026-01-01\n\n**Gate:**\n"
              "- [x] `make check` passes\n"
              "  the linter printed `BLOCKED` and BLOCKED; residual work is still open;"
              " soft residual, no device\n")
r, dv = run_json(str(pp))
if dv is not None and not findings_of(dv, 2) and not findings_of(dv, 4) and r.returncode == 0:
    ok("a finding quoted on the line after a ticked box is not read as a claim about that gate")
else:
    bad("a quote on the line after a ticked box voided it (red if the scan reads past "
        "the checkbox line)", json.dumps(dv, indent=2)[:400] if dv else r.stderr[:400])
pp.write_text("# Plan\n\n**Gate:**\n- [x] `make check` passes BLOCKED\n")
_, dv = run_json(str(pp))
hits = findings_of(dv, 2) if dv else []
if hits and hits[0].get("severity") == "blocking":
    ok("the same word on the checkbox line itself still voids the tick (blocking)")
else:
    bad("BLOCKED on the checkbox line itself was not flagged", json.dumps(hits, indent=2)[:300])
# An unindented line straight after the box is not off it: markdown runs it into the
# box's own text, so it is scanned as part of the box, and so is the Completed over it.
pp.write_text("# Plan\n\n**Completed:** 2026-01-01\n\n**Gate:**\n"
              "- [x] `make check` passes\nwaived by me, exit 2\n")
_, dv = run_json(str(pp))
hits = findings_of(dv, 2) if dv else []
if hits and hits[0].get("severity") == "blocking" and findings_of(dv, 4):
    ok("an unindented line run into the box is scanned with it (blocking), Completed included")
else:
    bad("an unindented continuation of a ticked box went unscanned",
        json.dumps(dv, indent=2)[:400] if dv else "")

# WEAK qualifiers do NOT void a tick alone. `amended` shows why: executing-plans
# tells the executor to write it whenever a check changes, so firing on it alone
# would punish the disclosure itself.
# A weak qualifier in RUNNING PROSE is not an amendment at all and must stay
# silent — this carve-out keeps the false-positive rate down. (A lone qualifier
# inside an undisclosed amendment parenthetical IS a finding; that is pinned
# separately in the lone-qualifier block below.)
for vocab in ["amended", "partial", "skipped", "deferred", "manual",
              "blocked", "unreachable", "residual"]:
    dd = newdir("f2w")
    pp = dd / "p.md"
    pp.write_text(f"# Plan\n\n**Gate:**\n"
                  f"- [x] the {vocab} path is exercised by the corpus suite.\n")
    _, dv = run_json(str(pp))
    if dv is not None and not findings_of(dv, 2):
        ok(f"'{vocab}' in prose does NOT void a tick")
    else:
        bad(f"'{vocab}' fired from prose — the main false-positive source is back",
            json.dumps(findings_of(dv, 2), indent=2)[:300] if dv else "")

# ...but two weak qualifiers together do, as advisory.
# Two WEAK qualifiers -> advisory. (Pairs containing a strong term are blocking
# and are pinned just below.)
for combo in ["skipped the suite, deferred to a bench",
              "amended — partial run", "manual step, blocked on review"]:
    dd = newdir("f2p")
    pp = dd / "p.md"
    pp.write_text(f"# Plan\n\n**Gate:**\n- [x] `make hil-thing` proves it. *({combo})*\n")
    _, dv = run_json(str(pp))
    hits = findings_of(dv, 2) if dv else []
    if hits and hits[0].get("severity") == "advisory":
        ok(f"two weak qualifiers ('{combo}') void as advisory")
    else:
        bad(f"weak pair '{combo}' did not fire as advisory",
            json.dumps(hits, indent=2)[:300])

for combo in ["amended, exit 2 on rerun", "amended, simulated only", "amended, no board fitted"]:
    dd = newdir("f2s")
    pp = dd / "p.md"
    pp.write_text(f"# Plan\n\n**Gate:**\n- [x] `make hil-thing` proves it. *({combo})*\n")
    _, dv = run_json(str(pp))
    hits = findings_of(dv, 2) if dv else []
    if hits and hits[0].get("severity") == "blocking":
        ok(f"a pair containing a strong term ('{combo}') is BLOCKING")
    else:
        bad(f"'{combo}' should be blocking — a strong term voids the tick outright",
            json.dumps(hits, indent=2)[:300])

# The sanctioned amendment protocol -- the form this repo's own rules mandate --
# must stay silent: the amendment carries its was-value.
d_amend = newdir("f2amend")
p_amend = d_amend / "p.md"
p_amend.write_text(
    "# Plan\n\n**Gate:**\n"
    "- [x] `make lint-widgets` exits 0 on the dial and gauge widgets. "
    "*(amended once the gauge widget was renamed — was: `make lint-gauge`)*\n")
_, dv = run_json(str(p_amend))
if dv is not None and not findings_of(dv, 2):
    ok("a sanctioned amendment carrying its was-value is not a finding")
else:
    bad("the amendment protocol itself fires — the main false-positive source",
        json.dumps(findings_of(dv, 2), indent=2)[:400] if dv else "")

# An UNticked box carrying the same words is honest bookkeeping, not a finding.
d = newdir("f2-neg")
p = d / "p.md"
p.write_text("# Plan\n\n**Gate:**\n- [ ] `make hil-thing` — BLOCKED, no board.\n")
_, doc = run_json(str(p))
if doc is not None and not findings_of(doc, 2):
    ok("an UNticked box carrying the same words is not a finding")
else:
    bad("finding 2 fired on an unticked box — that is honest bookkeeping")

# ------------------------------------------- finding 3: access line, no probe
print()
print("finding 3 — a Preflight access/device box flipped with no probe output in the commit")
repo, env = newrepo("f3")
plan = repo / "sub-04.md"
plan.write_text(preflight_plan(ticked=False))
base = commit(repo, env, "Sub-plan 4 authored")
plan.write_text(preflight_plan(ticked=True))
commit(repo, env, "Preflight green")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if findings_of(doc, 3):
        ok("access line flipped with no probe artefact flagged")
    else:
        bad("finding 3 NOT flagged", json.dumps(doc, indent=2)[:600])

repo, env = newrepo("f3-neg")
plan = repo / "sub-04.md"
plan.write_text(preflight_plan(ticked=False))
base = commit(repo, env, "Sub-plan 4 authored")
plan.write_text(preflight_plan(ticked=True))
(repo / "docs").mkdir()
(repo / "docs" / "evidence").mkdir()
(repo / "docs" / "evidence" / "probe-rig.txt").write_text(
    "ssh 192.0.2.10: serial TR-0042\n")
commit(repo, env, "Preflight green — rig probed")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if not findings_of(doc, 3):
        ok("same flip WITH a probe artefact in the commit is not flagged")
    else:
        bad("finding 3 fired despite a probe artefact",
            json.dumps(findings_of(doc, 3), indent=2)[:600])

# ------------------------------------------------- finding 4: Completed over BLOCKED
print()
print("finding 4 — **Completed:** standing over gate boxes that match finding 2")
d = newdir("f4")
p = d / "master.md"
p.write_text(MASTER_COMPLETED)
r, doc = run_json(str(p))
if doc is not None:
    if findings_of(doc, 4):
        ok("**Completed:** over amended gate boxes flagged")
    else:
        bad("finding 4 NOT flagged", json.dumps(doc, indent=2)[:800])
    if findings_of(doc, 2):
        ok("the underlying finding-2 rows are reported too, not swallowed by finding 4")
    else:
        bad("finding 2 rows missing from a file that has them")
    if r.returncode == 1:
        ok("exit 1 on a finding")
    else:
        bad(f"expected exit 1, got {r.returncode}")

# finding 4 must follow a link into a sub-plan.
d = newdir("f4-link")
(d / "master.md").write_text(MASTER_CLEAN_LINKING_DIRTY)
(d / "2026-01-09-sub-06-field-trial-plan.md").write_text(GATE_AMENDED)
_, doc = run_json(str(d / "master.md"))
if doc is not None:
    if findings_of(doc, 4):
        ok("finding 4 follows the register link into a dirty sub-plan")
    else:
        bad("finding 4 did not follow the sub-plan link",
            json.dumps(doc, indent=2)[:800])

# A **Completed:** over clean gates is not a finding.
d = newdir("f4-neg")
p = d / "clean.md"
p.write_text(CLEAN_PLAN + "\n**Completed:** 2026-01-18 — commits: abc1234\n")
r, doc = run_json(str(p))
if doc is not None:
    if not findings_of(doc, 4):
        ok("**Completed:** over clean gates is not a finding")
    else:
        bad("finding 4 fired on a clean plan",
            json.dumps(findings_of(doc, 4), indent=2)[:600])

# --------------------------------------- finding 5: judgment box, no evaluator
print()
print("finding 5 — a (judgment) box flipped with no evaluator/reviewer artefact")
repo, env = newrepo("f5")
plan = repo / "sub-01.md"
plan.write_text(judgment_plan(ticked=False))
base = commit(repo, env, "Sub-plan 1 authored")
plan.write_text(judgment_plan(ticked=True))
commit(repo, env, "Stage 1 green")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if findings_of(doc, 5):
        ok("(judgment) box flipped with no evaluator reference flagged")
    else:
        bad("finding 5 NOT flagged", json.dumps(doc, indent=2)[:600])

repo, env = newrepo("f5-neg")
plan = repo / "sub-01.md"
plan.write_text(judgment_plan(ticked=False))
base = commit(repo, env, "Sub-plan 1 authored")
plan.write_text(judgment_plan(ticked=True))
commit(repo, env,
       "Stage 1 green\n\nevaluator: independent subagent, judgment pass — PASS")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if not findings_of(doc, 5):
        ok("same flip with an evaluator line in the commit message is not flagged")
    else:
        bad("finding 5 fired despite an evaluator reference",
            json.dumps(findings_of(doc, 5), indent=2)[:600])

# --------------------------------------------------- clean history -> exit 0
print()
print("clean per-task history -> exit 0")
repo, env = newrepo("clean")
plan = repo / "sub-01.md"
plan.write_text(CLEAN_PLAN.replace("- [x]", "- [ ]"))
base = commit(repo, env, "Sub-plan 1 authored")
txt = plan.read_text().replace("- [ ]", "- [x]")
plan.write_text(txt)
(repo / "runner.sh").write_text("#!/usr/bin/env bash\nssh rig true\n")
commit(repo, env, "Stage 1 Task 1.1: widget harness")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if not doc.get("findings"):
        ok("clean per-task history produces no findings")
    else:
        bad("clean history produced findings",
            json.dumps(doc["findings"], indent=2)[:800])
    if r.returncode == 0:
        ok("exit 0 when clean")
    else:
        bad(f"expected exit 0, got {r.returncode}", r.stderr[:400])

# ------------------------------------------- coverage disclosure (honest-gates)
print()
print("coverage disclosure — the half that cannot run must say so, never read as clean")
d = newdir("nogit")
p = d / "master.md"
p.write_text(CLEAN_PLAN)
r, doc = run_json(str(p))
if doc is not None:
    not_run = {c["finding"] for c in doc.get("checks_not_run", [])}
    run_ = set(doc.get("checks_run", []))
    if not_run == {1, 3, 5, 8, 9, 10, 11}:
        ok("outside a git repo, findings 1/3/5/11 (and 8-10: no --repo) are reported NOT RUN")
    else:
        bad(f"checks_not_run was {sorted(not_run)}, expected [1, 3, 5, 8, 9, 10, 11]",
            json.dumps(doc, indent=2)[:600])
    if run_ == {2, 4, 6, 7}:
        ok("findings 2/4/6/7 (the on-disk checks) are reported as actually run")
    else:
        bad(f"checks_run was {sorted(run_)}, expected [2, 4, 6, 7]")
    if all(c.get("reason") for c in doc.get("checks_not_run", [])):
        ok("every not-run check carries a reason")
    else:
        bad("a not-run check has no reason", json.dumps(doc, indent=2)[:600])
    if "NOT RUN" in r.stderr or "not run" in r.stderr.lower():
        ok("the not-run banner reaches stderr, where a caller cannot drop it silently")
    else:
        bad("no not-run banner on stderr", f"stderr: {r.stderr[:400]}")

# In a git repo with a resolvable range, all five must report as run.
repo, env = newrepo("cover")
plan = repo / "p.md"
plan.write_text(CLEAN_PLAN.replace("- [x]", "- [ ]"))
base = commit(repo, env, "authored")
(repo / "x.txt").write_text("x\n")
plan.write_text(CLEAN_PLAN)          # the range must actually TOUCH the plan
commit(repo, env, "Stage 1 Task 1.1: work")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if set(doc.get("checks_run", [])) == {1, 2, 3, 4, 5, 6, 7}:
        ok("inside a git repo all seven checks report as run")
    else:
        bad(f"checks_run was {sorted(doc.get('checks_run', []))}, expected all seven",
            json.dumps(doc, indent=2)[:600])
    if doc.get("commits_examined") == 1 and doc.get("since_note"):
        ok("the audited range and commit count are disclosed")
    else:
        bad("range/commits_examined not disclosed", json.dumps(doc, indent=2)[:400])

# A range that touches the plan in NO commit examined nothing — reporting 5/5
# there is a clean bill over checks that never ran (the tool's own failure mode).
repo, env = newrepo("cover-empty")
plan = repo / "p.md"
plan.write_text(CLEAN_PLAN)
base = commit(repo, env, "authored")
(repo / "x.txt").write_text("x\n")
commit(repo, env, "Stage 1 Task 1.1: unrelated work")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    nr = {c["finding"] for c in doc.get("checks_not_run", [])}
    if nr == {1, 3, 5, 8, 9, 10} and doc.get("commits_examined") == 0:
        ok("a zero-commit range is NOT reported as five checks run")
    else:
        bad("zero-commit range claimed coverage it never had",
            json.dumps(doc, indent=2)[:600])

# --------------------------------------------------------------- CLI contract
print()
print("CLI contract")
r = run("/nonexistent/plan.md")
if r.returncode == 2:
    ok("missing plan file exits 2 (usage/IO), never 0")
else:
    bad(f"missing file exited {r.returncode}, expected 2", r.stderr[:300])

d = newdir("text")
p = d / "p.md"
p.write_text(GATE_AMENDED)
r = run(str(p))
if r.returncode == 1 and "hil-panel-fan" in r.stdout and ":" in r.stdout:
    ok("text output names the offending line")
else:
    bad("text output does not name the offending line",
        f"rc={r.returncode}\n{r.stdout[:400]}")

repo, env = newrepo("badrev")
plan = repo / "p.md"
plan.write_text(CLEAN_PLAN)
commit(repo, env, "authored")
r, doc = run_json(str(plan), "--since", "deadbeefdeadbeef", cwd=repo)
if doc is not None:
    nr = {c["finding"] for c in doc.get("checks_not_run", [])}
    if nr == {1, 3, 5, 8, 9, 10} and r.returncode == 0:
        ok("an unresolvable --since degrades to the static half rather than crashing")
    else:
        bad(f"unresolvable --since: rc={r.returncode}, not_run={sorted(nr)}",
            r.stderr[:400])


# ===================================================================
# Regression cases. Each pins one false negative. The heading names the
# mutation it catches.
# ===================================================================

print()
print("a box ticked AND re-worded in the same commit is still a flip")
repo, env = newrepo("c1")
plan = repo / "p.md"
plan.write_text(preflight_plan(ticked=False))
base = commit(repo, env, "authored")
# tick it and append an amendment in one edit — the usual fake, and a shape that
# exact-text diff pairing cannot match.
plan.write_text(preflight_plan(ticked=True).replace(
    "credentials are valid.", "credentials are valid. (verified 2026-01-12)"))
commit(repo, env, "Preflight green")
r, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None:
    if findings_of(doc, 3):
        ok("tick + same-commit text edit still detected")
    else:
        bad("REGRESSION: text-edited flip invisible", json.dumps(doc, indent=2)[:600])

print()
print("an UNTRACKED plan must never report history checks as run")
repo, env = newrepo("c2")
(repo / "seed.txt").write_text("x\n")
commit(repo, env, "Stage 1 green")
(repo / "seed2.txt").write_text("y\n")
commit(repo, env, "Stage 2 green")
untracked = repo / "untracked.md"
untracked.write_text(preflight_plan(ticked=True))
r, doc = run_json(str(untracked), cwd=repo)
if doc is not None:
    nr = {c["finding"] for c in doc.get("checks_not_run", [])}
    if nr == {1, 3, 5, 8, 9, 10, 11}:
        ok("untracked plan reports 1/3/5/11 NOT RUN despite the repo having history")
    else:
        bad("REGRESSION: untracked plan given a clean bill over checks that never ran",
            json.dumps(doc, indent=2)[:600])
    if "not tracked" in (doc.get("checks_not_run") or [{}])[0].get("reason", ""):
        ok("the reason names the actual cause (untracked), not 'not a git repo'")
    else:
        bad("the untracked plan's not-run reason is misleading",
            json.dumps(doc.get("checks_not_run"), indent=2)[:400])

print()
print("the two done-marker shapes plans use")
d = newdir("c3")
p1 = d / "status.md"
p1.write_text("# Plan\n\n### Task 1.1: thing\n"
              "- **Status:** [x] done (amended once the bench died: exit 2 with no board)\n")
_, doc = run_json(str(p1))
if doc is not None and findings_of(doc, 2):
    ok("`- **Status:** [x]` void tick detected")
else:
    bad("REGRESSION: **Status:** marker invisible",
        json.dumps(doc, indent=2)[:500] if doc else "")

d = newdir("c3b")
p2 = d / "reg.md"
p2.write_text("# Master Plan: x\n\n## Sub-plans\n\n"
              "| # | Plan | Status |\n|---|---|---|\n"
              "| 6 | sub-06 | [x] |\n\n"
              "**Gate:**\n- [x] `make hil` proves it. *(BLOCKED — no board)*\n")
_, doc = run_json(str(p2))
if doc is not None and findings_of(doc, 4):
    ok("master-register table tick over a void gate line detected")
else:
    bad("REGRESSION: table-cell register tick invisible",
        json.dumps(doc, indent=2)[:600] if doc else "")

print()
print("the three bulk-flip bypasses")
# (a) split the flip across four commits of six
repo, env = newrepo("c4a")
plan = repo / "p.md"
body = sub_plan(ticked=False).splitlines(keepends=True)
plan.write_text("".join(body))
base = commit(repo, env, "authored")
idxs = [i for i, l in enumerate(body) if l.startswith("- [ ]")]
for chunk in range(0, len(idxs), 6):
    for i in idxs[chunk:chunk + 6]:
        body[i] = body[i].replace("- [ ]", "- [x]")
    plan.write_text("".join(body))
    commit(repo, env, f"progress {chunk}")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("split flip (4 commits x 6) caught by the aggregate rule")
else:
    bad("REGRESSION: splitting the flip defeats the rule",
        json.dumps(doc, indent=2)[:600] if doc else "")

# (b) game the subject line: many "Task N.M" tokens in ONE commit
repo, env = newrepo("c4b")
plan = repo / "p.md"
plan.write_text(sub_plan(ticked=False))
base = commit(repo, env, "authored")
plan.write_text(sub_plan(ticked=True))
commit(repo, env, "Task 1.1 Task 1.2 Task 1.3 Task 1.4 Task 1.5 Task 1.6: all green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("many Task tokens in one subject counts as ONE task commit")
else:
    bad("REGRESSION: subject stuffing disables the rule",
        json.dumps(doc, indent=2)[:600] if doc else "")

# (d) a commit naming several tasks earns one credit per task with full proof
# records; with a record for only one task, its many ticks still fire finding 1.
PCD = SCRIPT.parent / "prove-claim.py"


def multi_task_world(label, proven, two_claims=False, deviate=()):
    repo, env = newrepo(label)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_calc.py").write_text(
        "import sys\nsys.path.insert(0, '.')\nfrom calc import add\nassert add(2, 3) == 5\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    blocks = "".join(
        f"### Task 1.{i}: t{i}\n- **Status:** {{st}}\n- `add` returns the sum.\n"
        f"- **Test:** `python3 tests/test_calc.py` — add returns the sum (red if add subtracts)"
        f"{'; add is commutative (red if add ignores b)' if two_claims else ''}\n\n"
        for i in range(1, 8))
    plan = repo / "p.md"
    plan.write_text("# Plan\n\n## Stage 1\n\n" + blocks.replace("{st}", "[ ]"))
    base = commit(repo, env, "authored")
    plan.write_text("# Plan\n\n## Stage 1\n\n" + blocks.replace("{st}", "[x]"))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    f = repo / "calc.py"
    orig = f.read_text()
    f.write_text(orig.replace("a + b", "a - b"))
    d = subprocess.run(["git", "-C", str(repo), "diff", "--", "calc.py"],
                       capture_output=True, text=True).stdout
    f.write_text(orig)
    # In a directory of our own: repo.parent is the shared temp root, where a fixed
    # name collides between concurrent suite runs.
    brk = newdir(f"{label}-brk") / "break.patch"
    brk.write_text(d)
    for i in proven:
        r = subprocess.run([sys.executable, str(PCD), "claim", "--repo", str(repo), "--plan",
                            str(plan), "--task", f"1.{i}", "--claim", "1", "--break", str(brk),
                            "--test", "python3 tests/test_calc.py", "--no-build-step",
                            "python, no build"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    for i in deviate:
        r = subprocess.run([sys.executable, str(PCD), "deviation", "--repo", str(repo), "--plan",
                            str(plan), "--task", f"1.{i}", "--claim", "1", "--why",
                            "the evidence lives outside the repo"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    commit(repo, env, " ".join(f"Task 1.{i}" for i in range(1, 8)) + ": all green")
    return repo, plan, base


repo, plan, base = multi_task_world("c4d", range(1, 8))
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and not findings_of(doc, 1):
    ok("seven proven tasks landing in one commit earn seven credits: no finding 1")
else:
    bad("each proven task earns its own credit (red when a commit is credited once whatever it holds)",
        json.dumps(doc, indent=2)[:600] if doc else "")
repo, plan, base = multi_task_world("c4e", [1])
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("with only one of seven tasks proven, the commit still fires finding 1")
else:
    bad("partial records leave subject stuffing caught (red when a task id alone earns credit)",
        json.dumps(doc, indent=2)[:600] if doc else "")

# Catches: one record crediting a task. Seven tasks with TWO required claims each
# (both name their break), only the first proven: no task is fully proven, so the commit counts once.
repo, plan, base = multi_task_world("c4f", range(1, 8), two_claims=True)
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("half-proven tasks (claim 1 of 2) earn no credit")
else:
    bad("a task earns credit only with all its claims proven (red when a single record is enough)",
        json.dumps(doc, indent=2)[:600] if doc else "")

# Catches: a claim deviation credited as proof. Seven tasks, each required claim
# recorded as a deviation (prove-claim.py deviation --claim): disclosed, never proven,
# so the commit still counts once.
repo, plan, base = multi_task_world("c4g", [], deviate=range(1, 8))
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("tasks whose claims are recorded as deviations earn no finding-1 credit")
else:
    bad("a claim deviation must earn no credit (red if a deviation counts as proof)",
        json.dumps(doc, indent=2)[:600] if doc else "")

# (c) duplicate box texts must not collapse
repo, env = newrepo("c4c")
plan = repo / "p.md"
dup_unticked = "# Plan\n\n**Gate:**\n" + "- [ ] `make test` passes.\n" * 21
dup_ticked = "# Plan\n\n**Gate:**\n" + "- [x] `make test` passes.\n" * 21
plan.write_text(dup_unticked)
base = commit(repo, env, "authored")
plan.write_text(dup_ticked)
commit(repo, env, "green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("21 identically-worded boxes count as 21, not 1")
else:
    bad("REGRESSION: duplicate texts collapse and hide the bulk flip",
        json.dumps(doc, indent=2)[:600] if doc else "")

print()
print("bulk-flip guard — pins the `task_commits < threshold` clause")
def bulk_with_task_commits(n_task_commits):
    repo, env = newrepo(f"guard{n_task_commits}")
    plan = repo / "p.md"
    plan.write_text(sub_plan(ticked=False))
    base = commit(repo, env, "authored")
    for i in range(n_task_commits):
        (repo / f"w{i}.txt").write_text("work\n")
        commit(repo, env, f"Stage 1 Task 1.{i + 1}: real work")
    plan.write_text(sub_plan(ticked=True))
    commit(repo, env, "gate green")
    _, dd = run_json(str(plan), "--since", base, cwd=repo)
    return dd

dd = bulk_with_task_commits(6)
if dd is not None and not findings_of(dd, 1):
    ok("21 flips WITH 6 task commits behind them: not flagged")
else:
    bad("guard: honest history flagged as a bulk flip",
        json.dumps(findings_of(dd, 1), indent=2)[:500] if dd else "")
dd = bulk_with_task_commits(5)
if dd is not None and findings_of(dd, 1):
    ok("21 flips with only 5 task commits: flagged (the clause is load-bearing)")
else:
    bad("guard MUTATION SURVIVES: deleting `task_commits < threshold` "
        "would not be caught", json.dumps(dd, indent=2)[:500] if dd else "")

print()
print("a box APPENDED already ticked is examined, not skipped")
repo, env = newrepo("i1")
plan = repo / "p.md"
plan.write_text("# Plan\n\n## Preflight\n\n- [x] Bench supply reads 12.0 V.\n")
base = commit(repo, env, "authored")
plan.write_text("# Plan\n\n## Preflight\n\n- [x] Bench supply reads 12.0 V.\n"
                "- [x] Device access: the test rig is reachable over SSH.\n")
commit(repo, env, "Preflight green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 3):
    ok("appended-already-ticked access box detected")
else:
    bad("REGRESSION: appending a ticked box bypasses finding 3",
        json.dumps(doc, indent=2)[:600] if doc else "")

print()
print("the evidence gates are not one-token bypasses")
repo, env = newrepo("i2a")
plan = repo / "p.md"
plan.write_text(preflight_plan(ticked=False))
base = commit(repo, env, "authored")
plan.write_text(preflight_plan(ticked=True))
(repo / "security-history.jsonl").write_text('{"x":1}\n')
commit(repo, env, "Preflight green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 3):
    ok("an unrelated .jsonl does not launder a flip")
else:
    bad("REGRESSION: any .jsonl suppresses finding 3",
        json.dumps(doc, indent=2)[:600] if doc else "")

repo, env = newrepo("i2b")
plan = repo / "p.md"
plan.write_text(judgment_plan(ticked=False))
base = commit(repo, env, "authored")
plan.write_text(judgment_plan(ticked=True))
commit(repo, env, "Stage 1 green\n\npeer review: none needed")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 5):
    ok("'peer review: none needed' does not satisfy the evaluator requirement")
else:
    bad("REGRESSION: a bare 'review:' word suppresses finding 5",
        json.dumps(doc, indent=2)[:600] if doc else "")

print()
print("a non-UTF-8 plan must not crash into exit 1")
repo, env = newrepo("i3")
plan = repo / "p.md"
plan.write_bytes(b"# Plan\n\n**Gate:**\n- [x] caf\xe9 gate. *(amended)*\n")
commit(repo, env, "authored")
r = run(str(plan), cwd=repo)
if r.returncode in (0, 1, 4) and "Traceback" not in r.stderr:
    ok(f"non-UTF-8 plan handled cleanly (exit {r.returncode}, no traceback)")
else:
    bad("REGRESSION: decode path crashes",
        f"rc={r.returncode}\n{r.stderr[:500]}")

print()
print("--require-all-checks turns partial coverage into a distinct exit code")
d = newdir("i4")
p = d / "clean.md"
p.write_text(CLEAN_PLAN)
r = run(str(p))
if r.returncode == 0:
    ok("without the flag, partial coverage still exits 0 (the documented default)")
else:
    bad(f"expected exit 0 without the flag, got {r.returncode}")
r = run(str(p), "--require-all-checks")
if r.returncode == 3:
    ok("with the flag, partial coverage exits 3 — distinct from clean AND from findings")
else:
    bad(f"expected exit 3 with --require-all-checks, got {r.returncode}", r.stderr[:300])
# findings still win over the coverage code
d = newdir("i4b")
p = d / "dirty.md"
p.write_text(GATE_AMENDED)
r = run(str(p), "--require-all-checks")
if r.returncode == 1:
    ok("a real finding still exits 1, not 3")
else:
    bad(f"expected exit 1, got {r.returncode}")

print()
print("vocabulary breadth and --vocab-file")
# Each weak qualifier still VOIDS when paired with a second signal: the tiers
# decide when a word fires, and every word stays in the vocabulary.
for vocab in ["partial", "skipped", "deferred", "waived", "simulated",
              "mocked", "stubbed", "exit code 2"]:
    dd = newdir("i6")
    pp = dd / "p.md"
    pp.write_text(f"# Plan\n\n**Gate:**\n- [x] `make hil` proves it. *({vocab} — amended)*\n")
    _, dv = run_json(str(pp))
    if dv is not None and findings_of(dv, 2):
        ok(f"'{vocab}' still voids a tick when paired")
    else:
        bad(f"'{vocab}' does not void even when paired — it left the vocabulary",
            json.dumps(dv, indent=2)[:300] if dv else "")

d = newdir("i6f")
vf = d / "vocab.txt"
vf.write_text("# custom\nfrobnicated\n")
pp = d / "p.md"
pp.write_text("# Plan\n\n**Gate:**\n- [x] `make hil` proves it. *(frobnicated)*\n"
              "- [x] `make other` proves it. *(amended)*\n")
# EXTEND is the default: adding one project word must not silently disable the
# other 20. A replacing default would be a fail-open reached by using the
# feature as documented.
# Extra patterns join the WEAK tier, so a bare project keyword still needs a
# co-signal — otherwise --vocab-file would reintroduce the single-word FP class.
pp.write_text("# Plan\n\n**Gate:**\n"
              "- [x] `make hil` proves it. *(frobnicated)*\n"
              "- [x] `make two` proves it. *(frobnicated — exit 2)*\n"
              "- [x] `make three` proves it. *(no hardware)*\n")
_, dv = run_json(str(pp), "--vocab-file", str(vf))
lines = {f["line"] for f in findings_of(dv, 2)} if dv else set()
sev = {f["line"]: f.get("severity") for f in findings_of(dv, 2)} if dv else {}
if lines == {4, 5, 6} and sev.get(4) == "advisory" and sev.get(6) == "blocking":
    ok("--vocab-file joins the WEAK tier (lone custom term advisory, built-ins intact)")
else:
    bad(f"--vocab-file extension wrong: lines {sorted(lines)} sev {sev}",
        json.dumps(dv, indent=2)[:500] if dv else "")

_, dv = run_json(str(pp), "--vocab-file", str(vf), "--vocab-replace")
lines = {f["line"] for f in findings_of(dv, 2)} if dv else set()
if lines == {4, 5} and 6 not in lines:
    ok("--vocab-replace makes the custom list STRONG and drops the built-ins")
else:
    bad(f"--vocab-replace wrong: fired on lines {sorted(lines)}, expected 4 and 5",
        json.dumps(dv, indent=2)[:500] if dv else "")

print()
print("CLI guards")
d = newdir("thr")
p = d / "p.md"
p.write_text(CLEAN_PLAN)
r = run(str(p), "--flip-threshold", "0")
if r.returncode == 2:
    ok("--flip-threshold 0 is rejected (it would silently disable check 1)")
else:
    bad(f"--flip-threshold 0 exited {r.returncode}, expected 2", r.stderr[:300])

d = newdir("contain")
sub = d / "inner"
sub.mkdir()
(sub / "master.md").write_text(
    "# Master Plan: x\n\n## Sub-plans\n\n| 1 | [out](../outside.md) | [x] |\n"
    "\n**Completed:** 2026-01-16 — done.\n")
(d / "outside.md").write_text("# Plan\n- [x] `make hil`. *(BLOCKED — no board)*\n")
_, doc = run_json(str(sub / "master.md"))
if doc is not None and not findings_of(doc, 4):
    ok("a `../outside.md` link is not followed out of the plan's subtree")
else:
    bad("containment: link traversal escaped the plan directory",
        json.dumps(doc, indent=2)[:500] if doc else "")



# ===================================================================
# Renames, empty task commits, decode paths, honest prose and tables.
# Each case pins a guard that a mutation could delete while the suite
# stayed green — and a suite that stays green while a guard is deleted
# is not evidence.
# ===================================================================

print()
print("a renamed plan file must not fabricate a bulk flip")
repo, env = newrepo("i2rename")
plan = repo / "old-plan.md"
plan.write_text(sub_plan(ticked=True))
base = commit(repo, env, "authored, already green")
subprocess.run(["git", "mv", "old-plan.md", "new-plan.md"], cwd=repo, check=True, env=env)
commit(repo, env, "rename the plan")
_, doc = run_json(str(repo / "new-plan.md"), "--since", base, cwd=repo)
if doc is not None and not findings_of(doc, 1):
    ok("git mv of an already-ticked plan produces no bulk-flip finding")
else:
    bad("REGRESSION: a rename fabricates a bulk flip",
        json.dumps(findings_of(doc, 1), indent=2)[:500] if doc else "")

print()
print("a task commit must contain WORK, not just a subject line")
def bulk_with_empty_task_commits(mode):
    repo, env = newrepo(f"i3{mode}")
    plan = repo / "p.md"
    plan.write_text(sub_plan(ticked=False))
    base = commit(repo, env, "authored")
    for i in range(6):
        if mode == "empty":
            subprocess.run(["git", "commit", "-q", "--allow-empty",
                            "-m", f"Task 1.{i + 1}: work"], cwd=repo, check=True, env=env)
        else:                       # touches ONLY the plan file
            plan.write_text(sub_plan(ticked=False) + f"\n<!-- {i} -->\n")
            commit(repo, env, f"Task 1.{i + 1}: work")
    plan.write_text(sub_plan(ticked=True))
    commit(repo, env, "gate green")
    _, dd = run_json(str(plan), "--since", base, cwd=repo)
    return dd

for mode, label in (("empty", "six --allow-empty commits"),
                    ("planonly", "six commits touching only the plan")):
    dd = bulk_with_empty_task_commits(mode)
    if dd is not None and findings_of(dd, 1):
        ok(f"{label} titled 'Task 1.N' do NOT buy a pass")
    else:
        bad(f"REGRESSION: {label} defeat the bulk-flip rule",
            json.dumps(dd, indent=2)[:500] if dd else "")

print()
print("two load-bearing guards that a mutation could delete unseen")
# (a) Counter-not-set: a parent with ONE pre-ticked duplicate must not mask the
# other 20. With `set`, prev contains the shared key and every flip vanishes.
repo, env = newrepo("i1counter")
plan = repo / "p.md"
dup = "- [ ] `make test` passes.\n"
plan.write_text("# Plan\n\n**Gate:**\n" + "- [x] `make test` passes.\n" + dup * 20)
base = commit(repo, env, "authored with one already ticked")
plan.write_text("# Plan\n\n**Gate:**\n" + "- [x] `make test` passes.\n" * 21)
commit(repo, env, "green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
if doc is not None and findings_of(doc, 1):
    ok("one pre-ticked duplicate does not mask the other 20 (Counter, not set)")
else:
    bad("REGRESSION: the Counter guard is unpinned — `set` would pass this",
        json.dumps(doc, indent=2)[:500] if doc else "")

# (b) the git decode path: a non-UTF-8 plan across TWO commits, so file_at() and
# therefore git(errors="replace") is actually exercised. The single-commit
# fixture above never reaches it.
repo, env = newrepo("i1decode")
plan = repo / "p.md"
plan.write_bytes(b"# Plan\n\n**Gate:**\n- [ ] caf\xe9 gate.\n")
base = commit(repo, env, "authored")
plan.write_bytes(b"# Plan\n\n**Gate:**\n- [x] caf\xe9 gate. *(amended)*\n")
commit(repo, env, "green")
r = run(str(plan), "--since", base, cwd=repo)
if r.returncode in (0, 1, 4) and "Traceback" not in r.stderr:
    ok(f"non-UTF-8 plan across two commits: no crash (exit {r.returncode})")
else:
    bad("REGRESSION: git decode path crashes — errors='replace' is unpinned",
        f"rc={r.returncode}\n{r.stderr[:400]}")

print()
print("the vocabulary does not fire on honest evidence prose")
d = newdir("i4fp")
p_ = d / "honest.md"
p_.write_text(
    "# Project Plan: honest\n\n**Gate:**\n"
    "- [x] `make test-panel` — `318 passed, 9 skipped in 41.07s` on the rig image.\n"
    "- [x] Fixture and budget suites both exit 0.\n"
    "- [x] `! grep -rn 'BLOCKED\\|soft residual' panel/Makefile` prints nothing.\n"
    "- [x] Each of the 17 widget sources builds to a non-empty object file.\n"
    "- [x] The second-pass review raised no Critical finding; the panel gate is not blocked.\n"
    "- [x] **(judgment)** The dial widget rewrite is whole, not partial.\n")
r, doc = run_json(str(p_))
if doc is not None:
    n = len(findings_of(doc, 2))
    if n == 0:
        ok("six honest evidence lines produce zero findings")
    else:
        bad(f"REGRESSION: {n} false positive(s) on honest prose",
            json.dumps(findings_of(doc, 2), indent=2)[:800])

# ...while every genuinely void tick still fires, unquoted.
d = newdir("i4tp")
p_ = d / "void.md"
p_.write_text("# Plan\n\n**Gate:**\n"
              "- [x] make hil-panel-fan spins the fan back up. *(amended: rig PSU tripped, exit 2, no board left to rerun on)*\n"
              "- [x] make test-panel-burnin holds for the full burn-in. *(soft residual)*\n")
_, doc = run_json(str(p_))
if doc is not None and len(findings_of(doc, 2)) == 2:
    ok("the true positives still fire — the prose carve-out does not blunt the rule")
else:
    bad("the prose carve-out went too far: a genuine void tick stopped firing",
        json.dumps(doc, indent=2)[:600] if doc else "")

print()
print("ordinary markdown tables are not scanned as checkboxes")
d = newdir("i7")
p_ = d / "risk.md"
p_.write_text("# Plan\n\n## Risks\n\n"
              "| Risk | Mitigated | Residual |\n|---|---|---|\n"
              "| supply chain | [x] | N/A |\n"
              "| flash wear | [x] | partial, tracked in backlog |\n")
_, doc = run_json(str(p_))
if doc is not None and not findings_of(doc, 2):
    ok("a risk table with [x] cells and 'N/A'/'partial' text is not a finding")
else:
    bad("REGRESSION: ordinary tables scanned as checkboxes",
        json.dumps(findings_of(doc, 2), indent=2)[:500] if doc else "")



# ===================================================================
# Severity and the two-signal rule. Every finding's severity is pinned,
# and every pre-filter is reachable from its own fixture; an unpinned
# severity or an unreachable filter lets a mutation survive a green run.
# Each case below names the mutation it kills.
# ===================================================================

print()
print("severity — pinned for every finding, not just finding 2 (M7-M11)")

# M9: finding 1's severity flipped to advisory.
repo, env = newrepo("sev1")
plan = repo / "p.md"
plan.write_text(sub_plan(ticked=False))
base = commit(repo, env, "authored")
plan.write_text(sub_plan(ticked=True))
commit(repo, env, "green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
f1 = findings_of(doc, 1) if doc else []
if f1 and all(f.get("severity") == "blocking" for f in f1):
    ok("finding 1 (bulk flip) is blocking")
else:
    bad("M9 SURVIVES: finding 1 severity unpinned", json.dumps(f1, indent=2)[:300])

# M10: finding 3.
repo, env = newrepo("sev3")
plan = repo / "p.md"
plan.write_text(preflight_plan(ticked=False))
base = commit(repo, env, "authored")
plan.write_text(preflight_plan(ticked=True))
commit(repo, env, "Preflight green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
f3 = findings_of(doc, 3) if doc else []
if f3 and all(f.get("severity") == "blocking" for f in f3):
    ok("finding 3 (device box, no probe) is blocking")
else:
    bad("M10 SURVIVES: finding 3 severity unpinned", json.dumps(f3, indent=2)[:300])

# M11: finding 5.
repo, env = newrepo("sev5")
plan = repo / "p.md"
plan.write_text(judgment_plan(ticked=False))
base = commit(repo, env, "authored")
plan.write_text(judgment_plan(ticked=True))
commit(repo, env, "Stage 1 green")
_, doc = run_json(str(plan), "--since", base, cwd=repo)
f5 = findings_of(doc, 5) if doc else []
if f5 and all(f.get("severity") == "blocking" for f in f5):
    ok("finding 5 (judgment box, no evaluator) is blocking")
else:
    bad("M11 SURVIVES: finding 5 severity unpinned", json.dumps(f5, indent=2)[:300])

# M7/M8: finding 4 must INHERIT from its evidence, both directions. M7 (always
# advisory) would downgrade a false **Completed:** over a void gate to a note.
d = newdir("sev4b")
(d / "m.md").write_text(
    "# Master Plan: x\n\n**Gate:**\n"
    "- [x] `make hil` proves it. *(no board)*\n"
    "\n**Completed:** 2026-01-16 — green.\n")
_, doc = run_json(str(d / "m.md"))
f4 = findings_of(doc, 4) if doc else []
if f4 and f4[0].get("severity") == "blocking":
    ok("finding 4 inherits BLOCKING from a blocking gate line (kills M7)")
else:
    bad("M7 SURVIVES: **Completed:** over a blocking gate line is not blocking",
        json.dumps(f4, indent=2)[:300])

d = newdir("sev4a")
(d / "m.md").write_text(
    "# Master Plan: x\n\n**Gate:**\n"
    "- [x] `make hil` proves it. *(amended — skipped the bench step)*\n"
    "\n**Completed:** 2026-01-16 — green.\n")
_, doc = run_json(str(d / "m.md"))
f4 = findings_of(doc, 4) if doc else []
if f4 and f4[0].get("severity") == "advisory":
    ok("finding 4 inherits ADVISORY when every gate line is advisory (kills M8)")
else:
    bad("M8 SURVIVES: finding 4 ignores its evidence's severity",
        json.dumps(f4, indent=2)[:300])

print()
print("the exit code carries the severity (a caller gates on $?)")
d = newdir("rc4")
(d / "adv.md").write_text("# P\n\n**Gate:**\n"
                          "- [x] `make x` proves it. *(amended — skipped a step)*\n")
r = run(str(d / "adv.md"))
if r.returncode == 4:
    ok("advisory-only exits 4 — distinct from a RED gate")
else:
    bad(f"advisory-only exited {r.returncode}, expected 4", r.stdout[:200])
(d / "blk.md").write_text("# P\n\n**Gate:**\n- [x] `make x` proves it. *(no board)*\n")
r = run(str(d / "blk.md"))
if r.returncode == 1:
    ok("a blocking finding still exits 1")
else:
    bad(f"blocking exited {r.returncode}, expected 1")

print()
print("the pre-filters must stay reachable (M14/M15) and the words distinct (M3)")
# Two weak terms where one is NEGATED: without the negation guard this fires.
d = newdir("negf")
(d / "p.md").write_text("# P\n\n**Gate:**\n"
    "- [x] The amended step is complete, not partial.\n")
_, doc = run_json(str(d / "p.md"))
if doc is not None and not findings_of(doc, 2):
    ok("negated second term keeps a two-term line silent (kills M14)")
else:
    bad("M14 SURVIVES: the NEGATED guard is unreachable from its fixture",
        json.dumps(findings_of(doc, 2), indent=2)[:300] if doc else "")

# Two weak terms where one is COUNTED.
d = newdir("cntf")
(d / "p.md").write_text("# P\n\n**Gate:**\n"
    "- [x] `make test-panel` — 318 passed, 9 skipped — under the amended runner. *(per §4)*\n")
_, doc = run_json(str(d / "p.md"))
if doc is not None and not findings_of(doc, 2):
    ok("counted second term keeps a two-term line silent (kills M15)")
else:
    bad("M15 SURVIVES: the COUNTED guard is unreachable from its fixture",
        json.dumps(findings_of(doc, 2), indent=2)[:300] if doc else "")

# M3: the same word twice is one signal, not two.
d = newdir("dupw")
(d / "p.md").write_text("# P\n\n**Gate:**\n"
    "- [x] `make x` proves it. *(deferred pending a deferred bench slot — per §4, was: none)*\n")
_, doc = run_json(str(d / "p.md"))
if doc is not None and not findings_of(doc, 2):
    ok("the same qualifier twice is one signal, not two (kills M3)")
else:
    bad("M3 SURVIVES: duplicate words counted as independent signals",
        json.dumps(findings_of(doc, 2), indent=2)[:300] if doc else "")

print()
print("a lone qualifier in an undisclosed amendment is never SILENT")
for term in ["amended", "stubbed", "mocked", "waived", "exit 78", "exit 2"]:
    dd = newdir("lone")
    pp = dd / "p.md"
    pp.write_text(f"# P\n\n**Gate:**\n- [x] `make hil` proves the board. *({term})*\n")
    r, dv = run_json(str(pp))
    hits = findings_of(dv, 2) if dv else []
    if hits:
        ok(f"lone '{term}' in an undisclosed amendment is a finding "
           f"({hits[0].get('severity')})")
    else:
        bad(f"REGRESSION: lone '{term}' in an undisclosed amendment is silent")

# ...but a lone qualifier that DISCLOSES stays silent, and so does one in prose.
d = newdir("lonok")
(d / "p.md").write_text("# P\n\n**Gate:**\n"
    "- [x] `make lint-dials` exits 0. *(amended per §2.3 when the dial set grew — was: `make lint-dial`)*\n"
    "- [x] every dial renders under the amended theme file.\n"
    "- [x] Manual calibration values survive a panel reboot unchanged.\n")
_, doc = run_json(str(d / "p.md"))
if doc is not None and not findings_of(doc, 2):
    ok("a disclosed amendment, and the word in prose, stay silent")
else:
    bad("the disclosure escape hatch or the prose carve-out broke",
        json.dumps(findings_of(doc, 2), indent=2)[:400] if doc else "")

print()
print("the two-signal rule, isolated from the lone-parenthetical rule")
# Two weak terms in PROSE — no amendment parenthetical, so the lone-qualifier
# rule cannot reach it and only the >=2 threshold can. Without this the two
# rules mask each other: a mutation raising the threshold to 3 stays green
# when every two-term fixture also sits inside a parenthetical.
d = newdir("two")
(d / "p.md").write_text("# P\n\n**Gate:**\n"
                        "- [x] The skipped step was deferred to a bench slot.\n")
_, doc = run_json(str(d / "p.md"))
hits = findings_of(doc, 2) if doc else []
if hits and hits[0].get("severity") == "advisory":
    ok("two weak terms in prose fire via the >=2 rule alone")
else:
    bad("the >=2 threshold is unpinned — it is masked by the parenthetical rule",
        json.dumps(hits, indent=2)[:300])
# ...and one weak term in prose must still be silent, which is the other half.
(d / "q.md").write_text("# P\n\n**Gate:**\n"
                        "- [x] The skipped step is covered by the corpus suite.\n")
_, doc = run_json(str(d / "q.md"))
if doc is not None and not findings_of(doc, 2):
    ok("one weak term in prose stays silent")
else:
    bad("a single prose term fired — the main false-positive source is back")

print()
print("--vocab-replace alone is rejected rather than silently ignored")
d = newdir("vr")
(d / "p.md").write_text(CLEAN_PLAN)
r = run(str(d / "p.md"), "--vocab-replace")
if r.returncode == 2:
    ok("--vocab-replace without --vocab-file exits 2")
else:
    bad(f"--vocab-replace alone exited {r.returncode}, expected 2", r.stderr[:200])


print()
print("a tool's own name is never a confession (the hyphenated -audit trap)")
# `\bstub\b` matches inside `example-stub-audit` because a hyphen is a word
# boundary. A gate report may cite an outside audit tool by name, so without
# the mask the detector flags a citation as a confession.
d = newdir("toolname")
(d / "p.md").write_text(
    "# Plan\n\n**Gate:**\n"
    "- [x] panel tree audited: example-stub-audit.py lists 0 suspect targets; "
    "plan-flip-audit reports clean; probe-device.sh is out of scope here.\n")
_r, _doc = run_json(str(d / "p.md"))
f2 = findings_of(_doc, 2)
if not f2:
    ok("a gate line citing example-stub-audit / plan-flip-audit / probe-device is silent")
else:
    bad("a gate report citing the audits by name must not be a finding",
        str(f2)[:300])

# Catches: a mask so wide it hides a confession. A bare word joined to `-audit` is
# prose, not a tool name: only a name with its script extension is masked.
d = newdir("toolname-wide")
(d / "p.md").write_text("# Plan\n\n**Gate:**\n- [x] hw: mocked-device-audit passed.\n")
_r, _doc = run_json(str(d / "p.md"))
if findings_of(_doc, 2):
    ok("a confession word joined to -audit without an extension is still a finding")
else:
    bad("`mocked-device-audit passed` must stay finding 2 (red if any *-audit word is masked)",
        json.dumps(_doc)[:300])

# The guard must not blind the real word. `stubbed` on its own still fires.
d = newdir("toolname-neg")
(d / "p.md").write_text(
    "# Plan\n\n**Gate:**\n"
    "- [x] hil-panel verified *(stubbed \u2014 no hardware)*\n")
_r, _doc = run_json(str(d / "p.md"))
if findings_of(_doc, 2):
    ok("the mask does not blind a genuine 'stubbed' confession")
else:
    bad("masking tool names must not suppress a real stub confession")


# ------------------------------------------------- finding 6: owner attestation
# An executor can tick "Owner approves the fan-curve presets as …"
# with no trace of the owner ever being asked. The owner's words are the only
# evidence such a box can have, so a tick without them is the executor's say-so.
print()
print("finding 6 — an owner decision needs the owner's words")
OWNER_BOX = ("- [x] Owner approves the fan-curve presets as the shipped defaults "
             "for the rig panel — Task 2.4 notes the call")

d = newdir("owner-pos")
(d / "p.md").write_text("# Plan\n\n## Preflight\n\n" + OWNER_BOX + "\n")
r, doc = run_json(str(d / "p.md"), "--repo", str(d))
f6 = findings_of(doc, 6) if doc else []
if f6 and r.returncode == 1:
    ok("a ticked 'Owner confirms …' with no quote is finding 6, exit 1")
else:
    bad("unquoted owner decision must be a blocking finding 6",
        f"exit {r.returncode}\n{json.dumps(doc, indent=2)[:600] if doc else r.stderr}")
# Catches: severity demoted to advisory.
if f6 and all(f.get("severity") == "blocking" for f in f6):
    ok("finding 6 is blocking")
else:
    bad("finding 6 must be blocking", str(f6)[:300])

# Catches: the ATTESTED escape deleted.
d = newdir("owner-quoted")
(d / "p.md").write_text("# Plan\n\n## Preflight\n\n" + OWNER_BOX +
                        ' *(owner, 2026-01-14: "approved, ship those presets")*\n')
_r, doc = run_json(str(d / "p.md"), "--repo", str(d))
if doc is not None and not findings_of(doc, 6):
    ok("the same box carrying the owner's quoted words is silent")
else:
    bad("a quoted owner attestation must clear finding 6",
        json.dumps(doc, indent=2)[:500] if doc else "")

# Catches: action verbs ("runs", "creates") added to the decision vocabulary.
# Those boxes are proven by their own command; a quote is not their evidence.
d = newdir("owner-action")
(d / "p.md").write_text(
    "# Plan\n\n## Preflight\n\n"
    "- [x] Owner runs `sudo apt install jq`; `jq --version` prints a version\n"
    "- [x] Owner creates the GitHub repo; `git ls-remote` answers\n")
_r, doc = run_json(str(d / "p.md"), "--repo", str(d))
if doc is not None and not findings_of(doc, 6):
    ok("'owner runs …' / 'owner creates …' are actions, not decisions — silent")
else:
    bad("owner ACTIONS must not need a quote", json.dumps(doc, indent=2)[:500] if doc else "")

# Catches: the start-of-box anchor removed. Mid-sentence mentions are prose,
# and the unanchored form fires on them.
d = newdir("owner-prose")
(d / "p.md").write_text(
    "# Plan\n\n**Gate:**\n"
    "- [x] The panel never applies a setting until the user confirms the dialog\n"
    "- [x] Profiles are versioned, pending owner approval of the labels\n")
_r, doc = run_json(str(d / "p.md"), "--repo", str(d))
if doc is not None and not findings_of(doc, 6):
    ok("an owner/user verb in the middle of a box is prose — silent")
else:
    bad("finding 6 must anchor to the start of the box", json.dumps(doc, indent=2)[:500] if doc else "")

# Catches: the ticked-only guard removed. An unticked box claims nothing.
d = newdir("owner-unticked")
(d / "p.md").write_text("# Plan\n\n## Preflight\n\n" + OWNER_BOX.replace("[x]", "[ ]") + "\n")
_r, doc = run_json(str(d / "p.md"), "--repo", str(d))
if doc is not None and not findings_of(doc, 6):
    ok("an unticked owner box is silent")
else:
    bad("an unticked box must not be finding 6", json.dumps(doc, indent=2)[:400] if doc else "")

# ------------------------------------------------ finding 7: stale was-values
# A pin amended at Preflight with a proper `was:` can still survive unannotated
# elsewhere: here the Research section keeps the old value.
print()
print("finding 7 — an amended value must not survive elsewhere unannotated")
AMEND_LINE = ("- [x] Dial firmware tagged: `git tag --contains 5d6e7f8` lists `fw-dial` "
              "*(amended at Preflight — was: `1a2b3c4`; that build hung the gauge widget)*\n")
d = newdir("stale-pos")
(d / "p.md").write_text("# Plan\n\n## Research\n\nThe dial firmware builds from commit `1a2b3c4`.\n\n"
                        "## Preflight\n\n" + AMEND_LINE)
r, doc = run_json(str(d / "p.md"), "--repo", str(d))
f7 = findings_of(doc, 7) if doc else []
if len(f7) == 1 and f7[0].get("line") == 5:
    ok("the surviving 1a2b3c4 in the Research section is finding 7, and only it")
else:
    bad("expected exactly one finding 7 on line 5", json.dumps(doc, indent=2)[:700] if doc else "")
# Catches: severity promoted to blocking (exit would become 1).
if f7 and all(f.get("severity") == "advisory" for f in f7) and r.returncode == 4:
    ok("finding 7 is advisory: exit 4, a line owed in the gate report")
else:
    bad(f"finding 7 must be advisory with exit 4, got exit {r.returncode}", str(f7)[:300])

# Catches: the STALE_EXEMPT check deleted. A survivor marked historical is the
# disclosure, not the defect.
d = newdir("stale-historical")
(d / "p.md").write_text("# Plan\n\n## Research\n\nThe dial firmware was built from commit `1a2b3c4` "
                        "(historical — the pin is now 5d6e7f8).\n\n## Preflight\n\n" + AMEND_LINE)
_r, doc = run_json(str(d / "p.md"), "--repo", str(d))
if doc is not None and not findings_of(doc, 7):
    ok("a survivor marked historical is silent")
else:
    bad("a historical mention must clear finding 7", json.dumps(doc, indent=2)[:500] if doc else "")

# Catches: the DISTINCTIVE filter deleted. A was-value that is ordinary words
# legitimately recurs elsewhere in the plan.
d = newdir("stale-words")
(d / "p.md").write_text(
    "# Plan\n\nEvery gauge uses the theme: high-contrast palette.\n\n## Preflight\n\n"
    "- [x] Panel theme chosen *(amended at Preflight per theme.md — "
    "was: `theme: high-contrast`)*\n")
_r, doc = run_json(str(d / "p.md"), "--repo", str(d))
if doc is not None and not findings_of(doc, 7):
    ok("a was-value that is words, not an identifier, is not swept")
else:
    bad("only identifier-like was-values may be swept", json.dumps(doc, indent=2)[:500] if doc else "")

# ------------------------------------------- baseline: no git history for the plan
# A plan can live in a folder that is not a git repository. Without a
# baseline, findings 1/3/5 cannot run on one — and that is exactly where a
# whole Preflight can be ticked at once, unseen.
print()
print("baseline — a plan outside git is audited against its --snapshot copy")

def baseline_world(label):
    """A plans dir holding the plan, and a separate project repo."""
    plans_dir = newdir(f"{label}-plans")
    proj, env = newrepo(f"{label}-proj")
    plan = plans_dir / "plan.md"
    lines = ["# Plan", "", "## Preflight", ""]
    lines += [f"- [ ] Tool {i} installed: `tool{i} --version`" for i in range(4)]
    lines += ["", "## Stage 1", ""]
    for i in range(1, 5):
        lines += [f"### Task 1.{i}: thing {i}", "- **Status:** [ ]", ""]
    lines += ["### Stage 1 Gate", "", "- [ ] **(judgment)** reads well", ""]
    plan.write_text("\n".join(lines))
    return plans_dir, proj, env, plan

def snap(plan, proj):
    return run(str(plan), "--snapshot", "--repo", str(proj))

plans_dir, proj, env, plan = baseline_world("bl-none")
r, doc = run_json(str(plan), "--repo", str(proj))
reasons = " ".join(c.get("reason", "") for c in (doc or {}).get("checks_not_run", []))
if doc is not None and {c["finding"] for c in doc["checks_not_run"]} == {1, 3, 5, 8, 9, 10, 11} \
        and "--snapshot" in reasons:
    ok("with no baseline, 1/3/5 and 11 are NOT RUN and the reason says to --snapshot")
else:
    bad("no baseline must leave 1/3/5 not run, pointing at --snapshot",
        json.dumps(doc, indent=2)[:500] if doc else r.stderr)

# The bulk shape: snapshot, one task commit, then every Preflight
# box and every task box ticked in one edit, plus the (judgment) box.
plans_dir, proj, env, plan = baseline_world("bl-bulk")
(proj / "README").write_text("x\n"); commit(proj, env, "chore: initial commit")
r = snap(plan, proj)
if r.returncode == 0:
    ok("--snapshot exits 0 and writes the baseline")
else:
    bad(f"--snapshot failed: exit {r.returncode}", r.stderr[:300])
# Catches: the refuse-to-overwrite guard deleted.
r2 = snap(plan, proj)
if r2.returncode == 2 and "already exists" in r2.stderr:
    ok("a second --snapshot is refused (exit 2) — it would launder every flip")
else:
    bad(f"second --snapshot must exit 2, got {r2.returncode}", r2.stderr[:300])
(proj / "a.kt").write_text("x\n"); commit(proj, env, "Stage 1 Task 1.1: scaffold")
plan.write_text(plan.read_text().replace("- [ ]", "- [x]").replace("**Status:** [ ]", "**Status:** [x]"))
r, doc = run_json(str(plan), "--repo", str(proj), "--require-all-checks")
got = {f["finding"] for f in (doc or {}).get("findings", [])}
if doc is not None and {1, 3, 5} <= got and r.returncode == 1:
    ok("bulk flip, Preflight ticks with no probe, judgment with no review: 1, 3, 5 all fire")
else:
    bad(f"expected findings 1, 3, 5 and exit 1; got {sorted(got)}, exit {r.returncode}",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)
if doc is not None and set(doc.get("checks_run", [])) == set(range(1, 12)) \
        and doc.get("baseline"):
    ok("baseline mode with --repo reports all eleven checks run, and names the baseline")
else:
    bad("baseline mode must report 1-7 run", json.dumps(doc, indent=2)[:500] if doc else "")
f3 = findings_of(doc, 3) if doc else []
if len(f3) == 4:
    ok("each of the 4 Preflight ticks is its own finding 3")
else:
    bad(f"expected 4 finding-3 entries, got {len(f3)}", str(f3)[:400])

# The honest version of the same run: one task commit per task, a committed
# probe artefact, a review ledger line. Nothing fires; coverage is complete.
plans_dir, proj, env, plan = baseline_world("bl-honest")
r = snap(plan, proj)                      # no commits yet: repo_head is null
if r.returncode == 0 and "no commits yet" in r.stdout:
    ok("--snapshot works before the first commit (a fresh `git init`)")
else:
    bad("--snapshot must work in a repo with no commits", r.stdout + r.stderr)
(proj / "evidence").mkdir()
(proj / "evidence" / "preflight-probe.txt").write_text("tool0 1.0\n")
commit(proj, env, "chore: Preflight report")
for i in range(1, 8):
    (proj / f"f{i}.kt").write_text(f"{i}\n")
    commit(proj, env, f"Stage 1 Task 1.{i}: work\n\nmutation: reverting f{i}.kt turns the test red")
(proj / "g.txt").write_text("g\n")
commit(proj, env, "Stage 1 green\n\nevaluator: PASS — reads well")
plan.write_text(plan.read_text().replace("- [ ]", "- [x]").replace("**Status:** [ ]", "**Status:** [x]"))
r, doc = run_json(str(plan), "--repo", str(proj), "--require-all-checks")
# Its tasks are evidenced by `mutation:` lines, which are legacy: proof records
# are the evidence form, so finding 8 reports the lines advisory, nothing else fires.
others = [f for f in (doc or {}).get("findings", []) if not (
    f["finding"] == 8 and f["severity"] == "advisory" and "legacy" in f["rule"])]
if doc is not None and not others and r.returncode == 4:
    ok("with task commits, a probe artefact and a review ledger: the history checks are clean")
else:
    bad(f"honest run must be clean; exit {r.returncode}",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: the hash check deleted. An edited baseline is not evidence.
import hashlib as _hl
key = _hl.sha256(str(plan.resolve()).encode()).hexdigest()[:16]
bp = proj / ".claude" / "plan-baseline" / f"{key}.json"
bdoc = json.loads(bp.read_text())
bdoc["text"] = bdoc["text"].replace("- [ ]", "- [x]")
bp.write_text(json.dumps(bdoc))
r = run(str(plan), "--repo", str(proj))
if r.returncode == 2 and "hash" in r.stderr:
    ok("a baseline edited after capture exits 2, never clean")
else:
    bad(f"tampered baseline must exit 2, got {r.returncode}", r.stdout[:300] + r.stderr[:300])

# Catches: the plan-identity check deleted. A baseline of another plan must not
# be borrowed.
bdoc["text"] = "# other\n"; bdoc["sha256"] = _hl.sha256(b"# other\n").hexdigest()
bdoc["plan"] = str(plans_dir / "other.md")
bp.write_text(json.dumps(bdoc))
r = run(str(plan), "--repo", str(proj))
if r.returncode == 2 and "different plan" in r.stderr:
    ok("a baseline recording a different plan exits 2")
else:
    bad(f"foreign baseline must exit 2, got {r.returncode}", r.stdout[:300] + r.stderr[:300])

# Finding 11: a plan outside git that has LOST structure since its --snapshot. A deleted
# task takes its tick and its proof obligation with it, and every other check reads only
# what is still there, so the deletion itself is the thing to report — each missing item
# by name, so a rename that hides a deletion in the totals is still seen.
print()
print("baseline — structure the snapshot had and the plan on disk lost (STRUCTURE-SHRANK)")

def struct_plan(drop=(), no_status=(), extra=()):
    """Stage 1 (Task 1.1) and Stage 2 (Tasks 2.1-2.3), each with a gate block. `drop`
    names what to leave out ("Stage 2", "Task 2.3", "Stage 2 Gate"); `no_status` the
    tasks written without their Status line; `extra` tasks added to Stage 2."""
    out = ["# Plan", ""]
    for s, tasks in ((1, ["1.1"]), (2, ["2.1", "2.2", "2.3", *extra])):
        if f"Stage {s}" not in drop:
            out += [f"## Stage {s}", ""]
        for t in tasks:
            if f"Task {t}" in drop:
                continue
            out += [f"### Task {t}: thing {t}"]
            if t not in no_status:
                out += ["- **Status:** [ ]"]
            out += [f"- Build thing {t}.", ""]
        if f"Stage {s} Gate" not in drop:
            out += [f"### Stage {s} Gate", "", "- [ ] `make test` exits 0", ""]
    return "\n".join(out)

plans_dir, proj, env = newdir("ss-plans"), *newrepo("ss-proj")
plan = plans_dir / "plan.md"
plan.write_text(struct_plan())
(proj / "README").write_text("x\n"); commit(proj, env, "chore: initial commit")
r = snap(plan, proj)
if r.returncode != 0:
    bad(f"--snapshot failed: exit {r.returncode}", r.stderr[:300])

def shrank(**kw):
    plan.write_text(struct_plan(**kw))
    r, doc = run_json(str(plan), "--repo", str(proj), "--require-all-checks")
    got = (doc or {}).get("findings", [])
    return r, doc, got, [f for f in got if f.get("finding") == 11]

r, doc, got, f11 = shrank(drop=("Task 2.3",))
if len(got) == 1 and len(f11) == 1 and f11[0].get("severity") == "advisory" \
        and f11[0].get("text") == "STRUCTURE-SHRANK ### Task 2.3" and r.returncode == 4:
    ok("a plan missing Task 2.3 since its snapshot gets one advisory STRUCTURE-SHRANK naming it, exit 4")
else:
    bad(f"a deleted task must be one advisory STRUCTURE-SHRANK finding naming Task 2.3, exit 4 "
        f"(red if the deleted task goes unreported); exit {r.returncode}",
        json.dumps(got, indent=2)[:900] if doc else r.stderr)

r, doc, got, f11 = shrank(drop=("Stage 2 Gate",))
if len(got) == 1 and len(f11) == 1 and f11[0].get("text") == "STRUCTURE-SHRANK ### Stage 2 Gate" \
        and r.returncode == 4:
    ok("a plan missing its Stage 2 gate block gets one STRUCTURE-SHRANK naming it, exit 4")
else:
    bad(f"a deleted gate block must be one STRUCTURE-SHRANK naming Stage 2 Gate; exit {r.returncode}",
        json.dumps(got, indent=2)[:900] if doc else r.stderr)

r, doc, got, f11 = shrank(no_status=("2.2",))
if len(got) == 1 and len(f11) == 1 \
        and f11[0].get("text") == "STRUCTURE-SHRANK - **Status:** of Task 2.2" and r.returncode == 4:
    ok("a plan with one fewer Status: line gets one STRUCTURE-SHRANK naming its task, exit 4")
else:
    bad(f"a vanished Status: line must be one STRUCTURE-SHRANK naming Task 2.2; exit {r.returncode}",
        json.dumps(got, indent=2)[:900] if doc else r.stderr)

# Catches: counting totals instead of identities. One task added, one deleted: the
# count of tasks is unchanged, the deleted one is still gone.
r, doc, got, f11 = shrank(drop=("Task 2.2",), extra=("2.4",))
if [f.get("text") for f in f11] == ["STRUCTURE-SHRANK ### Task 2.2"]:
    ok("a rename-plus-delete with the same task count still names the deleted task")
else:
    bad("a deletion masked by an added task must still be named",
        json.dumps(got, indent=2)[:900] if doc else r.stderr)

r, doc, got, f11 = shrank(drop=("Stage 2", "Task 2.1", "Task 2.2", "Task 2.3", "Stage 2 Gate"))
texts = sorted(f.get("text", "") for f in f11)
want = sorted(f"STRUCTURE-SHRANK {n}" for n in (
    "## Stage 2", "### Task 2.1", "### Task 2.2", "### Task 2.3", "### Stage 2 Gate"))
if texts == want:
    ok("a deleted stage names its heading, each task and its gate — not each task's Status line too")
else:
    bad("a deleted stage must be named item by item, once each",
        f"got {texts}\nwant {want}")

r, doc, got, f11 = shrank(extra=("2.4",))
if doc is not None and not got and r.returncode == 0 and 11 in doc.get("checks_run", []):
    ok("a plan that only grew gets no finding, and the structural check reports as run")
else:
    bad(f"a grown plan must be clean with 11 run; exit {r.returncode}",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

r, doc, got, f11 = shrank()
if doc is not None and not got and r.returncode == 0 \
        and set(doc.get("checks_run", [])) == set(range(1, 12)):
    ok("an unchanged plan gets no finding and every check, 11 included, reports as run")
else:
    bad(f"an unchanged plan must be clean with 1-11 run; exit {r.returncode}",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# A baseline that cannot be parsed is not tampering (its hash and plan cannot even be read):
# the checks that need it say they did not run, and every other check still runs.
key = _hl.sha256(str(plan.resolve()).encode()).hexdigest()[:16]
(proj / ".claude" / "plan-baseline" / f"{key}.json").write_text("{not json")
plan.write_text(struct_plan(drop=("Task 2.3",)).replace(
    "- **Status:** [ ]", "- **Status:** [x] done (amended — soft residual)", 1))
r = run(str(plan), "--repo", str(proj), "--require-all-checks", "--json")
try:
    doc = json.loads(r.stdout)     # parsed here, so an exit-2 regression fails the check below
except json.JSONDecodeError:
    doc = None
nr = {c["finding"]: c.get("reason", "") for c in (doc or {}).get("checks_not_run", [])}
said = [ln for ln in r.stderr.splitlines() if "structural check" in ln]
if doc is not None and r.returncode == 1 and {1, 3, 5, 11} == set(nr) \
        and findings_of(doc, 2) and not findings_of(doc, 11) \
        and {2, 4, 6, 7, 8, 9, 10} <= set(doc.get("checks_run", [])) and len(said) == 1:
    ok("an unreadable snapshot says so in one line; 1/3/5/11 are not run and the rest still run")
else:
    bad(f"an unreadable snapshot must skip only 1/3/5/11 and say so once; exit {r.returncode}",
        r.stderr[:600] + (json.dumps(doc, indent=2)[:600] if doc else ""))
plan.write_text(struct_plan())
r = run(str(plan), "--repo", str(proj), "--require-all-checks")
if r.returncode == 3:
    ok("with an unreadable snapshot and no findings, --require-all-checks still exits 3")
else:
    bad(f"an unreadable snapshot is never a clean bill: expected exit 3, got {r.returncode}",
        r.stdout[:300] + r.stderr[:300])

# JSON that is not an object is no more a baseline than text that is not JSON.
(proj / ".claude" / "plan-baseline" / f"{key}.json").write_text("[]")
r = run(str(plan), "--repo", str(proj), "--require-all-checks")
if r.returncode == 3 and "structural check" in r.stderr:
    ok("a snapshot holding JSON that is not an object is unreadable too: not run, exit 3")
else:
    bad(f"a non-object snapshot must read as unreadable, not exit 2; got {r.returncode}",
        r.stderr[:300])


def shrank_from(before, after, label):
    """Snapshot `before`, then audit `after`: the finding-11 texts and the exit."""
    pd, pj, ev = newdir(f"{label}-plans"), *newrepo(f"{label}-proj")
    pl = pd / "plan.md"
    pl.write_text(before)
    (pj / "README").write_text("x\n"); commit(pj, ev, "chore: initial commit")
    snap(pl, pj)
    pl.write_text(after)
    r, doc = run_json(str(pl), "--repo", str(pj))
    return r, [f.get("text") for f in (doc or {}).get("findings", []) if f.get("finding") == 11]

# A stage whose title says "gate" is a stage, not a gate block: retitling it loses nothing.
titled = struct_plan().replace("## Stage 2\n", "## Stage 2: Hosts and gate review\n")
r, f11 = shrank_from(titled, titled.replace(": Hosts and gate review", ": Hosts"), "ss-title")
if f11 == [] and r.returncode == 0:
    ok("retitling a stage whose title says 'gate' reports nothing lost")
else:
    bad(f"a stage title containing 'gate' was read as a gate block; exit {r.returncode}", f11)
_gm = importlib.util.module_from_spec(importlib.util.spec_from_file_location("pfa_gate", SCRIPT))
_gm.__spec__.loader.exec_module(_gm)
if _gm.gate_box_stages("## Stage 3: Hosts and gate review\n\n- [x] a\n") == {} \
        and _gm.gate_box_stages("### Stage 3 Gate\n\n- [x] a\n") == {3: "3"} \
        and _gm.gate_box_stages("### Stage 7-light gate\n\n- [x] a\n") == {3: "7"}:
    ok("gate boxes are the boxes under a gate heading, not under a stage titled with 'gate'")
else:
    bad("gate_box_stages must read `### Stage N Gate` only",
        str(_gm.gate_box_stages("## Stage 3: Hosts and gate review\n\n- [x] a\n")))

# A fenced example is not structure: deleting it loses nothing, and a `# comment` in a
# fenced block inside a task does not hide the task's Status line.
fenced = struct_plan().replace("- Build thing 2.1.\n", "- Build thing 2.1.\n\n```\n"
                               "### Task 9.9: an example\n- **Status:** [ ]\n## Stage 9\n```\n")
r, f11 = shrank_from(fenced, struct_plan(), "ss-fence")
if f11 == [] and r.returncode == 0:
    ok("deleting a fenced example of a task and a stage reports nothing lost")
else:
    bad(f"a fenced example was counted as structure; exit {r.returncode}", f11)
commented = struct_plan().replace("### Task 2.2: thing 2.2\n",
                                  "### Task 2.2: thing 2.2\n```sh\n# run it\n```\n")
r, f11 = shrank_from(struct_plan(), commented, "ss-fcomment")
if f11 == [] and r.returncode == 0:
    ok("a fenced `# comment` above a Status line does not hide it")
else:
    bad(f"a fenced comment line hid a task's Status line; exit {r.returncode}", f11)


# Finding 1 counts a stage's gate boxes only while that stage has no `Stage N green`
# commit in the range. Five task commits, five Status ticks and two gate boxes is an
# honest stage — counting the gate boxes would make it 7 > 6, a blocking bulk flip at
# every plan's second gate. The same ticks with no green commit are still a bulk flip.
def gated_plan(label, n_tasks=5):
    plans_dir = newdir(f"{label}-plans")
    lines = ["# Plan", "", "## Stage 1", ""]
    for i in range(1, n_tasks + 1):
        lines += [f"### Task 1.{i}: thing {i}", "- **Status:** [ ]", ""]
    lines += ["### Stage 1 Gate", "", "- [ ] `make test` exits 0", "- [ ] `make lint` exits 0", ""]
    plan = plans_dir / "plan.md"
    plan.write_text("\n".join(lines))
    return plan


def tick_all(plan):
    plan.write_text(plan.read_text().replace("- [ ]", "- [x]").replace("**Status:** [ ]", "**Status:** [x]"))


for label, green, want in (("bl-gate-green", True, False), ("bl-gate-nogreen", False, True)):
    plan = gated_plan(label)
    proj, env = newrepo(f"{label}-proj")
    (proj / "README").write_text("x\n"); commit(proj, env, "chore: initial commit")
    snap(plan, proj)
    for i in range(1, 6):
        (proj / f"f{i}.txt").write_text(f"{i}\n"); commit(proj, env, f"Stage 1 Task 1.{i}: work")
    if green:
        (proj / "gate.txt").write_text("gate report\n"); commit(proj, env, "Stage 1 green")
    tick_all(plan)
    r, doc = run_json(str(plan), "--repo", str(proj))
    f1 = findings_of(doc, 1) if doc else []
    if bool(f1) == want:
        ok("baseline: 5 task ticks + 2 gate boxes " + ("with" if green else "without")
           + " a `Stage 1 green` commit " + ("fires finding 1" if want else "is not a bulk flip"))
    else:
        bad("a stage's gate boxes are backed only by its green commit (red if gate boxes "
            "count, or count as backed with no green commit)", json.dumps(f1)[:400])

for label, green, want in (("hist-gate-green", True, False), ("hist-gate-nogreen", False, True)):
    repo, env = newrepo(label)
    plan = repo / "p.md"
    plan.write_text(gated_plan(f"{label}-src").read_text())
    base = commit(repo, env, "authored")
    for i in range(1, 6):
        (repo / f"f{i}.txt").write_text(f"{i}\n"); commit(repo, env, f"Stage 1 Task 1.{i}: work")
    tick_all(plan)
    commit(repo, env, "Stage 1 green" if green else "progress")
    r, doc = run_json(str(plan), "--since", base, cwd=repo)
    f1 = findings_of(doc, 1) if doc else []
    if bool(f1) == want:
        ok("history: the gate ticked " + ("in its `Stage 1 green` commit is not a bulk flip"
                                          if green else "in an ordinary commit still fires finding 1"))
    else:
        bad("history mode must back gate boxes by the green commit alone", json.dumps(f1)[:400])


# Finding 1 counts a Preflight box only while no probe artefact backs it. Six Preflight
# boxes and three task ticks, after three task commits, is an honest Stage 1 gate once
# the Preflight output is committed — counting those boxes would make it 9 > 6, a blocking
# bulk flip at the first gate of every plan with six Preflight checks. With no probe it is still a bulk flip.
def preflight_heavy_plan(label):
    plans_dir = newdir(f"{label}-plans")
    lines = ["# Plan", "", "## Preflight", ""]
    lines += [f"- [ ] Check {i}: `tool{i} --version` exits 0" for i in range(6)]
    lines += ["", "## Stage 1", ""]
    for i in range(1, 4):
        lines += [f"### Task 1.{i}: thing {i}", "- **Status:** [ ]", ""]
    plan = plans_dir / "plan.md"
    plan.write_text("\n".join(lines))
    return plan


for label, probed, want in (("bl-pre-probed", True, False), ("bl-pre-unprobed", False, True)):
    plan = preflight_heavy_plan(label)
    proj, env = newrepo(f"{label}-proj")
    (proj / "README").write_text("x\n"); commit(proj, env, "chore: initial commit")
    snap(plan, proj)
    for i in range(1, 4):
        (proj / f"f{i}.txt").write_text(f"{i}\n"); commit(proj, env, f"Stage 1 Task 1.{i}: work")
    if probed:
        (proj / "evidence").mkdir()
        (proj / "evidence" / "preflight-probe.txt").write_text("tool0 1.0\n")
        commit(proj, env, "Preflight probe output")
    tick_all(plan)
    r, doc = run_json(str(plan), "--repo", str(proj))
    f1 = findings_of(doc, 1) if doc else []
    if bool(f1) == want:
        ok("baseline: 6 Preflight + 3 task ticks after 3 task commits "
           + ("with a committed probe is not a bulk flip" if probed
              else "with no probe still fires finding 1"))
    else:
        bad("Preflight boxes join finding 1's count only when no probe backs them (red if a "
            "probe is ignored, or its absence is)", json.dumps(f1)[:400])

for label, probed, want in (("hist-pre-probed", True, False), ("hist-pre-unprobed", False, True)):
    repo, env = newrepo(label)
    plan = repo / "p.md"
    plan.write_text(preflight_heavy_plan(f"{label}-src").read_text())
    base = commit(repo, env, "authored")
    for i in range(1, 4):
        (repo / f"f{i}.txt").write_text(f"{i}\n"); commit(repo, env, f"Stage 1 Task 1.{i}: work")
    tick_all(plan)
    if probed:
        (repo / "evidence").mkdir()
        (repo / "evidence" / "preflight-probe.txt").write_text("tool0 1.0\n")
    commit(repo, env, "Preflight green" if probed else "progress")
    r, doc = run_json(str(plan), "--since", base, cwd=repo)
    f1 = findings_of(doc, 1) if doc else []
    if bool(f1) == want:
        ok("history: 6 Preflight + 3 task ticks in one commit "
           + ("carrying a probe artefact is not a bulk flip" if probed
              else "with no probe still fires finding 1"))
    else:
        bad("history mode must back Preflight boxes by a probe in their own commit",
            json.dumps(f1)[:400])

# The exemption's bounds. A probe file is blind to which
# box it backs, so it clears at most N Preflight boxes; it never touches a non-Preflight
# box, even one repeating a Preflight line's text; and in history mode a probe counts
# from the commit that adds it onward, never backwards.
def bounds_plan(label, n_pre, n_tasks, gate_dupes=0):
    plans_dir = newdir(f"{label}-plans")
    lines = ["# Plan", "", "## Preflight", ""]
    lines += [f"- [ ] Check {i}: `tool{i} --version` exits 0" for i in range(n_pre)]
    lines += ["", "## Stage 1", ""]
    for i in range(1, n_tasks + 1):
        lines += [f"### Task 1.{i}: thing {i}", "- **Status:** [ ]", ""]
    if gate_dupes:
        lines += ["### Stage 1 Gate", ""]
        lines += ["- [ ] Check 0: `tool0 --version` exits 0"] * gate_dupes
    plan = plans_dir / "plan.md"
    plan.write_text("\n".join(lines) + "\n")
    return plan


def bounds_case(label, n_pre, n_tasks, gate_dupes=0):
    plan = bounds_plan(label, n_pre, n_tasks, gate_dupes)
    proj, env = newrepo(f"{label}-proj")
    (proj / "README").write_text("x\n"); commit(proj, env, "chore: initial commit")
    snap(plan, proj)
    (proj / "f1.txt").write_text("1\n"); commit(proj, env, "Stage 1 Task 1.1: work")
    (proj / "evidence").mkdir()
    (proj / "evidence" / "preflight-probe.txt").write_text("tool0 1.0\n")
    commit(proj, env, "Preflight probe output")
    tick_all(plan)
    r, doc = run_json(str(plan), "--repo", str(proj))
    return findings_of(doc, 1) if doc else []


for label, args, why in (
        ("bl-cap", (8, 0), "8 probed Preflight boxes exceed the cap of 6"),
        ("bl-nonpre", (2, 7), "7 task ticks are not cleared by a Preflight probe"),
        ("bl-dupe", (1, 0, 7), "7 gate boxes repeating a Preflight line are not Preflight boxes")):
    f1 = bounds_case(label, *args)
    if f1:
        ok(f"baseline: finding 1 still fires — {why}")
    else:
        bad(f"a probe clears only up to N Preflight boxes, by line (red if {why} is exempted)",
            json.dumps(f1)[:300])

for label, order, want in (("hist-probe-first", "before", False),
                           ("hist-probe-after", "after", True)):
    repo, env = newrepo(label)
    plan = repo / "p.md"
    plan.write_text(preflight_heavy_plan(f"{label}-src").read_text())
    base = commit(repo, env, "authored")
    for i in range(1, 4):
        (repo / f"f{i}.txt").write_text(f"{i}\n"); commit(repo, env, f"Stage 1 Task 1.{i}: work")

    def probe():
        (repo / "evidence").mkdir()
        (repo / "evidence" / "preflight-probe.txt").write_text("tool0 1.0\n")
        commit(repo, env, "Preflight probe output")
    if order == "before":
        probe()
    tick_all(plan)
    commit(repo, env, "progress")
    if order == "after":
        probe()
    r, doc = run_json(str(plan), "--since", base, cwd=repo)
    f1 = findings_of(doc, 1) if doc else []
    if bool(f1) == want:
        ok("history: a probe committed " + order + " the Preflight ticks "
           + ("does not back them" if want else "backs them, as in baseline mode"))
    else:
        bad("history mode backs Preflight boxes by a probe in that commit or earlier, "
            "never a later one", json.dumps(f1)[:400])

# ------------------------------- findings 8 and 9: proof is a record, not a line
# An executor can write `mutation:` and `req:` lines that are false (a
# substituted break, a cleanup that is never exercised). A line is a claim; a
# prove-claim.py record is the tool having watched it. Findings 8 and 9 read
# records from the committed tree and validate each against the commit that
# added it; lines alone are "legacy, unverified" (advisory).
print()
print("findings 8 and 9 — proof records, bound to their commit")
PC = SCRIPT.parent / "prove-claim.py"
REC_PLAN = (
    "# Plan\n\n## Stage 1\n\n"
    "### Task 1.1: calc\n- **Status:** [x]\n- `add` returns the sum.\n"
    "- **Test:** `python3 tests/test_calc.py` — add returns the sum (red if add subtracts)\n"
)
CALC = "def add(a, b):\n    return a + b\n"
TESTPY = "import sys\nsys.path.insert(0, '.')\nfrom calc import add\nassert add(2, 3) == 5\n"
BUILD = "python3 -c 'import ast; ast.parse(open(\"calc.py\").read())'"


def rec_world(label):
    plans_dir = newdir(f"{label}-plans")
    proj, env = newrepo(f"{label}-proj")
    (proj / "calc.py").write_text(CALC)
    (proj / "tests").mkdir()
    (proj / "tests" / "test_calc.py").write_text(TESTPY)
    (proj / ".gitignore").write_text("__pycache__/\n")
    commit(proj, env, "base")
    plan = plans_dir / "2026-10-04-rec-plan.md"
    plan.write_text(REC_PLAN)
    return plan, proj, env


def prove_task(plan, proj, req_kind="covered"):
    """Prove claim 1 and requirement 1 of Task 1.1 on the current index."""
    f = proj / "calc.py"
    orig = f.read_text()
    f.write_text(orig.replace("return a + b", "return a - b"))
    d = subprocess.run(["git", "-C", str(proj), "diff", "--", "calc.py"],
                       capture_output=True, text=True).stdout
    f.write_text(orig)
    brk = newdir(f"{proj.name}-brk") / "break.patch"
    brk.write_text(d)
    base = ["--repo", str(proj), "--plan", str(plan), "--task", "1.1"]
    r1 = subprocess.run([sys.executable, str(PC), "claim", *base, "--claim", "1", "--break",
                         str(brk), "--test", "python3 tests/test_calc.py", "--build", BUILD],
                        capture_output=True, text=True)
    if req_kind == "covered":
        extra = ["req", *base, "--req", "1", "--covered-by-claim", "1"]
    else:
        extra = ["deviation", *base, "--req", "1", "--why", "add is not separately checkable here"]
    r2 = subprocess.run([sys.executable, str(PC), *extra], capture_output=True, text=True)
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
    return brk


def task_findings(doc, n):
    return [f for f in findings_of(doc, n) if f.get("text") == "Task 1.1"]


# A proven task, its records committed with its code: clean.
plan, proj, env = rec_world("rec-ok")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not task_findings(doc, 8) and not task_findings(doc, 9) and {8, 9} <= set(doc["checks_run"]):
    ok("a task whose records are committed with its code is clean on 8 and 9")
else:
    bad("valid committed records must satisfy 8 and 9 (red if records are not read)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# A project may keep proof records out of git (proof/ ignored): its plans live outside
# the repo, and a record copies the plan's path and wording. The records are then read
# from disk and bound to the commit that carries their task, never trusted unbound.
def local_world(label):
    plan, proj, env = rec_world(label)
    (proj / ".gitignore").write_text("__pycache__/\nproof/\n")
    commit(proj, env, "ignore proof records")
    return plan, proj, env


plan, proj, env = local_world("rec-local-ok")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
tracked = subprocess.run(["git", "-C", str(proj), "ls-files", "proof"], capture_output=True, text=True).stdout
r, doc = run_json(str(plan), "--repo", str(proj))
if (not tracked and doc is not None and not task_findings(doc, 8) and not task_findings(doc, 9)
        and {8, 9} <= set(doc["checks_run"])):
    ok("with proof/ ignored, valid records on disk satisfy 8 and 9")
else:
    bad("local records must be read from disk and bound to the task commit (red if only "
        "committed records are read)", json.dumps(doc, indent=2)[:900] if doc else r.stderr)

plan, proj, env = local_world("rec-local-stale")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
(proj / "calc.py").write_text(CALC + "# changed after the proof\n")
commit(proj, env, "Stage 1 Task 1.1: changed after proving")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "different tree" in f8[0]["rule"]:
    ok("a local record proven on another tree than its task's commit is blocking")
else:
    bad("a stale local record must be blocking (red if disk records are trusted unbound)", str(f8)[:500])

plan, proj, env = local_world("rec-local-nocommit")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "unrelated subject")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "no commit names" in f8[0]["rule"]:
    ok("a local record for a task no commit names is blocking")
else:
    bad("a local record with no task commit must be blocking", str(f8)[:500])

# Local mode says so, once per plan, so a reader can see which binding applied.
plan, proj, env = local_world("rec-local-banner")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
r, doc = run_json(str(plan), "--repo", str(proj))
banner = [f for f in findings_of(doc, 8) if "outside git" in f.get("rule", "")] if doc else []
if (len(banner) == 1 and banner[0]["severity"] == "advisory"
        and "commits naming" in banner[0]["rule"]):
    ok("local mode emits one advisory finding-8 line naming the binding it used")
else:
    bad("local mode must report itself once, advisory (red if the binding is silent)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: a valid claim deviation turned blocking by a later commit naming its task.
# The newest commit's tree differs; the older one, which recorded it, matches.
plan, proj, env = local_world("rec-local-claimdev")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
fp = subprocess.run([sys.executable, str(PC), "fingerprint", "--repo", str(proj)],
                    capture_output=True, text=True).stdout.strip()
(proj / "proof" / plan.stem / "1.1" / "claim-1.json").write_text(json.dumps({
    "schema": 2, "kind": "claim-deviation", "plan": str(plan), "task": "1.1", "index": 1,
    "text": "add returns the sum (red if add subtracts)",
    "why": "the scope trace is kept outside the repo", "fingerprint": fp,
    "created": "2026-10-04T00:00:00+00:00"}))
commit(proj, env, "Stage 1 Task 1.1: claim recorded as a deviation")
(proj / "notes.txt").write_text("later\n")
commit(proj, env, "Stage 1 Task 1.1: unrelated follow-up")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and all(f["severity"] == "advisory" for f in f8) and "outside the repo" in f8[0]["rule"]:
    ok("a local claim deviation stays advisory when a newer commit names its task")
else:
    bad("an older commit matching a valid claim deviation must bind it (red if the "
        "fallback treats a valid deviation as a failure)", str(f8)[:500])

# Catches: an ignore file overriding tracked records. Records are committed, then
# proof/ is excluded and a tracked record forged on disk: the committed copy decides.
plan, proj, env = rec_world("rec-tracked-excluded")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: proven")
(proj / ".git" / "info").mkdir(exist_ok=True)   # `--template=` creates no info/
with open(proj / ".git" / "info" / "exclude", "a") as fh:
    fh.write("proof/\n")
rp = proj / "proof" / plan.stem / "1.1" / "claim-1.json"
data = json.loads(rp.read_text())
data["red"]["exit"] = 0
rp.write_text(json.dumps(data))
r, doc = run_json(str(plan), "--repo", str(proj))
if (doc is not None and not task_findings(doc, 8)
        and not [f for f in findings_of(doc, 8) if "outside git" in f.get("rule", "")]):
    ok("tracked records stay in committed mode whatever an ignore file says")
else:
    bad("tracked records must be read from HEAD, never disk (red if an ignore file "
        "selects local mode)", json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: a local schema-1 record reported with an add date the audit cannot know.
plan, proj, env = local_world("rec-local-legacy")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
rp = proj / "proof" / plan.stem / "1.1" / "req-1.json"
data = json.loads(rp.read_text())
data.pop("covered_by_claim", None)
data.pop("touched_blobs", None)   # a bare-check record binds no claim's blobs
data.pop("witness_blobs", None)
data.update({"schema": 1, "check": "python3 tests/test_calc.py",
             "result": {"exit": 0, "tail": ""}})
rp.write_text(json.dumps(data))
commit(proj, env, "Stage 1 Task 1.1: req by a bare check")
r, doc = run_json(str(plan), "--repo", str(proj))
f9 = task_findings(doc, 9) if doc else []
if (f9 and f9[0]["severity"] == "advisory" and "a schema-1 record kept outside git" in f9[0]["rule"]
        and "cutover" not in f9[0]["rule"]):
    ok("a local schema-1 req record says it is kept outside git, not when it was added")
else:
    bad("a local schema-1 record must not claim an add date (red if it says 'added after "
        "the cutover')", str(f9)[:500])

# Records on disk that are neither tracked nor ignored were forgotten, not kept local on
# purpose: they stay "no record" (blocking), never a quiet switch to local mode.
plan, proj, env = rec_world("rec-forgotten")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "calc.py"], check=True, env=env)
prove_task(plan, proj)
subprocess.run(["git", "-C", str(proj), "reset", "-q", "--", "proof"], check=True, env=env)
subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m",
                "Stage 1 Task 1.1: twice, records left uncommitted"], check=True, env=env)
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "no record" in f8[0]["rule"]:
    ok("untracked records that are not ignored read as no record, not as local proof")
else:
    bad("forgotten records must stay 'no record' (red if local mode needs no ignore)", str(f8)[:500])

# Catches: "tracked" judged from the index alone. Valid records are committed, then a
# forged one is committed over them; `git rm --cached` empties the index, proof/ is
# excluded and the valid copy restored on disk. HEAD still carries the forgery, so it decides.
plan, proj, env = rec_world("rec-head-tracked")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
rp = proj / "proof" / plan.stem / "1.1" / "claim-1.json"
good = rp.read_text()
data = json.loads(good)
data["red"]["exit"] = 0
rp.write_text(json.dumps(data))
commit(proj, env, "forge the claim record")
subprocess.run(["git", "-C", str(proj), "rm", "-r", "-q", "--cached", "proof"], check=True, env=env)
(proj / ".git" / "info").mkdir(exist_ok=True)   # `--template=` creates no info/
with open(proj / ".git" / "info" / "exclude", "a") as fh:
    fh.write("proof/\n")
rp.write_text(good)
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
banner = [f for f in findings_of(doc, 8) if "outside git" in f.get("rule", "")] if doc else []
if f8 and f8[0]["severity"] == "blocking" and not banner:
    ok("records committed at HEAD stay in committed mode after leaving the index")
else:
    bad("a record tracked at HEAD must be read from HEAD (red if only the index "
        "decides 'tracked')", json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: the ignore status judged from the first record only. 1.1/ is ignored by a
# path-specific rule, 1.2/ is not: the 1.2 records were forgotten, so committed mode
# holds and Task 1.2 reads as "no record".
plan, proj, env = rec_world("rec-part-ignored")
plan.write_text(REC_PLAN + REC_PLAN.split("## Stage 1\n\n", 1)[1].replace("Task 1.1", "Task 1.2"))
(proj / ".gitignore").write_text(f"__pycache__/\nproof/{plan.stem}/1.1/\n")
commit(proj, env, "ignore the 1.1 records")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "calc.py"], check=True, env=env)
brk = prove_task(plan, proj)
r12 = subprocess.run([sys.executable, str(PC), "claim", "--repo", str(proj), "--plan", str(plan),
                      "--task", "1.2", "--claim", "1", "--break", str(brk),
                      "--test", "python3 tests/test_calc.py", "--build", BUILD],
                     capture_output=True, text=True)
assert r12.returncode == 0, r12.stderr
subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m",
                "Stage 1 Tasks 1.1 and 1.2: twice, records left uncommitted"], check=True, env=env)
r, doc = run_json(str(plan), "--repo", str(proj))
f8_12 = [f for f in findings_of(doc, 8) if f.get("text") == "Task 1.2"] if doc else []
banner = [f for f in findings_of(doc, 8) if "outside git" in f.get("rule", "")] if doc else []
if (not banner and f8_12 and f8_12[0]["severity"] == "blocking"
        and "no record" in f8_12[0]["rule"]):
    ok("one ignored record directory does not put a forgotten one in local mode")
else:
    bad("every record must be ignored for local mode (red if records[0] alone decides)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: the commit binding not checked. The code changes after the proof and
# is committed together with the now-stale record.
plan, proj, env = rec_world("rec-stale")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
(proj / "calc.py").write_text(CALC + "# changed after the proof\n")
commit(proj, env, "Stage 1 Task 1.1: changed after proving")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "different tree" in f8[0]["rule"]:
    ok("a record proven on another tree than its commit's is blocking")
else:
    bad("a record from an older tree must block (red when the commit binding goes unchecked)", str(f8)[:500])

# Catches: exit codes not validated. A hand-edited record: red exit 0.
plan, proj, env = rec_world("rec-forged")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
rp = proj / "proof" / plan.stem / "1.1" / "claim-1.json"
data = json.loads(rp.read_text())
data["red"]["exit"] = 0
rp.write_text(json.dumps(data))
commit(proj, env, "Stage 1 Task 1.1: forged")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "did not fail" in f8[0]["rule"]:
    ok("a record claiming red with an exit of 0 is blocking")
else:
    bad("a hand-edited record must block (red when exit codes go unread)", str(f8)[:500])

# Catches: records not bound to the plan's wording. The claim is reworded after
# it was proven: the record proves a sentence the plan no longer says.
plan, proj, env = rec_world("rec-reworded")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: proven")
plan.write_text(REC_PLAN.replace("add returns the sum (red", "add returns the total of both (red"))
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "different wording" in f8[0]["rule"]:
    ok("a record proven against wording the plan has since changed is blocking")
else:
    bad("a reworded claim must be blocking (red if wording is not compared)", str(f8)[:500])

# Schema 2: a req check must be proven by a break. A schema-1 req check — seen
# to pass, never to fail — is legacy, reported as such. The same shape claiming
# schema 2 is what a hand-written record would look like: the requirement is not
# shown met. A schema-1 record is legacy only when first added before the
# schema-2 cutover (LEGACY_CUTOFF in the script); the same record committed
# now is not shown met. Finding 9 is advisory in every case (no blocking mandate
# until its rate is measured), so the message is what differs.
BEFORE = {"GIT_COMMITTER_DATE": "2026-10-03T12:00:00+00:00", "GIT_AUTHOR_DATE": "2026-10-03T12:00:00+00:00"}
for label, schema, sev, dated in (("rec-legacy-req", 1, "legacy schema-1", BEFORE),
                                  ("rec-bare-req", 2, "not shown met", {}),
                                  ("rec-late-legacy", 1, "not shown met", {})):
    plan, proj, env = rec_world(label)
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
    prove_task(plan, proj)
    rp = proj / "proof" / plan.stem / "1.1" / "req-1.json"
    data = json.loads(rp.read_text())
    data.pop("covered_by_claim", None)
    data.pop("touched_blobs", None)   # a bare-check record binds no claim's blobs
    data.pop("witness_blobs", None)
    data.update({"schema": schema, "check": "python3 tests/test_calc.py",
                 "result": {"exit": 0, "tail": ""}})
    rp.write_text(json.dumps(data))
    commit(proj, {**env, **dated}, "Stage 1 Task 1.1: req by a bare check")
    r, doc = run_json(str(plan), "--repo", str(proj))
    f9 = task_findings(doc, 9) if doc else []
    when = " (added before the cutover)" if dated else (" (added after the cutover)" if schema == 1 else "")
    if f9 and f9[0]["severity"] == "advisory" and sev in f9[0]["rule"]:
        ok(f"a schema-{schema} req record with a bare passing check{when} is advisory: {sev}")
    else:
        bad(f"schema-{schema} bare req check{when} must be advisory '{sev}' (red if no cutoff "
            "date splits legacy from new)", str(f9)[:400])

# Catches: a covered-by citation not followed. The req cites claim 5 of a task
# that has one claim: the record validates on its own, the citation does not.
plan, proj, env = rec_world("rec-cites")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
rp = proj / "proof" / plan.stem / "1.1" / "req-1.json"
data = json.loads(rp.read_text())
data["covered_by_claim"] = 5
rp.write_text(json.dumps(data))
commit(proj, env, "Stage 1 Task 1.1: req cites a claim that does not exist")
r, doc = run_json(str(plan), "--repo", str(proj))
f9 = task_findings(doc, 9) if doc else []
if f9 and f9[0]["severity"] == "advisory" and "cites claim 5" in f9[0]["rule"]:
    ok("a req pointing at a nonexistent claim is reported (advisory)")
else:
    bad("the covered-by pointer must be followed (red when the cited claim goes unchecked)", str(f9)[:400])

# Catches: proof/ as a hiding place in the committed tree.
plan, proj, env = rec_world("rec-stray")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
(proj / "proof" / "helper.py").write_text("x = 1\n")
commit(proj, env, "Stage 1 Task 1.1: with a stray file under proof/")
r, doc = run_json(str(plan), "--repo", str(proj))
st = [f for f in findings_of(doc, 8) if f.get("text") == "proof/"] if doc else []
if st and st[0]["severity"] == "blocking" and "proof/helper.py" in st[0]["rule"]:
    ok("a committed file under proof/ that is not a record is blocking")
else:
    bad("a non-record file under proof/ must block (red when proof/ accepts any file)",
        json.dumps(doc, indent=2)[:600] if doc else r.stderr)

# Catches: the audit and the ref hook reading subjects differently. One reader,
# subject_tasks(), is shared; it is case-insensitive and expands lists and ranges.
_sp = importlib.util.spec_from_file_location("pfa_subjects", SCRIPT)
_sm = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(_sm)
cases = {"Stage 2 Task 2.8: x": {"2.8"}, "task 2.1: x": {"2.1"}, "Tasks 2.1 and 2.2: x": {"2.1", "2.2"},
         "Stage 1 Task 1.1 + Task 1.2: x": {"1.1", "1.2"}, "Tasks 2.4-2.7: x": {"2.4", "2.5", "2.6", "2.7"},
         "Tasks 2.4–2.7": {"2.4", "2.5", "2.6", "2.7"}, "Task #2.1": {"2.1"}, "Task-2.1": {"2.1"},
         "Stage 1 Task 1.10: x": {"1.10"}, "Stage 2 gate: none": set()}
wrong = {k: _sm.subject_tasks(k) for k, v in cases.items() if _sm.subject_tasks(k) != v}
if not wrong:
    ok("subject_tasks reads case, lists, ranges and 1.10 vs 1.1 as intended")
else:
    bad("subject_tasks must read every subject form", wrong)
plan, proj, env = rec_world("rec-lower")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "stage 1 task 1.1: lowercase subject")
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not task_findings(doc, 8) and not task_findings(doc, 9):
    ok("a lowercase 'task 1.1' subject is that task's commit for the audit, as for the hook")
else:
    bad("lowercase subjects must count (red if the audit reads subjects differently)",
        json.dumps(doc, indent=2)[:600] if doc else r.stderr)

# Catches: lines still counted as proof. Self-reported lines, no records.
plan, proj, env = rec_world("rec-legacy")
(proj / "x.txt").write_text("x\n")
commit(proj, env, "Stage 1 Task 1.1: work\n\nmutation: add subtracts -> red\nreq: add -> test")
r, doc = run_json(str(plan), "--repo", str(proj))
f8, f9 = (task_findings(doc, 8), task_findings(doc, 9)) if doc else ([], [])
if (f8 and f9 and all(f["severity"] == "advisory" and "legacy" in f["rule"] for f in f8 + f9)
        and r.returncode == 4):
    ok("lines alone are advisory 'legacy, unverified' on 8 and 9 — never clean, never blocking")
else:
    bad("self-reported lines with no record stay legacy advisories (red when a line passes as proof)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Nothing at all: a commit with neither lines nor records.
plan, proj, env = rec_world("rec-none")
(proj / "x.txt").write_text("x\n")
commit(proj, env, "Stage 1 Task 1.1: work")
r, doc = run_json(str(plan), "--repo", str(proj))
f8, f9 = (task_findings(doc, 8), task_findings(doc, 9)) if doc else ([], [])
if f8 and f8[0]["severity"] == "blocking" and r.returncode == 1:
    ok("a task commit with no proof at all is blocking on 8")
else:
    bad("no proof must be blocking on 8", json.dumps(doc, indent=2)[:900] if doc else r.stderr)
# An unaccounted requirement is reported, never blocking: finding 9 has no
# blocking mandate until its rate is measured.
if f9 and all(f["severity"] == "advisory" for f in f9) and "not shown met" in f9[0]["rule"]:
    ok("an unaccounted requirement is advisory on 9, never blocking")
else:
    bad("an unaccounted requirement must be advisory (red if finding 9 blocks)", str(f9)[:400])

# A requirement recorded as a deviation: advisory, named.
plan, proj, env = rec_world("rec-dev")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj, req_kind="deviation")
commit(proj, env, "Stage 1 Task 1.1: with a deviation")
r, doc = run_json(str(plan), "--repo", str(proj))
f9 = task_findings(doc, 9) if doc else []
if f9 and f9[0]["severity"] == "advisory" and "deviation" in f9[0]["rule"] and not task_findings(doc, 8):
    ok("a requirement recorded as a deviation is an advisory naming it")
else:
    bad("a deviation must be advisory", str(f9)[:400])

# A ticked task with no commit naming it: finding 8 advisory, finding 9 silent.
plan, proj, env = rec_world("rec-nocommit")
r, doc = run_json(str(plan), "--repo", str(proj))
f8, f9 = (task_findings(doc, 8), task_findings(doc, 9)) if doc else ([], [])
if f8 and "no commit" in f8[0]["rule"] and f8[0]["severity"] == "advisory" and not f9:
    ok("a ticked task with no commit: finding 8 advisory, finding 9 leaves it to 8")
else:
    bad("no-commit must be one advisory, from finding 8", f"f8={f8} f9={f9}")

# Records are owed for a ticked task's FIRST claim, plus any claim that names its
# break "(red if …)"; no other claim needs one.
# Catches: named breaks not required. Two claims, both named, only the first proven.
plan, proj, env = rec_world("rec-two")
plan.write_text(REC_PLAN.replace("(red if add subtracts)\n",
                                 "(red if add subtracts); add is commutative (red if add ignores b)\n"))
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: two claims, one proven")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "1 of 2 required claim" in f8[0]["rule"]:
    ok("an unrecorded claim that names its break blocks the task")
else:
    bad("every claim naming a break needs a record (red when only claim 1 is checked)", str(f8)[:400])

# Catches: every claim required. The second claim names no break and has no record.
plan, proj, env = rec_world("rec-unnamed")
plan.write_text(REC_PLAN.replace("(red if add subtracts)\n",
                                 "(red if add subtracts); add is commutative\n"))
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: second claim names no break")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if doc is not None and not f8:
    ok("an unrecorded claim that names no break leaves the task clean")
else:
    bad("records are owed for claim 1 and break-naming claims only (red when all claims are demanded)",
        str(f8)[:400] if doc else r.stderr)

# Catches: the first claim not required. Claim 1 names no break and has no record;
# claim 2 names its break and is proven.
plan, proj, env = rec_world("rec-first")
plan.write_text(REC_PLAN.replace("add returns the sum (red if add subtracts)\n",
                                 "add is defined; add returns the sum (red if add subtracts)\n"))
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
brk = prove_task(plan, proj)
# prove_task records claim 1; drop it, and prove claim 2 with the same break.
(proj / "proof" / plan.stem / "1.1" / "claim-1.json").unlink()
r2 = subprocess.run([sys.executable, str(PC), "claim", "--repo", str(proj), "--plan", str(plan),
                     "--task", "1.1", "--claim", "2", "--break", str(brk), "--test",
                     "python3 tests/test_calc.py", "--build", BUILD], capture_output=True, text=True)
assert r2.returncode == 0, r2.stderr
commit(proj, env, "Stage 1 Task 1.1: first claim unrecorded")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "claim 1:" in f8[0]["rule"]:
    ok("a ticked task missing its claim-1 record is blocking")
else:
    bad("claim 1 always needs a record (red when claim 1 is exempt)",
        str(f8)[:400] if doc else r.stderr)

# Catches: a claim deviation counted as proof. claim-1.json holds a claim
# deviation (prove-claim.py deviation --claim): disclosed, so advisory — never clean.
plan, proj, env = rec_world("rec-claimdev")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
fp = subprocess.run([sys.executable, str(PC), "fingerprint", "--repo", str(proj)],
                    capture_output=True, text=True).stdout.strip()
rp = proj / "proof" / plan.stem / "1.1" / "claim-1.json"
rp.write_text(json.dumps({"schema": 2, "kind": "claim-deviation", "plan": str(plan),
                          "task": "1.1", "index": 1,
                          "text": "add returns the sum (red if add subtracts)",
                          "why": "the scope trace is kept outside the repo", "fingerprint": fp,
                          "created": "2026-10-04T00:00:00+00:00"}))
commit(proj, env, "Stage 1 Task 1.1: claim recorded as a deviation")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if (f8 and all(f["severity"] == "advisory" for f in f8) and "deviation" in f8[0]["rule"]
        and "outside the repo" in f8[0]["rule"]):
    ok("a claim filed as a deviation yields a named advisory, not a clean result")
else:
    bad("a deviation on a claim must stay advisory (red when it passes as proof)",
        str(f8)[:400] if doc else r.stderr)
# The same deviation without a reason is no record at all: blocking.
d = json.loads(rp.read_text()); d["why"] = ""
rp.write_text(json.dumps(d))
commit(proj, env, "Stage 1 Task 1.1: deviation with no reason")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking":
    ok("a deviation with an empty why is blocking")
else:
    bad("a reasonless claim deviation must be blocking (red if it is waived silently)", str(f8)[:400])

# A claim deviation is bound like a proof: to its path, the plan's wording and
# its commit's tree. Each of these is blocking, never a disclosed advisory.
def claimdev_world(label, mutate):
    plan, proj, env = rec_world(label)
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
    prove_task(plan, proj)
    fp = subprocess.run([sys.executable, str(PC), "fingerprint", "--repo", str(proj)],
                        capture_output=True, text=True).stdout.strip()
    rec = {"schema": 2, "kind": "claim-deviation", "plan": str(plan), "task": "1.1", "index": 1,
           "text": "add returns the sum (red if add subtracts)",
           "why": "the scope trace is kept outside the repo", "fingerprint": fp,
           "created": "2026-10-04T00:00:00+00:00"}
    mutate(rec, plan, proj)
    (proj / "proof" / plan.stem / "1.1" / "claim-1.json").write_text(json.dumps(rec))
    commit(proj, env, f"Stage 1 Task 1.1: {label}")
    r, doc = run_json(str(plan), "--repo", str(proj))
    return task_findings(doc, 8) if doc else []


f8 = claimdev_world("claimdev-index", lambda rec, plan, proj: rec.update(index=2))
if f8 and f8[0]["severity"] == "blocking" and "not Task 1.1 #1" in f8[0]["rule"]:
    ok("a claim deviation stored at another claim's path is blocking")
else:
    bad("a claim deviation must match its path (red if task/index are not compared)", str(f8)[:400])
f8 = claimdev_world("claimdev-wording", lambda rec, plan, proj: rec.update(text="add returns a total"))
if f8 and f8[0]["severity"] == "blocking" and "different wording" in f8[0]["rule"]:
    ok("a claim deviation recorded against other wording is blocking")
else:
    bad("a claim deviation must match the plan's wording (red if wording is not compared)",
        str(f8)[:400])
f8 = claimdev_world("claimdev-tree", lambda rec, plan, proj: (proj / "calc.py").write_text(
    CALC + "# changed after the deviation was recorded\n"))
if f8 and f8[0]["severity"] == "blocking" and "different tree" in f8[0]["rule"]:
    ok("a claim deviation recorded on another tree than its commit's is blocking")
else:
    bad("a deviation on a claim is tied to the tree of its commit (red when fingerprints go uncompared)",
        str(f8)[:400])

# A record binds the blobs of the files its break touched (touched_blobs), not the whole
# tree: the task's own Status flip in a plan kept in the repo, or a rebase onto a commit
# that touches other files, leaves it valid. A later commit that changes a touched file
# is drift: blocking, naming the file and the record. A record with no touched_blobs is
# judged by the whole-tree fingerprint, as before.
TWICE = CALC + "\n\ndef twice(a):\n    return 2 * a\n"


def inrepo_world(label):
    plan0, proj, env = rec_world(label)
    plan = proj / "docs" / plan0.name
    plan.parent.mkdir()
    plan.write_text(REC_PLAN.replace("**Status:** [x]", "**Status:** [ ]"))
    commit(proj, env, "the plan lives in the repo")
    return plan, proj, env


plan, proj, env = inrepo_world("blob-flip")
(proj / "calc.py").write_text(TWICE)
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
plan.write_text(REC_PLAN)   # the task's own Status flip, after its proof
commit(proj, env, "Stage 1 Task 1.1: twice")
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not task_findings(doc, 8) and not task_findings(doc, 9):
    ok("records proven before the task's Status flip in an in-repo plan verify after it")
else:
    bad("a proof must survive its own task's Status flip in an in-repo plan (red under the "
        "index binding)", json.dumps(task_findings(doc, 8) + task_findings(doc, 9))[:900]
        if doc else r.stderr)

plan, proj, env = inrepo_world("blob-flip-legacy")
(proj / "calc.py").write_text(TWICE)
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
for rp in (proj / "proof" / plan.stem / "1.1").glob("*.json"):
    d = json.loads(rp.read_text())
    d.pop("touched_blobs", None)
    d.pop("witness_blobs", None)
    rp.write_text(json.dumps(d))
plan.write_text(REC_PLAN)
commit(proj, env, "Stage 1 Task 1.1: twice, records from before the blob binding")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and f8[0]["severity"] == "blocking" and "different tree" in f8[0]["rule"]:
    ok("a record without touched_blobs is still judged by the whole tree, never accepted unbound")
else:
    bad("a record with no touched_blobs must keep the fingerprint rule (red if it is "
        "accepted unbound)", str(f8)[:500])

for local in (False, True):
    mode = "local" if local else "committed"
    plan, proj, env = (local_world if local else rec_world)(f"blob-rebase-{mode}")
    g = ["git", "-C", str(proj)]
    subprocess.run(g + ["checkout", "-q", "-b", "side"], check=True, env=env)
    (proj / "notes.txt").write_text("other work\n")
    commit(proj, env, "other work, on another file")
    subprocess.run(g + ["checkout", "-q", "main"], check=True, env=env)
    (proj / "calc.py").write_text(TWICE)
    subprocess.run(g + ["add", "-A"], check=True, env=env)
    prove_task(plan, proj)
    commit(proj, env, "Stage 1 Task 1.1: twice")
    rb = subprocess.run(g + ["rebase", "-q", "side"], capture_output=True, text=True, env=env)
    r, doc = run_json(str(plan), "--repo", str(proj))
    f8 = task_findings(doc, 8) if doc else []
    if rb.returncode == 0 and (proj / "notes.txt").exists() and doc is not None and not f8:
        ok(f"after a rebase onto a commit touching other files, a {mode} record verifies")
    else:
        bad(f"a rebase that leaves the touched files as they were must keep a {mode} record "
            "valid (red under the whole-tree binding)", (rb.stderr, str(f8)[:600]))

plan, proj, env = rec_world("blob-drift")
(proj / "calc.py").write_text(TWICE)
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
(proj / "calc.py").write_text(TWICE + "# tidied after the proof\n")
commit(proj, env, "tidy calc")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
crel = f"proof/{plan.stem}/1.1/claim-1.json"
drift = [f for f in f8 if "drift" in f["rule"] and "calc.py" in f["rule"] and crel in f["rule"]]
if r.returncode == 1 and drift and drift[0]["severity"] == "blocking":
    ok("a later commit changing a touched file is blocking drift, naming the file and the record")
else:
    bad("drift must be reported, blocking, with the file and the record (red if the touched "
        "blobs at HEAD go uncompared)", f"rc={r.returncode} {str(f8)[:600]}")
# Catches: a req covered by claim 1 reporting the drift of claim 1's own maps a second time.
alld = [f for f in f8 if "drift" in f["rule"]]
if len(alld) == 1:
    ok("a covered req's drift is its claim's: the drift is reported once")
else:
    bad("a covered req must not repeat its claim's drift line (red if each record of the "
        "same maps reports it)", json.dumps(alld, indent=2)[:900])
# Catches: drift in a closed stage blocking a later stage. Stage 1's gate is fully ticked
# and its `Stage 1 green` commit holds calc.py as proven: a later change to a file Stage 1
# proved is expected of a later stage, and the drift is advisory. A stage whose gate is not
# fully ticked is still open: its drift blocks, as at its gate.
FULL_GATE = "\n### Stage 1 Gate\n- [x] the suite passes\n- [x] no regressions\n"
plan, proj, env = rec_world("blob-drift-closed")
(proj / "calc.py").write_text(TWICE)
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
subprocess.run(["git", "-C", str(proj), "commit", "-q", "--allow-empty", "-m", "Stage 1 green"],
               check=True, env=env)
(proj / "calc.py").write_text(TWICE + "# changed by a later stage\n")
commit(proj, env, "Stage 2 Task 2.1: tidy calc")
for gate_, sev_ in ((FULL_GATE, "advisory"),
                    (FULL_GATE.replace("- [x] no", "- [ ] no"), "blocking")):
    plan.write_text(REC_PLAN + gate_)
    r, doc = run_json(str(plan), "--repo", str(proj))
    f8 = task_findings(doc, 8) if doc else []
    drift = [f for f in f8 if "drift" in f["rule"] and "calc.py" in f["rule"]]
    if drift and all(f["severity"] == sev_ for f in drift) and r.returncode == (
            4 if sev_ == "advisory" else 1):
        ok(f"drift on a task of {'a closed' if sev_ == 'advisory' else 'an open'} stage is {sev_}")
    else:
        bad(f"drift on a task whose stage gate is {'fully' if sev_ == 'advisory' else 'not fully'} "
            f"ticked must be {sev_} (red if every stage's drift blocks)",
            f"rc={r.returncode} {str(f8)[:600]}")
# Catches: ticked boxes read as a close the proof survived. Here calc.py changed BEFORE the
# `Stage 1 green` commit, so the stage closed on a stale proof (a gate not installed, or
# bypassed): the drift stays blocking however the boxes read.
plan, proj, env = rec_world("blob-drift-stale-close")
(proj / "calc.py").write_text(TWICE)
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
(proj / "calc.py").write_text(TWICE + "# changed before the stage closed\n")
commit(proj, env, "tidy calc")
subprocess.run(["git", "-C", str(proj), "commit", "-q", "--allow-empty", "-m", "Stage 1 green"],
               check=True, env=env)
plan.write_text(REC_PLAN + FULL_GATE)
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
drift = [f for f in f8 if "drift" in f["rule"] and "calc.py" in f["rule"]]
if drift and all(f["severity"] == "blocking" for f in drift) and r.returncode == 1:
    ok("drift a record already had at its stage's `Stage N green` commit stays blocking")
else:
    bad("a stage closed on a drifted proof must keep its drift blocking (red if ticked gate "
        "boxes alone make it advisory)", f"rc={r.returncode} {str(f8)[:600]}")

# The test the record was watched under is bound too (witness_blobs): weakening it
# after the proof is drift, named like a changed touched file.
plan, proj, env = rec_world("blob-witness")
(proj / "calc.py").write_text(TWICE)
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
(proj / "tests" / "test_calc.py").write_text("pass  # the assertions are gone\n")
commit(proj, env, "weaken the test")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
crel = f"proof/{plan.stem}/1.1/claim-1.json"
drift = [f for f in f8 if "drift" in f["rule"] and "tests/test_calc.py" in f["rule"]
         and crel in f["rule"]]
if r.returncode == 1 and drift and drift[0]["severity"] == "blocking":
    ok("a test file edited after the proof is blocking drift, naming the test file and the record")
else:
    bad("a weakened test must be reported as drift (red if the files the test runs go unbound)",
        f"rc={r.returncode} {str(f8)[:600]}")

# After a repair, only the tasks whose touched files it changed are re-proved (review-cost
# change 3): the audit names those, and every other task's records still verify. Two tasks
# on two files; the repair edits Task 1.1's file only.
TWO_PLAN = REC_PLAN + (
    "\n### Task 1.2: mul\n- **Status:** [x]\n- `mul` returns the product.\n"
    "- **Test:** `python3 tests/test_mul.py` — mul returns the product (red if mul adds)\n"
)
plan, proj, env = rec_world("blob-two-tasks")
plan.write_text(TWO_PLAN)
(proj / "mul.py").write_text("def mul(a, b):\n    return a * b\n")
(proj / "tests" / "test_mul.py").write_text(
    "import sys\nsys.path.insert(0, '.')\nfrom mul import mul\nassert mul(2, 3) == 6\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
mbrk = newdir("blob-two-tasks-mbrk") / "break.patch"
mbrk.write_text("--- a/mul.py\n+++ b/mul.py\n@@ -1,2 +1,2 @@\n def mul(a, b):\n"
                "-    return a * b\n+    return a + b\n")
mb = ["--repo", str(proj), "--plan", str(plan), "--task", "1.2"]
r1 = subprocess.run([sys.executable, str(PC), "claim", *mb, "--claim", "1", "--break", str(mbrk),
                     "--test", "python3 tests/test_mul.py",
                     "--build", "python3 -c 'import mul'"], capture_output=True, text=True)
r2 = subprocess.run([sys.executable, str(PC), "req", *mb, "--req", "1", "--covered-by-claim", "1"],
                    capture_output=True, text=True)
commit(proj, env, "Stage 1 Task 1.1 and Task 1.2: add, mul")
(proj / "calc.py").write_text(CALC + "# repaired at the gate\n")
commit(proj, env, "Stage 1 gate round 1 (Task 1.1): repair calc")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = findings_of(doc, 8) if doc else []
d11 = [f for f in f8 if f.get("text") == "Task 1.1" and "drift" in f["rule"]
       and "calc.py" in f["rule"]]
d12 = [f for f in f8 if f.get("text") == "Task 1.2"]
if r1.returncode == 0 and r2.returncode == 0 and len(d11) == 1 and not d12:
    ok("a repair touching one task's file names that task's drifted record; the other verifies")
else:
    bad("after a repair, the audit must name only the task whose touched file changed (red if "
        "it names neither, or both)", f"{r1.stderr[-300:]} {r2.stderr[-300:]} {str(f8)[:700]}")

# Catches: a record that crashes the JSON parser crashing the whole audit (exit 2)
# instead of being named: deep nesting raises RecursionError, not ValueError.
plan, proj, env = rec_world("rec-nested2")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
(proj / "proof" / plan.stem / "1.1" / "claim-1.json").write_text("[" * 200000)
commit(proj, env, "Stage 1 Task 1.1: a record that crashes the parser")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if r.returncode == 1 and f8 and f8[0]["severity"] == "blocking" and "claim 1" in f8[0]["rule"]:
    ok("a record that crashes the JSON parser is a blocking finding, not a crashed audit")
else:
    bad("an unparseable record must be named, not crash the audit (red if RecursionError escapes)",
        f"rc={r.returncode} {str(f8)[:300]} {r.stderr[-300:]}")

# Catches: unticked tasks audited. An open task with no commit is not a finding.
plan, proj, env = rec_world("rec-open")
plan.write_text(REC_PLAN.replace("**Status:** [x]", "**Status:** [ ]"))
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not task_findings(doc, 8) and not task_findings(doc, 9):
    ok("an unticked task is not audited on 8 and 9")
else:
    bad("unticked tasks must be skipped", json.dumps(doc, indent=2)[:600] if doc else r.stderr)

# Catches: the task-id boundary. A commit for Task 1.10 is not one for Task 1.1.
plan, proj, env = rec_world("rec-110")
(proj / "x.txt").write_text("x\n")
commit(proj, env, "Stage 1 Task 1.10: other work\n\nmutation: x -> red")
r, doc = run_json(str(plan), "--repo", str(proj))
f8 = task_findings(doc, 8) if doc else []
if f8 and "no commit" in f8[0]["rule"]:
    ok("a 'Task 1.10' commit does not count as one for Task 1.1")
else:
    bad("task ids must match whole (red if 1.10 counts as 1.1)", str(f8)[:400])

# Catches: legacy `deviation:` lines ignored. Lines alone stay legacy, not blocking.
plan, proj, env = rec_world("rec-legacy-dev")
(proj / "x.txt").write_text("x\n")
commit(proj, env, "Stage 1 Task 1.1: work\n\nmutation: add subtracts -> red\n"
                  "deviation: add is checked by the claim")
r, doc = run_json(str(plan), "--repo", str(proj))
f9 = task_findings(doc, 9) if doc else []
if f9 and f9[0]["severity"] == "advisory" and "legacy" in f9[0]["rule"]:
    ok("legacy `deviation:` lines alone are a legacy advisory on 9")
else:
    bad("deviation lines must count as legacy evidence", str(f9)[:400])

# Without --repo, 8 and 9 are NOT RUN, never clean.
r, doc = run_json(str(plan))
nr = {c["finding"]: c.get("reason", "") for c in (doc or {}).get("checks_not_run", [])}
if doc is not None and 8 in nr and 9 in nr and "--repo" in nr[8]:
    ok("without --repo, findings 8 and 9 are NOT RUN and say to pass --repo")
else:
    bad("no --repo must leave 8 and 9 not run", json.dumps(doc, indent=2)[:400] if doc else "")

# ------------------------------- amendment notes are history, never clauses
# A plan amended under the protocol carries notes like
# `*(amended 2026-10-04 per … — was: …; …)*` inside a task's description or
# Test field. Split as clauses, one note read as two extra requirements.
print()
print("clause splitting ignores amendment / superseded notes")
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("pfa_clauses", SCRIPT)
_pfa = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_pfa)
plain = "Do a; do b. Then do c."
noted = ("Do a; do b *(amended 2026-10-04 per x — was: do b; then d. Also e)*. "
         "Then do c. *(superseded 2026-10-04 by commit abc; see y. Done)*")
if _pfa.requirement_clauses(noted) == _pfa.requirement_clauses(plain) == ["Do a", "do b", "Then do c."]:
    ok("a description's amendment and superseded notes add no requirement clauses")
else:
    bad("notes must not be clauses", f"{_pfa.requirement_clauses(noted)} vs {_pfa.requirement_clauses(plain)}")
t_plain = "`make t` — one works; two works"
t_noted = "`make t` — one works; two works *(superseded 2026-10-04 by commit abc — the x; y)*"
if len(_pfa.claim_clauses(t_noted)) == len(_pfa.claim_clauses(t_plain)) == 2:
    ok("a Test field's superseded note adds no claims")
else:
    bad("notes must not be claims", _pfa.claim_clauses(t_noted))

# Catches: a note used to hide a requirement. A note without history (no date,
# no was:, no by commit) is not history; it counts. And a code span is never a note.
hidden = "Do a. *(amended: do b too; and c)*"
if _pfa.count_requirements(hidden) == 3:
    ok("a note with no history in it is not stripped — its clauses still count")
else:
    bad("a history-free note must still count", _pfa.requirement_clauses(hidden))
spanned = "Do a; run `x *(amended 2026-10-04 was: y)*` exactly"
if _pfa.count_requirements(spanned) == 2 and "amended" in _pfa.requirement_clauses(spanned)[1]:
    ok("a note-shaped string inside a code span is kept")
else:
    bad("code spans must not be stripped as notes", _pfa.requirement_clauses(spanned))


# ---------- finding 10: remediating a live-checked gate without sweeping the captures
# A remediation fitted to the one capture a failed live run leaves behind, then
# checked by re-running a slow live check, spends a full live run per guess. The rule
# (gate-failure-procedure.md § Remediation that re-runs a live check): sweep every
# capture on the host first and record the command as a `fixture-sweep:` trailer.
print()
print("finding 10 — a remediation commit on a live-checked gate, missing its fixture-sweep: trailer")
LIVE_PLAN = (
    "# Plan\n\n## Stage 1: parser\n\n"
    "### Task 1.1: parse\n- **Status:** [ ]\n"
    "- **Test:** `python3 t.py` — parses (red if it does not)\n\n"
    "### Stage 1 Gate\n\n"
    "- [ ] Stage-scope: `make test` exits 0\n"
    "- [ ] **Live check, rig-driven:** the test rig answers the probe request\n\n"
    "## Stage 2: docs\n\n"
    "### Task 2.1: docs\n- **Status:** [ ]\n"
    "- **Test:** `python3 d.py` — documents (red if it does not)\n\n"
    "### Stage 2 Gate\n\n"
    "- [ ] Stage-scope: `make test` exits 0\n"
)


def live_world(label, subject, body=""):
    plans_dir = newdir(f"{label}-plans")
    proj, env = newrepo(f"{label}-proj")
    (proj / "README").write_text("x\n")
    commit(proj, env, "base")
    plan = plans_dir / "2026-10-01-live-plan.md"
    plan.write_text(LIVE_PLAN)
    (proj / "parser.py").write_text("x = 1\n")
    commit(proj, env, subject + ("\n\n" + body if body else ""))
    return plan, proj, env


# Catches: the finding silent — a live-check remediation with no sweep reads as clean.
plan, proj, env = live_world("live-nosweep", "Stage 1 gate remediation round 1: fit the parser")
r, doc = run_json(str(plan), "--repo", str(proj))
f10 = findings_of(doc, 10) if doc else []
if len(f10) == 1 and f10[0].get("severity") == "advisory" and 10 in doc.get("checks_run", []):
    ok("a live-check gate's remediation commit with no fixture-sweep: trailer is reported advisory")
else:
    bad("remediating a live-checked gate without a sweep is finding 10, advisory (red when nothing is reported)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)
# Catches: the severity raised — an advisory heuristic turned into a RED gate.
if f10 and r.returncode == 4 and not any(f.get("severity") == "blocking" for f in f10):
    ok("finding 10 alone exits 4, never 1 — it is never blocking")
else:
    bad(f"finding 10 is never blocking (red when it turns the exit into 1); exit {r.returncode}",
        json.dumps(f10, indent=2)[:400])

# Catches: the trailer ignored — the sweep was recorded and the finding fires anyway.
plan, proj, env = live_world("live-sweep", "Stage 1 gate remediation round 1: fit the parser",
                             "fixture-sweep: python3 -m pytest tests/captures  # 3 captures")
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not findings_of(doc, 10) and 10 in doc.get("checks_run", []) \
        and r.returncode == 0:
    ok("the same remediation with a fixture-sweep: trailer is clean")
else:
    bad("a fixture-sweep: trailer clears finding 10 (red when the trailer goes unread)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: every remediation flagged — Stage 2's gate has no live check.
plan, proj, env = live_world("live-hostonly", "Stage 2 gate remediation round 1: reword the docs")
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not findings_of(doc, 10) and 10 in doc.get("checks_run", []) \
        and r.returncode == 0:
    ok("remediating a gate without any live check reports nothing")
else:
    bad("only gates carrying a **Live check line are in scope (red when all remediations are flagged)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: the date bound dropped — a "Stage 1 gate remediation" from a plan the
# repo executed before this one was written is not this plan's remediation.
plans_dir = newdir("live-old-plans")
proj, env = newrepo("live-old-proj")
(proj / "README").write_text("x\n")
old_env = dict(env, GIT_AUTHOR_DATE="2026-09-01T12:00:00+00:00",
               GIT_COMMITTER_DATE="2026-09-01T12:00:00+00:00")
commit(proj, old_env, "Stage 1 gate remediation round 1: another plan's work")
plan = plans_dir / "2026-10-01-live-plan.md"
plan.write_text(LIVE_PLAN)
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and not findings_of(doc, 10) and 10 in doc.get("checks_run", []) \
        and r.returncode == 0:
    ok("a remediation commit older than the plan's date is another plan's, not flagged")
else:
    bad("finding 10 must read only commits from the plan's date on",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: the comma form `Stage N gate, remediation round K` — a subject form plans
# use alongside the plain one — read as no remediation at all.
plan, proj, env = live_world("live-comma", "Stage 1 gate, remediation round 1: fit the parser")
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and len(findings_of(doc, 10)) == 1:
    ok("the comma form `Stage N gate, remediation` is a remediation commit too")
else:
    bad("finding 10 must read `Stage N gate, remediation` (red if the comma form is missed)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: the "on or after" boundary — a commit dated ON the plan's date is this
# plan's.
plans_dir = newdir("live-same-plans")
proj, env = newrepo("live-same-proj")
(proj / "README").write_text("x\n")
same_env = dict(env, GIT_AUTHOR_DATE="2026-10-01T09:00:00+00:00",
                GIT_COMMITTER_DATE="2026-10-01T09:00:00+00:00")
commit(proj, same_env, "Stage 1 gate remediation round 1: same day")
plan = plans_dir / "2026-10-01-live-plan.md"
plan.write_text(LIVE_PLAN)
r, doc = run_json(str(plan), "--repo", str(proj))
if doc is not None and len(findings_of(doc, 10)) == 1:
    ok("a remediation commit dated on the plan's own date is in scope")
else:
    bad("the date bound is `on or after` the plan's date (red if the same day is dropped)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)


# ---- proof directory listings take any path; an orphaned proof directory is named
# Catches: committed records listed with a bare `ls-tree --name-only` and split on
# whitespace — a plan stem with a space becomes two paths and every record reads missing.
plan, proj, env = rec_world("rec-space")
splan, sproj = plan.with_name("2026-10-04-rec two-plan.md"), proj
plan.rename(splan)
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(splan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
r, doc = run_json(str(splan), "--repo", str(proj))
if doc is not None and not task_findings(doc, 8) and not task_findings(doc, 9):
    ok("a plan stem with a space: its committed records are each read as one path")
else:
    bad("records under a stem with a space must be read whole (red with the bare ls-tree listing)",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# Catches: a plan stem passed to git as a pathspec with its glob characters live. The stem
# `rec[1]*` then also names a decoy `proof/...rec1x-plan/`: committed, the record is judged
# on the decoy's commit; local, the staged decoy reads as a tracked record, nothing is local.
for local_ in (False, True):
    mode_ = "local" if local_ else "committed"
    plan, proj, env = (local_world if local_ else rec_world)(f"rec-glob-{mode_}")
    gplan = plan.with_name("2026-10-04-rec[1]*-plan.md")
    plan.rename(gplan)
    (proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
    prove_task(gplan, proj)
    commit(proj, env, "Stage 1 Task 1.1: twice")
    decoy = proj / "proof" / "2026-10-04-rec1x-plan" / "1.1"
    decoy.mkdir(parents=True)
    shutil.copy(proj / "proof" / gplan.stem / "1.1" / "claim-1.json", decoy / "claim-1.json")
    if not local_:
        (proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return a + a\n")
    subprocess.run(["git", "-C", str(proj), "add", "-f", "-A", "--", "proof/2026-10-04-rec1x-plan",
                    "calc.py"], check=True, env=env)
    if not local_:
        subprocess.run(["git", "-C", str(proj), "commit", "-q", "-m", "decoy"], check=True, env=env)
    # Local, the decoy is only staged: the index alone (ls-files) reads it as tracked.
    r, doc = run_json(str(gplan), "--repo", str(proj))
    f8 = task_findings(doc, 8) if doc else []
    want = (lambda fs: fs and all("proof drift" in f["rule"] for f in fs)) if not local_ else (
        lambda fs: not fs)
    if doc is not None and want(f8) and not task_findings(doc, 9):
        ok(f"a plan stem with glob characters: its {mode_} records are read as literal paths")
    else:
        bad(f"a stem with `[`, `*` must be a literal pathspec ({mode_}) (red if git reads it "
            "as a glob)", json.dumps(f8 + task_findings(doc or {}, 9), indent=2)[:900]
            if doc else r.stderr)

# Catches: a plan renamed without `git mv proof/<old> proof/<new>`. Its records stay
# under the old stem, which no plan names any more: reported, advisory, with the step.
plan, proj, env = rec_world("rec-orphan")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
fresh = plan.with_name("2026-10-05-fresh-plan.md")
fresh.write_text(REC_PLAN.replace("[x]", "[ ]"))
plan.unlink()
r, doc = run_json(str(fresh), "--repo", str(proj))
orph = [f for f in (doc or {}).get("findings", []) if "ORPHAN-PROOF-DIR" in f.get("text", "")]
if (len(orph) == 1 and orph[0].get("severity") == "advisory"
        and "git mv proof/2026-10-04-rec-plan proof/2026-10-05-fresh-plan" in orph[0].get("rule", "")
        and r.returncode == 4
        and all(f.get("severity") == "advisory" for f in doc.get("findings", []))):
    ok("an orphaned proof directory is one advisory ORPHAN-PROOF-DIR finding naming the git mv, exit 4")
else:
    bad(f"proof/<old>/ with no plan must be named, advisory, exit 4 (exit {r.returncode})",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)
# Catches: the step telling the owner to delete records that may be unrecoverable (kept
# local, or owned by a plan in another folder), instead of confirming no plan owns them.
rule_ = orph[0].get("rule", "") if orph else ""
if orph and "delete" not in rule_ and "another folder" in rule_:
    ok("the orphan finding asks to confirm no plan in another folder owns the directory")
else:
    bad("the orphan finding must not advise deleting the directory (red if it says "
        "\"otherwise delete\")", rule_)
# Catches: the suggested command printed unquoted — a stem with a space splits in two.
spaced = fresh.with_name("2026-10-05-fresh two-plan.md")
fresh.rename(spaced)
r, doc = run_json(str(spaced), "--repo", str(proj))
orph = [f for f in (doc or {}).get("findings", []) if "ORPHAN-PROOF-DIR" in f.get("text", "")]
cmd_ = orph[0]["rule"].split("`")[1] if orph and orph[0].get("rule", "").count("`") >= 2 else ""
try:
    words_ = shlex.split(cmd_)
except ValueError:
    words_ = []
if words_ == ["git", "mv", "proof/2026-10-04-rec-plan", "proof/2026-10-05-fresh two-plan"]:
    ok("the suggested git mv quotes a plan stem with a space, so it runs as printed")
else:
    bad("the git mv operands must be shell-quoted (red if a stem with a space splits)",
        json.dumps(orph, indent=2)[:900] if orph else (doc or r.stderr))
# Catches: `git mv proof/<old> proof/<new>` offered when proof/<new>/ already exists — it
# would nest the old directory inside the new one.
(proj / "proof" / spaced.stem / "1.1").mkdir(parents=True)
shutil.copy(proj / "proof" / "2026-10-04-rec-plan" / "1.1" / "claim-1.json",
            proj / "proof" / spaced.stem / "1.1" / "claim-1.json")
r, doc = run_json(str(spaced), "--repo", str(proj))
orph = [f for f in (doc or {}).get("findings", []) if "ORPHAN-PROOF-DIR" in f.get("text", "")]
rule_ = orph[0].get("rule", "") if orph else ""
if (len(orph) == 1 and orph[0].get("severity") == "advisory" and "merge" in rule_
        and "`git mv " not in rule_):
    ok("with proof/<new>/ already there, the orphan finding says to merge, not to git mv")
else:
    bad("an existing proof/<new>/ must get a merge step, not a nesting git mv",
        json.dumps(orph, indent=2)[:900] if orph else (doc or r.stderr))
# The same check over records kept local (proof/ ignored): the directory is on disk only.
plan, proj, env = local_world("rec-orphan-local")
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
commit(proj, env, "Stage 1 Task 1.1: twice")
fresh = plan.with_name("2026-10-05-fresh-plan.md")
fresh.write_text(REC_PLAN.replace("[x]", "[ ]"))
plan.unlink()
r, doc = run_json(str(fresh), "--repo", str(proj))
orph = [f for f in (doc or {}).get("findings", []) if "ORPHAN-PROOF-DIR" in f.get("text", "")]
if len(orph) == 1 and "proof/2026-10-04-rec-plan" in orph[0].get("rule", ""):
    ok("an orphaned local proof directory (proof/ ignored) is named too")
else:
    bad("a local proof/<old>/ with no plan must be named",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)
# And a proof directory whose plan is there is never an orphan.
r, doc = run_json(str(splan), "--repo", str(sproj))
if doc is not None and not [f for f in doc.get("findings", []) if "ORPHAN-PROOF-DIR" in f.get("text", "")]:
    ok("a proof directory whose plan exists is not reported")
else:
    bad("a proof directory with its plan present must not be an orphan",
        json.dumps(doc, indent=2)[:900] if doc else r.stderr)

# ---- a sentence opening with a code span is its own clause; records match by text
# Catches: the sentence split run on the masked text, whose lookahead sees a blank
# where the backtick was — "`a` holds. `b` holds." was one requirement.
spec_ = importlib.util.spec_from_file_location("pfa_clauses", SCRIPT)
pfa_ = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(pfa_)
got_ = pfa_.requirement_clauses("- `a` holds. `b` holds.")
if got_ == ["- `a` holds", "`b` holds."] or [g.lstrip("- ") for g in got_] == ["`a` holds", "`b` holds."]:
    ok("a sentence opening with a code span starts its own requirement clause")
else:
    bad("\"`a` holds. `b` holds.\" must be two clauses (red with the masked-text lookahead)", got_)
got_ = pfa_.requirement_clauses("- Use `a.b`. Then `c; d` runs.")
if len(got_) == 2:
    ok("a `.` or `;` inside a code span still never splits")
else:
    bad("separators inside code spans must not split", got_)
# Catches: the code-span sentence start read after an abbreviation. "e.g. `x`" is one
# sentence; cut there, a clause loses its subject and every later clause renumbers.
for abbr_ in ("e.g.", "i.e.", "vs.", "etc.", "cf.", "No.", "E.g.", "Fig.", "eq.", "approx.",
              "(e.g.", "a."):
    got_ = pfa_.requirement_clauses(f"- Run the check, {abbr_} `x` holds.")
    if len(got_) == 1:
        ok(f"an abbreviation before a code span does not split: {abbr_!r}")
    else:
        bad(f"\"{abbr_} `x`\" must stay one clause (red if a known abbreviation or a single "
            "letter ends a sentence)", got_)
got_ = pfa_.requirement_clauses("- `a` holds. `b` holds. The rest holds too.")
if len(got_) == 3:
    ok("after the abbreviation rule, \"`a` holds. `b` holds.\" still splits")
else:
    bad("a sentence ending in a word before a code span must still split", got_)

# Catches: a record made before the split, whose clause number shifted, read as
# unproven — or matched to the clause now at its old number. It matches its clause by
# its text; a clause whose text changed is unproven.
SHIFT_PLAN = REC_PLAN.replace("- `add` returns the sum.\n",
                              "- Adds numbers. `add` returns the sum. It stays pure.\n")
plan, proj, env = rec_world("rec-shift")
plan.write_text(SHIFT_PLAN)
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)   # claim 1 + req 1 (covered)
base_ = ["--repo", str(proj), "--plan", str(plan), "--task", "1.1"]
made_ = [subprocess.run([sys.executable, str(PC), "req", *base_, "--req", str(k_),
                         "--covered-by-claim", "1"], capture_output=True, text=True)
         for k_ in (2, 3)]
rdir = proj / "proof" / plan.stem / "1.1"
if all(m_.returncode == 0 for m_ in made_):
    # The record of "It stays pure" as the old split numbered it: requirement 2 of 2.
    old = json.loads((rdir / "req-3.json").read_text())
    (rdir / "req-3.json").unlink()
    (rdir / "req-2.json").unlink()
    old["index"] = 2
    (rdir / "req-2.json").write_text(json.dumps(old))
    subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
    commit(proj, env, "Stage 1 Task 1.1: twice")
    r, doc = run_json(str(plan), "--repo", str(proj))
else:
    r, doc = made_[-1], None
f9 = " ".join(f.get("rule", "") for f in task_findings(doc or {}, 9))
if doc is not None and "requirement 2:" in f9 and "requirement 3:" not in f9:
    ok("a renumbered record matches its clause by text; the clause now at its old number stays open")
else:
    bad("a record whose clause number shifted must match by text", f9 or (r.stderr if doc is None else doc))
plan.write_text(SHIFT_PLAN.replace("It stays pure.", "It stays pure and small."))
r, doc = run_json(str(plan), "--repo", str(proj))
f9 = " ".join(f.get("rule", "") for f in task_findings(doc or {}, 9))
if doc is not None and "requirement 3:" in f9:
    ok("a clause whose text changed since its record is reported unproven")
else:
    bad("a changed clause must be unproven", f9 or doc)

# Catches: a renumbered record winning over the record under the clause's own number by
# file order. req-2.json proves requirement 2 but is invalid; req-3.json carries
# requirement 2's text too. The own-number record decides, as in the commit gate.
plan, proj, env = rec_world("rec-dup")
plan.write_text(SHIFT_PLAN)
(proj / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
subprocess.run(["git", "-C", str(proj), "add", "-A"], check=True, env=env)
prove_task(plan, proj)
base_ = ["--repo", str(proj), "--plan", str(plan), "--task", "1.1"]
made_ = subprocess.run([sys.executable, str(PC), "req", *base_, "--req", "2",
                        "--covered-by-claim", "1"], capture_output=True, text=True)
rdir = proj / "proof" / plan.stem / "1.1"
if made_.returncode == 0:
    own = json.loads((rdir / "req-2.json").read_text())
    (rdir / "req-3.json").write_text(json.dumps(dict(own, index=3)))
    (rdir / "req-2.json").write_text(json.dumps(dict(own, fingerprint="zz")))
    commit(proj, env, "Stage 1 Task 1.1: twice")
    r, doc = run_json(str(plan), "--repo", str(proj))
else:
    r, doc = made_, None
f9 = " ".join(f.get("rule", "") for f in task_findings(doc or {}, 9))
if doc is not None and "requirement 2: no valid fingerprint" in f9:
    ok("a record under its clause's own number wins over a renumbered one, whatever the file order")
else:
    bad("the own-number record must decide its clause (red if a later renumbered file "
        "replaces it)", f9 or (r.stderr if doc is None else doc))

for d_ in _tmpdirs:
    shutil.rmtree(d_, ignore_errors=True)

print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
