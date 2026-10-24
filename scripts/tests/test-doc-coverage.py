#!/usr/bin/env python3
"""Fixture tests for scripts/check-doc-coverage.py.

A smoke-run against the live repo demonstrates only "today's tree happens to
pass", nothing about boundary conditions. These pin the parsing logic against
contrived trees:

  * a missing README fails, and reports every component as undocumented;
  * a component named in the README passes; one absent fails, BY NAME;
  * word-boundary matching — `backlog` is NOT satisfied by `old-backlog`,
    and a hyphenated name is not satisfied by half of itself;
  * an allowlist entry exempts exactly one component and nothing else;
  * the stub floor fires on a README that names everything and explains nothing;
  * /tests/ and /fixtures/ paths are excluded from the component set, so a
    plugin's own test data never becomes a documentation obligation.

No pytest. Plain assertions, non-zero exit on failure.
Run: python3 scripts/tests/test-doc-coverage.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_doc_coverage", ROOT / "scripts" / "check-doc-coverage.py")
cdc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdc)

fails: list[str] = []


def chk(cond, msg):
    if not cond:
        fails.append(msg)


def build(tmp, plugins_spec):
    """Materialise a fake marketplace root and point the module at it.

    plugins_spec: {plugin_name: {"skills": [...], "agents": [...],
                                 "commands": [...], "readme": str|None,
                                 "extra": [relative paths to also create]}}
    """
    root = Path(tmp)
    entries = []
    for name, spec in plugins_spec.items():
        pdir = root / name
        for s in spec.get("skills", []):
            p = pdir / "skills" / s / "SKILL.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\nname: %s\n---\n" % s)
        for a in spec.get("agents", []):
            p = pdir / "agents" / f"{a}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\nname: %s\n---\n" % a)
        for c in spec.get("commands", []):
            p = pdir / "commands" / f"{c}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\nname: %s\n---\n" % c)
        for rel in spec.get("extra", []):
            p = pdir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\nname: fixture-noise\n---\n")
        for rel, body in spec.get("files", {}).items():
            fp = pdir / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(body)
        if spec.get("readme") is not None:
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "README.md").write_text(spec["readme"])
        entries.append({"name": name, "source": f"./{name}"})
    mp = root / ".claude-plugin"
    mp.mkdir(parents=True, exist_ok=True)
    (mp / "marketplace.json").write_text(json.dumps({"plugins": entries}))
    cdc.ROOT = root
    cdc.MARKETPLACE = mp / "marketplace.json"
    cdc.ALLOWFILE = root / "scripts" / "doc-coverage-allow.txt"
    return root


def report_for(plugin, rep):
    for r in rep:
        if r["plugin"] == plugin:
            return r
    return None


PROSE = "x" * 4000  # comfortably clears the stub floor

with tempfile.TemporaryDirectory() as tmp:
    build(tmp, {
        "missing-readme": {"skills": ["alpha"], "readme": None},
        "documented": {"skills": ["beta"], "agents": ["gamma"],
                       "readme": f"# documented\n\nbeta and gamma are covered.\n{PROSE}"},
        "undocumented": {"skills": ["delta"], "agents": ["epsilon"],
                         "readme": f"# undocumented\n\nOnly delta is named.\n{PROSE}"},
    })
    rep = cdc.audit()

    r = report_for("missing-readme", rep)
    chk(r["readme"] is False, "missing README not detected")
    chk(len(r["missing"]) == 1, f"missing-README plugin should report all components: {r['missing']}")

    r = report_for("documented", rep)
    chk(r["missing"] == [], f"fully documented plugin reported missing: {r['missing']}")

    r = report_for("undocumented", rep)
    chk([c for _, c in r["missing"]] == ["epsilon"],
        f"should report exactly the absent component: {r['missing']}")

    chk(cdc.main([]) == 1, "main() should exit 1 when a plugin fails")
    chk(cdc.main(["--summary"]) == 0, "--summary should exit 0 even with failures")
    chk(cdc.main(["--plugin", "nope"]) == 2, "unknown --plugin should exit 2")
    chk(cdc.main(["--plugin", "documented"]) == 0, "a clean single plugin should exit 0")

# --- non-frontmatter component types (hooks, MCP, determinism lane) ---------
# These carry no frontmatter, so the shared PATTERNS correctly omit them — and a
# guard that inherited only PATTERNS would structurally never see them, and an
# undocumented determinism lane would pass.
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, {
        "extras": {
            "skills": ["s1"],
            "files": {"hooks/hooks.json": "{}",
                      ".mcp.json": "{}",
                      "scripts/validate.sh": "#!/bin/bash\n"},
            "readme": f"# extras\n\ns1 only.\n{PROSE}"},
    })
    kinds = {k for k, _ in report_for("extras", cdc.audit())["components"]}
    chk(kinds == {"skill", "hook", "mcp", "lane"},
        f"non-frontmatter component types not detected: {kinds}")
    missing = {c for _, c in report_for("extras", cdc.audit())["missing"]}
    chk(missing == {"hooks.json", ".mcp.json", "validate.sh"},
        f"undocumented hook/mcp/lane not all reported: {missing}")

with tempfile.TemporaryDirectory() as tmp:
    build(tmp, {
        "extras": {
            "skills": ["s1"],
            "files": {"hooks/hooks.json": "{}", "scripts/validate.sh": "#!/bin/bash\n"},
            "readme": f"# extras\n\ns1, hooks.json and validate.sh all documented.\n{PROSE}"},
    })
    chk(report_for("extras", cdc.audit())["missing"] == [],
        "naming the hook and lane in the README should satisfy the guard")

# A plugin with NO lane must not be asked to document one.
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, {"plain": {"skills": ["s1"], "readme": f"# plain\n\ns1.\n{PROSE}"}})
    kinds = {k for k, _ in report_for("plain", cdc.audit())["components"]}
    chk(kinds == {"skill"}, f"phantom component types on a plain plugin: {kinds}")

# --- word-boundary matching -------------------------------------------------
chk(not cdc.mentions("see old-backlog for details", "backlog"),
    "`backlog` was wrongly satisfied by `old-backlog` — substring match")
chk(cdc.mentions("the backlog skill", "backlog"), "`backlog` not matched when genuinely present")
chk(not cdc.mentions("we mention code only", "code-review"),
    "hyphenated name wrongly satisfied by a prefix word")
chk(cdc.mentions("run `code-review` first", "code-review"), "hyphenated name not matched when present")
chk(not cdc.mentions("lint-helper-extra is different", "lint-helper"),
    "name wrongly matched inside a longer hyphenated token")

# --- allowlist --------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    root = build(tmp, {"p": {"skills": ["kept", "exempted"],
                             "readme": f"# p\n\nkept is documented.\n{PROSE}"}})
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    cdc.ALLOWFILE.write_text(
        "# reason required after the hash\n"
        "p/exempted  # deliberately undocumented: internal-only, see the register\n")
    rep = cdc.audit()
    chk(report_for("p", rep)["missing"] == [],
        f"allowlisted component still reported: {report_for('p', rep)['missing']}")

    # ...and the allowlist must not exempt anything it wasn't asked to.
    cdc.ALLOWFILE.write_text("# only a comment, no entries\n")
    rep = cdc.audit()
    chk([c for _, c in report_for("p", rep)["missing"]] == ["exempted"],
        "comment-only allowlist wrongly exempted a component")

# --- stub floor -------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, {"stubby": {"skills": ["a", "b", "c", "d", "e"],
                           "readme": "# stubby\n\na b c d e\n"}})
    r = report_for("stubby", cdc.audit())
    chk(r["missing"] == [], "stub fixture should name every component (that is the point)")
    chk(r["stub"] is True,
        f"a README that names everything and explains nothing should trip the floor "
        f"({r['chars']} chars vs floor {r['floor']})")

# --- test data is not a documentation obligation ----------------------------
with tempfile.TemporaryDirectory() as tmp:
    build(tmp, {"withtests": {
        "skills": ["real"],
        "extra": ["skills/real/tests/SKILL.md", "skills/real/fixtures/SKILL.md"],
        "readme": f"# withtests\n\nreal is documented.\n{PROSE}"}})
    r = report_for("withtests", cdc.audit())
    chk(r["missing"] == [],
        f"/tests/ or /fixtures/ path leaked into the component set: {r['missing']}")
    chk(len(r["components"]) == 1,
        f"expected exactly 1 real component, got {[c for _, c in r['components']]}")

if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test-doc-coverage: all assertions passed")
