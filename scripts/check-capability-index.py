#!/usr/bin/env python3
"""capability-index.json is what build-capability-index.py produces from the tree today.

The index is generated and committed (doc guards resolve through it, never a tree walk
of their own). A component renamed, added, or re-described without regenerating it
leaves every consumer resolving against yesterday's tree, and nothing fails: the
generator is excluded from the validator set because it writes rather than checks. A CI
job running `build-capability-index.py --write` and then `git diff --exit-code` would
catch it only where CI runs; this is that check as a validator, so the canonical runner
runs it wherever it runs.

Read-only. Exit 0 when the committed index matches a fresh build, 1 otherwise.
"""
import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(REPO_ROOT, "capability-index.json")

_spec = importlib.util.spec_from_file_location(
    "build_capability_index", os.path.join(REPO_ROOT, "scripts", "build-capability-index.py"))
bci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bci)


def main():
    index = bci.build(REPO_ROOT)
    fresh, n = bci.render(index), len(index["components"])
    try:
        with open(INDEX_PATH, encoding="utf-8") as fh:
            committed = fh.read()
    except OSError as exc:
        print(f"FAIL: cannot read {INDEX_PATH} ({exc}) — run "
              "`python3 scripts/build-capability-index.py --write`")
        return 1
    if fresh != committed:
        print(f"FAIL: capability-index.json is stale against the tree ({n} components "
              "built) — run `python3 scripts/build-capability-index.py --write`")
        return 1
    print(f"capability-index.json matches a fresh build ({n} components).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
