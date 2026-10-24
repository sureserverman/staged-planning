#!/usr/bin/env python3
"""Guard: a plugin's prose description must not drift from its own `skills[]`.

Each plugin manifest carries a prose description, which may name the plugin's
skills, and the root marketplace entry mirrors it verbatim. Both can drift
without anyone noticing: a skill ships in `skills[]` but is never named in the
prose, or the "N-skill" count is bumped while the enumeration behind it is not. A count and a list that disagree are
worse than either alone — the count says the reader has seen everything.

Checks, per plugin:

  1. the marketplace entry's description is byte-identical to the manifest's —
     always, since the two are declared mirrors;
  2. a leading "<Number>-skill" claim equals `len(skills)`;
  3. every entry in `skills[]` is named somewhere in the description — but ONLY
     for a plugin that makes such a count claim. A thematic description that
     never promises exhaustiveness may legitimately name a subset; "N-skill" is
     the specific claim that tells the reader they have seen all N, and it is
     that pairing which drifts. This repo's one plugin, `planning`, makes no count
     claim, so checks 2 and 3 only bite once a description makes one.

Exit 0 when clean, 1 with a per-plugin report otherwise.
Run: python3 scripts/check-plugin-description-sync.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
sys.path.insert(0, str(ROOT / "scripts"))
from _layout import find_in, source_dirs  # noqa: E402

# Only the leading claim is checked; a plugin may legitimately omit it.
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}


def claimed_count(desc: str):
    """The N in a leading '<Number>-skill ...' claim, or None."""
    head = desc.split("-skill", 1)
    if len(head) < 2:
        return None
    word = head[0].strip().split()[-1].lower() if head[0].strip() else ""
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word)


def main() -> int:
    market = json.loads(MARKETPLACE.read_text())
    entries = {p["name"]: p for p in market.get("plugins", [])}
    problems: list[str] = []

    for entry in sorted(entries.values(), key=lambda p: p["name"]):
        name = entry["name"]
        source = entry.get("source", "")
        # The manifest is read from the plugin's sources, never the generated
        # copy. A missing one is drift, not a reason to skip the entry: a
        # skipped entry is a check that passes having compared nothing.
        found = find_in(source_dirs(str(ROOT), str(source)), ".claude-plugin/plugin.json")
        if found is None:
            problems.append(f"{name}: no .claude-plugin/plugin.json in the sources of {source}")
            continue
        manifest = Path(found)
        man = json.loads(manifest.read_text())
        desc = man.get("description", "")
        skills = [s.rsplit("/", 1)[-1] for s in man.get("skills", [])]

        n = claimed_count(desc)
        if n is not None and skills:
            if n != len(skills):
                problems.append(
                    f"{name}: description claims {n} skills, skills[] has {len(skills)}")
            # The count claim is what obliges the prose to be exhaustive.
            missing = [s for s in skills if s not in desc]
            if missing:
                problems.append(
                    f"{name}: description claims a skill count but never names "
                    f"{', '.join(missing)}")

        if entry.get("description") != desc:
            problems.append(
                f"{name}: marketplace entry description differs from "
                f"{manifest.relative_to(ROOT)} — the two are mirrors and must match")

    if problems:
        print("plugin description drift:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"OK — {len(entries)} plugin descriptions agree with their skills[] and mirrors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
