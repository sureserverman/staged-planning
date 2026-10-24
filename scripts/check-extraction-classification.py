#!/usr/bin/env python3
"""Every trunk heading is classified, and every classified row is a real heading.

An extraction classification decides what may leave a trunk. A heading missing
from the table is a section nobody decided about, and it will be moved or kept by
whoever happens to be editing — which is exactly the ungoverned drift the
classification exists to replace. A row naming no real heading is a decision
about nothing, usually a heading that was renamed after the table was written.

Both directions matter, so this is a SET EQUALITY check, not a count comparison:
two mistakes that cancel (one heading dropped, one row invented) leave the counts
identical and the classification wrong.

Pairs a trunk with its `references/extraction-classification.md`, and checks the
figures (not the heading set) of every host override of such a table. Read-only. Exit 0 when the sets match, every row
carries a class and a reason, and every figure a table states (bytes, markers, class
totals, header) is the one `trunk-sections.py` re-takes; 1 otherwise.
"""
import argparse
import importlib.util
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Trunks that must carry a classification, and where it lives.
PAIRS = [
    ("core/skills/executing-plans/SKILL.md",
     "core/skills/executing-plans/references/extraction-classification.md"),
    ("core/skills/planning-projects/SKILL.md",
     "core/skills/planning-projects/references/extraction-classification.md"),
    ("core/skills/honest-gates/SKILL.md",
     "core/skills/honest-gates/references/extraction-classification.md"),
]

VALID_CLASSES = ("unconditional", "rule+elaboration", "conditional")

# Fence-aware heading extraction, shared with check-trunk-retention.py so the two
# guards cannot disagree about what counts as a section. See that module's
# docstring for why a `^#{2,4} ` regex alone is wrong here.
_spec = importlib.util.spec_from_file_location(
    "_skill_sections", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "_skill_sections.py"))
_sections = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sections)


def trunk_headings(text):
    return _sections.headings(text)


def table_rows(text):
    """(section, klass, reason) per table row, keyed off the section column.

    Rows live under `### <class> — ...` headings; the class comes from the
    enclosing heading rather than a column, so a row cannot disagree with the
    section it is filed under.

    Delegates to the SHARED parser so this guard and check-trunk-retention.py
    cannot disagree about what a row is. Malformed rows (a non-numeric bytes
    cell) are still returned here — this guard's job is set equality, and a
    malformed row still names a section that must exist — but `malformed_rows()`
    reports them, because a row this guard accepts and the retention guard drops
    is a silent divergence.
    """
    return [(s, k, r) for s, k, r, _bad in _sections.class_rows(text)]


def malformed_rows(text):
    """Sections whose row has a non-numeric bytes cell."""
    return [s for s, _k, _r, bad in _sections.class_rows(text) if bad]


def check_pair(root, trunk_rel, table_rel):
    problems = []
    trunk_path = os.path.join(root, trunk_rel)
    table_path = os.path.join(root, table_rel)
    if not os.path.exists(table_path):
        return [f"{table_rel}: missing — {trunk_rel} has no classification"]

    heads = trunk_headings(open(trunk_path, encoding="utf-8").read())
    rows = table_rows(open(table_path, encoding="utf-8").read())

    in_table = {r[0] for r in rows}
    in_trunk = set(heads)
    for missing in sorted(in_trunk - in_table):
        problems.append(f"{table_rel}: heading not classified — {missing!r}")
    for extra in sorted(in_table - in_trunk):
        problems.append(f"{table_rel}: row names no such heading — {extra!r}")

    if len(heads) != len(in_trunk):
        dupes = [h for h in in_trunk if heads.count(h) > 1]
        problems.append(f"{trunk_rel}: duplicate heading text {sorted(dupes)!r} — "
                        "set equality cannot distinguish them")

    for section, klass, reason in rows:
        if klass not in VALID_CLASSES:
            problems.append(f"{table_rel}: {section!r} has no valid class")
        if not reason or len(reason) < 12:
            problems.append(f"{table_rel}: {section!r} has no usable reason")
    return problems


_ts_spec = importlib.util.spec_from_file_location(
    "trunk_sections", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "trunk-sections.py"))
_ts = importlib.util.module_from_spec(_ts_spec)
_ts_spec.loader.exec_module(_ts)


def _sizes(path):
    """{heading or 'scaffolding': bytes}, the accounting trunk-sections.py prints."""
    return dict(_ts.sections(open(path, encoding="utf-8").read(), all_levels=True))


def check_figures(root, trunk_rel, table_rel, host_trunk_rel=None):
    """Every figure a table states is the one its command re-takes.

    A table's header says its figures are re-taken from the trunk and that one that
    disagrees is stale; unchecked, such figures drift with every trunk edit.
    Checked here: each row's bytes cell, each `markers` cell against the retention
    table, each `### <class> — N sections, X B` heading against its rows, and the
    header's total, heading count and scaffolding. A host override's table records the
    source trunk (`trunk_rel`); a row naming a heading only the host trunk has is
    measured there."""
    problems = []
    table_path = os.path.join(root, table_rel)
    if not os.path.exists(table_path):
        return problems
    text = open(table_path, encoding="utf-8").read()
    core = _sizes(os.path.join(root, trunk_rel))
    host = _sizes(os.path.join(root, host_trunk_rel)) if host_trunk_rel else {}
    marker_count = {}
    if "## Retention markers" in text:
        tail = text.split("## Retention markers", 1)[1].split("\n## ", 1)[0]
        for line in tail.split("\n"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("|") and not line.startswith("|---") and len(cells) == 2 \
                    and cells[0] != "section":
                marker_count[cells[0]] = marker_count.get(cells[0], 0) + 1
    columns, klass, heads = [], None, {}
    for line in text.split("\n"):
        m = re.match(r"^### (\S+) — (\d+) sections?, (\d+) B$", line)
        if m:
            klass = m.group(1)
            heads[klass] = [int(m.group(2)), int(m.group(3)), 0, 0]
            continue
        if re.match(r"^### (unconditional|rule\+elaboration|conditional)\b", line):
            problems.append(f"{table_rel}: class heading {line!r} is not `### <class> — N "
                            "sections, X B`, so its rows' figures cannot be checked")
        if line.startswith("#"):
            klass = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or line.startswith("|---") or len(cells) < 4:
            continue
        if cells[0] == "bytes":
            columns = cells
            continue
        if klass not in heads or not cells[0].isdigit():
            continue
        name = cells[2]
        want = core.get(name, host.get(name))
        if want is None:
            continue    # check_pair names a row that is no heading
        heads[klass][2] += 1
        heads[klass][3] += int(cells[0])
        if int(cells[0]) != want:
            problems.append(f"{table_rel}: {name!r} says {cells[0]} B, the trunk has {want} B")
        if len(columns) > 1 and columns[1] == "markers" and cells[1].isdigit() \
                and int(cells[1]) != marker_count.get(name, 0):
            problems.append(f"{table_rel}: {name!r} says {cells[1]} marker(s), the retention "
                            f"table has {marker_count.get(name, 0)}")
    for klass, (n, b, rows, total) in heads.items():
        if (n, b) != (rows, total):
            problems.append(f"{table_rel}: `### {klass}` says {n} sections, {b} B; its rows "
                            f"are {rows} sections, {total} B")
    secs = sum(v for k, v in core.items() if k != "scaffolding")
    count, scaff = len(core) - 1, core["scaffolding"]
    m = re.search(r"\*\*(\d+) B\*\* across\s+\*\*(\d+) headings\*\*, (plus|of which) (\d+) B", text)
    if not m:
        problems.append(f"{table_rel}: no `**X B** across **N headings**` header figure")
    else:
        stated = (int(m.group(1)), int(m.group(2)), int(m.group(4)))
        total = secs + scaff if m.group(3) == "of which" else secs
        if stated != (total, count, scaff):
            problems.append(f"{table_rel}: header says {stated[0]} B, {stated[1]} headings, "
                            f"{stated[2]} B scaffolding; the trunk has {total} B, {count}, {scaff} B")
    return problems


def override_pairs(root):
    """(core trunk, override table, override trunk or None) for every host override of a
    pinned classification table."""
    out = []
    hosts = os.path.join(root, "hosts")
    for host in sorted(os.listdir(hosts)) if os.path.isdir(hosts) else []:
        for trunk_rel, table_rel in PAIRS:
            table = os.path.join("hosts", host, "overrides", os.path.relpath(table_rel, "core"))
            if os.path.exists(os.path.join(root, table)):
                own = os.path.join("hosts", host, "overrides", os.path.relpath(trunk_rel, "core"))
                out.append((trunk_rel, table,
                            own if os.path.exists(os.path.join(root, own)) else None))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-extraction-classification")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)

    pairs = [(t, c) for t, c in PAIRS
             if os.path.exists(os.path.join(args.root, t))]
    problems = []
    # A fixture root carries only the trunks its case needs, so a missing one is
    # skipped there. In this repo's own tree a pinned trunk that is gone is a
    # finding: skipping it would let this check report "0 trunk(s)" and pass
    # after a layout move.
    if os.path.realpath(args.root) == os.path.realpath(REPO_ROOT):
        problems += [f"{t}: PINNED-MISSING — a pinned trunk does not exist"
                     for t, _ in PAIRS if not os.path.exists(os.path.join(args.root, t))]
    for trunk_rel, table_rel in pairs:
        problems += check_pair(args.root, trunk_rel, table_rel)
        problems += check_figures(args.root, trunk_rel, table_rel)
    overrides = [o for o in override_pairs(args.root)
                 if os.path.exists(os.path.join(args.root, o[0]))]
    for trunk_rel, table_rel, own in overrides:
        problems += check_figures(args.root, trunk_rel, table_rel, own)

    # honest-gates: state the population examined, so an empty sweep cannot read
    # as a pass over something.
    print(f"{len(pairs)} classified trunk(s) and {len(overrides)} host override table(s) "
          f"checked; {len(problems)} problem(s).")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
