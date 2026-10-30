#!/usr/bin/env python3
"""Fixture tests for scripts/check-extraction-integrity.py.

Builds a synthetic plugin tree in a temp dir and asserts the scanner's
contract: dead relative paths, unresolved positional deixis, unresolved
section refs, the comparison/qualified exclusions that keep it honest,
allowlist suppression, --scope, --list-allowlisted, and exit codes.

The exclusion cases are the load-bearing ones. A guard that flags
"opt in below `high`" as deixis trains its readers to allowlist
everything, which is how a guard stops guarding. Stdlib only.
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "check-extraction-integrity.py")

spec = importlib.util.spec_from_file_location("integrity", SCRIPT)
integrity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integrity)

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def codes(findings):
    return sorted(f["code"] for f in findings)


def scan(text, name="p/skills/s/references/r.md", root=None):
    """Scan one synthetic file; returns findings."""
    return integrity.scan_file(name, text, root or "/nonexistent")


def dead_path_cases():
    with tempfile.TemporaryDirectory() as root:
        ref = "p/skills/s/references/r.md"
        write(os.path.join(root, ref), "x")
        write(os.path.join(root, "p/skills/s/references/sibling.md"), "x")
        write(os.path.join(root, "p/skills/s/SKILL.md"), "x")

        # Resolves from the file's own directory -> clean
        f = integrity.scan_file(ref, "See `sibling.md` for detail.\n", root)
        check(codes(f) == [], "existing sibling path not flagged")

        f = integrity.scan_file(ref, "See `../SKILL.md` for detail.\n", root)
        check(codes(f) == [], "existing ../ path not flagged")

        # Does not resolve under any convention -> DEAD-PATH
        f = integrity.scan_file(ref, "See `../references/missing.md` for detail.\n", root)
        check(codes(f) == ["DEAD-PATH"], "unresolvable internal reference flagged")
        check(f[0]["token"] == "../references/missing.md", "DEAD-PATH token is the path")

        # Markdown link form
        f = integrity.scan_file(ref, "See [detail](./references/gone.md).\n", root)
        check(codes(f) == ["DEAD-PATH"], "markdown link to missing file flagged")

        # Absolute/external are not our business
        f = integrity.scan_file(ref, "See [x](https://example.com) and `/etc/hosts`.\n", root)
        check(codes(f) == [], "http and absolute paths not flagged")

        # A path inside a fenced command block still resolves the same way
        f = integrity.scan_file(ref, "```bash\npython3 ../scripts/missing.py\n```\n", root)
        check(codes(f) == ["DEAD-PATH"], "unresolvable path inside a fence flagged")

        # --- only THIS repo's own files are in scope ---
        # Treating every path-ish token as internal floods the check with paths
        # that belong to the projects a plan targets, so none of these is flagged.
        for text, why in [
            ("Write `site/content/en-GB/tagline.txt` (<= 40 chars).\n",
             "target-project path"),
            ("Draft `deploy/regions/<serviceName>.yml` with the hash.\n",
             "templated <placeholder> path"),
            ("|   +-- `long_summary.txt`\n", "bare filename in a tree diagram"),
            ("Scans `*/agents/*.md` from the repo root.\n", "glob pattern"),
            ("See `~/.claude/skills/code-review/SKILL.md`.\n", "home-relative path"),
        ]:
            check(codes(integrity.scan_file(ref, text, root)) == [],
                  f"not flagged: {why}")

    # Plugin-rooted citation resolves against the plugin dir (the plugin-rooted form)
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "kit/skills/draft/SKILL.md"), "x")
        write(os.path.join(root, "kit/references/draft-format.md"), "x")
        f = integrity.scan_file("kit/skills/draft/SKILL.md",
                                "Format in `references/draft-format.md`.\n", root)
        check(codes(f) == [], "plugin-rooted reference resolves from the plugin dir")
        f = integrity.scan_file("kit/skills/draft/SKILL.md",
                                "Format in `references/absent.md`.\n", root)
        check(codes(f) == ["DEAD-PATH"], "plugin-rooted reference to a missing file flagged")


def link_target_cases():
    """A markdown link target is a reference by construction.

    is_internal_ref demands a structural marker or a SKILL.md suffix, which is
    right for a BARE token -- skill prose cites the user's project paths
    constantly. But `[text](target)` promises the reader can follow it, so the
    marker is not needed to establish intent. Two screens still apply: a
    `<placeholder>` template is not a path, and a link displayed INSIDE a
    backtick span is quoted text illustrating a line, not a reference.
    """
    with tempfile.TemporaryDirectory() as root:
        rel = "p/skills/s/references/r.md"
        base = os.path.join(root, "p/skills/s/references")

        write(os.path.join(base, "r.md"), "[the tier table](tier-table.md)\n")
        f = integrity.scan_file(rel, "[the tier table](tier-table.md)\n", root)
        check(codes(f) == ["DEAD-PATH"],
              "a bare-filename LINK target is resolved and flagged when dead")
        check(f[0]["token"] == "tier-table.md", "the token is the link target")

        write(os.path.join(base, "tier-table.md"), "x\n")
        check(codes(integrity.scan_file(rel, "[t](tier-table.md)\n", root)) == [],
              "the same link resolves once the sibling exists")

        # A bare token is NOT resolved: skill prose cites the user's project paths.
        check(codes(integrity.scan_file(rel, "See `sibling-gone.md`.\n", root)) == [],
              "a bare filename outside a link is still not treated as internal")

        # A link quoted inside a backtick span: the case this screen exists for.
        quoted = "`- [auth](auth.md) - login, signup` is the index line format.\n"
        check(codes(integrity.scan_file(rel, quoted, root)) == [],
              "a link DISPLAYED inside a backtick span is quoted text, not a reference")

        placeholder = "[maturity](<records home>/MATURITY.md)\n"
        check(codes(integrity.scan_file(rel, placeholder, root)) == [],
              "a <placeholder> link target is a template, not a path")
        check(integrity.is_placeholder("<notes>/x.md"),
              "is_placeholder screens what is_pathish does not")


def positional_deixis_cases():
    # Genuine deixis in a reference file -> flagged
    for text, why in [
        ("Stop when the exit criterion above is met.\n", "'criterion above'"),
        ("Execute it via the normal flow below.\n", "'flow below'"),
        ("See Context resets below, scaled up.\n", "'resets below'"),
        ("The gate rules above close this.\n", "'rules above'"),
    ]:
        check(codes(scan(text)) == ["DEIXIS-POSITIONAL"], f"deixis flagged: {why}")

    # Comparisons are not deixis -> must NOT flag
    for text, why in [
        ("A task may opt in below `high` with Review: required.\n", "below `high`"),
        ("skipped when the tier is below `standard`.\n", "below `standard`"),
        ("narrows it only if it crosses above ~5 minutes.\n", "above ~5 minutes"),
        ("one rung below the standard staged plan\n", "below the standard (tier word)"),
        ("anything above 200 changed lines\n", "above 200"),
    ]:
        check(codes(scan(text)) == [], f"comparison not flagged: {why}")

    # Trunks are checked too. "above" resolves inside one file only until an
    # extraction splits it, so a guard that exempted trunks would be blind at the
    # moment it is needed.
    f = scan("Follow the escalation rules below when this fires.\n",
             name="p/skills/s/SKILL.md")
    check(codes(f) == ["DEIXIS-POSITIONAL"], "positional deixis in a trunk IS flagged")

    # Not deixis: the noun's referent is right there (rows, a table, a block),
    # or there is no noun phrase to resolve.
    for text, why in [
        ("A release cannot go out without passing every Core-level item below.\n"
         "| R1 | check | proof |\n", "'item below' with rows below it"),
        ("Only add a new helper when no entry below covers the need.\n"
         "| Need | Library | Custom |\n", "'entry below' with a table below it"),
        ("Write YAML following the structure above, then render.\n"
         "```yaml\nkind: widget\n```\n", "'structure above' with a block present"),
        ("The parse contract accepts any key (see above), so these work.\n",
         "bare '(see above)' — no noun phrase to resolve"),
    ]:
        check(codes(scan(text)) == [], f"not flagged: {why}")

    # A shell-quoted path inside a fence resolves to an existing file
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/scripts/teardown.sh"), "x")
        write(os.path.join(root, "p/skills/s/SKILL.md"), "x")
        f = integrity.scan_file(
            "p/skills/s/SKILL.md",
            "```bash\ntrap 'skills/s/scripts/teardown.sh --dry-run' EXIT\n```\n", root)
        check(codes(f) == [], "shell-quoted path in a fence is stripped and resolves")


def section_ref_cases():
    # Unqualified § naming no local heading -> flagged
    f = scan("Applies the class rule — § A bug found during execution is a class.\n")
    check(codes(f) == ["DEIXIS-SECTION"], "unqualified § with no local heading flagged")

    # Same ref, heading present in this file -> clean
    f = scan("## A bug found during execution is a class\n\nSee § A bug found during execution is a class.\n")
    check(codes(f) == [], "§ resolving to a local heading not flagged")

    # Qualified by a backticked path -> the reader can follow it
    f = scan("See `../../planning-projects/references/task-fields.md` § Scope marking.\n")
    check("DEIXIS-SECTION" not in codes(f), "§ qualified by a path not flagged")

    # Qualified by the word 'trunk' -> names where it lives
    f = scan("counted (trunk, § Remediation budget), never free.\n")
    check(codes(f) == [], "§ qualified by 'trunk' not flagged")

    # A trunk's own dangling § is still a dead pointer
    f = scan("See § Light plans, rule 2 for the detail.\n", name="p/skills/s/SKILL.md")
    check(codes(f) == ["DEIXIS-SECTION"], "dangling § in a trunk flagged")

    # Qualified by a filename in BARE prose, not backticks — the reader can
    # still open it, so the reference does not dangle.
    f = scan("as sizing-notes.md § Unit rounding requires, apply the rule.\n")
    check("DEIXIS-SECTION" not in codes(f), "§ qualified by a bare filename not flagged")

    # ...but the filename must be ADJACENT to the §, not merely nearby. A
    # proximity-only window suppresses a genuinely dangling reference whenever
    # an unrelated filename happens to precede it within 70 chars.
    f = scan("After the config.yml rewrite, the § Legacy Format section was dropped.\n")
    check(codes(f) == ["DEIXIS-SECTION"],
          "an unrelated nearby filename does NOT qualify a dangling §")

    # Containment must not let a SHORT dangling ref hide inside a LONG heading
    f = scan("## Scope of the review pass\n\nThe § Scope rules moved elsewhere.\n")
    check(codes(f) == ["DEIXIS-SECTION"],
          "short dangling § not masked by a longer unrelated heading")


def allowlist_cases():
    with tempfile.TemporaryDirectory() as root:
        ref = "p/skills/s/references/r.md"
        write(os.path.join(root, ref), "The gate rules above close this.\n")
        allow = os.path.join(root, "allow.txt")

        rc = integrity.main(["--root", root, "--allowlist", allow])
        check(rc == 1, "unallowlisted finding exits 1")

        entry = "p/skills/s/references/r.md:DEIXIS-POSITIONAL:rules above"
        write(allow, f"# reason\n{entry}  # a known debt, burned down later\n")
        rc = integrity.main(["--root", root, "--allowlist", allow])
        check(rc == 0, "exact allowlist entry suppresses the finding")

        # Near-miss must NOT suppress — exact match only
        write(allow, "p/skills/s/references/r.md:DEIXIS-POSITIONAL:rules below\n")
        rc = integrity.main(["--root", root, "--allowlist", allow])
        check(rc == 1, "near-miss allowlist entry does not suppress")

        # A bare path is not an entry — suppression is per finding, not per file
        write(allow, "p/skills/s/references/r.md\n")
        rc = integrity.main(["--root", root, "--allowlist", allow])
        check(rc == 1, "bare path does not suppress a whole file")

    # --- the allowlist is a MULTISET, not a set -------------------------------
    # Allowlisting one instance must not hide the next one in the same file.
    # Tokens are low-entropy, so under set membership a NEW dead pointer reusing
    # an allowlisted token would vanish: one line suppresses one occurrence.
    with tempfile.TemporaryDirectory() as root:
        ref = "p/skills/s/references/r.md"
        allow = os.path.join(root, "allow.txt")
        entry = "p/skills/s/references/r.md:DEIXIS-POSITIONAL:rules below"

        write(os.path.join(root, ref), "Follow the escalation rules below now.\n")
        write(allow, entry + "\n")
        check(integrity.main(["--root", root, "--allowlist", allow]) == 0,
              "one line suppresses one occurrence")

        # A SECOND, genuinely new instance of the same token must surface
        write(os.path.join(root, ref),
              "Follow the escalation rules below now.\n"
              "Apply the escalation rules below again.\n")
        check(integrity.main(["--root", root, "--allowlist", allow]) == 1,
              "a second occurrence of an allowlisted token is NOT absorbed")

        # Two lines cover two occurrences
        write(allow, entry + "\n" + entry + "\n")
        check(integrity.main(["--root", root, "--allowlist", allow]) == 0,
              "two lines suppress two occurrences")


def list_allowlisted_cases():
    with tempfile.TemporaryDirectory() as root:
        ref = "p/skills/s/references/r.md"
        write(os.path.join(root, ref), "The gate rules above close this.\n")
        allow = os.path.join(root, "allow.txt")
        entry = "p/skills/s/references/r.md:DEIXIS-POSITIONAL:rules above"
        write(allow, entry + "\n")
        out = integrity.list_allowlisted(allow)
        check(out == [entry], "--list-allowlisted returns the entries verbatim")
        check(integrity.list_allowlisted(os.path.join(root, "none.txt")) == [],
              "missing allowlist file lists nothing")


def scope_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "a/skills/s/references/r.md"),
              "The gate rules above close this.\n")
        write(os.path.join(root, "b/skills/s/references/r.md"),
              "The gate rules above close this.\n")
        allow = os.path.join(root, "none.txt")

        rc = integrity.main(["--root", root, "--allowlist", allow, "--scope", "a"])
        check(rc == 1, "--scope a still sees a's finding")

        write(os.path.join(root, "a/skills/s/references/r.md"), "clean text\n")
        rc = integrity.main(["--root", root, "--allowlist", allow, "--scope", "a"])
        check(rc == 0, "--scope a ignores b's finding")
        rc = integrity.main(["--root", root, "--allowlist", allow])
        check(rc == 1, "unscoped run still sees b's finding")


def empty_sweep_cases():
    """An empty sweep must not read as a pass.

    An empty tree exiting 0 is exactly the silent clean pass a typo'd --scope
    degrades to, so it exits 2.
    """
    with tempfile.TemporaryDirectory() as root:
        allow = os.path.join(root, "n.txt")
        rc = integrity.main(["--root", root, "--allowlist", allow])
        check(rc == 2, "empty tree exits 2, not a silent clean 0")
        files = integrity.discover(root, None)
        check(files == [], "empty tree discovers no files (count is reported, not implied)")
        rc = integrity.main(["--root", root, "--allowlist", allow, "--min-files", "0"])
        check(rc == 0, "--min-files 0 opts a legitimately empty scope back in")

    # The shape that matters most: a scope typo over a NON-empty tree.
    # Without the floor this is the worst shape, because the tree really does
    # hold findings and the run still reports a clean pass.
    with tempfile.TemporaryDirectory() as root:
        allow = os.path.join(root, "n.txt")
        write(os.path.join(root, "a/skills/s/references/r.md"),
              "The gate rules above close this.\n")
        check(integrity.main(["--root", root, "--allowlist", allow, "--scope", "a"]) == 1,
              "the correct scope sees the finding")
        check(integrity.main(["--root", root, "--allowlist", allow, "--scope", "aa"]) == 2,
              "a typo'd --scope fails loudly instead of passing clean")

    # The floor is a number, not a bare non-empty test: a scope matching FEWER
    # files than the caller expects is the same failure, one step subtler.
    with tempfile.TemporaryDirectory() as root:
        allow = os.path.join(root, "n.txt")
        write(os.path.join(root, "a/skills/s/references/r.md"), "clean\n")
        check(integrity.main(["--root", root, "--allowlist", allow]) == 0,
              "one clean file clears the default floor of 1")
        check(integrity.main(["--root", root, "--allowlist", allow, "--min-files", "5"]) == 2,
              "a floor above the discovered count fails")


def exclusion_cases():
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/references/r.md"), "clean\n")
        write(os.path.join(root, "p/skills/s/tests/fixtures/references/bad.md"),
              "The gate rules above close this.\n")
        rc = integrity.main(["--root", root, "--allowlist", os.path.join(root, "n.txt")])
        check(rc == 0, "tests/fixtures trees excluded from the scan")


def host_layer_cases():
    # A host's override is read from its built plugin, where core/ supplies every file
    # the host does not override: its relative paths resolve there, not beside it.
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "core/skills/s/SKILL.md"), "x")
        write(os.path.join(root, "core/skills/s/references/only-core.md"), "x")
        write(os.path.join(root, "hosts/h/add/skills/s/references/only-add.md"), "x")
        override = "hosts/h/overrides/skills/s/SKILL.md"
        write(os.path.join(root, override), "x")
        f = integrity.scan_file(override, "Read `references/only-core.md` first.\n", root)
        check(codes(f) == [], "an override's link to a file only core holds resolves")
        f = integrity.scan_file(override, "Read `references/only-add.md` first.\n", root)
        check(codes(f) == [], "an override's link to its host's add/ file resolves")
        f = integrity.scan_file(override, "Read `references/missing.md` first.\n", root)
        check(codes(f) == ["DEAD-PATH"], "a link no layer holds is still dead")
        other = "hosts/other/overrides/skills/s/SKILL.md"
        write(os.path.join(root, other), "x")
        f = integrity.scan_file(other, "Read `references/only-add.md` first.\n", root)
        check(codes(f) == ["DEAD-PATH"], "another host's add/ file does not resolve for it")


def run_main(argv):
    """main()'s exit code and everything it printed to stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = integrity.main(argv)
    return rc, buf.getvalue()


def referent_cases():
    """A pointer whose referent was extracted away, pointer left in place.

    Every key here is byte-identical before and after the move -- the path, the
    code and the pointer text do not change -- so a guard that keys only on
    them reports `0 finding(s)` over a dead pointer. The referent is checked
    where the pointer names it.
    """
    trunk = "p/skills/s/SKILL.md"
    pointer = "Retries follow `references/a.md` § Retry policy, always.\n"
    with tempfile.TemporaryDirectory() as root:
        allow = os.path.join(root, "none.txt")
        write(os.path.join(root, trunk), pointer)
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n## Retry policy\n\nThree tries.\n")
        write(os.path.join(root, "p/skills/s/references/b.md"), "# B\n")
        rc, out = run_main(["--root", root, "--allowlist", allow])
        check(rc == 0, "a pointer whose referent is where it says is clean")

        # The extraction: the section moves to b.md, the trunk's pointer stays.
        write(os.path.join(root, "p/skills/s/references/a.md"), "# A\n")
        write(os.path.join(root, "p/skills/s/references/b.md"),
              "# B\n\n## Retry policy\n\nThree tries.\n")
        rc, out = run_main(["--root", root, "--allowlist", allow])
        check(rc == 1, "a trunk pointer whose section moved to another file FAILS "
                       f"(got rc={rc}: {out.strip().splitlines()[0] if out.strip() else ''})")
        check("LOST-REFERENT" in out and "§ Retry policy" in out,
              "the failure names the pointer")
        check("p/skills/s/references/a.md § Retry policy" in out,
              "the failure names the referent the pointer lost")
        check("p/skills/s/references/b.md" in out,
              "the failure names where the section went")

        # Deleted outright rather than moved: still dead, nothing to point at.
        write(os.path.join(root, "p/skills/s/references/b.md"), "# B\n")
        f = integrity.scan_file(trunk, pointer, root)
        check(codes(f) == ["LOST-REFERENT"], "a referent deleted outright is lost too")

    # "trunk" qualifies a § as well as a path does, so it names a referent too.
    with tempfile.TemporaryDirectory() as root:
        ref = "p/skills/s/references/r.md"
        write(os.path.join(root, trunk), "# S\n\n## Budget rules\n\nx\n")
        text = "This is counted (trunk, § Budget rules), never free.\n"
        write(os.path.join(root, ref), text)
        check(codes(integrity.scan_file(ref, text, root)) == [],
              "a trunk-qualified § whose heading is in the trunk is clean")
        write(os.path.join(root, trunk), "# S\n")
        check(codes(integrity.scan_file(ref, text, root)) == ["LOST-REFERENT"],
              "a trunk-qualified § whose section left the trunk is lost")

    # A dotted section number is part of the name: `§ Step 3.5` is lost when only
    # `Step 3.0` survives, and `§ 3.5` likewise; the sibling heading must not mask it.
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n### Step 3.0 — Test the premise first\n\n## 3.0 Setup\n")
        for text in ("see `references/a.md` § Step 3.5, then go on.\n",
                     "see `references/a.md` § 3.5.\n"):
            check(codes(integrity.scan_file(trunk, text, root)) == ["LOST-REFERENT"],
                  f"a dotted section number is part of the name: {text.strip()!r}")
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n### Step 3.5 — Stage gate\n\n## 3.5 Gate\n")
        for text in ("see `references/a.md` § Step 3.5, then go on.\n",
                     "see `references/a.md` § 3.5.\n",
                     "per `references/a.md` § Step 3.5. Then more.\n"):
            check(codes(integrity.scan_file(trunk, text, root)) == [],
                  f"a dotted section number that is there resolves: {text.strip()!r}")

    # A dash or colon inside both names is part of both titles: a surviving sibling that
    # shares only the clause before the dash does not mask a lost section.
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n## Checklist — Standard plans\n\n## Stage gate — standard plans\n\n"
              "## Rule: one gate per stage\n")
        for text in ("see `references/a.md` § Checklist — Light plans.\n",
                     "see `references/a.md` § Stage gate — light plans, then go on.\n",
                     "see `references/a.md` § Rule: two reviews per gate.\n"):
            check(codes(integrity.scan_file(trunk, text, root)) == ["LOST-REFERENT"],
                  f"a sibling sharing the clause before the dash does not mask: {text.strip()!r}")
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n## Checklist — Standard plans\n\n## Checklist — Light plans\n")
        check(codes(integrity.scan_file(trunk, "see `references/a.md` § Checklist — Light plans.\n",
                                        root)) == [],
              "a dashed section name that is there resolves")

    # A one-word heading is not the referent of a longer pointer it merely starts:
    # `## What` must not stand in for a lost `§ What belongs here`.
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/references/a.md"), "# A\n\n## What\n\nx\n")
        f = integrity.scan_file(trunk, "see `references/a.md` § What belongs here.\n", root)
        check(codes(f) == ["LOST-REFERENT"],
              f"a one-word heading does not resolve a longer pointer name ({codes(f)})")
        f = integrity.scan_file(trunk, "see `references/a.md` § What, above.\n", root)
        check(codes(f) == [], "the one-word heading still resolves its own name")

    # How pointers are actually written: abbreviated, emphasized, followed by
    # prose, at a line wrap, or after a path in an earlier sentence. None of
    # these is a lost referent.
    with tempfile.TemporaryDirectory() as root:
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n## Adopting a handoff (`--adopt <id>`)\n\n"
              "### Step 3.0 — Test the premise first\n\n"
              "## A bug is a class — sweep it, fix every instance\n\n"
              "## Auto-registration on first plan\n\n"
              "4. **Version bumps are deferred to the close-out.** Always.\n")
        write(os.path.join(root, trunk), "# S\n\n### Stage sizing\n")
        for text, why in [
            ("after `references/a.md` § Adopting a handoff verifies it\n",
             "heading carries a parenthetical, pointer runs into prose"),
            ("see `references/a.md` § Step 3.0, then go on.\n",
             "pointer abbreviates the heading"),
            ("per `references/a.md` § *A bug is a class* and more.\n",
             "emphasized name followed by prose"),
            ("per `references/a.md` § A bug is a class — sweep it, fix\n",
             "name cut by a line wrap"),
            ("per `references/a.md` § Auto-registration (warn, write x), then\n",
             "pointer carries its own parenthetical"),
            ("(`references/a.md` § *Version bumps are deferred to the close-out*)\n",
             "the § names a bold-run label, not a heading"),
            ("`*(amended per references/a.md § no-such-rule — was: x)*`\n",
             "a § inside a backtick span is quoted, not a pointer"),
            ("Fields: `references/a.md`. (Stage sizing is not there; it is § Stage sizing.)\n",
             "a path in an earlier sentence does not qualify this §"),
        ]:
            check("LOST-REFERENT" not in codes(integrity.scan_file(trunk, text, root)),
                  f"not lost: {why}")


def pinned_allowlist_cases():
    """An allowlist entry carries the referent its finding had when allowlisted.

    Key-only, the entry keeps suppressing after the place the pointer meant is
    extracted away, because the key does not change. Pinned, it lapses.
    """
    trunk = "p/skills/s/SKILL.md"
    key = f"{trunk}:DEIXIS-SECTION:Retry policy"
    with tempfile.TemporaryDirectory() as root:
        allow = os.path.join(root, "allow.txt")
        write(os.path.join(root, trunk), "# S\n\nRetries follow § Retry policy.\n")
        write(os.path.join(root, "p/skills/s/references/a.md"),
              "# A\n\n## Retry policy\n")
        write(allow, f"{key} -> p/skills/s/references/a.md § Retry policy\n")
        rc, _ = run_main(["--root", root, "--allowlist", allow])
        check(rc == 0, "a pinned entry suppresses while its referent holds")

        write(os.path.join(root, "p/skills/s/references/a.md"), "# A\n")
        write(os.path.join(root, "p/skills/s/references/b.md"),
              "# B\n\n## Retry policy\n")
        rc, out = run_main(["--root", root, "--allowlist", allow])
        check(rc == 1, "a pinned entry lapses when its referent is extracted away")
        check("p/skills/s/references/a.md § Retry policy" in out,
              "the lapse names the referent the entry was pinned to")

        write(allow, key + "\n")
        rc, _ = run_main(["--root", root, "--allowlist", allow])
        check(rc == 0, "an unpinned (key-only) entry still suppresses, as before")


def reseed_cases():
    trunk = "p/skills/s/SKILL.md"
    key = f"{trunk}:DEIXIS-SECTION:Retry policy"
    with tempfile.TemporaryDirectory() as root:
        allow = os.path.join(root, "allow.txt")
        write(os.path.join(root, trunk),
              "# S\n\nRetries follow § Retry policy.\nThe gate rules above apply.\n")
        write(os.path.join(root, "p/skills/s/references/b.md"),
              "# B\n\n## Retry policy\n")
        stale = f"{trunk}:DEAD-PATH:references/gone.md"
        write(allow, "# header kept verbatim\n\n"
                     f"{key} -> p/skills/s/references/a.md § Retry policy  # why\n"
                     f"{stale}\n")
        rc, _ = run_main(["--root", root, "--allowlist", allow, "--reseed"])
        check(rc == 0, "--reseed exits 0")
        with open(allow, encoding="utf-8") as fh:
            body = fh.read()
        check(body.startswith("# header kept verbatim\n"), "--reseed keeps the header")
        check(f"{key} -> p/skills/s/references/b.md § Retry policy  # why" in body,
              "--reseed re-pins an entry to its referent now, keeping its comment")
        check(stale not in body, "--reseed drops an entry no finding uses")
        check("DEIXIS-POSITIONAL" not in body,
              "--reseed pins existing debt, it never adds a finding to the allowlist")
        rc, _ = run_main(["--root", root, "--allowlist", allow])
        check(rc == 1, "the unallowlisted finding still fails after a reseed")
        rc, _ = run_main(["--root", root, "--allowlist", allow, "--reseed",
                          "--scope", "p"])
        check(rc == 2, "--reseed refuses a --scope (it would drop entries outside it)")


if __name__ == "__main__":
    print("dead paths:")
    dead_path_cases()
    print("host layers:")
    host_layer_cases()
    print("link targets:")
    link_target_cases()
    print("positional deixis:")
    positional_deixis_cases()
    print("section refs:")
    section_ref_cases()
    print("allowlist:")
    allowlist_cases()
    print("--list-allowlisted:")
    list_allowlisted_cases()
    print("--scope:")
    scope_cases()
    print("empty sweep:")
    empty_sweep_cases()
    print("exclusions:")
    exclusion_cases()
    print("lost referents:")
    referent_cases()
    print("pinned allowlist:")
    pinned_allowlist_cases()
    print("--reseed:")
    reseed_cases()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("\nall passed")
