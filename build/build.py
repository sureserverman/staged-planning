#!/usr/bin/env python3
"""Build one host's planning package from `core/` plus `hosts/<host>/`.

The generated directory is committed, because Claude Code installs a plugin
straight from the git repo with no build step. So the build has to be
reproducible and `--check` has to prove the output matches the sources.

Steps, in order, configured by hosts/<host>/host.yaml (schema: host_schema.py):
  1. copy every file under core/, less the host's `exclude:` globs. A host other
     than the identity host (claude) never ships tests or fixtures: any path
     with a `tests`, `fixtures` or `test-fixtures` directory is left out.
  2. apply the host's `rewrites:` in order, each to the core files its glob
     matches
  3. replace whole files from hosts/<host>/overrides/<core-relpath>
  4. move the paths the host's `moves:` names, each a file or directory the host
     ships from core/ (an override is still keyed, and locked, by its core path)
  5. copy every file under hosts/<host>/add/ on top (a host-only file must
     not collide with a core file — a host version of a core file is an
     override, not an addition)
  6. stamp the repo's VERSION into each built .<name>-plugin/plugin.json, and,
     for claude, into the root marketplace entry naming the output (plus the
     marketplace's metadata version). A host-only file named <name>.tmpl is
     written as <name>, with each {{VERSION}} in it replaced by VERSION.

Every override is locked in hosts/<host>/overrides.lock, which records the
sha256 of the core file it was last reread against. The build and `--check`
fail on an override with no lock entry, a lock entry with no override, a core
file that changed since its override was locked (a stale override: reread it,
then `--relock` it in the same commit), and a script override whose entry names
no `host_fact` (a script fork must name the host fact that forces it). An override
that loads another core file at run time names it under `depends_on`, with that
file's sha256; a change to it makes the override stale too, and `--relock`
refreshes those digests with the override's own.
`--no-lock-check` skips these for a development build; a gate or CI never
passes it.

VERSION is the one version source. A source plugin.json carrying its own
version is refused, because two sources would drift. The marketplace file is a
source the build also writes, so `--check` compares its versions to VERSION
and fails when the build has not been run since VERSION changed.

Only files git would track are copied: tracked files plus untracked files
that are not ignored. So __pycache__ and other local junk never reach the
package, and a new file reaches it before it is committed. Two things are
refused rather than skipped, because skipping them would ship a package
missing a file with nothing saying so:
  - a source file that .gitignore matches (a user's global gitignore may
    ignore names such as CLAUDE.md, AGENTS.md, .cursor/ or plans/, and a
    host layer may legitimately ship any of them)
  - a symlink, which the copy would flatten or drop

What `--check` compares:
  --check              the output on disk against what the sources on disk
                       produce. On a clean checkout (CI, or a gate run after
                       the commit) that is the committed copy; with
                       uncommitted changes it is not, and the check says so.
  --check --committed  HEAD's output against what HEAD's sources produce,
                       whatever the working tree holds.

Another repo can build its own core/ + hosts/ root with `--root <dir>` (relative
to the cwd). A host's output, relative to the root's git toplevel, is its
host.yaml `out`, or else the root's build.json entry
({"outputs": {"<host>": "<path>"}}); when both name one they must agree.
VERSION and the marketplace file are looked for in the root. Without `--root`,
this repo is the root and OUTPUTS stands in for build.json.

Usage:
  python3 build/build.py --host claude                       write plugins/claude/planning
  python3 build/build.py --host claude --check               exit 1 if the output on disk differs
  python3 build/build.py --host claude --check --committed   exit 1 if HEAD's output differs
  python3 <this repo>/build/build.py --root <dir> --host claude [--check [--committed]]
  python3 build/build.py --host codex --out <dir>             write the build to <dir> instead
  python3 build/build.py --host codex --relock <path>...      lock overrides to today's core
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

# The build writes only its output: no bytecode cache beside the tool either.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import host_schema  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = {"claude": "plugins/claude/planning"}
# What this run builds: the root holding core/ and hosts/, the git toplevel the
# output paths are relative to, and the outputs. `--root` rebinds all three.
ROOT, TOP, outputs = REPO_ROOT, REPO_ROOT, OUTPUTS
# Local byproducts the test suite writes into the sources. Ignored, and never
# part of a package, so they are the one ignored population that is not an error.
BYPRODUCTS = ("__pycache__",)
# What Claude Code writes into a plugin directory it loads (`--plugin-dir`, or a local
# marketplace installing in place), as paths under the output root. Matched by path, not by
# name: the plugin ships a `types/` of its own. Untracked, they never ship; a rebuild
# replaces them.
LOADER_BYPRODUCTS = ("tsconfig.json", ".claude-plugin/types")
VERSION_FILE = "VERSION"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
# A built plugin manifest, whichever host's: .claude-plugin/plugin.json, .codex-plugin/...
MANIFEST_RE = re.compile(r"^\.[a-z0-9-]+-plugin/plugin\.json$")
# The marketplace file VERSION owns, per host. A host not listed has none here.
MARKETPLACES = {"claude": os.path.join(".claude-plugin", "marketplace.json")}
# A marketplace whose entries carry no version: the build only checks that one entry
# names the host's output, so a moved output cannot leave the entry pointing elsewhere.
ENTRY_MARKETPLACES = {"codex": os.path.join(".agents", "plugins", "marketplace.json")}
# The identity host ships core/ + add/ as written. Every other host leaves out the
# test trees, which run only from the sources.
IDENTITY_HOST = "claude"
TEST_DIRS = ("tests", "fixtures", "test-fixtures")
# A host-only file with this suffix ships without it, its {{VERSION}} filled from VERSION.
TEMPLATE_EXT = ".tmpl"
SCRIPT_EXTS = (".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rb",
               ".pl", ".ps1")


class BuildError(Exception):
    pass


def git(*args, cwd=None):
    return subprocess.run(["git", "-C", cwd or ROOT, *args],
                          check=True, capture_output=True).stdout


def top_rel(rel):
    """A root-relative path, made relative to the root's git toplevel."""
    return os.path.normpath(os.path.join(os.path.relpath(ROOT, TOP), rel))


def load_root(root):
    """Point the build at another core/ + hosts/ root."""
    global ROOT, TOP
    ROOT = os.path.realpath(root)
    r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError(f"{root} is not inside a git work tree")
    TOP = os.path.realpath(r.stdout.strip())


def build_json_outputs():
    """The root's build.json outputs, OUTPUTS for this repo, or {} when it has none."""
    if ROOT == REPO_ROOT:
        return dict(OUTPUTS), "OUTPUTS"
    path = os.path.join(ROOT, "build.json")
    if not os.path.isfile(path):
        return {}, path
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    outs = doc.get("outputs") if isinstance(doc, dict) else None
    if not isinstance(outs, dict) or not outs \
            or not all(isinstance(v, str) and v for v in outs.values()):
        raise BuildError(f'{path} must hold {{"outputs": {{"<host>": "<path>"}}}}')
    return outs, path


def host_yaml(src_root, host):
    return os.path.join(src_root, "hosts", host, "host.yaml")


def host_config(src_root, host):
    """The host's host.yaml, or the empty configuration when it has none."""
    path = host_yaml(src_root, host)
    if not os.path.isfile(path):
        return {"host": host, "out": None, "exclude": [], "rewrites": [], "features": [],
                "moves": []}
    try:
        return host_schema.load_host(path, host)
    except host_schema.SchemaError as e:
        raise BuildError(str(e)) from None


def load_outputs():
    """Each host's output, from build.json (or OUTPUTS) and host.yaml `out`, guarded."""
    global outputs
    outs, where = build_json_outputs()
    named = dict(outs)
    hosts_dir = os.path.join(ROOT, "hosts")
    for host in sorted(os.listdir(hosts_dir)) if os.path.isdir(hosts_dir) else []:
        if not os.path.isfile(host_yaml(ROOT, host)):
            continue
        out = host_config(ROOT, host)["out"]
        if host in named and os.path.normpath(named[host]) != os.path.normpath(out):
            raise BuildError(f"{host_yaml(ROOT, host)}: out {out!r} disagrees with {where}'s "
                             f"{named[host]!r}")
        named[host] = out
    if not named:
        raise BuildError(f"{ROOT} names no output: give a host a hosts/<host>/host.yaml "
                         "with `out`, or the root a build.json")
    outputs = {host: guard_output(f"{host}'s output", out) for host, out in named.items()}
    # Each build deletes its own output whole, so no two hosts may share or nest one.
    for a in sorted(outputs):
        for b in sorted(outputs):
            if a < b and (outputs[a] == outputs[b] or outputs[a].startswith(outputs[b] + os.sep)
                          or outputs[b].startswith(outputs[a] + os.sep)):
                raise BuildError(f"{a}'s output {outputs[a]} and {b}'s output {outputs[b]} "
                                 "overlap; each host needs a directory of its own")


def guard_output(label, out, top_relative=True):
    """The output path, relative to TOP, once it is safe to delete and rewrite."""
    sources = [os.path.join(ROOT, d) for d in ("core", "hosts")]
    # The build deletes the output before writing it, so an output outside the
    # toplevel, inside .git, or holding the root or its sources, is refused. An
    # output reached through a symlink is refused too: with a link followed by
    # `..`, the resolved path (what a check sees) and the lexical one (what a
    # delete hits) differ, so the path checked must be the path written.
    # (write() also refuses an existing output holding what the build does not
    # produce.)
    lexical = os.path.normpath(os.path.join(TOP, out))
    full = os.path.realpath(lexical)
    rel = os.path.relpath(full, TOP)
    if full != lexical:
        raise BuildError(f"{label} {out!r} goes through a symlink; name the directory itself")
    inside = not (rel == ".." or rel.startswith(".." + os.sep))
    if (top_relative and (os.path.isabs(out) or not inside)) or rel == "." \
            or ".git" in rel.split(os.sep) or ".git" in os.path.normpath(out).split(os.sep) \
            or full == ROOT or ROOT.startswith(full + os.sep) or TOP.startswith(full + os.sep) \
            or any(full == s or full.startswith(s + os.sep) for s in sources):
        raise BuildError(f"{label} {out!r} must be a directory "
                         + ("inside the git toplevel, " if top_relative else "")
                         + "outside .git, apart from the root and its sources")
    return rel if top_relative else full


def source_files(rel_dir):
    """Repo-relative paths under rel_dir that git tracks or would track."""
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard",
              "--", rel_dir).decode()
    paths = sorted({p for p in out.split("\0") if p})
    # A file deleted from the working tree but still in the index is gone.
    paths = [p for p in paths if os.path.lexists(os.path.join(ROOT, p))]
    links = [p for p in paths if os.path.islink(os.path.join(ROOT, p))]
    if links:
        raise BuildError("symlinks are not supported in sources: " + ", ".join(links))
    ignored = [p for p in git("ls-files", "-z", "--others", "--ignored",
                              "--exclude-standard", "--", rel_dir).decode().split("\0")
               if p and not any(b in p.split("/") for b in BYPRODUCTS)]
    if ignored:
        raise BuildError(".gitignore hides source file(s) that would never ship: "
                         + ", ".join(sorted(ignored))
                         + " — add a negation for them, or move them")
    return paths


def is_test_path(rel):
    return any(part in TEST_DIRS for part in rel.split("/")[:-1])


def layout(host, files_under, src_root):
    """(files, rewrites, overrides) from a lister of source files: output-relative
    path -> source path; output-relative path -> the rewrites its core text takes;
    and core-relpath -> core source path, for each path an override replaces."""
    cfg = host_config(src_root, host)
    where = os.path.relpath(host_yaml(src_root, host), src_root)
    excludes = [(g, host_schema.glob_re(g)) for g in cfg["exclude"]]
    files, core, hit = {}, {}, set()
    for p in files_under("core"):
        rel = os.path.relpath(p, "core")
        core[rel] = p
        if host != IDENTITY_HOST and is_test_path(rel):
            continue
        matched = [g for g, rx in excludes if rx.match(rel)]
        if matched:
            hit.update(matched)
            continue
        files[rel] = p
    # A glob that matches nothing is a typo or a stale entry, and either way it does
    # not do what host.yaml says.
    for g, _ in excludes:
        if g not in hit:
            raise BuildError(f"{where}: exclude {g!r} matches no core file")
    rewrites = {}
    for i, rw in enumerate(cfg["rewrites"]):
        targets = [rel for rel in files if rw["match"].match(rel)]
        if not targets:
            raise BuildError(f"{where}: rewrites[{i}] glob {rw['glob']!r} matches no file "
                             "this host ships from core/")
        for rel in targets:
            rewrites.setdefault(rel, []).append(rw)
    overrides = {}
    ovr = f"hosts/{host}/overrides"
    for p in files_under(ovr):
        rel = os.path.relpath(p, ovr)
        if rel not in core:
            raise BuildError(f"{p} overrides no core file — a host-only file belongs under "
                             f"hosts/{host}/add/")
        if rel not in files:
            raise BuildError(f"{p} overrides core/{rel}, which this host does not ship")
        files[rel] = p
        rewrites.pop(rel, None)
        overrides[rel] = core[rel]
    left = {id(rw) for rws in rewrites.values() for rw in rws}
    for i, rw in enumerate(cfg["rewrites"]):
        if id(rw) not in left:
            raise BuildError(f"{where}: rewrites[{i}] glob {rw['glob']!r} matches only files "
                             "this host overrides, so it changes nothing")
    # A move renames what ships, after the overrides: the lock still names the core path,
    # so a moved file whose core text changes is still caught as stale.
    for i, mv in enumerate(cfg.get("moves") or []):
        src, dst = mv["from"], mv["to"]
        hit = [rel for rel in files if rel == src or rel.startswith(src + "/")]
        if not hit:
            raise BuildError(f"{where}: moves[{i}] from {src!r} names nothing this host "
                             "ships from core/")
        for rel in hit:
            new = dst + rel[len(src):]
            if new in files and new not in hit:
                raise BuildError(f"{where}: moves[{i}] puts {rel} at {new}, where "
                                 f"{files[new]} already ships")
        moved = {dst + rel[len(src):]: files.pop(rel) for rel in hit}
        files.update(moved)
        for rel in hit:
            if rel in rewrites:
                rewrites[dst + rel[len(src):]] = rewrites.pop(rel)
    add = f"hosts/{host}/add"
    for p in files_under(add):
        rel = os.path.relpath(p, add)
        if host != IDENTITY_HOST and is_test_path(rel):
            continue
        if rel.endswith(TEMPLATE_EXT):
            rel = rel[:-len(TEMPLATE_EXT)]
        if rel in core:
            raise BuildError(f"{p} collides with {core[rel]} — "
                             "a host version of a core file is an override, not an addition")
        if rel in files:
            raise BuildError(f"{p} would replace {files[rel]}, which already ships at {rel} "
                             "after the host's moves")
        files[rel] = p
    rels = set(files)
    for rel in rels:
        parent = os.path.dirname(rel)
        while parent:
            if parent in rels:
                raise BuildError(f"{files[rel]} needs {parent}/ to be a directory, "
                                 f"but {files[parent]} is a file there")
            parent = os.path.dirname(parent)
    return files, rewrites, overrides


def sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def lock_path(src_root, host):
    return os.path.join(src_root, "hosts", host, "overrides.lock")


def read_lock(src_root, host):
    path = lock_path(src_root, host)
    if not os.path.isfile(path):
        return {}
    try:
        return host_schema.load_lock(path)
    except host_schema.SchemaError as e:
        raise BuildError(str(e)) from None


def is_script(path):
    if path.endswith(SCRIPT_EXTS) or owner_exec(path):
        return True
    with open(path, "rb") as fh:
        return fh.read(2) == b"#!"


def lock_problems(host, src_root, overrides):
    """Each way the host's overrides and its lock disagree, as a message."""
    lock = read_lock(src_root, host)
    problems = []
    for rel in sorted(overrides):
        entry = lock.get(rel)
        if entry is None:
            problems.append(f"override {rel} has no lock entry — reread it against core/{rel}, "
                            f"then --relock {rel}")
            continue
        if sha256_of(os.path.join(src_root, overrides[rel])) != entry["base_sha256"]:
            problems.append(f"stale override: {rel} — core/{rel} changed since the override "
                            f"was locked; reread the override, then --relock {rel}")
        for dep, digest in sorted(entry.get("depends_on", {}).items()):
            path = os.path.join(src_root, "core", dep)
            if not os.path.isfile(path):
                problems.append(f"override {rel} depends on core/{dep}, which is no core file")
            elif sha256_of(path) != digest:
                problems.append(f"stale override: {rel} — core/{dep}, which it loads, changed "
                                f"since the override was locked; reread the override against "
                                f"it, then --relock {rel}")
        override = os.path.join(src_root, "hosts", host, "overrides", rel)
        if not entry["host_fact"] and is_script(override):
            problems.append(f"script override {rel} names no host_fact in the lock — a script "
                            "fork must name the host fact that forces it")
    for rel in sorted(set(lock) - set(overrides)):
        problems.append(f"lock entry {rel} has no override — remove it from the lock")
    return problems


def relock(host, paths):
    """Lock each named override to the core file as it is now, keeping its host_fact."""
    _, _, overrides = layout(host, source_files, ROOT)
    lock = read_lock(ROOT, host)
    prefix = f"hosts/{host}/overrides/"
    for given in paths:
        rel = os.path.normpath(given).replace(os.sep, "/")
        rel = rel[len(prefix):] if rel.startswith(prefix) else rel
        if rel not in overrides:
            raise BuildError(f"--relock {given}: hosts/{host}/overrides/ has no {rel}")
        fact = lock.get(rel, {}).get("host_fact")
        deps = {}
        for dep in lock.get(rel, {}).get("depends_on", {}):
            path = os.path.join(ROOT, "core", dep)
            if not os.path.isfile(path):
                raise BuildError(f"--relock {given}: its depends_on names core/{dep}, which "
                                 "is no core file")
            deps[dep] = sha256_of(path)
        lock[rel] = {"base_sha256": sha256_of(os.path.join(ROOT, overrides[rel])),
                     "host_fact": fact, "depends_on": deps}
    with open(lock_path(ROOT, host), "w", encoding="utf-8") as fh:
        fh.write(host_schema.dump_lock(lock))
    return len(paths)


def read_version(src_root):
    """The X.Y.Z in src_root/VERSION, or None when there is no VERSION file."""
    path = os.path.join(src_root, VERSION_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        version = fh.read().strip()
    if not VERSION_RE.match(version):
        raise BuildError(f"{VERSION_FILE} must hold one X.Y.Z version, not {version!r}")
    return version


def stamped_manifest(src_path, version):
    """The manifest's bytes with `version` set after its description (or name)."""
    with open(src_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if "version" in doc:
        raise BuildError(f"{src_path} carries a version, but VERSION is the one source — "
                         "remove the field")
    after = "description" if "description" in doc else "name"
    out = {}
    for key, value in doc.items():
        out[key] = value
        if key == after:
            out["version"] = version
    out.setdefault("version", version)
    return (json.dumps(out, indent=2, ensure_ascii=False) + "\n").encode()


def head_produced(host):
    """Top-level output entries HEAD's sources produce: a stale entry of the build's
    own (its source removed since the last commit) is one of these, not foreign."""
    try:
        out = git("ls-tree", "-r", "-z", "--name-only", "HEAD", "--", "core",
                  f"hosts/{host}/add").decode()
    except subprocess.CalledProcessError:
        return set()
    names = set()
    for p in filter(None, out.split("\0")):
        layer = "core/" if p.startswith("core/") else f"hosts/{host}/add/"
        name = p[len(layer):].split("/")[0]
        names.add(name[:-len(TEMPLATE_EXT)] if name.endswith(TEMPLATE_EXT) else name)
    try:
        names.update(mv["to"].split("/")[0] for mv in host_config(ROOT, host).get("moves") or [])
    except BuildError:
        pass
    return names


def write(files, src_root, out_dir, version=None, own=(), rewrites=None):
    rewrites = rewrites or {}
    if os.path.lexists(out_dir):
        # The output is deleted whole, so it may hold only what this build writes, or
        # wrote from HEAD's sources (`own`): any other entry at its top belongs to
        # something else.
        if os.path.islink(out_dir) or not os.path.isdir(out_dir):
            raise BuildError(f"{out_dir} is not a plain directory; refusing to replace it")
        tops = {rel.split("/")[0] for rel in files}
        loaded = {p.split("/")[0] for p in LOADER_BYPRODUCTS}
        foreign = sorted(n for n in os.listdir(out_dir)
                         if n not in tops and n not in own and n not in BYPRODUCTS
                         and n not in loaded)
        if foreign:
            raise BuildError(f"{out_dir} holds {', '.join(foreign)}, which this build does not "
                             "produce; refusing to delete it (move it, or remove it by hand "
                             "if it is a stale output)")
    # Everything is produced before the old output goes, so a refusal leaves it in place.
    produced, hits = {}, {}
    for rel, src in files.items():
        path = os.path.join(src_root, src)
        if version is not None and MANIFEST_RE.match(rel):
            data = stamped_manifest(path, version)
        else:
            with open(path, "rb") as fh:
                data = fh.read()
        if src.endswith(TEMPLATE_EXT):
            if version is None:
                raise BuildError(f"{src} is a template, but there is no {VERSION_FILE} to fill it")
            data = data.replace(b"{{VERSION}}", version.encode())
        if rel in rewrites:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise BuildError(f"{src} is not UTF-8 text, but a rewrite glob matches it") \
                    from None
            for rw in rewrites[rel]:
                text, n = rw["pattern"].subn(rw["replace"], text)
                hits[id(rw)] = hits.get(id(rw), 0) + n
            data = text.encode("utf-8")
        produced[rel] = data
    # A rewrite that changes nothing does not do what host.yaml says: its text moved, or
    # an override took every file it was for.
    dead = {rw["glob"] + " " + rw["pattern"].pattern
            for rws in rewrites.values() for rw in rws if not hits.get(id(rw))}
    if dead:
        raise BuildError("rewrite(s) that change no file: " + "; ".join(sorted(dead)))
    if os.path.lexists(out_dir):
        shutil.rmtree(out_dir)
    for rel, src in files.items():
        dst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(produced[rel])
        shutil.copymode(os.path.join(src_root, src), dst)


def marketplace_targets(doc, host):
    """The version-bearing places in a marketplace doc that VERSION owns:
    (container, label) pairs, each container holding a "version" key.

    A marketplace with no entry naming the output is refused: stamping nothing there
    would leave the one entry users install from unchecked.
    """
    out = []
    if isinstance(doc.get("metadata"), dict):
        out.append((doc["metadata"], "metadata"))
    want = os.path.relpath(os.path.join(TOP, outputs[host]), ROOT)
    for entry in doc.get("plugins") or []:
        if isinstance(entry, dict) and entry_source(entry) == want:
            out.append((entry, f"entry {entry.get('name', '?')!r}"))
    if not any(label.startswith("entry") for _, label in out):
        raise BuildError(f"{MARKETPLACES.get(host) or ENTRY_MARKETPLACES[host]} has no "
                         f"marketplace entry whose source is ./{want}")
    return out


def entry_source(entry):
    """A marketplace entry's local source path: a string, or {"source": "local", "path"}."""
    src = entry.get("source", "")
    if isinstance(src, dict):
        src = src.get("path", "") if src.get("source") == "local" else ""
    return str(src).removeprefix("./").rstrip("/")


def entry_problems(src_root, host):
    """For a host whose marketplace carries no versions: each way it fails to name the output."""
    if host not in ENTRY_MARKETPLACES:
        return []
    path = os.path.join(src_root, ENTRY_MARKETPLACES[host])
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    try:
        marketplace_targets(doc if isinstance(doc, dict) else {}, host)
    except BuildError as e:
        return [str(e)]
    return []


def marketplace_drift(src_root, host, version):
    """Each marketplace version VERSION owns that disagrees with it."""
    if host not in MARKETPLACES:
        return []
    path = os.path.join(src_root, MARKETPLACES[host])
    if version is None or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return [f"marketplace {label} says {c.get('version')!r}, VERSION says {version!r}"
            for c, label in marketplace_targets(doc, host) if c.get("version") != version]


def stamped_marketplace(host, version):
    """(path, new text) for the marketplace VERSION owns, or None when nothing changes.
    Computed before the output is touched, so a marketplace refusal leaves it in place."""
    if host not in MARKETPLACES:
        return None
    path = os.path.join(ROOT, MARKETPLACES[host])
    if version is None or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    targets = marketplace_targets(doc, host)
    if all(c.get("version") == version for c, _ in targets):
        return None
    for c, _ in targets:
        c["version"] = version
    return path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def tree(root, skip=(), skip_paths=()):
    """Every entry under root: files, symlinks, and directories with nothing in them,
    less any directory named in `skip` and any path in `skip_paths` (relative to root)."""
    found = {}
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in skip
                   and os.path.relpath(os.path.join(d, x), root) not in skip_paths]
        for n in dirs + names:
            full = os.path.join(d, n)
            rel = os.path.relpath(full, root)
            if rel in skip_paths:
                continue
            if os.path.islink(full):
                found[rel] = "symlink"
            elif os.path.isdir(full):
                if not os.listdir(full):
                    found[rel] = "empty dir"
            else:
                found[rel] = "file"
    return found


def owner_exec(path):
    # git records only the owner execute bit (100755 vs 100644).
    return bool(os.stat(path).st_mode & stat.S_IXUSR)


def diff(expected_dir, actual_dir, skip=(), skip_paths=()):
    """Human-readable differences between two trees: content, presence, exec bit."""
    want, have = tree(expected_dir), tree(actual_dir, skip, skip_paths)
    problems = [f"missing: {p}" for p in sorted(set(want) - set(have))]
    problems += [f"unexpected {have[p]}: {p}" for p in sorted(set(have) - set(want))]
    for p in sorted(set(want) & set(have)):
        if have[p] != want[p]:
            problems.append(f"{have[p]} where a {want[p]} belongs: {p}")
            continue
        a, b = os.path.join(expected_dir, p), os.path.join(actual_dir, p)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            if fa.read() != fb.read():
                problems.append(f"content differs: {p}")
                continue
        if owner_exec(a) != owner_exec(b):
            problems.append(f"mode differs: {p}")
    return problems


def uncommitted(host):
    paths = [top_rel("core"), top_rel(f"hosts/{host}"), outputs[host], top_rel(VERSION_FILE)]
    paths += [top_rel(MARKETPLACES[host])] if host in MARKETPLACES else []
    paths += [top_rel(ENTRY_MARKETPLACES[host])] if host in ENTRY_MARKETPLACES else []
    return git("status", "--porcelain", "--", *paths, cwd=TOP).decode().splitlines()


def extract_head(dest, *paths):
    """HEAD's tracked files under paths, with modes, into dest."""
    with tempfile.TemporaryFile() as fh:
        subprocess.run(["git", "-C", TOP, "archive", "--format=tar", "HEAD", "--", *paths],
                       check=True, stdout=fh)
        fh.seek(0)
        with tarfile.open(fileobj=fh) as tar:
            tar.extractall(dest, filter="tar")


def check(host, committed, lock_check=True):
    out_rel = outputs[host]
    with tempfile.TemporaryDirectory() as tmp:
        expected = os.path.join(tmp, "expected")
        if committed:
            head = os.path.join(tmp, "head")
            wanted = [top_rel("core"), top_rel(f"hosts/{host}"), out_rel, top_rel(VERSION_FILE)]
            wanted += [top_rel(MARKETPLACES[host])] if host in MARKETPLACES else []
            wanted += [top_rel(ENTRY_MARKETPLACES[host])] if host in ENTRY_MARKETPLACES else []
            existing = [p for p in wanted if git("ls-tree", "HEAD", "--", p, cwd=TOP)]
            extract_head(head, *existing)
            src_root = os.path.normpath(os.path.join(head, os.path.relpath(ROOT, TOP)))

            def files_under(rel):
                base = os.path.join(src_root, rel)
                found = sorted(os.path.relpath(os.path.join(d, n), src_root)
                               for d, _, names in os.walk(base) for n in names)
                links = [p for p in found if os.path.islink(os.path.join(src_root, p))]
                if links:
                    raise BuildError("symlinks are not supported in sources: "
                                     + ", ".join(links))
                return found
            files_under_root = files_under
            out_root = head
        else:
            src_root = ROOT
            files_under_root = source_files
            out_root = TOP
        version = read_version(src_root)
        files, rewrites, overrides = layout(host, files_under_root, src_root)
        locks = lock_problems(host, src_root, overrides) if lock_check else []
        write(files, src_root, expected, version, rewrites=rewrites)
        actual = os.path.join(out_root, out_rel)
        if not os.path.isdir(actual):
            where = "HEAD" if committed else "disk"
            print(f"build --check: {out_rel} does not exist on {where} — run the build",
                  file=sys.stderr)
            return 1
        if committed:
            # HEAD holds only what was committed, so nothing in it is a local byproduct.
            problems = diff(expected, actual)
        else:
            # Running the plugin from the output itself (a local marketplace installs in
            # place) leaves BYPRODUCTS and LOADER_BYPRODUCTS there. Untracked, they never
            # ship and are skipped; tracked, they ship, so each is a difference.
            problems = diff(expected, actual, BYPRODUCTS, LOADER_BYPRODUCTS)
            tracked = git("ls-files", "-z", "--", out_rel, cwd=TOP).decode().split("\0")
            for p in tracked:
                rel = os.path.relpath(p, out_rel) if p else ""
                if p and (any(b in p.split("/") for b in BYPRODUCTS)
                          or any(rel == b or rel.startswith(b + "/")
                                 for b in LOADER_BYPRODUCTS)):
                    problems.append(f"tracked byproduct: {rel}")
        problems += marketplace_drift(src_root, host, version) + locks \
            + entry_problems(src_root, host)
    what = "HEAD's " if committed else ""
    if problems:
        print(f"build --check: {what}{out_rel} is stale ({len(problems)} difference(s)):",
              file=sys.stderr)
        for p in problems[:50]:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"build --check: {what}{out_rel} matches its sources")
    if not committed:
        dirty = uncommitted(host)
        if dirty:
            print(f"build --check: note — {len(dirty)} uncommitted change(s) under the sources "
                  "or the output, so this covers the working tree, not HEAD "
                  "(`--committed` checks HEAD)", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="the core/ + hosts/ root to build (default: this repo)")
    ap.add_argument("--host", required=True)
    ap.add_argument("--check", action="store_true",
                    help="rebuild in a temp dir and fail if the output differs")
    ap.add_argument("--committed", action="store_true",
                    help="with --check: compare HEAD's output against HEAD's sources")
    ap.add_argument("--out", help="write the build to this directory instead of the host's "
                    "output (the marketplace is not stamped)")
    ap.add_argument("--no-lock-check", action="store_true",
                    help="skip the overrides.lock checks: development builds only, never in a "
                    "gate or CI")
    ap.add_argument("--relock", nargs="+", metavar="PATH",
                    help="lock these overrides (core-relative paths) to core as it is now, "
                    "and build nothing")
    args = ap.parse_args()
    if args.committed and not args.check:
        ap.error("--committed needs --check")
    if args.out and (args.check or args.relock):
        ap.error("--out writes a build; it does not combine with --check or --relock")
    if args.relock and (args.check or args.no_lock_check):
        ap.error("--relock only rewrites the lock")
    try:
        if args.root is not None:
            load_root(args.root)
        load_outputs()
        if args.host not in outputs:
            ap.error(f"argument --host: invalid choice: {args.host!r} "
                     f"(choose from {', '.join(sorted(outputs))})")
        if args.no_lock_check:
            print("build: lock check skipped (--no-lock-check): not for a gate or CI",
                  file=sys.stderr)
        if args.relock:
            n = relock(args.host, args.relock)
            print(f"build: relocked {n} override(s) in "
                  f"{os.path.relpath(lock_path(ROOT, args.host), TOP)}")
            return 0
        if args.check:
            return check(args.host, args.committed, lock_check=not args.no_lock_check)
        files, rewrites, overrides = layout(args.host, source_files, ROOT)
        problems = [] if args.no_lock_check else lock_problems(args.host, ROOT, overrides)
        if problems:
            print(f"build: {len(problems)} lock problem(s) for {args.host}:", file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            return 1
        version = read_version(ROOT)
        if args.out:
            out = guard_output("--out", os.path.abspath(args.out), top_relative=False)
            # --out is a scratch target: only an absent or empty directory, so the build
            # can never delete a directory it did not make.
            if os.path.lexists(out) and (not os.path.isdir(out) or os.path.islink(out)
                                         or os.listdir(out)):
                raise BuildError(f"--out {out} exists and is not an empty directory")
            write(files, ROOT, out, version, rewrites=rewrites)
            print(f"build: wrote {len(files)} files to {out}")
            return 0
        problems = entry_problems(ROOT, args.host)
        if problems:
            raise BuildError(problems[0])
        market = stamped_marketplace(args.host, version)
        write(files, ROOT, os.path.join(TOP, outputs[args.host]), version,
              own=head_produced(args.host), rewrites=rewrites)
        if market:
            with open(market[0], "w", encoding="utf-8") as fh:
                fh.write(market[1])
        print(f"build: wrote {len(files)} files to {outputs[args.host]}")
        return 0
    except BuildError as e:
        print(f"build: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
