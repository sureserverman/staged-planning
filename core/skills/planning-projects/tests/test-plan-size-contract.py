#!/usr/bin/env python3
"""Structure suite for the plan-size rules — run directly (CI convention):

    python3 core/skills/planning-projects/tests/test-plan-size-contract.py

PROSE contract, not behavior. It reads the four BUILT planning-projects trunks (what each
host installs) and the reference files, and asserts each states the rule, using the shared
negation screening. What it pins:

  1. The option marked Recommended is the smallest one that meets the request as the owner
     wrote it; an option that adds scope says what it adds, and carries the mark only when
     the request asks for it — in every built trunk's Phase -1 and in owner-decisions.md's
     "How to ask", core and built.
  2. Outcomes name the person or program that uses the product; a failure line is written
     only for a failure that user can cause through the product's own interface as the plan
     changes it; a stage whose result only a later stage or the project's own tests consume
     omits Outcomes — in every built trunk's Phase 2, the checklist's Standard and Light
     lists, and the Standard and Light templates. The old "one per way it can fail" list
     is gone from them.
  3. A plan carries one `(goal)` check, in its final gate; an earlier gate repeats it only
     when that stage's own tasks can make it fail — in gate-authoring.md, the Standard
     template and the checklist's Standard list, core and built. The old "every gate from
     the first one whose artifact exists" is gone from them.

Why: the 2026-11-13 execution audit found scope growing through the planner's own
questions — the larger option marked "(Recommended)" and accepted, 6 to 36 percent of a
plan's tasks. It also found Outcomes written for every way a stage could fail, some about the
project's own test tooling: in nice-dns the costliest gate (about 100 minutes, two fix
rounds, no product defect) demoed Outcomes about how the test harness reports its failures.
And the `(goal)` check was repeated in every gate: in three cases it was a grep that became
true in the first stage and could not fail afterwards.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(os.path.dirname(SKILLS))
CORE_PP = os.path.join(SKILLS, "planning-projects")
HELPER = os.path.join(SKILLS, "executing-plans", "tests", "test-gate-remediation-contract.py")

spec = importlib.util.spec_from_file_location("_gate_contract", HELPER)
_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_helper)
affirms_claim = _helper.affirms_claim

BUILT_PP = {
    "claude": os.path.join(REPO, "plugins", "claude", "planning", "skills", "planning-projects"),
    "codex": os.path.join(REPO, "plugins", "codex", "planning", "skills", "planning-projects"),
    "cursor": os.path.join(REPO, "plugins", "cursor", "planning", "skills", "planning-projects"),
    "opencode": os.path.join(REPO, "packages", "opencode", "skills", "planning-projects"),
}

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def ws(pattern):
    """Every space may be any whitespace run: the files are hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(text, heading_re):
    m = re.search(heading_re, text, re.M)
    if not m:
        return ""
    level = len(re.match(r"#+", text[m.start():]).group(0))
    nxt = re.search(rf"^#{{1,{level}}} ", text[m.end():], re.M)
    return text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]


def mark_screened(text):
    """The label `Recommended` is the mark's name, not a hedge: the shared negation list
    holds "recommended", so the capitalised label is renamed before screening."""
    return re.sub(r"\bRecommended\b", "RECMARK", text)


SMALLEST = [
    ("the marked option is the smallest that meets the request",
     ws(r"The option marked RECMARK is the smallest one that meets the request as the owner wrote it")),
    ("a larger option says what it adds",
     ws(r"An option that adds scope says what it adds, in tasks or stages")),
    ("a larger option carries the mark only when the request asks",
     ws(r"carries the mark only when the request asks for it")),
]


def check_smallest(label, sec):
    sec = mark_screened(sec)
    for name, pat in SMALLEST:
        check(f"{label}: {name}", bool(sec) and affirms_claim(sec, pat),
              "absent or negated" if sec else "section not found")


OUTCOMES = [
    ("Outcomes name the product's user",
     ws(r"Outcomes name the person or program that uses the product")),
    ("a failure line only for a failure that user can cause",
     ws(r"failure line (?:is written )?only for a failure that user can cause through the "
        r"product's own interface as (?:this|the) plan changes it")),
    ("a stage only a later stage or the tests consume omits Outcomes",
     ws(r"(?:a )?stage whose result only a later stage or the project's own tests consume "
        r"omits (?:its )?Outcomes")),
]

OLD_OUTCOMES = re.compile(r"(?:every|each|one per|a) way it can fail|another way it can fail", re.I)


def check_outcomes(label, sec):
    for name, pat in OUTCOMES:
        check(f"{label}: {name}", bool(sec) and affirms_claim(sec, pat),
              "absent or negated" if sec else "section not found")
    old = OLD_OUTCOMES.search(sec)
    check(f"{label}: the per-way-of-failing rule is gone", not old,
          f"still reads {old.group(0)!r}" if old else "")


GOAL_ONCE = [
    ("one (goal) check, in the final gate",
     ws(r"one `\(goal\)` check, in (?:its|the plan's) final gate")),
    ("an earlier gate repeats it only where its stage can fail it",
     ws(r"(?:an )?earlier gate repeats it only when that stage's own tasks can make it fail")),
]

OLD_GOAL = re.compile(ws(r"every gate from the first one " r"whose artifact exists"), re.I)


def check_goal_once(label, text):
    for name, pat in GOAL_ONCE:
        check(f"{label}: {name}", bool(text) and affirms_claim(text, pat),
              "absent or negated" if text else "section not found")
    old = OLD_GOAL.search(text)
    check(f"{label}: the every-gate rule is gone", not old, "still there" if old else "")


def main():
    for host, pp in sorted(BUILT_PP.items()):
        trunk = read(os.path.join(pp, "SKILL.md"))
        check_smallest(f"{host} trunk Phase -1", section(trunk, r"^## Phase -1\b"))
    for label, pp in [("core", CORE_PP)] + sorted(BUILT_PP.items()):
        od = read(os.path.join(pp, "references", "owner-decisions.md"))
        check_smallest(f"{label} owner-decisions.md How to ask", section(od, r"^## How to ask\b"))

    for host, pp in sorted(BUILT_PP.items()):
        trunk = read(os.path.join(pp, "SKILL.md"))
        check_outcomes(f"{host} trunk Phase 2", section(trunk, r"^## Phase 2 — Stage Breakdown"))
    for label, pp in [("core", CORE_PP)] + sorted(BUILT_PP.items()):
        ref = os.path.join(pp, "references")
        ac = read(os.path.join(ref, "authoring-checklist.md"))
        check_outcomes(f"{label} checklist Standard",
                       section(ac, r"^## Checklist — Standard plans"))
        check_outcomes(f"{label} checklist Light", section(ac, r"^## Checklist — Light plans"))
        check_outcomes(f"{label} Standard template", read(os.path.join(ref, "plan-document-template.md")))
        check_outcomes(f"{label} Light template", read(os.path.join(ref, "light-plan-format.md")))
        check_goal_once(f"{label} gate-authoring.md", read(os.path.join(ref, "gate-authoring.md")))
        check_goal_once(f"{label} Standard template",
                        read(os.path.join(ref, "plan-document-template.md")))
        check_goal_once(f"{label} checklist Standard",
                        section(ac, r"^## Checklist — Standard plans"))

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} check(s)")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
