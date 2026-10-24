#!/usr/bin/env python3
"""Fixture tests for scripts/host-matrix.py.

Each case builds a throwaway git repo holding a synthetic root below its toplevel
(src/thing, with hosts/features.yaml and two hosts), then runs the script from a third
directory with `--root`. The cases are the ones the matrix must get right or it lies:

  root      the feature ids come from the root's own hosts/features.yaml, never from
            this repo's, and the matrix is written to the root's git toplevel's
            docs/host-matrix.md; --out overrides that
  complete  --check --hosts fails for a listed host that lacks an id, has no host.yaml,
            or reports an id features.yaml does not define
  loss      an `absent` entry with no note fails (the loss must be named)
  stale     a hand edit to the written matrix, or no matrix at all, fails --check, and
            --check writes nothing
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "host-matrix.py")
FAILS = []
ROOT = "src/thing"
FEATURES = """features:
  - id: alpha-feature
    what: the first thing a host may do
  - id: beta-feature
    what: the second thing
"""
CLAUDE = """host: claude
out: out/claude
features:
  - id: alpha-feature
    status: native
  - id: beta-feature
    status: absent
    note: nothing carries the second thing here
"""
OTHER = """host: other
out: out/other
features:
  - id: alpha-feature
    status: inline
"""


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def fixture(tmp):
    repo = os.path.join(tmp, "repo")
    root = os.path.join(repo, ROOT)
    put(os.path.join(root, "hosts/features.yaml"), FEATURES)
    put(os.path.join(root, "hosts/claude/host.yaml"), CLAUDE)
    put(os.path.join(root, "hosts/other/host.yaml"), OTHER)
    subprocess.run(["git", "init", "-q", "--template=", repo], check=True)
    return repo


def run(repo, *args):
    cwd = os.path.join(os.path.dirname(repo), "elsewhere")
    os.makedirs(cwd, exist_ok=True)
    return subprocess.run([sys.executable, SCRIPT, "--root", os.path.join(repo, ROOT), *args],
                          cwd=cwd, capture_output=True, text=True)


def expect(r, code, needle=""):
    assert r.returncode == code, f"exit {r.returncode}, want {code}: {r.stdout}{r.stderr}"
    assert needle in r.stdout + r.stderr, f"{needle!r} not in output: {r.stdout}{r.stderr}"


def matrix(repo):
    with open(os.path.join(repo, "docs/host-matrix.md"), encoding="utf-8") as fh:
        return fh.read()


def written_to_the_roots_toplevel(repo):
    expect(run(repo, "--write"), 0, "docs/host-matrix.md")
    text = matrix(repo)
    assert "alpha-feature" in text and "beta-feature" in text, text
    assert "nothing carries the second thing here" in text, text
    # The ids are the root's own: none of this repo's feature ids appears.
    assert "handoff-envelope" not in text and "skills" not in text, text
    assert not os.path.exists(os.path.join(repo, ROOT, "docs")), "written under the root"
    expect(run(repo, "--check", "--hosts", "claude"), 0)


def out_overrides_the_destination(repo):
    dest = os.path.join(os.path.dirname(repo), "m.md")
    expect(run(repo, "--write", "--out", dest), 0)
    assert os.path.isfile(dest) and not os.path.exists(os.path.join(repo, "docs"))
    expect(run(repo, "--check", "--hosts", "claude", "--out", dest), 0)


def a_listed_host_missing_an_id_fails(repo):
    expect(run(repo, "--write"), 0)
    expect(run(repo, "--check", "--hosts", "claude,other"), 1, "other lacks beta-feature")


def a_listed_host_with_no_host_yaml_fails(repo):
    expect(run(repo, "--write"), 0)
    expect(run(repo, "--check", "--hosts", "claude,nowhere"), 1, "nowhere")


def an_unknown_id_fails(repo):
    put(os.path.join(repo, ROOT, "hosts/claude/host.yaml"),
        CLAUDE + "  - id: gamma-feature\n    status: native\n")
    expect(run(repo, "--write"), 0)
    expect(run(repo, "--check", "--hosts", "claude"), 1, "gamma-feature")


def absent_without_a_note_fails(repo):
    put(os.path.join(repo, ROOT, "hosts/claude/host.yaml"),
        CLAUDE.replace("    note: nothing carries the second thing here\n", ""))
    expect(run(repo, "--write"), 0)
    expect(run(repo, "--check", "--hosts", "claude"), 1, "absent with no note")


def a_hand_edit_is_stale(repo):
    expect(run(repo, "--write"), 0)
    with open(os.path.join(repo, "docs/host-matrix.md"), "a") as fh:
        fh.write("edited\n")
    expect(run(repo, "--check", "--hosts", "claude"), 1, "stale")


def no_matrix_fails_and_check_writes_nothing(repo):
    expect(run(repo, "--check", "--hosts", "claude"), 1, "host-matrix.md")
    assert not os.path.exists(os.path.join(repo, "docs")), "--check wrote a file"


def a_change_to_a_host_yaml_makes_it_stale(repo):
    expect(run(repo, "--write"), 0)
    put(os.path.join(repo, ROOT, "hosts/other/host.yaml"),
        OTHER.replace("status: inline", "status: equivalent"))
    expect(run(repo, "--check", "--hosts", "claude"), 1, "stale")


def an_empty_host_list_is_refused(repo):
    expect(run(repo, "--write"), 0)
    expect(run(repo, "--check", "--hosts", ","), 2, "names no host")


def a_root_with_no_hosts_dir_is_refused(repo):
    shutil.rmtree(os.path.join(repo, ROOT, "hosts"))
    os.makedirs(os.path.join(repo, ROOT, "core"))
    r = run(repo, "--write")
    expect(r, 2, "hosts")
    assert "Traceback" not in r.stderr, r.stderr


def a_pipe_in_the_text_stays_in_its_cell(repo):
    put(os.path.join(repo, ROOT, "hosts/features.yaml"),
        FEATURES.replace("the second thing", "the second | thing"))
    expect(run(repo, "--write"), 0)
    row = next(l for l in matrix(repo).splitlines() if l.startswith("| `beta-feature`"))
    assert len(re.findall(r"(?<!\\)\|", row)) == 5, row


def a_multi_line_note_is_refused(repo):
    put(os.path.join(repo, ROOT, "hosts/claude/host.yaml"),
        CLAUDE.replace("note: nothing carries the second thing here",
                       'note: "two\\nlines"'))
    expect(run(repo, "--write"), 2, "one line")


def a_repeated_key_is_refused(repo):
    put(os.path.join(repo, ROOT, "hosts/features.yaml"), FEATURES + "features: []\n")
    expect(run(repo, "--write"), 2, "repeated key")


for name, fn in list(globals().items()):
    if callable(fn) and fn.__module__ == "__main__" and name not in (
            "put", "fixture", "run", "expect", "matrix"):
        tmp = tempfile.mkdtemp(prefix="host-matrix-test-")
        try:
            fn(fixture(tmp))
            print(f"ok   {name}")
        except AssertionError as e:
            FAILS.append(name)
            print(f"FAIL {name}: {e}")
        finally:
            shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
