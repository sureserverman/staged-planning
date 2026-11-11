#!/usr/bin/env python3
"""Read `claude plugin eval --json` results for the behaviour-rule measurement.

A run that ended on a usage limit or a harness error scores 0 and carries an `error`.
That 0 is not a measurement, and neither is a score from a run whose paid (llm) graders
were skipped (`skippedPaidGraders: true`). Every reading here keeps such a run out of
every count and average and shows it as `not measured` instead. Each subcommand exits
non-zero on the failure it names, so a gate built on it can fail.

The results come from `claude plugin eval <build> --case <case> --model <id> --runs N
--ablation none --no-publish --trust-plugin --scaffold --allow-tools Write Edit Bash
--json <file>`. The cases cannot grant Write, Edit or Bash themselves; without
`--allow-tools` no case can execute its plan, and every run measures that instead.

Usage:
  eval-report.py pilot <result.json>...
  eval-report.py matrix <dir> --expect-runs N
  eval-report.py table <dir>
  eval-report.py tool-used <cell.json> <Tool>

pilot      prints one line per run: file, case, model, score, turns, error. Exits 1 when
           a control case (name ends `-control`) has a run scoring 0.5 or more (its
           grader passed the sabotage it exists to catch); a real case has a run scoring
           below 0.5 (the session could not do the work, so its control's low score
           proves nothing); one of the six cases (three real, three controls) has no
           run; any run is not clean (`error` set, or paid graders skipped); a file
           holds no runs; or a result is marked `partial`.
matrix     checks the 18 cells <rule>-<with|without>-<model>.json in <dir> (rules R1-R3;
           models claude-fable-5-2, claude-opus-5-5, claude-sonnet-5-5). Exits 1 on a
           missing cell or a cell with fewer than N clean runs (runs with `error` null)
           that <dir>/not-measured.txt does not name; on a cell that file names but that
           has N clean runs; on a cell file with other than one case or marked
           `partial`; and on a cell whose recorded model (suite.modelOverride), plugin
           folder (with / without-<rule>) or case (the rule's own real case) contradicts
           its file name or cannot be read.
table      prints a Markdown table, one row per cell in rule, model, arm order: clean runs
           (with `(+k not measured)` when k runs had `error` set), pass rate (clean runs
           with `passed` true) and mean score over clean runs, both as `not measured`
           when a cell has no clean run or no file. Output is deterministic.
tool-used  exits 0 when at least one clean run in the cell passed a `tool_used` grader
           for <Tool> that requires a call (min of 1 or more, max not 0); exits 1 when no
           such grader exists or none passed.

not-measured.txt: one cell per line, `<cell> <the harness's own error text>`, where
<cell> is the file name without `.json` (e.g. `R2-without-claude-opus-5-5 usage limit
reached`). Blank lines and lines starting with `#` are ignored. The error text is
required.

Fields read (anything else is ignored): cases[].name, cases[].graders[] (name, type,
config.tool/min/max), cases[].arms.with[] (score, error, skippedPaidGraders, turns,
passed, graders[].name, graders[].passed), suite.modelOverride, suite.plugins[].path,
partial, partialReason.
"""
import argparse
import json
import os
import re
import sys

RULES = ("R1", "R2", "R3")
MODELS = ("claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5")
ARMS = ("with", "without")
CELLS = [f"{r}-{a}-{m}" for r in RULES for a in ARMS for m in MODELS]
NOT_MEASURED = "not-measured.txt"
CONTROL_LIMIT = 0.5
# Each rule's own case; its control is `<case>-control`. The matrix runs the real case.
RULE_CASE = {"R1": "gate-blocked", "R2": "run-to-completion", "R3": "dispatch-mandated"}
PILOT_CASES = sorted([*RULE_CASE.values(), *(c + "-control" for c in RULE_CASE.values())])


class ReportError(Exception):
    pass


def fail(msg):
    print(f"eval-report: {msg}", file=sys.stderr)


# ------------------------------------------------------------------ reading

def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ReportError(f"cannot read result {path}: {exc}")
    if not isinstance(doc, dict) or not isinstance(doc.get("cases"), list):
        raise ReportError(f"{path}: not an eval result (no 'cases' list)")
    for case in doc["cases"]:
        arms = case.get("arms") if isinstance(case, dict) else None
        runs = arms.get("with") if isinstance(arms, dict) else None
        if not isinstance(runs, list):
            raise ReportError(f"{path}: case {case.get('name') if isinstance(case, dict) else case!r} "
                              f"has no arms.with list")
        for run in runs:
            if not isinstance(run, dict):
                raise ReportError(f"{path}: a run in case {case.get('name')!r} is not an object")
            if run.get("error") is None and not is_number(run.get("score")):
                raise ReportError(f"{path}: a run in case {case.get('name')!r} has no numeric score")
    return doc


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def model_of(doc):
    m = doc.get("suite", {}).get("modelOverride") if isinstance(doc.get("suite"), dict) else None
    return m if isinstance(m, str) and m else None


def runs_of(doc):
    for case in doc["cases"]:
        for run in case["arms"]["with"]:
            yield case, run


def clean(run):
    return run.get("error") is None and run.get("skippedPaidGraders") is not True


def why_unclean(run):
    if run.get("error") is not None:
        return f"error set: {run['error']}"
    return "paid graders skipped (skippedPaidGraders: true)"


def partial_text(doc):
    reason = doc.get("partialReason")
    return f"result is partial ({reason})" if isinstance(reason, str) and reason else "result is partial"


def run_passed(run):
    if isinstance(run.get("passed"), bool):
        return run["passed"]
    scored = [g for g in run.get("graders") or [] if isinstance(g, dict) and g.get("scored") is not False]
    return bool(scored) and all(g.get("passed") is True for g in scored)


def fmt_score(v):
    return f"{v:.2f}" if is_number(v) else "-"


# ------------------------------------------------------------------ pilot

def pilot(args):
    problems = []
    seen = set()
    print("file | case | model | score | turns | error")
    for path in args.files:
        doc = load(path)
        name = os.path.basename(path)
        if doc.get("partial"):
            problems.append(f"{name}: {partial_text(doc)}")
        count = 0
        for case, run in runs_of(doc):
            count += 1
            cname = case.get("name", "?")
            seen.add(cname)
            err = run.get("error")
            print(f"{name} | {cname} | {model_of(doc) or 'unknown'} | {fmt_score(run.get('score'))} | "
                  f"{run.get('turns', '-')} | {err if err is not None else '-'}")
            if not clean(run):
                problems.append(f"{name}: case {cname} run is not a measurement: {why_unclean(run)}")
            elif cname.endswith("-control") and run["score"] >= CONTROL_LIMIT:
                problems.append(f"{name}: control {cname} scored {fmt_score(run['score'])} "
                                f"(>= {CONTROL_LIMIT}): its grader passed the sabotage it must catch")
            elif not cname.endswith("-control") and run["score"] < CONTROL_LIMIT:
                problems.append(f"{name}: real case {cname} scored {fmt_score(run['score'])} "
                                f"(< {CONTROL_LIMIT}): the session did not do the work, so its "
                                f"control's score proves nothing")
        if count == 0:
            problems.append(f"{name}: holds no runs")
    missing = [c for c in PILOT_CASES if c not in seen]
    if missing:
        problems.append(f"pilot: no run for {', '.join(missing)} (needs all six: each real case "
                        f"and its control)")
    for p in problems:
        fail(p)
    if problems:
        fail(f"pilot: {len(problems)} problem(s); stop before the matrix")
        return 1
    print("pilot: all six cases ran; every control scored below 0.5, every real case 0.5 or "
          "more, and every run is a measurement")
    return 0


# ------------------------------------------------------------------ matrix

def read_not_measured(d):
    path = os.path.join(d, NOT_MEASURED)
    named = {}
    if not os.path.exists(path):
        return named
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cell, _, text = line.partition(" ")
            if cell not in CELLS:
                raise ReportError(f"{NOT_MEASURED}:{n}: {cell!r} is not one of the 18 cells")
            if not text.strip():
                raise ReportError(f"{NOT_MEASURED}:{n}: {cell} needs the harness's error text after the cell name")
            if cell in named:
                raise ReportError(f"{NOT_MEASURED}:{n}: {cell} is named twice")
            named[cell] = text.strip()
    return named


def cell_runs(d, cell):
    """(doc, clean runs, not-measured runs), or None when the file is absent."""
    path = os.path.join(d, f"{cell}.json")
    if not os.path.exists(path):
        return None
    doc = load(path)
    if len(doc["cases"]) != 1:
        raise ReportError(f"{cell}.json holds {len(doc['cases'])} cases; a cell holds exactly one")
    runs = [run for _, run in runs_of(doc)]
    return doc, [r for r in runs if clean(r)], [r for r in runs if not clean(r)]


def label_problems(cell, doc):
    """Every label the file name asserts must be read from the result and agree."""
    rule, arm, model = cell.split("-", 2)
    out = []
    if doc.get("partial"):
        out.append(f"{cell}: {partial_text(doc)}")
    recorded = model_of(doc)
    if recorded is None:
        out.append(f"{cell}: no recorded model (suite.modelOverride); the file name cannot be checked")
    elif recorded != model:
        out.append(f"{cell}: recorded model {recorded!r} contradicts the file name")
    plugins = doc.get("suite", {}).get("plugins") if isinstance(doc.get("suite"), dict) else None
    paths = [p.get("path") for p in plugins or [] if isinstance(p, dict) and isinstance(p.get("path"), str)]
    want = "with" if arm == "with" else f"without-{rule}"
    if len(paths) != 1:
        out.append(f"{cell}: {len(paths)} plugin path(s) recorded (suite.plugins); expected one "
                   f"ending in {want!r}")
    else:
        base = os.path.basename(paths[0].rstrip("/\\"))
        if not re.fullmatch(r"with|without-R\d+", base):
            out.append(f"{cell}: plugin folder {base!r} is neither 'with' nor 'without-<rule>'; "
                       f"the arm cannot be checked")
        elif base != want:
            out.append(f"{cell}: ran against plugin folder {base!r}, file name says {want!r}")
    names = [c.get("name") for c in doc["cases"]]
    if names != [RULE_CASE[rule]]:
        out.append(f"{cell}: holds case {names[0] if names else None!r}; {rule}'s case is "
                   f"{RULE_CASE[rule]!r}")
    return out


def matrix(args):
    d = args.dir
    if not os.path.isdir(d):
        raise ReportError(f"results folder not found: {d}")
    if args.expect_runs < 1:
        raise ReportError("--expect-runs must be 1 or more")
    named = read_not_measured(d)
    problems = []
    for cell in CELLS:
        got = cell_runs(d, cell)
        if got is None:
            have, why = 0, "missing"
        else:
            doc, good, bad = got
            problems.extend(label_problems(cell, doc))
            have, why = len(good), f"{len(good)} clean run(s), {len(bad)} not measured (error set or paid graders skipped)"
        if have >= args.expect_runs:
            if cell in named:
                problems.append(f"{cell}: named in {NOT_MEASURED} but has {have} clean run(s)")
            print(f"ok   {cell}: {why}")
        elif cell in named:
            print(f"nm   {cell}: {why}; not measured: {named[cell]}")
        else:
            problems.append(f"{cell}: {why}, expected {args.expect_runs} clean run(s), "
                            f"and {NOT_MEASURED} does not name it")
    for p in problems:
        fail(p)
    if problems:
        fail(f"matrix: {len(problems)} problem(s)")
        return 1
    print(f"matrix: all {len(CELLS)} cells measured or named in {NOT_MEASURED}")
    return 0


# ------------------------------------------------------------------ table

def table(args):
    d = args.dir
    if not os.path.isdir(d):
        raise ReportError(f"results folder not found: {d}")
    print("| Rule | Model | Arm | Runs | Pass rate | Mean score |")
    print("|---|---|---|---|---|---|")
    for rule in RULES:
        for model in MODELS:
            for arm in ARMS:
                got = cell_runs(d, f"{rule}-{arm}-{model}")
                good, bad = ([], []) if got is None else (got[1], got[2])
                runs = str(len(good)) + (f" (+{len(bad)} not measured)" if bad else "")
                if good:
                    rate = f"{100 * sum(run_passed(r) for r in good) / len(good):.0f}%"
                    mean = f"{sum(r['score'] for r in good) / len(good):.2f}"
                else:
                    rate = mean = "not measured"
                print(f"| {rule} | {model} | {arm} | {runs} | {rate} | {mean} |")
    return 0


# ------------------------------------------------------------------ tool-used

def grader_tool(g):
    cfg = g.get("config") if isinstance(g.get("config"), dict) else {}
    pick = lambda k, default=None: cfg.get(k, g.get(k, default))
    return pick("tool"), pick("min", 1), pick("max")


def requires_call(g, tool):
    if not isinstance(g, dict) or g.get("type") != "tool_used":
        return False
    t, lo, hi = grader_tool(g)
    return t == tool and is_number(lo) and lo >= 1 and not (is_number(hi) and hi < 1)


def tool_used(args):
    doc = load(args.cell)
    tool = args.tool
    defined = False
    used = False
    for case in doc["cases"]:
        names = {g.get("name") for g in case.get("graders") or [] if requires_call(g, tool)}
        names.discard(None)
        defined = defined or bool(names)
        for i, run in enumerate(case["arms"]["with"], 1):
            hits = [g for g in run.get("graders") or [] if isinstance(g, dict) and g.get("passed") is True
                    and (g.get("name") in names or requires_call(g, tool))]
            defined = defined or any(requires_call(g, tool) for g in run.get("graders") or [])
            state = "not measured (error set)" if not clean(run) else ("used" if hits else "not used")
            print(f"{case.get('name', '?')} run {i}: {tool} {state}")
            used = used or (clean(run) and bool(hits))
    if not defined:
        fail(f"{args.cell}: no tool_used grader for {tool} that requires a call (min >= 1)")
        return 1
    if not used:
        fail(f"{args.cell}: no clean run's graders show {tool} was used")
        return 1
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pilot", help="check pilot results: controls below 0.5, no errors")
    p.add_argument("files", nargs="+")
    m = sub.add_parser("matrix", help="check every cell is measured or named as not measured")
    m.add_argument("dir")
    m.add_argument("--expect-runs", type=int, required=True)
    t = sub.add_parser("table", help="print the rule x model x arm Markdown table")
    t.add_argument("dir")
    u = sub.add_parser("tool-used", help="exit 0 when a clean run's graders show the tool used")
    u.add_argument("cell")
    u.add_argument("tool")
    args = ap.parse_args(argv)
    try:
        return {"pilot": pilot, "matrix": matrix, "table": table, "tool-used": tool_used}[args.cmd](args)
    except ReportError as exc:
        fail(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
