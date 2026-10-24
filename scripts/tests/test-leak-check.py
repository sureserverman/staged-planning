#!/usr/bin/env python3
"""Fixture tests for scripts/leak-check.py.

A leak check that only ever passes is indistinguishable from one that reads nothing. So
every source of names is planted in a throwaway registry, notes tree and projects root,
and each must go red on a line that names it; the near-misses that must stay green (a
name inside a longer word, a two-letter name, a folder three deep) are planted beside
them. History cases build a throwaway git repo whose global config is a temp file, so the
machine's own global config is never read.

Every value is invented and built at run time from fragments, so this file itself holds
no home path, address or owner name for either check to find.

Stdlib only.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "leak-check.py")

FAILURES = []

# Fragments, joined at run time.
GLOBAL_ADDR = "owner.one" + "@" + "fake-mail.test"
LOCAL_ADDR = "local.two" + "@" + "fake-mail.test"
EXTRA_ADDR = "extra.three" + "@" + "fake-mail.test"
INC_ADDR = "inc.four" + "@" + "fake-mail.test"
HOSTNAME = "fakehost" + "-q7"
FULL_NAME = "Omega" + " Person"
HANDLE = "omega" + "hndl"
ALL_NAMES = ["alpha-widget", "beta_gadget", "theta-flow", "gamma-tool", "delta-kit",
             "group-x", "epsilon-box"]


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class World:
    """A fake registry, notes tree, projects root, home and global git config."""

    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="leak-")
        b = self.base
        self.home = os.path.join(b, "fakehome")
        os.makedirs(self.home)
        self.registry = os.path.join(b, "reg.yaml")
        write(self.registry, "version: 1\nprojects:\n"
              "  - path: x\n    name: alpha-widget\n"
              "  - path: x\n    name: \"beta_gadget\"  # quoted, underscore spelling\n"
              "  - path: x\n    name: ab\n"
              "  - {name: theta-flow, path: y}\n")
        self.names_dir = os.path.join(b, "notes", "projects")
        os.makedirs(os.path.join(self.names_dir, "area-one", "gamma-tool"))
        self.projects = os.path.join(b, "proj")
        for d in ("delta-kit", os.path.join("group-x", "epsilon-box"),
                  os.path.join("group-x", "epsilon-box", "zeta-deep"),
                  ".hidden-thing", os.path.join("group-x", ".hidden-two")):
            os.makedirs(os.path.join(self.projects, d))
        self.gitconfig = os.path.join(b, "global.gitconfig")
        write(self.gitconfig, f"[user]\n\temail = {GLOBAL_ADDR}\n\tname = Fake Owner\n")
        self.work = os.path.join(b, "work")
        os.makedirs(self.work)
        self.env = dict(os.environ, HOME=self.home, GIT_CONFIG_GLOBAL=self.gitconfig,
                        GIT_CONFIG_NOSYSTEM="1")
        self.env.pop("GIT_DIR", None)
        self.env.pop("GIT_WORK_TREE", None)

    def base_args(self, home=True):
        args = ["--registry", self.registry, "--names-dir", self.names_dir,
                "--projects-root", self.projects, "--hostname", HOSTNAME]
        if home:
            args += ["--home", self.home]
        return args

    def run(self, *args, cwd=None, home=True, raw=False, env=None):
        argv = list(args) if raw else self.base_args(home) + list(args)
        p = subprocess.run([sys.executable, SCRIPT, *argv], capture_output=True, text=True,
                           cwd=cwd or self.work, env=dict(self.env, **(env or {})))
        return p.returncode, p.stdout, p.stderr

    def git(self, repo, *args, email=None):
        env = dict(self.env)
        if email:
            env.update(GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_EMAIL=email,
                       GIT_AUTHOR_NAME="Fake Author", GIT_COMMITTER_NAME="Fake Author")
        p = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(f"git {args}: {p.stderr}")
        return p.stdout.strip()


def names(stdout):
    return sorted({line.split(" ", 1)[0] for line in stdout.splitlines() if line.strip()})


def tree_cases():
    w = World()
    print("every name source goes red, in every spelling")
    planted = {
        "alpha-widget": "uses alpha_widget here",       # registry name, _ spelling
        "alpha-widget ": "UPPER ALPHA-WIDGET case",     # case-insensitive
        "alpha-widget  ": "a path /x/alpha-widget/y",   # inside a path
        "beta_gadget": "the beta-gadget bit",           # registry _ name, - spelling
        "gamma-tool": "see gamma_tool notes",           # a --names-dir folder
        "delta-kit": "built delta-kit.",                # projects root, one deep
        "epsilon-box": "and epsilon-box too",           # projects root, two deep
        "group-x": "under group-x there",               # projects root, one deep
        "theta-flow": "a theta-flow entry",             # registry flow-style entry
    }
    for name, line in planted.items():
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, err = w.run("core")
        check(rc == 1 and names(out) == [name.strip()],
              f"{name.strip()!r} red on {line!r} (rc={rc}, got {names(out)})")
        check(f"{name.strip()} core/a.md:1" in out.splitlines(),
              f"{name.strip()!r} reports <name> <path>:<line> ({out!r})")
        check(f"{name.strip()} 1" in err, f"{name.strip()!r} total on stderr ({err!r})")

    print("every spelling form goes red: space, dot, joined, camel")
    for line in ("an alpha widget here", "the alpha.widget module", "alphawidget joined",
                 "class AlphaWidget:", "x/ALPHA.WIDGET/y"):
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, _ = w.run("core")
        check(rc == 1 and out.splitlines() == ["alpha-widget core/a.md:1"],
              f"alpha-widget red on {line!r} (rc={rc}, {out!r})")

    print("literal sources go red")
    for label, line in {"home": f"cd {w.home}/x", "email": f"mail {GLOBAL_ADDR}",
                        "hostname": f"on {HOSTNAME.upper()} box"}.items():
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, _ = w.run("core")
        check(rc == 1 and len(out.splitlines()) == 1, f"{label} literal red (rc={rc}, {out!r})")
    write(os.path.join(w.work, "core", "a.md"), f"cd {w.home}/x\n")
    rc, out, _ = w.run("core", home=False)
    check(rc == 1 and out.startswith(w.home + " "), f"--home defaults to $HOME (rc={rc}, {out!r})")

    print("near-misses stay green")
    write(os.path.join(w.work, "core", "a.md"),
          "alpha-widgets and xalpha-widget and alpha-widget2\n"
          "alphawidgets and xalphawidget and alpha.widgets and alpha widget9\n"
          "ab is too short to be a name\nzeta-deep is three deep\n"
          "see .hidden-thing and .hidden-two, dot folders\narea-one is a grouping folder\n")
    rc, out, err = w.run("core")
    check(rc == 0 and out.strip() == "", f"near-misses produce no hit (rc={rc}, {out!r})")
    check("names" in err, f"stderr says how many names it measured ({err!r})")

    print("--literal adds a source; allow words never suppress a literal")
    for lit, line in ((FULL_NAME, f"by {FULL_NAME.upper()} here"), (HANDLE, f"ping @{HANDLE}")):
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, _ = w.run("--literal", FULL_NAME, "--literal", HANDLE, "core")
        check(rc == 1 and out.splitlines() == [f"{lit} core/a.md:1"],
              f"--literal {lit!r} red (rc={rc}, {out!r})")
        rc, out, _ = w.run("--literal", lit, "--allow", lit, "core")
        check(rc == 1 and out.splitlines() == [f"{lit} core/a.md:1"],
              f"--allow does not suppress --literal {lit!r} (rc={rc}, {out!r})")
    for label, lit, line in (("hostname", HOSTNAME, f"on {HOSTNAME}"),
                             ("home", w.home, f"cd {w.home}/x"),
                             ("email", GLOBAL_ADDR, f"mail {GLOBAL_ADDR}")):
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, _ = w.run("--allow", lit, "core")
        check(rc == 1 and len(out.splitlines()) == 1,
              f"--allow does not suppress the {label} literal (rc={rc}, {out!r})")

    print("a name in a file path goes red; the tree's own absolute path does not")
    write(os.path.join(w.work, "pathcase", "sub", "alpha-widget-notes.md"), "clean\n")
    rc, out, _ = w.run("pathcase")
    check(rc == 1 and out.splitlines() == ["alpha-widget pathcase/sub/alpha-widget-notes.md:path"],
          f"a clean file named after a project is a <path>:path hit (rc={rc}, {out!r})")
    write(os.path.join(w.work, "pathcase", "sub", "gamma_tool"), "gamma-tool\n")
    rc, out, _ = w.run("pathcase/sub/gamma_tool")
    check(rc == 1 and sorted(out.splitlines()) == ["gamma-tool pathcase/sub/gamma_tool:1",
                                                   "gamma-tool pathcase/sub/gamma_tool:path"],
          f"a single-file tree reports both content and path (rc={rc}, {out!r})")
    absolute = os.path.join(w.home, "delta-kit")
    write(os.path.join(absolute, "x.md"), "clean\n")
    rc, out, _ = w.run(absolute)
    check(rc == 0 and out.strip() == "",
          f"an absolute tree is matched relative to itself (rc={rc}, {out!r})")

    print("NUL-byte, UTF-16 and non-UTF-8 files are scanned and counted on stderr")
    os.makedirs(os.path.join(w.work, "bincase"))
    with open(os.path.join(w.work, "bincase", "nul.dat"), "wb") as fh:
        fh.write(b"a\x00b alpha-widget\n")
    with open(os.path.join(w.work, "bincase", "latin.txt"), "wb") as fh:
        fh.write(b"caf\xe9 delta-kit\n")
    with open(os.path.join(w.work, "bincase", "bom16.txt"), "wb") as fh:
        fh.write("x\ngamma-tool here\n".encode("utf-16"))
    with open(os.path.join(w.work, "bincase", "le16.txt"), "wb") as fh:
        fh.write("theta-flow here\n".encode("utf-16-le"))
    rc, out, err = w.run("bincase")
    check(rc == 1 and sorted(out.splitlines()) == [
        "alpha-widget bincase/nul.dat:1", "delta-kit bincase/latin.txt:1",
        "gamma-tool bincase/bom16.txt:2", "theta-flow bincase/le16.txt:1"],
        f"NUL, non-UTF-8 and UTF-16 content is scanned (rc={rc}, {out!r})")
    check("2 NUL bytes" in err and "1 not UTF-8" in err and "1 UTF-16" in err
          and "bincase/nul.dat" in err and "bincase/latin.txt" in err
          and "bincase/bom16.txt" in err, f"stderr counts and names those files ({err!r})")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        locked = os.path.join(w.work, "lockcase", "locked.md")
        write(locked, "x\n")
        os.chmod(locked, 0)
        rc, _, err = w.run("lockcase")
        os.chmod(locked, 0o600)
        check(rc == 2, f"an unreadable file exits 2 (rc={rc}, {err.strip()!r})")
        lockdir = os.path.join(w.work, "lockdir", "sub")
        write(os.path.join(lockdir, "x.md"), "alpha-widget\n")
        os.chmod(lockdir, 0)
        rc, _, err = w.run("lockdir")
        os.chmod(lockdir, 0o700)
        check(rc == 2, f"an unreadable subdirectory exits 2 (rc={rc}, {err.strip()!r})")

    print("a symlink is never followed; its name and link text are scanned")
    write(os.path.join(w.work, "outside", "x.md"), "group-x inside\n")
    write(os.path.join(w.work, "outside", "f.md"), "delta-kit inside\n")
    write(os.path.join(w.work, "linkcase", "real", "clean.md"), "clean\n")
    lc = os.path.join(w.work, "linkcase")
    os.symlink("../outside", os.path.join(lc, "alpha-widget"))      # dir link, named path
    os.symlink(os.path.join(w.home, "x"), os.path.join(lc, "to-home"))
    os.symlink("../outside/f.md#gamma-tool", os.path.join(lc, "f.md"))
    os.symlink("../outside/f.md", os.path.join(lc, "plain.md"))     # file link, clean text
    os.symlink("nowhere-epsilon-box", os.path.join(lc, "dangle"))
    os.symlink("real", os.path.join(lc, "dirlink"))
    rc, out, err = w.run("linkcase")
    check(rc == 1 and sorted(out.splitlines()) == sorted([
        "alpha-widget linkcase/alpha-widget:path", f"{w.home} linkcase/to-home:link",
        "gamma-tool linkcase/f.md:link", "epsilon-box linkcase/dangle:link"]),
        f"links reported by name and text, targets never read (rc={rc}, {out!r}, {err!r})")

    print("allow words and the allow file suppress")
    write(os.path.join(w.work, "core", "a.md"), "alpha-widget\ndelta-kit\ngamma-tool\n")
    rc, out, _ = w.run("--allow", "alpha_widget", "core")
    check(rc == 1 and names(out) == ["delta-kit", "gamma-tool"],
          f"--allow suppresses one name in any spelling (rc={rc}, {names(out)})")
    allow = os.path.join(w.base, "allow.txt")
    write(allow, "# owner-reviewed\ndelta-kit  # a common word\n\nGAMMA-TOOL\n")
    rc, out, _ = w.run("--allow-file", allow, "--allow", "alpha-widget", "core")
    check(rc == 0 and out.strip() == "", f"--allow-file plus --allow clear every hit (rc={rc}, {out!r})")

    print("refuses, never skips")
    missing = os.path.join(w.base, "missing")
    write(os.path.join(w.work, "core", "a.md"), "clean\n")
    cases = {
        "registry unreadable": ["--registry", missing, "--names-dir", w.names_dir, "--projects-root",
                                w.projects, "--hostname", HOSTNAME, "--home", w.home, "core"],
        "names dir missing": ["--registry", w.registry, "--names-dir", missing,
                                        "--projects-root", w.projects, "--hostname", HOSTNAME,
                                        "--home", w.home, "core"],
        "projects root missing": ["--registry", w.registry, "--names-dir", w.names_dir,
                                  "--projects-root", missing, "--hostname", HOSTNAME,
                                  "--home", w.home, "core"],
    }
    for label, argv in cases.items():
        rc, _, err = w.run(*argv, raw=True)
        check(rc == 2, f"{label} exits 2 (rc={rc}, {err.strip()!r})")
    empty_reg = os.path.join(w.base, "empty.yaml")
    write(empty_reg, "version: 1\nprojects: []\n")
    rc, _, _ = w.run("--registry", empty_reg, "--names-dir", w.names_dir, "--projects-root", w.projects,
                     "--hostname", HOSTNAME, "--home", w.home, "core", raw=True)
    check(rc == 2, f"a registry with no name: entry exits 2 (rc={rc})")
    for label, extra in {"allow file missing": ["--allow-file", missing, "core"],
                         "tree missing": ["nope"], "no tree and no --history": [],
                         "--range without --history": ["--range", "HEAD", "core"],
                         "--no-authors without --history": ["--no-authors", "core"]}.items():
        rc, _, _ = w.run(*extra)
        check(rc == 2, f"{label} exits 2 (rc={rc})")
    rc, out, _ = w.run("core")
    check(rc == 0, f"a clean tree exits 0 (rc={rc}, {out!r})")
    allow_all = [a for n in ALL_NAMES for a in ("--allow", n)]
    rc, _, err = w.run(*allow_all, "core")
    check(rc == 2, f"allow words that empty the name set exit 2 (rc={rc}, {err.strip()!r})")
    rc, _, _ = w.run(*allow_all[:-2], "core")
    check(rc == 0, f"one name left is a measurement (rc={rc})")
    empty_names = os.path.join(w.base, "emptynames")
    os.makedirs(os.path.join(empty_names, "area-only"))
    empty_proj = os.path.join(w.base, "emptyproj")
    os.makedirs(os.path.join(empty_proj, ".dot-only"))
    for label, ndir, proj in (("an empty names dir", empty_names, w.projects),
                               ("an empty projects root", w.names_dir, empty_proj)):
        rc, _, err = w.run("--registry", w.registry, "--names-dir", ndir, "--projects-root", proj,
                           "--hostname", HOSTNAME, "--home", w.home, "core", raw=True)
        check(rc == 2, f"{label} exits 2 (rc={rc}, {err.strip()!r})")


def history_cases():
    w = World()
    repo = os.path.join(w.base, "repo")
    os.makedirs(repo)
    w.git(repo, "init", "-q", "-b", "main")
    w.git(repo, "config", "user.email", LOCAL_ADDR)

    write(os.path.join(repo, "notes.md"), "made for gamma-tool\n")
    w.git(repo, "add", "notes.md")
    w.git(repo, "commit", "-q", "-m", "one\n\nbody names epsilon-box only here", email=EXTRA_ADDR)
    old = w.git(repo, "rev-parse", "HEAD")
    write(os.path.join(repo, "notes.md"), "clean now\n")
    w.git(repo, "commit", "-q", "-am", "two", email="ok" + "@" + "neutral.test")
    write(os.path.join(repo, "more.md"), "then delta-kit\n")
    w.git(repo, "add", "more.md")
    w.git(repo, "commit", "-q", "-m", "three", email="ok" + "@" + "neutral.test")
    new = w.git(repo, "rev-parse", "HEAD")
    os.remove(os.path.join(repo, "more.md"))

    print("--history finds a name only in an old commit, and an author email")
    rc, out, _ = w.run(".", cwd=repo)
    check(rc == 0 and out.strip() == "", f"the working tree alone is clean (rc={rc}, {out!r})")
    rc, out, _ = w.run("--email", EXTRA_ADDR, "--history", ".", cwd=repo)
    lines = out.splitlines()
    check(rc == 1 and f"gamma-tool {old}:notes.md" in lines,
          f"old-commit name reported as <name> <commit>:<path> (rc={rc}, {out!r})")
    check(f"{EXTRA_ADDR} {old}:author" in lines, f"--email author address found ({out!r})")
    check(f"delta-kit {new}:more.md" in lines, f"newest commit scanned too ({out!r})")
    rc, out, _ = w.run("--history", cwd=repo)
    check(rc == 1 and f"gamma-tool {old}:notes.md" in out, f"--history needs no tree (rc={rc})")
    check(f"epsilon-box {old}:message" in out.splitlines(),
          f"a name only in an old commit's message is found ({out!r})")
    check(EXTRA_ADDR not in out, f"without --email the extra address is no source ({out!r})")

    print("--range excludes a commit outside it")
    rc, out, _ = w.run("--email", EXTRA_ADDR, "--history", "--range", "HEAD~1..HEAD", cwd=repo)
    check(rc == 1 and f"delta-kit {new}:more.md" in out.splitlines()
          and "gamma-tool" not in out and EXTRA_ADDR not in out and "epsilon-box" not in out,
          f"only the ranged commit is scanned (rc={rc}, {out!r})")
    rc, _, _ = w.run("--history", "--range", "no-such-ref..HEAD", cwd=repo)
    check(rc == 2, f"a bad range exits 2 (rc={rc})")

    print("--no-authors drops author hits, keeps diff hits")
    rc, out, _ = w.run("--email", EXTRA_ADDR, "--history", "--no-authors", cwd=repo)
    check(rc == 1 and EXTRA_ADDR not in out and f"gamma-tool {old}:notes.md" in out.splitlines(),
          f"author line skipped, diff name kept (rc={rc}, {out!r})")
    check(f"epsilon-box {old}:message" in out.splitlines(),
          f"--no-authors keeps message hits ({out!r})")

    print("the global and the repo-local user.email are both sources")
    write(os.path.join(repo, "who.md"), f"global {GLOBAL_ADDR}\n")
    rc, out, _ = w.run("who.md", cwd=repo)
    check(rc == 1 and out.startswith(GLOBAL_ADDR + " who.md:1"),
          f"global address is a source inside a repo with a local override (rc={rc}, {out!r})")
    write(os.path.join(repo, "who.md"), f"local {LOCAL_ADDR}\n")
    rc, out, _ = w.run("who.md", cwd=repo)
    check(rc == 1 and out.startswith(LOCAL_ADDR + " who.md:1"),
          f"the repo-local address is a source (rc={rc}, {out!r})")
    write(os.path.join(repo, "who.md"), f"extra {EXTRA_ADDR}\n")
    rc, out, _ = w.run("--email", EXTRA_ADDR, "who.md", cwd=repo)
    check(rc == 1 and out.startswith(EXTRA_ADDR + " who.md:1"), f"--email adds a source (rc={rc}, {out!r})")
    os.remove(os.path.join(repo, "who.md"))
    inc = os.path.join(w.base, "inc.gitconfig")
    write(inc, f"[user]\n\temail = {INC_ADDR}\n")
    with open(w.gitconfig, encoding="utf-8") as fh:
        saved = fh.read()
    write(w.gitconfig, f"[include]\n\tpath = {inc}\n" + saved)
    write(os.path.join(w.work, "inc.md"), f"inc {INC_ADDR}\n")
    rc, out, _ = w.run("inc.md")
    write(w.gitconfig, saved)
    check(rc == 1 and out.startswith(INC_ADDR + " inc.md:1"),
          f"an address only in an [include]d global file is a source (rc={rc}, {out!r})")

    print("--history outside a git repo exits 2")
    rc, _, _ = w.run("--history", cwd=w.work)
    check(rc == 2, f"no repo exits 2 (rc={rc})")


def history_config_cases():
    w = World()
    repo = os.path.join(w.base, "repo")
    os.makedirs(repo)
    w.git(repo, "init", "-q", "-b", "main")
    write(os.path.join(repo, "notes.md"), "made for gamma-tool\n")
    write(os.path.join(repo, "plain.md"), "clean\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "root")
    root = w.git(repo, "rev-parse", "HEAD")
    quoted = 'say"hi there.md'
    write(os.path.join(repo, quoted), "quoted delta-kit\n")
    with open(os.path.join(repo, "blob.dat"), "wb") as fh:
        fh.write(b"\x00\x01 binary\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "quoted")
    qc = w.git(repo, "rev-parse", "HEAD")
    w.git(repo, "checkout", "-q", "-b", "side")
    write(os.path.join(repo, "side.md"), "side clean\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "side")
    w.git(repo, "checkout", "-q", "main")
    write(os.path.join(repo, "main.md"), "main clean\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "main")
    w.git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    write(os.path.join(repo, "merge.md"), "evil group-x\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "merge")
    merge = w.git(repo, "rev-parse", "HEAD")
    w.git(repo, "mv", "plain.md", "alpha-widget-plan.md")
    w.git(repo, "commit", "-q", "-m", "move")
    moved = w.git(repo, "rev-parse", "HEAD")
    w.git(repo, "tag", "-a", "v1", "-m", "ships epsilon-box")
    w.git(repo, "tag", "theta-flow-1")
    w.git(repo, "notes", "add", "-m", "note for beta_gadget", root)
    hostile = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "diff.noprefix",
               "GIT_CONFIG_VALUE_0": "true", "GIT_CONFIG_KEY_1": "log.showRoot",
               "GIT_CONFIG_VALUE_1": "false"}

    print("--history ignores the user's diff config")
    rc, out, err = w.run("--history", "--no-authors", cwd=repo, env=hostile)
    lines = out.splitlines()
    check(rc == 1 and f"gamma-tool {root}:notes.md" in lines,
          f"diff.noprefix and log.showRoot=false hide nothing (rc={rc}, {out!r}, {err!r})")
    check(f"delta-kit {qc}:{quoted}" in lines, f"a C-quoted +++ path is parsed ({out!r})")
    check("1 binary" in err, f"a binary diff is counted on stderr ({err!r})")

    print("--history scans merges, moved paths, tags and notes")
    check(f"group-x {merge}:merge.md" in lines, f"a name added in a merge is found ({out!r})")
    check(f"alpha-widget {moved}:path" in lines, f"a git mv to a named path is found ({out!r})")
    check("epsilon-box tag:v1" in lines, f"an annotated tag message is found ({out!r})")
    check("theta-flow tag:theta-flow-1" in lines, f"a tag name is found ({out!r})")
    check(any(l.startswith("beta_gadget ") and l.endswith(":" + root) for l in lines),
          f"a git note is found ({out!r})")
    rc, out, _ = w.run("--history", "--no-authors", "--range", "HEAD~1..HEAD", cwd=repo,
                       env=hostile)
    check(rc == 1 and out.splitlines() == [f"alpha-widget {moved}:path"],
          f"--range scans only its commits, no tags (rc={rc}, {out!r})")

    print("a C-quoted diff --git path and a hostile commit message are parsed")
    tabbed = "d\tdelta-kit.txt"
    write(os.path.join(repo, tabbed), "clean\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "tabbed")
    tc = w.git(repo, "rev-parse", "HEAD")
    w.git(repo, "commit", "-q", "--allow-empty", "-m",
          "hostile\n\n\x02end-message\n+++ q/zz\ndiff --git nope\n\x01commit zz\n"
          "later names theta-flow")
    hc = w.git(repo, "rev-parse", "HEAD")
    rc, out, err = w.run("--history", "--no-authors", "--range", "HEAD~2..HEAD", cwd=repo)
    lines = out.splitlines()
    check(rc == 1 and f"delta-kit {tc}:path" in lines,
          f"a name in a C-quoted header path is found (rc={rc}, {out!r}, {err!r})")
    check(f"theta-flow {hc}:message" in lines,
          f"a message line can neither end the message nor crash the scan ({out!r})")

    print("an unparsable +++ header exits 2")
    shim = os.path.join(w.base, "shim")
    os.makedirs(shim)
    write(os.path.join(shim, "git"),
          "#!/bin/sh\n" + f"'{shutil.which('git')}' \"$@\" | sed 's|^+++ b/|+++ q/|'\n")
    os.chmod(os.path.join(shim, "git"), 0o755)
    rc, out, err = w.run("--history", "--no-authors", cwd=repo,
                         env={"PATH": shim + os.pathsep + os.environ.get("PATH", "")})
    check(rc == 2 and "+++" in err, f"a +++ header without b/ is refused (rc={rc}, {err.strip()!r})")


def replace_cases():
    w = World()
    repo = os.path.join(w.base, "repo")
    os.makedirs(repo)
    w.git(repo, "init", "-q", "-b", "main")
    write(os.path.join(repo, "notes.md"), "clean\n")
    w.git(repo, "add", ".")
    w.git(repo, "commit", "-q", "-m", "root")
    root = w.git(repo, "rev-parse", "HEAD")
    write(os.path.join(repo, "notes.md"), "made for gamma-tool\n")
    w.git(repo, "commit", "-q", "-am", "leak names epsilon-box")
    leak = w.git(repo, "rev-parse", "HEAD")
    write(os.path.join(repo, "notes.md"), "clean now\n")
    w.git(repo, "commit", "-q", "-am", "tidy")
    w.git(repo, "replace", leak, root)

    print("a replace ref cannot hide a commit")
    rc, out, err = w.run("--history", "--no-authors", cwd=repo)
    lines = out.splitlines()
    check(rc == 1 and f"gamma-tool {leak}:notes.md" in lines
          and f"epsilon-box {leak}:message" in lines,
          f"the replaced commit is scanned as written (rc={rc}, {out!r}, {err!r})")


def plan_name_cases():
    """A family stem, and every plan's topic and title, are names too."""
    w = World()
    with open(w.registry, "a", encoding="utf-8") as fh:
        fh.write("  - path: x\n    name: kappa-front\n  - path: x\n    name: kappa-back\n"
                 "  - path: x\n    name: lambda-solo\n")
    plans = os.path.join(w.names_dir, "area-one", "gamma-tool", "plans")
    write(os.path.join(plans, "2026-01-02-quartz-river-rollout-plan.md"),
          "# Project Plan: Velvet Harbor Lantern\n\nbody\n")
    write(os.path.join(plans, "2026-01-03-ember-loom-master-plan.md"), "# Master Plan: x\n")
    write(os.path.join(plans, "2026-01-03-ember-loom-sub-02-copper-tide-plan.md"), "# Plan\n")
    write(os.path.join(plans, "2026-01-04-tiny-plan.md"), "# Light Plan: Two Words\n")
    cases = {
        "kappa": "the kappa shape again",                     # stem of two names
        "quartz-river-rollout": "see quartz_river_rollout",   # a plan's topic
        "velvet harbor lantern": "the Velvet Harbor Lantern plan",   # its title
        "ember-loom": "ember-loom-master",                    # a master's topic
        "copper-tide": "sub-02-copper-tide",                  # a sub-plan's topic
    }
    for want, line in cases.items():
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, err = w.run("core")
        check(rc == 1 and want in out.lower(),
              f"{want!r} is a name: {line!r} (rc={rc}, {out!r}, {err!r})")
    for line in ("lambda alone is no family", "a tiny thing", "two words here"):
        write(os.path.join(w.work, "core", "a.md"), line + "\n")
        rc, out, _ = w.run("core")
        check(rc == 0, f"not a name: {line!r} (rc={rc}, {out!r})")
    write(os.path.join(w.work, "core", "a.md"), "quartz river rollout\n")
    rc, out, _ = w.run("--allow", "quartz-river-rollout", "core")
    check(rc == 0, f"an allow word suppresses a plan topic too (rc={rc}, {out!r})")


def main():
    tree_cases()
    plan_name_cases()
    replace_cases()
    history_cases()
    history_config_cases()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S)")
        return 1
    print("\nall leak-check cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
