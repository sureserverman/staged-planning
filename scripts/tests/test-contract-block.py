#!/usr/bin/env python3
"""Fixture tests for scripts/_contract_block.py.

This helper is the one place that finds the text between two markers, so a malformed
file — two blocks, an unclosed block, a CLOSE before its OPEN — is the same finding in
every validator that reads one. Copies of this logic drift apart, and then one validator
flags a file the other cannot see. The cases below pin each answer once, so both
consumers inherit it.

Stdlib only.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "_contract_block.py"

spec = importlib.util.spec_from_file_location("cb", SCRIPT)
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

O, C = "<!-- x -->", "<!-- /x -->"
FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def main():
    print("_contract_block — extract:")
    body, err = cb.extract(f"a\n{O}\nrule\n{C}\nb\n", O, C)
    check(err is None and body.strip() == "rule", "a well-formed block yields its body")

    _, err = cb.extract("no markers here\n", O, C)
    check(err and err[0] == cb.MISSING, "no markers is NO-CONTRACT-BLOCK")

    _, err = cb.extract(f"{C}\nbody\n{O}\n", O, C)
    check(err and err[0] == cb.MISSING, "CLOSE before OPEN is not a block")

    _, err = cb.extract(f"{O}\none\n{C}\n{O}\ntwo\n{C}\n", O, C)
    check(err and err[0] == cb.DUPLICATE,
          "TWO blocks is DUPLICATE, not silently the first — resolving to the first "
          "would leave a second, contradicting block unchecked")

    _, err = cb.extract(f"{O}\nbody\n", O, C)
    check(err and err[0] == cb.MISSING, "an unclosed block is not a block")

    body, err = cb.extract(f"{O}{C}", O, C)
    check(err is None and body == "",
          "an EMPTY block extracts cleanly — emptiness is the caller's judgment to make, "
          "not a parse error, and both callers do reject it")

    print("_contract_block — span:")
    text = f"line1\n{O}\nrule\n{C}\nafter\n"
    check(cb.span(text, O, C) == (2, 4), "span is 1-indexed and inclusive of both markers")
    check(cb.span("nothing\n", O, C) is None, "no block means no span, not a guessed one")
    check(cb.span(f"{O}\na\n{C}\n{O}\nb\n{C}\n", O, C) is None,
          "a DUPLICATED block yields no span — excluding a guessed range would hide genuine "
          "findings, which is worse than excluding nothing")

    print("_contract_block — first_difference:")
    check("at word 3" in cb.first_difference("a b X d", "a b c d"),
          "the first differing word is located, 1-indexed")
    check("at word 3" in cb.first_difference("a b", "a b c"),
          "a text that simply RUNS OUT diverges at the first missing word, not at its end "
          "— a prefix must never read as a match")
    check("<end>" in cb.first_difference("", "a b c"),
          "an empty side renders as <end> rather than as blank context")
    check(cb.first_difference("a b c", "a b c").startswith("no textual difference"),
          "identical texts say so explicitly — a caller that reached here has a slot "
          "mismatch, not a word mismatch, and the message must not imply otherwise")

    print("_contract_block — pinned_population:")
    check(cb.pinned_population(("a", "b"), {"a", "b"}, "agent") == [],
          "a fully present pinned set is silent")
    out = cb.pinned_population(("a", "b"), {"a"}, "agent")
    check(len(out) == 1 and "b" in out[0], "a missing member is named, not counted")
    dup = cb.pinned_population(("a", "a"), {"a"}, "agent")
    check(any("duplicate" in w for w in dup),
          "a DUPLICATED member is a finding even though every member is present — the "
          "length is then not the population, which is the floor failure the pinned set "
          "exists to prevent")
    both = cb.pinned_population(("a", "a", "b"), {"a"}, "agent")
    check(len(both) == 2,
          "duplication and absence are reported independently — one must not mask the other")

    print("_contract_block — flat:")
    check(cb.flat("a\n  b\n\nc") == "a b c", "whitespace collapses to single spaces")

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
