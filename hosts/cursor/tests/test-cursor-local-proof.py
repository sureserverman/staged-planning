#!/usr/bin/env python3
"""On Cursor, a proof record kept outside git binds to its stage's `Stage N green` commit.

The Cursor flow proves every task once, at the gate, on the stage's final tree (the
claim-verifier), and the git ref hook binds each record to the `Stage N green` commit's
fingerprint. With proof/ ignored, the built plan-flip-audit.py must accept that commit as a
record's binding: a task commit's own tree differs from the final one whenever a later task
or a gate fix landed after it.

  local, proven at the gate  task commit, a gate fix, the record proven on the final tree,
                             `Stage 1 green` -> no blocking finding 8 for Task 1.1
  local, stale               the same, but the code changes after proving and before
                             `Stage 1 green` -> blocking finding 8
  in-repo plan, flipped      the plan lives in the repo and its boxes are ticked after the
                             proof: the record binds its touched files' blobs, so the ref
                             hook lets `Stage 1 green` through and finding 8 stays clean
  drift                      a later commit changes a touched file -> the ref hook refuses
                             that tree as `Stage 1 green`, and finding 8 reports drift naming
                             the file and the record: blocking while the stage's gate is
                             open, advisory once it is ticked and `Stage 1 green` holds the
                             files as proven (a later stage may edit them)
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FAILS = []
GITENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
PLAN = """# Plan

## Stage 1: calc

### Task 1.1: calc
- **Status:** [x]
- `add` returns the sum.
- **Test:** `python3 tests/test_calc.py` — add returns the sum (red if add subtracts)

### Stage 1 Gate
- [x] the suite passes: `python3 tests/test_calc.py`
"""
CALC = "def add(a, b):\n    return a + b\n"
TESTPY = "import sys\nsys.path.insert(0, '.')\nfrom calc import add\nassert add(2, 3) == 5\n"
BUILD = "python3 -c 'import ast; ast.parse(open(\"calc.py\").read())'"


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[:900].replace("\n", "\n     | "))


tmp = tempfile.mkdtemp(prefix="cursor-local-proof-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "cursor",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    scripts = os.path.join(out, "skills", "executing-plans", "scripts")
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith(("CURSOR_", "CLAUDE_", "GIT_"))}
    env0.update(GITENV, PYTHONDONTWRITEBYTECODE="1")

    def git(repo, *a):
        # A global template or hooks path can abort a commit: none reaches this repo.
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", repo, *a],
                              capture_output=True, text=True, env=dict(env0), check=True)

    def gate(repo, plan, subject):
        """The Cursor ref hook's verdict on a commit of the staged tree named `subject`,
        with `plan` in flight at its stage 1 gate. The commit is made, not moved to."""
        os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
        state = os.path.join(repo, ".claude", "plan-progress.json")
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(state, "w") as fh:
            json.dump({"plan": plan, "phase": "gate", "stage": 1, "updated": now}, fh)
        try:
            tree = git(repo, "write-tree").stdout.strip()
            head = git(repo, "rev-parse", "HEAD").stdout.strip()
            c = git(repo, "commit-tree", tree, "-p", head, "-m", subject).stdout.strip()
            return subprocess.run(["bash", os.path.join(out, "hooks", "git-ref-gate.sh"),
                                   "prepared"], cwd=repo, input=f"{head} {c} refs/heads/main\n",
                                  capture_output=True, text=True, env=dict(env0))
        finally:
            os.remove(state)

    def world(name, stale, in_repo=False, later=False, gate_open=False):
        repo = os.path.join(tmp, name)
        plans = os.path.join(tmp, name + "-plans")
        os.makedirs(os.path.join(repo, "tests"))
        os.makedirs(plans)
        subprocess.run(["git", "init", "-q", "--template=", "-b", "main", repo], check=True,
                       env=dict(env0))
        calc = os.path.join(repo, "calc.py")
        with open(calc, "w") as fh:
            fh.write(CALC)
        with open(os.path.join(repo, "tests", "test_calc.py"), "w") as fh:
            fh.write(TESTPY)
        with open(os.path.join(repo, ".gitignore"), "w") as fh:
            fh.write("__pycache__/\nproof/\n.claude/\n")
        plan = os.path.join(repo if in_repo else plans, "2026-10-04-calc-plan.md")
        with open(plan, "w") as fh:
            # In the repo, the boxes are ticked only after the proof (below).
            fh.write(PLAN.replace("[x]", "[ ]") if in_repo else
                     PLAN.replace("- [x] the suite", "- [ ] the suite") if gate_open else PLAN)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        with open(calc, "a") as fh:
            fh.write("\n\ndef twice(a):\n    return 2 * a\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "Stage 1 Task 1.1: twice")
        # A gate fix lands after the task commit, so the final tree differs from it.
        with open(os.path.join(repo, "NOTES.md"), "w") as fh:
            fh.write("gate fix\n")
        git(repo, "add", "-A")
        # The verifier proves on the staged final tree.
        brk = os.path.join(tmp, name + "-break.patch")
        with open(calc) as fh:
            orig = fh.read()
        with open(calc, "w") as fh:
            fh.write(orig.replace("return a + b", "return a - b"))
        with open(brk, "w") as fh:
            fh.write(subprocess.run(["git", "-C", repo, "diff", "--", "calc.py"],
                                    capture_output=True, text=True, env=dict(env0)).stdout)
        with open(calc, "w") as fh:
            fh.write(orig)
        base = ["--repo", repo, "--plan", plan, "--task", "1.1"]
        pc = os.path.join(scripts, "prove-claim.py")
        r1 = subprocess.run([sys.executable, pc, "claim", *base, "--claim", "1", "--break", brk,
                             "--test", "python3 tests/test_calc.py", "--build", BUILD],
                            capture_output=True, text=True, env=dict(env0))
        r2 = subprocess.run([sys.executable, pc, "req", *base, "--req", "1",
                             "--covered-by-claim", "1"],
                            capture_output=True, text=True, env=dict(env0))
        assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
        if stale:
            with open(calc, "a") as fh:
                fh.write("# changed after the proof\n")
        if in_repo:
            with open(plan, "w") as fh:
                fh.write(PLAN)   # the task's Status and the gate box, ticked after the proof
        git(repo, "add", "-A")
        verdict = gate(repo, plan, "Stage 1 green")
        git(repo, "commit", "-q", "-m", "Stage 1 green")
        if later:
            # A later commit changes the proven code, or the test that proved it: the
            # stage's records have drifted.
            with open(calc if later is True else os.path.join(repo, later), "a") as fh:
                fh.write("# tidied after the stage closed\n")
            git(repo, "add", "-A")
            verdict = gate(repo, plan, "Stage 1 green")
            git(repo, "commit", "-q", "-m", "tidy calc")
        r = subprocess.run([sys.executable, os.path.join(scripts, "plan-flip-audit.py"), plan,
                            "--repo", repo, "--json"],
                           capture_output=True, text=True, env=dict(env0))
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            return None, r.stdout + r.stderr
        f8 = [f for f in doc.get("findings", []) if f.get("finding") == 8
              and f.get("text") == "Task 1.1"]
        return f8, doc, verdict

    f8, doc, _v = world("ok", stale=False)
    check(f8 is not None and not [f for f in f8 if f["severity"] == "blocking"],
          "a local record proven at the gate binds to the `Stage 1 green` commit "
          "(red if only commits naming the task are tried)",
          json.dumps(f8 if f8 is not None else doc)[:900])

    f8, doc, _v = world("stale", stale=True)
    check(f8 is not None and [f for f in f8 if f["severity"] == "blocking"],
          "a local record proven on a tree no commit records stays blocking",
          json.dumps(f8 if f8 is not None else doc)[:900])

    f8, doc, v = world("flip", stale=False, in_repo=True)
    check(v.returncode == 0,
          "the ref hook lets `Stage 1 green` through when the in-repo plan's boxes were ticked "
          "after the proof (red under the index binding)", v.stderr)
    check(f8 is not None and not [f for f in f8 if f["severity"] == "blocking"],
          "a record proven before the in-repo plan's Status flip verifies after it",
          json.dumps(f8 if f8 is not None else doc)[:900])

    f8, doc, v = world("drift", stale=False, later=True, gate_open=True)
    rel = "proof/2026-10-04-calc-plan/1.1/claim-1.json"
    check(v.returncode != 0 and "calc.py" in v.stderr and "different tree" in v.stderr,
          "the ref hook refuses as `Stage 1 green` a tree whose touched file changed after "
          "the proof, naming the file", v.stderr)
    drift = [f for f in (f8 or []) if f["severity"] == "blocking" and "drift" in f["rule"]
             and "calc.py" in f["rule"] and rel in f["rule"]]
    check(bool(drift), "a later commit changing a touched file is blocking drift naming the "
          "file and the record", json.dumps(f8 if f8 is not None else doc)[:900])

    f8, doc, v = world("drift-closed", stale=False, later=True)
    drift = [f for f in (f8 or []) if "drift" in f["rule"] and "calc.py" in f["rule"]]
    check(bool(drift) and all(f["severity"] == "advisory" for f in drift),
          "on a closed stage whose `Stage 1 green` held the files as proven, later drift is "
          "advisory (red if every stage's drift blocks)",
          json.dumps(f8 if f8 is not None else doc)[:900])

    f8, doc, v = world("drift-test", stale=False, later="tests/test_calc.py", gate_open=True)
    check(v.returncode != 0 and "tests/test_calc.py" in v.stderr,
          "the ref hook refuses as `Stage 1 green` a tree whose test file changed after the "
          "proof, naming it", v.stderr)
    drift = [f for f in (f8 or []) if f["severity"] == "blocking" and "drift" in f["rule"]
             and "tests/test_calc.py" in f["rule"] and rel in f["rule"]]
    check(bool(drift), "a later commit changing the test file is blocking drift naming it and "
          "the record", json.dumps(f8 if f8 is not None else doc)[:900])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if FAILS else 0)
