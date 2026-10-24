#!/usr/bin/env python3
"""prove-claim.py in a repo whose proof/ is git-ignored — run directly:

    python3 core/skills/executing-plans/tests/test-prove-claim-ignored-proof.py

A project that keeps its plans outside the repo ignores proof/, because each
record names the plan that produced it. The tool must still write the record,
replay it and fingerprint the tree there, and the record must stay out of
`git status`. All values below are invented.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "prove-claim.py"
passed = failed = 0

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

PLAN = """# Plan

## Stage 1

### Task 1.1: shapes
- **Status:** [ ]
- `area` returns width times height.
- **Test:** `python3 tests/test_shapes.py` — area multiplies (red if area adds)
- **Red-Green max cycles:** 3
"""

BASE = "def area(w, h):\n    return 0\n"
SHAPES = "def area(w, h):\n    return w * h\n"
TEST = ("import sys\nsys.path.insert(0, '.')\nfrom shapes import area\n"
        "assert area(3, 4) == 12\n")
BUILD = "python3 -c 'import ast; ast.parse(open(\"shapes.py\").read())'"


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


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                          env=GIT_ENV, check=True).stdout


def tool(*args):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, env=env)


print("prove-claim.py — claim, replay and fingerprint with proof/ ignored")
print()

tmp = Path(tempfile.mkdtemp(prefix="prove-claim-ignored-"))
try:
    repo, records = tmp / "repo", tmp / "records"
    repo.mkdir(), records.mkdir()
    # --template= / hooksPath: a global template hook must not touch the fixture repo.
    subprocess.run(["git", "init", "-q", "-b", "main", "--template=", str(repo)], check=True)
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / ".gitignore").write_text("__pycache__/\nproof/\n")
    (repo / "shapes.py").write_text(BASE)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")

    # The work being proven: staged, not committed.
    (repo / "shapes.py").write_text(SHAPES)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_shapes.py").write_text(TEST)
    git(repo, "add", "-A")

    plan = records / "2026-01-02-shapes-plan.md"
    plan.write_text(PLAN)

    # The break: made by editing and diffing, then undone.
    (repo / "shapes.py").write_text(SHAPES.replace("w * h", "w + h"))
    brk = tmp / "break.patch"
    brk.write_text(git(repo, "diff", "--", "shapes.py"))
    (repo / "shapes.py").write_text(SHAPES)

    r = tool("claim", "--repo", str(repo), "--plan", str(plan), "--task", "1.1",
             "--claim", "1", "--break", str(brk), "--test", "python3 tests/test_shapes.py",
             "--build", BUILD)
    record = repo / "proof" / plan.stem / "1.1" / "claim-1.json"
    if r.returncode == 0:
        ok("claim exits 0 with proof/ ignored")
    else:
        bad(f"claim must succeed with proof/ ignored, exit {r.returncode}", r.stdout + r.stderr)
    if record.is_file():
        ok("the record is written to disk under the ignored proof/")
    else:
        bad("the record must exist on disk", r.stdout + r.stderr)

    ci = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q",
                         str(record.relative_to(repo))])
    if ci.returncode == 0:
        ok("git reports the record as ignored")
    else:
        bad(f"the record must be git-ignored, check-ignore exit {ci.returncode}")

    status = git(repo, "status", "--porcelain")
    if "proof" not in status:
        ok("git status --porcelain does not list the record")
    else:
        bad("git status must not list proof/", status)
    if git(repo, "ls-files", "proof") == "":
        ok("the record is not in the index")
    else:
        bad("the record must not be tracked", git(repo, "ls-files", "proof"))

    r = tool("replay", "--repo", str(repo), "--plan", str(plan), "--task", "1.1")
    if r.returncode == 0 and "the break still turns the test red" in r.stdout:
        ok("replay exits 0 and re-runs the break")
    else:
        bad(f"replay must exit 0, exit {r.returncode}", r.stdout + r.stderr)

    r = tool("fingerprint", "--repo", str(repo))
    data = json.loads(record.read_text()) if record.is_file() else {}
    if r.returncode == 0 and r.stdout.strip() and data.get("fingerprint") == r.stdout.strip():
        ok("fingerprint exits 0 and matches the record")
    else:
        bad(f"fingerprint must match the record, exit {r.returncode}",
            f"{data.get('fingerprint')} vs {r.stdout.strip()} {r.stderr}")

    status = git(repo, "status", "--porcelain")
    if status == "M  shapes.py\nA  tests/test_shapes.py\n":
        ok("after replay the tree holds only the staged work")
    else:
        bad("replay must leave the tree as it was", status)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed or passed == 0 else 0)
