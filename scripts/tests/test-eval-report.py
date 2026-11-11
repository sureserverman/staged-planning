#!/usr/bin/env python3
"""eval-report.py reads plugin-eval results and refuses to call an unmeasured run a zero.

The behaviour-rule measurement rests on four readings of `claude plugin eval --json`
results. Each one is only worth having if it can fail, so every check here builds
synthetic result files in a temp folder (shaped like the harness's own: cases[].name,
cases[].graders[] definitions, cases[].arms.with[] runs with score, error, turns,
passed and graders[].passed) and runs the script over them.

  pilot      non-zero when a control run scores 0.5 or more, a real case scores below 0.5,
             a case of the six is missing, or any run has error set or skipped its paid graders
  matrix     non-zero on a missing cell, or a cell short of --expect-runs clean runs,
             that not-measured.txt does not name; on a cell whose model, plugin folder or
             case contradicts its name or cannot be read; on a partial result
  table      a run with error set or skipped paid graders reads `not measured`, never a
             zero; output is stable
  tool-used  non-zero when no clean run's graders show the tool was used
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scripts", "eval-report.py")
RULES = ("R1", "R2", "R3")
ARMS = ("with", "without")
MODELS = ("claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5")
RULE_CASE = {"R1": "gate-blocked", "R2": "run-to-completion", "R3": "dispatch-mandated"}
FAILS = []


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[-900:].replace("\n", "\n     | "))


def run(*args):
    return subprocess.run([sys.executable, "-B", SCRIPT, *args], capture_output=True, text=True)


def a_run(score=1.0, error=None, turns=5, passed=None, graders=None, skipped=False):
    if passed is None:
        passed = error is None and score >= 1.0
    if graders is None:
        graders = [] if error else [{"name": "result", "passed": passed, "scored": True}]
    return {"score": score, "error": error, "turns": turns, "passed": passed,
            "tracePath": "trace.jsonl", "graders": graders, "skippedPaidGraders": skipped}


def result(case, runs, model="claude-fable-5-2", definitions=None, plugin="with", partial=False):
    if definitions is None:
        definitions = [{"name": "result", "type": "regex", "weight": 1,
                        "config": {"target": "last_message", "pattern": "x"}}]
    suite = {"ablation": "none"}
    if model is not None:
        suite["modelOverride"] = model
    if plugin is not None:
        suite["plugins"] = [{"name": "planning", "path": f"/x/out/{plugin}"}]
    return {"schemaVersion": 1, "partial": partial,
            "suite": suite,
            "cases": [{"name": case, "graders": definitions,
                       "aggregates": {"score": 0, "passRate": 0},
                       "arms": {"with": runs}}]}


def dump(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


tmp = tempfile.mkdtemp(prefix="eval-report-test-")
try:
    # ------------------------------------------------------------------ pilot
    p = os.path.join(tmp, "pilot")
    os.makedirs(p)
    good = {}
    for case, score, model in (("gate-blocked", 1.0, "claude-fable-5-2"),
                               ("run-to-completion", 1.0, "claude-fable-5-2"),
                               ("dispatch-mandated", 1.0, "claude-fable-5-2"),
                               ("gate-blocked-control", 0.0, "claude-sonnet-5-5"),
                               ("run-to-completion-control", 0.4, "claude-sonnet-5-5"),
                               ("dispatch-mandated-control", 0.1, "claude-sonnet-5-5")):
        f = os.path.join(p, f"{case}.json")
        dump(f, result(case, [a_run(score=score, turns=7)], model=model))
        good[case] = f
    r = run("pilot", *good.values())
    check(r.returncode == 0, "pilot: controls below 0.5, real cases at 0.5 or more, no errors exit 0",
          r.stdout + r.stderr)
    check("run-to-completion-control" in r.stdout and "claude-sonnet-5-5" in r.stdout and "0.40" in r.stdout
          and "7" in r.stdout, "pilot: prints case, model, score and turns per run", r.stdout)

    def others(*leave):
        return [f for c, f in good.items() if c not in leave]

    f = os.path.join(p, "dmc-half.json")
    dump(f, result("dispatch-mandated-control", [a_run(score=0.5)], model="claude-sonnet-5-5"))
    r = run("pilot", *others("dispatch-mandated-control"), f)
    check(r.returncode != 0 and "dispatch-mandated-control" in (r.stdout + r.stderr),
          "pilot: a control scoring 0.5 exits non-zero naming it", r.stdout + r.stderr)

    f = os.path.join(p, "real-scores-half.json")
    dump(f, result("dispatch-mandated", [a_run(score=0.5)]))
    r = run("pilot", *others("dispatch-mandated"), f)
    check(r.returncode == 0, "pilot: a real case scoring 0.5 is not a failure", r.stdout + r.stderr)

    f = os.path.join(p, "real-did-nothing.json")
    dump(f, result("gate-blocked", [a_run(score=0.33)]))
    r = run("pilot", *others("gate-blocked"), f)
    check(r.returncode != 0 and "gate-blocked" in (r.stdout + r.stderr),
          "pilot: a real case scoring below 0.5 (the harness could not run the plan) exits non-zero",
          r.stdout + r.stderr)

    r = run("pilot", good["gate-blocked"], good["run-to-completion"], good["dispatch-mandated"])
    check(r.returncode != 0 and "gate-blocked-control" in (r.stdout + r.stderr),
          "pilot: a set with no control exits non-zero naming the missing controls", r.stdout + r.stderr)
    r = run("pilot", *others("run-to-completion"))
    check(r.returncode != 0 and "run-to-completion" in (r.stdout + r.stderr),
          "pilot: a control without its real twin exits non-zero", r.stdout + r.stderr)

    f = os.path.join(p, "skipped.json")
    dump(f, result("gate-blocked-control", [a_run(score=0.0, skipped=True)], model="claude-sonnet-5-5"))
    r = run("pilot", *others("gate-blocked-control"), f)
    check(r.returncode != 0 and "paid graders" in (r.stdout + r.stderr),
          "pilot: a run that skipped its paid graders exits non-zero", r.stdout + r.stderr)

    f = os.path.join(p, "partial.json")
    dump(f, result("gate-blocked-control", [a_run(score=0.0)], model="claude-sonnet-5-5", partial=True))
    r = run("pilot", *others("gate-blocked-control"), f)
    check(r.returncode != 0 and "partial" in r.stderr and "None" not in r.stderr,
          "pilot: a partial result exits non-zero without printing a None reason", r.stdout + r.stderr)

    f = os.path.join(p, "limit.json")
    dump(f, result("run-to-completion", [a_run(score=0.0, error="usage limit reached")]))
    r = run("pilot", *others("run-to-completion"), f)
    check(r.returncode != 0 and "usage limit reached" in (r.stdout + r.stderr),
          "pilot: a run with error set exits non-zero and shows the error", r.stdout + r.stderr)

    f = os.path.join(p, "empty.json")
    dump(f, result("gate-blocked", []))
    r = run("pilot", f)
    check(r.returncode != 0, "pilot: a file with no runs exits non-zero", r.stdout + r.stderr)

    # ------------------------------------------------------------------ matrix
    m = os.path.join(tmp, "matrix")
    os.makedirs(m)
    cells = [f"{rule}-{arm}-{model}" for rule in RULES for arm in ARMS for model in MODELS]
    check(len(cells) == 18, "matrix: 18 cells in the fixture")
    for cell in cells:
        rule, arm = cell.split("-")[0], cell.split("-")[1]
        model = cell.split("-", 2)[2]
        plugin = "with" if arm == "with" else f"without-{rule}"
        dump(os.path.join(m, f"{cell}.json"), result(RULE_CASE[rule], [a_run()], model=model, plugin=plugin))
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode == 0, "matrix: 18 cells with one clean run each exit 0", r.stdout + r.stderr)
    r = run("matrix", m, "--expect-runs", "2")
    check(r.returncode != 0, "matrix: --expect-runs 2 over one-run cells exits non-zero", r.stdout + r.stderr)

    # Each label check, one at a time: the cell is restored after each.
    lab = "R1-without-claude-opus-5-5"
    lab_path = os.path.join(m, f"{lab}.json")
    for what, data in (
            ("a recorded model that contradicts the file name",
             result("gate-blocked", [a_run()], model="claude-sonnet-5-5", plugin="without-R1")),
            ("a plugin folder that contradicts the file name",
             result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin="without-R2")),
            ("a with-build file saved under a without name",
             result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin="with")),
            ("no recorded model",
             result("gate-blocked", [a_run()], model=None, plugin="without-R1")),
            ("no plugin folder",
             result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin=None)),
            ("a plugin folder that is neither with nor without-<rule>",
             result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin="build-2")),
            ("another rule's case",
             result("run-to-completion", [a_run()], model="claude-opus-5-5", plugin="without-R1")),
            ("a control case",
             result("gate-blocked-control", [a_run()], model="claude-opus-5-5", plugin="without-R1")),
            ("a partial result",
             result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin="without-R1", partial=True))):
        dump(lab_path, data)
        r = run("matrix", m, "--expect-runs", "1")
        check(r.returncode != 0 and lab in (r.stdout + r.stderr),
              f"matrix: {what} exits non-zero naming the cell", r.stdout + r.stderr)
    two = result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin="without-R1")
    two["cases"].append(dict(two["cases"][0]))
    dump(lab_path, two)
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode != 0 and lab in (r.stdout + r.stderr),
          "matrix: a cell file holding two cases exits non-zero naming it", r.stdout + r.stderr)
    dump(lab_path, result("gate-blocked", [a_run(skipped=True)], model="claude-opus-5-5", plugin="without-R1"))
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode != 0 and lab in (r.stdout + r.stderr),
          "matrix: a run that skipped its paid graders is not a clean run", r.stdout + r.stderr)
    dump(lab_path, result("gate-blocked", [a_run()], model="claude-opus-5-5", plugin="without-R1"))
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode == 0, "matrix: the restored cell passes again", r.stdout + r.stderr)

    gone = "R2-without-claude-opus-5-5"
    os.rename(os.path.join(m, f"{gone}.json"), os.path.join(tmp, "parked.json"))
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode != 0 and gone in (r.stdout + r.stderr),
          "matrix: a missing cell exits non-zero naming it", r.stdout + r.stderr)
    nm = os.path.join(m, "not-measured.txt")
    with open(nm, "w", encoding="utf-8") as fh:
        fh.write(f"# cells with no clean run\n{gone} usage limit reached\n")
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode == 0, "matrix: a missing cell named in not-measured.txt passes", r.stdout + r.stderr)
    with open(nm, "w", encoding="utf-8") as fh:
        fh.write(f"{gone}\n")
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode != 0, "matrix: a not-measured.txt line without error text exits non-zero",
          r.stdout + r.stderr)
    with open(nm, "w", encoding="utf-8") as fh:
        fh.write(f"{gone} usage limit reached\nR1-with-claude-fable-5-2 usage limit reached\n")
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode != 0 and "R1-with-claude-fable-5-2" in (r.stdout + r.stderr),
          "matrix: a cell named in not-measured.txt that has its clean runs exits non-zero",
          r.stdout + r.stderr)
    with open(nm, "w", encoding="utf-8") as fh:
        fh.write(f"{gone} usage limit reached\n")

    short = "R3-with-claude-sonnet-5-5"
    dump(os.path.join(m, f"{short}.json"),
         result("dispatch-mandated", [a_run(score=0.0, error="harness: run could not start")],
                model="claude-sonnet-5-5"))
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode != 0 and short in (r.stdout + r.stderr),
          "matrix: a cell whose only run has error set, unnamed, exits non-zero naming it",
          r.stdout + r.stderr)
    with open(nm, "a", encoding="utf-8") as fh:
        fh.write(f"{short} harness: run could not start\n")
    r = run("matrix", m, "--expect-runs", "1")
    check(r.returncode == 0, "matrix: the short cell named in not-measured.txt passes", r.stdout + r.stderr)

    # ------------------------------------------------------------------ table
    mixed = "R1-with-claude-fable-5-2"
    dump(os.path.join(m, f"{mixed}.json"),
         result("gate-blocked", [a_run(score=1.0), a_run(score=0.0, error="usage limit reached"),
                                 a_run(score=0.0, skipped=True)]))
    half = "R1-without-claude-fable-5-2"
    dump(os.path.join(m, f"{half}.json"),
         result("gate-blocked", [a_run(score=1.0), a_run(score=0.5, passed=False)], plugin="without-R1"))
    t1 = run("table", m)
    t2 = run("table", m)
    out = t1.stdout
    check(t1.returncode == 0, "table: exits 0", t1.stdout + t1.stderr)
    check(t1.stdout == t2.stdout, "table: output is identical across runs")
    rows = [line for line in out.splitlines() if re.match(r"\| R\d+ \|", line)]
    check(len(rows) == 18, "table: one row per cell (18)", out)
    lines = {tuple(c.strip() for c in line.strip("|").split("|"))[:3]: line for line in rows}
    row = lines.get(("R1", "claude-fable-5-2", "with"), "")
    check("1.00" in row and "0.50" not in row and "0.33" not in row and "(+2 not measured)" in row,
          "table: an errored run and a run that skipped its paid graders are left out of the mean", row)
    row = lines.get(("R1", "claude-fable-5-2", "without"), "")
    check(row == "| R1 | claude-fable-5-2 | without | 2 | 50% | 0.75 |",
          "table: two clean runs give runs 2, pass rate 50%, mean 0.75", row)
    row = lines.get(("R3", "claude-sonnet-5-5", "with"), "")
    check("not measured" in row and "0.00" not in row and "0%" not in row,
          "table: a cell whose only run errored reads not measured, never a zero", row)
    row = lines.get(("R2", "claude-opus-5-5", "without"), "")
    check("not measured" in row, "table: a missing cell reads not measured", row)
    order = [tuple(c.strip() for c in line.strip("|").split("|"))[:3] for line in rows]
    want = [(rule, model, arm) for rule in RULES for model in MODELS for arm in ARMS]
    check(order == want, "table: rows are ordered rule, model, arm", order)

    # ------------------------------------------------------------------ tool-used
    defs = [{"name": "dispatched", "type": "tool_used", "weight": 1,
             "config": {"tool": "Agent", "min": 1}},
            {"name": "never-bash", "type": "tool_used", "weight": 1,
             "config": {"tool": "Bash", "min": 0, "max": 0}},
            {"name": "result", "type": "regex", "weight": 1, "config": {"pattern": "x"}}]
    tu = os.path.join(tmp, "R3-with-claude-fable-5-2.json")
    dump(tu, result("dispatch-mandated", [a_run(graders=[
        {"name": "dispatched", "passed": True, "scored": True},
        {"name": "never-bash", "passed": True, "scored": True},
        {"name": "result", "passed": True, "scored": True}])], definitions=defs))
    r = run("tool-used", tu, "Agent")
    check(r.returncode == 0, "tool-used: a passed tool_used grader for Agent exits 0", r.stdout + r.stderr)
    r = run("tool-used", tu, "Bash")
    check(r.returncode != 0, "tool-used: a passing never-called (max 0) grader does not count as used",
          r.stdout + r.stderr)
    r = run("tool-used", tu, "Write")
    check(r.returncode != 0 and "Write" in (r.stdout + r.stderr),
          "tool-used: no tool_used grader for the tool exits non-zero naming it", r.stdout + r.stderr)
    dump(tu, result("dispatch-mandated", [a_run(score=0.5, graders=[
        {"name": "dispatched", "passed": False, "scored": True},
        {"name": "result", "passed": True, "scored": True}])], definitions=defs))
    r = run("tool-used", tu, "Agent")
    check(r.returncode != 0, "tool-used: a failed Agent grader exits non-zero", r.stdout + r.stderr)
    dump(tu, result("dispatch-mandated", [a_run(score=0.0, error="usage limit reached", graders=[
        {"name": "dispatched", "passed": True, "scored": True}])], definitions=defs))
    r = run("tool-used", tu, "Agent")
    check(r.returncode != 0, "tool-used: a run with error set is not evidence of use",
          r.stdout + r.stderr)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s) failed")
    sys.exit(1)
print("PASS: eval-report fails on a passing control, a short matrix, an unmeasured zero and an unused tool")
