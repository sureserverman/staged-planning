#!/usr/bin/env python3
"""Contract suite for honest-gates — run directly (CI convention):

    python3 core/skills/honest-gates/tests/test-honest-gates-contract.py

These are PROSE contracts, not behavior. The suite asserts that the trunk STATES
each rule in a clause that carries no negation; it cannot verify that an executor
obeys one. Stated plainly because a structure suite that implies behavioral
coverage is the falsehood class honest-gates exists to name.

Two halves, and they answer different questions:

  1. **Sentence checks.** Each pinned rule is matched with `affirms_claim`, borrowed
     by path from executing-plans' gate-remediation suite so this file does not
     hand-roll a sixth negation screen (the screening span is derived from
     the text — back to the clause boundary, forward to the sentence end). A rule
     inverted in place ("you need not …") fails here, which is the half
     `check-trunk-retention.py` cannot see (its markers pin presence only).

  2. **Mutation battery.** For every retention marker the classification table
     declares, delete that marker's line from a temp copy of the trunk and assert
     `check-trunk-retention.py --root <tmp>` reports MISSING-RULE naming it. The
     count is derived from the table, never typed, so a marker added later without
     a killing mutation is a red suite rather than a silent gap. This is
     honest-gates' own rule — each guard independently reachable from a named
     test — applied to the guard that protects honest-gates.

Every check also records the pattern it matched, and the suite fails if two checks
pinned the same sentence: one owner per fact.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
TRUNK = os.path.join(SKILL_DIR, "SKILL.md")
TABLE = os.path.join(SKILL_DIR, "references", "extraction-classification.md")
TRUNK_REL = os.path.relpath(TRUNK, REPO)
TABLE_REL = os.path.relpath(TABLE, REPO)
RETENTION = os.path.join(REPO, "scripts", "check-trunk-retention.py")
HELPER = os.path.join(REPO, "core", "skills", "executing-plans", "tests",
                      "test-gate-remediation-contract.py")


def _load_helper():
    spec = importlib.util.spec_from_file_location("_gate_contract", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_helper = _load_helper()
affirms_claim = _helper.affirms_claim

FAILED = []
PINNED = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def pin(name, hay, pattern):
    """A prose requirement: the pattern appears in a non-negated clause of `hay`."""
    PINNED.append((name, pattern))
    check(name, affirms_claim(hay, pattern))


def pin_neg(name, hay, pattern):
    """A requirement whose own subject is a negation — "not green", "never an estimate".

    `affirms_claim` screens the whole clause and so rejects these on true prose (the
    sibling suite records the same case for "conditional, not absolute"). What can still
    be screened is everything in the sentence EXCEPT the match: the run-up from the
    previous clause boundary ("You need not **Never collapse …**") and the tail to the
    sentence end ("…never an estimate, though this is optional in practice") — the
    trailing-withdrawal shape `affirms_claim`'s own docstring names. Both ends are
    derived from the text with the helper's own boundary regexes (SENTENCE_END's `.**`
    alternative is what stops a bold sentence's tail leaking into the next paragraph).
    The phrase itself is specific enough that no inversion can match it by accident.

    **Stated limit:** a withdrawal in the NEXT sentence ("Never collapse … . That said,
    this is advisory.") is not screened — the sentence boundary is where the claim ends,
    the same limit affirms_claim carries.
    """
    PINNED.append((name, pattern))
    for m in re.finditer(pattern, hay, re.I | re.S):
        pre = hay[max(0, m.start() - _helper.NEGATION_LOOKBEHIND):m.start()]
        pre = re.split(r"[.;:]\s|\s[-–—]\s", pre)[-1]
        after = _helper.SENTENCE_END.search(hay, m.end())
        tail = hay[m.end(): (after.start() if after else len(hay))]
        if not _helper.NEGATION_RE.search(re.sub(r"`[^`]*`", " ", pre + " " + tail)):
            check(name, True)
            return
    check(name, False, "phrase missing, or every occurrence is negated in its run-up or tail")


def ws(pattern):
    """A literal phrase as a wrap-tolerant pattern: every space may be any whitespace run.
    The trunk is hard-wrapped, so a pinned phrase can break at any word; a pattern that
    guesses the break point is a test that fails on true prose after a reflow."""
    return re.sub(r" ", r"\\s+", pattern)


def section(text, heading):
    """Body of one `## ` section, excluding its heading line; '' when absent."""
    m = re.search(r"^## " + re.escape(heading) + r"\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def marker_rows(table_text):
    """[(section, marker)] from the `## Retention markers` table, in order."""
    tail = table_text.split("## Retention markers", 1)[1].split("\n## ", 1)[0]
    out = []
    for line in tail.split("\n"):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 2 and cells[0] != "section":
            out.append((cells[0], cells[1]))
    return out


def sentence_checks(trunk):
    print("Sentence checks — each rule stated in a non-negated clause:")
    one = section(trunk, "The one rule")
    pin("one rule: green only when the real command ran here and passed", one,
        r"green only when its real command ran in the current environment and\s+actually passed")
    pin_neg("one rule: a check that cannot run here is BLOCKED, not green", one,
        r"cannot make the real check run here, the gate is \*\*BLOCKED\*\*, not green")

    blocked = section(trunk, "When a gate is BLOCKED")
    pin("BLOCKED: stop on that gate", blocked, r"Stop on that gate")
    pin_neg("BLOCKED: the checklist item is written `[~]`, never a ticked box with a note", blocked,
        r"Write the checklist item as `- \[~\]`, never `- \[x\]` with a note")

    claim = section(trunk, "A behavioral claim is a gate too")
    pin("claim: an assertion about behavior cites the file:line it was checked against", claim,
        r"cite the\s+`file:line` you checked it against")
    pin_neg("claim: an absence claim is proved by a search, not a line", claim,
        r"An absence claim.*?is proved by a \*search\*, not a line")
    pin("claim: a correction is a new claim", claim, r"A correction is a new claim")

    mutant = section(trunk, "A test does not exist until its mutant dies")
    pin("mutant: ask first whether the mechanism can decide the property", mutant,
        r"can this mechanism decide this property")
    pin("mutant: rule 1 — write the set down before the fix", mutant,
        r"Write the set down before the fix")
    pin("mutant: rule 2 — revert the fix; the suite must go red", mutant,
        r"Revert the fix; the suite must go red")
    # One red proves one guard; two guards that mask each other pass rule 2 alone.
    pin("mutant: each guard is independently reachable from a named test", mutant,
        ws(r"each guard is independently reachable from a named test"))
    pin("mutant: a mutation battery, one mutation per guard, proves a verdict-producing check", mutant,
        ws(r"mutation battery, one mutation per guard"))
    pin_neg("mutant: rule 3 — fixtures from the requirement, never from observed behavior", mutant,
        r"Build fixtures from the requirement, never from observed behavior")
    pin_neg("mutant: assert the discriminating cause, not the outcome", mutant,
        r"Assert the discriminating cause, not the outcome")

    contract = section(trunk, "Changing a contract reclassifies everything already written")
    pin_neg("contract: a contract change does not ship until its corpus is inventoried", contract,
        r"does not ship\s+until the corpus it reclassifies has been inventoried")
    pin_neg("contract: the inventory is a command and its output, never an estimate", contract,
        r"The inventory is a command and its output, never an estimate")

    prohibited = section(trunk, "Prohibited (these are gate-faking)")
    # The executor can author the gate script, so a stub can stand in for a real check.
    pin("prohibited: a gate script written or modified during the run is named in the gate report",
        prohibited, r"written or modified during\s+the run is named in the gate report")
    pin_neg("prohibited: a script whose non-comment body cannot reach both outcomes is not a gate",
        prohibited, r"cannot reach both\s+outcomes is not a gate")
    check("prohibited: both stub shapes are named (`echo OK` pass, unconditional `exit 2` block)",
          re.search(r"`echo OK`", prohibited) is not None and re.search(r"`exit 2`", prohibited) is not None)

    # The exclusion bullet: removing a suite to save time is BLOCKED on that suite, and only
    # the tier policy's declared narrowing counts as scope rather than an amendment.
    excl = re.search(r"- \*\*Silently excluding the failing case\.\*\*.*?(?=\n- \*\*)", prohibited, re.S)
    excl = excl.group(0) if excl else ""
    pin_neg("prohibited: a suite removed from a gate command for time, disk or cost is `[~]` BLOCKED on that suite",
        excl, ws(r"for time, disk or cost is `\[~\]` BLOCKED on that suite"))
    pin_neg("prohibited: cost, time and disk are never an authorizing rule for an amendment",
        excl, ws(r"never an authorizing rule for an amendment"))
    pin_neg("prohibited: narrowing is scope only for trees the stage neither touched nor depends on (the discriminator)",
        excl, ws(r"drops only trees the stage's commits neither touched nor depend on"))
    pin_neg("prohibited: a named suite or a touched tree removed for cost is `[~]` whatever the report calls it",
        excl, ws(r"removed for cost, is `\[~\]` whatever the report calls it"))
    check("prohibited: the bullet cites test-scope-tiers.md for the declared-scope distinction",
          "test-scope-tiers.md" in excl)
    pin_neg("prohibited: declared stage-scope narrowing is scope on the gate's scope line, not an amendment",
        excl, ws(r"scope line, not an amendment"))
    tiers_path = os.path.join(REPO, "core", "skills", "planning-projects", "references", "test-scope-tiers.md")
    with open(tiers_path, encoding="utf-8") as fh:
        tiers = fh.read()
    check("mirror: test-scope-tiers.md § Guard rails still says the gate report names which scope ran",
          re.search(ws(r"the gate report says which scope"), tiers) is not None)

    reporting = section(trunk, "Reporting")
    pin("reporting: every gate is GREEN, RED or BLOCKED", reporting,
        r"every gate is one of: \*\*GREEN\*\*.*?\*\*RED\*\*.*?\*\*BLOCKED\*\*")
    pin_neg("reporting: never collapse BLOCKED into GREEN", reporting,
        r"Never collapse BLOCKED into GREEN")
    # Where did the evidence execute; a figure is reproducible at a sha.
    pin("reporting: a GREEN names where its evidence executed", reporting,
        ws(r"names where its evidence executed"))
    check("reporting: the four substrates are listed as one list (host, emulator, container, target device)",
          re.search(ws(r"host, emulator, container, or target device"), reporting) is not None)
    pin_neg("reporting: a deployed-behaviour claim whose evidence ran elsewhere is BLOCKED, not green",
        reporting, ws(r"ran anywhere else is \*\*BLOCKED\*\*, not green"))
    pin("reporting: a number in a gate report is emitted by a command at a sha it names, or carries the sha",
        reporting, ws(r"emitted by a command at a sha it names, or carries the sha"))
    pin("reporting: a corpus figure states its selection rule", reporting,
        ws(r"corpus figure states its selection rule"))

    dupes = {p for _, p in PINNED if [q for _, q in PINNED].count(p) > 1}
    check("one owner per fact: no two checks pin the same sentence", not dupes, str(sorted(dupes)))


def mutation_battery(trunk, table_text):
    rows = marker_rows(table_text)
    print(f"Mutation battery — {len(rows)} markers from {os.path.basename(TABLE)}:")
    killed = 0
    survivors = []
    lines = trunk.split("\n")
    for sec, needle in rows:
        root = tempfile.mkdtemp(prefix="hg-mut-")
        try:
            os.makedirs(os.path.join(root, os.path.dirname(TABLE_REL)))
            shutil.copy(TABLE, os.path.join(root, TABLE_REL))
            mutated = [l for l in lines if needle not in l]
            if len(mutated) != len(lines) - 1:
                survivors.append((sec, needle, f"marker matched {len(lines) - len(mutated)} lines, not 1"))
                continue
            with open(os.path.join(root, TRUNK_REL), "w", encoding="utf-8") as fh:
                fh.write("\n".join(mutated))
            r = subprocess.run([sys.executable, RETENTION, "--root", root],
                               capture_output=True, text=True)
            named = ("MISSING-RULE" in r.stdout and repr(sec) in r.stdout
                     and needle[:24] in r.stdout)
            if r.returncode == 1 and named:
                killed += 1
            else:
                survivors.append((sec, needle, f"exit {r.returncode}; named={named}"))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    for sec, needle, why in survivors:
        print(f"  SURVIVED: {sec!r} / {needle!r} — {why}")
    print(f"  {killed}/{len(rows)} killed")
    check("mutation battery: every marker's deletion is reported as MISSING-RULE",
          killed == len(rows) and len(rows) > 0)
    check("mutation battery: the marker count comes from the table, and the table is non-empty",
          len(rows) == table_text.count("\n| ") - table_text.count("\n| bytes")
          - table_text.count("\n| section") - _classification_row_count(table_text))


def _classification_row_count(table_text):
    """Rows of the 4-column class tables and the 2-column destination table — the
    rows that are NOT markers — so the marker count can be cross-derived."""
    head = table_text.split("## Retention markers", 1)[0]
    return sum(1 for l in head.split("\n")
               if l.startswith("| ") and not l.startswith("| bytes") and not l.startswith("| section"))


def main():
    with open(TRUNK, encoding="utf-8") as fh:
        trunk = fh.read()
    with open(TABLE, encoding="utf-8") as fh:
        table_text = fh.read()
    sentence_checks(trunk)
    mutation_battery(trunk, table_text)
    if FAILED:
        print(f"\nFAIL: {len(FAILED)} check(s) failed:")
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print(f"\nOK — {len(PINNED)} rule(s) pinned, negation-screened; battery green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
