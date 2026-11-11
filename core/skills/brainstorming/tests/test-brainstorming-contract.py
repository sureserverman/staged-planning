#!/usr/bin/env python3
"""Structure suite for the brainstorming trunk — run directly (CI convention):

    python3 core/skills/brainstorming/tests/test-brainstorming-contract.py

PROSE contract, not behavior. The trunk states its contract and no method tutorial.
What it pins:

  1. Kept: the HARD-GATE block (a design presented and approved before any handoff);
     the `decisions` skill's `relevant` grounding step; the background-work sentence
     for a delegated read; the records-home resolver call with `--for-write` and its
     0 / 3 / 2 exit handling; the `-design.md` save path and the design document's
     section list; both handoff routes and the explicit skip sentence.
  2. Gone: the 5W-1H framing, the "regardless of perceived" simplicity claim, the
     one-question-per-message rule, the per-section "does this match" check, and any
     Sources heading. (The phrases are split in the code below: the plan's gates grep the
     whole tree for them, tests included, so spelling them whole here would fail a gate
     that is right about every shipped skill.)
  3. The trunk is at most 5000 bytes.

Why: the gate is the skill's one job. A trim that drops it lets a planner start on a
design nobody approved; a trunk that keeps its tutorial costs every session its bytes.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "SKILL.md")
MAX_BYTES = 5000
# The Cursor build ships a whole-file fork of the trunk; the same contract binds it. Its
# host facts (the plugin-folder note, the check-the-command-ran block) cost up to 1000 B
# more. Absent from a built copy of this test, where only the trunk beside it is checked.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
FORKS = [(os.path.join(REPO, "hosts", "cursor", "overrides", "skills", "brainstorming",
                       "SKILL.md"), MAX_BYTES + 1000)]

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def ws(pattern):
    """Every space may be any whitespace run: the trunk may be hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def has(text, pattern):
    return re.search(ws(pattern), text, re.S) is not None


def check_trunk(path, max_bytes):
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    where = os.path.relpath(path, REPO) if path.startswith(REPO) else path
    print(f"== {where}")

    # --- 1. kept --------------------------------------------------------------------
    gate = re.search(r"<HARD-GATE>(.*?)</HARD-GATE>", text, re.S)
    body = gate.group(1) if gate else ""
    check("the HARD-GATE block is present", gate is not None, "no <HARD-GATE> block")
    check("the gate bars both handoff skills",
          "`architecting-projects`" in body and "`planning-projects`" in body,
          "the gate does not name architecting-projects and planning-projects")
    check("the gate requires a design presented and approved before handoff",
          has(body, r"presented and approved before (?:any )?handoff"),
          "no 'presented and approved before handoff' in the gate")
    check("the gate forbids, rather than permits, the handoff skills",
          has(body, r"Do NOT invoke `architecting-projects` or `planning-projects`"),
          "no 'Do NOT invoke `architecting-projects` or `planning-projects`' in the gate")

    check("grounding runs the decisions skill's relevant operation",
          has(text, r"`decisions` skill's `relevant` operation"),
          "no \"`decisions` skill's `relevant` operation\"")

    check("a delegated read waits on a background job by its own completion",
          has(text, r"wait on a background job by its own completion"),
          "no 'wait on a background job by its own completion'")
    check("a delegated read returns clean and says which",
          has(text, r"returns only after its own background work has finished or been "
                    r"stopped, and says which"),
          "no return-clean clause with 'and says which'")

    check("questions are asked only when the repo cannot answer, batched",
          has(text, r"Ask only what would change the design and the repo cannot answer")
          and has(text, r"Batch the questions in one round, with the host's question tool"),
          "the ask-only-what-you-cannot-infer or batching rule is missing")
    check("two or three alternatives are proposed with a recommendation",
          has(text, r"Propose two or three approaches") and has(text, r"name the one you recommend"),
          "no two-or-three alternatives with a recommendation")
    check("the design is presented once and approved once",
          has(text, r"Present the whole design in one message")
          and has(text, r"The user approves the design once, as a whole"),
          "the present-once / approve-once rule is missing")
    check("only an explicit yes approves; a change request is not a yes",
          has(text, r"Only an explicit yes approves the design")
          and has(text, r"A reply that asks for changes is not a yes")
          and has(text, r"Revise, present the revised design, and ask again"),
          "the explicit-yes rule is missing (a change request was taken as approval in "
          "the Stage 1 demo)")
    check("the records-home resolver is called for write",
          has(text, r"python3 (?:\$\{CLAUDE_PLUGIN_ROOT\}|<planning-plugin>)/lib/records_home\.py "
                    r"--project <repo> --for-write"),
          "no 'records_home.py --project <repo> --for-write' call")
    check("the resolver's exit 0 / 3 / 2 handling is stated",
          has(text, r"0 or 3, use the printed records home \(on 3 it is the repo's "
                    r"`docs/`, warn once\); 2, stop and show the message, creating "
                    r"nothing\."),
          "the 0 / 3 / 2 exit sentence is missing or changed")

    check("the design document saves to a -design.md path",
          has(text, r"<records home>/plans/YYYY-MM-DD-<topic>-design\.md"),
          "no '<records home>/plans/YYYY-MM-DD-<topic>-design.md'")
    sections = ["# Design: <Topic>", "## Problem", "## Alternatives considered",
                "## Architecture", "## Components", "## Data flow", "## Error handling",
                "## Testing strategy", "## Rollout / rollback", "## Risks"]
    missing = [s for s in sections if not re.search(r"^" + re.escape(s), text, re.M)]
    check("the design document's section list is present", not missing,
          f"missing: {missing}")
    check("Problem records the constraints and success criteria architecting-projects reads",
          has(text, r"`## Problem` states why, the constraints and the success criteria"),
          "no constraints-and-success-criteria line for ## Problem")

    check("route 1: a structural surface hands off to architecting-projects",
          has(text, r"This design has a structural surface, so handing off to the "
                    r"`architecting-projects` skill"),
          "no architecting-projects handoff sentence")
    check("route 2: no structural surface hands off to planning-projects",
          has(text, r"No structural surface — handing off to the `planning-projects` "
                    r"skill"),
          "no planning-projects handoff sentence")
    check("the skip of the architect is stated explicitly",
          has(text, r"\"no structural surface: straight to planning-projects\"")
          and has(text, r"Skipping the architect is never silent"),
          "the explicit skip sentence is missing")

    # --- 2. gone --------------------------------------------------------------------
    for phrase in ["5W" "1H", "regardless of " "perceived simplicity", "One question " "per message",
                   "does this match " "what you had in mind"]:
        check(f"the trunk no longer holds {phrase!r}", phrase.lower() not in text.lower(),
              "still present")
    check("the trunk has no Sources heading",
          re.search(r"^##\s+Sources\b", text, re.M) is None, "a '## Sources' heading remains")

    # --- 3. size --------------------------------------------------------------------
    check(f"{where} is at most {max_bytes} bytes", len(raw) <= max_bytes,
          f"{len(raw)} bytes")


def main():
    check_trunk(SKILL, MAX_BYTES)
    for path, limit in FORKS:
        if os.path.exists(path):
            check_trunk(path, limit)

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed:")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
