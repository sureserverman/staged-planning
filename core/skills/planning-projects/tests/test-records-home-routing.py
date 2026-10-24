#!/usr/bin/env python3
"""Every record-writing skill routes through lib/records_home.py, and says to stop on exit 2.

A skill that resolved the records location in its own prose would be a second
definition of "where records live" and of "reachable", and prose is the copy that
drifts: the defect this pins is a skill that branches on "nothing configured" alone and
so, against a configured but unreachable store, creates folders where it should
stop. What is decidable is that each skill NAMES the one resolver and carries the
stop instruction for its exit 2; whether a paragraph resolves correctly is not.

Stdlib only.
"""
import re
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
WRITERS = ["planning-projects", "architecting-projects", "brainstorming", "backlog",
           "decisions", "project-maturity"]
RESOLVER = "lib/records_home.py"
# The stop rule is anchored to an exit marker: a bare "2 … stop" would also match
# "≤ ~2 tasks … then stop" and "Fewer than 2 candidates survive: stop", so a skill that
# lost its exit-2 rule would still pass. A `2` counts only as `Exit 2`, `**2**`, `` `2` ``,
# `; 2,`, or a `2 —` / `2:` that no word stands before ("Stage 2:" does not count),
# followed within 200 characters of the same paragraph by "stop".
EXIT_2 = (r"(?:\bexit\s+(?:code\s+)?2\b|\*\*2\*\*|`2`|;\s*2,"
          r"|(?<![\w.~-])(?<!\w )2(?:\s*—|:))")
STOP_ON_2 = re.compile(EXIT_2 + r"(?:(?!\n[ \t]*\n).){0,200}?\bstop\b", re.I | re.S)
# Pinned in both directions, so the anchor cannot drift back into matching any "2".
MUST_MATCH = [
    "**Exit 2:** stop and show the message.",
    "0 or 3, use the printed home; 2, stop and show the message, creating nothing.",
    "   - **2** — a records resolver is configured but cannot reach its storage. **Stop and",
    "3. **Exit 2** means a configured records home could not be read. Stop and report it;",
]
MUST_NOT_MATCH = [
    "Stage 2 of the plan runs the tests, and then you stop.",
    "### Stage 2: review\nRun the review, then stop.",
    "Stage 2 — wrap up, then stop.",
    "- **Fewer than 2 evidenced candidates survive: stop.** Tell the user",
    "| **Direct** | ≤ ~2 tasks, one session | then stop — do not run Phases 0–5. |",
    "On exit 2 show the message.\n\nA later paragraph says stop.",
    "exit 20 is odd; stop.",
]
FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def main():
    print("the stop-rule pattern itself")
    for text in MUST_MATCH:
        check(bool(STOP_ON_2.search(text)), f"matches {text[:60]!r}")
    for text in MUST_NOT_MATCH:
        check(not STOP_ON_2.search(text), f"does not match {text[:60]!r}")
    print("the record-writing skills")
    for name in WRITERS:
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        check(RESOLVER in text, f"{name} routes through {RESOLVER}")
        check(bool(STOP_ON_2.search(text)), f"{name} says to stop on exit 2")
    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
