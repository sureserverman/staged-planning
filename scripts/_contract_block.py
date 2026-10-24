#!/usr/bin/env python3
"""Extract a delimited contract block, once, for every validator that needs one.

Separate copies of "find the text between two HTML comments" in
`check-agent-references.py` and `check-readonly-contract.py` diverge: a
duplicate-marker guard added to one and not the other leaves a second block
appended to a file silently unchecked in one validator and not the other.
`_frontmatter_common.py` states the convention this file follows — the rules that
must agree are imported from one place so that they do agree.

The leading underscore keeps it out of `run-tests.sh`'s `check-*.py` validator glob.
"""

DUPLICATE = "DUPLICATE-CONTRACT-BLOCK"
MISSING = "NO-CONTRACT-BLOCK"


def extract(text, open_marker, close_marker):
    """(body, None) when exactly one well-formed block exists, else (None, (code, why)).

    A duplicate pair is reported rather than resolved: picking the first silently
    leaves the second unchecked, and picking "all of them" invents a rule about which
    one is the contract. One block per file, or the file says which it means.
    """
    n_open, n_close = text.count(open_marker), text.count(close_marker)
    if n_open > 1 or n_close > 1:
        return None, (DUPLICATE,
                      f"{n_open} open / {n_close} close markers; exactly one contract "
                      f"block per file, or only one of them is ever checked")
    if n_open == 0 or n_close == 0 or text.index(close_marker) < text.index(open_marker):
        return None, (MISSING,
                      f"no `{open_marker}` … `{close_marker}` block; the contract is "
                      f"checked only inside it, because prose elsewhere cannot be told "
                      f"from a decoy")
    body = text[text.index(open_marker) + len(open_marker):text.index(close_marker)]
    return body, None


def span(text, open_marker, close_marker):
    """1-indexed (first, last) line numbers the block occupies, or None if absent.

    Used to exclude a block's interior from a sweep over the same file. Returns None
    for a malformed or duplicated block so the caller excludes nothing rather than
    guessing a range — a wrong exclusion hides real findings, which is the failure
    this helper exists to make impossible to introduce in only one of two places.
    """
    body, err = extract(text, open_marker, close_marker)
    if err is not None:
        return None
    first = text[:text.index(open_marker)].count("\n") + 1
    last = text[:text.index(close_marker) + len(close_marker)].count("\n") + 1
    return first, last


def first_difference(actual, expected):
    """The first word where two flattened texts diverge, with context from each side.

    Both required-literal validators emit this message shape. Shared because a message a
    reader learns to parse in one validator should not read differently in its sibling.
    """
    a, b = actual.split(" "), expected.split(" ")
    for i in range(max(len(a), len(b))):
        if i >= len(a) or i >= len(b) or a[i] != b[i]:
            return (f"at word {i + 1}: block has "
                    f"…{' '.join(a[max(0, i - 4):i + 6]) or '<end>'}… / canonical has "
                    f"…{' '.join(b[max(0, i - 4):i + 6]) or '<end>'}…")
    return "no textual difference (a substitution slot did not match its constraint)"


def pinned_population(expected, present, noun):
    """[] when every pinned member is present, else a one-line reason it is not.

    A pinned SET, not a floor. Any N members satisfy a floor of N, so removing one member
    while adding another keeps the count whole and the sweep silent — and a duplicated entry
    keeps the length whole while a real member leaves. Both directions are checked here, once,
    rather than in two copies of the same seven lines.
    """
    dupes = len(expected) != len(set(expected))
    missing = [rel for rel in expected if rel not in present]
    out = []
    if dupes:
        out.append(f"the pinned {noun} set has a duplicate member, so its length is not its "
                   f"population — that is the floor failure it exists to prevent")
    if missing:
        out.append(f"{len(missing)} expected {noun}(s) no longer qualify: "
                   f"{', '.join(missing)} — the sweep is wrong, or it really moved and the "
                   f"pinned set needs the deliberate edit")
    return out


def flat(s):
    """Prose with whitespace collapsed — an instruction is a sentence, not a line."""
    return " ".join(s.split())
