#!/usr/bin/env python3
"""Fixture tests for scripts/check-extraction-classification.py.

The load-bearing case is that this is a SET equality check, not a count check:
a table that drops one heading and invents one row has the right count and the
wrong classification, and a counting check passes it. Stdlib only.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-extraction-classification.py")

spec = importlib.util.spec_from_file_location("cls", SCRIPT)
cls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cls)

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def table(rows, klass="unconditional"):
    out = [f"### {klass} — n sections", "| bytes | retained | section | reason |",
           "|---|---|---|---|"]
    for name, reason in rows:
        out.append(f"| 100 | 100 | {name} | {reason} |")
    return "\n".join(out) + "\n"


def parse_cases():
    heads = cls.trunk_headings("## Alpha\ntext\n### Beta\n#### Gamma\n##### TooDeep\n")
    check(heads == ["Alpha", "Beta", "Gamma"],
          "headings ##..#### collected, ##### ignored")

    rows = cls.table_rows(table([("Alpha", "because it binds every run")]))
    check(rows == [("Alpha", "unconditional", "because it binds every run")],
          "row carries section, class from its enclosing heading, and reason")

    # A heading inside a fence is sample content, not a section of the trunk.
    # planning-projects/SKILL.md prints a `## Decisions in force` example inside a
    # ```markdown fence to show an author what to write; a fence-blind scan reports
    # it as this skill's own section and the table then has to file a decision
    # about a code sample — a row that fails the day the example is edited.
    fenced = cls.trunk_headings(
        "## Real\ntext\n\n```markdown\n## Sample\n- not a section\n```\n\n## AlsoReal\n")
    check(fenced == ["Real", "AlsoReal"],
          "a heading inside a ``` fence is not a trunk section")

    check(cls.trunk_headings("## Real\n\n~~~\n## Tilde\n~~~\n") == ["Real"],
          "~~~ fences are honoured too")

    # An unterminated fence swallows the rest of the file. That is the correct
    # reading of the markdown, and reporting fewer headings is the safe direction:
    # it fails set equality loudly rather than certifying a section nobody classified.
    check(cls.trunk_headings("## Real\n```\n## Swallowed\n") == ["Real"],
          "an unclosed fence hides what follows, and fails loudly downstream")


def set_equality_cases():
    with tempfile.TemporaryDirectory() as root:
        t = os.path.join(root, "trunk.md")
        c = os.path.join(root, "cls.md")

        def run():
            return cls.check_pair(root, "trunk.md", "cls.md")

        open(t, "w").write("## Alpha\nx\n## Beta\ny\n")
        open(c, "w").write(table([("Alpha", "reason enough here"),
                                  ("Beta", "reason enough here")]))
        check(run() == [], "matching sets pass")

        # The end-to-end version of the fence case: a trunk whose only extra
        # heading is inside a fence needs NO row for it, and gets no complaint.
        open(t, "w").write("## Alpha\nx\n\n```markdown\n## Sample\n```\n\n## Beta\ny\n")
        open(c, "w").write(table([("Alpha", "reason enough here"),
                                  ("Beta", "reason enough here")]))
        check(run() == [], "a fenced heading demands no classification row")

        # And the converse: filing a row for one is caught, so the table cannot
        # quietly classify a code sample either.
        open(c, "w").write(table([("Alpha", "reason enough here"),
                                  ("Beta", "reason enough here"),
                                  ("Sample", "reason enough here")]))
        check(any("no such heading" in x and "Sample" in x for x in run()),
              "a row naming a fenced heading is rejected")

        # Heading present, row absent
        open(c, "w").write(table([("Alpha", "reason enough here")]))
        p = run()
        check(len(p) == 1 and "not classified" in p[0], "unclassified heading is caught")

        # THE case: one dropped, one invented — counts match, sets do not
        open(c, "w").write(table([("Alpha", "reason enough here"),
                                  ("Ghost", "reason enough here")]))
        p = run()
        check(len(p) == 2, "drop-one/invent-one is caught (a count check would pass)")
        check(any("not classified" in x for x in p) and
              any("no such heading" in x for x in p),
              "both directions reported, not just one")

        # A row with no usable reason
        open(c, "w").write(table([("Alpha", "reason enough here"), ("Beta", "x")]))
        check(any("no usable reason" in x for x in run()), "empty reason is caught")

        # A class that is not one of the three
        open(c, "w").write(table([("Alpha", "reason enough here"),
                                  ("Beta", "reason enough here")], klass="whatever"))
        check(any("no valid class" in x for x in run()),
              "an unrecognised class heading yields no rows, so its headings read unclassified")

        # The case above has the invalid heading FIRST, so klass is never set.
        # The dangerous case is an invalid heading FOLLOWING a valid one: rows
        # under it that inherit the preceding class silently move a binding
        # section out of the retention sweep with both guards green.
        open(t, "w").write("## Alpha\nx\n## Beta\ny\n")
        open(c, "w").write(
            table([("Alpha", "reason enough here")])
            + "\n### deleted — rows kept for history\n"
            + "| bytes | retained | section | reason |\n|---|---|---|---|\n"
            + "| 200 | 0 | Beta | was removed, kept for the record |\n")
        check(any("no valid class" in x and "Beta" in x for x in run()),
              "a row under an invalid class heading does NOT inherit the preceding class")

        # Duplicate heading text defeats set equality — must be reported
        open(t, "w").write("## Alpha\nx\n## Alpha\ny\n")
        open(c, "w").write(table([("Alpha", "reason enough here")]))
        check(any("duplicate heading" in x for x in run()), "duplicate heading text is caught")

        # A missing classification file is a failure, not a skip
        os.remove(c)
        check(any("missing" in x for x in run()), "absent classification file fails")


def figure_cases():
    """A stated figure that the command would not re-take is reported, kind by kind."""
    with tempfile.TemporaryDirectory() as root:
        trunk = "---\nname: x\n---\n# T\n\n## Alpha\nab\n## Beta\ncdef\n"
        open(os.path.join(root, "trunk.md"), "w").write(trunk)
        sizes = cls._sizes(os.path.join(root, "trunk.md"))
        a, b, s = sizes["Alpha"], sizes["Beta"], sizes["scaffolding"]

        def doc(alpha=a, head=None, markers_alpha=1, header=None, extra=""):
            head = head if head is not None else (2, a + b)
            header = header if header is not None else (a + b, 2, s)
            return (f"**{header[0]} B** across **{header[1]} headings**, plus {header[2]} B "
                    f"of scaffolding.\n\n### unconditional — {head[0]} sections, {head[1]} B\n\n"
                    "| bytes | markers | section | reason |\n|---|---|---|---|\n"
                    f"| {alpha} | {markers_alpha} | Alpha | reason enough here |\n"
                    f"| {b} | 1 | Beta | reason enough here |\n{extra}\n"
                    "## Retention markers\n\n| section | marker |\n|---|---|\n"
                    "| Alpha | ab |\n| Beta | cdef |\n")

        def run(text, host=None):
            open(os.path.join(root, "cls.md"), "w").write(text)
            return cls.check_figures(root, "trunk.md", "cls.md", host)

        check(run(doc()) == [], "true figures pass")
        check(any("'Alpha' says" in p and "B, the trunk has" in p for p in run(doc(alpha=a + 1))),
              "a stale bytes cell is caught")
        check(any("`### unconditional` says" in p for p in run(doc(head=(2, a + b + 5)))),
              "a stale class-heading total is caught")
        check(any("header says" in p for p in run(doc(header=(a + b, 3, s)))),
              "a stale header heading count is caught")
        check(any("marker(s)" in p for p in run(doc(markers_alpha=2))),
              "a stale markers cell is caught")
        check(any("no `**X B** across" in p for p in run(doc().split("\n\n", 1)[1])),
              "a table with no header figure is caught")
        # A host-only row is measured on the host trunk, never reported against core.
        open(os.path.join(root, "host.md"), "w").write(trunk + "## Host notes\nhhhhhh\n")
        hn = cls._sizes(os.path.join(root, "host.md"))["Host notes"]
        row = f"| {hn} | 0 | Host notes | added by the host |\n"
        check(run(doc(head=(3, a + b + hn), extra=row), "host.md") == [],
              "a host-only row is measured on the host trunk")
        stale = row.replace(f"| {hn} |", f"| {hn + 1} |")
        check(any("'Host notes' says" in p
                  for p in run(doc(head=(3, a + b + hn + 1), extra=stale), "host.md")),
              "a stale host-only row is caught")
        check(any("header says" in p for p in run(doc(header=(a + b + 1, 2, s)))),
              "a stale header total is caught")
        check(any("header says" in p for p in run(doc(header=(a + b, 2, s + 1)))),
              "a stale header scaffolding figure is caught")
        check(any("class heading" in p for p in run(
            doc().replace(f"### unconditional — 2 sections, {a + b} B", "### unconditional — two sections"))),
              "a class heading the figure check cannot read is reported, not skipped")


def override_main_case():
    """main() checks a host override table's figures, and exits 1 on a stale one."""
    import shutil
    with tempfile.TemporaryDirectory() as root:
        trunk_rel, table_rel = cls.PAIRS[2]
        for rel in (trunk_rel, table_rel):
            os.makedirs(os.path.join(root, os.path.dirname(rel)), exist_ok=True)
            shutil.copy(os.path.join(cls.REPO_ROOT, rel), os.path.join(root, rel))
        override = os.path.join(root, "hosts", "x", "overrides", os.path.relpath(table_rel, "core"))
        os.makedirs(os.path.dirname(override))
        shutil.copy(os.path.join(root, table_rel), override)
        check(cls.main(["--root", root]) == 0, "a true host override table passes main()")
        text = open(override).read()
        row = next(l for l in text.split("\n") if l.startswith("| ") and l.split("|")[1].strip().isdigit())
        n = row.split("|")[1].strip()
        open(override, "w").write(text.replace(row, row.replace(f"| {n} |", f"| {int(n) + 1} |", 1), 1))
        check(cls.main(["--root", root]) == 1, "a stale host override table makes main() exit 1")


def exit_code_cases():
    with tempfile.TemporaryDirectory() as root:
        check(cls.main(["--root", root]) == 0,
              "a tree with no classified trunks exits 0 and reports the count")



def pinned_missing_case():
    """In the repo's own tree a pinned trunk that is gone is PINNED-MISSING, exit 1.

    A fixture --root skips absent trunks by design, so this runs a COPY of the script
    in a tree of its own: there REPO_ROOT is the copy's root, which holds no trunks.
    """
    import shutil
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(os.path.dirname(SCRIPT), os.path.join(tmp, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__", "tests"))
        r = subprocess.run([sys.executable, os.path.join(tmp, "scripts", os.path.basename(SCRIPT))],
                           capture_output=True, text=True)
        check(r.returncode == 1 and "PINNED-MISSING" in r.stdout,
              f"a pinned trunk missing from the repo's own tree is PINNED-MISSING and exits 1 "
              f"(rc={r.returncode})")

if __name__ == "__main__":
    print("parsing:")
    parse_cases()
    print("set equality:")
    set_equality_cases()
    print("figures:")
    figure_cases()
    override_main_case()
    print("exit codes:")
    exit_code_cases()
    print("pinned trunks in the repo's own tree:")
    pinned_missing_case()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
