#!/usr/bin/env python3
"""Structure suite for the proof-by-tool contract — run directly (CI convention):
    python3 core/skills/executing-plans/tests/test-proof-contract.py

A PROSE contract, not behavior. It asserts that the skill text routes a task's
proof through `prove-claim.py` and positions the record audit at the stage gate.
It cannot verify that an executor obeys either — stated plainly, because a
structure suite that implies behavioral coverage is the falsehood class
`honest-gates` exists to catch. The tools' behavior is pinned by their own
suites (test-prove-claim.py, test-plan-flip-audit.py) and the battery.

Every prose requirement is pinned with the shared clause screening
(test-gate-remediation-contract.py's `affirms_claim`), so a sentence that
names the tool only to opt out of it ("you need not run prove-claim.py claim")
does not satisfy the check.

What it pins in executing-plans:
  1. Rule 4a records the proof with `prove-claim.py claim`, for the first claim and
     every claim marked `(red if …)`, and stages `git add proof/` with the commit.
  2. Rule 4a does not ask for a hand-written mutation sentence.
  3. Rule 4a routes a requirement through `prove-claim.py req` or
     `prove-claim.py deviation`, and the device-only case to a deviation.
  4. Step 3.5 runs `plan-flip-audit.py … --repo` at every stage gate, and a
     blocking finding fails the gate.

What it pins in the two skills that must say the same:
  5. dispatching-parallel-agents' prompt template tells the dispatched task to
     run `prove-claim.py claim` and `git add proof/` before it commits — a
     dispatched task that may hand-write its proof is the gap rule 4a closes for
     inline tasks.
  6. honest-gates § *A test does not exist until its mutant dies* records the
     mutant's proof with `prove-claim.py`, and its device-only line is a
     deviation; neither skill asks for a hand-written sentence.
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
EP = SKILLS / "executing-plans" / "SKILL.md"
DPA = SKILLS / "dispatching-parallel-agents" / "SKILL.md"
HG = SKILLS / "honest-gates" / "SKILL.md"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "_gate_contract", HERE / "test-gate-remediation-contract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_helper = _load_helper()
affirms_claim = _helper.affirms_claim
affirms_predicate = _helper.affirms_predicate
FAILED = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def flat(s):
    return re.sub(r"\s+", " ", s)


def section(text, start, end, label):
    m = re.search(start, text)
    if not m:
        check(f"{label}: section start found", False, start)
        return ""
    e = re.search(end, text[m.end():])
    if not e:
        check(f"{label}: section end found", False, end)
        return ""
    return flat(text[m.start(): m.end() + e.start()])


# A hand-written proof line in any of its phrasings — a `mutation:` field, or
# "record/name the mutation and (the) count" — not only the two verbatim sentences.
HAND_WRITTEN = re.compile(r"mutation:|mutation,? and (?:the )?count|count in the commit", re.I)


def main():
    print("executing-plans — rule 4a and the stage gate use the proof tools:")
    ep = EP.read_text()
    r4a = section(ep, r"4a\. \*\*Prove it", r"\n5\. \*\*Flip the task", "rule 4a")
    check("rule 4a records the proof with `prove-claim.py claim`",
          affirms_claim(r4a, r"prove-claim\.py claim"))
    check("rule 4a names the claim set: the first claim and each `(red if …)` claim",
          affirms_claim(r4a, r"first claim") and affirms_claim(r4a, r"each claim marked `\(red if"))
    check("rule 4a: the work is staged before the tool runs",
          affirms_claim(r4a, r"work staged"))
    # The patch goes in the run's TMPDIR: Claude Code asks before (or, headless, denies)
    # every write under the repo's `.claude/`, and a literal /tmp path can leave the run.
    # Written by a shell redirect, because a file tool cannot expand $TMPDIR: a clean-machine
    # run (2026-10-25) saved the patch with the Write tool to a literal /tmp path.
    check("rule 4a: `--test` is a command from the task's `Test:`; a shell redirect writes the "
          "break patch, and every scratch file, into \"$TMPDIR\", never a literal /tmp/ path",
          affirms_claim(r4a, r"`--test` a command from the task's `Test:`")
          and affirms_predicate(r4a, r"as `--break`", r"a shell redirect writes into `\"\$TMPDIR\"`")
          and affirms_predicate(r4a, r"scratch too, never a literal", r"`/tmp/`")
          and ".claude/" not in r4a)
    check("rule 4a stages the records with the task commit (`git add proof/`)",
          affirms_claim(r4a, r"git add proof/"))
    check("rule 4a does not ask for a hand-written mutation sentence",
          not HAND_WRITTEN.search(r4a))
    check("rule 4a routes a checkable requirement to `prove-claim.py req`",
          affirms_claim(r4a, r"prove-claim\.py req"))
    check("rule 4a routes an uncheckable requirement to `prove-claim.py deviation`",
          affirms_claim(r4a, r"else `prove-claim\.py deviation`"))
    # Finding 9 is advisory, so a requirement record is optional — rule 4a must not read
    # as a per-sentence mandate whose cost nothing argues.
    check("rule 4a says a requirement MAY be recorded and finding 9 only reports the rest",
          affirms_claim(r4a, r"requirement may be recorded")
          and affirms_claim(r4a, r"finding 9 only reports"))
    check("rule 4a routes the device-only claim to `prove-claim.py deviation --claim`",
          affirms_claim(r4a, r"prove-claim\.py deviation --claim"))
    gate = section(ep, r"### Step 3\.5", r"\n## Context resets", "Step 3.5")
    check("Step 3.5 runs `plan-flip-audit.py … --repo` at EVERY stage gate",
          affirms_claim(gate, r"record audit runs at every stage gate")
          and affirms_claim(gate, r"plan-flip-audit\.py[^.;]{0,60}--repo"))
    check("Step 3.5: exit 1, a blocking finding, fails the gate",
          affirms_claim(gate, r"exit 1, a `blocking` finding, fails the gate"))
    check("Step 3.5: exit 2 is an error, never read as clean; advisory is exit 4",
          affirms_claim(gate, r"Exit 2 is an error to fix first")
          and affirms_claim(gate, r"`advisory` finding \(exit 4\)"))


    print("dispatching-parallel-agents and honest-gates say the same:")
    brief = section(DPA.read_text(), r"### Prompt template", r"\*\*Prompt discipline:", "prompt template")
    check("the dispatch brief tells the task to run `prove-claim.py claim` before committing",
          affirms_claim(brief, r"prove-claim\.py claim"))
    check("the dispatch brief stages the records (`git add proof/`)",
          affirms_claim(brief, r"git add proof/"))
    check("the dispatch brief: stage the work first, `--test` from the Test, the patch a shell "
          "redirect writes into \"$TMPDIR\"",
          affirms_claim(brief, r"Stage your work, then prove it")
          and affirms_claim(brief, r"`--test` the Test command above")
          and affirms_claim(brief, r"reverting your fix, which a shell redirect writes into `\"\$TMPDIR\"`")
          and ".claude/" not in brief)
    check("the dispatch brief names where the tool lives (not an undefined placeholder)",
          affirms_claim(brief, r"executing-plans/scripts/prove-claim\.py"))
    hg = section(HG.read_text(), r"A test does not exist until its mutant dies", r"\n## ", "honest-gates mutant")
    check("honest-gates records the mutant's proof with `prove-claim.py`",
          affirms_claim(hg, r"prove-claim\.py claim"))
    check("honest-gates' device-only line is a deviation",
          affirms_claim(hg, r"prove-claim\.py deviation --claim"))
    check("neither skill asks for a hand-written mutation sentence",
          not HAND_WRITTEN.search(hg) and not HAND_WRITTEN.search(brief))

    print()
    if FAILED:
        print(f"FAIL: {len(FAILED)} check(s) failed")
        for n in FAILED:
            print(f"  - {n}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
