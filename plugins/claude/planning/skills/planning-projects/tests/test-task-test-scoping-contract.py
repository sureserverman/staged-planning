#!/usr/bin/env python3
"""Structure suite for the task-level `Test:` scoping contract — run directly:
    python3 core/skills/planning-projects/tests/test-task-test-scoping-contract.py

A PROSE contract, not behavior. It asserts that the authoring text does not
claim a task-level `Test:` field is scoped automatically, and that it states the
authoring rule in the claim's place. It cannot verify that an author obeys the
rule — that is the TASK-TEST-UNSCOPED check in validate-gate-checks.py, and saying
so here is the honest-gates disclosure a structure suite owes.

What it pins:
  1. The falsified assumption is absent from the WHOLE TREE, in EVERY wording — the
     "by-construction" claim, the "already task-scope" one, and the table cell's
     "already targeted". (The first is not spelled out anywhere in this file,
     including here: a gate that greps that literal phrase across the tree would
     find this suite and redden. The matcher below is assembled from fragments for
     the same reason.)

     Every wording is swept tree-wide. Checking one wording tree-wide and another
     only inside a regex-extracted table cell would let a third file restating
     "already targeted" pass while this docstring claims tree-wide coverage. A
     check whose stated scope exceeds its actual one is the failure this repo
     tracks hardest.

     A literal grep for the phrase cannot fail: the phrase is hard-wrapped across
     a newline at its only site, so the grep returns nothing whether or not the
     claim is present. Normalizing whitespace is what makes the sweep able to
     fail; sweeping the whole tree, not one directory, is the class rule.
  2. `test-scope-tiers.md` states the replacement rule — on a project whose suite
     is expensive, a task `Test:` is path- or suite-scoped, or carries an explicit
     `full-suite: accepted`.
  3. It names the token `full-suite: accepted` verbatim, because the flag is what
     validate-gate-checks.py matches on: a rule naming no exact token leaves the
     validator free to invent one, and then the rule and the check disagree.
  4. It names the measured run the rule rests on (the figures the check below
     looks for), because a rule that reverses an earlier one needs evidence a
     reader can weigh; without it the reversal is an unsupported change of mind.
  5. The task-scope table row does not assert the field is "already targeted".
     The row is where an executor looks the tier up, so a corrected § Plan-authoring
     declaration with an uncorrected row leaves the claim standing at the site that
     is actually read — the connective-prose class, in its table form.
  6. The authoring checklist carries the obligation as an item, naming the same
     token, so the rule is checked at the moment a plan is authored rather than
     stated only in the reference a hurried author may not open.
  7. The item names its gating tier (authoring-time): a new mandate
     states what gates it, or it is an unbounded cost.
  8. BOTH checklists carry it — Standard and Light. The Light list's own closing
     paragraph says it is "shorter rather than softer" because every item it
     drops is a field the Light format does not have. A task `Test:` is a field
     it does have, so a rule present in one list and absent from the other
     contradicts that paragraph and leaves a Light plan on an expensive-suite
     project with exactly the defect the rule retracts. The class, not the
     instance.

Read-only. Exit 0 when every promise holds, 1 otherwise.
"""

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The sweep is tree-wide: the git checkout this test sits in (its plugin root when the
# plugin is installed outside one).
_top = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True)
REPO = Path(_top.stdout.strip()) if _top.returncode == 0 else HERE.parents[2]
TIERS = HERE.parent / "references" / "test-scope-tiers.md"
CHECKLIST = HERE.parent / "references" / "authoring-checklist.md"

FAILURES = []
RAN = []

# Built from parts so this suite is not itself a hit for the sweep in check 1 —
# and skipped by path anyway, belt and braces.
# Both wordings, swept tree-wide. The second alternation is context-bound rather
# than bare: "already targeted" is an ordinary English phrase, and a matcher that
# flagged every use of it would be a false-positive generator rather than a guard.
# What is falsified is the claim made ABOUT A TASK FIELD, so the context is the
# window in which that subject appears.
FALSIFIED = re.compile(
    r"task-scope\s+by\s+" + "construction"
    r"|already\s+task" + r"-scope"
    r"|(?:task(?:-level)?|`Test:`)[^.]{0,140}?already\s+targeted"
    r"|already\s+targeted[^.]{0,140}?(?:task(?:-level)?|`Test:`)",
    re.I,
)

SKIP_DIRS = (".git", "__pycache__", "node_modules")

# A claim quoted in order to DENY it is not an assertion of it. test-scope-tiers.md
# carries one — "on the belief that per-task runs were already targeted. They were
# not." — its retraction of a NARROWER version of the same claim. Without this
# exclusion the sweep reports the file's own retraction as the defect, which teaches
# an author that retracting a claim in prose is what trips the guard.
# Pinned in both directions by the assertions below: a denied claim passes, a bare one
# does not.
RETRACTED = re.compile(
    r"\A[^.]{0,40}\.\s*(?:They were not|That was false|Not so|Falsified|"
    r"That claim is (?:retracted|false)|This file said otherwise)",
    re.I,
)


def check(name, ok, detail=""):
    RAN.append(name)
    if not ok:
        FAILURES.append(f"{name}: {detail}" if detail else name)


def flat(s):
    """Collapse whitespace and blockquote markers so a matcher is not defeated by
    a line wrap. Every file here is hard-wrapped, and the phrase this suite must
    be able to find spans a newline at its only site — which is exactly why a
    literal grep for it cannot fail."""
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s*>\s?", "", s))


def slice_between(text, start, end):
    """Return the span between two anchors, and whether both were found."""
    i = text.find(start)
    if i < 0:
        return text, False
    j = text.find(end, i + len(start))
    if j < 0:
        return text[i:], False
    return text[i:j], True


def sweep_tree():
    hits = []
    for p in sorted(REPO.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        # plugins/ and packages/ are generated copies of core/: a claim there is the
        # same claim as at its source, counted once.
        if p.relative_to(REPO).parts[0] in ("plugins", "packages"):
            continue
        if p.resolve() == Path(__file__).resolve():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        flatm = flat(text)
        for m in FALSIFIED.finditer(flatm):
            if RETRACTED.match(flatm[m.end():]):
                continue
            hits.append(str(p.relative_to(REPO)))
            break
    return hits


def main():
    tiers = flat(TIERS.read_text(encoding="utf-8"))
    checklist = flat(CHECKLIST.read_text(encoding="utf-8"))

    hits = sweep_tree()
    check("the falsified 'scoped by construction' claim is gone tree-wide",
          not hits,
          "still asserted at: " + ", ".join(hits))

    # The retraction exclusion, both ways. A sweep that cannot tell an assertion from a
    # denial of it is a sweep whose green means nothing on a file that documents its own
    # corrections — which is every file in this plugin.
    check("a claim quoted in order to deny it is not counted as asserted",
          FALSIFIED.search("per-task runs were already targeted. They were not.")
          is not None
          and RETRACTED.match(
              "per-task runs were already targeted. They were not."[
                  FALSIFIED.search("per-task runs were already targeted. "
                                   "They were not.").end():]) is not None,
          "the exclusion does not fire on the file's own retraction")
    check("a BARE assertion is still counted",
          RETRACTED.match(" and so the field needs no bound.") is None,
          "the exclusion is too broad — it would swallow a live claim")

    check("test-scope-tiers.md states the expensive-suite scoping rule for task `Test:`",
          re.search(r"expensive[^.]{0,200}?task[^.]{0,120}?`?Test:?`?[^.]{0,200}?scoped"
                    r"|task[^.]{0,120}?`Test:`[^.]{0,300}?scoped[^.]{0,200}?expensive",
                    tiers, re.I) is not None,
          "no rule ties a task `Test:` on an expensive-suite project to being scoped")

    check("test-scope-tiers.md names the `full-suite: accepted` token verbatim",
          "full-suite: accepted" in tiers,
          "the escape hatch has no exact spelling, so validate-gate-checks.py would "
          "have to invent one")

    check("the rule cites the measured run it rests on",
          re.search(r"3132|3\.5\s*h|200\+?\s*min", tiers, re.I) is not None,
          "no evidence is cited, so a reader has nothing to weigh the reversal against")

    row = re.search(r"\|\s*\*\*task-scope\*\*\s*\|(.{0,600}?)\|\s*\*\*fix-scope\*\*", tiers)
    check("the task-scope table row exists and drops the 'already targeted' claim",
          row is not None and not re.search(r"already\s+targeted", row.group(1), re.I),
          "the row still asserts the field is already targeted"
          if row else "the task-scope row could not be located")

    check("the authoring checklist carries the obligation as an item",
          re.search(r"-\s*\[\s*\][^|]{0,400}?full-suite:\s*accepted", checklist) is not None,
          "the rule is stated only in the reference; an author following the "
          "checklist would never meet it")

    item = re.search(r"-\s*\[\s*\][^\[]{0,600}?full-suite:\s*accepted[^\[]{0,400}", checklist)
    check("the checklist item names its gating tier (authoring-time)",
          item is not None and re.search(r"authoring[- ]time", item.group(0), re.I),
          "the new mandate does not say what gates it")

    # Checked as a SET across the two lists. A Light plan has task `Test:` fields
    # and can be authored for an expensive-suite project, so a rule that reaches
    # only the Standard list is instance-shaped in the way this repo rejects
    # everywhere else.
    light, found = slice_between(checklist, "## Checklist - Light plans",
                                 "Why the Light list is shorter")
    if not found:
        light, found = slice_between(checklist, "## Checklist \u2014 Light plans",
                                     "Why the Light list is shorter")
    check("the Light checklist carries the same obligation",
          found and "full-suite: accepted" in light,
          "the Light list could not be located" if not found else
          "a Light plan on an expensive-suite project keeps the defect the rule "
          "retracts, and the list's own 'shorter rather than softer' paragraph "
          "says that is not a legitimate omission")

    print(f"assertions run ({len(RAN)}):")
    for name in RAN:
        print(f"  - {name}")
    if FAILURES:
        print("\nFAILURES:", file=sys.stderr)
        for f in FAILURES:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    print("\nOK — task-`Test:` scoping contract present in authoring text "
          "(prose contract only; enforcement is validate-gate-checks.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
