#!/usr/bin/env python3
"""Contract suite for agents/claim-verifier.md — run directly (repo convention):

    python3 core/skills/executing-plans/tests/test-agent-contract.py

The verifier is judgment, so no suite can grade it. What a suite CAN pin is the
contract that makes it a verifier rather than a second executor: it can run the
tool (it holds Bash, unlike the read-only reviewer), it reaches the tool through a
plugin-rooted path, and its instructions carry the rules each kind of fake proof
breaks.
"""
import re
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[3] / "agents" / "claim-verifier.md"
passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok    {msg}")
    else:
        failed += 1
        print(f"  FAIL  {msg}")


print("agents/claim-verifier.md — the contract that makes it a verifier")
text = AGENT.read_text() if AGENT.is_file() else ""
check(bool(text), f"{AGENT.name} exists")
m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
front = m.group(1) if m else ""
check(re.search(r"^name:\s*claim-verifier\s*$", front, re.M) is not None,
      "frontmatter name is claim-verifier")
check(re.search(r"^description:\s*\S", front, re.M) is not None,
      "frontmatter has a description, so the agent can be chosen by it")
tools = re.search(r"^tools:\s*(.*)$", front, re.M)
check(tools is not None and re.search(r"\bBash\b(?!\()", tools.group(1)) is not None,
      "holds unrestricted Bash — it must run builds, tests and prove-claim.py")
body = text[m.end():] if m else text
check("${CLAUDE_PLUGIN_ROOT}/skills/executing-plans/scripts/prove-claim.py" in body,
      "reaches prove-claim.py by a plugin-rooted path, not a host install path")
# The reference-resolution block names the plugin cache root as its fallback; outside
# it, the agent names no install path.
outside = re.sub(r"<!-- reference-resolution-contract -->.*?<!-- /reference-resolution-contract -->",
                 "", body, flags=re.S)
check("~/." not in outside, "names no host install path outside the reference-resolution block")
for needle, why in [
    ("prove-claim.py claim", "proves claims with the tool, not by saying so"),
    ("prove-claim.py req", "checks requirements with the tool"),
    ("(red if", "performs the plan's named break"),
    ("Never reuse one break", "does not let one break prove claims it cannot tell apart"),
    ("presence first", "an absence claim's test must first show the thing present"),
    ("never the test itself", "breaks the code, not the test"),
    ("Do not fix anything", "a verifier does not repair what it is verifying"),
    ("clean context", "independent of the executor's narrative"),
    ("copied exactly", "runs the plan's Test: command, not one it chose"),
    ("Exit 3 means stop", "stops when the tool reports the tree is not as it was"),
    ("the tool cannot judge that, so you must", "owns the covered-by judgment the tool cannot make"),
]:
    check(needle in body, f"instructs: {why}")
# Claude Code asks before (or, headless, denies) every write under the repo's .claude/,
# and a literal /tmp path can leave the run, so the patches go in the run's TMPDIR.
check('--break "${TMPDIR:-/tmp}/break-K.patch"' in body and '--break "${TMPDIR:-/tmp}/req-K.patch"' in body,
      "saves claim and requirement breaks in ${TMPDIR:-/tmp}")
check(".claude/break" not in body and ".claude/req" not in body,
      "never sends a break patch to the repo's .claude/, a protected path on Claude Code")
print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
