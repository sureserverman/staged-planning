#!/usr/bin/env python3
"""Tests for build/build.py, each against a throwaway repo holding a copy of it.

Every case here is a way `--check` could report green while the package is
wrong, or a way the build could drop a file without saying so.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build.py")
FAILS = []


def sh(repo, *cmd, ok=True):
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    if ok and r.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {r.stdout}{r.stderr}")
    return r


def build(repo, *args):
    return sh(repo, sys.executable, "build/build.py", "--host", "claude", *args, ok=False)


def fixture():
    repo = tempfile.mkdtemp(prefix="build-test-")
    os.makedirs(os.path.join(repo, "build"))
    shutil.copy(BUILD, os.path.join(repo, "build", "build.py"))
    shutil.copy(os.path.join(os.path.dirname(BUILD), "host_schema.py"), os.path.join(repo, "build"))
    files = {"core/skills/a/SKILL.md": "a\n", "core/scripts/run.sh": "#!/bin/sh\n",
             "hosts/claude/add/.claude-plugin/plugin.json": "{}\n"}
    for rel, text in files.items():
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
    os.chmod(os.path.join(repo, "core/scripts/run.sh"), 0o755)
    with open(os.path.join(repo, ".gitignore"), "w") as fh:
        fh.write("AGENTS.md\n__pycache__/\n")
    sh(repo, "git", "init", "-q")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "src",
       "--no-verify")
    r = build(repo)
    assert r.returncode == 0, r.stderr
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "out",
       "--no-verify")
    return repo


def case(name, fn):
    repo = fixture()
    try:
        fn(repo)
        print(f"ok   {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL {name}: {e}")
    finally:
        shutil.rmtree(repo)


OUT = "plugins/claude/planning"


def expect(r, code, needle=""):
    assert r.returncode == code, f"exit {r.returncode}, want {code}: {r.stdout}{r.stderr}"
    assert needle in r.stdout + r.stderr, f"{needle!r} not in output: {r.stdout}{r.stderr}"


def clean_check(repo):
    expect(build(repo, "--check"), 0, "matches its sources")
    expect(build(repo, "--check", "--committed"), 0, "matches its sources")


def exec_bit_survives(repo):
    assert os.stat(os.path.join(repo, OUT, "scripts/run.sh")).st_mode & 0o100


def extra_output_file(repo):
    open(os.path.join(repo, OUT, "stray.txt"), "w").close()
    expect(build(repo, "--check"), 1, "unexpected file: stray.txt")


def symlinked_dir_in_output(repo):
    os.symlink("/etc", os.path.join(repo, OUT, "dlink"))
    expect(build(repo, "--check"), 1, "unexpected symlink: dlink")


def symlink_replacing_a_file(repo):
    target = os.path.join(repo, OUT, "skills/a/SKILL.md")
    shutil.copy(target, os.path.join(repo, "copy.md"))
    os.remove(target)
    os.symlink(os.path.join(repo, "copy.md"), target)
    expect(build(repo, "--check"), 1, "symlink where a file belongs")


def empty_dir_in_output(repo):
    os.makedirs(os.path.join(repo, OUT, "emptydir"))
    expect(build(repo, "--check"), 1, "unexpected empty dir: emptydir")


def exec_bit_dropped(repo):
    os.chmod(os.path.join(repo, OUT, "scripts/run.sh"), 0o644)
    expect(build(repo, "--check"), 1, "mode differs: scripts/run.sh")


def stale_content(repo):
    with open(os.path.join(repo, "core/skills/a/SKILL.md"), "w") as fh:
        fh.write("changed\n")
    expect(build(repo, "--check"), 1, "content differs: skills/a/SKILL.md")


def ignored_source_refused(repo):
    with open(os.path.join(repo, "hosts/claude/add/AGENTS.md"), "w") as fh:
        fh.write("x\n")
    expect(build(repo), 1, "hosts/claude/add/AGENTS.md")
    expect(build(repo, "--check"), 1, "would never ship")


def pycache_is_not_a_source(repo):
    os.makedirs(os.path.join(repo, "core/scripts/__pycache__"))
    open(os.path.join(repo, "core/scripts/__pycache__/x.pyc"), "w").close()
    expect(build(repo, "--check"), 0, "matches its sources")


def pycache_in_output_is_not_a_difference(repo):
    # Running the plugin from its own checkout (a local marketplace installs in place)
    # leaves bytecode caches in the output. They are ignored and never ship.
    os.makedirs(os.path.join(repo, OUT, "scripts/__pycache__"))
    open(os.path.join(repo, OUT, "scripts/__pycache__/x.pyc"), "w").close()
    expect(build(repo, "--check"), 0, "matches its sources")


def tracked_pycache_in_output_is_caught(repo):
    # A bytecode cache that was committed into the output ships, so neither check skips it.
    os.makedirs(os.path.join(repo, OUT, "scripts/__pycache__"))
    open(os.path.join(repo, OUT, "scripts/__pycache__/x.pyc"), "w").close()
    sh(repo, "git", "add", "-f", OUT + "/scripts/__pycache__/x.pyc")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pyc",
       "--no-verify")
    expect(build(repo, "--check", "--committed"), 1, "__pycache__")
    expect(build(repo, "--check"), 1, "__pycache__")


def _loaded_as_a_plugin(repo):
    # What Claude Code writes into a plugin directory it loads with `--plugin-dir`.
    with open(os.path.join(repo, OUT, "tsconfig.json"), "w") as fh:
        fh.write("{}\n")
    os.makedirs(os.path.join(repo, OUT, ".claude-plugin/types/claude-code"))
    with open(os.path.join(repo, OUT, ".claude-plugin/types/claude-code/index.d.ts"), "w") as fh:
        fh.write("x\n")


def loader_byproducts_in_output_are_not_a_difference(repo):
    _loaded_as_a_plugin(repo)
    expect(build(repo, "--check"), 0, "matches its sources")
    expect(build(repo), 0)
    expect(build(repo, "--check"), 0, "matches its sources")


def tracked_loader_byproduct_is_caught(repo):
    _loaded_as_a_plugin(repo)
    sh(repo, "git", "add", "-f", OUT + "/tsconfig.json")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ts",
       "--no-verify")
    expect(build(repo, "--check", "--committed"), 1, "tsconfig.json")
    expect(build(repo, "--check"), 1, "tracked byproduct: tsconfig.json")


def loader_byproduct_names_elsewhere_are_still_differences(repo):
    # Matched by path: the same names deeper in the output are not skipped.
    with open(os.path.join(repo, OUT, "skills/tsconfig.json"), "w") as fh:
        fh.write("{}\n")
    os.makedirs(os.path.join(repo, OUT, "skills/types"))
    with open(os.path.join(repo, OUT, "skills/types/x.d.ts"), "w") as fh:
        fh.write("x\n")
    expect(build(repo, "--check"), 1, "skills/tsconfig.json")
    expect(build(repo, "--check"), 1, "skills/types/x.d.ts")


def marketplace_without_the_entry_refused(repo):
    _versioned(repo)
    mp = _json(repo, ".claude-plugin/marketplace.json")
    mp["plugins"] = [e for e in mp["plugins"] if e["source"] != "./" + OUT]
    with open(os.path.join(repo, ".claude-plugin/marketplace.json"), "w") as fh:
        json.dump(mp, fh, indent=2)
    expect(build(repo), 1, "no marketplace entry")
    expect(build(repo, "--check"), 1, "no marketplace entry")


def marketplace_refusal_leaves_the_output(repo):
    _versioned(repo)
    expect(build(repo), 0)
    with open(os.path.join(repo, "core/skills/a/SKILL.md"), "w") as fh:
        fh.write("changed\n")
    mp = _json(repo, ".claude-plugin/marketplace.json")
    mp["plugins"] = [e for e in mp["plugins"] if e["source"] != "./" + OUT]
    with open(os.path.join(repo, ".claude-plugin/marketplace.json"), "w") as fh:
        json.dump(mp, fh, indent=2)
    expect(build(repo), 1, "no marketplace entry")
    with open(os.path.join(repo, OUT, "skills/a/SKILL.md")) as fh:
        assert fh.read() == "a\n", "the output was rewritten before the refusal"


def codex_marketplace_entry_must_name_the_output(repo):
    os.makedirs(os.path.join(repo, "hosts/codex"))
    with open(os.path.join(repo, "hosts/codex/host.yaml"), "w") as fh:
        fh.write("host: codex\nout: plugins/codex/planning\n")
    os.makedirs(os.path.join(repo, ".agents/plugins"))

    def entry(path):
        with open(os.path.join(repo, ".agents/plugins/marketplace.json"), "w") as fh:
            json.dump({"name": "m", "plugins": [{"name": "p", "source": {
                "source": "local", "path": path}, "policy": {}, "category": "c"}]}, fh)
    entry("./plugins/codex/elsewhere")
    r = sh(repo, sys.executable, "build/build.py", "--host", "codex", ok=False)
    expect(r, 1, "no marketplace entry whose source is ./plugins/codex/planning")
    assert not os.path.exists(os.path.join(repo, "plugins/codex")), "written anyway"
    entry("./plugins/codex/planning")
    expect(sh(repo, sys.executable, "build/build.py", "--host", "codex", ok=False), 0)
    entry("./plugins/codex/elsewhere")
    expect(sh(repo, sys.executable, "build/build.py", "--host", "codex", "--check", ok=False),
           1, "no marketplace entry")


def check_refuses_a_second_version_source(repo):
    _versioned(repo)
    expect(build(repo), 0)
    _versioned(repo, source_version=True)
    expect(build(repo, "--check"), 1, "VERSION is the one source")


def symlink_source_refused(repo):
    os.symlink("SKILL.md", os.path.join(repo, "core/skills/a/LINK.md"))
    expect(build(repo), 1, "symlinks are not supported")


def committed_symlink_source_refused(repo):
    # The working-tree build refuses a symlink in the sources; --committed reads HEAD,
    # where git can hold one, and must refuse it there too rather than copy its target.
    os.symlink("SKILL.md", os.path.join(repo, "core/skills/a/LINK.md"))
    sh(repo, "git", "add", "core")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "link",
       "--no-verify")
    expect(build(repo, "--check", "--committed"), 1, "symlinks are not supported")


def collision_refused(repo):
    os.makedirs(os.path.join(repo, "hosts/claude/add/skills/a"))
    with open(os.path.join(repo, "hosts/claude/add/skills/a/SKILL.md"), "w") as fh:
        fh.write("host\n")
    expect(build(repo), 1, "is an override, not an addition")


def prefix_collision_refused(repo):
    os.makedirs(os.path.join(repo, "hosts/claude/add/scripts/run.sh"))
    with open(os.path.join(repo, "hosts/claude/add/scripts/run.sh/x"), "w") as fh:
        fh.write("x\n")
    expect(build(repo), 1, "to be a directory")


def uncommitted_is_disclosed(repo):
    with open(os.path.join(repo, "core/skills/a/NEW.md"), "w") as fh:
        fh.write("new\n")
    expect(build(repo), 0)
    r = build(repo, "--check")
    expect(r, 0, "covers the working tree, not HEAD")


def committed_sees_stale_head(repo):
    # Source committed without its rebuilt output: the working tree is
    # consistent, HEAD is not.
    with open(os.path.join(repo, "core/skills/a/NEW.md"), "w") as fh:
        fh.write("new\n")
    sh(repo, "git", "add", "core")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "src only",
       "--no-verify")
    expect(build(repo), 0)
    expect(build(repo, "--check"), 0)
    expect(build(repo, "--check", "--committed"), 1, "missing: skills/a/NEW.md")


# A VERSION file is the one version source: the build stamps it into the built
# manifest and into the marketplace entry naming the output, and --check fails
# when either has fallen behind it.
def _versioned(repo, version="1.2.3", entry="0.0.1", source_version=False):
    with open(os.path.join(repo, "VERSION"), "w") as fh:
        fh.write(version + "\n")
    os.makedirs(os.path.join(repo, ".claude-plugin"), exist_ok=True)
    with open(os.path.join(repo, ".claude-plugin/marketplace.json"), "w") as fh:
        json.dump({"name": "m", "metadata": {"version": entry},
                   "plugins": [{"name": "p", "source": "./" + OUT, "version": entry},
                               {"name": "other", "source": "./elsewhere", "version": "9.9.9"}]},
                  fh, indent=2)
    manifest = {"name": "p", "description": "d"}
    if source_version:
        manifest["version"] = "1.0.0"
    with open(os.path.join(repo, "hosts/claude/add/.claude-plugin/plugin.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)


def _json(repo, rel):
    with open(os.path.join(repo, rel)) as fh:
        return json.load(fh)


def version_is_stamped(repo):
    _versioned(repo)
    expect(build(repo), 0)
    built = _json(repo, OUT + "/.claude-plugin/plugin.json")
    assert built.get("version") == "1.2.3", built
    assert list(built) == ["name", "description", "version"], list(built)
    mp = _json(repo, ".claude-plugin/marketplace.json")
    assert mp["metadata"]["version"] == "1.2.3", mp
    assert mp["plugins"][0]["version"] == "1.2.3", mp
    assert mp["plugins"][1]["version"] == "9.9.9", "an entry naming other output is left alone"
    expect(build(repo, "--check"), 0, "matches its sources")


def version_bump_without_rebuild(repo):
    _versioned(repo)
    expect(build(repo), 0)
    with open(os.path.join(repo, "VERSION"), "w") as fh:
        fh.write("1.2.4\n")
    r = build(repo, "--check")
    expect(r, 1, "content differs: .claude-plugin/plugin.json")
    expect(r, 1, "marketplace")


def marketplace_hand_edit_caught(repo):
    _versioned(repo)
    expect(build(repo), 0)
    mp = _json(repo, ".claude-plugin/marketplace.json")
    mp["plugins"][0]["version"] = "1.2.2"
    with open(os.path.join(repo, ".claude-plugin/marketplace.json"), "w") as fh:
        json.dump(mp, fh, indent=2)
    expect(build(repo, "--check"), 1, "marketplace")


def committed_sees_unbuilt_version(repo):
    _versioned(repo)
    expect(build(repo), 0)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v",
       "--no-verify")
    expect(build(repo, "--check", "--committed"), 0, "matches its sources")
    with open(os.path.join(repo, "VERSION"), "w") as fh:
        fh.write("1.2.4\n")
    sh(repo, "git", "add", "VERSION")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "bump",
       "--no-verify")
    expect(build(repo, "--check", "--committed"), 1, "plugin.json")


def second_version_source_refused(repo):
    _versioned(repo, source_version=True)
    expect(build(repo), 1, "VERSION is the one source")


def malformed_version_refused(repo):
    _versioned(repo, version="1.2")
    expect(build(repo), 1, "VERSION")


for name, fn in list(globals().items()):
    if callable(fn) and fn.__module__ == "__main__" and name not in (
            "sh", "build", "fixture", "case", "expect", "_versioned", "_json",
            "_loaded_as_a_plugin") and not name.startswith("overlay"):
        case(name, fn)


# The overlay steps, on two synthetic roots (build/tests/fixtures/root-a, root-b) held
# in one throwaway repo. `alpha` stands for any non-identity host: it excludes, rewrites,
# overrides and adds. `claude` is the identity host: its output is core/ + its add/.
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SCHEMA = os.path.join(os.path.dirname(BUILD), "host_schema.py")
ROOTS = ("a", "b")


def overlay_fixture():
    repo = tempfile.mkdtemp(prefix="build-overlay-test-")
    for r in ROOTS:
        shutil.copytree(os.path.join(FIXTURES, f"root-{r}"), os.path.join(repo, "src", f"root-{r}"))
    tool = os.path.join(repo, "tool")
    os.makedirs(tool)
    shutil.copy(BUILD, tool)
    shutil.copy(SCHEMA, tool)
    with open(os.path.join(repo, ".gitignore"), "w") as fh:
        fh.write("/tool/\n__pycache__/\n")
    sh(repo, "git", "init", "-q")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "src",
       "--no-verify")
    return repo


def overlay_build(repo, r, host, *args):
    return sh(repo, sys.executable, "tool/build.py", "--root", f"src/root-{r}", "--host", host,
              *args, ok=False)


def overlay_read(repo, rel):
    with open(os.path.join(repo, rel), encoding="utf-8") as fh:
        return fh.read()


def overlay_write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def overlay_lock(repo, r):
    import yaml
    with open(os.path.join(repo, f"src/root-{r}/hosts/alpha/overrides.lock")) as fh:
        return yaml.safe_load(fh)


def overlay_set_lock(repo, r, doc):
    import yaml
    with open(os.path.join(repo, f"src/root-{r}/hosts/alpha/overrides.lock"), "w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=True)


def overlay_rewrite_applies_only_inside_its_glob(repo, r):
    expect(overlay_build(repo, r, "alpha"), 0, f"out/root-{r}/alpha")
    skill = overlay_read(repo, f"out/root-{r}/alpha/skills/one/SKILL.md")
    assert "./scripts/go.sh" in skill and "${PLUGIN_HOME}" not in skill, skill
    assert "$planning:one" in skill and " /planning:" not in skill, skill
    # scripts/ is outside the glob, so its text is copied as written.
    assert "${PLUGIN_HOME}" in overlay_read(repo, f"out/root-{r}/alpha/scripts/go.sh")
    expect(overlay_build(repo, r, "alpha", "--check"), 0, "matches its sources")


def overlay_exclude_and_the_test_default(repo, r):
    expect(overlay_build(repo, r, "alpha"), 0)
    out = os.path.join(repo, f"out/root-{r}/alpha")
    assert not os.path.exists(os.path.join(out, "docs")), "an excluded glob shipped"
    assert not os.path.exists(os.path.join(out, "scripts/tests")), \
        "a non-identity host shipped tests"
    expect(overlay_build(repo, r, "claude"), 0)
    ident = os.path.join(repo, f"out/root-{r}/claude")
    assert os.path.isfile(os.path.join(ident, "docs/notes.md"))
    assert os.path.isfile(os.path.join(ident, "scripts/tests/check-go.sh"))


def overlay_identity_host_is_core_plus_add(repo, r):
    expect(overlay_build(repo, r, "claude"), 0)
    root, out = os.path.join(repo, f"src/root-{r}/core"), os.path.join(repo, f"out/root-{r}/claude")
    want = {os.path.relpath(os.path.join(d, n), root) for d, _, ns in os.walk(root) for n in ns}
    have = {os.path.relpath(os.path.join(d, n), out) for d, _, ns in os.walk(out) for n in ns}
    assert want == have, sorted(want ^ have)
    for rel in want:
        assert overlay_read(repo, f"src/root-{r}/core/{rel}") == \
            overlay_read(repo, f"out/root-{r}/claude/{rel}"), rel


def overlay_override_and_add_layers(repo, r):
    expect(overlay_build(repo, r, "alpha"), 0)
    out = f"out/root-{r}/alpha"
    assert overlay_read(repo, f"{out}/skills/one/guide.md") == \
        overlay_read(repo, f"src/root-{r}/hosts/alpha/overrides/skills/one/guide.md")
    assert overlay_read(repo, f"{out}/scripts/run.py") == f"print('alpha {r}')\n"
    assert os.path.isfile(os.path.join(repo, out, "extra/alpha-only.md"))
    stamped = json.loads(overlay_read(repo, f"{out}/.alpha-plugin/plugin.json"))
    assert stamped.get("version") == "1.0.0", stamped


def overlay_add_over_a_core_path_is_refused(repo, r):
    # add/ adds; a host version of a core file is an override, so it is locked.
    overlay_write(repo, f"src/root-{r}/hosts/alpha/add/scripts/go.sh", "#!/bin/sh\n")
    expect(overlay_build(repo, r, "alpha"), 1, "is an override, not an addition")


def overlay_stale_lock_names_the_override(repo, r):
    expect(overlay_build(repo, r, "alpha"), 0)
    overlay_write(repo, f"src/root-{r}/core/skills/one/guide.md", "Core moved on.\n")
    res = overlay_build(repo, r, "alpha", "--check")
    expect(res, 1, "stale override: skills/one/guide.md")
    expect(overlay_build(repo, r, "alpha"), 1, "stale override: skills/one/guide.md")
    # The identity host has no overrides, so a core edit is just a rebuild there.
    expect(overlay_build(repo, r, "claude"), 0)
    expect(overlay_build(repo, r, "alpha", "--no-lock-check"), 0, "lock check skipped")
    expect(overlay_build(repo, r, "alpha", "--relock", "skills/one/guide.md"), 0, "relocked 1")
    expect(overlay_build(repo, r, "alpha"), 0)
    expect(overlay_build(repo, r, "alpha", "--check"), 0, "matches its sources")
    lock = overlay_lock(repo, r)
    assert lock["scripts/run.py"].get("host_fact"), "relock dropped another entry's host_fact"


def overlay_dependency_change_makes_the_override_stale(repo, r):
    import hashlib
    dep = f"src/root-{r}/core/scripts/go.sh"
    lock = overlay_lock(repo, r)
    lock["scripts/run.py"]["depends_on"] = {
        "scripts/go.sh": hashlib.sha256(overlay_read(repo, dep).encode()).hexdigest()}
    overlay_set_lock(repo, r, lock)
    expect(overlay_build(repo, r, "alpha"), 0)
    overlay_write(repo, dep, overlay_read(repo, dep) + "# core moved on\n")
    expect(overlay_build(repo, r, "alpha", "--check"), 1,
           "stale override: scripts/run.py — core/scripts/go.sh, which it loads, changed")
    expect(overlay_build(repo, r, "alpha", "--relock", "scripts/run.py"), 0, "relocked 1")
    expect(overlay_build(repo, r, "alpha"), 0)
    expect(overlay_build(repo, r, "alpha", "--check"), 0, "matches its sources")
    assert overlay_lock(repo, r)["scripts/run.py"]["depends_on"] == {
        "scripts/go.sh": hashlib.sha256(overlay_read(repo, dep).encode()).hexdigest()}, \
        "relock did not refresh the dependency's digest"
    lock = overlay_lock(repo, r)
    lock["scripts/run.py"]["depends_on"] = {"scripts/gone.sh": "0" * 64}
    overlay_set_lock(repo, r, lock)
    expect(overlay_build(repo, r, "alpha"), 1, "depends on core/scripts/gone.sh, which is no core file")


def overlay_script_override_needs_a_host_fact(repo, r):
    lock = overlay_lock(repo, r)
    del lock["scripts/run.py"]["host_fact"]
    overlay_set_lock(repo, r, lock)
    expect(overlay_build(repo, r, "alpha"), 1, "scripts/run.py")
    expect(overlay_build(repo, r, "alpha"), 1, "host_fact")
    # A prose override needs none: guide.md has none in the fixture.
    lock["scripts/run.py"]["host_fact"] = "a fact"
    overlay_set_lock(repo, r, lock)
    expect(overlay_build(repo, r, "alpha"), 0)


def overlay_unlocked_and_orphan_entries(repo, r):
    lock = overlay_lock(repo, r)
    entry = lock.pop("skills/one/guide.md")
    overlay_set_lock(repo, r, lock)
    expect(overlay_build(repo, r, "alpha"), 1, "skills/one/guide.md has no lock entry")
    lock["skills/one/guide.md"] = entry
    lock["skills/gone.md"] = dict(entry)
    overlay_set_lock(repo, r, lock)
    expect(overlay_build(repo, r, "alpha"), 1, "skills/gone.md has no override")


def overlay_override_needs_a_core_file(repo, r):
    overlay_write(repo, f"src/root-{r}/hosts/alpha/overrides/skills/new.md", "x\n")
    expect(overlay_build(repo, r, "alpha", "--no-lock-check"), 1, "no core file")


def overlay_lock_belongs_to_its_root(repo, r):
    other = "b" if r == "a" else "a"
    expect(overlay_build(repo, other, "alpha"), 0)
    # The other root's lock names the same paths, but for that root's core files.
    shutil.copy(os.path.join(repo, f"src/root-{other}/hosts/alpha/overrides.lock"),
                os.path.join(repo, f"src/root-{r}/hosts/alpha/overrides.lock"))
    expect(overlay_build(repo, r, "alpha"), 1, "stale override: skills/one/guide.md")
    expect(overlay_build(repo, other, "alpha"), 0)
    os.remove(os.path.join(repo, f"src/root-{r}/hosts/alpha/overrides.lock"))
    expect(overlay_build(repo, r, "alpha"), 1, "has no lock entry")
    expect(overlay_build(repo, other, "alpha", "--check"), 0, "matches its sources")


def overlay_out_dir_leaves_the_output_alone(repo, r):
    tmp = tempfile.mkdtemp(prefix="build-overlay-out-")
    try:
        expect(overlay_build(repo, r, "alpha", "--out", tmp), 0, tmp)
        assert os.path.isfile(os.path.join(tmp, "extra/alpha-only.md"))
        assert not os.path.exists(os.path.join(repo, f"out/root-{r}/alpha")), \
            "--out also wrote the host's output"
    finally:
        shutil.rmtree(tmp)


def overlay_output_drift_is_caught(repo, r):
    expect(overlay_build(repo, r, "alpha"), 0)
    overlay_write(repo, f"out/root-{r}/alpha/skills/one/SKILL.md", "hand edit\n")
    expect(overlay_build(repo, r, "alpha", "--check"), 1, "content differs: skills/one/SKILL.md")


def overlay_rewrite_glob_matching_nothing_is_refused(repo, r):
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    overlay_write(repo, path, overlay_read(repo, path).replace("skills/**/*.md", "skils/**/*.md", 1))
    expect(overlay_build(repo, r, "alpha"), 1, "matches no file")


def overlay_schema_refusals(repo, r):
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    good = overlay_read(repo, path)
    for bad, needle in ((good + "colour: red\n", "colour"),
                        (good.replace("host: alpha", "host: beta"), "beta"),
                        (good.replace("status: native", "status: maybe"), "maybe"),
                        (good.replace("pattern: '\\$", "pattern: '(\\$", 1), "pattern")):
        overlay_write(repo, path, bad)
        expect(overlay_build(repo, r, "alpha"), 1, needle)
    overlay_write(repo, path, good)
    expect(overlay_build(repo, r, "alpha"), 0)


def overlay_record_keys_are_carried_not_read(repo, r):
    # A probe's measured facts and the owner's rulings live in host.yaml beside the build
    # keys; the build carries them without reading them, and still refuses anything else.
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    good = overlay_read(repo, path)
    records = ("probe_date: 2026-01-01\nprobe_script: scripts/probes/alpha-probe.sh\n"
               "probe_events: {plugin: [stop], user: []}\nprobe_double_fire: {}\n"
               "claude_hooks_run: false\nshadow: {served: a, listed: [a]}\n"
               "install_shape: {skills: a, agents_commands: b, plugin_local_path: true}\n"
               "co_visible_roots: [a]\n"
               "external_directory: {default: rejected, with_permission: allowed}\n"
               "rulings: {names: {choice: bare, date: 2026-01-01, evidence: alpha-probe}}\n")
    overlay_write(repo, path, good + records)
    expect(overlay_build(repo, r, "alpha"), 0)
    overlay_write(repo, path, good + records + "probe_colour: red\n")
    expect(overlay_build(repo, r, "alpha"), 1, "probe_colour")
    overlay_write(repo, path, good)
    expect(overlay_build(repo, r, "alpha"), 0)


def overlay_moves_rename_what_ships(repo, r):
    # A move renames a shipped directory after the overrides: the override, locked by its
    # core path, lands at the new path, and the core file's rewrites still apply there.
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    good = overlay_read(repo, path)
    out = f"out/root-{r}/alpha"
    overlay_write(repo, path, good + "moves:\n  - {from: skills/one, to: skills/uno}\n")
    expect(overlay_build(repo, r, "alpha"), 0)
    assert not os.path.exists(os.path.join(repo, out, "skills/one"))
    assert overlay_read(repo, f"{out}/skills/uno/guide.md") == \
        overlay_read(repo, f"src/root-{r}/hosts/alpha/overrides/skills/one/guide.md")
    skill = overlay_read(repo, f"{out}/skills/uno/SKILL.md")
    assert "${PLUGIN_HOME}" not in skill and "$planning:one" in skill, skill
    for moves, needle in (("  - {from: skills/none, to: skills/x}\n", "names nothing"),
                          ("  - {from: skills/one/SKILL.md, to: scripts/run.py}\n",
                           "already ships"),
                          ("  - {from: ../x, to: y}\n", "plain relative path")):
        overlay_write(repo, path, good + "moves:\n" + moves)
        expect(overlay_build(repo, r, "alpha"), 1, needle)
    # An add/ file at a move's destination would silently replace the moved file.
    overlay_write(repo, path, good + "moves:\n  - {from: skills/one, to: skills/uno}\n")
    overlay_write(repo, f"src/root-{r}/hosts/alpha/add/skills/uno/SKILL.md", "a host copy\n")
    expect(overlay_build(repo, r, "alpha"), 1, "already ships")
    os.remove(os.path.join(repo, f"src/root-{r}/hosts/alpha/add/skills/uno/SKILL.md"))
    overlay_write(repo, path, good)
    expect(overlay_build(repo, r, "alpha"), 0)


def overlay_template_is_filled_from_version(repo, r):
    # A host-only <name>.tmpl ships as <name>, with {{VERSION}} filled from VERSION.
    tmpl = f"src/root-{r}/hosts/alpha/add/pkg/package.json.tmpl"
    overlay_write(repo, tmpl, '{"name": "alpha", "version": "{{VERSION}}"}\n')
    expect(overlay_build(repo, r, "alpha"), 0)
    out = f"out/root-{r}/alpha/pkg"
    assert sorted(os.listdir(os.path.join(repo, out))) == ["package.json"]
    assert json.loads(overlay_read(repo, f"{out}/package.json"))["version"] == "1.0.0"


def overlay_committed_check_sees_a_stale_lock(repo, r):
    expect(overlay_build(repo, r, "alpha"), 0)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "out",
       "--no-verify")
    expect(overlay_build(repo, r, "alpha", "--check", "--committed"), 0, "matches its sources")
    overlay_write(repo, f"src/root-{r}/core/skills/one/guide.md", "Core moved on.\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "core",
       "--no-verify")
    expect(overlay_build(repo, r, "alpha", "--check", "--committed"), 1,
           "stale override: skills/one/guide.md")


def overlay_exclude_matching_nothing_is_refused(repo, r):
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    overlay_write(repo, path, overlay_read(repo, path).replace("  - docs/**", "  - dcos/**"))
    expect(overlay_build(repo, r, "alpha"), 1, "matches no core file")


def overlay_override_of_an_excluded_file_is_refused(repo, r):
    overlay_write(repo, f"src/root-{r}/hosts/alpha/overrides/docs/notes.md", "x\n")
    expect(overlay_build(repo, r, "alpha", "--no-lock-check"), 1, "does not ship")


def overlay_rewrite_on_a_binary_file_is_refused(repo, r):
    with open(os.path.join(repo, f"src/root-{r}/core/skills/one/blob.md"), "wb") as fh:
        fh.write(b"\xff\xfe\x00bin")
    expect(overlay_build(repo, r, "alpha"), 1, "not UTF-8 text")


def overlay_rewrite_that_changes_nothing_is_refused(repo, r):
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    overlay_write(repo, path, overlay_read(repo, path).replace("PLUGIN_HOME", "NOWHERE_HOME"))
    expect(overlay_build(repo, r, "alpha"), 1, "change no file")
    assert not os.path.exists(os.path.join(repo, f"out/root-{r}/alpha")), "written anyway"


def overlay_rewrite_of_only_overridden_files_is_refused(repo, r):
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    overlay_write(repo, path, overlay_read(repo, path) .replace(
        "rewrites:\n", "rewrites:\n  - glob: skills/one/guide.md\n    pattern: Guide\n"
        "    replace: Notes\n", 1))
    expect(overlay_build(repo, r, "alpha"), 1, "matches only files this host overrides")


def overlay_out_must_be_absent_or_empty(repo, r):
    tmp = tempfile.mkdtemp(prefix="build-overlay-out-")
    try:
        os.makedirs(os.path.join(tmp, "skills"))
        overlay_write(tmp, "skills/keep.md", "someone's file\n")
        expect(overlay_build(repo, r, "alpha", "--out", tmp), 1, "not an empty directory")
        assert os.path.isfile(os.path.join(tmp, "skills/keep.md")), "--out deleted a file"
    finally:
        shutil.rmtree(tmp)


def overlay_repeated_key_is_refused(repo, r):
    path = f"src/root-{r}/hosts/alpha/host.yaml"
    overlay_write(repo, path, overlay_read(repo, path) + "exclude: []\n")
    expect(overlay_build(repo, r, "alpha"), 1, "repeated key 'exclude'")


def overlay_non_identity_add_tests_do_not_ship(repo, r):
    overlay_write(repo, f"src/root-{r}/hosts/alpha/add/extra/tests/check-extra.sh", "x\n")
    overlay_write(repo, f"src/root-{r}/hosts/claude/add/extra/tests/check-extra.sh", "x\n")
    expect(overlay_build(repo, r, "alpha"), 0)
    assert not os.path.exists(os.path.join(repo, f"out/root-{r}/alpha/extra/tests")), \
        "a non-identity host shipped an add/ test"
    expect(overlay_build(repo, r, "claude"), 0)
    assert os.path.isfile(os.path.join(repo, f"out/root-{r}/claude/extra/tests/check-extra.sh"))


def overlay_glob_translation(repo, r):
    sys.path.insert(0, os.path.join(repo, "tool"))
    import host_schema
    g = host_schema.glob_re
    assert g("**/x.md").match("x.md") and g("**/x.md").match("a/b/x.md"), "**/ spans 0+ dirs"
    assert not g("*.md").match("a/x.md"), "* crossed a /"
    assert g("a/*/c").match("a/b/c") and not g("a/*/c").match("a/b/b/c")
    assert g("a/**").match("a/b/c") and not g("a/**").match("ab/c")
    assert g("x?.md").match("x1.md") and not g("x?.md").match("x/.md"), "? crossed a /"
    assert not g("x.md").match("x.mdz") and not g("a.b").match("axb"), "unanchored or unescaped"


def overlay_case(name, fn):
    for r in ROOTS:
        repo = overlay_fixture()
        try:
            fn(repo, r)
            print(f"ok   {name} [root-{r}]")
        except AssertionError as e:
            FAILS.append(f"{name} [root-{r}]")
            print(f"FAIL {name} [root-{r}]: {e}")
        finally:
            shutil.rmtree(repo)


for name, fn in list(globals().items()):
    if callable(fn) and fn.__module__ == "__main__" and name.startswith("overlay_") and name not in (
            "overlay_fixture", "overlay_build", "overlay_read", "overlay_write", "overlay_lock",
            "overlay_set_lock", "overlay_case"):
        overlay_case(name, fn)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
