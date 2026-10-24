#!/usr/bin/env python3
"""check-doc-coverage — every shipped component is named in its plugin's README.

Enforces the mechanical half of the README contract (a plugin's README names
every component it ships):

  * every plugin in .claude-plugin/marketplace.json has a README.md;
  * every component on disk has its name present in that README —
    skills/agents/commands via the shared PATTERNS in _frontmatter_common.py,
    plus hooks and .mcp.json (which carry no frontmatter, so the shared rules
    correctly omit them and this guard must not), excluding /tests/ and
    /fixtures/;
  * the README is not a stub relative to how many components it must cover.

**What this CANNOT check.** It cannot tell a real usage section from a component
name sitting in a bullet list. Coverage is a floor, not a quality bar: green
means nothing is missing, NOT that anything is well explained. Read it as
exactly that much, and do not let an allowlist entry substitute for writing the
section — that inverts the guard into a way of recording what you skipped.

Exceptions: scripts/doc-coverage-allow.txt, one `plugin/component` per line with
a written reason after `#`, mirroring frontmatter-budget-allow.txt.

Run: python3 scripts/check-doc-coverage.py [--summary] [--plugin NAME]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
ALLOWFILE = ROOT / "scripts" / "doc-coverage-allow.txt"

_spec = importlib.util.spec_from_file_location(
    "_frontmatter_common", ROOT / "scripts" / "_frontmatter_common.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)
_spec = importlib.util.spec_from_file_location("_layout", ROOT / "scripts" / "_layout.py")
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)

# A README carrying real usage prose runs well past this per component. The floor
# only catches the degenerate case — a stub that lists names and stops — because
# anything tighter would be a style rule masquerading as a correctness check.
MIN_CHARS_BASE = 400
MIN_CHARS_PER_COMPONENT = 120


def plugins():
    """[(name, [dir, ...])] for every plugin the marketplace actually ships.

    An entry naming generated output is read from the sources it is built from
    (core/ plus that host's layer, `_layout.source_dirs`), never from the copy.
    """
    data = json.loads(MARKETPLACE.read_text())
    out = []
    for entry in data.get("plugins", []):
        src = entry.get("source", "./" + entry["name"])
        out.append((entry["name"], [Path(d) for d in layout.source_dirs(str(ROOT), src)]))
    return sorted(out)


# Component types the SHARED PATTERNS deliberately omit. _frontmatter_common
# exists to reason about context budget, and hooks/MCP carry no frontmatter — so
# they are correctly absent there and would be wrongly absent here. A hook is a
# shipped, user-visible component: it runs on the user's machine, and an
# undocumented one is a behaviour nobody asked for and cannot find the source of.
EXTRA_PATTERNS = (
    ("hook", "hooks/*.json"),
    ("mcp", ".mcp.json"),
    # A plugin-root `scripts/validate.sh` is the determinism-lane orchestrator
    # (a validation kit copied into the plugin). It is user-runnable — `bash
    # scripts/validate.sh <root> [--json]` — so it is a shipped component, not an
    # implementation detail. A validator the README never mentions is exactly the
    # silent omission this guard exists to catch.
    # NOTE: matched by the literal name `validate.sh`, so a README satisfies this
    # by naming the lane's entrypoint.
    ("lane", "scripts/validate.sh"),
)


def components(plugin_dirs):
    """[(kind, name)] shipped by a plugin, across every directory it is built from.

    Skills/agents/commands come from the shared PATTERNS so this guard and the
    context-budget tooling can never disagree about what a component is; hooks
    and MCP servers are added on top (see EXTRA_PATTERNS).
    """
    found = []
    for kind, pattern in fc.PATTERNS:
        # PATTERNS are marketplace-root-relative ("*/skills/*/SKILL.md"); strip
        # the leading plugin segment to glob inside one plugin directory.
        assert pattern.startswith("*/"), (
            f"shared PATTERNS entry {pattern!r} is not plugin-root-relative; "
            "the segment-strip below would glob the wrong subpath")
        sub = pattern.split("/", 1)[1]
        for path in sorted(p for d in plugin_dirs for p in d.glob(sub)):
            posix = "/" + path.relative_to(ROOT).as_posix()
            if fc.is_excluded(posix):
                continue
            name = path.parent.name if kind == "skill" else path.stem
            found.append((kind, name))
    for kind, pattern in EXTRA_PATTERNS:
        for path in sorted(p for d in plugin_dirs for p in d.glob(pattern)):
            posix = "/" + path.relative_to(ROOT).as_posix()
            if fc.is_excluded(posix):
                continue
            # Hooks are documented by their filename (`hooks.json`) or by the
            # script they invoke; accept either, so a README that explains what
            # the hook DOES satisfies the check without naming a JSON file.
            found.append((kind, path.name))
    return found


def load_allow():
    """{(plugin, component)} exempted, each with a written reason."""
    allowed = set()
    if not ALLOWFILE.exists():
        return allowed
    for line in ALLOWFILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = line.split("#", 1)[0].strip()
        if "/" in entry:
            p, c = entry.split("/", 1)
            allowed.add((p.strip(), c.strip()))
    return allowed


def mentions(readme_text, name):
    """Is this component named in the README?

    Word-boundary match so `backlog` does not satisfy itself via `old-backlog`,
    and so a hyphenated name is not matched by one of its halves.
    """
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", readme_text) is not None


def audit():
    allowed = load_allow()
    report = []
    for name, pdirs in plugins():
        comps = components(pdirs)
        found = layout.find_in([str(d) for d in pdirs], "README.md")
        readme = Path(found) if found else pdirs[0] / "README.md"
        if not readme.exists():
            report.append({"plugin": name, "readme": False, "components": comps,
                           "missing": [c for c in comps], "chars": 0, "stub": True})
            continue
        text = readme.read_text(errors="ignore")
        missing = [(k, c) for k, c in comps
                   if not mentions(text, c) and (name, c) not in allowed]
        floor = MIN_CHARS_BASE + MIN_CHARS_PER_COMPONENT * len(comps)
        report.append({"plugin": name, "readme": True, "components": comps,
                       "missing": missing, "chars": len(text),
                       "stub": len(text) < floor, "floor": floor})
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-doc-coverage")
    ap.add_argument("--summary", action="store_true",
                    help="Print a documented/total table and exit 0.")
    ap.add_argument("--plugin", default="", help="Check only this plugin.")
    args = ap.parse_args(argv)

    report = audit()
    if args.plugin:
        report = [r for r in report if r["plugin"] == args.plugin]
        if not report:
            print(f"no such plugin: {args.plugin}", file=sys.stderr)
            return 2

    if args.summary:
        print(f"{'plugin':22s} {'components':>10s} {'documented':>11s} {'chars':>7s}")
        for r in report:
            n = len(r["components"])
            print(f"{r['plugin']:22s} {n:>10d} {n - len(r['missing']):>11d} {r['chars']:>7d}"
                  + ("" if r["readme"] else "   (no README)"))
        return 0

    failed = False
    for r in report:
        if not r["readme"]:
            failed = True
            print(f"FAIL {r['plugin']}: no README.md "
                  f"({len(r['components'])} components undocumented)")
            continue
        if r["missing"]:
            failed = True
            print(f"FAIL {r['plugin']}: {len(r['missing'])} component(s) not named in README.md")
            for kind, c in r["missing"]:
                print(f"       - {kind} {c}")
        if r["stub"]:
            failed = True
            print(f"FAIL {r['plugin']}: README.md is {r['chars']} chars, below the "
                  f"{r['floor']}-char floor for {len(r['components'])} components")

    if failed:
        print("\ncoverage is a floor, not a quality bar",
              file=sys.stderr)
        return 1
    print(f"OK — {len(report)} plugin(s): every shipped component is named in its README")
    return 0


if __name__ == "__main__":
    sys.exit(main())
