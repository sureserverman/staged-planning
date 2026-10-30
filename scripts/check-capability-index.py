#!/usr/bin/env python3
"""capability-index.json is what build-capability-index.py produces from the tree today.

The index is generated and committed (doc guards resolve through it, never a tree walk
of their own). A component renamed, added, or re-described without regenerating it
leaves every consumer resolving against yesterday's tree, and nothing fails: the
generator is excluded from the validator set because it writes rather than checks. A CI
job running `build-capability-index.py --write` and then `git diff --exit-code` would
catch it only where CI runs; this is that check as a validator, so the canonical runner
runs it wherever it runs.

It also holds each mod's declared command list (`registered-commands.json`, which the
index reads) to the `$.command.register` calls in the mod's sources: a command the mod
registers without declaring it would be missing from the index's
`registered_commands`, and nothing else would notice.

Read-only. Exit 0 when the committed index matches a fresh build and every mod's
registrations match its declared list, 1 otherwise.
"""
import argparse
import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "build_capability_index", os.path.join(REPO_ROOT, "scripts", "build-capability-index.py"))
bci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bci)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=REPO_ROOT, help="repo root to check")
    root = ap.parse_args(argv).root
    index_path = os.path.join(root, "capability-index.json")
    drift = bci.registration_drift(root)
    for problem in drift:
        print(f"FAIL: {problem}")
    index = bci.build(root)
    fresh, n = bci.render(index), len(index["components"])
    try:
        with open(index_path, encoding="utf-8") as fh:
            committed = fh.read()
    except OSError as exc:
        print(f"FAIL: cannot read {index_path} ({exc}) — run "
              "`python3 scripts/build-capability-index.py --write`")
        return 1
    if fresh != committed:
        print(f"FAIL: capability-index.json is stale against the tree ({n} components "
              "built) — run `python3 scripts/build-capability-index.py --write`")
        return 1
    if drift:
        return 1
    print(f"capability-index.json matches a fresh build ({n} components).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
