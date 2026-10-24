#!/usr/bin/env python3
"""Structure suite for the gate-heuristic rule — run directly (CI convention):

    python3 core/skills/planning-projects/tests/test-gate-heuristic-contract.py

PROSE contract, not behavior: it asserts that gate-authoring.md states the rule an
author of one of this plugin's own checks follows, using the shared negation screening.
What it pins:

  1. A heuristic wired into a gate ships with BOTH a severity axis (blocking vs
     advisory) and a trigger rate measured over a real corpus, stated in its source with
     the corpus and the date.
  2. The blocking criterion is stated, not left to taste: a blocking finding is one
     whose measured hits were all true defects.
  3. A check too noisy to leave on is a defect in the check — never recorded as a
     residual of the plans it flags.
  4. The measurement it rests on is cited: 31.4% -> 12.8% over the same corpus.

The measurement: a flat-vocabulary void detector fires on 31.4% of a corpus of 188 plans.
At that rate a check gets waived, and the waiver is written as a note beside a green
gate — the artifact the check exists to abolish. Split into two tiers, the same detector
fires on 12.8% of the same corpus, a rate a check can stay on at.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
GATE_AUTHORING = os.path.join(SKILLS, "planning-projects", "references", "gate-authoring.md")
HELPER = os.path.join(SKILLS, "executing-plans", "tests", "test-gate-remediation-contract.py")

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
    """Every space may be any whitespace run: the references are hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def main():
    with open(GATE_AUTHORING, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^## A gate heuristic ships with a severity axis and a measured trigger rate",
                  text, re.M)
    sec = ""
    if m:
        nxt = re.search(r"^## ", text[m.end():], re.M)
        sec = text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]
    check("gate-authoring: the heuristic section is present", bool(sec))

    # The axis's values are pinned by presence: "advisory" is itself a word the shared
    # negation screen reads as a softener, so it cannot sit in a screened clause.
    check("heuristic: ships with a severity axis and a trigger rate",
          affirms_claim(sec, ws(r"ships with a severity axis and a trigger rate")),
          "the severity-axis / trigger-rate requirement is absent or negated")
    check("heuristic: the axis has the two values blocking and advisory",
          re.search(ws(r"The axis has two values, blocking and advisory"), sec) is not None,
          "the axis's values are unstated")
    check("heuristic: the trigger rate is measured over a real corpus",
          affirms_claim(sec, ws(r"The trigger rate is measured over a real corpus")),
          "the measured-trigger-rate requirement is absent or negated")
    check("heuristic: the rate is stated in the check's source with corpus and date",
          affirms_claim(sec, ws(r"stated in its source with the corpus and the date")),
          "where the measurement is recorded is unspecified")
    check("heuristic: the blocking criterion is stated",
          affirms_claim(sec, ws(r"A blocking finding is one whose measured hits were all true defects")),
          "blocking is left to taste")
    check("heuristic: an advisory finding never exits 1 and never fails a gate",
          re.search(ws(r"never exits 1 and never fails a gate"), sec) is not None
          and re.search(ws(r"changes no exit code"), sec) is None,
          "the advisory definition misstates the exit code (plan-flip-audit exits 4)")
    check("heuristic: blocking needs at least one measured hit",
          re.search(ws(r"at least one hit"), sec) is not None,
          "an unmeasured (n=0) check could be called blocking")
    check("heuristic: a too-noisy check is a defect in the check",
          affirms_claim(sec, ws(r"A check too noisy to leave on is a defect in the check")),
          "the defect-in-the-check clause is absent or negated")
    check("heuristic: cites the 31.4% -> 12.8% measurement",
          "31.4%" in sec and "12.8%" in sec,
          "the measurement the rule rests on is not cited")

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
