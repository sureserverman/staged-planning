#!/usr/bin/env python3
"""prove-claim.py — a claim about a task's test is proven by a run, not by a sentence.

    prove-claim.py claim     --repo R --plan P --task N.M --claim K --break PATCH
                             --test CMD (--build CMD | --no-build-step WHY) [--timeout S]
    prove-claim.py req       --repo R --plan P --task N.M --req K
                             (--check CMD --break PATCH (--build CMD | --no-build-step WHY)
                              | --covered-by-claim J) [--timeout S]
    prove-claim.py deviation --repo R --plan P --task N.M (--req K | --claim K) --why TEXT
    prove-claim.py replay    --repo R --plan P [--task N.M] [--timeout S]
    prove-claim.py fingerprint --repo R

WHY THIS EXISTS. An agent executing tasks can ship one defect over and over: a
check that passes while measuring nothing (a /tmp check that cannot see TMPDIR,
an input fixture with nothing in it for the code to change, an Error
test that passes with the cleanup deleted), or a claim of proof that is not one
(a substituted easier break, a `mutation:` line that is false). The agent that
writes the code also writes the test and the sentence saying the test works. A sentence cannot be audited; a run can. So a claim is
proven only by this tool having watched it:

  1. the worktree equals the index outside proof/, nothing untracked (host and
     plugin state in the top-level .claude/ aside), no index
     flags hiding a change — the record binds to exactly what will be committed
  2. --test is a command written in the task's `Test:` field, never free text
     (a "test" of `git diff --quiet` goes red for any change at all)
  3. the build (when given) and the test PASS as the code stands
  4. the break — a content edit of existing, tracked, regular, non-test files
     only, read once into a private copy — is applied; a journal under .git
     records what it touched, so a killed run is undone by the next one
  5. the code still builds with the break (a break that stops compilation turns
     every test red); the test FAILS, and not because it could not run
  6. every touched file is restored and verified byte-identical, with an mtime
     newer than anything built under the break; the build runs again; the whole
     tree must then be exactly as before — otherwise exit 3
  7. a record is written to proof/<plan-stem>/<task>/claim-<K>.json

`req` records that a requirement clause was checked — by a command that passes,
and FAILS under a break of that requirement, through the same run as a claim
(a check that cannot fail, like `echo ok`, is refused) — or is covered by a
proven claim. `deviation --req` records one that could not be checked.
`deviation --claim` records a CLAIM no repo patch can break — its evidence lives
outside the repo (a file in the records home, a device) — at claim-K.json as kind
`claim-deviation`: disclosed, so the audit reports it, but never proof.
`replay` re-runs every claim record's break against the tree as it stands; a
claim deviation has no break and is listed as skipped.

WHAT THIS DOES NOT DO. Whether a break, or a req check, is the one that matters
is judgment — a reviewer's, reading the record. The plan's "red if …"
is recorded as `named_break` so a reader can compare. A record written by hand
is still possible; replay, the fingerprint binding and validate() make it a
deliberate lie rather than an oversight. One run each: a flaky test can pass.

EXIT CODES: 0 proven / recorded / replay clean · 1 not proven or refused (no
record written) · 2 usage or IO error, or another run holds the lock · 3 the tree
is not as it was, or an interrupted run was just recovered (or its journal no
longer matches the repo) — check the tree by hand before anything else · 4 the test
ran over --timeout before the break: the task-test budget is spent (no record; stop,
never narrow the test — task-execution.md § A task test has a time budget).

Each record's `baseline` and `red` runs carry `elapsed_s`, the test's wall-clock time.
"""
import argparse
import base64
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Schema 2: a req record's check is proven by a break, like a claim.
# Schema-1 req records with a bare passing check are LEGACY: validate() accepts
# them only when asked to (the audit, which reports them advisory), never at commit.
SCHEMA = 2
PROOF_DIR = "proof"
TAIL_LINES = 40
# Paths a break may not touch. A break is a change to what the claim is ABOUT;
# editing the test so it fails proves only that a test can be made to fail.
TEST_PATH = re.compile(
    r"(^|/)(tests?|Tests|androidTest|testFixtures|__tests__|spec|testdata|fixtures)/"
    r"|(^|/)[A-Za-z]*Test/"
    r"|(^|/)(test_[^/]*|test-[^/]*|conftest)\.(py|sh)$|_test\.(go|py)$"
    r"|(Tests?|Spec|IT)\.(kt|java|swift|scala)$|\.(spec|test)\.[jt]sx?$")
# A task's proof records, a stage's two gate reports (stage-brief.py): the premise
# worksheet of Step 3.0 and the demo evaluator's report, and evaluation-ledger.py's
# committed files: an experiment's ledger and the original receipts it binds. The
# ledger keeps no lock file, and a temp it leaves (a leading dot) never matches.
_LEDGER_ID = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
RECORD_PATH = re.compile(rf"^{PROOF_DIR}/[^/]+/(\d+\.\d+/(claim|req|deviation)-[1-9]\d*\.json"
                         r"|stage-[1-9]\d*/(demo|premise)\.md"
                         rf"|evaluation/{_LEDGER_ID}\.jsonl|originals/{_LEDGER_ID}\.json)$")
NAMED_BREAK = re.compile(r"\(red if (.+?)\)\s*$", re.S)
TRIVIAL_BUILD = {"", "true", ":", "exit 0", "/bin/true", "/usr/bin/true"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# The staleness probe lives in the plugin's lib/, not beside this file: loaded by
# explicit path, as in check-master-register.py, so a stale plugin-cache copy says so
# before it audits or proves anything under yesterday's rules.
_STALE = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass


class Refused(Exception):
    """Not proven: exit 1, no record."""


class Usage(Exception):
    """Usage or IO error: exit 2."""


class RestoreFailed(Exception):
    """The tree is not as it was: exit 3."""


class OverBudget(Exception):
    """The test ran over --timeout before the break: exit 4, no record. On a plan with a
    task-test budget this is a Stop condition, never a reason to narrow the test: a test
    narrowed to fit its budget passes while the behaviour it dropped stays unchecked."""


def _audit_module():
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("plan_flip_audit", here / "plan-flip-audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PFA = _audit_module()


# ------------------------------------------------------------------- git

def git(repo, *args, check=True, cfg=()):
    pre = [x for kv in cfg for x in ("-c", kv)]
    r = subprocess.run(["git", "-C", str(repo), *pre, *args], capture_output=True, text=True,
                       errors="surrogateescape", env={**os.environ, "LC_ALL": "C", "LANG": "C"})
    if check and r.returncode != 0:
        raise Usage(f"git {' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    return r


def git_dir(repo):
    return Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip())


def _fingerprint_lines(entries):
    """sha256 over `mode sha path` entries, proof/ excluded, order-independent."""
    keep = sorted(e for e in entries if not e[2].startswith(PROOF_DIR + "/"))
    h = hashlib.sha256()
    for mode, sha, path in keep:
        h.update(f"{mode} {sha} {path}\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def index_entries(repo):
    out, entries = git(repo, "ls-files", "-s", "-z").stdout, []
    for rec in out.split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            mode, sha, _stage = meta.split()
            entries.append((mode, sha, path))
    return entries


def index_fingerprint(repo):
    """Fingerprint of the index (what `git commit` would record), proof/ excluded."""
    return _fingerprint_lines(index_entries(repo))


def commit_fingerprint(repo, rev):
    """Fingerprint of a commit's tree in the same form as index_fingerprint."""
    out, entries = git(repo, "ls-tree", "-r", "-z", rev).stdout, []
    for rec in out.split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            mode, _type, sha = meta.split()
            entries.append((mode, sha, path))
    return _fingerprint_lines(entries)


def require_clean(repo):
    """Worktree == index outside proof/; nothing hides a difference; proof/ holds records only.

    `git diff` is told to see everything: file modes, submodule dirt, no external
    diff or textconv. Index flags that make git LOOK AWAY from a file
    (assume-unchanged, skip-worktree) are refused outright, because the proof
    would run on worktree code the fingerprint never binds.
    """
    ex = f":(exclude){PROOF_DIR}"
    see_all = ("core.fileMode=true", "diff.ignoreSubmodules=none")
    diff = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "--",
               ".", ex, cfg=see_all).stdout.split("\0")
    diff = [d for d in diff if d]
    if diff:
        raise Refused("the worktree differs from the index outside proof/ — stage the change "
                      f"being proven first (`git add`): {', '.join(diff[:5])}")
    flags = [ln for ln in git(repo, "ls-files", "-v", "-z").stdout.split("\0")
             if ln and not ln.startswith("H ")]
    if flags:
        raise Refused("index entries flagged so git ignores their changes (assume-unchanged / "
                      f"skip-worktree / unmerged) — clear them first: {', '.join(flags[:5])}")
    # The top-level .claude/ holds what the host and its plugins write on their own
    # (progress cache, state files, other plugins' sidecars), never the change being
    # proven; counted, it blocks every proof in a repo that does not ignore .claude/.
    untracked = [u for u in git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--",
                                ".", ex, ":(top,exclude).claude/").stdout.split("\0") if u]
    if untracked:
        raise Refused("untracked files outside proof/ would not be in the commit this proof "
                      f"is bound to — add or ignore them: {', '.join(untracked[:5])}")
    if any("\n" in e[2] for e in index_entries(repo)):
        raise Refused("a tracked path contains a newline; the fingerprint cannot bind it")
    stray = [p for p in git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                            "--", PROOF_DIR).stdout.split("\0")
             if p and not RECORD_PATH.match(p)]
    if stray:
        raise Refused(f"{PROOF_DIR}/ may hold proof records only — it is excluded from every "
                      f"other check, so nothing else may live there: {', '.join(stray[:5])}")


# ------------------------------------------------------------------- plan

def task_block(plan_text, task):
    for t in PFA.task_blocks(plan_text):
        if t["id"] == task:
            return t
    raise Usage(f"no `### Task {task}` in the plan")


def plan_stem(plan):
    return Path(plan).stem


def record_path(repo, plan, task, kind, index):
    return Path(repo) / PROOF_DIR / plan_stem(plan) / task / f"{kind}-{index}.json"


def read_plan(plan):
    try:
        return Path(plan).read_text(errors="replace")
    except OSError as e:
        raise Usage(f"cannot read plan {plan}: {e}")


def pick(items, index, what):
    if index < 1 or index > len(items):
        raise Usage(f"{what} {index} does not exist — the task has {len(items)}: "
                    + "; ".join(f"{i}. {c[:60]}" for i, c in enumerate(items, 1)))
    return items[index - 1]


def test_commands(test_field):
    """The commands a task's `Test:` field writes: its code spans before ` — `."""
    masked = PFA._masked(test_field)
    head = test_field[:masked.index(" — ")] if " — " in masked else test_field
    return [m.group(0).strip("`").strip() for m in PFA.QUOTED_SPAN.finditer(head)
            if m.group(0).startswith("`")]


def require_planned_test(test, test_field, task):
    planned = test_commands(test_field)
    if test.strip() not in planned:
        raise Refused(f"--test must be a command written in Task {task}'s `Test:` field — a "
                      "free-form test can go red for reasons unrelated to the claim. "
                      f"The field has: {planned or 'no command in backticks'}")


# ------------------------------------------------------------------- runs

def run(cmd, repo, timeout):
    """(exit code, output tail); exit None on timeout. The whole process group dies.

    No .pyc from any run this tool makes: a break and its restore can land in the
    same second with the same size, and Python then trusts the BROKEN bytecode.
    A timeout or an interrupt kills the process
    GROUP — a test's grandchildren must not keep writing to the tree after restore.
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.Popen(cmd, shell=True, cwd=repo, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", env=env,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(p)
        return None, f"timed out after {timeout}s"
    except BaseException:
        _kill_group(p)
        raise
    return p.returncode, "\n".join((out or "").splitlines()[-TAIL_LINES:])


def _kill_group(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        p.communicate(timeout=10)
    except Exception:  # noqa: BLE001
        pass


INTERPRETERS = {"python", "python3", "bash", "sh", "zsh", "dash", "node", "ruby", "perl",
                "deno", "bun", "pwsh", "tclsh", "lua", "Rscript"}


def command_programs(cmd):
    """The programs a command runs — each segment's first word, or the script an
    interpreter is given — so a break of the test runner itself can be refused.
    A source file the command merely names (`grep x calc.py`) is not one."""
    out = set()
    for seg in re.split(r"&&|\|\||[;|\n]", cmd):
        try:
            words = shlex.split(seg)
        except ValueError:
            words = seg.split()
        words = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
        if not words:
            continue
        prog = words[0]
        if Path(prog).name in INTERPRETERS:
            rest = [w for w in words[1:] if not w.startswith("-")]
            if "-m" in words[1:] or "-c" in words[1:] or not rest:
                continue
            prog = rest[0]
        out.add(os.path.normpath(prog))
    return out


def check_patch(repo, patch, test=None):
    """Paths a break edits, after refusing everything but a content edit of existing,
    tracked, regular, non-test files. Anything else — a rename, a new or deleted
    file, a mode change, a binary hunk, a symlink, a path in a submodule or .git —
    is a shape the restore cannot undo exactly, or not a change to what a claim is
    about."""
    summary = git(repo, "apply", "--summary", str(patch), check=False)
    if summary.returncode != 0:
        raise Refused(f"the break does not apply to the tree: {summary.stderr.strip()[:300]}")
    for line in summary.stdout.splitlines():
        line = line.strip()
        if line.startswith(("rename", "copy", "create", "delete", "mode change")):
            raise Refused(f"the break may only edit the content of existing files, not: {line}")
    num = git(repo, "apply", "--numstat", "-z", str(patch), check=False)
    if num.returncode != 0:
        raise Refused(f"the break does not apply to the tree: {num.stderr.strip()[:300]}")
    paths, recs = [], [r for r in num.stdout.split("\0") if r]
    for rec in recs:
        parts = rec.split("\t")
        if len(parts) != 3 or not parts[2]:
            raise Refused(f"the break has an entry this tool cannot read: {rec!r}")
        added, deleted, path = parts
        if added == "-" or deleted == "-":
            raise Refused(f"the break edits a binary file ({path})")
        paths.append(path)
    if not paths:
        raise Refused("the break changes no file")
    modes = {path: mode for mode, _sha, path in index_entries(repo)}
    gitlinks = [p for p, m in modes.items() if m == "160000"]
    runs = command_programs(test) if test else set()
    for p in paths:
        if TEST_PATH.search(p):
            raise Refused(f"the break touches a test file ({p}) — break the code the claim "
                          "is about, not the test that checks it")
        if os.path.normpath(p) in runs:
            raise Refused(f"the break edits {p}, which the test command runs — breaking the "
                          "test runner proves only that a runner can be made to fail")
        if p.startswith((PROOF_DIR + "/", ".git/")) or p == ".git":
            raise Refused(f"the break touches {p}")
        if any(p == g or p.startswith(g + "/") for g in gitlinks):
            raise Refused(f"the break edits a path inside a submodule ({p})")
        if modes.get(p) not in ("100644", "100755"):
            raise Refused(f"the break may only edit tracked regular files; {p} is "
                          f"{'untracked' if p not in modes else 'mode ' + modes[p]}")
    return paths


class Broken:
    """Apply a break; always put every touched file back, verified.

    A journal under .git records the original bytes BEFORE the break is applied,
    so a run killed between apply and restore (SIGKILL, power loss) is undone by
    the next invocation of this tool, which refuses to do anything else first.
    """

    def __init__(self, repo, patch, paths):
        self.repo, self.patch, self.paths = Path(repo), patch, paths
        self.saved, self.modes, self.broken_mtimes = {}, {}, {}
        self.journal = git_dir(repo) / "prove-claim-journal.json"

    def __enter__(self):
        for p in self.paths:
            f = self.repo / p
            self.saved[p] = f.read_bytes()
            self.modes[p] = f.stat().st_mode
        # HEAD and each path's index blob let recovery tell "this repo, still broken"
        # from "the user has since switched branch or fixed the file by hand".
        blobs = {sha_path[2]: sha_path[1] for sha_path in index_entries(self.repo)
                 if sha_path[2] in self.saved}
        head = git(self.repo, "rev-parse", "--verify", "--quiet", "HEAD", check=False).stdout.strip()
        write_atomic(self.journal, json.dumps({
            "head": head, "blobs": blobs,
            "files": {p: base64.b64encode(b).decode() for p, b in self.saved.items()},
            "modes": self.modes}))
        try:
            r = git(self.repo, "apply", str(self.patch), check=False)
            if r.returncode != 0:
                raise Refused(f"the break did not apply: {r.stderr.strip()[:300]}")
            for p in self.paths:
                self.broken_mtimes[p] = (self.repo / p).stat().st_mtime_ns
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(self, *exc):
        self._restore()
        return False

    def _restore(self):
        bad = restore_files(self.repo, self.saved, self.modes, self.broken_mtimes)
        if bad:
            raise RestoreFailed("could not restore: " + "; ".join(bad)
                                + f" — the journal {self.journal} still holds the originals")
        self.journal.unlink(missing_ok=True)


def restore_files(repo, saved, modes, broken_mtimes=None):
    """Write the saved bytes back, mode and a fresh mtime; return the problems."""
    bad = []
    for p, data in saved.items():
        f = Path(repo) / p
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
            os.chmod(f, modes[p] & 0o7777)
        except OSError as e:
            bad.append(f"{p}: {e}")
            continue
        if f.read_bytes() != data:
            bad.append(f"{p}: bytes differ after restore")
            continue
        # Restoring the bytes is not enough: anything BUILT during the break still
        # holds the broken code, and a build tool asking "is the source newer than
        # the output?" — make, cargo, a copy-if-newer step — would keep using it.
        # So the restored file is made newer than anything built under the break:
        # now, and at least one second past the broken write (which also defeats
        # Python's exact-mtime .pyc check). Putting the ORIGINAL mtime back would
        # make the restored source look older than the broken build — stale forever.
        broke = (broken_mtimes or {}).get(p, 0)
        t = max(time.time_ns(), broke + 10**9)
        try:
            os.utime(f, ns=(t, t))
        except OSError as e:
            bad.append(f"{p}: could not reset mtime: {e}")
    return bad


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=Path(path).parent, prefix=".prove-claim-")
    with os.fdopen(fd, "w") as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def lock(repo):
    """Hold an exclusive lock for this run; a second run exits 2 instead of
    recovering — and so reverting — a live run's break."""
    fh = open(git_dir(repo) / "prove-claim.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise Usage("another prove-claim.py run holds the lock in this repo — wait for it")
    return fh


def recover_if_needed(repo):
    """An interrupted earlier run left a journal: undo its break, then stop (exit 3).

    Only when the repo is still the one the journal was written in — same HEAD,
    same index blob for every path. Otherwise the user has moved on (another
    branch, a hand fix) and writing the journal's bytes would clobber their work.
    """
    journal = git_dir(repo) / "prove-claim-journal.json"
    if not journal.exists():
        return
    try:
        j = json.loads(journal.read_text())
        saved = {p: base64.b64decode(b) for p, b in j["files"].items()}
        modes = {p: int(m) for p, m in j["modes"].items()}
        head, blobs = j["head"], j["blobs"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
        raise RestoreFailed(f"an interrupted run's journal {journal} is unreadable ({e}) — "
                            "restore its files by hand (git checkout), then delete it")
    now_head = git(repo, "rev-parse", "--verify", "--quiet", "HEAD", check=False).stdout.strip()
    now_blobs = {p: sha for _m, sha, p in index_entries(repo) if p in saved}
    if now_head != head or now_blobs != blobs:
        raise RestoreFailed(f"an interrupted run left the journal {journal}, but the repo has "
                            "moved since (HEAD or the index differs), so it was NOT restored. "
                            f"Check {', '.join(saved)} by hand, then delete the journal")
    bad = restore_files(repo, saved, modes)
    if bad:
        raise RestoreFailed("an interrupted run left a break in the tree and it could not be "
                            "undone: " + "; ".join(bad))
    journal.unlink()
    raise RestoreFailed(f"an earlier run was interrupted with a break applied; restored "
                        f"{len(saved)} file(s) from its journal ({', '.join(saved)}). Check "
                        "the tree (`git status`), then run again")


def _on_signal(signum, _frame):
    raise KeyboardInterrupt(f"signal {signum}")


# ------------------------------------------------------------------- modes

def require_build(build, no_build):
    if build is not None and build.strip() in TRIVIAL_BUILD:
        raise Usage(f"--build {build!r} builds nothing — give the project's build, or "
                    "--no-build-step WHY")
    if not build and not no_build:
        raise Usage("give --build CMD (the code must still build with the break in place) "
                    "or --no-build-step WHY")


def prove(repo, plan, task, index, patch_src, test, build, no_build, timeout, write=True):
    plan_text = read_plan(plan)
    block = task_block(plan_text, task)
    text = pick(PFA.claim_clauses(block["test"]), index, "claim")
    require_planned_test(test, block["test"], task)
    require_build(build, no_build)
    seen = observe(repo, patch_src, test, build, no_build, timeout, text)
    if not write:
        return None
    named = NAMED_BREAK.search(text)
    rec = {
        "schema": SCHEMA, "kind": "claim", "plan": str(Path(plan).resolve()),
        "task": task, "index": index, "text": text,
        "named_break": named.group(1).strip() if named else None,
        "build": build, "no_build_reason": no_build, "test": test, **seen,
        "created": _now(),
    }
    return write_record(repo, plan, task, "claim", index, rec)


def observe(repo, patch_src, test, build, no_build, timeout, text):
    """Watch `test` pass, fail under the break, and the tree come back. Returns the
    record fields the run proves; raises Refused / RestoreFailed otherwise."""
    require_clean(repo)
    fp = index_fingerprint(repo)
    # The break is read ONCE, into a private copy: validated, applied and recorded
    # from the same bytes, so nothing can swap it between check and use.
    fd, private = tempfile.mkstemp(dir=git_dir(repo), prefix="prove-claim-", suffix=".patch")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(Path(patch_src).read_bytes())
        patch_text = Path(private).read_text(errors="replace")
        paths = check_patch(repo, private, test)
        base, red = _observe(repo, private, paths, test, build, no_build, timeout, fp, text)
    finally:
        Path(private).unlink(missing_ok=True)
    return {"break_patch": patch_text, "touched": paths, "fingerprint": fp,
            "baseline": {"exit": base[0], "tail": base[1], "elapsed_s": base[2]},
            "red": {"exit": red[0], "tail": red[1], "elapsed_s": red[2]}}


def unparseable(repo, paths):
    """Touched files whose syntax this tool can check and which do not parse."""
    bad = []
    for p in paths:
        f = Path(repo) / p
        try:
            if p.endswith(".py"):
                compile(f.read_bytes(), p, "exec", dont_inherit=True)
            elif p.endswith(".json"):
                json.loads(f.read_bytes())
            elif p.endswith((".sh", ".bash")):
                if subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode:
                    bad.append(p)
        except (SyntaxError, ValueError, RecursionError):  # RecursionError: deep nesting
            bad.append(p)
    return bad


def _observe(repo, patch, paths, test, build, no_build, timeout, fp, text):
    if build:
        b_rc, b_tail = run(build, repo, timeout)
        if b_rc != 0:
            raise Refused(f"the code does not build before the break (exit {b_rc})\n{b_tail}")
    t0 = time.monotonic()
    base_rc, base_tail = run(test, repo, timeout)
    base_s = round(time.monotonic() - t0, 1)
    if base_rc is None:
        raise OverBudget(f"the test ran over --timeout {timeout} s before the break "
                         f"({base_s} s) — the task-test budget is spent; stop and report, "
                         "never narrow the test to fit")
    if base_rc != 0:
        raise Refused(f"the test does not pass before the break (exit {base_rc}) — a test "
                      f"that fails anyway proves nothing\n{base_tail}")
    with Broken(repo, patch, paths):
        if build:
            b_rc, b_tail = run(build, repo, timeout)
            if b_rc != 0:
                raise Refused(f"the code does not build with the break (exit {b_rc}) — a "
                              f"break that stops the build turns every test red\n{b_tail}")
        else:
            # No build step to catch it: a break that leaves a file unparseable turns
            # every test red, which is the "easier substituted break" this tool exists
            # to refuse. Checked where the language is known.
            broken = unparseable(repo, paths)
            if broken:
                raise Refused(f"the break leaves {', '.join(broken)} unparseable — with no "
                              "build step that fails every test, not this claim")
        t0 = time.monotonic()
        red_rc, red_tail = run(test, repo, timeout)
        red_s = round(time.monotonic() - t0, 1)
    if build:
        # Rebuild on the restored sources, so the broken build does not outlive the proof.
        a_rc, a_tail = run(build, repo, timeout)
        if a_rc != 0:
            raise RestoreFailed(f"the build fails after the restore (exit {a_rc})\n{a_tail}")
    try:
        require_clean(repo)
        after = index_fingerprint(repo)
    except Refused as e:
        raise RestoreFailed(f"the tree is not as it was before the proof: {e}")
    if after != fp:
        raise RestoreFailed("the index changed during the proof — the build or test staged "
                            "something; the record would bind to a tree nobody proved")
    if red_rc is None:
        raise Refused(f"the test hung under the break ({red_tail}) — inconclusive")
    if red_rc in (126, 127) or red_rc < 0 or red_rc >= 128:
        raise Refused(f"the test could not RUN under the break (exit {red_rc}: not found, "
                      f"not executable, or killed by a signal) — that is not the claim "
                      f"failing\n{red_tail}")
    if red_rc == 0:
        raise Refused("the test still PASSES with the break in place — it does not check "
                      f"this:\n  {text}\n{red_tail}")
    return (base_rc, base_tail, base_s), (red_rc, red_tail, red_s)


def req(repo, plan, task, index, check, covered_by, timeout, brk=None, build=None,
        no_build=None):
    plan_text = read_plan(plan)
    block = task_block(plan_text, task)
    text = pick(PFA.requirement_clauses(block["desc"]), index, "requirement")
    require_clean(repo)
    fp = index_fingerprint(repo)
    rec = {"schema": SCHEMA, "kind": "req", "plan": str(Path(plan).resolve()), "task": task,
           "index": index, "text": text, "fingerprint": fp, "created": _now()}
    if covered_by is not None:
        claims = PFA.claim_clauses(block["test"])
        if not 1 <= covered_by <= len(claims):
            raise Refused(f"claim {covered_by} does not exist in Task {task}")
        claim = record_path(repo, plan, task, "claim", covered_by)
        crec = load(claim) if claim.exists() else None
        problems = (validate(crec, fp, ("claim", task, covered_by, claims[covered_by - 1]))
                    if claim.exists() else [f"{claim} does not exist"])
        if not problems and crec.get("kind") != "claim":
            # validate() accepts a reasoned claim deviation as a RECORD; it is still
            # a disclosure, not a proof, and covers no requirement.
            problems = ["it is recorded as a claim deviation, not proven"]
        if problems:
            raise Refused(f"claim {covered_by} is not a valid proof for this tree: "
                          + "; ".join(problems))
        rec["covered_by_claim"] = covered_by
    else:
        if not check or check.strip() in TRIVIAL_BUILD:
            raise Usage(f"--check {check!r} checks nothing")
        if not brk:
            raise Usage("--check needs --break PATCH: a check is evidence only if it fails "
                        "when the requirement is broken (`echo ok` never does)")
        require_build(build, no_build)
        seen = observe(repo, brk, check, build, no_build, timeout, text)
        rec.update({"check": check, "build": build, "no_build_reason": no_build, **seen})
    return write_record(repo, plan, task, "req", index, rec)


def deviation(repo, plan, task, index, why, target="req"):
    """A requirement (`target` "req") or a claim ("claim") recorded as not checkable
    here, with the reason. A claim deviation replaces any proof at claim-K.json."""
    plan_text = read_plan(plan)
    block = task_block(plan_text, task)
    if target == "claim":
        text = pick(PFA.claim_clauses(block["test"]), index, "claim")
    else:
        text = pick(PFA.requirement_clauses(block["desc"]), index, "requirement")
    if not why or len(why.strip()) < 10:
        raise Usage("--why must say what differs and why (10+ characters)")
    kind = "claim-deviation" if target == "claim" else "deviation"
    rec = {"schema": SCHEMA, "kind": kind, "plan": str(Path(plan).resolve()),
           "task": task, "index": index, "text": text, "why": why.strip(),
           "fingerprint": index_fingerprint(repo), "created": _now()}
    return write_record(repo, plan, task, "claim" if target == "claim" else "deviation",
                        index, rec)


def replay(repo, plan, task, timeout):
    root = Path(repo) / PROOF_DIR / plan_stem(plan)
    files = sorted(root.glob(f"{task}/claim-*.json" if task else "*/claim-*.json"))
    if not files:
        raise Refused(f"no claim records under {root}" + (f"/{task}" if task else ""))
    plan_text, failed = read_plan(plan), 0
    for f in files:
        rec = load(f)
        m = re.match(r"claim-(\d+)\.json$", f.name)
        if isinstance(rec, dict) and rec.get("kind") == "claim-deviation":
            # No break to re-run: disclosed, not proven. Named, never a failure.
            print(f"skip  {f.relative_to(repo)}: claim deviation — {rec.get('why', '')}")
            continue
        try:
            text = PFA.claim_clauses(task_block(plan_text, f.parent.name)["test"])[int(m.group(1)) - 1]
        except (Usage, IndexError):
            text = None
        problems = validate(rec, None, ("claim", f.parent.name, int(m.group(1)), text))
        if not problems:
            fd, tmp = tempfile.mkstemp(dir=git_dir(repo), prefix="prove-claim-replay-",
                                       suffix=".patch")
            try:
                with os.fdopen(fd, "w") as out:
                    out.write(rec["break_patch"])
                prove(repo, plan, rec["task"], rec["index"], tmp, rec["test"],
                      rec.get("build"), rec.get("no_build_reason"), timeout, write=False)
            except (Refused, Usage, OverBudget) as e:
                # One slow record is that record's failure; the rest still replay.
                problems = [str(e).splitlines()[0]]
            finally:
                Path(tmp).unlink(missing_ok=True)
        if problems:
            failed += 1
            print(f"FAIL  {f.relative_to(repo)}: {'; '.join(problems)}")
        else:
            print(f"ok    {f.relative_to(repo)}: the break still turns the test red")
    if failed:
        raise Refused(f"{failed} of {len(files)} record(s) did not replay")
    return None


# ------------------------------------------------------------------- records

def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def write_record(repo, plan, task, kind, index, rec):
    path = record_path(repo, plan, task, kind, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A requirement is either checked or a deviation, never both.
    other = {"req": "deviation", "deviation": "req"}.get(kind)
    if other:
        record_path(repo, plan, task, other, index).unlink(missing_ok=True)
    path.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    print(f"prove-claim: recorded {path.relative_to(repo)}")
    return path


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, RecursionError) as e:  # RecursionError: deep nesting
        return {"_unreadable": str(e)}


def _is_int(x):
    return type(x) is int  # not bool: True == 1 and False == 0 would pass an == check


def _exit(rec, key):
    """rec[key]["exit"], or None when either level is not what a record holds."""
    v = rec.get(key)
    return v.get("exit") if isinstance(v, dict) else None


def _check_run(rec, p, what):
    """The fields a watched run (claim, or schema-2 req check) must carry."""
    if not _is_int(_exit(rec, "baseline")) or _exit(rec, "baseline") != 0:
        p.append("baseline run did not pass")
    red = _exit(rec, "red")
    if not _is_int(red) or red == 0 or red in (126, 127) or red < 0 or red >= 128:
        p.append(f"the {what} did not fail under the break")
    if not isinstance(rec.get("break_patch"), str) or not rec["break_patch"].strip():
        p.append("no break recorded")
    touched = rec.get("touched")
    if not isinstance(touched, list) or not touched:
        p.append("no touched files recorded")
    elif any(not isinstance(t, str) or TEST_PATH.search(t) for t in touched):
        p.append("the break touched a test file")
    build, why = rec.get("build"), rec.get("no_build_reason")
    if not (isinstance(build, str) and build.strip() not in TRIVIAL_BUILD) and not (
            isinstance(why, str) and why.strip()):
        p.append("no real build step and no reason for its absence")


def is_legacy(rec):
    """A schema-1 req record whose check was only seen to pass, never to fail."""
    return (isinstance(rec, dict) and rec.get("schema") == 1 and rec.get("kind") == "req"
            and "covered_by_claim" not in rec)


def validate(rec, fingerprint=None, expect=None, allow_legacy=False):
    """Problems with a record, [] when valid. Shared by the audit and the commit gate
    (hooks/git-ref-gate.sh).

    `expect` = (kind, task, index, text) from the record's PATH and the plan: a
    record copied to another name, or proven against a claim the plan has since
    reworded, does not count. `text` None skips only the text comparison.
    `allow_legacy` accepts a schema-1 req check (see is_legacy) — the audit's
    choice, which reports it advisory; the commit hook never passes it.
    """
    if not isinstance(rec, dict):
        return ["not a record"]
    if "_unreadable" in rec:
        return [f"unreadable: {rec['_unreadable']}"]
    # Every field below is read defensively: validate() answers for a hand-made
    # record, and a record that crashed it would be one no caller judged.
    p = []
    legacy = allow_legacy and is_legacy(rec)
    schema = rec.get("schema")
    if not (schema == SCHEMA or legacy or (schema == 1 and rec.get("kind") != "req")
            or (schema == 1 and "covered_by_claim" in rec)):
        p.append(f"schema {schema!r} is not {SCHEMA}"
                 + (" — a schema-1 req check was never shown able to fail" if is_legacy(rec)
                    else ""))
    kind = rec.get("kind")
    if kind == "claim-deviation" and (not expect or expect[0] == "claim"):
        # A disclosed claim, stored where its proof would be. One validator for it,
        # the audit's, so the audit and the commit hook cannot disagree.
        return p + PFA.claim_deviation_problems(
            rec, fingerprint, expect or ("claim", rec.get("task"), rec.get("index"), None))
    if expect:
        ekind, etask, eindex, etext = expect
        if kind != ekind:
            p.append(f"a {kind!r} record stored as a {ekind!r} record")
        if rec.get("task") != etask or rec.get("index") != eindex:
            p.append(f"records Task {rec.get('task')} #{rec.get('index')}, not Task {etask} "
                     f"#{eindex}")
        if etext is not None and rec.get("text") != etext:
            p.append("proven against different wording than the plan now has")
    if kind == "claim":
        _check_run(rec, p, "test")
        if not isinstance(rec.get("test"), str) or not rec["test"].strip():
            p.append("no test command recorded")
    elif kind == "req":
        if "covered_by_claim" in rec:
            if not _is_int(rec["covered_by_claim"]) or rec["covered_by_claim"] < 1:
                p.append("covered_by_claim is not a claim number")
        elif legacy:
            if (not _is_int(_exit(rec, "result")) or _exit(rec, "result") != 0
                    or not isinstance(rec.get("check"), str)):
                p.append("the check did not pass")
        else:
            _check_run(rec, p, "check")
            if not isinstance(rec.get("check"), str) or not rec["check"].strip():
                p.append("no check command recorded")
    elif kind == "deviation":
        if not isinstance(rec.get("why"), str) or not rec["why"].strip():
            p.append("a deviation without a reason")
    else:
        p.append(f"unknown kind {kind!r}")
    fpr = rec.get("fingerprint")
    if not isinstance(fpr, str) or not HEX64.match(fpr):
        p.append("no valid fingerprint")
    elif fingerprint and fpr != fingerprint:
        p.append("proven on a different tree than this one")
    return p


# ------------------------------------------------------------------- main

def break_file(repo, given):
    """The --break file: as given from the cwd, else (a relative path) under --repo."""
    brk = Path(given).resolve()
    if not brk.is_file() and not Path(given).is_absolute() and (repo / given).is_file():
        brk = (repo / given).resolve()
    if not brk.is_file():
        raise Usage(f"--break file not found: {brk} (--break takes a file holding the diff, not the diff itself: write it to the repo's top-level .claude/, e.g. .claude/break-1.patch)")
    return brk


def main():
    _warn_if_stale()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)

    def common(p, task_required=True):
        p.add_argument("--repo", required=True)
        p.add_argument("--plan", required=True)
        p.add_argument("--task", required=task_required)
        p.add_argument("--timeout", type=int, default=3600)

    c = sub.add_parser("claim"); common(c)
    c.add_argument("--claim", type=int, required=True)
    c.add_argument("--break", dest="brk", required=True, metavar="PATCH",
                   help="the break: a FILE holding the unified diff, outside the work tree (e.g. under $TMPDIR) or in the repo's top-level .claude/, which this tool leaves aside — use .claude/ where the host refuses writes outside the workspace. A relative path that does not exist from the cwd resolves against --repo")
    c.add_argument("--test", required=True)
    g = c.add_mutually_exclusive_group()
    g.add_argument("--build")
    g.add_argument("--no-build-step", dest="no_build")
    r = sub.add_parser("req"); common(r)
    r.add_argument("--req", type=int, required=True)
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--check")
    g.add_argument("--covered-by-claim", type=int, dest="covered")
    r.add_argument("--break", dest="brk", metavar="PATCH",
                   help="the break of the requirement: a FILE holding the unified diff, outside the work tree (e.g. under $TMPDIR) or in the repo's top-level .claude/, which this tool leaves aside — use .claude/ where the host refuses writes outside the workspace. A relative path that does not exist from the cwd resolves against --repo")
    g2 = r.add_mutually_exclusive_group()
    g2.add_argument("--build")
    g2.add_argument("--no-build-step", dest="no_build")
    d = sub.add_parser("deviation"); common(d)
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--req", type=int)
    g.add_argument("--claim", type=int)
    d.add_argument("--why", required=True)
    rp = sub.add_parser("replay"); common(rp, task_required=False)
    fpp = sub.add_parser("fingerprint")
    fpp.add_argument("--repo", required=True)
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    if git(repo, "rev-parse", "--show-toplevel", check=False).stdout.strip() != str(repo):
        raise Usage(f"{repo} is not the root of a git work tree")
    held = lock(repo)  # noqa: F841 — released when the process exits
    recover_if_needed(repo)
    if a.mode == "fingerprint":
        print(index_fingerprint(repo))
    elif a.mode == "claim":
        brk = break_file(repo, a.brk)
        prove(repo, a.plan, a.task, a.claim, brk, a.test, a.build, a.no_build, a.timeout)
    elif a.mode == "req":
        brk = None
        if a.brk:
            brk = break_file(repo, a.brk)
        req(repo, a.plan, a.task, a.req, a.check, a.covered, a.timeout, brk, a.build, a.no_build)
    elif a.mode == "deviation":
        if a.claim is not None:
            deviation(repo, a.plan, a.task, a.claim, a.why, target="claim")
        else:
            deviation(repo, a.plan, a.task, a.req, a.why)
    elif a.mode == "replay":
        replay(repo, a.plan, a.task, a.timeout)
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGHUP, _on_signal)
    try:
        sys.exit(main())
    except Refused as e:
        print(f"prove-claim: NOT PROVEN — {e}", file=sys.stderr)
        sys.exit(1)
    except OverBudget as e:
        print(f"prove-claim: OVER BUDGET — {e}", file=sys.stderr)
        sys.exit(4)
    except RestoreFailed as e:
        print(f"prove-claim: RESTORE FAILED — {e}. Check the tree by hand before anything "
              "else.", file=sys.stderr)
        sys.exit(3)
    except Usage as e:
        print(f"prove-claim: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt as e:
        print(f"prove-claim: interrupted ({e}); touched files were restored before exit",
              file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001 — never let a crash read as "not proven"
        print(f"prove-claim: internal error: {e.__class__.__name__}: {e}", file=sys.stderr)
        sys.exit(2)
