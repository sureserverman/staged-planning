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
import base64
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

# Catches: a read-only file left broken. The build makes the file
# unwritable, before the break and again under it; the restore still writes the
# original bytes back and keeps the read-only mode it saved.
rorepo, roplan = world()
r = claim(rorepo, roplan, 1, patch(rorepo, "calc.py", "a + b", "a - b"), build="chmod a-w calc.py")
romode = stat.S_IMODE((rorepo / "calc.py").stat().st_mode)
os.chmod(rorepo / "calc.py", stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
if r.returncode == 0 and romode & 0o222 == 0 and (rorepo / "calc.py").read_text() == CALC:
    ok("a read-only file is broken and restored, its read-only mode kept")
else:
    bad(f"a read-only file must be restored with its mode, exit {r.returncode}, "
        f"mode {oct(romode)}", r.stderr)

# Catches: restore not verified. Under the break the build puts a directory where the
# file was, so no write can put the file back.
GONE = "grep -q 'a + b' calc.py || { rm -f calc.py; mkdir calc.py; }"
r = claim(repo, plan, 1, brk, build=GONE)
if (repo / "calc.py").is_dir():
    (repo / "calc.py").rmdir()
if r.returncode == 3 and "RESTORE FAILED" in r.stderr:
    ok("a restore that cannot be completed exits 3, loudly")
else:
    bad(f"an unrestorable file must exit 3, exit {r.returncode}", r.stderr)
# The journal kept the originals: the next run restores them and stops — onto a file
# a later step left read-only, which is what recovery meets after a partial restore.
(repo / "calc.py").write_text("broken\n")
os.chmod(repo / "calc.py", stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
r = claim(repo, plan, 1, brk)
os.chmod(repo / "calc.py", stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
if r.returncode == 3 and "interrupted" in r.stderr and (repo / "calc.py").read_text() == CALC:
    ok("the next run restores a failed restore's files from the journal, even read-only, then stops (exit 3)")
else:
    bad(f"journal recovery must restore and stop, exit {r.returncode}", r.stderr)

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
if r.returncode == 1 and "could not RUN" in r.stderr and "killed by signal 9" in r.stderr:
    ok("exit 137 under the break is not counted as red, and the refusal names signal 9")
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

# Catches: the runner hidden behind shell syntax. The program of each form is the
# word after `{`, `(`, `!`, `if`, or a wrapper (`timeout N`, `env A=1`, `time`);
# taking the first word records the syntax, and a break of the real runner passes.
T_PY = "exec(open('tests/test_calc.py').read())\n"
T_SH = "python3 tests/test_calc.py\n"
SYNTAX_FORMS = [
    ("{ python3 t.py; }", "python3", "t.py"),
    ("( bash t.sh )", "bash", "t.sh"),
    ("if python3 t.py; then exit 0; else exit 1; fi", "python3", "t.py"),
    ("timeout 60 python3 t.py", "python3", "t.py"),
    ("env A=1 python3 t.py", "python3", "t.py"),
    ("time python3 t.py", "python3", "t.py"),
]


def with_files(repo, files):
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "add", *files)
    git(repo, "commit", "-q", "-m", "runner")


for form, _prog, script in SYNTAX_FORMS:
    if form.startswith("timeout ") and not shutil.which("timeout"):
        ok(f"skipped `{form}`: no timeout on this host (stock macOS ships gtimeout)")
        continue
    repo_f, plan_f = world(form)
    with_files(repo_f, {"t.py": T_PY, "t.sh": T_SH})
    brk_f = (patch(repo_f, "t.py", "exec(", "raise SystemExit(1)\nexec(") if script == "t.py"
             else patch(repo_f, "t.sh", "python3 tests/test_calc.py", "exit 1"))
    r = claim(repo_f, plan_f, 1, brk_f, test=form)
    if r.returncode == 1 and f"edits {script}, which the test command runs" in r.stderr:
        ok(f"a break of {script} under `{form}` is refused as a break of the runner")
    else:
        bad(f"the runner behind `{form}` must not be breakable, exit {r.returncode}",
            r.stdout + r.stderr)

# Catches: the runner rule grown too wide. grep merely NAMES calc.py, so a break of
# calc.py under `! grep …` is an honest break, proven.
NEG = "! grep -q 'a [*] b' calc.py"
repo_g, plan_g = world(NEG)
r = claim(repo_g, plan_g, 1, patch(repo_g, "calc.py", "return a + b", "return a * b"), test=NEG)
if r.returncode == 0 and rec(repo_g, plan_g, "claim", 1).is_file():
    ok("a break of a file `! grep` only reads is proven, not refused as the runner")
else:
    bad(f"a file grep names is not its runner, exit {r.returncode}", r.stdout + r.stderr)

# Catches: a break of the runner's own definition file. `make test` runs the recipe
# the Makefile holds, `npm test` the script package.json holds.
for runner, rel, text, old, new in [
        ("make test", "Makefile", "test:\n\tpython3 tests/test_calc.py\n",
         "\tpython3 tests/test_calc.py", "\texit 1"),
        ("npm test", "package.json",
         '{"name": "calc", "scripts": {"test": "python3 tests/test_calc.py"}}\n',
         '"python3 tests/test_calc.py"', '"exit 1"')]:
    repo_m, plan_m = world(runner)
    with_files(repo_m, {rel: text})
    r = claim(repo_m, plan_m, 1, patch(repo_m, rel, old, new), test=runner)
    if r.returncode == 1 and f"edits {rel}, the file `{runner.split()[0]}` reads" in r.stderr:
        ok(f"a break of {rel} under `{runner}` is refused, naming the runner file")
    else:
        bad(f"the {rel} behind `{runner}` must not be breakable, exit {r.returncode}",
            r.stdout + r.stderr)

# Catches: every exit of 128 or more read as a signal death. 255 is an ordinary
# red (a test calling exit(-1), ssh's own error exit); only 129..192 is 128+signal.
R255 = "grep -q 'a + b' calc.py || exit 255; python3 tests/test_calc.py"
repo_e, plan_e = world(R255)
r = claim(repo_e, plan_e, 1, patch(repo_e, "calc.py", "return a + b", "return a - b"), test=R255)
red255 = (json.loads(rec(repo_e, plan_e, "claim", 1).read_text()).get("red", {}).get("exit")
          if rec(repo_e, plan_e, "claim", 1).is_file() else None)
if r.returncode == 0 and red255 == 255:
    ok("a red of 255 under the break is proven and recorded as exit 255")
else:
    bad(f"exit 255 is a legitimate red, exit {r.returncode}", r.stdout + r.stderr)

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

# Catches: the program read as the first word. Each form's program is the word the
# shell actually runs; an interpreter's program is then the script it is given.
SYNTAX_WORDS = {"{", "(", "!", "if", "then", "else", "fi", "timeout", "60", "env", "A=1", "time"}
for form, prog, script in SYNTAX_FORMS + [(NEG, "grep", "grep")]:
    # getattr: before simple_commands exists, this is a FAIL, not a crash of the suite.
    first = next(iter(getattr(_pcp, "simple_commands", lambda c: [])(form)), [None])[0]
    progs = _pcp.command_programs(form)
    if first == prog and script in progs and not progs & SYNTAX_WORDS:
        ok(f"`{form}` runs {prog}, and its program is {script}")
    else:
        bad(f"the program behind `{form}` must be {prog} -> {script}",
            f"first word {first!r}, programs {sorted(progs)}")
# Catches: the runner missed where the shell actually runs it — after a `cd` (scoped to
# its subshell), inside a command or process substitution or backquotes, behind a
# shell's `-c`, a loop keyword or a wrapper's own options — or found where nothing runs
# (single quotes).
LOCATED = [
    ("cd scripts && python3 v2.py", {"scripts/v2.py"}),
    ("( cd scripts && python3 v2.py ) && python3 t.py", {"scripts/v2.py", "t.py"}),
    ("{ cd scripts; python3 v2.py; } && python3 t.py", {"scripts/v2.py", "scripts/t.py"}),
    ("x=$(python3 t.py) && test -n \"$x\"", {"t.py", "test"}),
    ("diff <(python3 t.py) want.txt", {"t.py", "diff"}),
    ("echo `python3 t.py`", {"t.py", "echo"}),
    ("bash -c 'cd scripts && python3 v2.py'", {"scripts/v2.py"}),
    ("while python3 t.py; do sleep 1; done", {"t.py", "sleep"}),
    ("until python3 t.py; do sleep 1; done", {"t.py", "sleep"}),
    ("timeout -s KILL 60 python3 t.py", {"t.py"}),
    ("cd scripts && ./run.sh", {"scripts/run.sh"}),
    ("echo '$(python3 t.py)'", {"echo"}),
]
for form, want in LOCATED:
    progs = _pcp.command_programs(form)
    if progs == want:
        ok(f"`{form}` runs {sorted(want)}")
    else:
        bad(f"the programs `{form}` runs must be {sorted(want)}", sorted(progs))
# End to end: the runner a `cd` reaches is refused like any other.
CDT = "cd scripts && python3 v2.py"
repo_c, plan_c = world(CDT)
with_files(repo_c, {"scripts/v2.py": "import sys\nsys.path.insert(0, '..')\n" + T_PY.replace("tests/", "../tests/")})
r = claim(repo_c, plan_c, 1, patch(repo_c, "scripts/v2.py", "import sys\n", "raise SystemExit(1)\n"), test=CDT)
if r.returncode == 1 and "edits scripts/v2.py, which the test command runs" in r.stderr:
    ok("a break of the runner a `cd` reaches is refused as a break of the runner")
else:
    bad(f"the runner behind `{CDT}` must not be breakable, exit {r.returncode}", r.stdout + r.stderr)

# Catches: a runner reached through a `for` loop's variable, by a brace list or a glob
# (this plan's own gates loop `for v in scripts/check-*.py`), taken as no runner at all.
LOOPED = [
    ('for f in {t,u}.py; do python3 "$f" || exit 1; done', {"t.py", "u.py"}),
    ('for v in scripts/check-*.py; do python3 "$v" || exit 1; done', {"scripts/check-*.py"}),
    ('for h in a b; do bash "${h}.sh"; done', {"a.sh", "b.sh"}),
]
for form, want in LOOPED:
    progs = _pcp.command_programs(form)
    if want <= progs:
        ok(f"`{form}` runs {sorted(want)}")
    else:
        bad(f"the programs `{form}` runs must include {sorted(want)}", sorted(progs))
LOOPT = 'for f in t*.py; do python3 "$f" || exit 1; done'
repo_l, plan_l = world(LOOPT)
with_files(repo_l, {"t1.py": T_PY})
r = claim(repo_l, plan_l, 1, patch(repo_l, "t1.py", "exec(", "raise SystemExit(1)\nexec("), test=LOOPT)
if r.returncode == 1 and "edits t1.py, which the test command runs" in r.stderr:
    ok("a break of a runner a `for` glob reaches is refused as a break of the runner")
else:
    bad(f"the runner behind `{LOOPT}` must not be breakable, exit {r.returncode}", r.stdout + r.stderr)
T_UP = "import os\nos.chdir('..')\nexec(open('tests/test_calc.py').read())\n"   # run from a subdirectory
# Catches: the script a make recipe or an npm script runs taken as code: the recipe's
# runner is the test's runner, one file further on.
for runner, files, rel in [
        ("make test", {"Makefile": "all:\n\techo all\n\ntest:\n\t@python3 t.py\n", "t.py": T_PY}, "t.py"),
        ("make -C sub", {"sub/Makefile": "check:\n\tpython3 t.py\n", "sub/t.py": T_UP}, "sub/t.py"),
        ("npm test", {"package.json": '{"scripts": {"test": "python3 t.py"}}\n', "t.py": T_PY}, "t.py"),
        ("cd web && npm run check", {"web/package.json": '{"scripts": {"check": "python3 t.py"}}\n',
                                     "web/t.py": T_UP}, "web/t.py")]:
    repo_r, plan_r = world(runner)
    with_files(repo_r, files)
    r = claim(repo_r, plan_r, 1, patch(repo_r, rel, "exec(", "raise SystemExit(1)\nexec("), test=runner)
    if r.returncode == 1 and f"edits {rel}, which the test command runs" in r.stderr:
        ok(f"a break of {rel}, which `{runner}`'s recipe runs, is refused as the runner")
    else:
        bad(f"the script `{runner}`'s recipe runs must not be breakable, exit {r.returncode}",
            r.stdout + r.stderr)

# Catches: the runner-file rule too wide (a file the runner never reads) or too narrow
# (the runner run from another directory, through a wrapper, or by yarn/pnpm).
RUNNER_FILES = [
    ("make test", {"Makefile", "makefile", "GNUmakefile"}),
    ("timeout 60 make -C sub test", {"sub/Makefile", "sub/makefile", "sub/GNUmakefile"}),
    ("make -f ci.mk test", {"ci.mk"}),
    ("npm test", {"package.json"}),
    ("npm --prefix web test", {"web/package.json"}),
    ("yarn test", {"package.json"}),
    ("pnpm -C web test", {"web/package.json"}),
    ("python3 t.py", set()),
    ("grep -q make Makefile", set()),
]
got = {cmd: set(getattr(_pcp, "runner_files", lambda c: {})(cmd)) for cmd, _ in RUNNER_FILES}
RUNNER_FILES += [
    ("make -Csub test", {"sub/Makefile", "sub/makefile", "sub/GNUmakefile"}),
    ("make -fci.mk test", {"ci.mk"}),
    ("pnpm -Cweb test", {"web/package.json"}),
    ("cd sub && make test", {"sub/Makefile", "sub/makefile", "sub/GNUmakefile"}),
    ("cd web && npm test", {"web/package.json"}),
    ("( cd web && npm test ) && make test",
     {"web/package.json", "Makefile", "makefile", "GNUmakefile"}),
]
got = {cmd: set(getattr(_pcp, "runner_files", lambda c: {})(cmd)) for cmd, _ in RUNNER_FILES}
if all(got[cmd] == want for cmd, want in RUNNER_FILES):
    ok("make and npm/yarn/pnpm name their definition files; other commands name none")
else:
    bad("runner_files must name exactly the file each runner reads",
        {cmd: sorted(got[cmd]) for cmd, want in RUNNER_FILES if got[cmd] != want})

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
# Catches: the validator and the live check judging a red by different rules. Only a
# signal death (128+1..128+64, or negative) is "killed"; 128, 193..255 are reds.
reds, killed = (1, 2, 128, 193, 254, 255), (-9, -1, 129, 137, 143, 192)
wrong = ([rc for rc in reds if any("did not fail" in p for p in pc.validate(dict(good, red={"exit": rc, "tail": ""})))]
         + [rc for rc in killed if not any("did not fail" in p for p in pc.validate(dict(good, red={"exit": rc, "tail": ""})))])
if not wrong:
    ok("validate() accepts a red of 128 or 193..255 and rejects a signal death (129..192, negative)")
else:
    bad("validate() must judge a red exit by signal range", f"misjudged: {wrong}")
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

# Catches: a Test using bash syntax run under /bin/sh, where it is a syntax error, so
# the task cannot be proven at all. The test runs under bash when bash is
# on PATH, and the record names the shell it ran under.
BASHISM = "diff <(printf a) <(printf a) && python3 tests/test_calc.py"
brepo, bplan = world(BASHISM)
r = claim(brepo, bplan, 1, patch(brepo, "calc.py", "a + b", "a - b"), test=BASHISM)
bshell = json.loads(rec(brepo, bplan, "claim", 1).read_text()).get("shell") if r.returncode == 0 else None
if r.returncode == 0 and bshell == "bash":
    ok("a Test using process substitution runs under bash, and the record's shell is bash")
else:
    bad(f"a bash-syntax Test must run under bash and record shell bash, exit {r.returncode}, "
        f"shell {bshell!r}", r.stderr)

# Catches: a host with no bash failing outright instead of falling back to sh.
stub = Path(tempfile.mkdtemp(prefix="prove-claim-nobash-"))
_tmp.append(stub)
for prog in ("python3", "git", "sh"):
    where = shutil.which(prog)
    (stub / prog).symlink_to(where)
srepo, splan = world()
sargs = ["claim", "--repo", str(srepo), "--plan", str(splan), "--task", "1.1", "--claim", "1",
         "--break", str(patch(srepo, "calc.py", "a + b", "a - b")),
         "--test", "python3 tests/test_calc.py", "--no-build-step", "pure python"]
senv = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
senv["PATH"] = str(stub)
r = subprocess.run([sys.executable, str(SCRIPT), *sargs], capture_output=True, text=True, env=senv)
sshell = json.loads(rec(srepo, splan, "claim", 1).read_text()).get("shell") if r.returncode == 0 else None
if r.returncode == 0 and sshell == "sh":
    ok("with no bash on PATH the Test runs under sh, and the record's shell is sh")
else:
    bad(f"with no bash on PATH the Test must fall back to sh and record it, exit {r.returncode}, "
        f"shell {sshell!r}", r.stderr)

# Catches: a relative bash path from a `.` PATH entry resolved after the chdir into the
# repo, so a `bash` the repo itself ships runs the test. The caller's own bash is meant.
crepo, cplan = world()
(crepo / "bash").write_text("#!/bin/sh\nexit 7\n")
os.chmod(crepo / "bash", 0o755)
git(crepo, "add", "bash")
git(crepo, "commit", "-q", "-m", "a repo-supplied bash")
caller = Path(tempfile.mkdtemp(prefix="prove-claim-caller-"))
_tmp.append(caller)
(caller / "bash").symlink_to(shutil.which("bash"))
cargs = ["claim", "--repo", str(crepo), "--plan", str(cplan), "--task", "1.1", "--claim", "1",
         "--break", str(patch(crepo, "calc.py", "a + b", "a - b")),
         "--test", "python3 tests/test_calc.py", "--no-build-step", "pure python"]
cenv = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
cenv["PATH"] = ".:" + str(stub)
r = subprocess.run([sys.executable, str(SCRIPT), *cargs], capture_output=True, text=True,
                   env=cenv, cwd=str(caller))
if r.returncode == 0:
    ok("a `.` PATH entry resolves bash from the caller's directory, never the repo's own")
else:
    bad(f"the repo's own ./bash must not run the test, exit {r.returncode}", r.stderr)

# Catches: replay re-running a bash record under sh (it would fail where the proof held),
# or a record naming a shell the tool never runs being accepted.
r = run("replay", "--repo", str(brepo), "--plan", str(bplan), "--task", "1.1")
if r.returncode == 0 and "ok" in r.stdout:
    ok("a bash record replays under bash")
else:
    bad(f"a bash record must replay, exit {r.returncode}", r.stdout + r.stderr)
bpath = rec(brepo, bplan, "claim", 1)
if bpath.is_file():
    brec = json.loads(bpath.read_text())
    brec["shell"] = "zsh"
    bpath.write_text(json.dumps(brec))
r = run("replay", "--repo", str(brepo), "--plan", str(bplan), "--task", "1.1")
if bpath.is_file() and r.returncode != 0 and "shell" in r.stdout:
    ok("a record naming a shell other than bash or sh is refused by the validator")
else:
    bad(f"a record with shell zsh must fail validation, exit {r.returncode}", r.stdout + r.stderr)

# Catches: a record with no `shell` (written before the field) replayed under bash, or
# a bash record replayed under sh where bash is missing. The old record ran under sh, so
# under sh it replays; a bash-syntax Test therefore fails its baseline there.
if bpath.is_file():
    brec.pop("shell", None)
    bpath.write_text(json.dumps(brec))
r = run("replay", "--repo", str(brepo), "--plan", str(bplan), "--task", "1.1")
# Exit 2 is dash's syntax error on `<(…)`: replay printed only the first line of it.
if bpath.is_file() and r.returncode != 0 and "before the break (exit 2)" in r.stdout:
    ok("a record without `shell` replays under sh, as it was run")
else:
    bad(f"a record without `shell` must replay under sh, exit {r.returncode}", r.stdout + r.stderr)
if bpath.is_file():
    brec["shell"] = "bash"
    bpath.write_text(json.dumps(brec))
renv = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
renv["PATH"] = str(stub)
r = subprocess.run([sys.executable, str(SCRIPT), "replay", "--repo", str(brepo), "--plan",
                    str(bplan), "--task", "1.1"], capture_output=True, text=True, env=renv)
if r.returncode != 0 and "bash is not on PATH" in r.stdout + r.stderr:
    ok("a bash record on a host without bash is refused, naming bash")
else:
    bad(f"a bash record must not replay under sh, exit {r.returncode}", r.stdout + r.stderr)

# Catches: requirement K picked from the old split, where a sentence opening with a
# code span merged into the one before: `req --req 2` must record "`sub` returns …".
qrepo, qplan = world()
qplan.write_text(qplan.read_text().replace(
    "- `add` returns the sum; `sub` returns the difference. The module is importable.",
    "- `add` returns the sum. `sub` returns the difference."))
qc = claim(qrepo, qplan, 1, patch(qrepo, "calc.py", "a + b", "a - b"))
r = run("req", "--repo", str(qrepo), "--plan", str(qplan), "--task", "1.1", "--req", "2",
        "--covered-by-claim", "1")
qtext = (json.loads(rec(qrepo, qplan, "req", 2).read_text()).get("text")
         if r.returncode == 0 else None)
if qc.returncode == 0 and qtext == "`sub` returns the difference.":
    ok("requirement 2 is the sentence that opens with a code span")
else:
    bad(f"`req --req 2` must pick the sentence opening with `sub`, exit {r.returncode}, "
        f"text {qtext!r}", r.stderr + qc.stderr)

# Catches: an untracked file the build writes counted as a failed restore.
# It is there before the break is applied, so the tree after the
# restore is the tree the break started from.
urepo, uplan = world()
UBUILD = BUILD_OK + " && echo built > build.out"
r = claim(urepo, uplan, 1, patch(urepo, "calc.py", "a + b", "a - b"), build=UBUILD)
if r.returncode == 0 and rec(urepo, uplan, "claim", 1).is_file():
    ok("an untracked file the build wrote before the break does not fail the restore check")
else:
    bad(f"a build's own untracked output must not fail the restore, exit {r.returncode}", r.stderr)

# Catches: a break that stops the build leaving the broken build behind: the refusal skipped the rebuild on the restored sources.
srepo2, splan2 = world()
(srepo2 / ".gitignore").write_text("__pycache__/\nout.py\n")
git(srepo2, "add", ".gitignore")
git(srepo2, "commit", "-q", "-m", "ignore out.py")
SBUILD = "cp calc.py out.py && " + BUILD_OK
r = claim(srepo2, splan2, 1, patch(srepo2, "calc.py", "def add(a, b):", "def add(a, b:"),
          build=SBUILD)
out_now = (srepo2 / "out.py").read_text() if (srepo2 / "out.py").exists() else None
if r.returncode == 1 and "does not build with the break" in r.stderr and out_now == CALC:
    ok("a break that stops the build is refused, and the restored sources are rebuilt")
else:
    bad(f"a build-stopping break must be refused and rebuilt after, exit {r.returncode}, "
        f"out.py restored: {out_now == CALC}", r.stderr)

# Catches: a non-UTF-8 break stored lossily: replay would apply a
# patch with U+FFFD where the original bytes were.
nrepo, nplan = world()
LATIN = b"# -*- coding: latin-1 -*-\n# caf\xe9\n" + CALC.encode()
(nrepo / "calc.py").write_bytes(LATIN)
git(nrepo, "add", "calc.py")
git(nrepo, "commit", "-q", "-m", "latin-1")
(nrepo / "calc.py").write_bytes(LATIN.replace(b"a + b", b"a - b"))
npatch = subprocess.run(["git", "-C", str(nrepo), "diff", "--", "calc.py"], capture_output=True,
                        check=True).stdout
(nrepo / "calc.py").write_bytes(LATIN)
nbrk = nrepo.parent / "break-latin.patch"
nbrk.write_bytes(npatch)
r = claim(nrepo, nplan, 1, nbrk, "--no-build-step", "pure python", build=None)
nrec = json.loads(rec(nrepo, nplan, "claim", 1).read_text()) if r.returncode == 0 else {}
nb64 = nrec.get("break_patch_b64")
if (b"\xe9" in npatch and r.returncode == 0 and isinstance(nb64, str)
        and base64.b64decode(nb64) == npatch):
    ok("a non-UTF-8 break round-trips byte-exact, stored as break_patch_b64")
else:
    bad(f"a non-UTF-8 break must be stored byte-exact, exit {r.returncode}, b64 {bool(nb64)}",
        r.stderr)
r = run("replay", "--repo", str(nrepo), "--plan", str(nplan), "--task", "1.1")
if r.returncode == 0 and "ok" in r.stdout:
    ok("a non-UTF-8 break replays from its stored bytes")
else:
    bad(f"a non-UTF-8 break must replay, exit {r.returncode}", r.stdout + r.stderr)
if nrec:
    nrec["break_patch_b64"] = "not base64!"
    rec(nrepo, nplan, "claim", 1).write_text(json.dumps(nrec))
r = run("replay", "--repo", str(nrepo), "--plan", str(nplan), "--task", "1.1")
if nrec and r.returncode != 0 and "break_patch_b64 is not base64" in r.stdout:
    ok("a record whose break_patch_b64 is not base64 is refused by the validator")
else:
    bad(f"an undecodable break_patch_b64 must fail validation, exit {r.returncode}",
        r.stdout + r.stderr)
if nrec:
    nrec["break_patch_b64"] = base64.b64encode(b"--- a/other\n").decode()
    rec(nrepo, nplan, "claim", 1).write_text(json.dumps(nrec))
r = run("replay", "--repo", str(nrepo), "--plan", str(nplan), "--task", "1.1")
if nrec and r.returncode != 0 and "not the break that break_patch shows" in r.stdout:
    ok("a record whose break_patch_b64 is another break than break_patch is refused")
else:
    bad(f"break_patch_b64 and break_patch must be one break, exit {r.returncode}",
        r.stdout + r.stderr)

# Catches: the lock released while a break is in the tree: the
# commit hooks read it to refuse a commit that would carry the break. The test itself
# checks the lock is held, so it is held for the baseline and under the break.
LOCKCHECK = ("import fcntl, subprocess, sys\n"
             "p = subprocess.run(['git', 'rev-parse', '--git-path', 'prove-claim.lock'],\n"
             "                   capture_output=True, text=True).stdout.strip()\n"
             "f = open(p)\n"
             "try:\n"
             "    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "except OSError:\n"
             "    sys.exit(0)\n"
             "sys.exit(5)\n")
LTEST = "python3 tests/lockcheck.py && python3 tests/test_calc.py"
lrepo, lplan = world(LTEST)
(lrepo / "tests" / "lockcheck.py").write_text(LOCKCHECK)
git(lrepo, "add", "tests/lockcheck.py")
git(lrepo, "commit", "-q", "-m", "lockcheck")
r = claim(lrepo, lplan, 1, patch(lrepo, "calc.py", "a + b", "a - b"), test=LTEST)
lred = (json.loads(rec(lrepo, lplan, "claim", 1).read_text()).get("red", {}).get("exit")
        if r.returncode == 0 else None)
# lockcheck exits 5 when the lock is free, and `&&` stops there: a red of 5 would be the
# lock released under the break, not the claim failing.
if r.returncode == 0 and lred == 1:
    ok("prove-claim holds `git rev-parse --git-path prove-claim.lock` while the test runs and the break is applied")
else:
    bad(f"the lock must be held while the break is applied, exit {r.returncode}, red {lred}",
        r.stderr)

# ------------------------------------------- a record binds its touched files' blobs
# A record names the files its break touched and binds their blobs (touched_blobs), so a
# change elsewhere in the tree — the task's own Status flip in a plan kept in the repo, a
# rebase onto other work — leaves it valid, and a change to a touched file does not. A
# record from before the blob binding keeps the whole-tree fingerprint rule.
print()
print("touched_blobs — a record binds the files its break touched")


def index_blob(repo, path):
    return git(repo, "ls-files", "-s", "--", path).split()[1]


def judged(rec_, repo, rev, expect):
    """validate() of a record against commit `rev`'s tree; an error raised is a problem."""
    try:
        return pc.validate(rec_, pc.commit_fingerprint(repo, rev), expect,
                           blobs=pc.commit_blobs(repo, rev))
    except Exception as e:  # noqa: BLE001
        return [f"raised {e.__class__.__name__}: {e}"]


brepo, bplan0 = world()
bplan = brepo / "docs" / bplan0.name
bplan.parent.mkdir()
shutil.move(str(bplan0), str(bplan))
git(brepo, "add", "docs")
git(brepo, "commit", "-q", "-m", "the plan lives in the repo")
(brepo / "calc.py").write_text(CALC + "\n\ndef twice(a):\n    return 2 * a\n")
git(brepo, "add", "calc.py")
r = claim(brepo, bplan, 1, patch(brepo, "calc.py", "return a + b", "return a - b"))
r2 = run("req", "--repo", str(brepo), "--plan", str(bplan), "--task", "1.1", "--req", "1",
         "--covered-by-claim", "1")
brec = json.loads(rec(brepo, bplan, "claim", 1).read_text()) if r.returncode == 0 else {}
breq = json.loads(rec(brepo, bplan, "req", 1).read_text()) if r2.returncode == 0 else {}
if brec.get("touched_blobs") == {"calc.py": index_blob(brepo, "calc.py")}:
    ok("a claim record binds each touched file's blob, read from the index the proof ran on")
else:
    bad("a record must carry touched_blobs {path: blob} for its touched files (red if only "
        "the fingerprint is written)", (brec.get("touched_blobs"), r.stderr))
# The test the record was watched under is part of the proof: the files the Test command
# runs are bound too (witness_blobs), so a test weakened after the proof stales it.
if brec.get("witness_blobs") == {"tests/test_calc.py": index_blob(brepo, "tests/test_calc.py")}:
    ok("a claim record binds the blob of each tracked file the Test command runs")
else:
    bad("a record must carry witness_blobs {path: blob} for the files its test runs (red if "
        "the test goes unbound)", (brec.get("witness_blobs"), r.stderr))
if breq.get("touched_blobs") and breq.get("touched_blobs") == brec.get("touched_blobs"):
    ok("a req covered by a claim binds that claim's blobs")
else:
    bad("a covered req must carry its claim's touched_blobs", (breq, r2.stderr))
bplan.write_text(bplan.read_text().replace("**Status:** [ ]", "**Status:** [x]"))
git(brepo, "add", "docs", "proof")
git(brepo, "commit", "-q", "-m", "Stage 1 Task 1.1: twice")
bexp = ("claim", "1.1", 1, "add returns the sum (red if add subtracts)")
rexp = ("req", "1.1", 1, "`add` returns the sum; `sub` returns the difference.")
probs = judged(brec, brepo, "HEAD", bexp)
rprobs = judged(breq, brepo, "HEAD", (rexp[0], rexp[1], rexp[2], breq.get("text")))
if brec and probs == [] and rprobs == []:
    ok("records proven before the task's Status flip in an in-repo plan validate after it")
else:
    bad("a proof must survive the Status flip of its own task (red under the index binding: "
        "the flip changes the tree)", (probs, rprobs))
legacy_rec = {k: v for k, v in brec.items() if k not in ("touched_blobs", "witness_blobs")}
half = {k: v for k, v in brec.items() if k != "witness_blobs"}
if any("different tree" in p for p in judged(half, brepo, "HEAD", bexp)):
    ok("a record with touched_blobs but no witness_blobs is judged by the whole tree (fail safe)")
else:
    bad("a record without witness_blobs must keep the fingerprint rule (red if its test "
        "goes unbound)", judged(half, brepo, "HEAD", bexp))
if any("different tree" in p for p in judged(legacy_rec, brepo, "HEAD", bexp)):
    ok("a record without touched_blobs keeps the whole-tree rule: the same flip refuses it")
else:
    bad("a record without touched_blobs must be judged by its fingerprint (red if it is "
        "accepted unbound)", judged(legacy_rec, brepo, "HEAD", bexp))
# Catches: a deviation carrying blob maps (copied by hand) judged by them. A deviation
# proves no file: the whole-tree rule judges it, so the same flip refuses it.
dev_maps = dict(brec, kind="deviation", why="the sum is checked on the device, outside the repo")
dprobs = judged(dev_maps, brepo, "HEAD", ("deviation", "1.1", 1, None))
if brec and any("different tree" in p for p in dprobs):
    ok("a deviation carrying blob maps is still judged by the whole tree")
else:
    bad("only a claim or req record binds by blobs (red if a deviation's copied maps are "
        "compared instead of its fingerprint)", dprobs)
shapes = {"binds no file": dict(brec, touched_blobs={}),
          "names a file the break did not touch": dict(brec, touched_blobs={"other.py": "0" * 40}),
          "holds a value that is not a blob id": dict(brec, touched_blobs={"calc.py": "xyz"}),
          "is not a mapping": dict(brec, touched_blobs=["calc.py"]),
          "witness map is not a mapping": dict(brec, witness_blobs=["tests/test_calc.py"]),
          "witness value is not a blob id": dict(brec, witness_blobs={"tests/test_calc.py": "x"})}
loose = [k for k, v in shapes.items() if not pc.validate(v)]
if brec and not loose:
    ok("touched_blobs that binds nothing, names other files or holds no blob id is rejected")
else:
    bad("a malformed touched_blobs must be rejected", loose)
(brepo / "notes.txt").write_text("unrelated\n")
git(brepo, "add", "notes.txt")
git(brepo, "commit", "-q", "-m", "a file neither touched nor run")
probs = judged(brec, brepo, "HEAD", bexp)
if brec and probs == []:
    ok("a later commit to a file the break did not touch and the test does not run keeps it valid")
else:
    bad("an unbound file edited after the proof must not stale the record", probs)
tpath = brepo / "tests" / "test_calc.py"
tgood = tpath.read_text()
tpath.write_text("pass  # the assertions are gone\n")
git(brepo, "commit", "-q", "-am", "weaken the test after the proof")
probs = judged(brec, brepo, "HEAD", bexp)
if any("different tree" in p and "tests/test_calc.py" in p for p in probs):
    ok("a test file edited after the proof stales the record, naming the test file")
else:
    bad("a weakened test must stale the record (red if the test the record was watched under "
        "goes unbound)", probs)
tpath.write_text(tgood)
git(brepo, "commit", "-q", "-am", "the test restored")
(brepo / "calc.py").write_text(CALC + "# changed after the proof\n")
git(brepo, "commit", "-q", "-am", "a later change to the proven code")
probs = judged(brec, brepo, "HEAD", bexp)
try:
    moved = pc.blob_drift(brec, pc.commit_blobs(brepo, "HEAD"))
except Exception as e:  # noqa: BLE001
    moved = f"raised {e.__class__.__name__}"
if any("different tree" in p and "calc.py" in p for p in probs) and moved == ["calc.py"]:
    ok("a commit that changes a touched file: the record is refused and drift names the file")
else:
    bad("a changed touched file must fail the record, naming it (red if the blobs go "
        "uncompared)", (probs, moved))

# ------------------------------------------- the witness binds every test file it names
# A record binds by blobs only when its witness names every test file the command runs.
# A directory argument binds the tracked files under it; a `::node` suffix and a dotted
# `-m unittest` module name a file. A command that names nothing, or names a path that is
# not tracked, binds nothing by blobs: the record keeps the whole-tree fingerprint rule.
print()
print("witness_files — every test file a runner is given, or no blob binding at all")
wtracked = {"calc.py", "tests/test_a.py", "tests/conftest.py", "tests/helpers/h.py",
            "pkg/x.go", "pkg/x_test.go", "go.mod", "docs/plan.md"}
wdir = Path(tempfile.mkdtemp(prefix="prove-claim-witness-"))
_tmp.append(wdir)
under_tests = ["tests/conftest.py", "tests/helpers/h.py", "tests/test_a.py"]
wforms = {"pytest tests/": under_tests,
          "pytest tests": under_tests,
          "pytest": None,
          "python3 -m pytest": None,
          "go test ./...": sorted(wtracked),
          "go test ./pkg/...": ["pkg/x.go", "pkg/x_test.go"],
          "pytest tests/test_a.py::test_add": ["tests/test_a.py"],
          "python3 -m unittest tests.test_a": ["tests/test_a.py"],
          "python3 -m unittest tests.test_gone": None,
          "python3 -m unittest tests.test_a tests.test_gone": None,
          "pytest tests/test_a.py tests/test_gone.py": None,
          "python3 tests/test_a.py": ["tests/test_a.py"]}
for cmd_, want in wforms.items():
    try:
        got = pc.witness_files(wdir, cmd_, wtracked)
    except Exception as e:  # noqa: BLE001
        got = f"raised {e.__class__.__name__}: {e}"
    if got == want:
        ok(f"`{cmd_}` binds {want if want is not None else 'no blob map (fingerprint rule)'}")
    else:
        bad(f"`{cmd_}` must bind {want} (red if a runner's test files go unbound)", got)

# A record whose command resolves nothing carries neither map, so a test weakened after
# the proof stales it (the whole-tree rule), where an empty witness map accepted it.
RUNPY = "python3 -c \"import runpy; runpy.run_path('tests/test_calc.py')\""
nrepo, nplan = world(RUNPY)
r = claim(nrepo, nplan, 1, patch(nrepo, "calc.py", "return a + b", "return a - b"), test=RUNPY)
nrec = json.loads(rec(nrepo, nplan, "claim", 1).read_text()) if r.returncode == 0 else {}
if nrec and not any(k in nrec for k in ("touched_blobs", "witness_blobs")):
    ok("a record whose test command names no tracked file carries no blob maps")
else:
    bad("a command that resolves nothing must write neither blob map (red if an empty "
        "witness map binds)", (sorted(nrec), r.stderr))
git(nrepo, "add", "proof")
git(nrepo, "commit", "-q", "-m", "Stage 1 Task 1.1: proven by a command naming no file")
nexp = ("claim", "1.1", 1, "add returns the sum (red if add subtracts)")
before = judged(nrec, nrepo, "HEAD", nexp)
(nrepo / "tests" / "test_calc.py").write_text("pass  # the assertions are gone\n")
git(nrepo, "commit", "-q", "-am", "weaken the test after the proof")
after = judged(nrec, nrepo, "HEAD", nexp)
if nrec and before == [] and any("different tree" in p for p in after):
    ok("its test weakened after the proof, the record is refused by the whole-tree rule")
else:
    bad("a record binding no test file must be refused after a test edit (red if it "
        "verifies by its touched blobs alone)", (before, after))
# A record with an empty witness map (as this tool wrote one for such a command) binds no
# test file, so it is judged by the whole tree. HEAD~2 is the commit that weakened the
# test, with calc.py as proven.
eprobs = judged(dict(brec, witness_blobs={}), brepo, "HEAD~2", bexp)
if brec and any("different tree" in p for p in eprobs):
    ok("a record with an empty witness_blobs is judged by the whole tree, never bound")
else:
    bad("an empty witness_blobs must not count as bound (red if a test edited after the "
        "proof verifies)", eprobs)

# ------------------------------------------- a renumbered record is moved, never overwritten
# "It stays pure." was requirement 2 before a sentence opening with a code span became its
# own clause; it is requirement 3 now. Proving the new requirement 2 must not overwrite the
# old req-2.json, which proves requirement 3: it is moved to req-3.json first.
print()
print("a renumbered req or deviation record is moved to its clause's number, never lost")
SHIFT_DESC = "- Adds numbers. `add` returns the sum. It stays pure."


def shifted(kind):
    """A repo whose req or deviation record for "It stays pure." sits at its old number 2."""
    repo_, plan_ = world()
    plan_.write_text(plan_.read_text().replace(
        "- `add` returns the sum; `sub` returns the difference. The module is importable.",
        SHIFT_DESC))
    base_ = ["--repo", str(repo_), "--plan", str(plan_), "--task", "1.1"]
    claim(repo_, plan_, 1, patch(repo_, "calc.py", "a + b", "a - b"))
    if kind == "req":
        run("req", *base_, "--req", "3", "--covered-by-claim", "1")
    else:
        run("deviation", *base_, "--req", "3", "--why", "purity is reviewed, not tested here")
    old_ = rec(repo_, plan_, kind, 3)
    data_ = json.loads(old_.read_text()) if old_.exists() else {}
    if data_:
        old_.unlink()
        rec(repo_, plan_, kind, 2).write_text(json.dumps(dict(data_, index=2)))
    return repo_, plan_, base_, data_


for kind_ in ("req", "deviation"):
    mrepo, mplan, mbase, mold = shifted(kind_)
    r = run("req", *mbase, "--req", "2", "--covered-by-claim", "1")
    moved_ = rec(mrepo, mplan, kind_, 3)
    mrec = json.loads(moved_.read_text()) if moved_.exists() else {}
    new2 = rec(mrepo, mplan, "req", 2)
    ntext = json.loads(new2.read_text()).get("text") if new2.exists() else None
    if (mold and r.returncode == 0 and mrec.get("text") == "It stays pure."
            and mrec.get("index") == 3 and ntext == "`add` returns the sum"
            and f"{kind_}-3.json" in r.stdout + r.stderr):
        ok(f"proving the new requirement 2 moves the old {kind_}-2.json of requirement 3 to "
           f"{kind_}-3.json, and says so")
    else:
        bad(f"a renumbered {kind_} record must be moved to its clause's number before req-2 is "
            "written (red if it is overwritten)", (r.returncode, mrec, ntext, r.stdout + r.stderr))
# The same through `deviation --req 2`, which replaces req-2.json too.
mrepo, mplan, mbase, mold = shifted("req")
r = run("deviation", *mbase, "--req", "2", "--why", "the sum is reviewed, not tested here")
moved_ = rec(mrepo, mplan, "req", 3)
mrec = json.loads(moved_.read_text()) if moved_.exists() else {}
if mold and r.returncode == 0 and mrec.get("text") == "It stays pure." and mrec.get("index") == 3:
    ok("recording requirement 2 as a deviation moves the old req-2.json of requirement 3 first")
else:
    bad("a deviation must not delete a renumbered req record at its number (red if "
        "req-2.json is lost)", (r.returncode, mrec, r.stdout + r.stderr))
mrepo, mplan, mbase, mold = shifted("req")
run("req", *mbase, "--req", "3", "--covered-by-claim", "1")   # slot 3 is taken now
before2 = rec(mrepo, mplan, "req", 2).read_text() if rec(mrepo, mplan, "req", 2).exists() else ""
r = run("req", *mbase, "--req", "2", "--covered-by-claim", "1")
after2 = rec(mrepo, mplan, "req", 2).read_text() if rec(mrepo, mplan, "req", 2).exists() else ""
if (mold and r.returncode != 0 and before2 and after2 == before2
        and "req-2.json" in r.stderr and "req-3.json" in r.stderr):
    ok("with the clause's own number taken, proving requirement 2 is refused, naming both files")
else:
    bad("a renumbered record whose clause already has a record must refuse, naming both files "
        "(red if req-2.json is overwritten)", (r.returncode, r.stderr))

for d in _tmp:
    shutil.rmtree(d, ignore_errors=True)
print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
