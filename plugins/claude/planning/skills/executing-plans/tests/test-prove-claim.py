#!/usr/bin/env python3
"""Fixture suite for prove-claim.py — run directly (repo convention):

    python3 core/skills/executing-plans/tests/test-prove-claim.py

WHAT THIS SUITE IS REALLY GUARDING. prove-claim.py exists because an executor
that writes its own proof sentences can write false ones. Each negative fixture
below is one shape a fake proof takes, and each says which guard it pins: a break the test never notices; a break of
the test instead of the code; a break that stops the build; a test that fails
anyway; a proof taken on a tree that is not the one being committed; a restore
that silently did not happen. If a fixture stops failing, that fake is back.
"""
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "prove-claim.py"
passed = failed = 0
_tmp = []


def ok(msg):
    global passed
    passed += 1
    print(f"  ok    {msg}")


def bad(msg, detail=""):
    global failed
    failed += 1
    print(f"  FAIL  {msg}")
    for line in str(detail).splitlines()[:12]:
        print(f"        | {line}")
    if os.environ.get("SUITE_FAIL_FAST") == "1":   # the battery needs only the first FAIL
        for d_ in _tmp:
            shutil.rmtree(d_, ignore_errors=True)
        sys.exit(1)


def run(*args, cwd=None):
    # The caller's PYTHONDONTWRITEBYTECODE is removed: the tool must set it for
    # its own test runs. Inherited, it hides exactly that guard — this suite run
    # under prove-claim.py (which sets it) cannot see the guard deleted.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, cwd=cwd, env=env)


PLAN = """# Plan

## Stage 1

### Task 1.1: calc
- **Status:** [ ]
- `add` returns the sum; `sub` returns the difference. The module is importable.
- **Test:** `python3 tests/test_calc.py` — add returns the sum (red if add subtracts); sub returns the difference
- **Red-Green max cycles:** 3
"""

CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
TEST = ("import sys\nsys.path.insert(0, '.')\nfrom calc import add, sub\n"
        "assert add(2, 3) == 5\nassert sub(5, 3) == 2\n")
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                          env=GIT_ENV, check=True).stdout


def world(test_cmd=None):
    """A repo with calc.py + tests/, and a plan outside it (plans may live outside the repo).

    `test_cmd` replaces the command in the plan's Test field: the tool only runs a
    test the plan names, so a case needing another command needs its own plan."""
    d = Path(tempfile.mkdtemp(prefix="prove-claim-"))
    _tmp.append(d)
    repo, plans = d / "repo", d / "plans"
    repo.mkdir(), plans.mkdir()
    # --template= / hooksPath: a global git template can install a
    # pre-commit hook that aborts a fixture repo's first commit.
    subprocess.run(["git", "init", "-q", "-b", "main", "--template=", str(repo)], check=True)
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "calc.py").write_text(CALC)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_calc.py").write_text(TEST)
    # Build output is ignored, as in any project: the guard refuses
    # untracked files, and a test run must not trip it by itself.
    (repo / ".gitignore").write_text("__pycache__/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    plan = plans / "2026-10-04-calc-plan.md"
    plan.write_text(PLAN if test_cmd is None else
                    PLAN.replace("`python3 tests/test_calc.py`", f"`{test_cmd}`"))
    return repo, plan


def patch(repo, rel, old, new):
    """A break as a unified diff, made by editing and diffing, then undone."""
    f = repo / rel
    orig = f.read_text()
    assert old in orig, (rel, old)
    f.write_text(orig.replace(old, new))
    diff = git(repo, "diff", "--", rel)
    f.write_text(orig)
    p = repo.parent / f"break-{len(list(repo.parent.glob('break-*')))}.patch"
    p.write_text(diff)
    return p


# The build parses without writing bytecode. py_compile always writes a .pyc,
# and a .pyc of the BROKEN code is exactly the stale artefact that fails the next
# baseline (see test "a copy-if-newer build is rebuilt after the restore").
BUILD_OK = "python3 -c 'import ast; ast.parse(open(\"calc.py\").read())'"


def claim(repo, plan, k, brk, *extra, test="python3 tests/test_calc.py", build=BUILD_OK):
    args = ["claim", "--repo", str(repo), "--plan", str(plan), "--task", "1.1",
            "--claim", str(k), "--break", str(brk), "--test", test]
    if build:
        args += ["--build", build]
    return run(*args, *extra)


def rec(repo, plan, kind, k):
    return repo / "proof" / plan.stem / "1.1" / f"{kind}-{k}.json"


def tree_clean(repo):
    return git(repo, "status", "--porcelain", "--", ".", ":(exclude)proof") == ""


print("prove-claim.py — a claim is proven by a run, not by a sentence")
print()

# ---------------------------------------------------------- a genuine proof
repo, plan = world()
brk = patch(repo, "calc.py", "return a + b", "return a - b")
r = claim(repo, plan, 1, brk)
f = rec(repo, plan, "claim", 1)
if r.returncode == 0 and f.is_file():
    ok("a break the test catches is proven and recorded (exit 0)")
else:
    bad(f"a real proof must be recorded, exit {r.returncode}", r.stdout + r.stderr)
data = json.loads(f.read_text()) if f.is_file() else {}
if data.get("red", {}).get("exit", 0) != 0 and data.get("baseline", {}).get("exit") == 0:
    ok("the record holds a passing baseline and a failing run under the break")
else:
    bad("record must show baseline=0 and red!=0", json.dumps(data)[:400])
if data.get("named_break") == "add subtracts":
    ok("the plan's named break is recorded beside the break actually used")
else:
    bad("named_break must be read from '(red if …)'", data.get("named_break"))
fp = run("fingerprint", "--repo", str(repo)).stdout.strip()
if data.get("fingerprint") == fp and tree_clean(repo):
    ok("the record is bound to the tree, and the tree is back as it was")
else:
    bad("fingerprint must match and the tree must be restored",
        f"{data.get('fingerprint')} vs {fp}; status: {git(repo, 'status', '--porcelain')}")

# Catches: test runs writing .pyc. The suite's fixtures import calc, so a run
# that writes bytecode leaves __pycache__/ — and a stale .pyc of broken code
# makes every later proof's baseline fail.
if not (repo / "__pycache__").exists():
    ok("the tool's build and test runs leave no bytecode behind")
else:
    bad("test runs must not write .pyc", list((repo / "__pycache__").iterdir()))

# ------------------------------------------------- fakes that must be refused
# Catches: a run whose test stays green under the break being recorded.
brk = patch(repo, "calc.py", "def sub(a, b):", "def sub(a, b):  # cosmetic")
r = claim(repo, plan, 2, brk)
if r.returncode == 1 and not rec(repo, plan, "claim", 2).exists() and "still PASSES" in r.stderr:
    ok("a break the test does not notice is refused, nothing recorded")
else:
    bad(f"a green-under-break run must be refused, exit {r.returncode}", r.stderr)

# Catches: test paths allowed in a break.
brk = patch(repo, "tests/test_calc.py", "assert add(2, 3) == 5", "assert add(2, 3) == 6")
r = claim(repo, plan, 1, brk)
if r.returncode == 1 and "test file" in r.stderr:
    ok("a break that edits the test instead of the code is refused")
else:
    bad(f"breaking the test must be refused, exit {r.returncode}", r.stderr)

# Catches: the build step skipped. A syntax error turns every test red for free.
brk = patch(repo, "calc.py", "return a + b", "return a +")
r = claim(repo, plan, 1, brk)
if r.returncode == 1 and "does not build" in r.stderr and tree_clean(repo):
    ok("a break that stops the build is refused, and the tree is restored")
else:
    bad(f"a non-building break must be refused, exit {r.returncode}", r.stderr)
r = claim(repo, plan, 1, brk, build=None)
if r.returncode == 2 and "--build" in r.stderr:
    ok("a claim with neither --build nor --no-build-step is a usage error")
else:
    bad(f"missing build step must exit 2, exit {r.returncode}", r.stderr)

# Catches: the baseline run dropped. A test that always fails is "red" for free.
brk = patch(repo, "calc.py", "return a + b", "return a - b")
FAILS = "python3 tests/test_calc.py && false"
repo_f, plan_f = world(FAILS)
r = claim(repo_f, plan_f, 1, patch(repo_f, "calc.py", "return a + b", "return a - b"), test=FAILS)
if r.returncode == 1 and "does not pass before the break" in r.stderr:
    ok("a test that fails before the break is refused")
else:
    bad(f"a failing baseline must be refused, exit {r.returncode}", r.stderr)

# Catches: proof taken on a tree that is not the one being committed.
(repo / "calc.py").write_text(CALC + "\n# unstaged\n")
r = claim(repo, plan, 1, brk)
(repo / "calc.py").write_text(CALC)
if r.returncode == 1 and "differs from the index" in r.stderr:
    ok("an unstaged change outside proof/ is refused")
else:
    bad(f"a dirty tree must be refused, exit {r.returncode}", r.stderr)
(repo / "stray.py").write_text("x = 1\n")
r = claim(repo, plan, 1, brk)
(repo / "stray.py").unlink()
if r.returncode == 1 and "untracked" in r.stderr:
    ok("an untracked file outside proof/ is refused")
else:
    bad(f"untracked files must be refused, exit {r.returncode}", r.stderr)

# Catches: restore not verified. The build step makes the file unwritable.
r = claim(repo, plan, 1, brk, build="chmod a-w calc.py")
os.chmod(repo / "calc.py", stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
if r.returncode == 3 and "RESTORE FAILED" in r.stderr:
    ok("a restore that cannot be completed exits 3, loudly")
else:
    bad(f"an unrestorable file must exit 3, exit {r.returncode}", r.stderr)
# The journal kept the originals: the next run restores them and stops.
r = claim(repo, plan, 1, brk)
if r.returncode == 3 and "interrupted" in r.stderr and (repo / "calc.py").read_text() == CALC:
    ok("the next run restores a failed restore's files from the journal, then stops (exit 3)")
else:
    bad(f"journal recovery must restore and stop, exit {r.returncode}", r.stderr)
# The journal restored the mode it saved — read-only, as that build left it.
os.chmod(repo / "calc.py", stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

# Catches: the restore putting back the ORIGINAL mtime. A build that only
# rebuilds when the source is newer than its output (make, cargo, here a
# copy-if-newer) would then keep the output built from the BROKEN code, and the
# next proof's baseline fails. The restored file must be newer than that output.
cin = "test out.py -nt calc.py || cp calc.py out.py"
tst = cin + " && python3 -c 'import out; assert out.add(2, 3) == 5'"
repo2, plan2 = world(tst)
(repo2 / ".gitignore").write_text("__pycache__/\nout.py\n")
git(repo2, "add", ".gitignore")
git(repo2, "commit", "-q", "-m", "ignore out.py")
brk2 = patch(repo2, "calc.py", "return a + b", "return a - b")
r1 = claim(repo2, plan2, 1, brk2, test=tst, build=cin)
r2 = claim(repo2, plan2, 1, brk2, test=tst, build=cin)
if r1.returncode == 0 and r2.returncode == 0:
    ok("a copy-if-newer build is rebuilt after the restore (a second proof's baseline passes)")
else:
    bad(f"the restore must leave the source newer than the broken build, exits "
        f"{r1.returncode}/{r2.returncode}", r2.stderr)

r = claim(repo, plan, 9, brk)
if r.returncode == 2 and "does not exist" in r.stderr:
    ok("a claim number the task does not have is a usage error")
else:
    bad(f"out-of-range claim must exit 2, exit {r.returncode}", r.stderr)

# ------------------------------------------------- attacks on the proof itself
print()
print("guards against a fabricated proof")

# Catches: --test free text. `git diff --quiet` goes red for ANY break.
r = claim(repo, plan, 1, brk, test="git diff --quiet && python3 tests/test_calc.py")
if r.returncode == 1 and "written in Task 1.1's `Test:` field" in r.stderr:
    ok("a test command the plan does not name is refused")
else:
    bad(f"a free-form --test must be refused, exit {r.returncode}", r.stderr)

# Catches: a trivial build accepted as the build step.
r = claim(repo, plan, 1, brk, build="true")
if r.returncode == 2 and "builds nothing" in r.stderr:
    ok("--build true is a usage error")
else:
    bad(f"a trivial build must be refused, exit {r.returncode}", r.stderr)

# Catches: shapes the restore cannot undo. A rename, a new file, a mode change.
def raw_patch(text):
    p = repo.parent / f"raw-{len(list(repo.parent.glob('raw-*')))}.patch"
    p.write_text(text)
    return p
ren = raw_patch("diff --git a/calc.py b/calc2.py\nsimilarity index 100%\nrename from calc.py\nrename to calc2.py\n")
new = raw_patch("diff --git a/extra.py b/extra.py\nnew file mode 100644\n--- /dev/null\n+++ b/extra.py\n@@ -0,0 +1 @@\n+x = 1\n")
mode = raw_patch("diff --git a/calc.py b/calc.py\nold mode 100644\nnew mode 100755\n")
for label, p in (("a rename", ren), ("a new file", new), ("a mode change", mode)):
    r = claim(repo, plan, 1, p)
    if r.returncode == 1 and "content of existing files" in r.stderr and tree_clean(repo):
        ok(f"a break that is {label} is refused, tree untouched")
    else:
        bad(f"{label} must be refused, exit {r.returncode}", r.stderr)

# Catches: TEST_PATH evaded through C-quoting. Without -z, --numstat returns a
# non-ASCII test file name as "tests/caf\303\251.py", which an anchored match misses.
(repo / "tests" / "café_test.py").write_text("x = 1\n")
git(repo, "add", "-A")
q = patch(repo, "tests/café_test.py", "x = 1", "x = 2")
r = claim(repo, plan, 1, q)
git(repo, "rm", "-q", "--cached", "tests/café_test.py")
(repo / "tests" / "café_test.py").unlink()
if r.returncode == 1 and "test file" in r.stderr:
    ok("a break of a non-ASCII test file is refused as a test-file break")
else:
    bad(f"quoted paths must not evade the test-file guard, exit {r.returncode}", r.stderr)

# Catches: an index flag hiding a change. assume-unchanged makes `git diff` blind.
(repo / "calc.py").write_text(CALC + "# hidden\n")
git(repo, "update-index", "--assume-unchanged", "calc.py")
r = claim(repo, plan, 1, brk)
git(repo, "update-index", "--no-assume-unchanged", "calc.py")
(repo / "calc.py").write_text(CALC)
if r.returncode == 1 and "assume-unchanged" in r.stderr:
    ok("an assume-unchanged entry is refused")
else:
    bad(f"index flags must be refused, exit {r.returncode}", r.stderr)

# Catches: proof/ as a hiding place. It is excluded from every check.
(repo / "proof" / "helper.py").parent.mkdir(exist_ok=True)
(repo / "proof" / "helper.py").write_text("x = 1\n")
r = claim(repo, plan, 1, brk)
(repo / "proof" / "helper.py").unlink()
if r.returncode == 1 and "proof records only" in r.stderr:
    ok("a non-record file under proof/ is refused")
else:
    bad(f"proof/ must hold records only, exit {r.returncode}", r.stderr)

# Catches: red that is "could not run". Under the break the test is not found.
# `a + b` is absent only under the break (sub's `a - b` is there all along).
NF = "grep -q 'a + b' calc.py || exit 127; python3 tests/test_calc.py"
repo_n, plan_n = world(NF)
r = claim(repo_n, plan_n, 1, patch(repo_n, "calc.py", "return a + b", "return a - b"), test=NF)
if r.returncode == 1 and "could not RUN" in r.stderr:
    ok("a test that exits 127 under the break is not counted as red")
else:
    bad(f"exit 127 must not be red, exit {r.returncode}", r.stderr)

# Catches: no post-run check. The test leaves a file behind under the break.
LEAK = "grep -q 'a + b' calc.py || touch leaked.txt; python3 tests/test_calc.py"
repo_l, plan_l = world(LEAK)
r = claim(repo_l, plan_l, 1, patch(repo_l, "calc.py", "return a + b", "return a - b"), test=LEAK)
if r.returncode == 3 and "not as it was" in r.stderr and not rec(repo_l, plan_l, "claim", 1).exists():
    ok("a test that leaves the tree changed fails the proof (exit 3), no record")
else:
    bad(f"a changed tree after the proof must exit 3, exit {r.returncode}", r.stderr)

# Catches: no journal. The tool itself is killed with the break applied.
KILL = "grep -q 'a + b' calc.py || kill -9 $PPID; python3 tests/test_calc.py"
repo_k, plan_k = world(KILL)
r = claim(repo_k, plan_k, 1, patch(repo_k, "calc.py", "return a + b", "return a - b"), test=KILL)
broken_after_kill = "a + b" not in (repo_k / "calc.py").read_text()
r2 = claim(repo_k, plan_k, 1, brk, test=KILL)
if (r.returncode == -9 and broken_after_kill and r2.returncode == 3 and "interrupted" in r2.stderr
        and (repo_k / "calc.py").read_text() == CALC):
    ok("a run killed mid-break leaves a journal; the next run restores the tree and stops")
else:
    bad(f"SIGKILL recovery, exits {r.returncode}/{r2.returncode}, broken={broken_after_kill}",
        r2.stderr)

# Catches: a timeout that kills only the shell. The test's grandchild (here a
# sleep) keeps the output pipe open and keeps running after the restore.
HANG = "grep -q 'a + b' calc.py || sleep 30; python3 tests/test_calc.py"
repo_h, plan_h = world(HANG)
t0 = time.monotonic()
r = claim(repo_h, plan_h, 1, patch(repo_h, "calc.py", "return a + b", "return a - b"),
          "--timeout", "5", test=HANG)
took = time.monotonic() - t0
if r.returncode == 1 and "hung" in r.stderr and took < 12:
    ok(f"a hung test's whole process group dies at the timeout ({took:.0f}s)")
else:
    bad(f"timeout must kill the process group, exit {r.returncode}, took {took:.0f}s", r.stderr)

# ------------------------------------------------------------------ task-test cost
print()
print("a task test's elapsed time is recorded, and a test over its budget is a stop")
# Catches: the elapsed time missing from a record — nothing measures what a task test
# costs, so a task test running for hours is noticed by a person, not a tool.
repo_e, plan_e = world()
r = claim(repo_e, plan_e, 1, patch(repo_e, "calc.py", "return a + b", "return a - b"))
data = json.loads(rec(repo_e, plan_e, "claim", 1).read_text()) if rec(repo_e, plan_e, "claim", 1).is_file() else {}
el = [data.get(k, {}).get("elapsed_s") for k in ("baseline", "red")]
if r.returncode == 0 and all(isinstance(x, (int, float)) and x >= 0 for x in el):
    ok(f"a record carries elapsed_s for the baseline and the break run ({el})")
else:
    bad(f"a record must carry elapsed_s for both runs (red if either is missing); got {el}",
        r.stderr)

# Catches: a test slower than --timeout recorded as proven, or refused as an ordinary
# NOT PROVEN — the budget's stop must be distinguishable from a failed claim.
SLOW = "sleep 8; python3 tests/test_calc.py"
repo_s, plan_s = world(SLOW)
r = claim(repo_s, plan_s, 1, patch(repo_s, "calc.py", "return a + b", "return a - b"),
          "--timeout", "3", test=SLOW)
# (and the tree as it was: the stop comes before the break is applied)
if r.returncode == 4 and "over --timeout" in r.stderr and not rec(repo_s, plan_s, "claim", 1).exists() \
        and tree_clean(repo_s):
    ok("a test over --timeout writes no record and exits 4 (the task-test budget is spent)")
else:
    bad(f"a test over --timeout must exit 4 with no record (red if a slow test is recorded "
        f"as proven); exit {r.returncode}", r.stderr)

# Catches: the budget rule missing from where the executor and the plan author read it.
REFS = HERE.parent / "references"
TIERS = HERE.parents[1] / "planning-projects" / "references" / "test-scope-tiers.md"
te = (REFS / "task-execution.md").read_text(encoding="utf-8")
budget = te[te.find("## A task test has a time budget"):]
budget = budget[: budget.find("\n## ", 5)] if "\n## " in budget[5:] else budget
for what, pat in (("the 300 s default", r"300\s+s\s+by\s+default"),
                  ("the Preflight override line", r"`task-test budget: N s`"),
                  ("prove-claim.py --timeout", r"--timeout"),
                  ("the Stop condition", r"Stop\s+condition"),
                  ("the blocked phase note", r'`phase: "blocked"`'),
                  ("never narrowing the test", r"never\s+narrowed\s+to\s+fit")):
    if budget and re.search(pat, budget, re.S):
        ok(f"task-execution.md § A task test has a time budget names {what}")
    else:
        bad(f"the task-test budget rule must name {what} (red if it is missing)")
# The mutation battery runs this suite in a copy holding only the executing-plans skill and
# the hooks, so test-scope-tiers.md is absent there; in the repo it is always present.
if not TIERS.is_file():
    print("  note  test-scope-tiers.md not in this tree (a battery copy) — checked in the repo")
elif "`task-test budget: N s`" in TIERS.read_text(encoding="utf-8"):
    ok("test-scope-tiers.md documents the `task-test budget: N s` override line")
else:
    bad("test-scope-tiers.md must document the `task-test budget: N s` line")

# ------------------------------------------------- safe recovery, honest red
print()
print("recovery only where it is safe; red only when the test really failed")

# Catches: recovery overwriting blindly. A run is killed with the break applied;
# the user then stages their own fix. The journal no longer matches: not restored.
repo_j, plan_j = world(KILL)
r = claim(repo_j, plan_j, 1, patch(repo_j, "calc.py", "return a + b", "return a - b"), test=KILL)
mine = CALC + "# the user's own fix, staged\n"
(repo_j / "calc.py").write_text(mine)
subprocess.run(["git", "-C", str(repo_j), "add", "calc.py"], check=True)
r2 = run("fingerprint", "--repo", str(repo_j))
if (r.returncode == -9 and r2.returncode == 3 and "NOT restored" in r2.stderr
        and (repo_j / "calc.py").read_text() == mine
        and (repo_j / ".git" / "prove-claim-journal.json").exists()):
    ok("a journal whose files changed since it was written is not restored (exit 3, kept)")
else:
    bad(f"recovery must refuse a moved repo, exits {r.returncode}/{r2.returncode}", r2.stderr)

# Catches: a second run recovering — reverting — a live run's break.
repo_l2, plan_l2 = world()
(repo_l2 / ".git" / "prove-claim-journal.json").write_text('{"sentinel": true}')
holder = subprocess.Popen([sys.executable, "-c",
                           "import fcntl, sys, time; f = open(sys.argv[1], 'w'); "
                           "fcntl.flock(f, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)",
                           str(repo_l2 / ".git" / "prove-claim.lock")], stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
r = run("fingerprint", "--repo", str(repo_l2))
holder.kill()
holder.wait()
if (r.returncode == 2 and "holds the lock" in r.stderr
        and (repo_l2 / ".git" / "prove-claim-journal.json").read_text() == '{"sentinel": true}'):
    ok("a second run while one holds the lock exits 2 without touching its journal")
else:
    bad(f"runs must be exclusive, exit {r.returncode}", r.stderr)
(repo_l2 / ".git" / "prove-claim-journal.json").unlink()

# Catches: a syntax-error break counted as red when nothing builds.
repo_s, plan_s = world()
r = claim(repo_s, plan_s, 1, patch(repo_s, "calc.py", "def add(a, b):", "def add(a, b:"),
          "--no-build-step", "python, nothing to build", build=None)
if r.returncode == 1 and "unparseable" in r.stderr and tree_clean(repo_s):
    ok("a syntax-error break under --no-build-step is refused, tree restored")
else:
    bad(f"a non-parsing break must be refused, exit {r.returncode}", r.stderr)

# Catches: a killed test (128+n, as a shell reports SIGKILL) counted as red.
K137 = "grep -q 'a + b' calc.py || exit 137; python3 tests/test_calc.py"
repo_k2, plan_k2 = world(K137)
r = claim(repo_k2, plan_k2, 1, patch(repo_k2, "calc.py", "return a + b", "return a - b"), test=K137)
if r.returncode == 1 and "could not RUN" in r.stderr:
    ok("exit 137 under the break is not counted as red")
else:
    bad(f"exit 137 must not be red, exit {r.returncode}", r.stderr)

# Catches: breaking the test runner. The plan's test runs run.sh; the break edits it.
RUNNER = "bash run.sh"
repo_r, plan_r = world(RUNNER)
(repo_r / "run.sh").write_text("python3 tests/test_calc.py\n")
subprocess.run(["git", "-C", str(repo_r), "add", "run.sh"], check=True)
subprocess.run(["git", "-C", str(repo_r), "commit", "-q", "-m", "runner"], check=True, env=GIT_ENV)
r = claim(repo_r, plan_r, 1, patch(repo_r, "run.sh", "python3 tests/test_calc.py", "exit 1"),
          test=RUNNER)
if r.returncode == 1 and "which the test command runs" in r.stderr:
    ok("a break of the script the test command runs is refused")
else:
    bad(f"the test runner must not be breakable, exit {r.returncode}", r.stderr)

# Catches: test trees the path rule did not know.
_spec = importlib.util.spec_from_file_location("pc_paths", SCRIPT)
_pcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pcp)
wider = ["src/commonTest/kotlin/A.kt", "app/src/jvmTest/B.kt", "Tests/AppTests/Helper.swift",
         "testdata/in.json", "pkg/fixtures/x.txt"]
if all(_pcp.TEST_PATH.search(p) for p in wider) and not _pcp.TEST_PATH.search("src/main/Contest.kt"):
    ok("source sets *Test/, Tests/, testdata/ and fixtures/ count as test paths")
else:
    bad("TEST_PATH must cover the wider test trees",
        [p for p in wider if not _pcp.TEST_PATH.search(p)])

# Catches: the evaluation ledger's committed files refused as "not a proof record"
# (a tracked proof/ would make every commit carrying them unmergeable), or its lock
# and temporary files admitted.
ledger_paths = ["proof/p/evaluation/exp-a.jsonl", "proof/p/originals/result-1.json"]
never = ["proof/p/evaluation/exp-a.lock", "proof/p/evaluation/.evaluation-0123abcd",
         "proof/p/evaluation/exp-a.json", "proof/p/originals/result-1.jsonl",
         "proof/p/evaluation/sub/exp-a.jsonl", "proof/p/originals/.hidden.json"]
if all(_pcp.RECORD_PATH.match(p) for p in ledger_paths) and \
        not any(_pcp.RECORD_PATH.match(p) for p in never):
    ok("the evaluation ledger and its original receipts are records; its lock and temps are not")
else:
    bad("RECORD_PATH must admit the ledger's committed files and nothing else beside them",
        [p for p in ledger_paths if not _pcp.RECORD_PATH.match(p)]
        + [p for p in never if _pcp.RECORD_PATH.match(p)])

# ------------------------------------------------- requirements and deviations
print()
print("req / deviation / replay")
base = ["--repo", str(repo), "--plan", str(plan), "--task", "1.1"]
unimportable = patch(repo, "calc.py", "def add(a, b):", "raise ImportError('broken')\n\n\ndef add(a, b):")
r = run("req", *base, "--req", "3", "--check", "python3 -c 'import calc'", "--break",
        str(unimportable), "--build", BUILD_OK)
r3 = json.loads(rec(repo, plan, "req", 3).read_text()) if rec(repo, plan, "req", 3).is_file() else {}
if r.returncode == 0 and r3.get("red", {}).get("exit") not in (None, 0) and r3.get("schema") == 2:
    ok("a requirement whose check passes, and fails under its break, is recorded (schema 2)")
else:
    bad(f"a check proven by a break must record, exit {r.returncode}", r.stderr)
# Catches: a failing check recorded as met.
r = run("req", *base, "--req", "2", "--check", "python3 -c 'import calc; assert calc.sub(5,3)==3'",
        "--break", str(unimportable), "--build", BUILD_OK)
if r.returncode == 1 and not rec(repo, plan, "req", 2).exists() and "does not pass before" in r.stderr:
    ok("a requirement whose check fails is refused, nothing recorded")
else:
    bad(f"failing req check must be refused, exit {r.returncode}", r.stderr)
# Catches: a check that cannot fail recorded as evidence.
r = run("req", *base, "--req", "2", "--check", "echo ok", "--break", str(unimportable),
        "--build", BUILD_OK)
if r.returncode == 1 and "still PASSES" in r.stderr and not rec(repo, plan, "req", 2).exists():
    ok('req --check "echo ok" is refused: it passes under the break too')
else:
    bad(f"a check that cannot fail must be refused, exit {r.returncode}", r.stderr)
r = run("req", *base, "--req", "2", "--check", "python3 -c 'import calc'")
if r.returncode == 2 and "needs --break" in r.stderr:
    ok("req --check without a break is a usage error")
else:
    bad(f"--check without --break must be refused, exit {r.returncode}", r.stderr)
# Catches: a dangling covered-by-claim reference accepted.
r = run("req", *base, "--req", "2", "--covered-by-claim", "2")
if (r.returncode == 1 and not rec(repo, plan, "req", 2).exists()
        and "not a valid proof" in r.stderr):
    ok("covered-by-claim pointing at an unproven claim is refused")
else:
    bad(f"dangling claim reference must be refused, exit {r.returncode}", r.stderr)
r = run("req", *base, "--req", "1", "--covered-by-claim", "1")
if r.returncode == 0 and json.loads(rec(repo, plan, "req", 1).read_text()).get("covered_by_claim") == 1:
    ok("covered-by-claim pointing at a valid proof of this tree is recorded")
else:
    bad(f"valid claim reference must record, exit {r.returncode}", r.stderr)
r = run("req", *base, "--req", "2", "--check", "true")
if r.returncode == 2 and "checks nothing" in r.stderr:
    ok("req --check true is a usage error")
else:
    bad(f"a trivial check must be refused, exit {r.returncode}", r.stderr)

r = run("deviation", *base, "--req", "2", "--why", "short")
if r.returncode == 2:
    ok("a deviation without a real reason is a usage error")
else:
    bad(f"empty deviation reason must exit 2, exit {r.returncode}", r.stderr)
r = run("deviation", *base, "--req", "2", "--why", "sub is checked by claim 2, which no break can isolate yet")
if r.returncode == 0 and rec(repo, plan, "deviation", 2).is_file():
    ok("a deviation with its reason is recorded")
else:
    bad(f"deviation must record, exit {r.returncode}", r.stderr)

r = run("replay", "--repo", str(repo), "--plan", str(plan), "--task", "1.1")
if r.returncode == 0 and "still turns the test red" in r.stdout and tree_clean(repo):
    ok("replay re-runs a valid record's break and it still bites")
else:
    bad(f"replay of a valid record must pass, exit {r.returncode}", r.stdout + r.stderr)
# Catches: replay that only re-reads the JSON. Weaken the test so add is
# never checked: the recorded break no longer turns it red.
(repo / "tests" / "test_calc.py").write_text(TEST.replace("assert add(2, 3) == 5\n", ""))
git(repo, "add", "tests/test_calc.py")
r = run("replay", "--repo", str(repo), "--plan", str(plan), "--task", "1.1")
if r.returncode == 1 and "FAIL" in r.stdout and "still PASSES" in r.stdout:
    ok("replay fails once the test no longer catches the recorded break")
else:
    bad(f"replay must re-run, not re-read, exit {r.returncode}", r.stdout + r.stderr)

# ------------------------------------------------- claim deviations
# A claim no repo patch can break — its evidence lives outside the repo (a file
# in another folder, a device) — is disclosed with `deviation --claim K --why TEXT`: stored at
# claim-K.json as kind "claim-deviation", reported by the audit, never proof.
print()
print("claim deviations — disclosed, never silent")
repo_d, plan_d = world()
base_d = ["--repo", str(repo_d), "--plan", str(plan_d), "--task", "1.1"]
# Catches: a claim waived silently. No reason, no record.
r = run("deviation", *base_d, "--claim", "2", "--why", "short")
if r.returncode == 2 and not rec(repo_d, plan_d, "claim", 2).exists():
    ok("a claim deviation without a reason is refused, nothing recorded")
else:
    bad(f"a reasonless claim deviation must be refused, exit {r.returncode}", r.stderr)
r = run("deviation", *base_d, "--claim", "2", "--why", "sub is checked on the device, outside this repo")
cd = json.loads(rec(repo_d, plan_d, "claim", 2).read_text()) if rec(repo_d, plan_d, "claim", 2).is_file() else {}
if (r.returncode == 0 and cd.get("kind") == "claim-deviation"
        and cd.get("text") == "sub returns the difference" and "outside this repo" in cd.get("why", "")):
    ok("a claim deviation with its reason is recorded at claim-K.json, kind claim-deviation")
else:
    bad(f"a claim deviation must record, exit {r.returncode}", r.stderr + json.dumps(cd)[:300])
r = run("deviation", *base_d, "--claim", "9", "--why", "a claim the task does not have at all")
if r.returncode == 2 and "claim 9 does not exist" in r.stderr:
    ok("a claim deviation for a claim the task does not have is a usage error")
else:
    bad(f"claim number must exist, exit {r.returncode}", r.stderr)
r = run("deviation", *base_d, "--why", "neither a requirement nor a claim named")
if r.returncode == 2:
    ok("deviation needs --req or --claim")
else:
    bad(f"deviation with no target must be a usage error, exit {r.returncode}", r.stderr)
# Catches: a claim deviation used as proof. A requirement "covered by" claim 2,
# which is only disclosed, is not covered.
r = run("req", *base_d, "--req", "2", "--covered-by-claim", "2")
if r.returncode == 1 and "claim deviation" in r.stderr and not rec(repo_d, plan_d, "req", 2).exists():
    ok("req --covered-by-claim refuses a claim recorded as a deviation")
else:
    bad(f"a claim deviation must not cover a requirement, exit {r.returncode}", r.stderr)
# Replay re-runs breaks; a claim deviation has none and is not a failure.
r = run("replay", "--repo", str(repo_d), "--plan", str(plan_d), "--task", "1.1")
if r.returncode == 0 and "claim deviation" in r.stdout:
    ok("replay reports a claim deviation as such, not as a failed replay")
else:
    bad(f"replay must skip claim deviations, exit {r.returncode}", r.stdout + r.stderr)

# ------------------------------------------------- the shared validator
print()
print("validate() — what the audit and the hook check a record with")
sys.path.insert(0, str(SCRIPT.parent))
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("prove_claim", SCRIPT)
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)
good = json.loads(rec(repo, plan, "claim", 1).read_text())
if pc.validate(good) == []:
    ok("a tool-written claim record validates")
else:
    bad("tool-written record must validate", pc.validate(good))
forged = dict(good, red={"exit": 0, "tail": ""})
if any("did not fail" in p for p in pc.validate(forged)):
    ok("a hand-edited record with red exit 0 is rejected")
else:
    bad("red exit 0 must be rejected", pc.validate(forged))
if any("different tree" in p for p in pc.validate(good, "0" * 64)):
    ok("a record checked against another fingerprint is rejected")
else:
    bad("fingerprint mismatch must be rejected", pc.validate(good, "0" * 64))
# Catches: a record copied to another name, or proven against old wording.
if any("not Task 1.1 #2" in p for p in pc.validate(good, None, ("claim", "1.1", 2, None))):
    ok("claim-1's record stored as claim-2 is rejected")
else:
    bad("a record at the wrong path must be rejected", pc.validate(good, None, ("claim", "1.1", 2, None)))
if any("different wording" in p for p in pc.validate(good, None, ("claim", "1.1", 1, "reworded"))):
    ok("a record proven against wording the plan no longer has is rejected")
else:
    bad("reworded claim must be rejected", "")
if any("stored as a 'claim'" in p for p in pc.validate(dict(good, kind="deviation", why="x" * 20), None, ("claim", "1.1", 1, None))):
    ok("a deviation stored as claim-1.json is rejected")
else:
    bad("kind/path mismatch must be rejected", "")
# A claim deviation stored at claim-K.json validates as a record (the hook lets
# a disclosed claim through); without a reason it does not.
cdev = json.loads(rec(repo_d, plan_d, "claim", 2).read_text())
cexp = ("claim", "1.1", 2, "sub returns the difference")
if pc.validate(cdev, None, cexp) == [] and any("without a reason" in p for p in
                                               pc.validate(dict(cdev, why=""), None, cexp)):
    ok("validate() accepts a reasoned claim deviation at claim-K.json, rejects a reasonless one")
else:
    bad("claim deviations must validate by their reason", pc.validate(dict(cdev, why=""), None, cexp))
# Catches: `False != 0` is False, `True` is an int — booleans must not pass.
if any("baseline" in p for p in pc.validate(dict(good, baseline={"exit": False}))) and \
        any("did not fail" in p for p in pc.validate(dict(good, red={"exit": True}))):
    ok("boolean exit codes are rejected")
else:
    bad("booleans must not pass as exit codes", "")
# Catches: validate() crashing on a record's shape — a crash is a record no caller judged.
odd = [dict(good, baseline="x"), dict(good, red=[1]), dict(good, touched="calc.py"),
       {"schema": 1, "kind": "req", "check": "x", "result": 5, "fingerprint": good["fingerprint"]}]
try:
    outs = [pc.validate(o, allow_legacy=True) for o in odd]
    if all(outs):
        ok("validate() reports wrong-typed fields as problems, never raises")
    else:
        bad("every odd record must have problems", outs)
except Exception as e:  # noqa: BLE001
    bad(f"validate() raised {e.__class__.__name__} on a malformed record", e)

# Catches: a req check that was never seen to fail. Schema 2 needs the run;
# schema 1 passes only where the caller allows legacy (the audit, advisory).
bare = {"schema": 2, "kind": "req", "task": "1.1", "index": 1, "text": "x",
        "check": "python3 tests/test_calc.py", "result": {"exit": 0, "tail": ""},
        "fingerprint": good["fingerprint"]}
if any("did not fail" in p or "no break" in p for p in pc.validate(bare)):
    ok("a schema-2 req record with a bare passing check is rejected")
else:
    bad("a bare schema-2 req check must be rejected", pc.validate(bare))
legacy = dict(bare, schema=1)
if pc.validate(legacy) and pc.validate(legacy, allow_legacy=True) == []:
    ok("a schema-1 req check is rejected unless the caller allows legacy")
else:
    bad("legacy req checks: rejected by default, accepted only with allow_legacy",
        (pc.validate(legacy), pc.validate(legacy, allow_legacy=True)))

# Catches: host and plugin state at the repo's top-level .claude/ blocking every
# proof in a repo that does not ignore .claude/. The host and its plugins write
# there on their own (the progress cache, another plugin's sidecar); none of it
# is the change being proven. Only that one folder is exempt.
srepo, splan = world()
sbrk = patch(srepo, "calc.py", "a + b", "a - b")
(srepo / ".claude").mkdir()
(srepo / ".claude" / "plan-progress-cache.json").write_text("{}\n")
(srepo / ".claude" / "other-plugin-sidecar.md").write_text("# sidecar\n")
r = claim(srepo, splan, 1, sbrk)
if r.returncode == 0:
    ok("untracked host and plugin state under the top-level .claude/ does not block a proof")
else:
    bad(f"untracked .claude/ state must not block a proof, exit {r.returncode}", r.stderr)
for stray in ("sub/.claude/state.json", ".claude-notes.md"):
    p = srepo / stray
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n")
    r = claim(srepo, splan, 1, sbrk)
    p.unlink()
    if r.returncode == 1 and "untracked" in r.stderr:
        ok(f"an untracked {stray} is still refused")
    else:
        bad(f"an untracked {stray} must still be refused, exit {r.returncode}", r.stderr)

# Catches: a break location the caller cannot find out from the tool itself. A session that
# reads only `--help` must learn that --break takes a FILE and where one may live, and one that
# passes the diff inline must be told the same.
for sub in ("claim", "req"):
    r = run(sub, "--help")
    if r.returncode == 0 and ".claude/" in r.stdout and "FILE" in r.stdout:
        ok(f"`{sub} --help` says --break takes a file and names the repo's .claude/")
    else:
        bad(f"`{sub} --help` must name a file in the repo's .claude/ for --break", r.stdout[-400:])
r = claim(srepo, splan, 1, Path("--- a/calc.py +++ b/calc.py"))
if r.returncode == 2 and "not the diff" in r.stderr and ".claude/" in r.stderr:
    ok("an inline diff given as --break is refused with where the file goes")
else:
    bad(f"an inline diff as --break must say to write a file under .claude/, exit {r.returncode}", r.stderr)

# Catches: help that claims every host can write the repo's .claude/ (Claude Code asks
# before each write there), and help that names no place outside the work tree.
for sub in ("claim", "req"):
    h = " ".join(run(sub, "--help").stdout.split())
    if "every host" not in h and "TMPDIR" in h and "resolves against --repo" in h:
        ok(f"`{sub} --help` names $TMPDIR, says a relative path resolves against --repo, claims no host-wide write")
    else:
        bad(f"`{sub} --help` must name $TMPDIR, the --repo resolution, and not claim every host writes .claude/", h[-500:])

# Catches: a relative --break such as .claude/break-1.patch refused because the caller's cwd
# is not the repo. It resolves against --repo when it does not exist from the cwd.
rrepo, rplan = world()
rdiff = patch(rrepo, "calc.py", "a + b", "a - b")
(rrepo / ".claude").mkdir()
(rrepo / ".claude" / "break-rel.patch").write_text(rdiff.read_text())
r = run("claim", "--repo", str(rrepo), "--plan", str(rplan), "--task", "1.1", "--claim", "1",
        "--break", ".claude/break-rel.patch", "--test", "python3 tests/test_calc.py",
        "--build", BUILD_OK, cwd=str(rplan.parent))
if r.returncode == 0 and rec(rrepo, rplan, "claim", 1).is_file():
    ok("a relative .claude/ --break given from another cwd resolves against --repo")
else:
    bad(f"a relative --break missing from the cwd must resolve against --repo, exit {r.returncode}", r.stderr)
r = run("claim", "--repo", str(rrepo), "--plan", str(rplan), "--task", "1.1", "--claim", "1",
        "--break", ".claude/no-such.patch", "--test", "python3 tests/test_calc.py",
        "--build", BUILD_OK, cwd=str(rplan.parent))
if r.returncode == 2 and "not found" in r.stderr and ".claude/" in r.stderr:
    ok("a relative --break found under neither the cwd nor --repo is still refused with the hint")
else:
    bad(f"a missing relative --break must be refused with the hint, exit {r.returncode}", r.stderr)

for d in _tmp:
    shutil.rmtree(d, ignore_errors=True)
print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
