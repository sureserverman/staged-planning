#!/usr/bin/env python3
"""Discovery contract for scripts/run-tests.sh.

The property is not "today's suites are in the runner" but "the runner's notion of
what a suite is can grow". A runner that happens to find today's suites proves
nothing about the next one, in a new home or a new language: a glob over two
directories and one extension leaves a bash suite in a third directory invisible
and silently skipped.

So these pin discovery itself, not a suite count:

  * every test-*.py / test-*.sh on disk appears in `run-tests.sh --list`, walked
    independently of the runner rather than by re-using its own glob;
  * a suite planted in a directory the runner has never seen is still discovered
    (the generality claim);
  * a planted .sh in a .py-only tree is discovered (the cross-language claim);
  * the comparison has teeth: a listing with one path withheld is reported as a
    discrepancy, so a passing run means agreement and not a vacuous match;
  * --list is side-effect free (it must not execute the suites it names);
  * an unknown argument is rejected rather than silently treated as a full run.

Every group that plants a file does so in a throwaway tree, never in the repo under
test — see throwaway_repo() for why cleanup blocks are not sufficient. Group 1 is the
only group that reads the real tree, and it writes nothing.

No pytest. Plain assertions, non-zero exit on failure.
Run: python3 scripts/tests/test-run-tests-discovery.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RUNNER = ROOT / "scripts" / "run-tests.sh"

fails: list[str] = []


def chk(cond, msg):
    if not cond:
        fails.append(msg)
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")


def listing(runner: Path = RUNNER, cwd: Path | None = None) -> set[str]:
    """Suite paths the runner reports, as a set of tree-relative strings.

    Deliberately NOT check=True: a nonzero --list (the runner refusing because of an
    unsupported suite, an unreadable subtree, or leftover state from an interrupted
    run) would raise CalledProcessError and abort the whole file with a traceback,
    which is precisely the unstructured failure this suite's own reporting discipline
    exists to avoid. Return the empty set and let the caller's chk() report it.

    `runner`/`cwd` are parameters so the planting groups can point this at a throwaway
    tree instead of the repo under test — see throwaway_repo().
    """
    out = subprocess.run(
        ["bash", str(runner), "--list"],
        capture_output=True, text=True, cwd=cwd or ROOT)
    if out.returncode != 0:
        chk(False, f"--list exited {out.returncode}: {(out.stderr or out.stdout).strip()[:160]}")
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def throwaway_repo(td: str) -> tuple[Path, Path]:
    """A fresh tree holding a copy of the runner, for any group that PLANTS files.

    No group that writes a file writes it into the repo under test. Two reasons.
    Invoking the full runner from inside a suite the runner discovers is unbounded
    recursion (this file -> run-tests.sh -> this file -> ...). And a hard kill
    mid-test leaves planted files behind in the real working tree: a `finally:` block
    cleans up after an assertion failure but never after a SIGKILL, so isolation has
    to come from the tree, not from cleanup.

    This does not weaken the planting claims. Discovery is location-independent by
    construction — run-tests.sh derives REPO from its own path (line 29) and matches by
    filename — so a claim proved in a copied tree holds in the real one. Group 1 is
    what pins discovery against the real repo's size and prune rules; the planting
    groups pin its generality, which is orthogonal.
    """
    tmp = Path(td)
    (tmp / "scripts").mkdir(parents=True)
    runner = tmp / "scripts" / "run-tests.sh"
    shutil.copy(RUNNER, runner)
    return tmp, runner


def walk_disk() -> set[str]:
    """Every suite file on disk, walked WITHOUT re-using the runner's glob.

    Deliberately an independent implementation: a test that asked the runner what
    it found and then checked the runner found it would pass no matter how narrow
    the runner's discovery became.
    """
    found = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules"}
                       # The generated copies (plugins/, packages/) are not suites
                       # to run; group 7 proves the runner skips them.
                       and not (Path(dirpath) == ROOT and d in {"plugins", "packages"})]
        for fn in filenames:
            if fn.startswith("test-") and (fn.endswith(".py") or fn.endswith(".sh")):
                found.add(str(Path(dirpath, fn).relative_to(ROOT)))
    return found


print("group 1 — every suite on disk is discovered")
disk = walk_disk()
listed = listing()
missing = sorted(disk - listed)
extra = sorted(listed - disk)
chk(not missing, f"no suite on disk is absent from --list (missing: {missing or 'none'})")
chk(not extra, f"--list names nothing that is not on disk (extra: {extra or 'none'})")
chk(len(disk) > 0, f"the walk found suites at all ({len(disk)} on disk)")

print("group 2 — discovery generalizes to homes and languages the runner has never seen")
# Directory names mirror plausible-but-absent homes rather than real ones: the claim is
# about a home the runner has never seen, and a throwaway tree satisfies that more
# honestly than a real plugin dir the runner already walks.
with tempfile.TemporaryDirectory() as td:
    tmp, tmp_runner = throwaway_repo(td)
    planted_sh = tmp / "tools" / "experimental" / "tests" / "test-planted-generality.sh"
    planted_py = tmp / "mobile-kit" / "tests" / "test-planted-crosslang.py"
    for p in (planted_sh, planted_py):
        p.parent.mkdir(parents=True, exist_ok=True)
    planted_sh.write_text("#!/usr/bin/env bash\nexit 0\n")
    planted_py.write_text("import sys\nsys.exit(0)\n")

    rel_sh = str(planted_sh.relative_to(tmp))
    rel_py = str(planted_py.relative_to(tmp))
    after = listing(tmp_runner, tmp)
    chk(rel_sh in after, f"a .sh suite in an unseen directory is discovered ({rel_sh})")
    chk(rel_py in after, f"a .py suite in a separate unseen tree is discovered ({rel_py})")

    print("group 3 — the comparison has teeth (against a real listing, not set algebra)")
    # Set algebra over one listing, such as `bool((after - (after - {x})) - set())`, is
    # an identity: true for any set containing x, so it restates group 2 rather than
    # testing anything. This deletes the planted file from DISK and re-reads the
    # runner's actual output.
    planted_sh.unlink()
    after_removal = listing(tmp_runner, tmp)
    chk(rel_sh not in after_removal,
        "a suite deleted from disk disappears from a FRESH --list invocation")
    chk(rel_py in after_removal,
        "and its sibling is still listed, so the drop was specific, not a wholesale failure")
    planted_sh.write_text("#!/usr/bin/env bash\nexit 0\n")
    chk(rel_sh in listing(tmp_runner, tmp),
        "restoring the file brings it back — discovery is live, not cached")

print("group 4 — a suite in an unrunnable language fails loudly, never silently")
# The class, generalized: a suite the runner cannot execute must not be
# skipped in silence. Planted under a tests/ dir because that is what scopes the
# check away from test-scope-tiers.md and test-fixtures/.
#
# What carries this group is the two MESSAGE assertions, not the return code. A copied
# runner cannot exit 0 outside the real repo anyway — EXTRA_VALIDATORS names a path that
# does not exist in a throwaway tree — so `returncode != 0` would hold even with the
# unsupported-extension branch deleted. The strings it prints would not.
#
# The runnable .py alongside the .rb keeps the tree shaped like the real case (one suite
# the runner can execute, one it cannot) rather than a tree with nothing runnable in it.
# It is not what makes the assertions bite: UNSUPPORTED is checked at run-tests.sh:109,
# ahead of the empty-sweep guard at :121, so the message appears either way.
with tempfile.TemporaryDirectory() as td:
    tmp, tmp_runner = throwaway_repo(td)
    (tmp / "scripts" / "tests").mkdir(parents=True)
    (tmp / "scripts" / "tests" / "test-planted-runnable.py").write_text("import sys\nsys.exit(0)\n")
    rb = tmp / "scripts" / "tests" / "test-planted-unrunnable.rb"
    rb.write_text("puts 'hi'\n")

    res = subprocess.run(["bash", str(tmp_runner)], capture_output=True, text=True, cwd=tmp)
    chk(res.returncode != 0, "an unrunnable-language suite makes the runner exit non-zero")
    chk("test-planted-unrunnable.rb" in (res.stderr + res.stdout),
        "the failure names the offending file")
    chk(".py, .sh" in (res.stderr + res.stdout),
        "the failure states which extensions ARE supported")
    res_list = subprocess.run(["bash", str(tmp_runner), "--list"],
                              capture_output=True, text=True, cwd=tmp)
    chk(res_list.returncode != 0, "--list refuses too rather than reporting a clean set")

print("group 5 — the check does not fire on non-suite paths named test-*")
for benign in ["core/skills/planning-projects/references/test-scope-tiers.md",
               "core/skills/applying-design-handoff/scripts/test-fixtures"]:
    chk((ROOT / benign).exists(), f"benign path still present and not swept: {benign}")
chk(subprocess.run(["bash", str(RUNNER), "--list"], capture_output=True,
                   cwd=ROOT).returncode == 0,
    "with only benign test-* paths present, --list succeeds")

print("group 6 — --list is side-effect free and arguments are validated")
# A sentinel nothing ever writes passes even if --list executes every suite, so this
# plants a suite that DOES write one when run.
# Throwaway tree per throwaway_repo(), which is where the isolation rationale lives.
with tempfile.TemporaryDirectory() as td:
    tmp, tmp_runner = throwaway_repo(td)
    (tmp / "scripts" / "tests").mkdir(parents=True)
    sentinel = tmp / "sentinel"
    spy = tmp / "scripts" / "tests" / "test-planted-spy.sh"
    spy.write_text(f"#!/usr/bin/env bash\ntouch '{sentinel}'\nexit 0\n")

    lst = subprocess.run(["bash", str(tmp_runner), "--list"],
                         capture_output=True, text=True, cwd=tmp)
    chk("scripts/tests/test-planted-spy.sh" in lst.stdout, "the spy suite is discovered")
    chk(not sentinel.exists(),
        "--list did NOT execute the spy suite (sentinel absent after a listing)")
    subprocess.run(["bash", str(tmp_runner)], capture_output=True, text=True, cwd=tmp)
    chk(sentinel.exists(),
        "a full run DOES execute it — proving the sentinel is a live signal, not a dead check")

bad = subprocess.run(["bash", str(RUNNER), "--bogus"],
                     capture_output=True, text=True, cwd=ROOT)
chk(bad.returncode != 0, "an unknown argument exits non-zero rather than running everything")
chk("--bogus" in (bad.stderr + bad.stdout), "the rejection message names the offending argument")

print()
print("group 7 — generated output is never discovered")
# plugins/<host>/planning is a rebuilt copy of core/ + hosts/<host>/: a suite there is
# the same suite twice, and a stale copy would keep a deleted suite "passing".
with tempfile.TemporaryDirectory() as td:
    tmp, tmp_runner = throwaway_repo(td)
    for rel in ("core/tests/test-real.py", "plugins/claude/planning/tests/test-copy.py",
                "packages/opencode/tests/test-copy.sh"):
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    got = listing(tmp_runner, tmp)
    chk("core/tests/test-real.py" in got, "a source suite is discovered")
    chk(not any(p.startswith(("plugins/", "packages/")) for p in got),
        f"no suite under plugins/ or packages/ is discovered ({sorted(got)})")

print("group 8 — a passing validator's NOT CHECKED disclosure reaches the output")
# A validator may pass while leaving part of its subject unchecked; it says so in a line
# containing NOT CHECKED. The runner swallows a passing validator's output, so without
# surfacing that line the summary would read as full coverage.
with tempfile.TemporaryDirectory() as td:
    tmp, tmp_runner = throwaway_repo(td)
    (tmp / "core" / "tests").mkdir(parents=True)
    (tmp / "core" / "tests" / "test-ok.sh").write_text("exit 0\n")
    (tmp / "scripts" / "check-partial.py").write_text(
        "print('3 sites swept')\nprint('  PART NOT CHECKED: the definition is absent')\n")
    res = subprocess.run(["bash", str(tmp_runner)], capture_output=True, text=True, cwd=tmp)
    chk("PART NOT CHECKED: the definition is absent" in res.stdout,
        "a passing validator's NOT CHECKED line is printed by the runner")
    chk("3 sites swept" not in res.stdout,
        "...and only that line: the rest of a passing validator's output stays quiet")

print("group 9 — every validate-*.py the plugin ships is run")
# The runner discovers scripts/check-*.py by name; a validator living in core/ is run
# only because EXTRA_VALIDATORS names it. Without this group, deleting that line leaves
# the suite green while the validator silently stops running.
runner_text = RUNNER.read_text()
shipped = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "core").rglob("validate-*.py")
                 if "fixtures" not in p.parts and "tests" not in p.parts)
# Validators of an ARGUMENT, not of the tree: each needs a file to check, so there is
# nothing for a bare run to validate. They are exercised by their own suites.
ARG_VALIDATORS = {
    "core/skills/applying-design-handoff/scripts/validate-handoff-pack.py": "a handoff pack path",
    "core/skills/planning-projects/scripts/validate-dispatch.py": "a plan file",
    "core/skills/planning-projects/scripts/validate-gate-checks.py": "a plan file",
}
unlisted = [p for p in shipped if f'"{p}"' not in runner_text and p not in ARG_VALIDATORS]
chk(set(ARG_VALIDATORS) <= set(shipped),
    f"every exempt argument-validator still exists ({sorted(set(ARG_VALIDATORS) - set(shipped)) or 'all present'})")
chk(shipped, f"the plugin ships validators at all ({shipped})")
chk(not unlisted, f"every shipped validate-*.py is in EXTRA_VALIDATORS (unlisted: {unlisted or 'none'})")

if fails:
    print(f"FAILED — {len(fails)} check(s):")
    for f in fails:
        print(f"  {f}")
    sys.exit(1)
print(f"OK — discovery contract holds across {len(disk)} suite(s).")
