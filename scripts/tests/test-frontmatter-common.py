#!/usr/bin/env python3
"""Tests for scripts/_frontmatter_common.py — the shared scan primitives that
check-frontmatter-budget.py and build-capability-index.py both import.

Two jobs: unit-test the shared helpers, and — the reason this file exists — a
cross-tool agreement guard. The budget script and the index generator must never
disagree about which components are dispatch-only; this walks every REAL
component in the repo and asserts the shared predicate matches the committed
capability-index.json field. If a future edit reintroduces a second, divergent
predicate in either script, this fails. Stdlib only.
"""
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import _frontmatter_common as common  # noqa: E402
import _layout as layout  # noqa: E402

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def dmi(val):
    return f"---\nname: b\ndescription: d\ndisable-model-invocation: {val}\n---\n"


def unit_cases():
    check(common.frontmatter_block("---\nname: x\n---\n# b\n") == "name: x",
          "frontmatter_block returns the block")
    check(common.frontmatter_block("# no frontmatter\n") is None,
          "frontmatter_block -> None when absent")
    check(common.is_excluded("p/skills/x/tests/SKILL.md") is True,
          "tests/ path excluded")
    check(common.is_excluded("hosts/cursor/add/skills/hooks/SKILL.md") is True,
          "a non-Claude host layer is not a component of the Claude marketplace")
    check(common.is_excluded("hosts/opencode/add/commands/backlog.md") is True,
          "...on any non-Claude host")
    check(common.is_excluded("hosts/claude/add/commands/statusline.md") is False,
          "the Claude host layer is")
    check(common.is_excluded("p/skills/x/fixtures/a/SKILL.md") is True,
          "fixtures/ path excluded")
    check(common.is_excluded("p/skills/x/SKILL.md") is False,
          "normal component path not excluded")
    # Authored convention: true/false only, PyYAML-independent, quote-tolerant.
    for val, want in [("true", True), ("True", True), ("TRUE", True),
                      ("'true'", True), ('"true"', True),
                      ("false", False), ("yes", False), ("on", False),
                      ("no", False)]:
        check(common.disable_model_invocation(dmi(val)) is want,
              f"disable-model-invocation: {val} -> {want}")
    check(common.disable_model_invocation("# no fm\n") is False,
          "no frontmatter -> not dispatch-only")


def cross_tool_agreement_case():
    """The committed index's disable_model_invocation for every real component
    must equal the shared predicate applied to that file. Ties the generator's
    emitted flag to the one shared rule over live data."""
    index_path = os.path.join(REPO_ROOT, "capability-index.json")
    if not os.path.exists(index_path):
        check(False, "capability-index.json exists (run build-capability-index.py --write)")
        return
    index = json.load(open(index_path, encoding="utf-8"))
    mismatches = []
    for comp in index["components"]:
        fpath = os.path.join(REPO_ROOT, comp["path"])
        if not os.path.exists(fpath):
            mismatches.append(f"{comp['path']} (missing on disk)")
            continue
        text = open(fpath, encoding="utf-8").read()
        if common.disable_model_invocation(text) != comp["disable_model_invocation"]:
            mismatches.append(comp["path"])
    check(not mismatches,
          "index disable_model_invocation agrees with shared predicate for every component"
          + ("" if not mismatches else f" (mismatches: {mismatches[:5]})"))
    # Sanity: the walk actually covered the real component set (same scan rules).
    n_scanned = 0
    for _, pattern in common.PATTERNS:
        for p in layout.glob_components(REPO_ROOT, pattern):
            if not common.is_excluded(os.path.relpath(p, REPO_ROOT)):
                n_scanned += 1
    check(n_scanned == len(index["components"]),
          f"index covers every scanned component ({n_scanned} on disk == {len(index['components'])} indexed)")


if __name__ == "__main__":
    print("unit:")
    unit_cases()
    print("cross-tool agreement:")
    cross_tool_agreement_case()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
