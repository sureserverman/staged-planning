#!/usr/bin/env python3
"""Fixture tests for scripts/check-trunk-budget.py.

The budget file is a RATCHET: every trunk carries a ceiling it may not exceed,
seeded at the size measured when the entry was written. The regression mode it
exists to stop is silent re-growth: a trunk creeping back up after an extraction
with nothing reporting it.

The load-bearing cases are the ones proving the ratchet actually rejects: a
budget file that never fires is a stub. Stdlib only.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-trunk-budget.py")

spec = importlib.util.spec_from_file_location("budget", SCRIPT)
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def parse_cases():
    with tempfile.TemporaryDirectory() as root:
        bf = os.path.join(root, "b.txt")
        write(bf, "# comment\n\np/skills/s/SKILL.md 1000\n"
                  "q/skills/t/SKILL.md 2000  # trailing reason\n")
        got = budget.load_budgets(bf)
        check(got == {"p/skills/s/SKILL.md": 1000, "q/skills/t/SKILL.md": 2000},
              "budget file parses paths, sizes, comments")
        check(budget.load_budgets(os.path.join(root, "none.txt")) == {},
              "missing budget file parses to empty")

        # A duplicate path with a DIFFERENT ceiling must be loud. Last-write-
        # wins would let a bad merge that re-adds a trunk at a larger ceiling
        # loosen the ratchet with nothing reporting it.
        write(bf, "p/skills/s/SKILL.md 1000\np/skills/s/SKILL.md 9999\n")
        try:
            budget.load_budgets(bf)
            check(False, "duplicate ceiling raises")
        except budget.DuplicateBudget:
            check(True, "duplicate ceiling raises DuplicateBudget")
        # An identical repeat is harmless and must not raise
        write(bf, "p/skills/s/SKILL.md 1000\np/skills/s/SKILL.md 1000\n")
        try:
            budget.load_budgets(bf)
            check(True, "identical duplicate line does not raise")
        except budget.DuplicateBudget:
            check(False, "identical duplicate line does not raise")


def ratchet_cases():
    with tempfile.TemporaryDirectory() as root:
        skill = "p/skills/s/SKILL.md"
        write(os.path.join(root, skill), "x" * 500)
        bf = os.path.join(root, "b.txt")

        write(bf, f"{skill} 500\n")
        check(budget.main(["--root", root, "--budgets", bf]) == 0,
              "file exactly at its ceiling passes")

        # A ceiling sitting above a shrunk trunk is re-growth room, so a file
        # under its ceiling is not a pass. Under the default exact ratchet it
        # is STALE; slack is opt-in per run.
        write(bf, f"{skill} 600\n")
        check(budget.main(["--root", root, "--budgets", bf]) == 1,
              "file 100 B under its ceiling is STALE by default")
        check(budget.main(["--root", root, "--budgets", bf,
                           "--max-slack", "100"]) == 0,
              "--max-slack 100 tolerates exactly that much drift")
        check(budget.main(["--root", root, "--budgets", bf,
                           "--max-slack", "99"]) == 1,
              "one byte more drift than --max-slack allows FAILS")

        # THE case: growth past the ceiling must fail
        write(bf, f"{skill} 499\n")
        check(budget.main(["--root", root, "--budgets", bf]) == 1,
              "file one byte over its ceiling FAILS")

        write(os.path.join(root, skill), "x" * 5000)
        write(bf, f"{skill} 500\n")
        check(budget.main(["--root", root, "--budgets", bf]) == 1,
              "10x growth FAILS")


def missing_file_cases():
    with tempfile.TemporaryDirectory() as root:
        bf = os.path.join(root, "b.txt")
        write(bf, "p/skills/gone/SKILL.md 500\n")
        rc = budget.main(["--root", root, "--budgets", bf])
        check(rc == 1, "a budgeted file that does not exist FAILS")
        # An entry silently skipped would let a deleted trunk read as compliant.


def unbudgeted_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/SKILL.md"), "x" * 20000)
        bf = os.path.join(root, "b.txt")
        write(bf, "")
        rc = budget.main(["--root", root, "--budgets", bf, "--min-size", "10000"])
        check(rc == 1, "a trunk over --min-size with no budget entry FAILS")
        # Otherwise the ratchet is opt-in, and a new fat trunk opts out by default.

        write(os.path.join(root, "p/skills/small/SKILL.md"), "x" * 100)
        write(bf, "p/skills/s/SKILL.md 20000\n")
        rc = budget.main(["--root", root, "--budgets", bf, "--min-size", "10000"])
        check(rc == 0, "a trunk under --min-size needs no entry")


def stale_ceiling_cases():
    """A ceiling left above a shrunk trunk is silent re-growth room.

    The ratchet's own header says ceilings are lowered by hand when an
    extraction lands, "which is what makes the reduction durable rather than a
    number that drifts back up" -- and a hand-lowering that nothing verifies is
    one that drifts.
    """
    with tempfile.TemporaryDirectory() as root:
        skill = "p/skills/s/SKILL.md"
        write(os.path.join(root, skill), "x" * 500)
        bf = os.path.join(root, "b.txt")

        write(bf, f"{skill} 500\n")
        check(budget.main(["--root", root, "--budgets", bf]) == 0,
              "a ceiling equal to the measured size is not stale")

        # The shape that matters: the trunk shrinks, the budget file does not move.
        write(os.path.join(root, skill), "x" * 300)
        check(budget.main(["--root", root, "--budgets", bf]) == 1,
              "a trunk that shrank without its ceiling being lowered FAILS")

        write(bf, f"{skill} 300\n")
        check(budget.main(["--root", root, "--budgets", bf]) == 0,
              "lowering the ceiling to the new size clears it")

        # Over-ceiling must still outrank stale: growth is the primary defect.
        write(os.path.join(root, skill), "x" * 900)
        check(budget.main(["--root", root, "--budgets", bf]) == 1,
              "growth past the ceiling still FAILS with the stale check present")


def unmeasured_headroom_cases():
    """The floor and the stale ceiling are one defect: room nobody measures."""
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/SKILL.md"), "x" * 500)
        write(os.path.join(root, "p/skills/small/SKILL.md"), "x" * 100)
        bf = os.path.join(root, "b.txt")
        write(bf, "p/skills/s/SKILL.md 500\n")
        import io as _io, json as _json, contextlib as _ctx
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            budget.main(["--root", root, "--budgets", bf,
                         "--min-size", "1000", "--json"])
        data = _json.loads(buf.getvalue())
        # small/ is 100 B under a 1000 B floor -> 900 B of room nothing ratchets
        check(data["unmeasured_headroom"] == 900,
              f"sub-floor headroom is counted and reported (got {data['unmeasured_headroom']})")
        check(data["stale"] == [], "no stale ceilings when every ceiling is exact")


def report_cases():
    with tempfile.TemporaryDirectory() as root:
        skill = "p/skills/s/SKILL.md"
        write(os.path.join(root, skill), "x" * 400)
        bf = os.path.join(root, "b.txt")
        write(bf, f"{skill} 1000\n")
        rows = budget.measure(root, budget.load_budgets(bf), 10000)
        check(len(rows) == 1, "measure returns one row per budgeted trunk")
        r = rows[0]
        check(r["size"] == 400 and r["budget"] == 1000 and r["headroom"] == 600,
              "row carries size, budget and headroom")
        check(budget.main(["--root", root, "--budgets", bf,
                           "--max-slack", "600"]) == 0,
              "reporting run exits 0 when compliant")


def empty_sweep_cases():
    with tempfile.TemporaryDirectory() as root:
        bf = os.path.join(root, "b.txt")
        write(bf, "")
        rc = budget.main(["--root", root, "--budgets", bf])
        check(rc == 0, "empty tree exits 0")
        check(budget.measure(root, {}, 10000) == [],
              "empty tree measures nothing (count reported, not implied)")


if __name__ == "__main__":
    print("budget file parsing:")
    parse_cases()
    print("ratchet:")
    ratchet_cases()
    print("missing budgeted file:")
    missing_file_cases()
    print("unbudgeted trunks:")
    unbudgeted_cases()
    print("stale ceilings:")
    stale_ceiling_cases()
    print("unmeasured headroom:")
    unmeasured_headroom_cases()
    print("reporting:")
    report_cases()
    print("empty sweep:")
    empty_sweep_cases()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
