#!/usr/bin/env python3
"""Structure suite for the `(goal)` gate-check rule — run directly (CI convention):

    python3 core/skills/planning-projects/tests/test-goal-check-contract.py

PROSE contract, not behavior: it asserts that every planning-projects file carrying a part
of the rule states that part, using the shared negation screening. What it pins:

  1. gate-authoring.md owns the rule: the goal check sweeps the WHOLE artifact, never a
     subset by category; it sits in every gate from the first whose artifact exists; it is
     cheap; `(judgment)` is allowed on it only where no command decides the goal; and the
     reason for the first-gate position is stated.
  2. The three templates (Standard, master register entry, Light) carry a `(goal)` line in
     their gate blocks, and master-plan-format.md says the sub-plan's own gates carry one too.
  3. authoring-checklist.md asks for zero GOAL-CHECK-MISSING on Standard, master and Light
     plans, and the Light "goal-level end-to-end check" item is gone — replaced, not doubled.
  4. set-valued-checks.md names the filtered-subset shape and `(scoped)` as its answer.
  5. SKILL.md's validator checklist line names GOAL-CHECK-MISSING.

Why: a goal that a stage's checks only partly cover passes every gate. A sweep behind an
awk field filter reads one category of a table's rows only, and a row of another category
that lacks the property surfaces only at the first reader of the plan goal, the close-out
evaluator.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
PP = os.path.join(SKILLS, "planning-projects")
REF = os.path.join(PP, "references")
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


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def section(text, heading_re):
    m = re.search(heading_re, text, re.M)
    if not m:
        return ""
    level = len(re.match(r"#+", text[m.start():]).group(0))
    nxt = re.search(rf"^#{{1,{level}}} ", text[m.end():], re.M)
    return text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]


def gate_blocks(text):
    """Every gate block's checkbox lines: under a `### … Gate` heading or a `**Gate:**`."""
    out = []
    for m in re.finditer(r"^(?:#{2,4}\s+(?:Stage\s+\S+\s+)?Gates?\b.*|\*\*Gates?:\*\*)\s*$",
                         text, re.M):
        seg = text[m.end():]
        end = re.search(r"^(?:#{1,4} |\*\*Gates?:\*\*|```)", seg, re.M)
        out.append(seg[: end.start()] if end else seg)
    return out


def main():
    ga = read(REF, "gate-authoring.md")
    sec = section(ga, r"^## The plan's goal is a check from the first gate")
    check("gate-authoring: the (goal) section is present", bool(sec))
    check("gate-authoring: every plan format and master entry carries a (goal) check",
          affirms_claim(sec, ws(r"Every Standard plan, Light plan and master register entry "
                                r"carries at least one gate check marked `\(goal\)`")),
          "the obligation is absent or negated")
    check("gate-authoring: the goal check sweeps the whole artifact",
          affirms_claim(sec, ws(r"The goal check sweeps the whole artifact")),
          "whole-artifact scope is absent or negated")
    check("gate-authoring: never a subset by category",
          re.search(ws(r"never a subset by category"), sec) is not None,
          "the subset prohibition is absent")
    check("gate-authoring: it sits in every gate from the first one whose artifact exists",
          affirms_claim(sec, ws(r"It sits in every gate from the first one whose artifact exists")),
          "the rule's position is absent or negated")
    check("gate-authoring: it must be cheap",
          affirms_claim(sec, ws(r"It must be cheap")), "the cost bound is absent or negated")
    check("gate-authoring: (judgment) only where no command can decide the goal",
          re.search(ws(r"`\(judgment\)` is allowed on it only where no command can decide the goal"),
                    sec) is not None,
          "the (judgment) bound is absent")
    check("gate-authoring: a new plan is presented with zero GOAL-CHECK-MISSING",
          affirms_claim(sec, ws(r"A \*\*new\*\* plan is presented with zero GOAL-CHECK-MISSING")),
          "the new-plan bar is absent or negated")
    check("gate-authoring: states why the goal check sits from the first gate",
          re.search(ws(r"Raising the remediation budget buys repair attempts, not earlier "
                       r"detection"), sec) is not None
          and "$4 ~ /public/" in sec,
          "the reason (filter, budget) is not stated")

    check("gate-authoring: says the validator checks presence, not placement",
          # a stated limit carries its own "not", so it is pinned by presence, like the
          # subset prohibition above
          re.search(ws(r"It checks presence, not placement: a plan whose one `\(goal\)` check "
                       r"sits in its final gate reports zero"), sec) is not None,
          "the validator's limit is unstated, so its zero reads as proof of placement")
    check("gate-authoring: the gap surfaces only at the first reader of the plan goal",
          re.search(ws(r"surfaces only at the first reader given the plan goal"), sec)
          is not None,
          "where an unchecked goal gap is found is unstated")

    tpl = read(REF, "plan-document-template.md")
    tblocks = gate_blocks(tpl)
    check("plan-document-template: every gate block carries a (goal) line",
          len(tblocks) >= 2 and all("**(goal)**" in b for b in tblocks),
          f"{sum('**(goal)**' not in b for b in tblocks)} of {len(tblocks)} gate block(s) lack one")

    mpf = read(REF, "master-plan-format.md")
    blocks = gate_blocks(mpf)
    check("master-plan-format: every register **Gate:** block in the template carries (goal)",
          bool(blocks) and all("**(goal)**" in b for b in blocks
                               if re.search(r"^- \[ \]", b, re.M)),
          "a template register entry's Gate block has no (goal) line")
    check("master-plan-format: the sub-plan's own gates carry one too",
          affirms_claim(mpf, ws(r"the sub-plan's own gates carry a `\(goal\)` check")),
          "the sub-plan half of the rule is absent or negated")

    lpf = read(REF, "light-plan-format.md")
    check("light-plan-format: the gate template carries a (goal) line",
          any("**(goal)**" in b for b in gate_blocks(lpf)), "no (goal) line in the gate template")
    check("light-plan-format: the old 'goal proven end-to-end' placeholder is replaced",
          "the plan's goal proven end-to-end]" not in lpf, "the old placeholder survives")

    ac = read(REF, "authoring-checklist.md")
    std = section(ac, r"^## Checklist — Standard plans")
    mas = section(ac, r"^## Additionally, for a decomposed project")
    lig = section(ac, r"^## Checklist — Light plans")
    for name, part in (("Standard", std), ("master", mas)):
        check(f"authoring-checklist: the {name} item says placement is not validator-checked",
              re.search(r"^- \[ \] .*(?:GOAL-CHECK-MISSING.*placement|placement.*GOAL-CHECK-MISSING)",
                        part, re.M) is not None
              and re.search(ws(r"checks presence, not placement"), part) is not None,
              f"the {name} item offers the validator as proof of placement")
    for name, part in (("Standard", std), ("master", mas), ("Light", lig)):
        check(f"authoring-checklist: the {name} list asks for zero GOAL-CHECK-MISSING",
              re.search(r"^- \[ \] .*zero GOAL-CHECK-MISSING", part, re.M) is not None,
              f"no {name} item")
    check("authoring-checklist: the Light 'goal-level end-to-end check' item is gone",
          "goal-level end-to-end check" not in ac, "the replaced item survives beside the new one")

    svc = read(REF, "set-valued-checks.md")
    fs = section(svc, r"^### The sixth error")
    check("set-valued-checks: the filtered-subset section is present", bool(fs))
    check("set-valued-checks: names FILTERED-SUBSET and (scoped) as its answer",
          "FILTERED-SUBSET" in fs and affirms_claim(fs, ws(r"`\(scoped\)` is the answer")),
          "the finding or its answer is absent or negated")

    sk = read(PP, "SKILL.md")
    check("SKILL.md: the validator checklist line names GOAL-CHECK-MISSING",
          re.search(r"^- \[ \] .*validate-gate-checks\.py.*GOAL-CHECK-MISSING", sk, re.M)
          is not None, "the trunk checklist does not name it")

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
