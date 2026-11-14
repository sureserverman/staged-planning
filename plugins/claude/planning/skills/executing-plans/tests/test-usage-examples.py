#!/usr/bin/env python3
"""Fixture suite: a wrong call to a plugin script is answered with a call that works.

    python3 core/skills/executing-plans/tests/test-usage-examples.py

WHAT THIS SUITE IS REALLY GUARDING. The 2026-11-13 audit counted 307 `--help` runs
and 138 `prove-claim.py` argument errors across 59 executions: the executor did not
know how to call the scripts, and learnt again after every handoff. So every script an
executor or planner calls, in every host build, ends an argument error with one
`example: <a complete call>` line. A line that its own script then refused would
teach the wrong call, so each example is parsed back through the same script.

THE SET. Every `skills/{executing-plans,planning-projects}/scripts/*.py` in each of
the four host builds that uses argparse (the core scripts and every host fork), plus
`plan-progress.py`, which reads `sys.argv` by hand. It is enumerated here, not
listed, so a new script joins it on its own. The builds are tested rather than
`core/`: a fork lives only there, and `build.py --check` ties the builds to source.

PARSE ONLY. A script is run under a wrapper that patches
`argparse.ArgumentParser.parse_args`: a call that parses prints `PARSED` and exits 0
before the script acts, so no call here installs, writes or reads a run. "Parses"
includes the rules argparse cannot state (a flag another flag needs): each script runs
them inside parsing, through `ExampleParser(check=...)`, so an example missing
`--build` is refused here exactly as the script would refuse it. That gap is how the
first version of this suite passed an example `prove-claim.py claim` then refused
(Stage 1 gate, 2026-11-14). A refusal that depends on the run's state or on a file
cannot be judged while parsing; those few are run for real, in a scratch directory.
"""
import concurrent.futures
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
BUILDS = [REPO / "plugins/claude/planning", REPO / "plugins/codex/planning",
          REPO / "plugins/cursor/planning", REPO / "packages/opencode"]
SKILLS = ("executing-plans", "planning-projects")

WRAPPER = r'''
import argparse, json, os, runpy, sys
mode, path, *args = sys.argv[1:]
original = argparse.ArgumentParser.parse_args
def patched(self, args=None, namespace=None):
    if mode == "subs":
        names = [n for a in self._actions if isinstance(a, argparse._SubParsersAction)
                 for n in a.choices]
        print("SUBS " + json.dumps(names))
        sys.exit(0)
    ns = original(self, args, namespace)
    print("PARSED " + json.dumps(vars(ns), default=str))
    sys.exit(0)
argparse.ArgumentParser.parse_args = patched
sys.argv = [path] + args
sys.path.insert(0, os.path.dirname(path))
runpy.run_path(path, run_name="__main__")
'''

passed = failed = 0


def ok(msg):
    global passed
    passed += 1
    print(f"  ok    {msg}")


def bad(msg, detail=""):
    global failed
    failed += 1
    print(f"  FAIL  {msg}")
    if detail:
        print("        | " + str(detail)[:900].replace("\n", "\n        | "))


def run(argv, cwd=None, stdin=None):
    return subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, text=True,
                          timeout=60, stdin=None if stdin is not None else subprocess.DEVNULL)


def wrapped(mode, script, args):
    return run([sys.executable, "-c", WRAPPER, mode, str(script), *args])


def example_of(stderr):
    """The example a failed call printed, or an error string saying why there is none."""
    lines = [l for l in stderr.splitlines() if l.strip()]
    examples = [l for l in lines if l.startswith("example: ")]
    if len(examples) != 1:
        return None, f"{len(examples)} `example:` lines"
    if lines[-1] != examples[0]:
        return None, "the `example:` line is not stderr's last line"
    return examples[0][len("example: "):], None


def call_of(example, rel):
    """(stdin text or None, args after the script path) of an example, or an error."""
    stdin = None
    if "|" in example:
        left, example = example.rsplit("|", 1)
        words = shlex.split(left)
        if words[:1] != ["echo"] or len(words) != 2:
            return None, None, f"the part before `|` is not one echo: {left!r}"
        stdin = words[1]
    words = shlex.split(example)
    want = f"<planning-plugin>/{rel}"
    if words[:2] != ["python3", want]:
        return None, None, f"does not start `python3 {want}`: {example!r}"
    return stdin, words[2:], None


def argparse_scripts(build):
    for skill in SKILLS:
        for f in sorted((build / "skills" / skill / "scripts").glob("*.py")):
            if re.search(r"^(import|from) argparse\b", f.read_text(errors="ignore"), re.M):
                yield f


# The core scripts that parse with argparse (2026-11-14). Each one a build ships must be
# in that build's set: a script whose import stops matching the predicate cannot leave the
# set unnoticed.
KNOWN = {"check-master-register.py", "context-usage.py", "evaluation-ledger.py",
         "handoff-envelope.py", "owner-decision.py", "plan-flip-audit.py", "plan-state.py",
         "proof-hooks-install.py", "prove-claim.py", "review-ledger-check.py",
         "stage-brief.py", "statusline-install.py", "validate-dispatch.py",
         "validate-gate-checks.py"}

# Wrong calls the parser alone accepts and the script must still answer with its example:
# (script, args, words the error must hold). Run parse-only.
AFTER_PARSE = [
    ("prove-claim.py", ["claim", "--repo", "r", "--plan", "p", "--task", "1.1", "--claim", "1",
                        "--break", "b", "--test", "t"], "give --build"),
    ("prove-claim.py", ["req", "--repo", "r", "--plan", "p", "--task", "1.1", "--req", "1",
                        "--check", "c"], "--check needs --break"),
    ("prove-claim.py", ["deviation", "--repo", "r", "--plan", "p", "--task", "1.1",
                        "--claim", "1", "--why", "short"], "10+ characters"),
    ("prove-claim.py", ["req", "--repo", "r", "--plan", "p", "--task", "1.1",
                        "--req", "first", "--check", "c"], "--req takes the requirement's number"),
    ("review-ledger-check.py", ["--repo", "r"], "--plan and --stage are required"),
    ("plan-flip-audit.py", ["p", "--vocab-replace"], "requires --vocab-file"),
    ("plan-flip-audit.py", ["p", "--flip-threshold", "0"], "must be >= 1"),
]


def check_after_parse(build):
    out = []
    root = build / "skills/executing-plans/scripts"
    # Every script stating a rule through check= has a row here, so a rule added later
    # cannot go untested.
    rowed = {name for name, _, _ in AFTER_PARSE}
    for skill in SKILLS:
        for f in sorted((build / "skills" / skill / "scripts").glob("*.py")):
            if re.search(r"\bcheck=(?!None)", f.read_text(errors="ignore")) and f.name not in rowed:
                out.append((False, f"{build.relative_to(REPO)}: {f.name} states a check= rule "
                            "and has no AFTER_PARSE row", ""))
    for name, args, words in AFTER_PARSE:
        script = root / name
        if not script.is_file():
            continue
        what = f"{build.relative_to(REPO)}: {name} {' '.join(args)}"
        r = wrapped("parse", script, args)
        example, why = example_of(r.stderr)
        if r.returncode == 2 and words in r.stderr and not why:
            out.append((True, f"{what}: refused at parse time with its example", ""))
        else:
            out.append((False, f"{what}: not refused with `{words}` and an example "
                        f"(exit {r.returncode}{', ' + why if why else ''})", r.stdout + r.stderr))
    return out


def check_state_refusals(build):
    """Refusals that need the run's state or a file: run for real, in a scratch dir."""
    root = build / "skills/executing-plans/scripts"
    label = f"{build.relative_to(REPO)}"
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        plan = tmp / "fixture-plan.md"
        plan.write_text(PLAN_FIXTURE)
        repo = tmp / "repo"
        repo.mkdir()
        git_repo(repo)
        cases = [
            ("owner-decision.py", ["match", "--plan", str(plan)], tmp, "--at is needed"),
            ("owner-decision.py", ["match", "--plan", str(plan), "--at", "stage"], tmp,
             "--at stage needs --stage"),
            ("prove-claim.py", ["claim", "--repo", str(repo), "--plan", str(plan), "--task",
                                "1.1", "--claim", "1", "--break", "the diff text itself",
                                "--test", "true", "--no-build-step", "no build here"],
             tmp, "--break file not found"),
        ]
        for name, args, cwd, words in cases:
            what = f"{label}: {name} {args[0]} ({words})"
            r = run([sys.executable, str(root / name), *args], cwd=cwd, stdin="")
            example, why = example_of(r.stderr)
            if r.returncode == 2 and words in r.stderr and not why:
                out.append((True, f"{what}: ends with its example", ""))
            else:
                out.append((False, f"{what}: exit {r.returncode}, {why or 'no ' + repr(words)}",
                            r.stdout + r.stderr))
    return out


def check_argparse_script(build, script):
    """Every parser of one script: a failed call ends with an example it accepts."""
    rel = script.relative_to(build).as_posix()
    label = f"{build.relative_to(REPO)}: {script.name}"
    out = []
    r = wrapped("subs", script, [])
    if r.returncode != 0 or not r.stdout.startswith("SUBS "):
        return [(False, f"{label}: its parser could not be read", r.stderr)]
    import json
    subs = json.loads(r.stdout[5:])
    for sub in [None] + subs:
        what = f"{label} {sub or '(top level)'}"
        args = [] if sub is None else [sub]
        r = wrapped("parse", script, args)
        if r.returncode == 0:
            # It takes no arguments: a wrong one is the failed call to test.
            args = args + ["--no-such-option"]
            r = wrapped("parse", script, args)
        if r.returncode != 2:
            out.append((False, f"{what}: `{' '.join(args)}` exits {r.returncode}, not 2",
                        r.stderr))
            continue
        example, why = example_of(r.stderr)
        if why:
            out.append((False, f"{what}: `{' '.join(args) or '(no arguments)'}`: {why}",
                        r.stderr))
            continue
        _, words, why = call_of(example, rel)
        if why:
            out.append((False, f"{what}: {why}", ""))
            continue
        if sub is not None and words[:1] != [sub]:
            out.append((False, f"{what}: the example calls {words[:1]}, not {sub}", example))
            continue
        r = wrapped("parse", script, words)
        if r.returncode == 0 and r.stdout.startswith("PARSED "):
            out.append((True, f"{what}: ends with an example it accepts", ""))
        else:
            out.append((False, f"{what}: its own example is refused: {example}", r.stderr))
    return out


def git_repo(root):
    for cmd in (["git", "init", "-q", "-b", "work"],
                # No hooks: a machine's own commit hooks are not this fixture's subject.
                ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty",
                 "-m", "base"]):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)


PLAN_FIXTURE = """# Project Plan: fixture
## Preflight
- [x] Dispatch roster — `0 of 1 tasks`
## Stage 1: one
**Depends on:** none
### Task 1.1: a task
- **Status:** [ ]
- **Dispatch:** NO
### Stage 1 Gate
- [ ] a check: `true`
"""


def check_plan_progress(build):
    """plan-progress.py's hand-written argument failures end with an example too."""
    script = build / "skills/executing-plans/scripts/plan-progress.py"
    rel = script.relative_to(build).as_posix()
    label = f"{build.relative_to(REPO)}: plan-progress.py"
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        git_repo(repo)
        plan = repo / "fixture-plan.md"
        plan.write_text(PLAN_FIXTURE)
        fill = {"<plan>": str(plan), "<repo>": str(repo), "<ref>": "HEAD"}
        cases = [
            (["--dispatch-check"], 2),
            (["--dispatch-check", str(plan), "--since"], 2),
            (["--stage-order-check", "--stage", "two"], 2),
            (["--stage-order-check", "--stage", "1"], 2),
        ]
        text = script.read_text()
        if '"--json" in sys.argv' in text:
            cases.append((["--json", "extra"], 2))
        else:
            # A fork with no renderer: a bare call is a missing mode, exit 64.
            cases.append(([], 64))
        for args, code in cases:
            what = f"{label} `{' '.join(a if a != str(plan) else '<plan>' for a in args)}`"
            r = run([sys.executable, str(script), *args], cwd=repo, stdin="")
            if r.returncode != code:
                out.append((False, f"{what}: exits {r.returncode}, not {code}", r.stderr))
                continue
            example, why = example_of(r.stderr)
            if why:
                out.append((False, f"{what}: {why}", r.stderr))
                continue
            stdin, words, why = call_of(example, rel)
            if why:
                out.append((False, f"{what}: {why}", ""))
                continue
            if args and words[:1] != args[:1]:
                out.append((False, f"{what}: the example calls {words[:1]}", example))
                continue
            words = [fill.get(w, w) for w in words]
            if stdin is not None:
                for k, v in fill.items():
                    stdin = stdin.replace(k, v)
            r = run([sys.executable, str(script), *words], cwd=repo,
                    stdin=stdin if stdin is not None else "")
            if "example: " in r.stderr:
                out.append((False, f"{what}: its own example is an argument error: {example}",
                            r.stderr))
            else:
                out.append((True, f"{what}: ends with an example it accepts", ""))
    return out


def check_claim_text(build):
    """The commonest error: the claim's text passed to --claim, which takes a number."""
    script = build / "skills/executing-plans/scripts/prove-claim.py"
    label = f"{build.relative_to(REPO)}: prove-claim.py"
    want = "--claim takes the claim's number (1 is the task's first claim), not its text"
    out = []
    for args in (["claim", "--repo", "r", "--plan", "p", "--task", "1.1",
                  "--claim", "the parser refuses a bad line", "--break", "b", "--test", "t"],
                 ["deviation", "--repo", "r", "--plan", "p", "--task", "1.1",
                  "--claim", "the parser refuses a bad line", "--why", "w"]):
        r = wrapped("parse", script, args)
        example, _ = example_of(r.stderr)
        if r.returncode == 2 and want in r.stderr and example and "--claim 1" in example:
            out.append((True, f"{label} {args[0]}: a text --claim draws the number message", ""))
        else:
            out.append((False, f"{label} {args[0]}: a text --claim does not say it takes "
                        "the claim's number and show `--claim 1`", r.stderr))
    return out


def check_plan_state_missing(build):
    """plan-state.py's own refusal of a missing revision or id names the call too."""
    script = build / "skills/executing-plans/scripts/plan-state.py"
    rel = script.relative_to(build).as_posix()
    label = f"{build.relative_to(REPO)}: plan-state.py"
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        git_repo(Path(tmp))
        r = run([sys.executable, str(script), "transition", "--repo", tmp], stdin="{}")
        example, why = example_of(r.stderr)
        if r.returncode != 3 or '"state_error"' not in r.stdout:
            out.append((False, f"{label}: a missing --expected-revision no longer exits 3 "
                        "with its state_error", r.stdout + r.stderr))
        elif why:
            out.append((False, f"{label}: a missing --expected-revision: {why}", r.stderr))
        else:
            _, words, why = call_of(example, rel)
            p = wrapped("parse", script, words or [])
            if why or p.returncode != 0 or "--expected-revision" not in words \
                    or "--operation-id" not in words:
                out.append((False, f"{label}: the example for a missing revision is not a "
                            f"full call it accepts: {example}", why or p.stderr))
            else:
                out.append((True, f"{label}: a missing revision or id shows the full call", ""))
    return out


def main():
    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        for build in BUILDS:
            if not build.is_dir():
                bad(f"{build.relative_to(REPO)}: build missing")
                continue
            scripts = list(argparse_scripts(build))
            names = {s.name for s in scripts}
            shipped = {n for n in KNOWN if any((build / "skills" / k / "scripts" / n).is_file()
                                               for k in SKILLS)}
            if shipped - names or not shipped:
                bad(f"{build.relative_to(REPO)}: argparse scripts missing from the set: "
                    f"{sorted(shipped - names) or 'none shipped'}")
            else:
                ok(f"{build.relative_to(REPO)}: all {len(shipped)} known argparse scripts it "
                   f"ships are in the set ({len(scripts)} in all)")
            jobs.append(pool.submit(check_after_parse, build))
            jobs.append(pool.submit(check_state_refusals, build))
            for s in scripts:
                jobs.append(pool.submit(check_argparse_script, build, s))
            jobs.append(pool.submit(check_plan_progress, build))
            jobs.append(pool.submit(check_claim_text, build))
            jobs.append(pool.submit(check_plan_state_missing, build))
        for job in jobs:
            for good, msg, detail in job.result():
                ok(msg) if good else bad(msg, detail)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed or not passed else 0


if __name__ == "__main__":
    sys.exit(main())
