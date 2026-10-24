#!/usr/bin/env python3
"""Structure suite for the gate evaluator's brief — run directly (CI convention):

    python3 core/skills/executing-plans/tests/test-evaluator-brief-contract.py

PROSE contract, not behavior: it asserts that every executing-plans file stating what the
gate evaluator is briefed with names the PLAN goal, using the shared negation screening.
What it pins:

  1. SKILL.md and stage-gate.md brief the gate evaluator with the plan goal, the stage goal
     and the gate's pass criteria, and still never with the transcript or a summary.
  2. stage-gate.md's Blocking row covers a stage whose finished output already falls short
     of the plan goal with no later stage planned to change it; its report example and its
     "brief it with" line name the plan goal too.
  3. stage-gate.md and master-plans.md give a sub-plan's gate evaluator its master register
     Goal as well.
  4. extraction-classification.md's Step 3.5 retention marker matches the trunk sentence.
  5. Nowhere in executing-plans is the evaluator briefed on the stage goal alone.

Why: a gate reader that is not given the plan goal lets an end-goal gap survive every
stage gate, so only the close-out evaluator can find it.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.dirname(HERE)
REF = os.path.join(EP, "references")
HELPER = os.path.join(HERE, "test-gate-remediation-contract.py")

spec = importlib.util.spec_from_file_location("_gate_contract", HELPER)
_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_helper)
affirms_claim = _helper.affirms_claim

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def ws(pattern):
    """Every space may be any whitespace run: the files are hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def section(text, heading_re):
    m = re.search(heading_re, text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]


BRIEF = ws(r"briefed ONLY with the plan goal, the stage goal and the gate's pass criteria")
NEVER_TRANSCRIPT = ws(r"briefed ONLY with the plan goal, the stage goal and the gate's pass "
                      r"criteria — never the (?:implementation )?transcript or your own summary")


def main():
    sk = read(EP, "SKILL.md")
    para = section(sk, r"^### Step 3\.5")
    ev = re.search(r"\*\*Independent evaluator for non-command checks\.\*\*.*?(?=\n\n)", para, re.S)
    ev = ev.group(0) if ev else ""
    check("SKILL.md: the evaluator paragraph is present", bool(ev))
    check("SKILL.md: briefed with the plan goal, the stage goal and the gate criteria",
          affirms_claim(ev, BRIEF), "the plan goal is not in the brief, or it is negated")
    check("SKILL.md: still never the transcript or a summary",
          re.search(NEVER_TRANSCRIPT, ev) is not None, "the exclusion is gone")

    sg = read(REF, "stage-gate.md")
    ie = section(sg, r"^## Independent evaluator for non-command checks")
    check("stage-gate: the evaluator section is present", bool(ie))
    check("stage-gate: briefed with the plan goal, the stage goal and the gate criteria",
          affirms_claim(ie, BRIEF), "the plan goal is not in the brief, or it is negated")
    check("stage-gate: still never the transcript or a summary",
          re.search(NEVER_TRANSCRIPT, ie) is not None, "the exclusion is gone")
    check("stage-gate: the register Goal reaches a sub-plan's evaluator too",
          affirms_claim(ie, ws(r"a sub-plan's gate evaluator is also briefed with its master "
                               r"register Goal")),
          "the register-Goal half is absent or negated")
    check("stage-gate: gives the reason the brief carries the plan goal",
          affirms_claim(ie, ws(r"The plan goal is there so a stage gate can see a gap in the "
                               r"plan's end goal")),
          "the reason is absent or negated")
    row = re.search(r"^\| \*\*Blocking\*\* \|.*$", ie, re.M)
    row = row.group(0) if row else ""
    check("stage-gate: the Blocking row covers a stage already short of the plan goal",
          re.search(ws(r"already falls short of the plan goal"), row) is not None
          and re.search(ws(r"no later stage is planned to change it"), row) is not None,
          "the Blocking row does not cover the plan goal at a gate")
    check("stage-gate: the 'brief it with' line names the plan goal",
          re.search(ws(r"Brief it with the plan goal, the stage goal and the `\(judgment\)` "
                       r"lines only"), ie) is not None,
          "the command-check paragraph briefs with one goal only")
    check("stage-gate: the report example names the plan goal in the brief",
          re.search(r"^evaluator: .*briefed on the plan goal \+ stage goal \+ gate criteria",
                    sg, re.M) is not None,
          "the report example omits the plan goal from the brief")

    mp = read(REF, "master-plans.md")
    check("master-plans: the register Goal reaches a sub-plan's evaluator too",
          affirms_claim(mp, ws(r"a sub-plan's gate evaluator is also briefed with its master "
                               r"register Goal")),
          "absent or negated")

    ec = read(REF, "extraction-classification.md")
    check("extraction-classification: the Step 3.5 marker is the plan-goal brief",
          "| Step 3.5 — Stage gate | briefed ONLY with the plan goal |" in ec,
          "the retention marker pins a stage-goal-only sentence")
    check("extraction-classification: the marker matches the trunk",
          re.search(ws(r"briefed ONLY with the plan goal"), sk) is not None,
          "the trunk no longer carries the marker text")

    old = "ONLY with the " + "stage goal"     # split, so a repo grep for it does not match this file
    stale = []
    for root, _dirs, files in os.walk(EP):
        for f in files:
            if f.endswith((".md", ".py")):
                path = os.path.join(root, f)
                if old in read(path):
                    stale.append(os.path.relpath(path, EP))
    check("nowhere in executing-plans is the evaluator briefed on the stage goal alone", not stale,
          f"still in: {stale}")

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
