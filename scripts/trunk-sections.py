#!/usr/bin/env python3
"""Bytes per `## ` section of a skill trunk, plus scaffolding, summing to the file size.

    python3 scripts/trunk-sections.py core/skills/honest-gates/SKILL.md

Prints one `<bytes>\t<heading>` line per top-level section (heading line included,
up to the next `## `), a `scaffolding` line for everything before the first
section (frontmatter, title, preamble), and a `TOTAL` line equal to `wc -c`. The
same accounting `scripts/check-trunk-budget.py` uses for the whole file, split by
section, so an extraction classification's `bytes` / `retained` columns can be
emitted by this command at a sha rather than typed: a figure nobody can
re-take is not a measurement.

Not a validator — the `check-*.py` prefix is reserved for guards the runner
discovers, and this only reports. Headings are taken outside fenced blocks via
the shared `_skill_sections` walker, so a `## ` inside a code block does not
start a section here and yet does count toward the section it sits in.
"""
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location(
    "_skill_sections", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "_skill_sections.py"))
_sections = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sections)


def sections(text, all_levels=False):
    """[(heading or 'scaffolding', bytes)] in document order; bytes sum to len(text).

    Default: one row per `## ` section, sub-headings counted inside their parent.
    `all_levels`: one row per heading of any level (`##`–`####`), each running to the
    next heading of any level — the accounting an extraction classification with
    per-sub-heading rows uses (executing-plans has 32 such rows)."""
    out, cur, buf = [], "scaffolding", []
    for is_heading, heading, raw in _sections._walk(text):
        if is_heading and (all_levels or raw.startswith("## ")):
            out.append((cur, len("\n".join(buf).encode("utf-8"))))
            cur, buf = heading, [raw]
        else:
            buf.append(raw)
    out.append((cur, len("\n".join(buf).encode("utf-8"))))
    # `_walk` splits on "\n"; the joins above drop exactly len(out)-1 separators
    # plus the file's trailing newline. Charge each section its own newline so
    # the rows sum to the byte size `wc -c` reports and nothing is unaccounted.
    fixed = []
    for i, (name, n) in enumerate(out):
        fixed.append((name, n + (1 if i < len(out) - 1 else 0)))
    total = sum(n for _, n in fixed)
    size = len(text.encode("utf-8"))
    if total != size:  # trailing-newline accounting
        name, n = fixed[-1]
        fixed[-1] = (name, n + (size - total))
    return fixed


def main(argv):
    all_levels = "--all-levels" in argv
    args = [a for a in argv[1:] if a != "--all-levels"]
    if len(args) != 1:
        print(__doc__.strip().split("\n")[0] + "  [--all-levels]", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as fh:
        text = fh.read()
    rows = sections(text, all_levels)
    for name, n in rows:
        print(f"{n}\t{name}")
    print(f"{sum(n for _, n in rows)}\tTOTAL")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
