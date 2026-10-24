#!/usr/bin/env python3
"""Tolerant structural linter for a *local* Claude Design handoff pack.

Locates the pack root under a given path, confirms at least one recognizable
section (tokens / components / layout / assets), and prints a normalized manifest
as JSON. The pack format is proprietary and moving, so this checks *shape*, not a
frozen schema: it fails only when nothing recognizable can be found at all.

Usage:
    validate-handoff-pack.py <path>

Exit 0 = a usable pack was found (manifest printed to stdout).
Exit 1 = no recognizable pack under <path> (reason printed to stderr).
Exit 2 = bad invocation.

No third-party deps; stdlib only. The *live* (DesignSync) input path is not linted
here — that goes through the DesignSync tool's own read methods.
See ../references/handoff-pack-format.md for the contract.
"""

import json
import os
import sys

MANIFEST_NAMES = ("handoff.json", "manifest.json", "design.json", "_ds_manifest.json")
TOKEN_NAMES = ("tokens.json", "tokens.js", "tokens.css", "tokens.yaml", "tokens.yml")
COMPONENT_DIRS = ("components", "component")
LAYOUT_DIRS = ("screens", "layouts", "layout", "frames")
ASSET_DIRS = ("assets", "asset", "media")
# basenames that strongly signal a pack root — preferred over a generic match
HANDOFF_DIR_NAMES = ("handoff", "design-handoff", ".design")
MAX_SEARCH_DEPTH = 4  # how deep below <path> we'll hunt for a pack root


def _scan_dir(d):
    """Return (sections, has_manifest) for directory d.

    `sections` counts each section (0 = absent) or None if the dir carries no
    gradeable section at all. `has_manifest` flags a recognized manifest file.
    All section values are non-negative ints so the emitted JSON is uniform.
    """
    try:
        entries = os.listdir(d)
    except OSError:
        return None, False
    lower = {e.lower(): e for e in entries}

    sections = {"tokens": 0, "components": 0, "layout": 0, "assets": 0}

    # tokens: a tokens.* file, or a manifest carrying a "tokens" key
    if any(t in lower for t in TOKEN_NAMES):
        sections["tokens"] = 1

    has_manifest = False
    for name in MANIFEST_NAMES:
        if name in lower:
            has_manifest = True
            try:
                with open(os.path.join(d, lower[name]), encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    if "tokens" in data:
                        sections["tokens"] = 1
                    comp = data.get("components")
                    if isinstance(comp, (list, dict)):
                        sections["components"] = max(sections["components"], len(comp))
                    lay = (data.get("screens") or data.get("layout")
                           or data.get("layouts") or data.get("frames"))
                    if isinstance(lay, (list, dict)):
                        sections["layout"] = max(sections["layout"], len(lay))
            except (OSError, ValueError):
                pass  # tolerant: a malformed manifest doesn't sink an otherwise-good pack

    def _count_dir(names):
        for n in names:
            if n in lower and os.path.isdir(os.path.join(d, lower[n])):
                try:
                    return len([
                        f for f in os.listdir(os.path.join(d, lower[n]))
                        if not f.startswith(".")
                    ])
                except OSError:
                    return 0
        return 0

    sections["components"] = max(sections["components"], _count_dir(COMPONENT_DIRS))
    sections["layout"] = max(sections["layout"], _count_dir(LAYOUT_DIRS))
    sections["assets"] = _count_dir(ASSET_DIRS)

    gradeable = sections["tokens"] or sections["components"] or sections["layout"]
    return (sections if gradeable else None), has_manifest


def find_pack_root(start):
    """Find the best pack-root directory under `start`.

    Collects every gradeable directory, then ranks by the doc's priority order:
    a handoff-named directory, then one carrying a manifest, then the shallowest.
    This keeps a stray `src/components/` from masking a real `handoff/` dir.
    """
    start = os.path.abspath(start)
    if not os.path.isdir(start):
        return None, None
    start_depth = start.rstrip(os.sep).count(os.sep)
    candidates = []  # (name_rank, manifest_rank, depth, dirpath, sections)
    for dirpath, dirs, _files in os.walk(start):
        depth = dirpath.rstrip(os.sep).count(os.sep) - start_depth
        if depth >= MAX_SEARCH_DEPTH:
            dirs[:] = []  # don't descend past the cap (current dir still scanned)
        if os.path.basename(dirpath) == ".git":
            dirs[:] = []
            continue
        sections, has_manifest = _scan_dir(dirpath)
        if sections is None:
            continue
        name_rank = 0 if os.path.basename(dirpath).lower() in HANDOFF_DIR_NAMES else 1
        candidates.append((name_rank, 0 if has_manifest else 1, depth, dirpath, sections))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _, _, _, dirpath, sections = candidates[0]
    return dirpath, sections


def main(argv):
    if len(argv) != 2:
        print("usage: validate-handoff-pack.py <path>", file=sys.stderr)
        return 2
    target = argv[1]
    if not os.path.isdir(target):
        print(f"path is not a directory: {os.path.abspath(target)}", file=sys.stderr)
        return 2
    root, sections = find_pack_root(target)
    if root is None:
        print(
            f"no recognizable handoff pack under {os.path.abspath(target)} "
            "(need at least one of: tokens, components, or layout/screens)",
            file=sys.stderr,
        )
        return 1
    manifest = {
        "source": "local",
        "root": root,
        "sections": sections,
        "gradeable": [
            k for k, v in (
                ("tokens", sections["tokens"]),
                ("components", sections["components"]),
                ("layout", sections["layout"]),
            ) if v
        ],
    }
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
