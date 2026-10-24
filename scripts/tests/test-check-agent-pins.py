#!/usr/bin/env python3
"""Fixture tests for scripts/check-agent-pins.py.

The load-bearing cases are the ones proving the sweep REJECTS. A pin check that
only ever passes certifies that every agent carries a deliberate cost pin while
a new one quietly inherits the session's, which is the decay this validator
exists to stop.

The other case worth pinning is that HIGH-PIN and BAD-VALUE stay distinguishable.
A gate regex like `^effort: *\\(low\\|medium\\|high\\)$` cannot express the valid
`xhigh`, so a correct pin fails as though it were malformed. A policy finding
must be arguable; a syntax finding must not be.

Stdlib only.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-agent-pins.py")

spec = importlib.util.spec_from_file_location("pins", SCRIPT)
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)

FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def agent(model="sonnet", effort="medium", fm=True):
    body = "\n# Agent\n\nBody text.\n"
    if not fm:
        return body
    lines = ["---", "name: a", "description: d"]
    if model:
        lines.append(f"model: {model}")
    if effort:
        lines.append(f"effort: {effort}")
    lines.append("---")
    return "\n".join(lines) + body


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def run(files):
    with tempfile.TemporaryDirectory() as root:
        for rel, text in files.items():
            write(root, rel, text)
        return [p for rel in pins.agent_files(root)
                for p in pins.check_file(root, rel)]


def cases():
    check(run({"p/agents/a.md": agent()}) == [], "a fully pinned agent passes")

    p = run({"p/agents/a.md": agent(effort=None)})
    check(any("MISSING-EFFORT" in x for x in p), "an unpinned effort is caught")

    p = run({"p/agents/a.md": agent(model=None)})
    check(any("MISSING-MODEL" in x for x in p), "an unpinned model is caught")

    p = run({"p/agents/a.md": agent(effort="lo")})
    check(any("BAD-VALUE" in x for x in p),
          "a typo'd effort is BAD-VALUE, not silently inherited")

    # The distinction a plain value regex cannot make.
    p = run({"p/agents/a.md": agent(effort="xhigh")})
    check(any("HIGH-PIN" in x for x in p) and not any("BAD-VALUE" in x for x in p),
          "`xhigh` is a POLICY finding (HIGH-PIN), never a syntax one")
    check(any("revisit" in x or "POLICY_MAX" in x for x in p),
          "...and the message says how to override it deliberately")

    p = run({"p/agents/a.md": agent(effort="high")})
    check(any("HIGH-PIN" in x for x in p), "`high` exceeds the policy ceiling too")

    check(run({"p/agents/a.md": agent(model="claude-opus-4-1-20250805")}) == [],
          "a full model id is accepted, not just the short names")

    p = run({"p/agents/a.md": agent(fm=False)})
    check(any("NO-FRONTMATTER" in x for x in p), "a file with no frontmatter is caught")

    # A host whose agent files take no model or effort field gets the inverse rule.
    for h in ("cursor", "opencode"):
        bare = "---\nname: a\ndescription: d\n---\nbody\n"
        check(run({f"hosts/{h}/overrides/agents/a.md": bare}) == [],
              f"a {h} agent with no pins passes")
        p = run({f"hosts/{h}/overrides/agents/a.md": agent()})
        check(any("HOST-PIN" in x for x in p) and not any("MISSING" in x for x in p),
              f"a {h} agent carrying a pin is HOST-PIN")

    # Population rules: READMEs and test data are not agents.
    with tempfile.TemporaryDirectory() as root:
        write(root, "p/agents/README.md", "# not an agent\n")
        write(root, "p/agents/tests/fixture.md", agent(effort=None))
        write(root, "p/agents/real.md", agent())
        found = pins.agent_files(root)
    check(found == ["p/agents/real.md"],
          "README.md and tests/ fixtures are excluded from the population")


def real_tree():
    check(pins.main([]) == 0, "every shipped agent is pinned within policy")
    files = pins.agent_files(pins.REPO_ROOT)
    # >= not ==: a correctly pinned new agent must not redden the suite. The
    # floor sits at or below the shipped count.
    # check-agent-pins.py carries the policy; this only guards against the sweep
    # silently finding nothing, which would let main() report a pass over zero.
    check(len(files) >= 2,
          f"the sweep sees the shipped agents and is not empty (saw {len(files)})")
    check(not any(f.replace(os.sep, "/").startswith(("plugins/", "packages/")) for f in files),
          f"the sweep reads the sources, never the generated copies ({files})")


if __name__ == "__main__":
    print("check-agent-pins fixtures:")
    cases()
    print("real tree:")
    real_tree()
    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("OK")
