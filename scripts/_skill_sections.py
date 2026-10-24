#!/usr/bin/env python3
"""Heading extraction for a skill trunk, with fenced code blocks excluded.

Shared by check-extraction-classification.py and check-trunk-retention.py.

A `^#{2,4} ` regex over a SKILL.md does not read markdown, it reads lines — so a
heading inside a ```fence``` counts as a section of the trunk. That is not a
pedantic distinction here. A trunk that shows an author what a plan's
`## Decisions in force` section should look like by printing one inside a
```markdown fence gains, under a fence-blind scan, that heading as one of its own.

The shape recurs whenever a skill documents a document format, which these skills
do constantly, and the failure it prevents is silent. **Its live coverage is the
unit tests in `scripts/tests/test-check-extraction-classification.py`, not the
trunks** — a trunk with no such fence does not exercise this code, so do not read
a green tree as evidence that it is.

Both guards then go wrong, and neither is recoverable by allowlisting:

  * check-extraction-classification.py demands a classification row for it, so
    the table has to file a decision about a code sample. Worse, the row is a
    time bomb: the day someone edits the example, the row "names no such
    heading" and the guard fails on a change that touched nothing real.
  * check-trunk-retention.py reads its binding sections from that same table, so
    it would sweep a section that does not exist and report the count as
    coverage.

The classification is the authority for what may leave a trunk, so it has to
quantify over the trunk's real sections and nothing else.

Why the two callers share this rather than each keeping a copy: they deliberately
keep their own PAIRS lists, because those are policy and may legitimately differ.
Parsing is not policy. Two guards disagreeing about what counts as a heading in
the same file is a silent divergence, and the one that sees fewer headings is the
one that stops guarding.

**Fences are stripped for HEADINGS, never for rule text.** Stripping fences
before the retention check's substring match, on the reasoning that a marker
should be satisfied by prose rather than by a code sample, breaks a legitimate
marker in the live table: `Step 3.3` pins `Executor: dispatched — <subagent_type>`,
and the trailer shapes are a fenced block because the rule *is* the literal. A rule may be a code block; only a
heading may not be.

Fence tracking is deliberately simple and matches CommonMark's common case: a
line whose first non-space characters are ``` or ~~~ toggles fenced state. It
does not model info strings, indented code blocks, or differing fence lengths,
because a SKILL.md that needs those has a bigger problem than this parser. Two
consequences worth stating rather than discovering: a `~~~` line inside a
```-fence toggles the state early, and a heading placed inside a *legitimate*
fence disappears from both guards silently whenever the classification has no row
for it. An UNCLOSED fence hides everything after it, which fails loudly at set
equality — the safe direction.

**Why `sections()` and `class_rows()` live here too.** The callers deliberately
keep their own PAIRS lists, because those are policy and may legitimately differ.
Parsing is not policy, and a divergence in it is silent: the guard that sees less
is the one that stops guarding, and neither divergence below turns the suite red.
"""
import re

HEADING_RE = re.compile(r"^#{2,4} (.+)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
VALID_CLASSES = ("unconditional", "rule+elaboration", "conditional")


def _walk(text):
    """(is_heading, heading_text, raw_line) per line, fenced blocks neutralized."""
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            yield False, None, line
            continue
        if in_fence:
            yield False, None, line
            continue
        m = HEADING_RE.match(line)
        yield (True, m.group(1).strip(), line) if m else (False, None, line)


def headings(text):
    """Every `^#{2,4} ` heading OUTSIDE a fenced block, in document order.

    Returns a list, not a set: a duplicate heading text is itself a finding the
    callers report, and a set would hide it.
    """
    return [h for is_h, h, _ in _walk(text) if is_h]


def section_bodies(text):
    """{heading: body} — each section's text, EXCLUDING its own heading line.

    Excluding the heading is the point, not an accident. A retention marker is a
    promise that the section still carries its RULE; a marker satisfiable by the
    heading itself pins nothing, because `MISSING-HEADING` already guarantees the
    heading. A row like `| Subcommands | Subcommands |` is exactly that shape.

    A body runs to the next heading of ANY depth, so a rule that lives in a
    subsection belongs to that subsection, not to its parent.

    Duplicate heading text collapses here; `check-extraction-classification.py`
    reports duplicates separately and set equality cannot survive them anyway.
    """
    out, current, buf = {}, None, []
    for is_h, head, line in _walk(text):
        if is_h:
            if current is not None:
                out[current] = "\n".join(buf)
            current, buf = head, []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf)
    return out


def class_rows(text):
    """(section, klass, reason, malformed) per classification-table row.

    SHARED so the two guards cannot disagree about what a row is. If one
    required `cells[0].isdigit()` while the other required only 4+ cells, the
    retention guard's row set would be a strict SUBSET of the classification
    guard's: a one-character edit to a bytes cell (`497` -> `n/a`) would drop a
    section out of the retention sweep entirely, with BOTH guards green and the
    only trace a population count moving by one that nothing asserts.

    A row under a `### <class>` heading whose bytes cell is not a digit is
    returned with malformed=True rather than skipped, so it can be REPORTED. A
    silent skip would let the divergence hide.

    **Deliberately fence-blind**, unlike `headings()` above, which is the one
    asymmetry in this module. A classification table inside a fenced block would
    be parsed as real rows. No shipped table has one, and a fenced 4-column table
    under a `### <class>` heading is not a shape these documents use — but the
    asymmetry is stated here rather than left for a reader to trip on, because the
    rest of this module is about fences.
    """
    rows, klass = [], None
    for line in text.split("\n"):
        m = re.match(r"^### (\S+)", line)
        if m:
            # An invalid class heading RESETS klass rather than falling through.
            # Falling through would be a second silent-drop path with the same
            # end state as the bytes-cell divergence, reached by a different edit:
            # append `### deleted — rows kept for history`, move a row under it,
            # and it would INHERIT the preceding valid class — leaving the binding
            # sweep with both guards green.
            klass = m.group(1) if m.group(1) in VALID_CLASSES else None
            continue
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "bytes":
            continue
        # klass may be None — a row under a heading that is not one of the three
        # valid classes. It is RETURNED rather than skipped so the caller can
        # report "has no valid class", which names the actual defect. Skipping it
        # would surface only the downstream symptom (the heading reading as
        # unclassified) and lose the diagnosis.
        rows.append((cells[2], klass, cells[3], not cells[0].isdigit()))
    return rows
