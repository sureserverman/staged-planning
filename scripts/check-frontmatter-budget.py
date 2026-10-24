#!/usr/bin/env python3
"""Enforce a max-length budget on plugin component `description` frontmatter.

For every enabled plugin, Claude Code injects the `description` frontmatter of
each skill, agent, and slash command into model context at session start. This
script measures those descriptions against a character budget so the always-on
context footprint can't silently regress.

Scans `*/skills/*/SKILL.md`, `*/agents/*.md`, `*/commands/*.md` from the repo
root. Paths under `tests/` or `fixtures/` are excluded (they are test data, not
shipped components). A path listed in `scripts/frontmatter-budget-allow.txt`
(one repo-relative path per line, `#` comments allowed) is reported as allowed
and never counts as a violation.

Read-only: never writes to the repo. Exit 0 when clean, 1 when any violation.
"""
import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWLIST_PATH = os.path.join(REPO_ROOT, "scripts", "frontmatter-budget-allow.txt")

# Shared scan primitives live in _frontmatter_common so this script and
# build-capability-index.py can't drift on what counts as a component or on the
# dispatch-only rule. Bootstrap this script's own dir onto sys.path so the import
# resolves both when run directly and when loaded via importlib in the tests.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _frontmatter_common import (  # noqa: E402
    PATTERNS,
    is_excluded,
    frontmatter_block,
    disable_model_invocation,
    load_lines,
)
from _layout import glob_components, plugin_name  # noqa: E402

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - CI installs pyyaml
    _yaml = None


def load_allowlist(path=ALLOWLIST_PATH):
    # The shared comment-stripping loader, not a private copy: every script that
    # reads a control file must parse it the same way, and a copy here would
    # drift from the others.
    return set(load_lines(path))


def extract_description(text):
    """Return the frontmatter `description` value as a single collapsed line.

    Handles YAML folded/literal blocks (`description: >` / `|`) and plain
    single-line values. Returns None when there is no frontmatter description.
    """
    fm = frontmatter_block(text)
    if fm is None:
        return None
    m2 = re.search(
        r"^description:\s*(.*?)(?=\n[A-Za-z_][\w-]*:|\Z)", fm, re.S | re.M
    )
    if not m2:
        return None
    value = m2.group(1)
    # Strip a leading YAML block-scalar indicator (`>`, `|`, with optional
    # chomping/indent modifiers like `>-`, `|2`) so it isn't measured as text.
    value = re.sub(r"^[>|][+\-0-9]*\s*\n", "", value)
    return re.sub(r"\s+", " ", value.strip())


def yaml_error(text):
    """Return a short reason string if the frontmatter is not valid YAML with a
    usable string `description`, else None.

    Catches the common breakage of an unquoted plain scalar that contains a
    `: ` sequence (e.g. `description: ... Triggers: "x"`), which a real YAML
    loader rejects even though a naive regex parse would not. Falls back to a
    lightweight heuristic when PyYAML is unavailable.
    """
    fm = frontmatter_block(text)
    if fm is None:
        return None
    if _yaml is not None:
        try:
            data = _yaml.safe_load(fm)
        except Exception as exc:  # yaml.YAMLError and friends
            return str(exc).splitlines()[0][:120]
        if not isinstance(data, dict) or not isinstance(data.get("description"), str):
            return "description missing or not a string after YAML parse"
        return None
    # Fallback (no PyYAML): flag an unquoted single-line description containing `: `.
    m2 = re.search(r"^description:[ \t]*(?![>|'\"])(.*)$", fm, re.M)
    if m2 and ": " in m2.group(1):
        return "unquoted description contains ': ' (invalid plain scalar) [heuristic]"
    return None


def summarize(root):
    """Bucket every component's description length by plugin, split into
    *injected* (counted against the always-on footprint) and *dispatch-only*
    (`disable-model-invocation: true`, not injected). Same scan rules as scan().
    Returns (per_plugin, totals) where per_plugin maps plugin -> dict of
    injected_chars/injected_count/dispatch_chars/dispatch_count."""
    per_plugin = {}
    for kind, pattern in PATTERNS:
        for path in glob_components(root, pattern):
            rel = os.path.relpath(path, root)
            if is_excluded(rel):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            desc = extract_description(text)
            if desc is None:
                continue
            plugin = plugin_name(rel)
            bucket = per_plugin.setdefault(
                plugin, {"injected_chars": 0, "injected_count": 0,
                         "dispatch_chars": 0, "dispatch_count": 0})
            if disable_model_invocation(text):
                bucket["dispatch_chars"] += len(desc)
                bucket["dispatch_count"] += 1
            else:
                bucket["injected_chars"] += len(desc)
                bucket["injected_count"] += 1
    totals = {"injected_chars": 0, "injected_count": 0,
              "dispatch_chars": 0, "dispatch_count": 0}
    for b in per_plugin.values():
        for k in totals:
            totals[k] += b[k]
    return per_plugin, totals


def scan(root, max_chars, allowlist):
    violations = []
    allowed = []
    invalid = []
    for kind, pattern in PATTERNS:
        for path in glob_components(root, pattern):
            rel = os.path.relpath(path, root)
            if is_excluded(rel):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            plugin = plugin_name(rel)
            err = yaml_error(text)
            if err is not None and rel not in allowlist:
                invalid.append({"path": rel, "kind": kind, "plugin": plugin, "error": err})
            desc = extract_description(text)
            if desc is None:
                continue
            n = len(desc)
            if n <= max_chars:
                continue
            record = {"path": rel, "kind": kind, "plugin": plugin, "chars": n}
            if rel in allowlist:
                allowed.append(record)
            else:
                violations.append(record)
    violations.sort(key=lambda r: -r["chars"])
    allowed.sort(key=lambda r: -r["chars"])
    invalid.sort(key=lambda r: r["path"])
    return violations, allowed, invalid


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max", type=int, default=300, help="max description chars (default 300)")
    ap.add_argument("--root", default=REPO_ROOT, help="repo root to scan")
    ap.add_argument("--allowlist", default=ALLOWLIST_PATH, help="path to allowlist file")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--summary", action="store_true",
                    help="report per-plugin injected vs dispatch-only description chars")
    args = ap.parse_args(argv)

    allowlist = load_allowlist(args.allowlist)
    violations, allowed, invalid = scan(args.root, args.max, allowlist)

    if args.summary:
        per_plugin, totals = summarize(args.root)
        if args.json:
            print(json.dumps({"per_plugin": per_plugin, "totals": totals}, indent=2, sort_keys=True))
        else:
            print("Always-on description footprint (injected = counted, "
                  "dispatch-only = disable-model-invocation):\n")
            print(f"  {'plugin':22s} {'injected':>18s} {'dispatch-only':>18s}")
            for plugin in sorted(per_plugin):
                b = per_plugin[plugin]
                inj = f"{b['injected_chars']}c/{b['injected_count']}"
                dsp = f"{b['dispatch_chars']}c/{b['dispatch_count']}"
                print(f"  {plugin:22s} {inj:>18s} {dsp:>18s}")
            tinj = f"{totals['injected_chars']}c/{totals['injected_count']}"
            tdsp = f"{totals['dispatch_chars']}c/{totals['dispatch_count']}"
            print(f"  {'TOTAL':22s} {tinj:>18s} {tdsp:>18s}")
        return 1 if (violations or invalid) else 0

    if args.json:
        print(json.dumps(
            {"max": args.max, "violations": violations, "allowed": allowed, "invalid": invalid},
            indent=2,
        ))
    else:
        if invalid:
            print(f"{len(invalid)} description(s) with invalid YAML frontmatter:")
            for r in invalid:
                print(f"  {r['kind']:8s}  {r['path']}  — {r['error']}")
            print()
        if violations:
            print(f"{len(violations)} description(s) over {args.max} chars:")
            for r in violations:
                print(f"  {r['chars']:5d}  {r['kind']:8s}  {r['path']}")
        else:
            print(f"All descriptions within {args.max} chars.")
        if allowed:
            print(f"\n{len(allowed)} allowlisted (not counted):")
            for r in allowed:
                print(f"  {r['chars']:5d}  {r['kind']:8s}  {r['path']}")

    return 1 if (violations or invalid) else 0


if __name__ == "__main__":
    sys.exit(main())
