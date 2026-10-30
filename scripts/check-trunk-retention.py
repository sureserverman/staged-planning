#!/usr/bin/env python3
"""An extraction kept every obligation it promised to keep.

`check-extraction-classification.py` proves the classification and the trunk
describe the same set of headings. It cannot prove the trunk still carries the
RULES those headings stand for: a section reduced to `## Stop conditions` plus a
pointer satisfies set equality perfectly and has lost the obligation.

That gap is the whole failure mode an extraction must avoid — a `references/` file is a definition site the executor may never open,
so an unconditional rule moved out of the trunk stops binding while every
structural check stays green. This script closes it with these findings:

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
  NEGATED-RULE      the marker is there, but every occurrence of it sits behind a
                    negation that reverses it: `You need not **Respect the cycle
                    budget**`. The finding names the marker and the sentence.
                    BLOCKING by the owner's decision (2026-10-29: "Blocking, gap
                    disclosed"), though gate-authoring.md § A gate heuristic ships
                    with a severity axis and a measured trigger rate asks for at
                    least one true hit first; that section names it as an open
                    gap. NEGATED-RULE:
                    measured 2026-10-29 over this repo's three pinned trunks (206
                    markers present) and every committed version of them in git
                    history (224 commits on all refs, 314 trunk+table versions,
                    21059 marker checks): 0 hits, 0 true. No inversion has ever been
                    committed, so the rate says nothing about precision yet. What
                    the window costs, from the same corpus: widened to 4 words it
                    lights 1 live marker (1 distinct sentence in history), false
                    (`(... no task creates it) → **plan defect**`); widened to the
                    whole clause, 5 live markers (7 distinct sentences in
                    history), all false.

`conditional` sections are exempt by construction — they are the ones that were
supposed to leave, and their retained pointer is checked by
check-extraction-integrity.py instead: DEAD-PATH for the file, LOST-REFERENT for the section.

WHAT THIS GUARD CANNOT SCREEN, disclosed
----------------------------------------
**A marker is screened for a negation in front of it, and nowhere else.** Markers
are matched as plain case-sensitive substrings; NEGATED-RULE then reads the text
just before each occurrence with the contract suites' shared clause screen
(`affirms_claim` in executing-plans' test-gate-remediation-contract.py, loaded, not
copied). The span is derived from the text: the paragraph or list item holding the
marker, cut back to the last clause boundary before it, and capped at the
NEGATION_WORDS words nearest the marker. The marker's own words are not screened —
`Never collapse BLOCKED into GREEN.` states its rule with its negation. So these are
caught:

    3. **Respect the cycle budget**
      ->  3. You need not **Respect the cycle budget**   (also: Never ..., You are
          not required to ..., There is no need to ...)

And these still pass, each a measured limit rather than an oversight:

    **Remediation budget — default 2 rounds per gate.** This is advisory only and
    never limits looping.
      (a withdrawal AFTER the marker, or in a later sentence, is not read: the
      trunks qualify markers with "X, not Y" constantly, and the shared screen
      applied as it reads a requirement, after the marker included, lit 39 of 206
      live markers, all false)
    It is no longer necessary to **Respect the cycle budget**.
      (the negation is 4 words back, outside the window; the window stops at 3
      because the nearest legitimate negation in the corpus is 4 words back)
    Never, under any circumstance, **Respect the cycle budget**.
      (a comma ends the clause, so the "Never" belongs to the clause before)
    ```Respect the cycle budget: optional```
      (a marker inside a fenced block is a literal, as a `code span` is to the
      shared screen, and is pinned for presence only)

**So read a green run as "the rule is still there and nothing just before it says
the opposite", never as "the rule still says what it said."** The runtime output
repeats this, because a docstring is not read by whoever is looking at a passing
gate.

Read-only. Exit 0 when every promise holds, 1 otherwise; an ADVISORY finding is
printed and never changes the exit code.
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


# The negation screen is the contract suites' own, loaded rather than copied: a
# second copy of a clause grammar drifts, and the copy that reads fewer clause
# boundaries is the one that rejects true prose. That file's checks run only under
# `__main__`; importing it defines functions and constants and nothing else. It is a
# test file, and this script is a repo validator that the build never ships, so it
# is always beside it. Loaded on first use, so a fixture tree that sweeps no marker
# (the PINNED-MISSING case runs a copy of scripts/ alone) never needs it.
SCREEN_PATH = os.path.join(REPO_ROOT, "core", "skills", "executing-plans", "tests",
                           "test-gate-remediation-contract.py")
_SCREEN = []

# NEGATED-RULE's tier. gate-authoring.md asks for at least one true hit before
# blocking; this one is blocking by the owner's decision with 0 hits, 0 true, and is
# listed there as an open gap. The measurement is in the docstring.
NEGATED_RULE_TIER = "blocking"

# How many words before a marker the negation screen reads. Measured, not chosen:
# see the docstring. At 4 the screen lights `no task creates it) → **plan defect**`.
NEGATION_WORDS = 3

# Stands in for the marker inside the screened text, so the marker's own words
# ("Never collapse BLOCKED into GREEN.") are never read as a withdrawal of itself.
_HOLE = "RETAINEDMARKER"
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")


def _screen():
    if not _SCREEN:
        if not os.path.exists(SCREEN_PATH):
            sys.exit(f"check-trunk-retention: the shared negation screen is gone: "
                     f"{os.path.relpath(SCREEN_PATH, REPO_ROOT)}")
        spec = importlib.util.spec_from_file_location("_gate_contract", SCREEN_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SCREEN.append(mod)
    return _SCREEN[0]


def _prose_units(body):
    """(is_fenced, text) per paragraph, list item, or fenced line of a body.

    A unit is the widest span a sentence can have: `flat()` joins wrapped lines, so
    without these cuts a list item would run into the next item's negation.
    """
    out, buf, fenced = [], [], False

    def flush():
        if buf:
            out.append((False, "\n".join(buf)))
            buf.clear()
    for line in body.split("\n"):
        if _sections._FENCE_RE.match(line):
            flush()
            fenced = not fenced
        elif fenced:
            out.append((True, line))
        elif not line.strip():
            flush()
        else:
            if _LIST_ITEM.match(line):
                flush()
            buf.append(line)
    flush()
    return out


def negated_sentence(body, needle):
    """The sentence holding `needle` when EVERY occurrence of it is negated, else None.

    One clean occurrence is enough, as it is for the shared screen. An occurrence in
    a fenced block counts as clean: a fence holds literals.
    """
    g = _screen()
    found = None
    for fenced, unit in _prose_units(body):
        if needle not in unit:
            continue
        if fenced:
            return None
        hay, flat_needle = g.flat(unit), g.flat(needle)
        for m in re.finditer(re.escape(flat_needle), hay):
            lead = hay[:m.start()]
            words = list(re.finditer(r"\S*\w\S*", lead))
            cut = words[-NEGATION_WORDS].start() if len(words) >= NEGATION_WORDS else 0
            if lead[:cut].count("`") % 2:  # never start inside a `code span`
                cut = lead.rfind("`", 0, cut)
            if g.affirms_claim(lead[cut:] + _HOLE, _HOLE):
                return None
            if found is None:
                starts = [b.end() for b in g.SENTENCE_END.finditer(lead)]
                end = g.SENTENCE_END.search(hay, m.end())
                found = hay[(starts[-1] if starts else 0):
                            (end.start() if end else len(hay))].strip()
    return found


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
                sentence = negated_sentence(body, needle)
                if sentence is not None:
                    tier = "" if NEGATED_RULE_TIER == "blocking" else "ADVISORY "
                    problems.append(
                        f"{trunk_rel}: {tier}NEGATED-RULE — {section!r} keeps "
                        f"{needle!r} only behind a negation that reverses it: "
                        f"{sentence!r}")
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
    advisory = [p for p in problems if "ADVISORY NEGATED-RULE" in p]
    print(f"{len(pairs)} trunk(s), {checked} binding section(s) swept; "
          f"{len(problems) - len(advisory)} problem(s), "
          f"{len(advisory)} advisory finding(s).")
    # The disclosure, at the point of use. A green line that does not say what
    # green excludes is the thing that gets quoted at a gate.
    print(f"  (a marker is screened only for a negation in the {NEGATION_WORDS} words "
          "before it, in its clause: a withdrawal after it, or in a fenced block, passes)")
    for p in problems:
        print(f"  {p}")
    return 1 if len(problems) > len(advisory) else 0


if __name__ == "__main__":
    sys.exit(main())
