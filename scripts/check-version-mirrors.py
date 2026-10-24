#!/usr/bin/env python3
"""A plugin's version agrees at every site that mirrors it.

A version is one fact stored in several places: a reference (the repo's VERSION file in
a `core/` source layout, else the plugin manifest), the root marketplace entry, a
`(vX.Y.Z)` marker in the README's lead paragraph, and the top `## [X.Y.Z]` entry of a
`CHANGELOG.md` in the plugin's sources, when one exists. The repo-root CHANGELOG.md sits
outside the plugin's sources, so it is not one of the mirrors reconciled here. Left
unbound, they drift.

A README lead-paragraph marker is the mirror that goes stale first: it is one line
nobody reads when they bump a version, so a plugin can ship release after release with
its README still naming an old one. So each mirror is read from its file, never
recalled: a version string typed from memory is the drift this script exists to catch.

**A sweep for the outgoing version string cannot catch it.** A line reading the old
version never matches a search for the new one, and a path list that omits the file
returns zero and reads as green. That is the failure this script exists to make
impossible: it enumerates the mirrors POSITIVELY and reconciles them against the
reference, so a site can only pass by agreeing, never by being unreachable.

  MANIFEST-MISSING   a marketplace entry names a plugin with no manifest.
  MARKETPLACE-DRIFT  the marketplace entry's version != the reference.
  README-DRIFT       the README lead paragraph's `(vX.Y.Z)` != the reference.
  CHANGELOG-DRIFT    the top `## [X.Y.Z]` entry != the reference.
  MIRROR-MISSING     a plugin KNOWN to carry a mirror has lost it.
  UNLISTED           a plugin directory (in a source layout, a generated output under
                     plugins/<host>/) with a manifest and no marketplace entry.
  VERSION-MISSING    a source layout with no VERSION file.
  VERSION-MALFORMED  a VERSION file that does not hold one X.Y.Z.
  SECOND-SOURCE      a source manifest carrying its own version beside VERSION.
  GENERATED-DRIFT    the generated manifest the marketplace entry names is missing,
                     or its version != VERSION (VERSION changed, the build did not run).
  METADATA-DRIFT     the marketplace metadata version != VERSION.

The CHANGELOG class matters because a changelog that declares itself the record of
"All notable changes" while its top entry sits releases behind has real consumers: a
release tool that sources a tag message from the top entry "if one exists" produces a
tag describing the wrong release.

Reading a run of missing entries as a convention ("this file records minor versions
only") is the reasoning that lets that drift through. Consecutive misses in the only
file claiming to document every release are drift, and the difference between the two
readings is exactly what a guard settles and prose does not.

MIRROR-MISSING exists because a bare `rv is not None` test makes marker DELETION silent: a
plugin that loses its README marker becomes indistinguishable from one that never
had it, so the guard can drop from checking a site to checking none while still
printing green. That is the same "unreachable reads as green" class this script was
written for, one level in. Membership is pinned in KNOWN_MIRRORS below.

**Only the lead paragraph is checked, and only the parenthesized form.** READMEs
legitimately contain version strings that are not mirrors — a trigger phrase such as
`"cut v1.4.0"`, or a sample command input. Both are usage, not claims about the
plugin, and a looser matcher would demand they track the plugin version. The lead
paragraph (everything before the first `## `) plus parentheses is the convention
actually in use.

A plugin whose README carries no such marker is fine — this reports drift, it does
not mandate a mirror that does not exist.

**A source layout has one version source.** In a `core/` plus `hosts/<host>/add/`
layout the build stamps VERSION into the generated manifest and the marketplace entry, so
there every mirror is compared to VERSION, and the last five classes above apply. A plain
marketplace layout (no `core/`) keeps the manifest as each plugin's reference, even with a
VERSION file beside it.

Read-only. Exit 0 when every mirror agrees, 1 otherwise.
"""
import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETPLACE = os.path.join(".claude-plugin", "marketplace.json")
LEAD_VERSION_RE = re.compile(r"\(v(\d+\.\d+\.\d+)\)")
CHANGELOG_ENTRY_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.M)

# Plugins known to carry each optional mirror. Pinned so that DELETING a mirror is a
# finding rather than a silent loss of coverage. Add a plugin here when it gains one.
KNOWN_MIRRORS = {"readme_lead": {"planning"}, "changelog": set()}

VERSION_FILE = "VERSION"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
MANIFEST = os.path.join(".claude-plugin", "plugin.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _layout import CORE, find_in, is_generated, source_dirs  # noqa: E402


def repo_version(root):
    """The stripped contents of root/VERSION, or None when there is none."""
    path = os.path.join(root, VERSION_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def _locate(root, plugin_dir, rel):
    """`rel` in the directories `plugin_dir` is built from (its sources, never a
    generated copy), or None."""
    return find_in(source_dirs(root, plugin_dir), rel)


def _shown(root, plugin_dir, rel):
    """The repo-relative path a message should name: the source file actually read."""
    found = _locate(root, plugin_dir, rel)
    return os.path.relpath(found, root) if found else os.path.join(plugin_dir, rel)


def manifest_version(root, plugin_dir):
    path = _locate(root, plugin_dir, os.path.join(".claude-plugin", "plugin.json"))
    if path is None:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("version")


def readme_lead_version(root, plugin_dir):
    """The `(vX.Y.Z)` in the README's lead paragraph, or None.

    Lead paragraph = everything before the first `## ` heading. Scoped that way on
    purpose: a version further down is documentation of a command or an example,
    not a claim about this plugin's own version.
    """
    path = _locate(root, plugin_dir, "README.md")
    if path is None:
        return None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lead = re.split(r"^## ", text, maxsplit=1, flags=re.M)[0]
    m = LEAD_VERSION_RE.search(lead)
    return m.group(1) if m else None


def changelog_version(root, plugin_dir):
    """The topmost released `## [X.Y.Z]` in a CHANGELOG, or None.

    An `## [Unreleased]` section above it is conventional and is skipped rather
    than treated as the top entry — the regex only matches a semver triple.
    """
    path = _locate(root, plugin_dir, "CHANGELOG.md")
    if path is None:
        return None
    with open(path, encoding="utf-8") as fh:
        m = CHANGELOG_ENTRY_RE.search(fh.read())
    return m.group(1) if m else None


def check(root):
    problems = []
    mp_path = os.path.join(root, MARKETPLACE)
    with open(mp_path, encoding="utf-8") as fh:
        mp = json.load(fh)

    layered = os.path.isdir(os.path.join(root, CORE))
    version = repo_version(root) if layered else None
    if layered and version is None:
        problems.append(f"{VERSION_FILE}-MISSING — a source layout has no {VERSION_FILE} file, "
                        "so no version source")
    elif version is not None and not VERSION_RE.match(version):
        problems.append(f"{VERSION_FILE}-MALFORMED — {VERSION_FILE} holds {version!r}, "
                        "not one X.Y.Z")
    if version is not None:
        meta = (mp.get("metadata") or {}).get("version")
        if meta != version:
            problems.append(f"marketplace: METADATA-DRIFT — metadata says {meta!r}, "
                            f"{VERSION_FILE} says {version!r}")

    listed = set()
    counts = {"readme": 0, "changelog": 0}
    for entry in mp.get("plugins", []):
        name = entry.get("name", "?")
        plugin_dir = entry.get("source", "").removeprefix("./")
        listed.add(plugin_dir)
        if _locate(root, plugin_dir, MANIFEST) is None:
            problems.append(f"{name}: MANIFEST-MISSING — marketplace names "
                            f"{plugin_dir!r}, which has no plugin.json")
            continue
        mv = manifest_version(root, plugin_dir)
        if version is not None:
            if mv is not None:
                problems.append(f"{name}: SECOND-SOURCE — {_shown(root, plugin_dir, MANIFEST)} "
                                f"carries version {mv!r} beside {VERSION_FILE}; remove it")
            mv = version
            if is_generated(plugin_dir):
                gen = os.path.join(root, plugin_dir, MANIFEST)
                gv = None
                if os.path.exists(gen):
                    with open(gen, encoding="utf-8") as fh:
                        gv = json.load(fh).get("version")
                if gv != version:
                    problems.append(f"{name}: GENERATED-DRIFT — {os.path.join(plugin_dir, MANIFEST)} "
                                    f"says {gv!r}, {VERSION_FILE} says {version!r}; run the build")
        said = VERSION_FILE if version is not None else "manifest"
        if entry.get("version") != mv:
            problems.append(f"{name}: MARKETPLACE-DRIFT — marketplace says "
                            f"{entry.get('version')!r}, {said} says {mv!r}")
        rv = readme_lead_version(root, plugin_dir)
        if rv is not None and rv != mv:
            problems.append(f"{name}: README-DRIFT — {_shown(root, plugin_dir, 'README.md')} lead "
                            f"paragraph says (v{rv}), {said} says {mv}")
        elif rv is None and name in KNOWN_MIRRORS["readme_lead"]:
            problems.append(f"{name}: MIRROR-MISSING — {_shown(root, plugin_dir, 'README.md')} is known "
                            "to carry a (vX.Y.Z) lead marker and no longer does")
        if rv is not None:
            counts["readme"] += 1

        cv = changelog_version(root, plugin_dir)
        if cv is not None and cv != mv:
            problems.append(f"{name}: CHANGELOG-DRIFT — {_shown(root, plugin_dir, 'CHANGELOG.md')}'s top "
                            f"entry is [{cv}], {said} says {mv}")
        elif cv is None and name in KNOWN_MIRRORS["changelog"]:
            problems.append(f"{name}: MIRROR-MISSING — {_shown(root, plugin_dir, 'CHANGELOG.md')} is known "
                            "to carry released entries and has none")
        if cv is not None:
            counts["changelog"] += 1

    # A plugin with a manifest and no marketplace entry ships nowhere, and no
    # version check would ever look at it.
    candidates = sorted(os.listdir(root))
    if layered:
        # In a source layout the shipped plugins are the generated outputs.
        gen = os.path.join(root, "plugins")
        candidates += sorted(f"plugins/{h}/{n}" for h in (os.listdir(gen) if os.path.isdir(gen) else [])
                             if os.path.isdir(os.path.join(gen, h))
                             for n in os.listdir(os.path.join(gen, h)))
    for name in candidates:
        d = os.path.join(root, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, ".claude-plugin", "plugin.json")):
            if name not in listed:
                problems.append(f"{name}: UNLISTED — has a manifest but no "
                                "marketplace entry")
    return problems, len(mp.get("plugins", [])), counts


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-version-mirrors")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)
    problems, n, counts = check(args.root)
    # honest-gates: name each population SEPARATELY. "N plugins reconciled across
    # manifest, marketplace and README lead" overstates a run in which fewer than N
    # carry a README marker: it reads as N leads reconciled when fewer were.
    print(f"{n} manifest/marketplace pair(s), {counts['readme']} README lead(s) and "
          f"{counts['changelog']} changelog(s) reconciled; {len(problems)} problem(s).")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
