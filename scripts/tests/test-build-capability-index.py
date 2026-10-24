#!/usr/bin/env python3
"""Fixture tests for scripts/build-capability-index.py.

Builds synthetic plugin trees in temp dirs and asserts the generator's
contract: component discovery across skills/agents/commands, name derivation,
model + disable-model-invocation extraction, requires_enablement detection
(hooks / .mcp.json / bundled container MCP), tests/fixtures exclusion, stable
sort, and byte-idempotent output (the CI freshness check depends on it).
Stdlib only.
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "build-capability-index.py")

spec = importlib.util.spec_from_file_location("capindex", SCRIPT)
capindex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capindex)

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def skill(name, desc, extra=""):
    return f"---\nname: {name}\ndescription: {desc}\n{extra}---\n\n# {name}\n"


def by_name(components, name):
    return next(c for c in components if c["name"] == name)


def discovery_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "lang-kit/skills/lang-coding/SKILL.md"),
              skill("lang-coding", "Use when authoring Lang."))
        write(os.path.join(root, "lang-kit/agents/lang-expert.md"),
              skill("lang-expert", "Lang authoring agent.", extra="model: sonnet\n"))
        write(os.path.join(root, "lang-kit/commands/lang-review.md"),
              skill("lang-review", "Review Lang."))
        # excluded paths
        write(os.path.join(root, "lang-kit/skills/x/tests/SKILL.md"),
              skill("t", "test data"))
        write(os.path.join(root, "lang-kit/skills/x/fixtures/SKILL.md"),
              skill("f", "fixture data"))

        index = capindex.build(root)
        comps = index["components"]
        names = {c["name"] for c in comps}
        check(index["schema"] == capindex.SCHEMA_VERSION, "schema version present")
        check(names == {"lang-coding", "lang-expert", "lang-review"},
              "skills+agents+commands discovered, tests/fixtures excluded")
        kinds = {c["name"]: c["kind"] for c in comps}
        check(kinds["lang-coding"] == "skill" and kinds["lang-expert"] == "agent"
              and kinds["lang-review"] == "command", "kinds correct")
        check(all(c["path"].startswith("lang-kit/") and "\\" not in c["path"]
                  for c in comps), "paths repo-relative with forward slashes")
        check(by_name(comps, "lang-expert")["model"] == "sonnet", "agent model pin captured")
        check(by_name(comps, "lang-coding")["model"] is None, "no model -> null")


def field_cases():
    with tempfile.TemporaryDirectory() as root:
        # disable-model-invocation true
        write(os.path.join(root, "pp/skills/forum-post/SKILL.md"),
              skill("forum-post", "Draft a forum post.",
                    extra="disable-model-invocation: true\n"))
        # folded description collapses
        write(os.path.join(root, "pp/skills/digest/SKILL.md"),
              "---\nname: digest\ndescription: >\n  line one\n  line two\n---\n\n# r\n")
        # no name field -> derived from dir
        write(os.path.join(root, "pp/skills/derived/SKILL.md"),
              "---\ndescription: no name here\n---\n\n# d\n")
        # agent with no name -> derived from filename
        write(os.path.join(root, "pp/agents/post-drafter.md"),
              "---\ndescription: drafter\nmodel: haiku\n---\n\n# p\n")

        comps = capindex.build(root)["components"]
        check(by_name(comps, "forum-post")["disable_model_invocation"] is True,
              "disable-model-invocation: true captured")
        check(by_name(comps, "digest")["disable_model_invocation"] is False,
              "absent flag -> False")
        check(by_name(comps, "digest")["description"] == "line one line two",
              "folded description collapsed to one line")
        check(by_name(comps, "derived")["name"] == "derived",
              "skill name derived from directory when frontmatter name absent")
        check(by_name(comps, "post-drafter")["name"] == "post-drafter",
              "agent name derived from filename when absent")
        # Single-quoted YAML scalar with an embedded "..." phrase and a doubled
        # apostrophe — must be unquoted/unescaped to real text (the content the
        # router consumes), not carried through with literal quotes.
        write(os.path.join(root, "wk/skills/tip/SKILL.md"),
              "---\nname: tip\ndescription: 'Use Avery''s \"12 Widget Pitfalls\" list.'\n---\n\n# c\n")
        comps = capindex.build(root)["components"]
        check(by_name(comps, "tip")["description"] == 'Use Avery\'s "12 Widget Pitfalls" list.',
              "single-quoted description unquoted/unescaped to real text")


def hard_require_yaml_case():
    # With PyYAML unavailable, the generator must fail loudly, not silently fall
    # back to a divergent parse that would break byte-reproducibility.
    saved = capindex._yaml
    try:
        capindex._yaml = None
        raised = False
        try:
            capindex.parse_frontmatter("---\nname: x\ndescription: y\n---\n")
        except SystemExit:
            raised = True
        check(raised, "parse_frontmatter raises SystemExit when PyYAML is absent")
    finally:
        capindex._yaml = saved


def enablement_cases():
    with tempfile.TemporaryDirectory() as root:
        # plugin with native hooks
        write(os.path.join(root, "hooky/commands/hooky.md"), skill("hooky", "hook sets"))
        write(os.path.join(root, "hooky/hooks/hooks.json"), "{}\n")
        # plugin with bundled container MCP
        write(os.path.join(root, "mobile-kit/skills/mobile-build/SKILL.md"),
              skill("mobile-build", "build"))
        write(os.path.join(root, "mobile-kit/infrastructure/mcp-server/server.mjs"), "//\n")
        # plugin with native .mcp.json
        write(os.path.join(root, "mcp-plug/skills/s/SKILL.md"), skill("s", "x"))
        write(os.path.join(root, "mcp-plug/.mcp.json"), "{}\n")
        # plugin with neither
        write(os.path.join(root, "lang-kit/skills/lang-coding/SKILL.md"),
              skill("lang-coding", "lang"))
        # plugin whose ONLY .mcp.json is test-fixture data — must NOT count
        write(os.path.join(root, "planning/skills/pm/SKILL.md"), skill("pm", "maturity"))
        write(os.path.join(root, "planning/skills/pm/tests/fixtures/x/.mcp.json"), "{}\n")

        comps = capindex.build(root)["components"]
        check(by_name(comps, "hooky")["requires_enablement"] is True,
              "native hooks -> requires_enablement")
        check(by_name(comps, "mobile-build")["requires_enablement"] is True,
              "bundled container MCP -> requires_enablement")
        check(by_name(comps, "s")["requires_enablement"] is True,
              "native .mcp.json -> requires_enablement")
        check(by_name(comps, "lang-coding")["requires_enablement"] is False,
              "plugin without hooks/MCP -> not requires_enablement")
        check(by_name(comps, "pm")["requires_enablement"] is False,
              "fixture-only .mcp.json does NOT flag requires_enablement")


def stability_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "b-plug/skills/z/SKILL.md"), skill("z", "z"))
        write(os.path.join(root, "b-plug/skills/a/SKILL.md"), skill("a", "a"))
        write(os.path.join(root, "a-plug/agents/m.md"), skill("m", "m"))

        first = capindex.render(capindex.build(root))
        second = capindex.render(capindex.build(root))
        check(first == second, "output byte-identical across two runs (reproducible)")
        check(first.endswith("\n"), "output ends with trailing newline")
        # no absolute path leaked into output
        check(root not in first, "no absolute path in output")
        comps = capindex.build(root)["components"]
        ordered = [(c["plugin"], c["kind"], c["name"]) for c in comps]
        check(ordered == sorted(ordered), "components sorted by (plugin, kind, name)")


def main_cli_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/a/SKILL.md"), skill("a", "desc a"))
        out = os.path.join(root, "capability-index.json")
        rc = capindex.main(["--root", root, "--write", "--out", out])
        check(rc == 0, "--write exits 0")
        check(os.path.exists(out), "--write creates the index file")
        with open(out) as fh:
            data = json.load(fh)
        check(len(data["components"]) == 1 and data["components"][0]["name"] == "a",
              "written index parses and carries the component")


if __name__ == "__main__":
    print("discovery:")
    discovery_cases()
    print("fields:")
    field_cases()
    print("hard-require yaml:")
    hard_require_yaml_case()
    print("enablement:")
    enablement_cases()
    print("stability:")
    stability_cases()
    print("cli:")
    main_cli_cases()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
