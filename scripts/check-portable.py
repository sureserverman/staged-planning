#!/usr/bin/env python3
"""The repo refers to nothing outside itself: a portability property, checked by class.

A public plugin must run on a machine that has only it installed. The way that breaks is
rarely code: it is prose and fixtures that point at the author's own machine, sibling
plugins, or record ids from somebody else's register. A list of known names cannot catch
those, because the next leak is a name nobody listed. So this check matches *shapes* that
are wrong in a portable tree whatever they say:

  home-path        a literal absolute path under a user's home or a mount point, with or
                   without a trailing slash (/home/<x>, /var/home/<x>, /Users/<x>, the root
                   user's home, /mnt/<x>, /media/<x>, /run/media/<x>, /Volumes/<x>,
                   C:\\Users\\<x> and its JSON-escaped form). ~/… and $HOME/… are the
                   portable forms and pass.
  email            an address, except the git hosts' ssh users and the noreply address
                   in ALLOWED_EMAILS, and any address at example.com/.org/.net (or a
                   subdomain) or under the reserved .test/.example/.invalid/.localhost
  ip-address       a literal IPv4 address (octets 0-255, not part of a longer dotted
                   string such as a version), except 0.x, loopback 127.x, 255.x masks and
                   the documentation ranges 192.0.2.x, 198.51.100.x and 203.0.113.x, which
                   are the portable form for an example
  plugin-id        a /<x>:<y> command, or an <x>:<y> agent/skill id in a code span, table
                   cell, quoted string, Skill(...)/Agent(...) call or an unquoted
                   subagent_type:/agent: YAML value, whose <x> is not this plugin; or
                   this plugin's install identity planning@<m> under a marketplace <m>
                   that is not this repo's (example-* marketplaces pass, and `local`,
                   host-status.py's name for a copy that declares no marketplace)
  unregistered-id  a BL-/DEC-/GDEC- id, plain or tagged (DEC-SP-NNN), that this repo's
                   own docs/backlog.md or docs/decisions.md does not define. A tagged id
                   passes when its tag heads any entry there (closed items are removed);
                   BL-NNN / DEC-NNN placeholders pass
  vault-word       the vocabulary of a cross-project notes layer, outside the files VAULT_EXEMPT
                   lists (the three docs that describe the records-resolver hook, and
                   the tooling that names that layer to check it)

Each finding prints as `<class> <path>:<line>`, once per occurrence: two hits of one
class on one line are two findings. These are exact checks, not heuristics: every hit is
a defect by definition, so there is no trigger rate to tune. Every file is scanned as
text: NUL bytes are stripped, invalid UTF-8 is replaced, and a UTF-16 BOM decodes as
UTF-16. A symlink is never followed: its link text is scanned as one line of the link's
own path. Unreadable files are counted on stderr; an unreadable file, a named tree that
does not exist, or a missing or malformed baseline exits 2.

Usage:
  check-portable.py [--root R] <tree>...           strict: any finding exits 1
  check-portable.py --list <tree>...               print findings only
  check-portable.py --json <tree>...
        {"trees": [...], "counts": {<class>: n}, "files": {<path>: {<class>: n}}}
  check-portable.py --write-baseline F <tree>...   record per-class, per-file counts in F
  check-portable.py --ratchet F [--exact] <tree>...
        F holds a `# trees:` header and one `<class> <path> <count>` line per class per
        file. Exit 1 if any file's count of a class exceeds its own line, or a file with
        no line has a finding (`OVER <class> <path> <have> > <ceiling>`); print
        `STALE <class> <path> <have> < <ceiling>` when one fell below it (with --exact a
        STALE line also exits 1); exit 2 if the tree list differs from F's header
  check-portable.py                                bare, as run-tests.sh runs it: the
        default trees, strict. A scripts/portable-baseline.txt beside it is refused
        (exit 2), never obeyed, so a stray baseline cannot turn the gate back into a
        ratchet.

The ratchet is for a tree that still holds findings: it gates every commit while they are
removed. Counts may only fall, per class per file, so a removal in one file cannot pay for
a new leak in another, and --exact makes a fall be recorded. It runs only when asked for
with --ratchet.

Stdlib only.
"""
import argparse
import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TREES = ["core", "hosts", "build", "scripts", "docs", "plugins", "README.md"]
DEFAULT_BASELINE = os.path.join("scripts", "portable-baseline.txt")
CLASSES = ["home-path", "email", "ip-address", "plugin-id", "unregistered-id", "vault-word"]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
# The type definitions Claude Code writes into a plugin directory it loads: machine-written,
# ignored by git through their own `*` .gitignore, never shipped. Matched as (parent, name),
# not by name: a plugin's own `types/` is scanned.
LOADER_DIRS = {(".claude-plugin", "types")}

OWN_PLUGIN = "planning"
OWN_MARKETPLACE = "staged-planning"
# Prefixes of <x>:<y> that are schemes, runtimes or hashes, never plugin ids.
NON_PLUGIN = {"http", "https", "git", "file", "mailto", "data", "node", "ssh", "sha1",
              "sha256", "npm", "urn", "ftp", "tcp", "udp", "unix", "ws", "wss", "localhost",
              "javascript", "about", "chrome", "blob", "std"}

_NAME = r"[A-Za-z0-9._-]+"
HOME_RE = re.compile(
    r"(?<![\w.~-])(?:"
    r"(?:/var)?/home/" + _NAME + r"|/Users/" + _NAME + r"|/roo[t](?![\w-])"
    r"|/mnt/" + _NAME + r"|(?:/run)?/media/" + _NAME + r"|/Volumes/" + _NAME +
    r"|[A-Za-z]:\\{1,2}Users\\{1,2}" + _NAME + r")")
EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]+)@"
    r"([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}|localhost)(?![^\W_])")
OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4_RE = re.compile(r"(?<![\d.])" + r"\.".join([OCTET] * 4) + r"(?!\d|\.\d)")
IP_OK = ("0.", "127.", "255.", "192.0.2.", "198.51.100.", "203.0.113.")
ALLOWED_EMAILS = {"git@github.com", "git@gitlab.com", "git@bitbucket.org", "noreply@anthropic.com"}
EMAIL_OK_DOMAIN = ("example.com", "example.org", "example.net")
EMAIL_OK_TLD = ("test", "example", "invalid", "localhost")
_ID = r"([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)"
PLUGIN_RES = [
    re.compile(r"(?<![\w/.:-])/" + _ID + r"(?![\w:])"),          # slash command
    re.compile(r"`" + _ID + r"(?=[`\s(])"),                     # code span
    re.compile(r"\|\s*" + _ID + r"\s*\|"),                     # table cell
    re.compile(r"[\"']" + _ID + r"[\"']"),                     # quoted string
    re.compile(r"\b(?:Skill|Agent)\(\s*" + _ID + r"(?![\w:])"),  # Skill()/Agent() call
    re.compile(r"(?:^\s*(?:-\s+)?|[{,]\s*)(?:subagent_type|agent)\s*:\s*" + _ID
               + r"(?![\w:])"),                                 # unquoted YAML value
]
# A host install identity <plugin>@<marketplace>. Only this plugin's own name is matched:
# it has exactly one right marketplace, so every other one is a defect by definition. An
# address (a dot and a word after the marketplace) is the email class's to judge.
IDENTITY_RE = re.compile(r"(?<![\w.+-])" + OWN_PLUGIN + r"@([a-z0-9][a-z0-9-]*)(?![\w-]|\.\w)")
# Plain (DEC-NNN) and tagged (DEC-SP-NNN) forms. A repo whose own register uses a tag
# can never mistake a citation of someone else's plain DEC-NNN for one of its own.
_IDS = r"(?:(?:BL|DEC)-(?:([A-Z]{2,4})-)?\d{3,}|GDEC-(?:([A-Z]+)-)?\d{3,})"
ID_RE = re.compile(r"\b" + _IDS + r"\b")
DEF_RE = re.compile(r"^## (" + _IDS + r")\b", re.M)
VAULT_RE = re.compile(r"\bvaults?\b|Portfolio/|\bregistr(?:y|ies)\b", re.I)
REGISTERS = [os.path.join("docs", "backlog.md"), os.path.join("docs", "decisions.md")]
# Files allowed to use the vault vocabulary: the three docs that describe the resolver hook,
# and the portability tooling, whose own flags and class names carry the words.
VAULT_EXEMPT = {
    "docs/configuration.md", "docs/records-resolver.md", "core/references/records-resolver.md",
    "scripts/check-portable.py", "scripts/tests/test-check-portable.py",
    "scripts/portable-baseline.txt",
    "scripts/leak-check.py", "scripts/tests/test-leak-check.py",
    "scripts/clean-machine-run.sh", "scripts/tests/test-clean-machine-run.sh",
}


class Fatal(Exception):
    """Input the check cannot honestly judge: exit 2 with the message."""


def id_tag(m):
    return m.group(1) or m.group(2)


def defined_ids(root):
    """The ids this repo's registers define, and the tags those definitions use."""
    ids, tags = set(), set()
    for rel in REGISTERS:
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        for m in DEF_RE.finditer(text):
            ids.add(m.group(1))
            m2 = ID_RE.match(m.group(1))
            if m2 and id_tag(m2):
                tags.add(id_tag(m2))
    return ids, tags


def email_ok(local, domain):
    domain = domain.lower()
    if f"{local.lower()}@{domain}" in ALLOWED_EMAILS:
        return True
    if any(domain == d or domain.endswith("." + d) for d in EMAIL_OK_DOMAIN):
        return True
    return "." in domain and domain.rsplit(".", 1)[1] in EMAIL_OK_TLD


def files_under(root, tree, skipped):
    path = os.path.join(root, tree)
    if os.path.islink(path) or os.path.isfile(path):
        yield tree
        return
    if not os.path.isdir(path):
        raise Fatal(f"tree {tree!r} does not exist under {root}")

    def unreadable_dir(err):
        skipped["unreadable"] += 1
        print(f"unreadable: {err.filename}", file=sys.stderr)

    for dirpath, dirnames, filenames in os.walk(path, onerror=unreadable_dir):
        # A link to a directory is listed as a directory; it is a file here, never entered.
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d not in links
                             and (os.path.basename(dirpath), d) not in LOADER_DIRS)
        for name in sorted(filenames + links):
            yield os.path.relpath(os.path.join(dirpath, name), root)


def read_text(path, skipped):
    """The text to scan. A symlink's content is its link text, so a link can never
    bring a file from outside the tree into the scan, or hide a leak in its target."""
    try:
        if os.path.islink(path):
            return os.readlink(path)
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as err:
        skipped["unreadable"] += 1
        print(f"unreadable: {path}: {err.strerror}", file=sys.stderr)
        return None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    return text.replace("\x00", "")


def scan_line(line, rel, ids, tags):
    """One entry per occurrence, so two hits of a class on one line count two."""
    found = ["home-path" for _ in HOME_RE.finditer(line)]
    found += ["email" for m in EMAIL_RE.finditer(line) if not email_ok(m.group(1), m.group(2))]
    found += ["ip-address" for m in IPV4_RE.finditer(line) if not m.group(0).startswith(IP_OK)]
    starts = set()
    for rx in PLUGIN_RES:
        for m in rx.finditer(line):
            if m.group(1) != OWN_PLUGIN and m.group(1) not in NON_PLUGIN:
                starts.add(m.start(1))
    found += ["plugin-id"] * len(starts)
    found += ["plugin-id" for m in IDENTITY_RE.finditer(line)
              if m.group(1) not in (OWN_MARKETPLACE, "local") and not m.group(1).startswith("example")]
    found += ["unregistered-id" for m in ID_RE.finditer(line)
              if m.group(0) not in ids and id_tag(m) not in tags]
    if rel.replace(os.sep, "/") not in VAULT_EXEMPT:
        found += ["vault-word" for _ in VAULT_RE.finditer(line)]
    return found


def scan(root, trees):
    ids, tags = defined_ids(root)
    findings = []
    seen = set()
    skipped = {"unreadable": 0}
    for tree in trees:
        for rel in files_under(root, tree, skipped):
            if rel in seen:
                continue
            seen.add(rel)
            text = read_text(os.path.join(root, rel), skipped)
            if text is None:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for cls in scan_line(line, rel, ids, tags):
                    findings.append((cls, rel.replace(os.sep, "/"), n))
    return findings, skipped


def counts_of(findings):
    counts = {c: 0 for c in CLASSES}
    for cls, _, _ in findings:
        counts[cls] += 1
    return counts


def file_counts_of(findings):
    """{(class, path): n} for every class and file with at least one finding."""
    per = {}
    for cls, rel, _ in findings:
        per[(cls, rel)] = per.get((cls, rel), 0) + 1
    return per


def read_baseline(path):
    """(trees, {(class, path): ceiling}); a missing or malformed file is Fatal."""
    trees, ceilings = None, {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as err:
        raise Fatal(f"cannot read baseline {path}: {err}")
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if line.startswith("# trees:"):
            trees = line[len("# trees:"):].split()
            continue
        if not line or line.startswith("#"):
            continue
        parts = line.split(" ", 1)
        rest = parts[1].rsplit(" ", 1) if len(parts) == 2 else []
        if (len(rest) != 2 or parts[0] not in CLASSES or not rest[0].strip()
                or not rest[1].isdigit() or (parts[0], rest[0]) in ceilings):
            raise Fatal(f"malformed baseline {path}:{n}: {raw!r} "
                        "(want `<class> <path> <count>`, one line per class per file)")
        ceilings[(parts[0], rest[0])] = int(rest[1])
    if trees is None:
        raise Fatal(f"malformed baseline {path}: no `# trees:` header")
    return trees, ceilings


def path_key(rel):
    """The baseline names a file by a hash of its path: a path can itself be a leak
    (a fixture folder named after a project), and the baseline must not repeat it."""
    return "sha256:" + hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]


def write_baseline(path, trees, per_file):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Per-class, per-file ceilings for scripts/check-portable.py --ratchet.\n")
        fh.write("# Counts may only fall. Lower a ceiling when its count falls; never raise one.\n")
        fh.write("# A file with no line for a class has a ceiling of 0. Files are named by\n")
        fh.write("# sha256:<first 16 hex of the sha256 of the path>, never by the path itself.\n")
        fh.write("# trees: " + " ".join(trees) + "\n")
        rows = sorted(((cls, path_key(rel), n) for (cls, rel), n in per_file.items()),
                      key=lambda r: (CLASSES.index(r[0]), r[1]))
        for cls, key, n in rows:
            fh.write(f"{cls} {key} {n}\n")


def main(argv=None):
    try:
        return run(argv)
    except Fatal as err:
        print(f"check-portable: {err}", file=sys.stderr)
        return 2


def run(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("trees", nargs="*")
    ap.add_argument("--root", default=None, help="repo root (default: this script's repo)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--write-baseline", metavar="F")
    mode.add_argument("--ratchet", metavar="F")
    ap.add_argument("--exact", action="store_true")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or REPO)
    trees = args.trees
    ratchet = args.ratchet
    if not trees and not (args.list or args.json or args.write_baseline or ratchet):
        trees = DEFAULT_TREES
        if os.path.exists(os.path.join(root, DEFAULT_BASELINE)):
            print(f"check-portable: {DEFAULT_BASELINE} exists, but the bare run is strict — "
                  "remove the file, or pass --ratchet explicitly", file=sys.stderr)
            return 2
    if not trees:
        trees = DEFAULT_TREES
    if args.exact and not ratchet:
        ap.error("--exact needs --ratchet")

    findings, skipped = scan(root, trees)
    counts = counts_of(findings)
    per_file = file_counts_of(findings)
    if skipped["unreadable"]:
        print(f"skipped {skipped['unreadable']} unreadable", file=sys.stderr)
    # An unreadable file was not checked, so no mode may report the scan as complete.
    bad = 2 if skipped["unreadable"] else None

    if args.list:
        for cls, rel, n in findings:
            print(f"{cls} {rel}:{n}")
        return bad or 0
    if args.json:
        files = {}
        for (cls, rel), n in sorted(per_file.items()):
            files.setdefault(rel, {})[cls] = n
        print(json.dumps({"trees": trees, "counts": counts, "files": files}))
        return bad or 0
    if args.write_baseline:
        if bad:
            raise Fatal("refusing to write a baseline from a scan with unreadable files")
        write_baseline(args.write_baseline, trees, per_file)
        print(f"wrote {args.write_baseline}: " + ", ".join(f"{c} {counts[c]}" for c in CLASSES))
        return 0
    if ratchet:
        path = ratchet if os.path.exists(ratchet) else os.path.join(root, ratchet)
        base_trees, ceilings = read_baseline(path)
        if base_trees != trees:
            print(f"tree list {trees} differs from the baseline's {base_trees}", file=sys.stderr)
            return 2
        # Ceilings are keyed by path hash; map every scanned file back to its path so a
        # report can name the file, including one whose findings have all gone.
        names = {}
        for tree in trees:
            for rel in files_under(root, tree, {"unreadable": 0}):
                rel = rel.replace(os.sep, "/")
                names[path_key(rel)] = rel
        have = {(cls, path_key(rel)): n for (cls, rel), n in per_file.items()}
        order = lambda k: (CLASSES.index(k[0]), names.get(k[1], k[1]))
        over = sorted((k for k in have if have[k] > ceilings.get(k, 0)), key=order)
        stale = sorted((k for k in ceilings if have.get(k, 0) < ceilings[k]), key=order)
        for k in over:
            rel = names.get(k[1], k[1])
            print(f"OVER {k[0]} {rel} {have[k]} > {ceilings.get(k, 0)}")
            for cls, frel, n in findings:
                if cls == k[0] and frel == rel:
                    print(f"  {cls} {frel}:{n}")
        for k in stale:
            print(f"STALE {k[0]} {names.get(k[1], k[1])} {have.get(k, 0)} < {ceilings[k]}")
        if bad:
            return bad
        if over or (args.exact and stale):
            return 1
        print("portable: within the ratchet (" + ", ".join(f"{c} {counts[c]}" for c in CLASSES) + ")")
        return 0

    for cls, rel, n in findings:
        print(f"{cls} {rel}:{n}")
    return bad or (1 if findings else 0)


if __name__ == "__main__":
    sys.exit(main())
