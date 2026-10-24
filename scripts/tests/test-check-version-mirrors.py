#!/usr/bin/env python3
"""Fixture tests for scripts/check-version-mirrors.py.

The load-bearing cases are the ones proving the guard REJECTS. A check that searches
for the *outgoing* version string and never looks in the directory it is meant to check
returns zero and reads as green — so a version-mirror check that only ever passes is
indistinguishable from no check at all.

Two classes deserve their own cases beyond simple drift:

  * **MIRROR-MISSING.** Deleting a marker is silent when "no marker" and "no drift"
    are the same state. A plugin then goes from checked to unchecked while the guard
    still prints green.
  * **CHANGELOG-DRIFT.** A changelog's top entry is a mirror too, and the one most
    easily left out of a sweep.

Stdlib only.
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-version-mirrors.py")

spec = importlib.util.spec_from_file_location("vm", SCRIPT)
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)

FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def build(root, plugins, marketplace=None):
    """plugins: {name: {version, readme?, changelog?}}. marketplace defaults to agreeing."""
    entries = []
    for name, spec_ in plugins.items():
        d = os.path.join(root, name, ".claude-plugin")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "plugin.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": name, "version": spec_["version"]}, fh)
        if "readme" in spec_:
            with open(os.path.join(root, name, "README.md"), "w", encoding="utf-8") as fh:
                fh.write(f"# {name}\n\n{spec_['readme']}\n\n## Installation\n\nx\n")
        if "changelog" in spec_:
            with open(os.path.join(root, name, "CHANGELOG.md"), "w", encoding="utf-8") as fh:
                fh.write(f"# Changelog\n\n{spec_['changelog']}\n\n### Changed\n- x\n")
        entries.append({"name": name, "source": f"./{name}",
                        "version": (marketplace or {}).get(name, spec_["version"])})
    d = os.path.join(root, ".claude-plugin")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "marketplace.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "m", "metadata": {"version": "1.0.0"}, "plugins": entries}, fh)


def run(root):
    problems, _n, _counts = vm.check(root)
    return problems


def cases():
    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3"}})
        check(run(root) == [], "manifest and marketplace agreeing passes")

    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3"}}, marketplace={"alpha": "1.2.2"})
        p = run(root)
        check(any("MARKETPLACE-DRIFT" in x for x in p), "marketplace drift is caught")

    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3", "readme": "A thing (v1.2.3) that works."}})
        check(run(root) == [], "an agreeing README lead marker passes")

    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3", "readme": "A thing (v1.0.0) that works."}})
        p = run(root)
        check(any("README-DRIFT" in x for x in p), "a stale README lead marker is caught")

    # The exclusion the live tree depends on: usage samples are not mirrors.
    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3",
                               "readme": 'Run `tag v3.1.0` to mark a release.'}})
        check(run(root) == [],
              "an unparenthesised version in prose is a usage sample, not a mirror")

    # ...and one below the lead is history, not a claim about this version.
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "alpha", ".claude-plugin"))
        with open(os.path.join(root, "alpha", ".claude-plugin", "plugin.json"), "w") as fh:
            json.dump({"name": "alpha", "version": "1.2.3"}, fh)
        with open(os.path.join(root, "alpha", "README.md"), "w") as fh:
            fh.write("# alpha\n\nA thing.\n\n## History\n\nTiering shipped (v0.9.0).\n")
        d = os.path.join(root, ".claude-plugin"); os.makedirs(d)
        with open(os.path.join(d, "marketplace.json"), "w") as fh:
            json.dump({"name": "m", "metadata": {"version": "1.0.0"},
                       "plugins": [{"name": "alpha", "source": "./alpha", "version": "1.2.3"}]}, fh)
        check(run(root) == [], "a (vX.Y.Z) below the lead paragraph is not checked")

    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3", "changelog": "## [1.2.3] - 2026-01-01"}})
        check(run(root) == [], "an agreeing changelog top entry passes")

    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3", "changelog": "## [1.0.0] - 2026-01-01"}})
        p = run(root)
        check(any("CHANGELOG-DRIFT" in x for x in p),
              "a stale changelog top entry is caught — a changelog is a mirror too")

    # An Unreleased section above the top release must not be read as the version.
    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3",
                               "changelog": "## [Unreleased]\n\n- wip\n\n## [1.2.3] - 2026-01-01"}})
        check(run(root) == [], "an `## [Unreleased]` section is skipped, not treated as the top")

    # MIRROR-MISSING: a KNOWN mirror that has been deleted.
    with tempfile.TemporaryDirectory() as root:
        build(root, {"planning": {"version": "1.2.3", "readme": "No marker here."}})
        p = run(root)
        check(any("MIRROR-MISSING" in x for x in p),
              "deleting a KNOWN README marker is caught, not silently uncovered")

    # No plugin in this repo carries a changelog mirror yet, so the mechanism is
    # exercised with a fixture plugin registered for the length of the case.
    saved = set(vm.KNOWN_MIRRORS["changelog"])
    vm.KNOWN_MIRRORS["changelog"].add("withlog")
    try:
        with tempfile.TemporaryDirectory() as root:
            build(root, {"withlog": {"version": "1.2.3"}})
            p = run(root)
            check(any("MIRROR-MISSING" in x and "CHANGELOG" in x for x in p),
                  "deleting a KNOWN changelog is caught too")
    finally:
        vm.KNOWN_MIRRORS["changelog"] = saved

    # A plugin nobody ships, and an entry pointing at nothing.
    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3"}})
        os.makedirs(os.path.join(root, "orphan", ".claude-plugin"))
        with open(os.path.join(root, "orphan", ".claude-plugin", "plugin.json"), "w") as fh:
            json.dump({"name": "orphan", "version": "0.1.0"}, fh)
        p = run(root)
        check(any("UNLISTED" in x for x in p), "a manifest with no marketplace entry is caught")

    with tempfile.TemporaryDirectory() as root:
        d = os.path.join(root, ".claude-plugin"); os.makedirs(d)
        with open(os.path.join(d, "marketplace.json"), "w") as fh:
            json.dump({"name": "m", "metadata": {"version": "1.0.0"},
                       "plugins": [{"name": "ghost", "source": "./ghost", "version": "1.0.0"}]}, fh)
        p = run(root)
        check(any("MANIFEST-MISSING" in x for x in p),
              "a marketplace entry with no manifest is caught")


def build_layered(root, version="1.2.3", source_version=None, generated="1.2.3",
                  entry="1.2.3", metadata="1.2.3", readme="1.2.3"):
    """A core/ + hosts/ source layout with a VERSION file and a generated copy."""
    if version is not None:
        with open(os.path.join(root, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write(version + "\n")
    os.makedirs(os.path.join(root, "core"))
    with open(os.path.join(root, "core", "README.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# planning\n\nA thing (v{readme}).\n\n## Install\n\nx\n")
    src = os.path.join(root, "hosts", "claude", "add", ".claude-plugin")
    os.makedirs(src)
    manifest = {"name": "planning"}
    if source_version is not None:
        manifest["version"] = source_version
    with open(os.path.join(src, "plugin.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    if generated is not None:
        out = os.path.join(root, "plugins", "claude", "planning", ".claude-plugin")
        os.makedirs(out)
        with open(os.path.join(out, "plugin.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "planning", "version": generated}, fh)
    d = os.path.join(root, ".claude-plugin")
    os.makedirs(d)
    with open(os.path.join(d, "marketplace.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "m", "metadata": {"version": metadata},
                   "plugins": [{"name": "planning", "source": "./plugins/claude/planning",
                                "version": entry}]}, fh)


def version_file_cases():
    """With a VERSION file, every mirror is compared to it, not to a manifest."""
    with tempfile.TemporaryDirectory() as root:
        build_layered(root)
        check(run(root) == [], "every mirror agreeing with VERSION passes")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, version="1.2.4")
        p = run(root)
        check(any("GENERATED-DRIFT" in x for x in p),
              "a VERSION bump with no rebuild is caught in the generated manifest")
        check(any("MARKETPLACE-DRIFT" in x for x in p) and any("METADATA-DRIFT" in x for x in p),
              "...and in the marketplace entry and metadata")
        check(any("README-DRIFT" in x for x in p), "...and in the README lead")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, generated=None)
        check(any("GENERATED-DRIFT" in x for x in run(root)),
              "a missing generated manifest is drift, not a pass")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, source_version="1.2.3")
        check(any("SECOND-SOURCE" in x for x in run(root)),
              "a source manifest carrying a version is a second source, even when it agrees")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, metadata="1.0.0")
        check(any("METADATA-DRIFT" in x for x in run(root)), "marketplace metadata drift is caught")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, version=None, source_version="1.2.3")
        check(any("VERSION-MISSING" in x for x in run(root)),
              "a source layout with no VERSION file is caught, not read as the old layout")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, version="1.2.4", readme="1.2.3")
        with open(os.path.join(root, ".claude-plugin", "marketplace.json"), "w") as fh:
            json.dump({"name": "m", "metadata": {"version": "1.2.4"}, "plugins": []}, fh)
        p = run(root)
        check(any("UNLISTED" in x and "plugins/claude/planning" in x for x in p),
              "a generated output with no marketplace entry is caught, so no mirror goes unchecked")

    with tempfile.TemporaryDirectory() as root:
        build_layered(root, version="1.2")
        check(any("VERSION-MALFORMED" in x for x in run(root)), "a VERSION that is not X.Y.Z is caught")

    # A plain marketplace layout keeps the per-manifest meaning even beside a VERSION file.
    with tempfile.TemporaryDirectory() as root:
        build(root, {"alpha": {"version": "1.2.3"}, "beta": {"version": "2.0.0"}})
        with open(os.path.join(root, "VERSION"), "w") as fh:
            fh.write("9.9.9\n")
        check(run(root) == [], "VERSION mode applies only to the core/ source layout")


def real_tree():
    check(vm.main([]) == 0, "every shipped mirror agrees")
    _p, n, counts = vm.check(vm.REPO_ROOT)
    # This marketplace ships exactly one plugin, planning.
    check(n == 1, f"the sweep sees the marketplace's plugin (saw {n})")
    check(vm.repo_version(vm.REPO_ROOT) is not None,
          "the repo's VERSION file is the source every mirror is compared to")
    # The population line must not overstate: these are the sites actually reconciled.
    check(counts["readme"] >= 1,
          f"the README mirror is actually reconciled, not merely counted "
          f"(readme={counts['readme']})")
    # The mirrors are read from the sources, never from the generated copy the
    # marketplace entry names.
    manifest = vm._locate(vm.REPO_ROOT, "plugins/claude/planning",
                          os.path.join(".claude-plugin", "plugin.json"))
    check(manifest is not None and "/hosts/claude/add/" in manifest.replace(os.sep, "/"),
          f"the manifest is read from hosts/claude/add, not plugins/ (got {manifest})")


if __name__ == "__main__":
    print("check-version-mirrors fixtures:")
    cases()
    print("VERSION file:")
    version_file_cases()
    print("real tree:")
    real_tree()
    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("OK")
