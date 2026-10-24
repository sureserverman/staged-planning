#!/usr/bin/env python3
"""Re-run the plan validators over a corpus of real plans and compare with a record.

Why this exists: the gate heuristics state trigger rates measured over a corpus of real
plans. Real plans hold their owner's data, so they cannot be test fixtures in a
public repo: the in-repo tests use synthetic plans built for each case, and the real
corpus lives with its owner. This script is how that corpus still pins the classifiers.
It runs validate-gate-checks.py, validate-dispatch.py and plan-flip-audit.py over every
plan, one plan at a time, and compares each plan's classifications with
<dir>/expected.json.

The corpus is a home directory plus any extra sources. The home directory holds the
expected.json and some plans of its own (every *.md in it). An extra source is another
directory (every *.md in it) or a glob. --write-expected records the extra sources in
expected.json, so a later run given only the home directory reads them again: the record
always covers the same set it was written from.

What is compared, per plan and per tool:
  validate-gate-checks  exit code, the per-class counts and every separate-axis or
                        advisory count from its summary
  validate-dispatch     exit code, the count of each FAIL class, the count of notes
  plan-flip-audit       exit code, the count of each finding and severity, and which
                        checks ran
Each plan's sha256 is recorded too, so a difference says whether the plan changed or
the classifier did.

plan-flip-audit runs without --repo, with the plan's own directory as its cwd. So
findings 8-10 (which read a project repo's task commits) never run, and findings 1, 3
and 5 read git history only when the plan itself sits in a git repository: there they
run over the commits that touch the plan; elsewhere they run only from a --snapshot
baseline under the plan's directory, and otherwise not at all (checks_run says which).
For a frozen plan that matters: committing it, moving it into or out of a repository,
rewriting the history that touches it, or a baseline appearing beside it can change its
plan-flip-audit record while its sha256 stays the same, which reads as a classifier
DIFF. Keep the home directory outside any repository, or re-record after such a move.

A tool result that cannot be read is an error, never a recorded expectation. Each tool
has a normal set of exit codes, from its own documentation: validate-gate-checks 0 or 1
with its "N gate check(s) across M file(s): …" summary, or 2 with its "found 0 gate
checks" line (a file with no gate check is a real outcome, recorded as rc 2 with no
counts); validate-dispatch 0 or 1, printing only `note:` lines on stdout and `FAIL:`
lines on stderr, with at least one FAIL when it exits 1 (its 2, an unreadable plan or
sub-plan, is an error); plan-flip-audit 0, 1 or 4 with a JSON document on stdout (its
2, a usage or internal error, is an error; 3 needs --require-all-checks, never passed).
Anything else — an exit code outside that set, a missing summary, garbage, a tool that
could not start — is an ERROR for that plan and tool. --write-expected then refuses
(exit 2, nothing written, each plan and tool named), and a compare run fails (exit 1,
"ERROR <key>: <tool>: …"); that tool is not compared for that plan.

The home plans are frozen; the extra sources are live, edited as their plans are worked.
Exit 1 on a difference that can only be a regression: any change to a home plan (a
changed classification, MISSING, NEW, or content changed with every classification the
same: "CHANGED <key>: frozen plan edited"), a changed classification on any plan whose
content is unchanged, or any ERROR. An edited, new or gone live plan is printed as a
NOTE and does not fail the run (a live plan whose content changed but whose
classifications did not prints nothing); re-record with --write-expected to fold those
in. A recorded live source that now matches no plan (its directory emptied, its glob
matching nothing) is not an error: each plan recorded from it is a NOTE "gone". Exit 0
otherwise. The summary line counts "N difference(s), M note(s)", plus "E error(s)" when
there are any.

Exit 2 when the run would read nothing or would compare against the wrong record: a
missing or unreadable home directory, a home with no plan, a missing or malformed
expected.json, an extra source that is not a directory or a glob, an extra source given
while writing that matches no plan, and — on a compare run — an extra source given on
the command line that is not recorded in expected.json ("not in the record; re-record
with --write-expected"), whether or not it matches plans. A run that read nothing must
not look like a pass.

Usage:
  corpus-regress.py --corpus <dir> [--corpus <dir-or-glob> ...]
  corpus-regress.py --corpus <dir> [--corpus <dir-or-glob> ...] --write-expected

Stdlib only.
"""
import argparse
import collections
import concurrent.futures
import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = {
    "validate-gate-checks": os.path.join(
        REPO, "core", "skills", "planning-projects", "scripts", "validate-gate-checks.py"),
    "validate-dispatch": os.path.join(
        REPO, "core", "skills", "planning-projects", "scripts", "validate-dispatch.py"),
    "plan-flip-audit": os.path.join(
        REPO, "core", "skills", "executing-plans", "scripts", "plan-flip-audit.py"),
}
EXPECTED = "expected.json"
FORMAT = 1

TOTALS = re.compile(r"^\d+ gate check\(s\) across \d+ file\(s\): (.*)$")
AXIS = re.compile(r"^(.+?) (\d+) \((?:separate axis|advisory)")
VD_FAIL = re.compile(r"^FAIL: .*?: ([A-Z][A-Z-]+): ")
ZERO_CHECKS = re.compile(r"^error: swept \d+ file\(s\) and found 0 gate checks", re.M)


class UsageError(Exception):
    pass


class ToolError(Exception):
    """A tool's result could not be read: it is reported, never recorded."""


def _run(tool, args, cwd):
    try:
        r = subprocess.run([sys.executable, TOOLS[tool], *args], capture_output=True,
                           text=True, cwd=cwd)
    except (OSError, ValueError) as e:
        raise ToolError(f"could not start: {e}")
    return r.returncode, r.stdout, r.stderr


def _said(rc, out, err):
    """The tool's own words, shortened, for an ERROR line."""
    text = " | ".join(line.strip() for line in (err + "\n" + out).splitlines()
                      if line.strip())
    return f"exit {rc}: {text[:200] or 'no output'}"


def gate_result(path):
    rc, out, err = _run("validate-gate-checks", ["--quiet", path], os.path.dirname(path))
    if rc == 2 and ZERO_CHECKS.search(err):
        return {"rc": rc, "counts": {}}
    counts, summary = {}, False
    for line in out.splitlines():
        m = TOTALS.match(line)
        if m:
            summary = True
            for pair in m.group(1).split(", "):
                k, _, v = pair.rpartition(" ")
                if not v.isdigit():
                    raise ToolError(f"unreadable summary {line!r} ({_said(rc, out, err)})")
                counts[k] = int(v)
            continue
        m = AXIS.match(line)
        if m:
            counts[m.group(1)] = int(m.group(2))
    if rc not in (0, 1):
        raise ToolError(f"exit {rc} is not a result ({_said(rc, out, err)})")
    if not summary:
        raise ToolError(f"no summary line ({_said(rc, out, err)})")
    return {"rc": rc, "counts": counts}


def dispatch_result(path):
    rc, out, err = _run("validate-dispatch", [path], os.path.dirname(path))
    if rc not in (0, 1):
        raise ToolError(f"exit {rc} is not a result ({_said(rc, out, err)})")
    stray = [line for line in out.splitlines() if line.strip() and not line.startswith("note: ")]
    stray += [line for line in err.splitlines() if line.strip() and not VD_FAIL.match(line)]
    if stray:
        raise ToolError(f"unreadable output {stray[0][:120]!r} ({_said(rc, out, err)})")
    fails = collections.Counter(m.group(1) for m in map(VD_FAIL.match, err.splitlines()) if m)
    if (rc == 1) != bool(fails):
        raise ToolError(f"exit {rc} with {sum(fails.values())} FAIL line(s) "
                        f"({_said(rc, out, err)})")
    notes = sum(1 for line in out.splitlines() if line.startswith("note: "))
    return {"rc": rc, "fail": dict(sorted(fails.items())), "notes": notes}


def flip_result(path):
    rc, out, err = _run("plan-flip-audit", [path, "--json"], os.path.dirname(path))
    if rc not in (0, 1, 4):
        raise ToolError(f"exit {rc} is not a result ({_said(rc, out, err)})")
    try:
        doc = json.loads(out)
    except ValueError:
        raise ToolError(f"output is not JSON ({_said(rc, out, err)})")
    if (not isinstance(doc, dict) or not isinstance(doc.get("findings"), list)
            or not isinstance(doc.get("checks_run"), list)
            or not all(isinstance(f, dict) for f in doc["findings"])):
        raise ToolError(f"JSON without findings and checks_run ({_said(rc, out, err)})")
    found = collections.Counter(f"{f.get('finding')}:{f.get('severity')}"
                                for f in doc["findings"])
    return {"rc": rc, "findings": dict(sorted(found.items())),
            "checks_run": sorted(doc["checks_run"])}


READERS = {"validate-gate-checks": gate_result, "validate-dispatch": dispatch_result,
           "plan-flip-audit": flip_result}


def classify(path):
    """(record, errors): errors maps a tool to why its result could not be read; that
    tool is absent from the record."""
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    rec, errors = {"sha256": sha}, {}
    for tool in TOOLS:
        try:
            rec[tool] = READERS[tool](path)
        except ToolError as e:
            errors[tool] = str(e)
    return rec, errors


def expand(source, allow_empty=False):
    """The plans a source names: every *.md in a directory, or a glob's matches."""
    if os.path.isdir(source):
        found = glob.glob(os.path.join(glob.escape(source), "*.md"))
    elif glob.has_magic(source):
        found = [p for p in glob.glob(source) if os.path.isfile(p)]
    else:
        raise UsageError(f"not a directory or a glob: {source}")
    if not found and not allow_empty:
        raise UsageError(f"source matched no plan: {source}")
    return sorted(os.path.abspath(p) for p in found)


def plan_set(home, sources, recorded=()):
    """{key: path}. Home plans are keyed by name, so the home directory can move. A
    source in `recorded` may match nothing: its recorded plans are then simply gone."""
    plans = {os.path.basename(p): p for p in expand(home)}
    seen = set(plans.values())
    for src in sources:
        for p in expand(src, allow_empty=src in recorded):
            if p not in seen:
                seen.add(p)
                plans[p] = p
    return plans


def results(plans):
    """({key: record}, [(key, tool, why)])."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        futs = {k: pool.submit(classify, p) for k, p in plans.items()}
        got, errors = {}, []
        for k in sorted(futs):
            got[k], errs = futs[k].result()
            errors += [(k, tool, why) for tool, why in errs.items()]
        return got, errors


def load_expected(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise UsageError(f"no {EXPECTED} in the corpus: {path} (write it with --write-expected)")
    except (OSError, ValueError) as e:
        raise UsageError(f"unreadable {EXPECTED}: {path}: {e}")
    if (not isinstance(doc, dict) or doc.get("format") != FORMAT
            or not isinstance(doc.get("plans"), dict)
            or not isinstance(doc.get("sources"), list)):
        raise UsageError(f"malformed {EXPECTED}: {path}")
    return doc


def compare(expected, got):
    """(failures, notes). A home plan is keyed by its bare name and is frozen: any change
    to it fails, its content alone included. A live plan (an extra source, keyed by its
    path) is edited as it is worked, so an edited, new or gone live plan is a note; a
    classification that moved on a plan whose content is unchanged fails wherever the plan
    lives. A tool missing from `got` (its result was an ERROR) is not compared."""
    fails, notes = [], []
    for key in sorted(set(expected) | set(got)):
        frozen = os.sep not in key
        if key not in got:
            (fails if frozen else notes).append(
                f"{'MISSING' if frozen else 'NOTE'} {key}: recorded in {EXPECTED}, gone")
            continue
        if key not in expected:
            (fails if frozen else notes).append(
                f"{'NEW' if frozen else 'NOTE'} {key}: no record in {EXPECTED}")
            continue
        e, g = expected[key], got[key]
        same = e.get("sha256") == g["sha256"]
        why = "content unchanged" if same else "content changed"
        if frozen and not same:
            fails.append(f"CHANGED {key}: frozen plan edited (sha256 "
                         f"{str(e.get('sha256'))[:12]} -> {g['sha256'][:12]})")
        for tool in TOOLS:
            if tool in g and e.get(tool) != g[tool]:
                line = (f"{tool}: expected {json.dumps(e.get(tool))}, "
                        f"got {json.dumps(g[tool])} ({why})")
                if same or frozen:
                    fails.append(f"DIFF {key}: {line}")
                else:
                    notes.append(f"NOTE {key}: {line}")
    return fails, notes


def main(argv=None):
    ap = argparse.ArgumentParser(prog="corpus-regress", description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", action="append", required=True, metavar="DIR-OR-GLOB",
                    help="the first is the home directory holding expected.json; "
                         "any more are extra sources")
    ap.add_argument("--write-expected", action="store_true",
                    help="record the current classifications in <home>/expected.json")
    args = ap.parse_args(argv)
    home = os.path.abspath(args.corpus[0])
    extra = [os.path.abspath(s) for s in args.corpus[1:]]
    exp_path = os.path.join(home, EXPECTED)
    try:
        if not os.path.isdir(home):
            raise UsageError(f"not a directory: {home}")
        if args.write_expected:
            plans = plan_set(home, extra)
            got, errors = results(plans)
            if errors:
                for key, tool, why in errors:
                    print(f"ERROR {key}: {tool}: {why}", file=sys.stderr)
                raise UsageError(f"refusing to write {exp_path}: {len(errors)} tool "
                                 f"result(s) could not be read (above) — an unreadable "
                                 f"result is never a recorded expectation")
            doc = {"format": FORMAT, "written": datetime.date.today().isoformat(),
                   "sources": extra, "plans": got}
            with open(exp_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=1, sort_keys=True)
                fh.write("\n")
            print(f"corpus-regress: wrote {exp_path}: {len(plans)} plan(s) "
                  f"from {1 + len(extra)} source(s)")
            return 0
        doc = load_expected(exp_path)
        unrecorded = [s for s in extra if s not in doc["sources"]]
        if unrecorded:
            raise UsageError(f"source not in the record; re-record with --write-expected: "
                             + ", ".join(unrecorded))
        sources = doc["sources"]
        plans = plan_set(home, sources, recorded=set(sources))
    except UsageError as e:
        print(f"corpus-regress: {e}", file=sys.stderr)
        return 2
    got, errors = results(plans)
    diffs, notes = compare(doc["plans"], got)
    for key, tool, why in errors:
        print(f"ERROR {key}: {tool}: {why}")
    for line in diffs + notes:
        print(line)
    print(f"corpus-regress: {len(plans)} plan(s) from {1 + len(sources)} source(s) "
          f"compared with {EXPECTED} ({doc.get('written', 'undated')}): "
          f"{len(diffs)} difference(s), {len(notes)} note(s)"
          + (f", {len(errors)} error(s)" if errors else ""))
    return 1 if (diffs or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
