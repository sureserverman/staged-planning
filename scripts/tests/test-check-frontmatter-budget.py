#!/usr/bin/env python3
"""Fixture tests for scripts/check-frontmatter-budget.py.

Builds a synthetic plugin tree in a temp dir and asserts the scanner's
contract: budget comparison, folded-YAML parsing, missing frontmatter,
tests/fixtures exclusion, allowlist handling, and exit codes. Stdlib only.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-frontmatter-budget.py")

spec = importlib.util.spec_from_file_location("budget", SCRIPT)
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)

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


def fm(desc, folded=False):
    if folded:
        body = "description: >\n  " + desc.replace(" ", " ")
        return f"---\n{body}\nother: x\n---\n\n# body\n"
    return f"---\ndescription: {desc}\nother: x\n---\n\n# body\n"


def extract_cases():
    # Plain single-line
    check(budget.extract_description(fm("hello world")) == "hello world",
          "plain single-line description parsed")
    # Folded block collapses to one line
    long = "a" * 50 + " " + "b" * 50
    got = budget.extract_description(fm(long, folded=True))
    check(got == long, "folded (>) block collapsed to single line")
    # Missing frontmatter
    check(budget.extract_description("# just a body\n") is None,
          "no frontmatter -> None")
    # Frontmatter without description
    check(budget.extract_description("---\nname: x\n---\n") is None,
          "frontmatter without description -> None")


def scan_cases():
    with tempfile.TemporaryDirectory() as root:
        # under budget
        write(os.path.join(root, "p1/skills/a/SKILL.md"), fm("x" * 100))
        # exactly at budget (300) -> not a violation
        write(os.path.join(root, "p1/skills/b/SKILL.md"), fm("y" * 300))
        # over budget skill
        write(os.path.join(root, "p1/skills/c/SKILL.md"), fm("z" * 301))
        # over budget agent
        write(os.path.join(root, "p2/agents/agt.md"), fm("w" * 400))
        # over budget command
        write(os.path.join(root, "p2/commands/cmd.md"), fm("v" * 350))
        # excluded: under tests/
        write(os.path.join(root, "p2/skills/x/tests/SKILL.md"), fm("t" * 500))
        # excluded: under fixtures/
        write(os.path.join(root, "p2/skills/x/fixtures/deep/SKILL.md"), fm("f" * 500))

        allow = os.path.join(root, "allow.txt")
        with open(allow, "w") as fh:
            fh.write("# reasons\np2/commands/cmd.md  # legacy\n")

        violations, allowed, invalid = budget.scan(root, 300, budget.load_allowlist(allow))
        vpaths = {v["path"] for v in violations}
        apaths = {a["path"] for a in allowed}

        check("p1/skills/b/SKILL.md" not in vpaths, "exactly-300 is not a violation")
        check("p1/skills/a/SKILL.md" not in vpaths, "under-budget is not a violation")
        check("p1/skills/c/SKILL.md" in vpaths, "over-budget skill flagged")
        check("p2/agents/agt.md" in vpaths, "over-budget agent flagged")
        check(not any("tests" in p for p in vpaths), "tests/ path excluded")
        check(not any("fixtures" in p for p in vpaths), "fixtures/ path excluded")
        check("p2/commands/cmd.md" in apaths, "allowlisted path reported as allowed")
        check("p2/commands/cmd.md" not in vpaths, "allowlisted path not a violation")
        check(all("kind" in v and "plugin" in v and "chars" in v for v in violations),
              "violation records carry kind/plugin/chars")
        vc = next(v for v in violations if v["path"] == "p1/skills/c/SKILL.md")
        check(vc["chars"] == 301 and vc["plugin"] == "p1" and vc["kind"] == "skill",
              "violation record fields correct")


def invalid_yaml_cases():
    with tempfile.TemporaryDirectory() as root:
        # Unquoted plain scalar containing ": " — invalid YAML, the breakage a
        # shortened description most easily carries (`... Triggers: "x"`).
        write(os.path.join(root, "p/skills/bad/SKILL.md"),
              '---\nname: bad\ndescription: short desc. Triggers: "x", "y"\n---\n\n# b\n')
        # Same content but single-quoted — valid, must NOT be flagged.
        write(os.path.join(root, "p/skills/good/SKILL.md"),
              "---\nname: good\ndescription: 'short desc. Triggers: \"x\", \"y\"'\n---\n\n# g\n")
        violations, allowed, invalid = budget.scan(root, 300, set())
        ipaths = {r["path"] for r in invalid}
        check("p/skills/bad/SKILL.md" in ipaths, "unquoted ': ' description flagged invalid")
        check("p/skills/good/SKILL.md" not in ipaths, "single-quoted ': ' description is valid")
        rc = budget.main(["--root", root, "--max", "300", "--allowlist", os.path.join(root, "none.txt")])
        check(rc == 1, "invalid YAML alone forces exit 1")


def summary_cases():
    with tempfile.TemporaryDirectory() as root:
        # injected skill
        write(os.path.join(root, "p1/skills/a/SKILL.md"), fm("x" * 100))
        # dispatch-only skill (disable-model-invocation: true) — not injected
        write(os.path.join(root, "p1/skills/b/SKILL.md"),
              "---\nname: b\ndescription: " + "y" * 40 +
              "\ndisable-model-invocation: true\n---\n\n# b\n")
        # injected agent in another plugin
        write(os.path.join(root, "p2/agents/agt.md"), fm("z" * 50))
        # excluded fixture — must not count
        write(os.path.join(root, "p2/skills/x/fixtures/SKILL.md"), fm("f" * 500))

        # parser — authored convention is true/false only, and the answer must
        # be independent of PyYAML availability (regex-only, no divergence).
        def dmi(val):
            return f"---\nname: b\ndescription: d\ndisable-model-invocation: {val}\n---\n"
        check(budget.disable_model_invocation(dmi("true")) is True,
              "disable-model-invocation: true detected")
        check(budget.disable_model_invocation(dmi("True")) is True,
              "capitalized True detected (case-insensitive)")
        check(budget.disable_model_invocation(dmi("'true'")) is True,
              "quoted 'true' detected")
        check(budget.disable_model_invocation(dmi("false")) is False,
              "false -> not dispatch-only")
        check(budget.disable_model_invocation(dmi("yes")) is False,
              "YAML-1.1 'yes' NOT treated as true (outside authored convention)")
        check(budget.disable_model_invocation(fm("plain")) is False,
              "absent flag -> not dispatch-only")
        saved = budget._yaml
        try:
            budget._yaml = None
            check(budget.disable_model_invocation(dmi("true")) is True,
                  "answer identical with PyYAML absent (no env divergence)")
        finally:
            budget._yaml = saved

        per_plugin, totals = budget.summarize(root)
        check(per_plugin["p1"]["injected_chars"] == 100
              and per_plugin["p1"]["injected_count"] == 1,
              "injected skill counted in injected bucket")
        check(per_plugin["p1"]["dispatch_chars"] == 40
              and per_plugin["p1"]["dispatch_count"] == 1,
              "flagged skill lands in dispatch-only bucket, not injected")
        check(per_plugin["p2"]["injected_chars"] == 50,
              "agent counted in its plugin's injected bucket")
        check("fixtures" not in str(per_plugin) and per_plugin["p2"]["injected_count"] == 1,
              "fixture path excluded from summary")
        check(totals["injected_chars"] == 150 and totals["dispatch_chars"] == 40,
              "grand totals sum injected and dispatch-only separately")


def exit_code_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/a/SKILL.md"), fm("x" * 100))
        rc = budget.main(["--root", root, "--max", "300", "--allowlist", os.path.join(root, "none.txt")])
        check(rc == 0, "clean tree exits 0")
        write(os.path.join(root, "p/skills/b/SKILL.md"), fm("x" * 500))
        rc = budget.main(["--root", root, "--max", "300", "--allowlist", os.path.join(root, "none.txt")])
        check(rc == 1, "tree with violation exits 1")


if __name__ == "__main__":
    print("extract_description:")
    extract_cases()
    print("scan:")
    scan_cases()
    print("invalid yaml:")
    invalid_yaml_cases()
    print("summary:")
    summary_cases()
    print("exit codes:")
    exit_code_cases()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
