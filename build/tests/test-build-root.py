#!/usr/bin/env python3
"""Tests for `build/build.py --root`, each against a throwaway repo.

The root sits below its repo's toplevel and the build runs from a third
directory, so the output only lands right when a relative `--root` is read
against the cwd and the build.json output against the root's git toplevel.
build.py runs from a copy outside any repo: if it ignored `--root` it would
build its own (absent) sources and fail, never this repo.
"""
import os
import shutil
import subprocess
import sys
import tempfile

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build.py")
FAILS = []
ROOT = "src/thing"
OUT = "out/thing"
FILES = {"core/a.txt": "a\n", "core/sub/run.sh": "#!/bin/sh\n",
         "hosts/claude/add/extra/c.md": "c\n"}


def sh(cwd, *cmd, ok=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if ok and r.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {r.stdout}{r.stderr}")
    return r


def commit(repo, msg):
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg,
       "--no-verify")


def fixture(tmp):
    """A repo with a root at ROOT, its sources committed, and a copy of build.py
    outside it. Returns (repo, build.py copy)."""
    repo = os.path.join(tmp, "repo")
    root = os.path.join(repo, ROOT)
    for rel, text in FILES.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    os.chmod(os.path.join(root, "core/sub/run.sh"), 0o755)
    with open(os.path.join(root, "build.json"), "w") as fh:
        fh.write('{"outputs": {"claude": "%s"}}\n' % OUT)
    sh(repo, "git", "init", "-q")
    commit(repo, "src")
    tool = os.path.join(tmp, "tool", "build")
    os.makedirs(tool)
    shutil.copy(BUILD, tool)
    shutil.copy(os.path.join(os.path.dirname(BUILD), "host_schema.py"), tool)
    return repo, os.path.join(tool, "build.py")


def build(repo, script, *args):
    # From <repo>/src, so `--root thing` is relative to the cwd, not to the toplevel.
    return sh(os.path.join(repo, "src"), sys.executable, script,
              "--root", os.path.basename(ROOT), "--host", "claude", *args, ok=False)


def expect(r, code, needle=""):
    assert r.returncode == code, f"exit {r.returncode}, want {code}: {r.stdout}{r.stderr}"
    assert needle in r.stdout + r.stderr, f"{needle!r} not in output: {r.stdout}{r.stderr}"


def listing(top):
    found = {}
    for d, _, names in os.walk(top):
        for n in names:
            full = os.path.join(d, n)
            with open(full, "rb") as fh:
                found[os.path.relpath(full, top)] = (fh.read(), bool(os.stat(full).st_mode & 0o100))
    return found


def output_is_core_plus_add(repo, script):
    expect(build(repo, script), 0, f"to {OUT}")
    want = {}
    root = os.path.join(repo, ROOT)
    for layer in ("core", "hosts/claude/add"):
        want.update(listing(os.path.join(root, layer)))
    have = listing(os.path.join(repo, OUT))
    assert have == want, f"output {sorted(have)} differs from core + add {sorted(want)}"
    expect(build(repo, script, "--check"), 0, "matches its sources")
    commit(repo, "out")
    expect(build(repo, script, "--check", "--committed"), 0, "matches its sources")
    with open(os.path.join(repo, OUT, "a.txt"), "w") as fh:
        fh.write("stale\n")
    expect(build(repo, script, "--check"), 1, "content differs: a.txt")


def ignored_source_refused(repo, script):
    with open(os.path.join(repo, ".gitignore"), "w") as fh:
        fh.write("hidden.txt\n")
    with open(os.path.join(repo, ROOT, "core", "hidden.txt"), "w") as fh:
        fh.write("h\n")
    expect(build(repo, script), 1, "hidden.txt")
    assert not os.path.exists(os.path.join(repo, OUT)), "an output was written anyway"


def retarget(repo, out):
    with open(os.path.join(repo, ROOT, "build.json"), "w") as fh:
        fh.write('{"outputs": {"claude": "%s"}}\n' % out)
    commit(repo, "retarget")


def refused_output(out):
    """A case: build.json naming `out` is refused, and nothing in the repo or beside
    it is deleted."""
    def run(repo, script):
        retarget(repo, out)
        before = listing(os.path.dirname(repo))
        expect(build(repo, script), 1, "output")
        after = listing(os.path.dirname(repo))
        assert before == after, f"files changed: {sorted(set(before) ^ set(after))}"
    return run


def output_in_git_dir_refused(repo, script):
    retarget(repo, ".git")
    expect(build(repo, script), 1, ".git")
    assert sh(repo, "git", "status", ok=False).returncode == 0, "the repo's .git was destroyed"


def output_through_symlink_refused(repo, script):
    # The output does not exist yet, so only the containment check can refuse it:
    # without it the build would create and fill a directory outside the repo.
    outside = os.path.join(os.path.dirname(repo), "outside")
    os.makedirs(outside)
    os.symlink(outside, os.path.join(repo, "lnk"))
    retarget(repo, "lnk/fresh")
    expect(build(repo, script), 1, "lnk/fresh")
    assert os.listdir(outside) == [], "the build wrote outside the repo"


def linked_dir(repo):
    """A tracked symlink lnk -> plugins/other, two levels down inside the repo."""
    os.makedirs(os.path.join(repo, "plugins", "other"))
    with open(os.path.join(repo, "plugins", "other", "o.md"), "w") as fh:
        fh.write("o\n")
    os.symlink(os.path.join("plugins", "other"), os.path.join(repo, "lnk"))
    commit(repo, "link")


def output_link_then_dotdot_into_sources_refused(repo, script):
    # Resolved, lnk/../<root>/core is plugins/<root>/core; written lexically it is the
    # root's own core/. The path checked must be the path written.
    linked_dir(repo)
    retarget(repo, "lnk/../" + ROOT + "/core")
    before = listing(os.path.dirname(repo))
    expect(build(repo, script), 1, "output")
    assert listing(os.path.dirname(repo)) == before, "files changed"


def output_link_then_dotdot_out_of_repo_refused(repo, script):
    linked_dir(repo)
    retarget(repo, "lnk/../../escaped")
    expect(build(repo, script), 1, "output")
    assert not os.path.exists(os.path.join(os.path.dirname(repo), "escaped")), \
        "the build wrote outside the repo"


def own_stale_entry_is_replaced(repo, script):
    # Removing a top-level source directory and rebuilding before committing is
    # ordinary work: the old output entry is the build's own (HEAD's sources
    # produce it), so it goes, and nothing else is in the way.
    expect(build(repo, script), 0, f"to {OUT}")
    shutil.rmtree(os.path.join(repo, ROOT, "core", "sub"))
    expect(build(repo, script), 0, f"to {OUT}")
    assert not os.path.exists(os.path.join(repo, OUT, "sub")), "the stale entry was kept"


def output_holding_foreign_files_refused(repo, script):
    expect(build(repo, script), 0, f"to {OUT}")
    expect(build(repo, script), 0, f"to {OUT}")  # a rebuild over its own output is fine
    sibling = os.path.join(repo, os.path.dirname(OUT), "sibling", "s.txt")
    os.makedirs(os.path.dirname(sibling))
    with open(sibling, "w") as fh:
        fh.write("s\n")
    commit(repo, "sibling")
    retarget(repo, os.path.dirname(OUT))
    expect(build(repo, script), 1, "sibling")
    assert os.path.isfile(sibling), "a file the build does not produce was deleted"


def output_through_an_inner_symlink_refused(repo, script):
    # lnk -> plugins/other resolves inside the toplevel and away from the sources, so
    # only the symlink clause can refuse it: the path checked must be the path written.
    linked_dir(repo)
    retarget(repo, "lnk/fresh")
    expect(build(repo, script), 1, "goes through a symlink")
    assert not os.path.exists(os.path.join(repo, "plugins", "other", "fresh")), \
        "the build wrote through the link"


def output_that_is_a_file_refused(repo, script):
    path = os.path.join(repo, OUT)
    os.makedirs(os.path.dirname(path))
    with open(path, "w") as fh:
        fh.write("not a directory\n")
    expect(build(repo, script), 1, "not a plain directory")
    with open(path) as fh:
        assert fh.read() == "not a directory\n", "the file was replaced"


def host_yaml_and_build_json_must_agree(repo, script):
    with open(os.path.join(repo, ROOT, "hosts/claude/host.yaml"), "w") as fh:
        fh.write("host: claude\nout: out/elsewhere\n")
    expect(build(repo, script), 1, "disagrees")
    assert not os.path.exists(os.path.join(repo, "out")), "an output was written anyway"


def overlapping_outputs_refused(repo, script):
    os.makedirs(os.path.join(repo, ROOT, "hosts/other"))
    with open(os.path.join(repo, ROOT, "hosts/other/host.yaml"), "w") as fh:
        fh.write("host: other\nout: %s/nested\n" % OUT)
    expect(build(repo, script), 1, "overlap")
    assert not os.path.exists(os.path.join(repo, "out")), "an output was written anyway"


def case(name, fn):
    tmp = tempfile.mkdtemp(prefix="build-root-test-")
    try:
        fn(*fixture(tmp))
        print(f"ok   {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL {name}: {e}")
    finally:
        shutil.rmtree(tmp)


case("output is core/ plus the add files, under the root's toplevel", output_is_core_plus_add)
case("an ignored source file is refused", ignored_source_refused)
# The build deletes its output before writing it, so every output that could hold
# something else is refused, and refusing deletes nothing.
case("an output outside the toplevel is refused", refused_output("../x"))
case("an output equal to the root is refused", refused_output(ROOT))
case("an output holding the root is refused", refused_output(os.path.dirname(ROOT)))
case("an output inside the root's sources is refused", refused_output(ROOT + "/core/out"))
case("an output inside .git is refused", output_in_git_dir_refused)
case("an output reached through a symlink out of the repo is refused",
     output_through_symlink_refused)
case("an output through a symlink and .. into the sources is refused",
     output_link_then_dotdot_into_sources_refused)
case("an output through a symlink and .. out of the repo is refused",
     output_link_then_dotdot_out_of_repo_refused)
case("an output holding files the build does not produce is refused",
     output_holding_foreign_files_refused)
case("a top-level output entry whose source was just removed is replaced",
     own_stale_entry_is_replaced)
case("an output through a symlink that stays inside the repo is refused",
     output_through_an_inner_symlink_refused)
case("an output path holding a file is refused", output_that_is_a_file_refused)
case("a host.yaml out that disagrees with build.json is refused",
     host_yaml_and_build_json_must_agree)
case("two hosts whose outputs nest are refused", overlapping_outputs_refused)

if FAILS:
    print(f"{len(FAILS)} failure(s)")
    sys.exit(1)
print("all build --root cases passed")
