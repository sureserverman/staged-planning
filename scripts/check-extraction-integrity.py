#!/usr/bin/env python3
"""Catch what extraction breaks that a diff cannot see.

Moving prose out of a monolith into `references/` silently invalidates two
things that were correct in the single file:

  DEAD-PATH          a relative path or link that resolved from the monolith's
                     directory and resolves from nowhere one level down.
  DEIXIS-POSITIONAL  "the rules above", "the flow below" — position words whose
                     referent is not present in this file.
  DEIXIS-SECTION     an unqualified `§ Some Heading` naming no heading in this
                     file and no file the reader could open.

Both deixis checks run over trunks AND reference files. Exempting trunks from
the positional check on the reasoning that "inside a single trunk, 'above'
genuinely resolves" is true before an extraction and false after it, which makes
the exemption blindest at the exact moment the guard is needed. Because
allowlist keys carry the path, text that MOVES surfaces as a new finding at its
new home even when its old location was allowlisted.

What it deliberately does NOT flag, because a guard that cries wolf gets its
findings allowlisted wholesale and then guards nothing:

  - `below \x60standard\x60`, `above ~5 minutes`, `below the standard plan` — these are
    comparisons and rankings, not positions. The distinguishing feature is what
    FOLLOWS the word: a backticked token, a number, or a tier name.
  - `\x60../SKILL.md\x60 § Stage structure` — a § qualified by a path or by the word
    "trunk" tells the reader where to look, which is the whole point.
  - A positional word whose referent IS resolvable in the same file (a heading,
    bold run, or table caption matching the noun phrase).

Scans every `*/skills/*/SKILL.md` and every `*/references/*.md` in the tree —
the latter repo-wide, not only under `skills/`, because plugin-root reference
dirs (`<plugin>/references/`) hold the files plugin-rooted citations point at. Paths under `tests/`, `fixtures/` or
`test-fixtures/` are excluded (test data, not shipped prose).
A finding is suppressed only by an exact `path:CODE:token` entry in
`scripts/extraction-integrity-allow.txt` — never by a bare path. The allowlist is
read as a MULTISET: one line suppresses exactly one finding, so N instances need
N lines and the N+1th surfaces. Set membership would make this paragraph false,
because the tokens are low-entropy enough that a new dead pointer routinely
collides with an allowlisted one.

Read-only: never writes to the repo. Exit 0 when clean, 1 when any finding, and
2 when the scan itself is invalid: fewer than `--min-files` files discovered
(default 1). Without that floor a typo'd `--scope` degrades to a silent clean
pass — `Scanned 0 file(s); 0 finding(s)` and exit 0 — which is the failure
`scripts/run-tests.sh` already refuses for the identical shape, in its own
words: "an empty sweep must never report a pass". The floor is a NUMBER rather
than a bare non-empty test because the sharper case is a scope that matches a
few files instead of none: a caller that knows it should sweep the whole tree
can assert the size of the sweep it expects, not merely that something was
looked at. Exit 2 rather than 1 keeps "the scan did not run" distinguishable
from "the scan ran and found something".
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWLIST_PATH = os.path.join(REPO_ROOT, "scripts", "extraction-integrity-allow.txt")

# Shared with check-frontmatter-budget.py and check-trunk-budget.py so the rules
# that must agree — what counts as test data, how a control file parses — are
# defined once. Bootstrap this script's own dir so the import resolves both when
# run directly and when loaded via importlib in the tests.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _frontmatter_common import EXCLUDE_SEGMENTS, load_lines  # noqa: E402
import _layout  # noqa: E402

EXCLUDE_PARTS = EXCLUDE_SEGMENTS

# A path-ish string: has a separator or a known extension, and no spaces.
PATH_EXTS = (".md", ".py", ".sh", ".json", ".txt", ".yml", ".yaml", ".toml")

BACKTICK_RE = re.compile(r"`([^`\n]+)`")
MDLINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# Words that make "above"/"below" a comparison rather than a position.
TIER_WORDS = (
    "high", "standard", "light", "none", "medium", "low",
    "critical", "important", "the standard", "threshold", "budget", "baseline",
)

# noun phrase + position word, e.g. "the gate rules above", "Context resets below"
POSITIONAL_RE = re.compile(
    r"(?P<noun>[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*){0,3})\s+"
    r"(?P<word>above|below)\b",
    re.IGNORECASE,
)
SEE_RE = re.compile(r"\(?\bsee\s+(?P<word>above|below)\b\)?", re.IGNORECASE)

SECTION_RE = re.compile(r"§\s*(?P<name>[^.,;)\n]+)")
BARE_FILENAME_RE = re.compile(r"[\w./-]+\.(?:md|py|sh|json|ya?ml)[\s,)]*$")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.M)


def normalize(s):
    """Lowercase, strip markdown emphasis and punctuation, collapse whitespace."""
    s = re.sub(r"[*_`\"'“”‘’]", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def load_allowlist(path=ALLOWLIST_PATH):
    """Allowlist as a MULTISET: one line suppresses one finding, not all matches.

    Set membership would silently break the contract this file's own header
    states. Keys are `path:CODE:token` and the tokens are low-entropy —
    "sections below", "checks above", "§ Review scope" recur all over the repo —
    so under set membership a brand-new dead pointer in an already-allowlisted
    file reuses an existing key and vanishes. Measured under set membership:
    three dead pointers appended to allowlisted files were all suppressed:
    0 findings, exit 0.

    Counting closes that without a new file format, because the file holds one line
    per finding: N occurrences need N lines, and the N+1th surfaces.
    """
    return collections.Counter(load_lines(path))


def list_allowlisted(path=ALLOWLIST_PATH):
    """The allowlist's entries, verbatim and in file order."""
    return load_lines(path)


def is_pathish(tok):
    if not tok or " " in tok or "\t" in tok:
        return False
    if tok.startswith(("http://", "https://", "mailto:", "#", "/", "~")):
        return False
    if tok.startswith("$") or "${" in tok:
        return False          # ${CLAUDE_PLUGIN_ROOT}/... is resolved at runtime
    if "*" in tok:
        return False          # a glob is a pattern, not a path to resolve
    if tok.endswith(PATH_EXTS):
        return True
    return False


# Structural names that mark a token as a reference to a file in THIS repo.
INTERNAL_MARKERS = ("/references/", "references/", "/skills/", "skills/",
                    "/scripts/", "scripts/", "/agents/", "agents/")


def is_placeholder(tok):
    """A `<name>` template stands for a path the reader substitutes, not a path.

    Note this screen lives here and NOT in is_pathish: `<applicationId>.yml`
    ends with a known extension and carries no space, so is_pathish accepts it.
    Any caller that bypasses is_internal_ref must apply this itself.
    """
    return "<" in tok or ">" in tok


def is_link_target(tok):
    """True for a markdown link target that should be resolved.

    is_internal_ref demands a structural marker (`references/`, `skills/`, ...)
    or a SKILL.md suffix, which is right for a BARE token: skill prose cites
    paths in the user's project constantly, and treating every path-ish token as
    internal floods the report with paths no reader of this repo could open
    (measured in is_internal_ref). A markdown LINK is
    different in kind — `[text](target)` is a promise the reader can follow it —
    so the structural marker is not needed to disambiguate intent.

    Two screens still apply. Measured on this tree: 12 distinct link targets
    pass is_pathish, 2 of them do not resolve, and both sit INSIDE a backtick
    span. One is `core/skills/workflow-spec/SKILL.md:26`, which reads
    ``- [auth](auth.md) — login, signup, ...``: it illustrates a line in the
    *user's* docs/workflows/README.md. A link displayed as literal code is
    quoted material, not a reference this repo makes, which is the same reason
    the deixis checks skip fenced blocks. The `<placeholder>` screen matches
    none of the 12; it stays because a template with no space
    (`<applicationId>.yml`) passes is_pathish and never resolves.
    With both screens the rule fires on 0 of the 12, so it needs no allowlist
    entries and still guards bare-filename links.
    """
    return not is_placeholder(tok)


def in_code_span(line, start):
    """True when offset `start` falls inside a backtick span on this line."""
    return line.count("`", 0, start) % 2 == 1


def is_internal_ref(tok):
    """True when the token points at another file in this repo's own tree.

    Skill prose cites paths in the *user's* project constantly — `fastlane/
    metadata/android/en-US/title.txt`, `docs/f-droid/<applicationId>.yml`,
    `app/build.gradle` — and those never resolved from here and never should.
    Measured on this tree 2026-10-24, treating every path-ish token as internal
    produces 456 findings where the structural rule produces 0: 104 are `<placeholder>`
    templates and the rest are target-project paths, tree-diagram filenames and
    bare script names; none carries a structural marker.
    An allowlist that size is not a guard, so the discriminator is structural:
    a cross-reference to a plugin file names `SKILL.md`, or sits under one of
    this repo's own structural directories.
    """
    if "<" in tok or ">" in tok:
        return False                      # templated placeholder, not a path
    if tok.endswith("SKILL.md"):
        return True
    marked = f"/{tok}"
    return any(m in marked for m in INTERNAL_MARKERS)


# A position word qualified by one of these is describing physical space or a
# ranking, not a place in the document: "slightly above the avatar's head",
# "on API 25 and below", "ranking it above a populated key".
SPATIAL_QUALIFIERS = ("slightly", "just", "directly", "immediately", "well",
                      "far", "and", "or", "sits", "ranking", "rank", "ranked")
PRONOUNS = ("it", "them", "this", "that", "these", "those", "one", "which", "you",
            # "see" is the bare form — "(see above)" names no referent, so
            # there is nothing to resolve and nothing that can be judged dead.
            "see")
# Nouns that name a structure rather than a titled section: resolvable only by
# looking for the structure itself, not by matching a heading.
STRUCTURAL_NOUNS = {
    "table": re.compile(r"^\s*\|", re.M),
    "list": re.compile(r"^\s*(?:[-*+]|\d+\.)\s", re.M),
    "form": re.compile(r"^\s*\|", re.M),
    "diagram": re.compile(r"^\s*```", re.M),
    "block": re.compile(r"^\s*```", re.M),
    "example": re.compile(r"^\s*```", re.M),
    # These three nouns name a row or a fenced structure the same way `table`
    # does — "every Basic-tier item below" points at tables in its own file,
    # "no entry below fits" at the tables filling the rest of it, "the structure
    # above" at an XML block. An unlisted noun can never be resolved, and
    # `_resolves_locally` needs the phrase twice, so a single correct mention
    # would be unfalsifiable.
    "item": re.compile(r"^\s*(?:\||[-*+]|\d+\.)\s", re.M),
    "entry": re.compile(r"^\s*(?:\||[-*+]|\d+\.)\s", re.M),
    "structure": re.compile(r"^\s*(?:```|\|)", re.M),
}


def _comparison_context(text, end):
    """True when what follows the position word makes it a comparison."""
    rest = text[end:end + 40].lstrip()
    if not rest:
        return False
    if rest[0] in "`~":
        return True
    m = re.match(r"(?:about\s+|roughly\s+|~)?(\d)", rest)
    if m:
        return True
    low = rest.lower()
    return any(low.startswith(w) for w in TIER_WORDS)


def _spatial_or_ranking(noun):
    """True when the noun phrase makes this a physical or ordering relation."""
    words = noun.lower().split()
    if not words:
        return True
    if words[-1] in SPATIAL_QUALIFIERS or words[-1] in PRONOUNS:
        return True
    return False


def _structure_present(text, noun, word):
    """For 'the table below' / 'the list above': does that structure exist here?

    A referent that is genuinely present in this same file is not the extraction
    defect — that defect is a referent left behind in the trunk. Checking for
    the structure rather than a heading is what makes a generic noun decidable.
    """
    last = noun.lower().split()[-1] if noun.split() else ""
    pattern = STRUCTURAL_NOUNS.get(last)
    if pattern is None:
        return False
    return bool(pattern.search(text))


def _resolves_locally(text, noun):
    """True when the noun phrase names something present in this same file.

    This is a whole-file substring count, and it is loose:
    the phrase need only appear twice anywhere, so a coincidental later mention
    can silence a genuinely dead pointer. Requiring the second occurrence to be
    a DEFINITION site (heading, bold run, colon-terminated label, table cell)
    measures as follows over one owner's plugin marketplace's skill files
    (undated):

      lab case (a constructed repro) ............... caught
      corpus true positives ........................ 0
      corpus false positives ...................... 11
      allowlist entries to ship it ................ +11

    All 11 are live references the stricter rule cannot see -- a generic noun
    pointing at a specific named thing ("the status marker below", "the
    per-row figures below"), physical space ("the toolbar below the header"),
    a hyphenated comparison ("a below-threshold verdict"), and
    a backticked HTML sentinel that merely quotes the word. With no true
    positive anywhere in the corpus the tightening is unfalsifiable here: it can
    only be measured by what it breaks, and 11 fresh allowlist entries to catch
    nothing is the "guard cries wolf, gets allowlisted wholesale, then guards
    nothing" failure this module's own header warns about.

    Tighten it only when the corpus has a real dead positional pointer to
    calibrate against -- that is the missing evidence, not a missing heuristic.
    """
    n = normalize(noun)
    if not n:
        return False
    # Drop leading articles/determiners so "the gate rules" matches "Gate rules".
    n = re.sub(r"^(the|a|an|its|this|that|these|those|one|each|every|normal|same)\s+", "", n)
    if len(n) < 4:
        return False
    hay = normalize(text)
    # Count occurrences: one is the reference itself, so it must appear twice.
    return hay.count(n) >= 2


def plugin_roots(relpath, root):
    """The directories a plugin-rooted citation in this file resolves against.

    `<plugin>/skills/<skill>/SKILL.md` -> `[<root>/<plugin>]`, which is what
    a plugin-rooted `references/foo.md` citation resolves against. A file in this
    repo's planning sources -> every source root of the plugin (core/ and each
    hosts/<host>/add/), because the built plugin is their union.
    """
    if _layout.plugin_name(relpath) == _layout.PLUGIN and "/" in relpath:
        layers = sorted(glob.glob(os.path.join(root, _layout.HOST_LAYERS)))
        return [os.path.join(root, _layout.CORE), *layers]
    parts = relpath.split("/")
    return [os.path.join(root, parts[0])] if len(parts) > 1 else [root]


def citation_forms(cand):
    """`cand`, plus — for a marketplace-rooted `planning/...` citation — the
    same path from the plugin root."""
    prefix = _layout.PLUGIN + "/"
    return [cand, cand[len(prefix):]] if cand.startswith(prefix) else [cand]


def scan_file(relpath, text, root):
    """Findings for one file. `relpath` is repo-relative; `root` resolves paths."""
    findings = []
    filedir = os.path.dirname(os.path.join(root, relpath))
    lines = text.split("\n")

    headings = [normalize(h) for h in HEADING_RE.findall(text)]

    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue

        # --- DEAD-PATH -------------------------------------------------
        toks = [(m.group(1), False) for m in BACKTICK_RE.finditer(line)]
        # A markdown link target is a reference by construction, so it does not
        # need is_internal_ref's structural marker to prove intent --
        # unless the link is being *displayed* inside a backtick span, where it
        # is quoted text rather than a link this file makes.
        toks += [(m.group(1), not in_code_span(line, m.start()))
                 for m in MDLINK_RE.finditer(line)]
        # Inside a fence there are no backticks to delimit anything: the whole
        # line is a command, and its bare arguments are paths the reader will
        # actually run. The extraction defect's sharper half lives here.
        if in_fence:
            toks += [(t, False) for t in line.split()]
        for tok, is_link in toks:
            # Strip shell quoting before anything else. `trap 'skills/.../down.sh
            # --mock' EXIT` inside a fence splits to a token carrying a leading
            # quote, which resolves against nothing — so a file that EXISTS would
            # be reported dead and seeded as debt: the "guard cries wolf, gets
            # allowlisted, guards nothing" failure this script's own docstring
            # warns about, reached by its own tokenizer.
            cand = tok.strip("'\"").split("#", 1)[0].strip()
            if not is_pathish(cand):
                continue
            if not (is_link_target(cand) if is_link else is_internal_ref(cand)):
                continue
            # Three addressing conventions are all legitimate here, so a token
            # is dead only when it resolves under none of them:
            #   file-relative   `../review-scope.md` from a references/ file
            #   plugin-rooted   `references/plan-format.md` from a SKILL.md,
            #                   for a skill with no skill-level references/
            #                   dir whose file lives at <plugin>/references/
            #   repo-rooted     a fenced command, which runs from the checkout
            # A host layer file resolves each of these in its host's built plugin
            # (`_layout.built_twins`): an override's references/ live in core/.
            # Picking one and flagging the rest is the guard being wrong about
            # which contract the string serves.
            bases = [filedir, *_layout.built_twins(root, relpath), *plugin_roots(relpath, root),
                     root]
            if not any(os.path.exists(os.path.normpath(os.path.join(base, form)))
                       for base in bases for form in citation_forms(cand)):
                findings.append({
                    "path": relpath, "line": i, "code": "DEAD-PATH",
                    "token": cand, "text": line.strip()[:120],
                })

        # --- DEIXIS-POSITIONAL (prose only, trunks included) -----------
        # Inside a fence, "checked above" is a SAFETY comment about the lines
        # of code above it, and "# see below" annotates a YAML key. Both refer
        # to the listing, not to the document, so neither is extraction deixis.
        #
        # A bare "(see above)" or "(see below)" carries no noun phrase, so there
        # is nothing to resolve and no way to tell a live reference from a dead
        # one. Flagged unconditionally, it measures 13 hits on this tree, every
        # one a "(see below)" that points at a section that follows, and no dead
        # ones. An unfalsifiable
        # rule that only ever fires wrongly is worse than no rule, so it is left
        # unflagged rather than allowlisted.
        if not in_fence:
            for m in POSITIONAL_RE.finditer(line):
                if _comparison_context(line, m.end()):
                    continue
                noun = m.group("noun")
                if _spatial_or_ranking(noun):
                    continue
                if _structure_present(text, noun, m.group("word")):
                    continue
                if _resolves_locally(text, noun):
                    continue
                token = f"{noun.split()[-1]} {m.group('word')}".lower()
                findings.append({
                    "path": relpath, "line": i, "code": "DEIXIS-POSITIONAL",
                    "token": token, "text": line.strip()[:120],
                })

        # --- DEIXIS-SECTION (everywhere) -------------------------------
        for m in SECTION_RE.finditer(line):
            before = line[:m.start()]
            # Qualified by a path or by the word "trunk" -> the reader can follow it.
            tail = before[-70:]
            if "trunk" in tail.lower():
                continue
            # Backticked paths are searched over the WHOLE line prefix, not the
            # 70-char window: the window splits a backtick pair whenever the
            # citation is long, so `../../planning-projects/SKILL.md` § Stage
            # structure would read as unqualified purely because of where the
            # truncation fell. A citation is a citation wherever it sits on the line.
            if any(is_pathish(t.split("#", 1)[0].strip())
                   for t in BACKTICK_RE.findall(before)):
                continue
            # A filename in bare prose qualifies just as well as a backticked
            # one: `metrics-format.md § Target linkage` names the file the
            # heading lives in, and that heading does exist there. Requiring
            # backticks would make the finding's own premise ("no file the reader
            # could open") factually wrong.
            if BARE_FILENAME_RE.search(tail):
                continue
            name = normalize(m.group("name"))
            if not name:
                continue
            # Containment must not run in the direction that lets a SHORT
            # dangling reference hide inside a LONGER unrelated heading: a
            # file with `## Scope of the review pass` would otherwise swallow
            # a dead `§ Scope rules`. Only the reference-contains-heading
            # direction is safe, plus exact equality.
            if any(h == name or h in name for h in headings if h):
                continue
            findings.append({
                "path": relpath, "line": i, "code": "DEIXIS-SECTION",
                "token": m.group("name").strip()[:60],
                "text": line.strip()[:120],
            })

    return findings


def discover(root, scope):
    """Repo-relative SKILL.md and references/*.md paths, sorted."""
    out = []
    base = os.path.join(root, scope) if scope else root
    if not os.path.isdir(base):
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")
                       # Generated copies: their sources are scanned instead.
                       and not (dirpath == root and d in _layout.GENERATED)]
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            marker = f"/{rel}"
            if any(p in marker for p in EXCLUDE_PARTS):
                continue
            if fn == "SKILL.md" or "/references/" in marker:
                out.append(rel)
    return sorted(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-extraction-integrity")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--allowlist", default=None)
    ap.add_argument("--scope", default=None,
                    help="repo-relative subtree to restrict the scan to")
    ap.add_argument("--min-files", type=int, default=1, metavar="N",
                    help="fail with exit 2 if fewer than N files are discovered "
                         "(default 1; pass 0 to allow a legitimately empty scope)")
    ap.add_argument("--list-allowlisted", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    allow_path = args.allowlist or os.path.join(args.root, "scripts",
                                                "extraction-integrity-allow.txt")

    if args.list_allowlisted:
        for entry in list_allowlisted(allow_path):
            print(entry)
        return 0

    allowed = load_allowlist(allow_path)
    files = discover(args.root, args.scope)

    # An empty (or unexpectedly small) sweep must never read as a pass. discover()
    # returns [] both for a scope that does not exist and for one that exists and
    # matches nothing, and neither is distinguishable downstream from a clean tree
    # — so the check belongs here, before any finding is counted.
    if len(files) < args.min_files:
        where = f" under {args.scope}" if args.scope else ""
        print(f"FAIL: discovered {len(files)} file(s){where}, "
              f"below the --min-files floor of {args.min_files}.", file=sys.stderr)
        if args.scope:
            print("Either --scope names a subtree that does not exist or holds no "
                  "SKILL.md / references/*.md, or it is misspelled.", file=sys.stderr)
        else:
            print("Either --root is not this repo's tree (a partial checkout, or a "
                  "copy of this script elsewhere), or discovery no longer matches "
                  "this repo's layout.", file=sys.stderr)
        print("Both are failures here: an empty sweep must never report a pass. "
              "Pass --min-files 0 if the empty scope is intended.", file=sys.stderr)
        return 2

    findings, suppressed = [], []
    remaining = collections.Counter(allowed)
    for rel in files:
        with open(os.path.join(args.root, rel), encoding="utf-8") as fh:
            text = fh.read()
        for f in scan_file(rel, text, args.root):
            key = f"{f['path']}:{f['code']}:{f['token']}"
            if remaining[key] > 0:
                remaining[key] -= 1
                suppressed.append(f)
            else:
                findings.append(f)

    if args.json:
        print(json.dumps({"scanned": len(files), "findings": findings,
                          "suppressed": len(suppressed)}, indent=2))
    else:
        # honest-gates: always print what was examined, so an empty sweep
        # cannot read as a pass that covered something.
        scope_note = f" under {args.scope}" if args.scope else ""
        print(f"Scanned {len(files)} file(s){scope_note}; "
              f"{len(findings)} finding(s), {len(suppressed)} allowlisted.")
        for f in findings:
            print(f"  {f['path']}:{f['line']}  {f['code']}  [{f['token']}]")
            print(f"      {f['text']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
