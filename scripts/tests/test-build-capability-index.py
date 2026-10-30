#!/usr/bin/env python3
"""Fixture tests for scripts/build-capability-index.py.

Builds synthetic plugin trees in temp dirs and asserts the generator's
contract: component discovery across skills/agents/commands, name derivation,
model + disable-model-invocation extraction, requires_enablement detection
(hooks / .mcp.json / bundled container MCP), tests/fixtures exclusion, stable
sort, and byte-idempotent output (the CI freshness check depends on it).
Stdlib only.
"""
import contextlib
import importlib.util
import io
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


CHECK_SCRIPT = os.path.join(os.path.dirname(HERE), "check-capability-index.py")
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MOD = "hosts/claude/add/hooks/mod"


def declared(*commands):
    return json.dumps({"commands": [{"name": n, "description": d} for n, d in commands]})


def registering(name, desc):
    # The construct a mod registers a slash command with (pane.tsx), not a loose
    # string: `$.command.register({ name, description })` inside session.start.
    return ("export function registerX(on) {\n"
            "  on('session.start', {}, async ($, e, next) => {\n"
            "    const started = await next(e)\n"
            "    await $.command.register({\n"
            f"      name: '{name}',\n"
            f"      description: '{desc}',\n"
            "    })\n"
            "    return started\n"
            "  })\n"
            f"  on('command.run', {{ command: '{name}' }}, async $ => ({{ text: 'ok' }}))\n"
            "}\n")


def run_check(root):
    spec = importlib.util.spec_from_file_location("capcheck", CHECK_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(["--root", root])
    return rc, buf.getvalue()


def registered_command_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "core/skills/a/SKILL.md"), skill("a", "desc a"))
        write(os.path.join(root, MOD, "registered-commands.json"),
              declared(("plan-view", "Show the plan in a pane")))
        index = capindex.build(root)
        cmds = index.get("registered_commands", [])
        check([c["name"] for c in cmds] == ["plan-view"],
              "built index lists plan-view from the declared registered-commands.json")
        check(cmds and cmds[0]["description"] == "Show the plan in a pane"
              and cmds[0]["plugin"] == "planning"
              and cmds[0]["path"] == f"{MOD}/registered-commands.json",
              "declared command carries description, plugin and repo-relative path")
        check([c["name"] for c in index["components"]] == ["a"],
              "declared commands stay out of components (no file to Read-and-follow)")

    # The real tree: the mod's /plan-view is in the index, as the mod describes it.
    real = capindex.build(REPO_ROOT)
    plan_view = [c for c in real.get("registered_commands", []) if c["name"] == "plan-view"]
    check(len(plan_view) == 1 and plan_view[0]["description"] ==
          "Show the executing plan, its stages and tasks, and dispatched agents in a pane",
          "real tree: built index lists /plan-view with the mod's own description")


def registration_drift_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "core/skills/a/SKILL.md"), skill("a", "desc a"))
        write(os.path.join(root, MOD, "registered-commands.json"),
              declared(("plan-view", "Show the plan")))
        write(os.path.join(root, MOD, "pane.tsx"), registering("plan-view", "Show the plan"))
        # A test file's registrations are test doubles, not the mod's commands.
        write(os.path.join(root, MOD, "pane.test.tsx"), registering("test-only", "x"))
        with contextlib.redirect_stdout(io.StringIO()):
            capindex.main(["--root", root, "--write",
                           "--out", os.path.join(root, "capability-index.json")])
        rc, out = run_check(root)
        check(rc == 0, f"check passes when every registration is declared (rc={rc}: {out.strip()})")

        write(os.path.join(root, MOD, "ghost.ts"), registering("ghost-cmd", "Haunt"))
        rc, out = run_check(root)
        check(rc == 1 and "ghost-cmd" in out,
              "a mod registration absent from the declared list fails the check, naming it")

        os.remove(os.path.join(root, MOD, "ghost.ts"))
        write(os.path.join(root, MOD, "pane.tsx"), registering("plan-view", "Show it all"))
        rc, out = run_check(root)
        check(rc == 1 and "plan-view" in out and "description" in out,
              "a declared description that differs from the mod's fails the check")

        write(os.path.join(root, MOD, "pane.tsx"), "export const x = 1\n")
        rc, out = run_check(root)
        check(rc == 1 and "plan-view" in out,
              "a declared command the mod no longer registers fails the check")

        write(os.path.join(root, MOD, "pane.tsx"),
              "await $.command.register({ name: NAME, description: 'd' })\n")
        rc, out = run_check(root)
        check(rc == 1 and "pane.tsx" in out,
              "a registration whose name is not a string literal fails the check")

        # A registration passed anything but an object literal can't be read at all.
        write(os.path.join(root, MOD, "pane.tsx"),
              registering("plan-view", "Show the plan") + "await $.command.register(spec)\n")
        rc, out = run_check(root)
        check(rc == 1 and "pane.tsx:" in out,
              f"a registration whose argument is not an object literal fails the check (rc={rc})")

        # A commented-out registration registers nothing.
        write(os.path.join(root, MOD, "pane.tsx"),
              "// " + registering("plan-view", "Show the plan").replace("\n", "\n// ")
              + "\n/* " + registering("plan-view", "Show the plan") + " */\n")
        rc, out = run_check(root)
        check(rc == 1 and "no mod source registers" in out,
              f"a commented-out registration does not count as registered (rc={rc})")

        # A registration in a subdirectory, or in a .js/.mjs/.jsx source, is the mod's too.
        write(os.path.join(root, MOD, "pane.tsx"), registering("plan-view", "Show the plan"))
        for rel in ("sub/extra.js", "more.mjs", "view.jsx"):
            write(os.path.join(root, MOD, rel), registering("ghost-cmd", "Haunt"))
            rc, out = run_check(root)
            check(rc == 1 and "ghost-cmd" in out and rel in out,
                  f"a registration in {rel} is seen (rc={rc})")
            os.remove(os.path.join(root, MOD, rel))
        # Comment markers inside a string are text: `'src/*.ts'` opens no comment that
        # would swallow the registration after it.
        write(os.path.join(root, MOD, "pane.tsx"),
              "const glob = 'src/*.ts', url = \"https://x.org\"\n"
              + registering("plan-view", "Show the plan") + "const end = '*/'\n")
        rc, out = run_check(root)
        check(rc == 0, f"comment markers inside strings are not comments (rc={rc}: {out.strip()})")


def registration_lexing_cases():
    """The drift check against JS/TS a comment-blanker misreads. Its property: every
    live registration is matched or fails by name and line, and a commented-out one
    never counts. Where the reading is uncertain, the check fails rather than passes."""
    good = registering("plan-view", "Show the plan")
    ghost = "$.command.register({ name: 'ghost-cmd', description: 'Haunt' })\n"

    def drift(files, declared_cmds=(("plan-view", "Show the plan"),)):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, MOD, "registered-commands.json"), declared(*declared_cmds))
            for rel, text in files.items():
                write(os.path.join(root, MOD, rel), text)
            return capindex.registration_drift(root)

    # A live call is never hidden: a regex literal holding a comment marker opens no
    # comment, before the call or on its own line.
    for label, src in (
            ("a regex literal holding /*", "const r = /src\\/*.ts/\n" + ghost + "const z = 1 /* */\n"),
            ("a regex literal holding //", "s.replace(/\\//g, ''); " + ghost),
            ("a regex class holding /", "const r = /[/]x/; " + ghost)):
        out = drift({"pane.tsx": good + src})
        check(any("ghost-cmd" in p for p in out), f"{label} hides no registration ({out})")

    # Every call shape that reaches register is read or fails, naming file and line.
    for label, src in (
            ("a generic call", "$.command.register<Spec>({ name: 'ghost-cmd', description: 'H' })\n"),
            ("a chained call", "$.command\n  .register({ name: 'ghost-cmd', description: 'H' })\n"),
            ("an optional call", "$.command.register?.({ name: 'ghost-cmd', description: 'H' })\n"),
            ("a computed member", "$.command['register']({ name: 'ghost-cmd', description: 'H' })\n"),
            ("an alias", "const r = $.command.register; r({ name: 'ghost-cmd' })\n"),
            ("a destructured register", "const { register } = $.command\n")):
        out = drift({"pane.tsx": good + src})
        check(any("pane.tsx:" in p and ("ghost-cmd" in p or "can't be checked" in p) for p in out),
              f"{label} is read or fails ({out})")

    # The object literal is read whole: a nested `})` does not cut it short, and a
    # second argument or a cast fails as such.
    out = drift({"pane.tsx": "$.command.register({ name: 'plan-view', run: () => f({b: 1}), "
                             "description: 'Show the plan' })\n"})
    check(out == [], f"a nested `}})` inside the literal does not truncate it ({out})")
    out = drift({"pane.tsx": "$.command.register({ meta: { name: 'inner' }, name: 'plan-view', "
                             "description: 'Show the plan' })\n"})
    check(out == [], f"a nested object's `name:` is not the command's ({out})")
    for label, src in (("a second argument", "{ name: 'plan-view', description: 'Show the plan' }, opts"),
                       ("a cast", "{ name: 'plan-view', description: 'Show the plan' } as Spec")):
        out = drift({"pane.tsx": f"$.command.register({src})\n"})
        check(any("pane.tsx:1:" in p and "one object literal" in p for p in out),
              f"{label} fails as such ({out})")

    # A quote that opens no string, or a nested template, never revives a commented-out
    # registration: the declared command stays unregistered.
    for label, src in (
            ("a JSX apostrophe", "const v = <p>Don't</p>\n// " + good.replace("\n", "\n// ") + "\n"),
            ("a quote in a regex", "const q = /\"/\n// $.command.register({ name: 'plan-view', "
                                   "description: 'Show the plan' })\n"),
            ("a nested template", "const t = `a${ '`' }b`\n// $.command.register({ name: "
                                  "'plan-view', description: 'Show the plan' })\n")):
        out = drift({"pane.tsx": src})
        check(any("no mod source registers" in p for p in out),
              f"{label} does not revive a commented-out registration ({out})")

    # Line numbers survive a multi-line block comment.
    head = good + "/*\n * one\n * two\n */\n"
    out = drift({"pane.tsx": head + ghost})
    want = head.count("\n") + 1
    check(any(f"pane.tsx:{want}:" in p and "ghost-cmd" in p for p in out),
          f"the line number holds after a block comment (want {want}: {out})")

    # Text inside a string is not a registration, and says so rather than misnaming it.
    out = drift({"pane.tsx": good + "throw new Error('call $.command.register(spec) first')\n"})
    check(any("string" in p for p in out) and not any("object literal" in p for p in out),
          f"a registration inside a string fails as one ({out})")

    # Which files are the mod's: doubles (.test./.spec. sources, __tests__/) and
    # dependencies are not; a symlink is refused rather than skipped or crashed on.
    out = drift({"pane.tsx": good, "pane.spec.ts": ghost, "__tests__/x.ts": ghost,
                 "node_modules/dep/index.js": ghost, "sub/a.test.ts": ghost})
    check(out == [], f"test doubles and dependencies are not the mod's sources ({out})")
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, MOD, "registered-commands.json"),
              declared(("plan-view", "Show the plan")))
        write(os.path.join(root, MOD, "pane.tsx"), good)
        os.symlink("missing.ts", os.path.join(root, MOD, "dangling.ts"))
        os.symlink(os.path.join(root, "elsewhere"), os.path.join(root, MOD, "linked"))
        out = capindex.registration_drift(root)
        check(any("dangling.ts" in p and "symlink" in p for p in out) and
              any("linked" in p and "symlink" in p for p in out),
              f"a symlinked file or directory in the mod tree fails, naming it ({out})")


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
    print("registered commands:")
    registered_command_cases()
    print("registration drift:")
    registration_drift_cases()
    print("registration lexing:")
    registration_lexing_cases()
    print("cli:")
    main_cli_cases()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
