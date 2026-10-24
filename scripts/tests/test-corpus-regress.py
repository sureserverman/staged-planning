#!/usr/bin/env python3
"""Fixture tests for scripts/corpus-regress.py.

A regression check that only ever passes is indistinguishable from one that reads
nothing. So each run below builds a throwaway corpus of invented plans, records it with
--write-expected, and then proves both directions: an unchanged corpus exits 0, and each
kind of drift — a plan whose classification changed, a plan gone, a plan added, a
tampered expected entry — exits 1 and names the plan. A missing directory, a missing or
malformed expected.json and a source that matches nothing exit 2, because a run that
read nothing must never look like a pass.

Every value is invented (example-app, /records/plans/…). Stdlib only.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "corpus-regress.py")

FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def run(*args):
    r = subprocess.run([sys.executable, SCRIPT, *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


CLEAN = """# Project Plan: example-app widgets
Date: 2026-01-05

## Stage 1: Widgets

### Task 1.1: Add the widget
- **Status:** [ ]
- **Depends on:** none
- **Dispatch:** NO
- **Test:** `python3 tests/test_widget.py` exits 0

### Stage 1 Gate
- [ ] **(goal)** `! grep -rl 'TODO-widget' src/ docs/` prints nothing — every file
- [ ] `python3 tests/test_widget.py` exits 0
"""

SHAPED = """# Project Plan: example-app records
Date: 2026-01-06

## Stage 1: Records

### Task 1.1: Move the records
- **Status:** [ ]
- **Depends on:** none
- **Dispatch:** NO
- **Test:** `python3 tests/test_records.py` exits 0

### Stage 1 Gate
- [ ] the setup page stops saying the records sit under /records/plans/
- [ ] `python3 tests/test_records.py` exits 0
"""

if not os.path.isfile(SCRIPT):
    print(f"FAILED — script missing: {SCRIPT}")
    sys.exit(1)

with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    home = root / "corpus"
    home.mkdir()
    (home / "2026-01-05-widgets-plan.md").write_text(CLEAN, encoding="utf-8")
    (home / "2026-01-06-records-plan.md").write_text(SHAPED, encoding="utf-8")
    live = root / "live" / "example-app" / "plans"
    live.mkdir(parents=True)
    (live / "2026-01-07-live-plan.md").write_text(CLEAN.replace("widgets", "live"),
                                                  encoding="utf-8")
    (live / "2026-01-09-other-plan.md").write_text(SHAPED.replace("records", "other"),
                                                   encoding="utf-8")
    live_glob = str(root / "live" / "*" / "plans" / "*.md")

    print("group 1 — usage errors exit 2: a run that read nothing is not a pass")
    rc, out = run("--corpus", home)
    check(rc == 2 and "expected.json" in out, f"no expected.json exits 2 naming it (rc {rc})")
    rc, out = run("--corpus", root / "absent")
    check(rc == 2, f"a missing corpus directory exits 2 (rc {rc})")
    rc, out = run("--corpus", home, "--corpus", str(root / "none" / "*.md"),
                  "--write-expected")
    check(rc == 2 and "matched no plan" in out,
          f"an extra source matching nothing exits 2, even when writing (rc {rc})")
    check(not (home / "expected.json").exists(), "and writes nothing")

    print("group 2 — --write-expected records every plan, the extra sources included")
    rc, out = run("--corpus", home, "--corpus", live_glob, "--write-expected")
    check(rc == 0, f"--write-expected exits 0 (rc {rc}; {out.strip()[-200:]})")
    exp = json.loads((home / "expected.json").read_text(encoding="utf-8"))
    check(sorted(exp["plans"]) == sorted(["2026-01-05-widgets-plan.md",
                                          "2026-01-06-records-plan.md",
                                          str(live / "2026-01-07-live-plan.md"),
                                          str(live / "2026-01-09-other-plan.md")]),
          f"home plans keyed by name, extra plans by path ({sorted(exp['plans'])})")
    check(exp["sources"] == [live_glob], "the extra source is recorded for later runs")
    rec = exp["plans"]["2026-01-06-records-plan.md"]
    check(set(rec) >= {"sha256", "validate-gate-checks", "validate-dispatch",
                       "plan-flip-audit"},
          f"each plan records all three tools ({sorted(rec)})")
    check(rec["validate-gate-checks"]["rc"] == 1
          and rec["validate-gate-checks"]["counts"].get("instance-shaped") == 1,
          f"the gate classification is recorded, not just an exit code "
          f"({rec['validate-gate-checks']})")
    check(exp["plans"]["2026-01-05-widgets-plan.md"]["validate-gate-checks"]["rc"] == 0,
          "the clean plan is recorded as clean")

    print("group 3 — an unchanged corpus matches; the recorded sources are re-read")
    rc, out = run("--corpus", home)
    check(rc == 0, f"a match exits 0 (rc {rc}; {out.strip()[-200:]})")
    check("4 plan(s)" in out, f"the run reports how many plans it compared ({out.strip()[-120:]})")

    print("group 4 — drift in the frozen home plans, or of a classifier, exits 1 and names the plan")
    p = home / "2026-01-05-widgets-plan.md"
    p.write_text(CLEAN.replace("- [ ] `python3 tests/test_widget.py` exits 0",
                               "- [ ] the widget page in README.md reads well"),
                 encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 1 and "2026-01-05-widgets-plan.md" in out and "validate-gate-checks" in out,
          f"a changed plan exits 1, naming the plan and the tool (rc {rc})")
    check("content changed" in out, "and says the plan's content changed")
    p.write_text(CLEAN, encoding="utf-8")
    check(run("--corpus", home)[0] == 0, "restored, the corpus matches again")

    # A live source is edited as its plans are worked: an edited, new or gone live plan is
    # reported but is not a failure. A classification that moved on an UNCHANGED plan is.
    lp = live / "2026-01-07-live-plan.md"
    live_text = lp.read_text(encoding="utf-8")
    lp.write_text(SHAPED, encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 0 and "NOTE" in out and "2026-01-07-live-plan.md" in out
          and "content changed" in out,
          f"an edited plan in a live source is a NOTE, exit 0 (rc {rc}; {out.strip()[-160:]})")
    lp.unlink()
    rc, out = run("--corpus", home)
    check(rc == 0 and "NOTE" in out and "gone" in out and "2026-01-07-live-plan.md" in out,
          f"a recorded live plan that is gone is a NOTE, exit 0 (rc {rc})")
    lp.write_text(live_text, encoding="utf-8")
    newlive = live / "2026-01-09-newlive-plan.md"
    newlive.write_text(CLEAN, encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 0 and "NOTE" in out and "no record" in out and newlive.name in out,
          f"a new plan in a live source is a NOTE, exit 0 (rc {rc})")
    newlive.unlink()
    raw0 = (home / "expected.json").read_text(encoding="utf-8")
    t0 = json.loads(raw0)
    lkey = [k for k in t0["plans"] if k.endswith("2026-01-07-live-plan.md")][0]
    t0["plans"][lkey]["validate-gate-checks"]["rc"] = 7
    (home / "expected.json").write_text(json.dumps(t0), encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 1 and "DIFF" in out and "content unchanged" in out,
          f"a moved classification on an unchanged live plan exits 1 (rc {rc})")
    (home / "expected.json").write_text(raw0, encoding="utf-8")
    hp = home / "2026-01-06-records-plan.md"
    htext = hp.read_text(encoding="utf-8")
    hp.unlink()
    rc, out = run("--corpus", home)
    check(rc == 1 and "MISSING" in out and hp.name in out,
          f"a frozen home plan that is gone exits 1 as MISSING (rc {rc})")
    hp.write_text(htext, encoding="utf-8")

    extra = home / "2026-01-08-extra-plan.md"
    extra.write_text(CLEAN, encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 1 and "NEW" in out and extra.name in out,
          f"a plan with no expected entry exits 1 as NEW (rc {rc})")
    extra.unlink()

    raw = (home / "expected.json").read_text(encoding="utf-8")
    t = json.loads(raw)
    t["plans"]["2026-01-06-records-plan.md"]["validate-dispatch"]["rc"] = 1
    (home / "expected.json").write_text(json.dumps(t), encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 1 and "validate-dispatch" in out and "content unchanged" in out,
          f"a difference on an unchanged plan exits 1 and says the classifier moved (rc {rc})")
    (home / "expected.json").write_text("{not json", encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 2, f"a malformed expected.json exits 2 (rc {rc})")
    (home / "expected.json").write_text(raw, encoding="utf-8")
    check(run("--corpus", home)[0] == 0, "restored, the corpus matches again")

    print("group 5 — a frozen plan whose content changed fails even when every class is the same")
    hp = home / "2026-01-05-widgets-plan.md"
    hp.write_text(CLEAN + "\nA closing remark on the widgets.\n", encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 1 and "DIFF" not in out and "CHANGED 2026-01-05-widgets-plan.md" in out
          and "frozen plan edited" in out,
          f"a frozen plan edited without a classification change exits 1 as CHANGED "
          f"(rc {rc}; {out.strip()[-200:]})")
    hp.write_text(CLEAN, encoding="utf-8")
    lp.write_text(live_text + "\nA closing remark on the live plan.\n", encoding="utf-8")
    rc, out = run("--corpus", home)
    check(rc == 0 and "CHANGED" not in out and "DIFF" not in out,
          f"a live plan edited without a classification change stays exit 0 (rc {rc})")
    lp.write_text(live_text, encoding="utf-8")

    print("group 6 — a tool result that cannot be read is an error, never a record")
    def script_copy(name, stub=None):
        """A copy of the script under <root>/<name>/scripts/, so its tool paths resolve
        under <root>/<name>/ — nowhere, or to stubs that print `stub`."""
        base = root / name
        (base / "scripts").mkdir(parents=True)
        dst = base / "scripts" / "corpus-regress.py"
        dst.write_text(pathlib.Path(SCRIPT).read_text(encoding="utf-8"), encoding="utf-8")
        if stub is not None:
            for rel in ("core/skills/planning-projects/scripts/validate-gate-checks.py",
                        "core/skills/planning-projects/scripts/validate-dispatch.py",
                        "core/skills/executing-plans/scripts/plan-flip-audit.py"):
                t = base / rel
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text(f"print({stub!r})\n", encoding="utf-8")
        return dst

    def run_copy(script, *args):
        r = subprocess.run([sys.executable, str(script), *map(str, args)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    raw_home = (home / "expected.json").read_text(encoding="utf-8")
    for label, script in (("tool paths that point nowhere", script_copy("nowhere")),
                          ("stub tools that print garbage",
                           script_copy("stub", stub="garbage, not a result"))):
        rc, out = run_copy(script, "--corpus", home, "--write-expected")
        check(rc == 2 and "2026-01-05-widgets-plan.md" in out
              and all(t in out for t in ("validate-gate-checks", "validate-dispatch",
                                         "plan-flip-audit")),
              f"{label}: --write-expected refuses with exit 2, naming the plan and every "
              f"tool (rc {rc}; {out.strip()[-200:]})")
        check((home / "expected.json").read_text(encoding="utf-8") == raw_home,
              f"{label}: and writes nothing")
        (home / "expected.json").write_text(raw_home, encoding="utf-8")
        rc, out = run_copy(script, "--corpus", home)
        check(rc == 1 and "ERROR 2026-01-05-widgets-plan.md: validate-gate-checks: " in out
              and "ERROR 2026-01-05-widgets-plan.md: validate-dispatch: " in out
              and "ERROR 2026-01-05-widgets-plan.md: plan-flip-audit: " in out
              and "DIFF" not in out,
              f"{label}: a compare run exits 1 with ERROR per plan and tool, not DIFF "
              f"(rc {rc}; {out.strip()[-200:]})")
        last = out.strip().splitlines()[-1] if out.strip() else ""
        check(re.search(r"0 difference\(s\), 0 note\(s\), 12 error\(s\)$", last) is not None,
              f"{label}: the summary counts the errors on their own ({last[-90:]})")

    # A plan with no gate check at all is a real outcome (validate-gate-checks exits 2 and
    # says so), not an unreadable result: it records and matches.
    home2 = root / "corpus-nogate"
    home2.mkdir()
    (home2 / "2026-01-05-widgets-plan.md").write_text(CLEAN, encoding="utf-8")
    (home2 / "NOTES.md").write_text("# Notes\n\nNo plan here, no gate.\n", encoding="utf-8")
    rc, out = run("--corpus", home2, "--write-expected")
    check(rc == 0, f"a file with no gate check records (rc {rc}; {out.strip()[-160:]})")
    rc, out = run("--corpus", home2)
    check(rc == 0, f"and matches (rc {rc}; {out.strip()[-160:]})")

    print("group 7 — sources: unrecorded ones refuse; a recorded one emptied is a NOTE")
    other = root / "other" / "plans"
    other.mkdir(parents=True)
    (other / "2026-01-10-other-plan.md").write_text(CLEAN, encoding="utf-8")
    rc, out = run("--corpus", home, "--corpus", other)
    check(rc == 2 and "not in the record" in out and "re-record with --write-expected" in out,
          f"a CLI source not in expected.json exits 2 (rc {rc}; {out.strip()[-160:]})")
    rc, out = run("--corpus", home, "--corpus", str(root / "none" / "*.md"))
    check(rc == 2, f"an unrecorded empty CLI source exits 2 (rc {rc})")
    rc, out = run("--corpus", home, "--corpus", live_glob)
    check(rc == 0, f"a recorded source repeated on the CLI is fine (rc {rc}; {out.strip()[-160:]})")
    stash = root / "stash"
    stash.mkdir()
    for f in sorted(live.glob("*.md")):
        f.rename(stash / f.name)
    rc, out = run("--corpus", home)
    check(rc == 0 and out.count("NOTE") == 2 and "gone" in out
          and "2026-01-07-live-plan.md" in out and "2026-01-09-other-plan.md" in out,
          f"a recorded live source now empty: its plans are NOTE gone, exit 0 "
          f"(rc {rc}; {out.strip()[-200:]})")
    for f in sorted(stash.glob("*.md")):
        f.rename(live / f.name)
    for f in sorted(home.glob("*.md")):
        f.rename(stash / f.name)
    rc, out = run("--corpus", home)
    check(rc == 2 and "matched no plan" in out, f"an empty home exits 2 (rc {rc})")
    for f in sorted(stash.glob("*.md")):
        f.rename(home / f.name)

    print("group 8 — the summary counts differences and notes apart")
    lp.write_text(SHAPED, encoding="utf-8")
    rc, out = run("--corpus", home)
    last = out.strip().splitlines()[-1]
    check(rc == 0 and re.search(r": 0 difference\(s\), 1 note\(s\)$", last) is not None,
          f"a NOTE-only run reads '0 difference(s), 1 note(s)' ({last[-90:]})")
    lp.write_text(live_text, encoding="utf-8")
    check(run("--corpus", home)[0] == 0, "restored, the corpus matches again")

print()
if FAILURES:
    print(f"FAILED — {len(FAILURES)} check(s):")
    for f in FAILURES:
        print(f"  {f}")
    sys.exit(1)
print("OK — corpus-regress.py matches an unchanged corpus, names every drift, and refuses "
      "a run that read nothing")
