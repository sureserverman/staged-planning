#!/usr/bin/env python3
"""An extraction kept every obligation it promised to keep.

`check-extraction-classification.py` proves the classification and the trunk
describe the same set of headings. It cannot prove the trunk still carries the
RULES those headings stand for: a section reduced to `## Stop conditions` plus a
pointer satisfies set equality perfectly and has lost the obligation.

That gap is the whole failure mode an extraction must avoid — a `references/` file is a definition site the executor may never open,
so an unconditional rule moved out of the trunk stops binding while every
structural check stays green. This script closes it in two directions:

  MISSING-HEADING   a section classified `unconditional` or `rule+elaboration`
                    is not in the trunk at all.
  MISSING-RULE      the section is there, but the sentence its classification
                    row promised to keep is not. This catches the demotion a
                    heading check cannot see.
  UNMARKED-SECTION  a binding row carries no retention marker, so nothing pins
                    what "the rule stayed" means for it. Set equality against the
                    marker table is deliberate: without it, a row could be
                    silenced by deleting its marker rather than by keeping its
                    rule. Both binding classes are covered — `unconditional` rows
                    need markers most, being the ones that may never move at all.

`conditional` sections are exempt by construction — they are the ones that were
supposed to leave, and their retained pointer is checked by the DEAD-PATH half of
check-extraction-integrity.py instead.

WHAT THIS GUARD CANNOT SCREEN, disclosed
----------------------------------------
**A marker pins PRESENCE, never ASSERTION.** Markers are matched as plain
case-sensitive substrings with no negation screening, so a rule can be INVERTED in
place and stay green as long as the marker text survives inside it. For example,
against the live trunks:

    3. **Respect the cycle budget**
      ->  3. You need not **Respect the cycle budget** ... On exhaustion, carry on

    **Remediation budget — default 2 rounds per gate.**
      ->  **Remediation budget — default 2 rounds per gate.** This is advisory
          only and never limits looping.

Both keep every marker substring intact; this guard, check-extraction-classification.py
and every executing-plans contract suite stay green.

A prose guard must derive its negation-screening span from the text AND disclose
what it cannot screen. This guard does the second and not the first,
deliberately and for now: the screening half is a real piece of work with genuine
false-positive risk (this corpus is full of legitimately negative rule text — "Don't
shotgun", "never a pointer", "may not be presented"), and bolting a naive screen on
would trade a known gap for an unknown one. The screening half is
deferred work.

**So read a green run as "the rule is still there", never as "the rule still says
what it said."** Deletion and demotion — the failures this guard was built for — are
caught; inversion is not. The runtime output repeats this, because a docstring is
not read by whoever is looking at a passing gate.

Read-only. Exit 0 when every promise holds, 1 otherwise.
"""
import argparse
import collections
import importlib.util
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Same pairing as check-extraction-classification.py. Kept as its own list rather
# than imported because these two checks answer different questions and a trunk
# may sensibly gain one before the other.
PAIRS = [
    ("core/skills/executing-plans/SKILL.md",
     "core/skills/executing-plans/references/extraction-classification.md"),
    ("core/skills/planning-projects/SKILL.md",
     "core/skills/planning-projects/references/extraction-classification.md"),
    ("core/skills/honest-gates/SKILL.md",
     "core/skills/honest-gates/references/extraction-classification.md"),
]

VALID_CLASSES = ("unconditional", "rule+elaboration", "conditional")
# Sections that must keep a named rule. `conditional` is excluded on purpose.
BINDING_CLASSES = ("unconditional", "rule+elaboration")

# PAIRS is policy and is duplicated deliberately (above); PARSING is not, so the
# heading scan is shared. Two guards disagreeing about what counts as a heading in
# the same file is a silent divergence, and the one seeing fewer headings is the
# one that stops guarding.
_spec = importlib.util.spec_from_file_location(
    "_skill_sections", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "_skill_sections.py"))
_sections = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sections)


def trunk_headings(text):
    # A set here on purpose: this guard asks "is the section present", and the
    # duplicate-heading finding belongs to check-extraction-classification.py.
    return set(_sections.headings(text))


def _rows(text, want_cells):
    """Table rows with exactly `want_cells` columns, as stripped cell lists."""
    out = []
    for line in text.split("\n"):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == want_cells:
            out.append(cells)
    return out


def classified(text):
    """{section: class} from the 4-column classification tables.

    Rows come from the SHARED parser. A local row test stricter than
    check-extraction-classification.py's (say, `cells[0].isdigit()`) would make
    this guard's row set a strict subset of that one's — so editing a bytes cell
    to `n/a` would silently remove a section from this sweep with both guards
    green. Malformed rows are counted here and reported by the caller rather
    than skipped.
    """
    out, malformed = {}, []
    for section, klass, _reason, bad in _sections.class_rows(text):
        if bad:
            malformed.append(section)
            continue
        out[section] = klass
    return out, malformed


def markers(text):
    """{section: [required substrings]} from the `## Retention markers` table.

    Scoped to that section so the 2-column "where the conditional material went"
    table cannot be mistaken for a marker table — they have the same shape and
    only their position distinguishes them.

    LIST-valued, because one marker per section is instance-shaped. `Step 3.5 —
    Stage gate` retains more than a dozen distinct obligations; pinned by a single
    string, all but one could be demoted to pointers with this sweep still green —
    which is the defect class this repo's gate rules exist to reject, reproduced
    inside the guard meant to enforce them. A dict keyed by section would silently
    keep only the last row for a repeated section, so the table could not express
    what the rule requires.
    """
    out = collections.defaultdict(list)
    if "## Retention markers" not in text:
        return out
    tail = text.split("## Retention markers", 1)[1].split("\n## ", 1)[0]
    for cells in _rows(tail, 2):
        if cells[0] != "section":
            out[cells[0]].append(cells[1])
    return out


def check_pair(root, trunk_rel, table_rel):
    problems = []
    trunk_path = os.path.join(root, trunk_rel)
    table_path = os.path.join(root, table_rel)
    if not os.path.exists(table_path):
        return [f"{table_rel}: missing — {trunk_rel} has no classification"]

    with open(trunk_path, encoding="utf-8") as fh:
        trunk = fh.read()
    with open(table_path, encoding="utf-8") as fh:
        table = fh.read()

    heads = trunk_headings(trunk)
    klasses, malformed = classified(table)
    marks = markers(table)
    bodies = _sections.section_bodies(trunk)

    # A malformed row is a section this guard would silently stop sweeping while
    # check-extraction-classification.py kept accepting it. Report, never skip.
    for section in sorted(malformed):
        problems.append(
            f"{table_rel}: MALFORMED-ROW — {section!r} has a non-numeric bytes "
            "cell, which drops it from this sweep while set equality still passes")

    binding = {s for s, k in klasses.items() if k in BINDING_CLASSES}
    for section in sorted(binding):
        if section not in heads:
            problems.append(
                f"{trunk_rel}: MISSING-HEADING — {section!r} is classified "
                f"{klasses[section]!r} and must stay in the trunk")

    # EVERY binding section needs at least one marker, and every marker needs a row.
    #
    # `unconditional` rows are not exempt. Exempting them, on the reasoning that they
    # may never move so heading presence is enough, is backwards: those rows carry
    # the STRONGEST guarantee in the table, and heading presence is precisely the
    # check that cannot see a section gutted to a stub — the demotion this script's
    # own docstring opens by promising to catch.
    for section in sorted(binding - set(marks)):
        problems.append(
            f"{table_rel}: UNMARKED-SECTION — {section!r} is {klasses[section]!r} "
            "but names no retention marker")
    for section in sorted(set(marks) - set(klasses)):
        problems.append(
            f"{table_rel}: marker names no classified section — {section!r}")

    # The needle must appear in the body of the section that CLAIMS it, not
    # anywhere in the trunk. Matching against the whole file makes a row
    # unfalsifiable whenever its marker also occurs in another section: gutting
    # the row's own section leaves this guard green. Measured (undated, over the 44
    # rows the tables then held): with whole-file matching, replacing each binding
    # section's body with a pointer leaves 4 of the 44 rows green.
    #
    # The body EXCLUDES the section's own heading line, so a marker cannot be
    # satisfied by the heading `MISSING-HEADING` already guarantees.
    for section in sorted(marks):
        body = bodies.get(section)
        for needle in marks[section]:
            if not needle:
                problems.append(f"{table_rel}: {section!r} has an empty marker")
                continue
            if body is None:
                continue  # MISSING-HEADING already reported it
            if needle in body:
                continue
            where = " (it is elsewhere in the trunk, which is not this section's promise)" \
                if needle in trunk else ""
            problems.append(
                f"{trunk_rel}: MISSING-RULE — {section!r} promised to keep "
                f"{needle!r} in its own section and it is not there{where}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-trunk-retention")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)

    pairs = [(t, c) for t, c in PAIRS
             if os.path.exists(os.path.join(args.root, t))]
    problems, checked = [], 0
    # A fixture root carries only the trunks its case needs, so a missing one is
    # skipped there. In this repo's own tree a pinned trunk that is gone is a
    # finding: skipping it would let this check report "0 trunk(s)" and pass
    # after a layout move.
    if os.path.realpath(args.root) == os.path.realpath(REPO_ROOT):
        problems += [f"{t}: PINNED-MISSING — a pinned trunk does not exist"
                     for t, _ in PAIRS if not os.path.exists(os.path.join(args.root, t))]
    for trunk_rel, table_rel in pairs:
        problems += check_pair(args.root, trunk_rel, table_rel)
        table_path = os.path.join(args.root, table_rel)
        if os.path.exists(table_path):
            with open(table_path, encoding="utf-8") as fh:
                table = fh.read()
            checked += len({s for s, k in classified(table)[0].items()
                            if k in BINDING_CLASSES})

    # honest-gates: name the population swept, so a table that lost its rows
    # cannot report a pass over nothing.
    print(f"{len(pairs)} trunk(s), {checked} binding section(s) swept; "
          f"{len(problems)} problem(s).")
    # The disclosure, at the point of use. A green line that does not say what
    # green excludes is the thing that gets quoted at a gate.
    print("  (markers pin PRESENCE, not ASSERTION: a rule inverted in place around "
          "its marker text passes)")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
