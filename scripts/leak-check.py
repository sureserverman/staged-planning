#!/usr/bin/env python3
"""Find the owner's own names in a tree: a leak check whose name list is measured, not typed.

check-portable.py matches shapes. It cannot know that a word is the name of one of the
owner's other projects. This check can, because it reads the owner's own sources at run
time and never stores what it finds:

  names     every `name:` in the projects registry (block style `name: x` or flow style
            `- {name: x, ...}`), every folder two deep under --names-dir (a notes
            tree of <group>/<project>/ folders), and every directory
            one and two deep under the projects root (dot folders excepted). A project
            deeper than two levels is a name only if the registry lists it. Each name is
            split into words at `-`, `_`, `.` and spaces and matched with any of those
            separators or none (alpha-widget, alpha_widget, alpha widget, alpha.widget,
            alphawidget, which case-insensitively covers AlphaWidget), bounded by
            characters other than [A-Za-z0-9], so a name inside a path matches. Names
            shorter than 3 characters are dropped; the floor applies to names only. A
            names dir or a projects root that yields no name is refused.
            Two more kinds are derived from those: a family stem, the first word that
            two or more multi-word names share (4+ characters, `kappa` from kappa-front
            and kappa-back), since a family's own name is the owner's too; and each plan
            in a project folder's `plans/` dir under --names-dir, by its topic (the file
            name less its date, `-sub-NN-`, and `-plan`/`-master-plan`/`-light-plan`/
            `-design`/`-done` endings) and by its first `# ` title (less any `… Plan:`
            prefix), each kept when it has 2+ words and 10+ characters. A plan file that
            cannot be read is refused.
  literals  the home path ($HOME, or --home), the hostname (`hostname`, or --hostname),
            every user.email of `git config --global --includes` (so an [include]d
            file counts) and of `git config` run here (so inside a repo the repo-local
            one counts too), every --email and every --literal (a handle, a full name).
            They are matched as written, case-insensitively, with the same bounds, and
            have no length floor.

Generic words that are also project names (test, core, ...) are passed as --allow or in an
--allow-file (one word per line, `#` starts a comment). An allow word suppresses every
spelling of that name. It never suppresses a literal. Allow words are runtime arguments
only; this file holds none.

What is scanned:
  trees     every file under each <tree> (except .git, node_modules, __pycache__, .venv):
            its content line by line, and its path. The path is matched as given on the
            command line for a relative tree, and relative to the tree for an absolute
            one, so the tree's own location is never a hit. Directories are matched only
            through the paths of the files in them; an empty directory is not seen. A
            symlink (to a file, a directory or nothing) is never followed: its own path
            and its link text are matched instead of a target's content. Content that is
            not clean UTF-8 is still scanned: a file with a UTF-16 BOM is decoded as
            UTF-16, otherwise NUL bytes are removed (so BOM-less UTF-16 reads as ASCII)
            and invalid UTF-8 is decoded with replacement. Such files are counted and
            named on stderr.
  history   with --history, every commit `git log --all` reaches (refs/notes included, so
            git notes are scanned as the notes ref's diffs; reflog-only and unreachable
            commits are not): the message, the author and committer lines, every added
            line of the diff, and every path in the diff headers. A merge is diffed
            against its first parent, so content added in the merge itself is seen. Rename
            detection is off, so a move is a delete plus an add of the new path. Every
            tag name, and each annotated tag's message and tagger line, are scanned too.
            The user's diff and log config cannot hide a commit or change a path, and
            replace refs are ignored, so each commit is read as written. Messages are
            read NUL-separated, so no message line can end a message early or pose as
            a diff line. A C-quoted header path is unquoted before it is matched.

What is not scanned:
  - a diff git calls binary (by content or by .gitattributes): counted on stderr, its
    path still matched
  - the target of a symlink in a tree
  - removed and context lines of a diff (each was an added line in an earlier commit)
  - with --range: commits outside it, and tags
  - branch and other ref names, the reflog, stashes not reachable from a ref, submodule
    contents, the notes' page contents, and encoded spellings (%2D, &#45;)

Each hit prints as `<name> <path>:<line>`, `<name> <path>:path` or (a symlink's link
text) `<name> <path>:link` for a tree, and as `<name> <commit>:<path>` for history, where
<path> is `author` or `committer` for an identity line, `message` for the commit message
and `path` for a name in a diff header path; a tag hit prints as `<name> tag:<tagname>`.
Per-name totals go to stderr.

Usage:
  leak-check.py --registry F --names-dir D --projects-root D [--allow W]... [--allow-file F]...
                [--email A]... [--literal T]... [--home P] [--hostname H]
                [--history [--range REV-RANGE] [--no-authors]] [<tree>...]

  --literal T   one more owner literal, matched like the home path; repeatable
  --history     also scan the git repo at the current directory, as described above
  --range R     limit --history to the commits of R (for example A..B); tags are skipped
  --no-authors  with --history, skip author, committer and tagger lines (messages are
                still scanned)

Exit 0 no hits, 1 hits, 2 a named source unreadable or empty, a file, symlink or
subdirectory unreadable, a diff header that cannot be parsed, or a usage error. A source
that cannot be read is refused, never skipped, and so is a measurement of nothing: no
name left after the allow words, or no literal, exits 2.

Stdlib only.
"""
import argparse
import os
import re
import socket
import subprocess
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
MIN_LEN = 3
NAME_RE = re.compile(r"^\s*(?:-\s+)?name:\s*(.*?)\s*$")
FLOW_RE = re.compile(r"^\s*(?:-\s*)?\{(.*)\}\s*(?:#.*)?$")
FLOW_NAME_RE = re.compile(r"(?:^|,)\s*name\s*:\s*(\"[^\"]*\"|'[^']*'|[^,}]*)")
SPLIT_RE = re.compile(r"[-_.\s]+")
SEP = r"(?:[-_.]|[ \t]+)"
CQUOTE = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
MARK = "\x01"
GIT = ["git", "--no-replace-objects"]   # a replace ref must not stand in for a commit


class Refuse(Exception):
    """A named source is unreadable, or the arguments are unusable: exit 2."""


def parts(word):
    return [p for p in SPLIT_RE.split(word.strip().lower()) if p]


def key(word):
    return "-".join(parts(word))


def unquote_value(value):
    if value[:1] in "\"'":
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else value[1:]
    return value.split(" #", 1)[0].strip()


def registry_names(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise Refuse(f"registry unreadable: {path}: {e.strerror}")
    found = []
    for line in text.splitlines():
        flow = FLOW_RE.match(line)
        if flow:
            values = [unquote_value(v.strip()) for v in FLOW_NAME_RE.findall(flow.group(1))]
        else:
            m = NAME_RE.match(line)
            values = [unquote_value(m.group(1))] if m else []
        found.extend(v for v in values if v)
    if not found:
        raise Refuse(f"registry has no name: entry: {path}")
    return found


def subdirs(path, label):
    try:
        entries = sorted(os.listdir(path))
    except OSError as e:
        raise Refuse(f"{label} unreadable: {path}: {e.strerror}")
    return [n for n in entries if not n.startswith(".") and os.path.isdir(os.path.join(path, n))]


def notes_names(names_dir):
    if not os.path.isdir(names_dir):
        raise Refuse(f"names dir unreadable: {names_dir}")
    found = []
    for group in subdirs(names_dir, "names dir"):
        found.extend(subdirs(os.path.join(names_dir, group), "names dir"))
    if not found:
        raise Refuse(f"names dir has no project folder: {names_dir}")
    return found


def project_names(root):
    if not os.path.isdir(root):
        raise Refuse(f"projects root unreadable: {root}")
    found = []
    for one in subdirs(root, "projects root"):
        found.append(one)
        found.extend(subdirs(os.path.join(root, one), "projects root"))
    if not found:
        raise Refuse(f"projects root has no project folder: {root}")
    return found


FAMILY_MIN = 4
PLAN_MIN = 10
PLAN_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
PLAN_END = re.compile(r"-(?:master-plan|light-plan|plan|design|done)$")
PLAN_SUB = re.compile(r"^(.*?)-sub-\d+-(.*)$")


def family_stems(names):
    """The first word two or more multi-word names share."""
    firsts = {}
    for name in names:
        words = parts(name)
        if len(words) >= 2:
            firsts.setdefault(words[0], set()).add(key(name))
    return sorted(w for w, keys in firsts.items() if len(keys) >= 2 and len(w) >= FAMILY_MIN)


def plan_topic_names(names_dir):
    """Each plan's topic and title, from the plans/ dir of every project folder."""
    found = []
    for group in subdirs(names_dir, "names dir"):
        for proj in subdirs(os.path.join(names_dir, group), "names dir"):
            plans = os.path.join(names_dir, group, proj, "plans")
            if not os.path.isdir(plans):
                continue
            for f in sorted(os.listdir(plans)):
                path = os.path.join(plans, f)
                if not f.endswith(".md") or not os.path.isfile(path):
                    continue
                stem = PLAN_END.sub("", PLAN_DATE.sub("", f[:-3]))
                sub = PLAN_SUB.match(stem)
                topics = [sub.group(1), sub.group(2)] if sub else [stem]
                found += [PLAN_END.sub("", t) for t in topics]
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        title = next((l[2:].strip() for l in fh if l.startswith("# ")), "")
                except OSError as e:
                    raise Refuse(f"plan unreadable: {path}: {e.strerror}")
                found.append(title.split(":", 1)[1] if ":" in title else title)
    return [n for n in found if len(parts(n)) >= 2 and len(key(n)) >= PLAN_MIN]


def allow_words(words, files):
    allowed = {key(w) for w in words if w.strip()}
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    word = line.split("#", 1)[0].strip()
                    if word:
                        allowed.add(key(word))
        except OSError as e:
            raise Refuse(f"allow file unreadable: {path}: {e.strerror}")
    return allowed


def config_emails():
    """Every user.email in the global config (includes followed) and in the effective
    config here, which adds the repo-local one inside a repo."""
    found = []
    for scope in (["--global", "--includes"], ["--includes"]):
        cmd = GIT + ["config", *scope, "--get-all", "user.email"]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as e:
            raise Refuse(f"git not runnable: {e.strerror}")
        if p.returncode == 1:
            continue                     # the key is unset: there is nothing to leak
        if p.returncode != 0:
            raise Refuse(f"{' '.join(cmd[2:])} failed: {p.stderr.strip()}")
        found += [e.strip() for e in p.stdout.splitlines() if e.strip()]
    return found


def bounded(text):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(text) + r"(?![A-Za-z0-9])", re.I)


def name_regex(words):
    """The words joined by any one separator, or by none when the joined form keeps the floor."""
    sep = SEP + ("?" if len("".join(words)) >= MIN_LEN else "")
    body = sep.join(re.escape(w) for w in words)
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)


class Matcher:
    """Every source as (label, needle, regex); a line hits each label at most once.

    The needle is a lowercase substring every hit must contain: a cheap prefilter."""

    def __init__(self, names, literals, allowed):
        self.sources = []
        seen = set()
        for name in names:
            k = key(name)
            if len(name.strip()) < MIN_LEN or not k or k in seen or k in allowed:
                continue
            seen.add(k)
            words = parts(name)
            self.sources.append((name, words[0], name_regex(words)))
        self.name_count = len(self.sources)
        seen_lit = set()
        for lit in literals:
            if lit and lit.lower() not in seen_lit:
                seen_lit.add(lit.lower())
                self.sources.append((lit, lit.lower(), bounded(lit)))
        self.literal_count = len(self.sources) - self.name_count

    def labels(self, line):
        low = line.lower()
        found = []
        for label, needle, rx in self.sources:
            if needle in low and label not in found and rx.search(line):
                found.append(label)
        return found


def walk_error(err):
    raise Refuse(f"directory unreadable: {err.filename}: {err.strerror}")


def files_under(tree):
    """(path, is_link) for every file and symlink; a symlink is never followed."""
    if os.path.islink(tree) or os.path.isfile(tree):
        yield tree, os.path.islink(tree)
        return
    for dirpath, dirnames, filenames in os.walk(tree, onerror=walk_error):
        links = sorted(d for d in dirnames if os.path.islink(os.path.join(dirpath, d)))
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d not in links)
        for name in sorted(filenames + links):
            path = os.path.join(dirpath, name)
            yield path, os.path.islink(path)


def read_text(path):
    """(text, None), or (text, why) when the bytes were not clean UTF-8 and were
    decoded with replacement: UTF-16 by its BOM, otherwise NULs removed."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise Refuse(f"file unreadable: {path}: {e.strerror}")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace"), "UTF-16"
    why = None
    if b"\x00" in data:
        data, why = data.replace(b"\x00", b""), "NUL bytes"
    try:
        return data.decode("utf-8"), why
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), why or "not UTF-8"


def read_link(path):
    try:
        return os.readlink(path)
    except OSError as e:
        raise Refuse(f"symlink unreadable: {path}: {e.strerror}")


def matched_path(tree, path):
    """The path a reader of the tree sees: as given if relative, else relative to the tree."""
    shown = os.path.normpath(path)
    if not os.path.isabs(shown):
        return shown
    if os.path.islink(tree) or os.path.isfile(tree):
        return os.path.basename(shown)
    return os.path.relpath(shown, os.path.normpath(tree))


def scan_trees(trees, matcher, hits, lossy):
    count = 0
    for tree in trees:
        for path, is_link in files_under(tree):
            count += 1
            rel = os.path.normpath(path).replace(os.sep, "/")
            for label in matcher.labels(matched_path(tree, path).replace(os.sep, "/")):
                hits.append((label, f"{rel}:path"))
            if is_link:
                for label in matcher.labels(read_link(path)):
                    hits.append((label, f"{rel}:link"))
                continue
            text, why = read_text(path)
            if why:
                lossy.append((why, rel))
            for n, line in enumerate(text.splitlines(), 1):
                for label in matcher.labels(line):
                    hits.append((label, f"{rel}:{n}"))
    return count


def c_unquote(text):
    """Undo git's C-style quoting of a path: "b/say\\"hi" -> b/say"hi."""
    body, out, i = text[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1:i + 2]
        if nxt in CQUOTE:
            out.append(CQUOTE[nxt])
            i += 2
        elif re.fullmatch(r"[0-3][0-7]{2}", body[i + 1:i + 4]):
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        else:
            raise ValueError(text)
    return out.decode("utf-8", errors="replace")


def git_path(rest, commit, line):
    """The path of a `diff --git a/P b/P` header; with renames off both sides are P."""
    if rest.startswith('"'):
        m = re.match(r'"(?:[^"\\]|\\.)*"', rest)
        try:
            first = c_unquote(m.group(0)) if m else ""
        except ValueError:
            first = ""
        if first.startswith("a/") and len(first) > 2:
            return first[2:]
    elif (len(rest) - 5) % 2 == 0:
        p = rest[2:2 + (len(rest) - 5) // 2]
        if p and rest == f"a/{p} b/{p}":
            return p
    raise Refuse(f"--history: unparsable diff header in {commit}: {line!r}")


def plus_path(line, commit):
    """The new-side path of a `+++ ` header, None for /dev/null; anything else is refused."""
    target = line[4:]
    if target.endswith("\t"):           # git appends a tab when the name holds a space
        target = target[:-1]
    if target == "/dev/null":
        return None
    if len(target) >= 2 and target[0] == '"' and target[-1] == '"':
        try:
            target = c_unquote(target)
        except ValueError:
            target = None
    if target and target.startswith("b/") and len(target) > 2:
        return target[2:]
    raise Refuse(f"--history: unparsable diff header in {commit}: {line!r}")


def scan_tags(matcher, authors, hits):
    fmt = "%01%(refname:strip=2)%00%(objecttype)%00%(taggername) %(taggeremail)%00%(contents)"
    p = subprocess.run(GIT + ["for-each-ref", f"--format={fmt}", "refs/tags"],
                       capture_output=True)
    if p.returncode != 0:
        raise Refuse(f"git for-each-ref failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    count = 0
    for record in p.stdout.decode("utf-8", errors="replace").split("\x01")[1:]:
        fields = record.split("\x00")
        if len(fields) != 4:
            raise Refuse(f"--history: unparsable tag record: {record[:80]!r}")
        name, kind, tagger, contents = fields
        count += 1
        texts = [name]
        if kind == "tag":                # annotated; a lightweight tag's contents are its commit's
            texts += contents.splitlines() + ([tagger] if authors else [])
        labels = []
        for text in texts:
            labels += [l for l in matcher.labels(text) if l not in labels]
        hits.extend((label, f"tag:{name}") for label in labels)
    return count


def git_log(fmt, extra, rev_range):
    cmd = GIT + ["-c", "core.quotepath=false", "log", "--no-color", "--no-ext-diff",
                 "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "--no-renames",
                 "--root", "--diff-merges=first-parent", "--no-relative",
                 "--no-show-signature", "--encoding=UTF-8", f"--format={fmt}", *extra]
    cmd += [rev_range] if rev_range else ["--all"]
    cmd += ["--"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise Refuse(f"git log failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8", errors="replace")


def scan_history(matcher, rev_range, authors, hits):
    probe = subprocess.run(GIT + ["rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if probe.returncode != 0:
        raise Refuse("--history: the current directory is not in a git repo")
    # Pass 1, identities and messages: NUL-separated, and a message cannot hold a NUL.
    fmt = "%H%x00%an <%ae>%x00%cn <%ce>%x00%B"
    fields = git_log(fmt, ["-z", "-s"], rev_range).split("\x00")
    if len(fields) % 4 != 1 or fields[-1]:
        raise Refuse("--history: unparsable git log -z output")
    seen = []
    for i in range(0, len(fields) - 1, 4):
        commit, author, committer, message = fields[i:i + 4]
        seen.append(commit)
        if authors:
            for where, ident in (("author", author), ("committer", committer)):
                for label in matcher.labels(ident):
                    hits.append((label, f"{commit}:{where}"))
        msg_labels = []
        for line in message.splitlines():
            msg_labels += [l for l in matcher.labels(line) if l not in msg_labels]
        hits.extend((label, f"{commit}:message") for label in msg_labels)
    # Pass 2, diffs: the header is only the hash, after a byte no diff line starts with.
    binaries, diffed = 0, []
    commit, path, in_hunk, path_labels = None, None, False, set()
    for line in git_log(f"{MARK}%H", ["-p"], rev_range).split("\n"):
        if line.startswith(MARK):
            commit = line[len(MARK):]
            diffed.append(commit)
            path, in_hunk, path_labels = None, False, set()
        elif line.startswith("diff --git "):
            path, in_hunk = None, False
            rest = line[len("diff --git "):]
            for label in matcher.labels(git_path(rest, commit, line)):
                if label not in path_labels:
                    path_labels.add(label)
                    hits.append((label, f"{commit}:path"))
        elif not in_hunk and line.startswith("+++ "):
            path = plus_path(line, commit)
        elif not in_hunk and line.startswith("Binary files "):
            binaries += 1
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and path and line.startswith("+"):
            for label in matcher.labels(line[1:]):
                hits.append((label, f"{commit}:{path}"))
    if sorted(diffed) != sorted(seen):
        raise Refuse("--history: the message and diff passes saw different commits")
    tags = 0 if rev_range else scan_tags(matcher, authors, hits)
    return len(seen), binaries, tags


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("trees", nargs="*")
    ap.add_argument("--registry", required=True)
    ap.add_argument("--names-dir", required=True)
    ap.add_argument("--projects-root", required=True)
    ap.add_argument("--allow", action="append", default=[], metavar="WORD")
    ap.add_argument("--allow-file", action="append", default=[], metavar="F")
    ap.add_argument("--email", action="append", default=[], metavar="ADDR")
    ap.add_argument("--literal", action="append", default=[], metavar="TEXT")
    ap.add_argument("--home", default=None)
    ap.add_argument("--hostname", default=None)
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--range", default=None, metavar="REV-RANGE")
    ap.add_argument("--no-authors", action="store_true")
    args = ap.parse_args(argv)

    if not args.trees and not args.history:
        ap.error("give at least one tree, or --history")
    if (args.range or args.no_authors) and not args.history:
        ap.error("--range and --no-authors need --history")

    try:
        for tree in args.trees:
            if not os.path.exists(tree):
                raise Refuse(f"tree not found: {tree}")
        home = args.home if args.home is not None else os.environ.get("HOME", "")
        host = args.hostname if args.hostname is not None else socket.gethostname()
        if not home.strip("/"):
            raise Refuse("home path unknown: set $HOME or pass --home")
        if not host:
            raise Refuse("hostname unknown: pass --hostname")
        names = (registry_names(args.registry) + notes_names(args.names_dir)
                 + project_names(args.projects_root))
        names += family_stems(names) + plan_topic_names(args.names_dir)
        emails = [e for e in config_emails() + args.email if e]
        literals = [t for t in [home.rstrip("/"), host] + emails + args.literal if t.strip()]
        matcher = Matcher(names, literals, allow_words(args.allow, args.allow_file))
        if matcher.name_count == 0:
            raise Refuse("no name left to match after the allow words: this would measure nothing")
        if matcher.literal_count == 0:
            raise Refuse("no literal left to match: this would measure nothing")
        hits, lossy = [], []
        files = scan_trees(args.trees, matcher, hits, lossy)
        commits, binaries, tags = (scan_history(matcher, args.range, not args.no_authors, hits)
                                   if args.history else (0, 0, 0))
    except Refuse as e:
        print(f"leak-check: {e}", file=sys.stderr)
        return 2

    for label, where in hits:
        print(f"{label} {where}")
    totals = {}
    for label, _ in hits:
        totals[label] = totals.get(label, 0) + 1
    scope = f"{files} files" + (f", {commits} commits, {tags} tags" if args.history else "")
    print(f"leak-check: {matcher.name_count} names, {matcher.literal_count} "
          f"literals; scanned {scope}; {len(hits)} hits", file=sys.stderr)
    if lossy:
        kinds = {}
        for why, _ in lossy:
            kinds[why] = kinds.get(why, 0) + 1
        print("leak-check: content scanned after lossy decoding: "
              + ", ".join(f"{n} {why}" for why, n in sorted(kinds.items())), file=sys.stderr)
        for why, rel in lossy:
            print(f"  lossy ({why}) {rel}", file=sys.stderr)
    if binaries:
        print(f"leak-check: {binaries} binary diffs in history, content not scanned "
              "(paths were)", file=sys.stderr)
    for label, n in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {label} {n}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
