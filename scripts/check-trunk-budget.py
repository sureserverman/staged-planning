#!/usr/bin/env python3
"""A ratchet on skill trunk sizes: no SKILL.md may exceed its recorded ceiling.

A skill's *body* is loaded per invocation, not per session, so every byte in a
trunk is paid every time the skill fires, in every project with the plugin
enabled. Trunks therefore grow the way costs grow when nobody is measuring.
Measured on one owner's plugin (undated): a trunk gained 34% in six days.

`scripts/trunk-budget.txt` records one `<repo-relative-path> <max-bytes>` line
per trunk. The ceiling is seeded at the size measured when the entry is written,
so the ratchet's day-one value does not depend on any extraction happening: a
trunk may shrink freely and may not grow at all. Ceilings are lowered by hand
when an extraction lands, which is what makes the reduction durable rather than
a number that drifts back up.

Three failure modes this deliberately treats as errors rather than skips:

  - A budgeted file that does not exist. Skipping it would let a deleted or
    renamed trunk read as compliant forever.
  - A trunk over `--min-size` with no budget entry. Without this the ratchet is
    opt-in, and a new fat trunk opts out of it by simply never being listed.
  - A STALE ceiling: a trunk that has shrunk more than `--max-slack` below its
    recorded ceiling. The paragraph above says ceilings are lowered by
    hand when an extraction lands, "which is what makes the reduction durable
    rather than a number that drifts back up" -- but unless something checks
    that the hand-lowering happens, the gap between a shrunk trunk and its
    unchanged ceiling is silent room to grow straight back.

The floor and the stale ceiling are the same defect wearing two hats, which is
why one fix answers both: each is room to grow that the ratchet does not
measure. A trunk under `--min-size` carries implicit headroom up to the floor;
a stale ceiling carries it explicitly. So the summary states the total
unmeasured headroom rather than implying the ratchet covers everything -- a
count of budgeted trunks says nothing about what is NOT budgeted.

Read-only: never writes to the repo. Exit 0 when every trunk is within its
ceiling and no ceiling is stale, 1 otherwise.
"""
import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGETS_PATH = os.path.join(REPO_ROOT, "scripts", "trunk-budget.txt")
DEFAULT_MIN_SIZE = 10000

# Shared with check-frontmatter-budget.py and check-extraction-integrity.py so
# the rules that must agree are defined once, per _frontmatter_common's own
# docstring. Bootstrap this script's dir so the import resolves when run
# directly and when loaded via importlib in the tests.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _frontmatter_common import EXCLUDE_SEGMENTS, load_lines  # noqa: E402
from _layout import GENERATED  # noqa: E402

EXCLUDE_PARTS = EXCLUDE_SEGMENTS


class DuplicateBudget(ValueError):
    """Two ceilings for one path — the file no longer says what it means."""


def load_budgets(path=BUDGETS_PATH):
    """{repo-relative path: max bytes} from the budget file.

    A duplicate path is an error, not a last-write-wins overwrite. A bad merge
    that re-adds a trunk with a larger ceiling would otherwise loosen the
    ratchet silently, which is the one failure this file exists to make loud.
    """
    budgets = {}
    for entry in load_lines(path):
        parts = entry.split()
        if len(parts) != 2:
            continue
        try:
            size = int(parts[1])
        except ValueError:
            continue
        if parts[0] in budgets and budgets[parts[0]] != size:
            raise DuplicateBudget(
                f"{path}: {parts[0]} has two ceilings "
                f"({budgets[parts[0]]} and {size})")
        budgets[parts[0]] = size
    return budgets


def discover_trunks(root):
    """Every `*/skills/*/SKILL.md` in the tree, repo-relative and sorted."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", "__pycache__")
                       # Generated copies of core/ + hosts/ (`_layout.GENERATED`):
                       # their trunks are budgeted at their source.
                       and not (dirpath == root and d in GENERATED)]
        if "SKILL.md" not in filenames:
            continue
        rel = os.path.relpath(os.path.join(dirpath, "SKILL.md"), root)
        if any(p in f"/{rel}" for p in EXCLUDE_PARTS):
            continue
        if "/skills/" in f"/{rel}":
            out.append(rel)
    return sorted(out)


def measure(root, budgets, min_size):
    """One row per budgeted trunk: size, budget, headroom, over."""
    rows = []
    for rel, cap in sorted(budgets.items()):
        full = os.path.join(root, rel)
        size = os.path.getsize(full) if os.path.exists(full) else None
        rows.append({
            "path": rel,
            "size": size,
            "budget": cap,
            "headroom": None if size is None else cap - size,
            "over": size is None or size > cap,
            "missing": size is None,
        })
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-trunk-budget")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--budgets", default=None)
    ap.add_argument("--min-size", type=int, default=DEFAULT_MIN_SIZE,
                    help="trunks at or above this size must carry a budget entry")
    ap.add_argument("--max-slack", type=int, default=0, metavar="B",
                    help="a budgeted trunk more than B bytes under its ceiling is "
                         "STALE: the ceiling was not lowered when the trunk shrank "
                         "(default 0 -- the ratchet is exact by design)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    budgets_path = args.budgets or os.path.join(args.root, "scripts",
                                                "trunk-budget.txt")
    budgets = load_budgets(budgets_path)
    rows = measure(args.root, budgets, args.min_size)

    # A big trunk with no entry is a gap in the ratchet, not a pass.
    unbudgeted = []
    for rel in discover_trunks(args.root):
        if rel in budgets:
            continue
        if os.path.getsize(os.path.join(args.root, rel)) >= args.min_size:
            unbudgeted.append(rel)

    over = [r for r in rows if r["over"]]
    # A ceiling left above a shrunk trunk is re-growth room nothing reports.
    stale = [r for r in rows
             if not r["missing"] and r["headroom"] > args.max_slack]

    # What the ratchet is NOT measuring, from both sources.
    slack_bytes = sum(r["headroom"] for r in stale)
    floor_bytes = 0
    for rel in discover_trunks(args.root):
        if rel in budgets:
            continue
        size = os.path.getsize(os.path.join(args.root, rel))
        if size < args.min_size:
            floor_bytes += args.min_size - size

    if args.json:
        print(json.dumps({"rows": rows, "unbudgeted": unbudgeted,
                          "stale": [r["path"] for r in stale],
                          "unmeasured_headroom": slack_bytes + floor_bytes},
                         indent=2))
    else:
        # honest-gates: state the population, so an empty sweep cannot read as
        # a pass over something.
        print(f"{len(rows)} budgeted trunk(s); {len(over)} over ceiling, "
              f"{len(stale)} stale ceiling(s), "
              f"{len(unbudgeted)} unbudgeted over {args.min_size} B.")
        print(f"  unmeasured headroom: {slack_bytes + floor_bytes} B "
              f"({slack_bytes} B stale ceilings + {floor_bytes} B under the "
              f"{args.min_size} B floor).")
        for r in sorted(rows, key=lambda x: -(x["size"] or 0)):
            if r["missing"]:
                print(f"  MISSING  {r['path']}  (budgeted {r['budget']} B)")
                continue
            flag = "OVER  " if r["over"] else "ok    "
            print(f"  {flag}   {r['size']:>7} / {r['budget']:>7} B  "
                  f"({r['headroom']:+d})  {r['path']}")
        for rel in unbudgeted:
            print(f"  NO-BUDGET  {rel}  "
                  f"({os.path.getsize(os.path.join(args.root, rel))} B)")

    if stale:
        print("\nSTALE ceiling(s) -- the trunk shrank and the ceiling did not. "
              "Paste these lines into scripts/trunk-budget.txt:", file=sys.stderr)
        for r in stale:
            print(f"  {r['path']} {r['size']}"
                  f"    # was {r['budget']} ({r['headroom']:+d})", file=sys.stderr)

    return 1 if (over or unbudgeted or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
