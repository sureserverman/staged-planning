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
  3. the build (when given) and the test PASS as the code stands, under bash when
     bash is on PATH (else sh); the record names the shell
  4. the break — a content edit of existing, tracked, regular, non-test files
     only, read once into a private copy — is applied; a journal under .git
     records what it touched, so a killed run is undone by the next one
  5. the code still builds with the break (a break that stops compilation turns
     every test red); the test FAILS, and not because it could not run
  6. every touched file is restored and verified byte-identical, with an mtime
     newer than anything built under the break; the build runs again (also after
     a refusal under the break); the whole tree must then be exactly as before —
     the untracked files the build and the baseline wrote before the break aside,
     which a later run's step 1 still refuses unless ignored — otherwise exit 3
  7. a record is written to proof/<plan-stem>/<task>/claim-<K>.json. It binds the
     blob of each file the break touched (`touched_blobs`) and of each tracked file
     the test command names (`witness_blobs`), read from the index the proof ran on, and
     keeps the whole-index `fingerprint` beside it; a command whose test files it cannot
     resolve gets neither map, and the fingerprint binds the record

`req` records that a requirement clause was checked — by a command that passes,
and FAILS under a break of that requirement, through the same run as a claim
(a check that cannot fail, like `echo ok`, is refused) — or is covered by a
proven claim. `deviation --req` records one that could not be checked. Either first moves
a req or deviation record already at that number whose text is another clause's (the
clauses were renumbered) to that clause's number, and refuses when that number is taken.
`deviation --claim` records a CLAIM no repo patch can break — its evidence lives
outside the repo (a file in the records home, a device) — at claim-K.json as kind
`claim-deviation`: disclosed, so the audit reports it, but never proof.
`replay` re-runs every claim record's break against the tree as it stands; a
claim deviation has no break and is listed as skipped.

WHAT THIS DOES NOT DO. Whether a break, or a req check, is the one that matters
is judgment — a reviewer's, reading the record. The plan's "red if …"
is recorded as `named_break` so a reader can compare. A record written by hand
is still possible; replay, the binding to the touched files' blobs and validate()
make it a deliberate lie rather than an oversight. One run each: a flaky test can pass.

WHAT A RECORD BINDS. A record names the files its break touched, and `touched_blobs`
holds the blob each had when the test was watched; `witness_blobs` holds the blob of
every tracked file the test command names, runs as a script or reads its recipe from
(witness_files(): a directory argument binds the tracked files under it).
validate() judges a record against a tree by those blobs alone: a change elsewhere in the
tree (the task's own Status flip in a plan kept in the repo, a rebase, a squash or a
cherry-pick that leaves the bound files as they were) leaves it valid, and a change to a
bound file makes it stale. Not bound: what the test imports or sources (a conftest.py, a
helper, a fixture) unless the command names it or a directory holding it, other files the
touched code depends on, and file modes. A command whose test files cannot be resolved (bare
`pytest`, `python3 -m pytest`, a path that names nothing tracked) writes neither map, and
the record is judged by its whole-index `fingerprint`, as is one without both maps (written
before the blob binding) or with an empty witness. A deviation proves no file and keeps the
fingerprint rule too; a req covered by a claim binds that claim's blobs.

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
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import stat
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
# A git object id: SHA-1 (40 hex) or SHA-256 (64 hex) repositories.
OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
# What a record binds, path -> blob: the files its break touched, and the tracked files its
# test (or check) command names (not what that test imports). A record binds by blobs only
# when it carries both and its witness is not empty (binds_by_blobs).
BLOB_MAPS = ("touched_blobs", "witness_blobs")

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


def commit_entries(repo, rev):
    """`(mode, sha, path)` entries of a commit's tree, in the form index_entries gives."""
    out, entries = git(repo, "ls-tree", "-r", "-z", rev).stdout, []
    for rec in out.split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            mode, _type, sha = meta.split()
            entries.append((mode, sha, path))
    return entries


def commit_fingerprint(repo, rev):
    """Fingerprint of a commit's tree in the same form as index_fingerprint."""
    return _fingerprint_lines(commit_entries(repo, rev))


def blobs_of(entries):
    """{path: blob id} of a tree's entries: what a record's touched_blobs is judged against."""
    return {path: sha for _mode, sha, path in entries}


def commit_blobs(repo, rev):
    """{path: blob id} of a commit's tree."""
    return blobs_of(commit_entries(repo, rev))


def commit_tree(repo, rev):
    """(fingerprint, {path: blob id}) of a commit's tree, from one listing."""
    entries = commit_entries(repo, rev)
    return _fingerprint_lines(entries), blobs_of(entries)


def untracked_files(repo):
    """Untracked, unignored paths outside proof/ and the top-level .claude/."""
    ex = f":(exclude){PROOF_DIR}"
    return [u for u in git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--",
                           ".", ex, ":(top,exclude).claude/").stdout.split("\0") if u]


def require_clean(repo, allowed_untracked=()):
    """Worktree == index outside proof/; nothing hides a difference; proof/ holds records only.

    `allowed_untracked` is the after-the-proof check's: what the build and the baseline
    run wrote before the break was applied is the tree the break started from.

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
    untracked = [u for u in untracked_files(repo) if u not in allowed_untracked]
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

def test_shell(wanted=None):
    """(name, path) of the shell a test runs under: bash when it is on PATH, else sh.

    A Test may use bash syntax (`<(…)`, `{a,b}`), which /bin/sh rejects as a syntax
    error where sh is dash. A record names its shell, and a replay asks for that one:
    a bash record is never re-run under sh, and a record without the field (written
    before it existed) ran under sh.
    """
    if wanted in (None, "bash"):
        bash = shutil.which("bash")
        if bash:
            # Absolute now: a relative PATH entry (`.`) would otherwise be resolved
            # after the chdir into the repo, running a repo-supplied ./bash.
            return "bash", os.path.abspath(bash)
        if wanted == "bash":
            raise Refused("the record ran its test under bash, and bash is not on PATH "
                          "here — replay it where bash is installed")
    return "sh", "/bin/sh"


def run(cmd, repo, timeout, shell="/bin/sh"):
    """(exit code, output tail); exit None on timeout. The whole process group dies.

    No .pyc from any run this tool makes: a break and its restore can land in the
    same second with the same size, and Python then trusts the BROKEN bytecode.
    A timeout or an interrupt kills the process
    GROUP — a test's grandchildren must not keep writing to the tree after restore.
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.Popen(cmd, shell=True, executable=shell, cwd=repo, stdout=subprocess.PIPE,
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
# Shell syntax a simple command can open with, before its program: `{ python3 t.py; }`,
# `( bash t.sh )`, `! grep …`, `if python3 t.py; then …`. A segment opening with a
# closer (`}`, `fi`, `done`) runs nothing.
SHELL_OPENERS = {"!", "{", "(", "if", "then", "elif", "else", "while", "until", "do"}
SHELL_CLOSERS = {"}", ")", "fi", "done", "esac"}
# Commands that run the program they are given: name -> (the options that take a
# separate value, how many positional words come before the program).
WRAPPERS = {"timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1),
            "env": ({"-u", "--unset", "-C", "--chdir"}, 0),
            "time": ({"-f", "--format", "-o", "--output"}, 0)}
# The file each build-tool runner reads its recipe from. `make` reads the first of
# these that exists — any of them is its definition.
MAKEFILES = ("GNUmakefile", "makefile", "Makefile")
MAKE_DIR, MAKE_FILE = ("-C", "--directory"), ("-f", "--file", "--makefile")
JS_RUNNER_DIR = {"npm": ("--prefix",), "yarn": ("--cwd",), "pnpm": ("-C", "--dir")}
# Shells whose `-c STRING` is itself a command line: its commands are read, not the shell.
C_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# What this reading of shell text does NOT see, so a break there is not refused: a
# runner behind another wrapper (`sudo`, `nice`, `nohup`, `exec`, `xargs`, `npx`,
# `uv run`), a `case` arm, an interpreter option taking a value (`python3 -W error
# t.py` names `error`), a variable other than a `for` loop's, a make variable or a
# prerequisite's recipe, and a `cd` to an absolute path or a variable. It reads the
# command (and a make or npm runner's recipe); it does not run a shell.


def killed_by_signal(rc):
    """A run a signal ended: negative (Popen's -N for its own child), or 128+N for a
    signal N of 1..64, as a shell reports its child's death. 128 itself and 193..255
    are exit codes a program chose — `exit(-1)` is 255 — a red like any other."""
    return rc < 0 or 128 < rc <= 128 + 64


def _is_paren(word):
    return bool(word) and set(word) <= {"(", ")"}


def _program_words(words):
    """A simple command's words from its program on: leading shell syntax and wrapper
    commands (with their options and positional arguments) skipped, and cut at a
    closing parenthesis; [] when the segment only closes a compound command."""
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        if w in SHELL_OPENERS or _is_paren(w):
            i += 1
        elif w in SHELL_CLOSERS:
            return []
        elif Path(w).name in WRAPPERS:
            takes_value, positional = WRAPPERS[Path(w).name]
            i += 1
            while i < n and words[i].startswith("-"):
                opt = words[i]
                i += 2 if opt in takes_value else 1
                if opt == "--":
                    break
            i += positional
        else:
            break
    rest = words[i:]
    cut = next((j for j, w in enumerate(rest) if _is_paren(w)), len(rest))
    return rest[:cut]


def _substitutions(cmd):
    """(`cmd` with each `$(…)`, `<(…)`, `>(…)` and backquoted command replaced by one
    placeholder word, [the commands they held]). Text in single quotes runs nothing
    and is left alone; nesting is followed by counting parentheses."""
    out, inner, i, n, quote = [], [], 0, len(cmd), None
    while i < n:
        c = cmd[i]
        if quote == "'":
            quote = None if c == "'" else quote
            out.append(c)
            i += 1
        elif c == "'" and quote is None:
            quote = "'"
            out.append(c)
            i += 1
        elif c == '"':
            quote = None if quote == '"' else '"'
            out.append(c)
            i += 1
        elif c in "$<>" and cmd.startswith("(", i + 1):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(cmd[j], 0)
                j += 1
            inner.append(cmd[i + 2:j - 1])
            out.append("_subst_")
            i = j
        elif c == "`":
            j = cmd.find("`", i + 1)
            j = n if j < 0 else j
            inner.append(cmd[i + 1:j])
            out.append("_subst_")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out), inner


def _segments(cmd):
    """`cmd` split at `&&`, `||`, `;`, `|` and newlines outside quotes."""
    seg, quote, i, n = [], None, 0, len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            quote = None if c == quote else quote
        elif c in "'\"":
            quote = c
        elif cmd.startswith(("&&", "||"), i) or c in ";|\n":
            yield "".join(seg)
            seg = []
            i += 2 if cmd.startswith(("&&", "||"), i) else 1
            continue
        seg.append(c)
        i += 1
    yield "".join(seg)


def _braces(word):
    """`word` with each `{a,b}` list expanded, as a shell does before anything else."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not m:
        return [word]
    return [w for alt in m.group(1).split(",")
            for w in _braces(word[:m.start()] + alt + word[m.end():])]


def _loop_expand(words, loops):
    """One copy of `words` per value of the first `for` variable they use."""
    for i, w in enumerate(words):
        for var, values in loops.items():
            if f"${var}" in w or f"${{{var}}}" in w:
                return [words[:i] + [w.replace(f"${{{var}}}", v).replace(f"${var}", v)]
                        + words[i + 1:] for v in values]
    return [words]


def located_commands(cmd, base=".", _depth=0):
    """(directory, words) for each simple command `cmd` runs, the words from the
    program on — so the program of `timeout 60 python3 t.py` is python3, not timeout.
    Variable assignments (`A=1`) are dropped wherever they stand. `directory` is where
    it runs, relative to the test's: a `cd sub` moves the commands after it, until the
    subshell it stands in closes. A command substitution, a process substitution and a
    shell's `-c STRING` are read as commands of their own."""
    if _depth > 8:
        return
    cmd, inner = _substitutions(cmd)
    for sub in inner:
        yield from located_commands(sub, base, _depth + 1)
    stack, loops = [], {}
    for seg in _segments(cmd):
        try:
            # punctuation_chars: `(bash t.sh)` splits into `(`, `bash`, `t.sh`, `)`.
            lex = shlex.shlex(seg, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            words = list(lex)
        except ValueError:
            words = re.findall(r"[()]|[^\s()]+", seg)
        words = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
        # A subshell opened before the program keeps the directory to return to; a
        # `{ }` group is no subshell, so a `cd` inside it carries on after it.
        for w in words:
            if _is_paren(w):
                stack += [base] * w.count("(")
            elif w not in SHELL_OPENERS:
                break
        prog = _program_words(words)
        if prog and prog[0] == "for":
            # `for v in a {b,c} d*.py` — the body's `$v` is each word (a glob stays a
            # pattern, matched against a break's paths).
            if len(prog) > 3 and prog[2] == "in":
                loops[prog[1]] = [x for w in prog[3:] for x in _braces(w)]
            prog = []
        if prog and prog[0] == "cd":
            dest = prog[1] if len(prog) > 1 else ""
            base = (os.path.normpath(os.path.join(base, dest))
                    if dest and not dest.startswith(("/", "~", "$", "-")) else ".")
        elif prog and Path(prog[0]).name in C_SHELLS and "-c" in prog[1:-1]:
            yield from located_commands(prog[prog.index("-c", 1) + 1], base, _depth + 1)
        elif prog:
            for each in _loop_expand(prog, loops):
                yield base, each
        for _ in range(sum(w.count(")") for w in words if _is_paren(w))):
            if stack:
                base = stack.pop()


def simple_commands(cmd):
    """Each simple command `cmd` runs, as its words from the program on (see
    located_commands)."""
    for _base, words in located_commands(cmd):
        yield words


def command_programs(cmd, base="."):
    """The programs a command runs — each simple command's program, or the script an
    interpreter is given — so a break of the test runner itself can be refused.
    A source file the command merely names (`grep x calc.py`) is not one."""
    out = set()
    for base, words in located_commands(cmd, base):
        prog = words[0]
        if Path(prog).name in INTERPRETERS:
            rest = [w for w in words[1:] if not w.startswith("-")]
            if "-m" in words[1:] or "-c" in words[1:] or not rest:
                continue
            prog = os.path.join(base, rest[0])
        elif "/" in prog:
            prog = os.path.join(base, prog)
        out.add(os.path.normpath(prog))
    return out


def _option_values(args, names):
    """The values given to any of the options `names`, as `-C dir`, `-Cdir` or `--dir=dir`."""
    vals, i = [], 0
    while i < len(args):
        a = args[i]
        if a in names and i + 1 < len(args):
            vals.append(args[i + 1])
            i += 2
            continue
        vals += [a.split("=", 1)[1] for nm in names
                 if nm.startswith("--") and a.startswith(nm + "=")]
        vals += [a[len(nm):] for nm in names
                 if not nm.startswith("--") and a.startswith(nm) and len(a) > len(nm)]
        i += 1
    return vals


def runner_files(cmd):
    """{path: runner} — the files a build-tool runner in `cmd` reads its recipe from:
    make's makefiles (its -f files, under its -C directory) and the package.json of
    npm (--prefix), yarn (--cwd) or pnpm (-C/--dir). A break there edits the runner,
    not the code the claim is about."""
    out = {}
    for where, words in located_commands(cmd):
        name, args = Path(words[0]).name, words[1:]
        if name in ("make", "gmake"):
            base = os.path.join(where, *_option_values(args, MAKE_DIR))
            for f in _option_values(args, MAKE_FILE) or MAKEFILES:
                out[os.path.normpath(os.path.join(base, f))] = name
        elif name in JS_RUNNER_DIR:
            base = os.path.join(where, *_option_values(args, JS_RUNNER_DIR[name]))
            out[os.path.normpath(os.path.join(base, "package.json"))] = name
    return out


def _make_recipe(text, targets):
    """The recipe lines `make <targets>` runs from a makefile's text (the first rule's
    target when none is named), each with its `@`, `-` and `+` prefixes dropped."""
    rules, order, cur = {}, [], None
    for ln in text.splitlines():
        if ln.startswith("\t"):
            for t in cur or ():
                rules[t].append(ln[1:].lstrip("@-+ "))
            continue
        m = re.match(r"^([^\s#:=][^:=]*?)\s*::?(?!=)(.*)$", ln)
        if m:
            cur = m.group(1).split()
            for t in cur:
                rules.setdefault(t, [])
                order.append(t)
            if ";" in m.group(2):
                for t in cur:
                    rules[t].append(m.group(2).split(";", 1)[1].strip())
        elif ln.strip() and not ln.lstrip().startswith("#"):
            cur = None
    targets = targets or [t for t in order if not t.startswith(".")][:1]
    return [c for t in targets for c in rules.get(t, [])]


NPM_ALIASES = {"t": "test", "tst": "test", "run-script": "run"}


def recipe_lines(repo, cmd, base="."):
    """(directory, command line) for each line of a make recipe or an npm/yarn/pnpm script
    that `cmd` runs, one level down: the directory is where the recipe runs."""
    for where, words in located_commands(cmd, base):
        name, args = Path(words[0]).name, words[1:]
        recipes, at = [], where
        if name in ("make", "gmake"):
            at = os.path.normpath(os.path.join(where, *_option_values(args, MAKE_DIR)))
            files = _option_values(args, MAKE_FILE) or MAKEFILES
            skip = {v for v in _option_values(args, MAKE_DIR + MAKE_FILE)}
            targets = [a for a in args if not a.startswith("-") and "=" not in a
                       and a not in skip and not a.isdigit()]
            for f in files:
                mk = Path(repo) / at / f
                if mk.is_file():
                    recipes = _make_recipe(mk.read_text(errors="replace"), targets)
                    break
        elif name in JS_RUNNER_DIR:
            at = os.path.normpath(os.path.join(where, *_option_values(args, JS_RUNNER_DIR[name])))
            pos = [a for a in args if not a.startswith("-") and a not in _option_values(args, JS_RUNNER_DIR[name])]
            pos = [NPM_ALIASES.get(a, a) for a in pos]
            script = pos[1] if pos[:1] == ["run"] and len(pos) > 1 else (pos[0] if pos else None)
            try:
                scripts = json.loads((Path(repo) / at / "package.json").read_text()).get("scripts", {})
            except (OSError, ValueError, AttributeError):
                scripts = {}
            if script and isinstance(scripts, dict):
                recipes = [scripts[k] for k in (f"pre{script}", script, f"post{script}")
                           if isinstance(scripts.get(k), str)]
        for rc in recipes:
            yield at, rc


def recipe_programs(repo, cmd, base=".", _depth=0):
    """The programs a make recipe or an npm/yarn/pnpm script runs, when `cmd` runs one:
    the recipe's runner is the test's runner, one file further on."""
    out = set()
    if _depth > 4:
        return out
    for at, rc in recipe_lines(repo, cmd, base):
        out |= command_programs(rc, at)
        out |= recipe_programs(repo, rc, at, _depth + 1)
    return out


# Programs whose arguments name the tests they run: an interpreter's script, a test
# runner's files and directories. An argument of one that reads as a path but names nothing
# tracked is a test the witness cannot bind (witness_files answers None).
TEST_RUNNERS = {"pytest", "py.test", "go", "cargo", "jest", "vitest", "mocha", "bats",
                "rspec", "phpunit", "tox", "nox", "ctest"}
# The option of an interpreter whose value is program text, not a path.
CODE_OPTION = {"python": "-c", "python3": "-c", "node": "-e", "perl": "-e", "ruby": "-e"}
PATH_LIKE = re.compile(r"/|^\.\.?$|\.(py|sh|bash|bats|js|mjs|cjs|ts|tsx|jsx|rb|pl|go|rs|lua"
                       r"|r|tcl|ps1|php|java|kt|swift|json|toml|ini|cfg|ya?ml)$", re.I)
DOTTED_MODULE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


def _tracked_under(n, tracked):
    """The tracked paths `n` (a path relative to the repo root) names: a glob's matches, the
    file itself, or every tracked file under a directory (`.`, and Go's `dir/...`)."""
    if n == "...":
        n = "."
    elif n.endswith("/..."):
        n = n[:-4]
    if any(ch in n for ch in "*?["):
        return {t for t in tracked if fnmatch.fnmatchcase(t, n)}
    if n in tracked:
        return {n}
    return set(tracked) if n == "." else {t for t in tracked if t.startswith(n + "/")}


def _argument_witness(cmd, base, tracked):
    """({tracked paths the arguments of `cmd`'s commands name}, complete). Not complete when
    a runner or interpreter is given an argument that reads as a path (or a dotted module
    after `-m`) and names nothing tracked: a test file the record could not bind."""
    out, complete = set(), True
    for where, words in located_commands(cmd, base):
        prog = Path(words[0]).name
        runner = prog in INTERPRETERS or prog in TEST_RUNNERS
        module = prog in INTERPRETERS and "-m" in words[1:]
        code = CODE_OPTION.get(prog)
        args = [w for i, w in enumerate(words[1:], 1)
                if w and not w.startswith("-") and not (code and words[i - 1] == code)]
        for w in args:
            if w.startswith(("/", "~", "$")):
                complete &= not runner
                continue
            n = os.path.normpath(os.path.join(where, w.split("::", 1)[0]))
            hit = _tracked_under(n, tracked)
            if not hit and module and DOTTED_MODULE.match(w):
                n = os.path.normpath(os.path.join(where, *w.split(".")))
                hit = _tracked_under(n + ".py", tracked) or _tracked_under(n, tracked)
                complete &= bool(hit)
            elif not hit and runner and PATH_LIKE.search(w.split("::", 1)[0]):
                complete = False
            out |= hit
    return out, complete


def witness_files(repo, cmd, tracked):
    """The tracked files a Test (or req --check) command runs or reads its recipe from, or
    None when the record cannot bind its test by blobs.

    Each program and interpreter script (command_programs), what a make recipe or an npm
    script runs (recipe_programs), the recipe files themselves (runner_files), and every
    argument of the command and its recipes that names a tracked path: a file
    (`pytest tests/x.py::t`, the `::node` dropped), every tracked file under a directory
    (`pytest tests`, `go test ./...`), a glob's matches, and a dotted module after `-m`
    (`python3 -m unittest tests.test_a` names tests/test_a.py). These are the record's
    witness: a test edited after the proof proves nothing about the code. Not bound: what the
    test imports or sources (a conftest.py, a helper, a fixture) unless the command names it
    or a directory holding it.

    None — no blob maps, so the record keeps the whole-tree fingerprint rule — when the
    witness is empty (bare `pytest`, `python3 -m pytest`, `cargo test`) or a runner or
    interpreter is given a path that names nothing tracked. `tracked` is the set of tracked
    paths; proof/ never counts."""
    named = command_programs(cmd) | recipe_programs(repo, cmd) | set(runner_files(cmd))
    out = set()
    for n in named:
        if any(ch in n for ch in "*?["):
            out |= {t for t in tracked if fnmatch.fnmatchcase(t, n)}
        elif n in tracked:
            out.add(n)
    complete, todo = True, [(".", cmd, 0)]
    while todo:
        base, line, depth = todo.pop()
        got, whole = _argument_witness(line, base, tracked)
        out, complete = out | got, complete and whole
        if depth < 4:
            todo += [(at, rc, depth + 1) for at, rc in recipe_lines(repo, line, base)]
    out = sorted(t for t in out if not t.startswith(PROOF_DIR + "/"))
    return out if out and complete else None


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
    runs = (command_programs(test) | recipe_programs(repo, test)) if test else set()
    patterns = {r for r in runs if any(ch in r for ch in "*?[")}
    recipes = runner_files(test) if test else {}
    for p in paths:
        if TEST_PATH.search(p):
            raise Refused(f"the break touches a test file ({p}) — break the code the claim "
                          "is about, not the test that checks it")
        if os.path.normpath(p) in runs or any(fnmatch.fnmatchcase(p, r) for r in patterns):
            raise Refused(f"the break edits {p}, which the test command runs — breaking the "
                          "test runner proves only that a runner can be made to fail")
        if os.path.normpath(p) in recipes:
            raise Refused(f"the break edits {p}, the file `{recipes[os.path.normpath(p)]}` "
                          "reads to run the test — breaking the runner's recipe proves only "
                          "that a runner can be made to fail; break the code it runs")
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
            try:
                f.write_bytes(data)
            except PermissionError:
                # A file left read-only — by the build, or by an earlier partial restore
                # that already put a saved read-only mode back — is still ours to put
                # back: made writable for the write, its saved mode set just below.
                os.chmod(f, stat.S_IMODE(f.stat().st_mode) | stat.S_IWUSR)
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


def prove(repo, plan, task, index, patch_src, test, build, no_build, timeout, write=True,
          shell=None):
    plan_text = read_plan(plan)
    block = task_block(plan_text, task)
    text = pick(PFA.claim_clauses(block["test"]), index, "claim")
    require_planned_test(test, block["test"], task)
    require_build(build, no_build)
    seen = observe(repo, patch_src, test, build, no_build, timeout, text, shell)
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


def observe(repo, patch_src, test, build, no_build, timeout, text, shell=None):
    """Watch `test` pass, fail under the break, and the tree come back. Returns the
    record fields the run proves; raises Refused / RestoreFailed otherwise."""
    shell_name, shell_path = test_shell(shell)
    require_clean(repo)
    fp = index_fingerprint(repo)
    # The blobs the record binds, from the same index: the after-the-proof check below
    # refuses a run whose index moved, so these are the blobs the test was watched on.
    staged = blobs_of(index_entries(repo))
    # The break is read ONCE, into a private copy: validated, applied and recorded
    # from the same bytes, so nothing can swap it between check and use.
    fd, private = tempfile.mkstemp(dir=git_dir(repo), prefix="prove-claim-", suffix=".patch")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(Path(patch_src).read_bytes())
        patch_bytes = Path(private).read_bytes()
        paths = check_patch(repo, private, test)
        base, red = _observe(repo, private, paths, test, build, no_build, timeout, fp, text,
                             shell_path)
    finally:
        Path(private).unlink(missing_ok=True)
    try:
        stored = {"break_patch": patch_bytes.decode("utf-8")}
    except UnicodeDecodeError:
        # Not UTF-8: the readable text is for a person, the exact bytes are for replay.
        stored = {"break_patch": patch_bytes.decode("utf-8", errors="replace"),
                  "break_patch_b64": base64.b64encode(patch_bytes).decode()}
    # No witness (the command names no test file the record can bind): no blob maps, and
    # the record is judged by the whole-tree fingerprint.
    witness = witness_files(repo, test, set(staged))
    maps = ({"touched_blobs": {p: staged[p] for p in paths},
             "witness_blobs": {w: staged[w] for w in witness}} if witness else {})
    return {**stored, "touched": paths, **maps, "fingerprint": fp, "shell": shell_name,
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


def _observe(repo, patch, paths, test, build, no_build, timeout, fp, text, shell):
    if build:
        b_rc, b_tail = run(build, repo, timeout, shell)
        if b_rc != 0:
            raise Refused(f"the code does not build before the break (exit {b_rc})\n{b_tail}")
    t0 = time.monotonic()
    base_rc, base_tail = run(test, repo, timeout, shell)
    base_s = round(time.monotonic() - t0, 1)
    if base_rc is None:
        raise OverBudget(f"the test ran over --timeout {timeout} s before the break "
                         f"({base_s} s) — the task-test budget is spent; stop and report, "
                         "never narrow the test to fit")
    if base_rc != 0:
        raise Refused(f"the test does not pass before the break (exit {base_rc}) — a test "
                      f"that fails anyway proves nothing\n{base_tail}")
    # What the build and the baseline wrote is the tree the break starts from, and
    # the after-the-proof check compares against it: only what appears under the
    # break is a change the restore failed to undo.
    before = set(untracked_files(repo))
    refused = None
    try:
        with Broken(repo, patch, paths):
            if build:
                b_rc, b_tail = run(build, repo, timeout, shell)
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
            red_rc, red_tail = run(test, repo, timeout, shell)
            red_s = round(time.monotonic() - t0, 1)
    except Refused as e:
        # Even a refusal under the break (the build stopped, a file left unparseable)
        # rebuilds below: the broken build must not outlive the proof either way.
        refused = e
    if build:
        # Rebuild on the restored sources, so the broken build does not outlive the proof.
        a_rc, a_tail = run(build, repo, timeout, shell)
        if a_rc != 0:
            raise RestoreFailed(f"the build fails after the restore (exit {a_rc})\n{a_tail}"
                                + (f"\n(the proof was already refused: {refused})"
                                   if refused else ""))
    if refused:
        raise refused
    try:
        require_clean(repo, before)
        after = index_fingerprint(repo)
    except Refused as e:
        raise RestoreFailed(f"the tree is not as it was before the proof: {e}")
    if after != fp:
        raise RestoreFailed("the index changed during the proof — the build or test staged "
                            "something; the record would bind to a tree nobody proved")
    if red_rc is None:
        raise Refused(f"the test hung under the break ({red_tail}) — inconclusive")
    if red_rc in (126, 127) or killed_by_signal(red_rc):
        why = ({126: "not executable", 127: "not found"}.get(red_rc)
               or f"killed by signal {-red_rc if red_rc < 0 else red_rc - 128}")
        raise Refused(f"the test could not RUN under the break (exit {red_rc}: {why}) — "
                      f"that is not the claim failing\n{red_tail}")
    if red_rc == 0:
        raise Refused("the test still PASSES with the break in place — it does not check "
                      f"this:\n  {text}\n{red_tail}")
    return (base_rc, base_tail, base_s), (red_rc, red_tail, red_s)


def make_room(repo, plan, task, index, clauses):
    """Before a req or deviation record is written at `index`: a req or deviation record
    there whose text is another clause j's (the clause split renumbered it: PFA.renumbered)
    is moved to number j, its `index` rewritten, so the new record does not overwrite the
    proof of clause j. Refused, naming both files, when j already holds a record of that kind."""
    for kind in ("req", "deviation"):
        here = record_path(repo, plan, task, kind, index)
        if not here.is_file():
            continue
        old = load(here)
        j = PFA.renumbered(old, clauses)
        if j is None or j == index:
            continue
        there = record_path(repo, plan, task, kind, j)
        if there.exists():
            raise Refused(f"{here.relative_to(repo)} proves requirement {j} by its text, and "
                          f"{there.relative_to(repo)} already holds a record for requirement {j}: "
                          f"keep the one that proves it, remove the other, then record "
                          f"requirement {index} again")
        write_atomic(there, json.dumps(dict(old, index=j), indent=1, sort_keys=True) + "\n")
        here.unlink()
        print(f"prove-claim: moved {here.relative_to(repo)} to {there.relative_to(repo)}: "
              f"its text is requirement {j}'s since the clauses were renumbered")


def req(repo, plan, task, index, check, covered_by, timeout, brk=None, build=None,
        no_build=None):
    plan_text = read_plan(plan)
    block = task_block(plan_text, task)
    text = pick(PFA.requirement_clauses(block["desc"]), index, "requirement")
    make_room(repo, plan, task, index, PFA.requirement_clauses(block["desc"]))
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
        problems = (validate(crec, fp, ("claim", task, covered_by, claims[covered_by - 1]),
                             blobs=blobs_of(index_entries(repo)))
                    if claim.exists() else [f"{claim} does not exist"])
        if not problems and crec.get("kind") != "claim":
            # validate() accepts a reasoned claim deviation as a RECORD; it is still
            # a disclosure, not a proof, and covers no requirement.
            problems = ["it is recorded as a claim deviation, not proven"]
        if problems:
            raise Refused(f"claim {covered_by} is not a valid proof for this tree: "
                          + "; ".join(problems))
        rec["covered_by_claim"] = covered_by
        for key in BLOB_MAPS:
            if key in crec:
                # Covered by a claim, the requirement is bound to what that claim proves.
                rec[key] = crec[key]
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
    if target != "claim":
        make_room(repo, plan, task, index, PFA.requirement_clauses(block["desc"]))
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
                with os.fdopen(fd, "wb") as out:
                    out.write(base64.b64decode(rec["break_patch_b64"])
                              if "break_patch_b64" in rec else rec["break_patch"].encode())
                prove(repo, plan, rec["task"], rec["index"], tmp, rec["test"],
                      rec.get("build"), rec.get("no_build_reason"), timeout, write=False,
                      shell=rec.get("shell", "sh"))
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
    if not _is_int(red) or red == 0 or red in (126, 127) or killed_by_signal(red):
        p.append(f"the {what} did not fail under the break")
    if not isinstance(rec.get("break_patch"), str) or not rec["break_patch"].strip():
        p.append("no break recorded")
    if "break_patch_b64" in rec:
        try:
            raw = base64.b64decode(rec["break_patch_b64"], validate=True)
        except (TypeError, ValueError):
            p.append("break_patch_b64 is not base64")
        else:
            # The bytes replay applies and the text a person reads must be one break.
            if not raw or raw.decode("utf-8", errors="replace") != rec.get("break_patch"):
                p.append("break_patch_b64 is not the break that break_patch shows")
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


def _blob_map_sound(m):
    return isinstance(m, dict) and all(
        isinstance(k, str) and k and isinstance(v, str) and OBJECT_ID.match(v)
        for k, v in m.items())


def touched_blobs_problems(rec):
    """Problems with the shape of a record's blob maps, [] when they are sound:
    `touched_blobs` a non-empty {path: blob id} naming exactly the files the break touched
    (a req covered by a claim carries that claim's, and has no break of its own), and
    `witness_blobs`, when present, a {path: blob id}. An empty witness map is sound in shape
    but binds no test, so validate() judges that record by its fingerprint (binds_by_blobs)."""
    tb = rec.get("touched_blobs")
    if "touched_blobs" in rec and (not isinstance(tb, dict) or not tb):
        return ["touched_blobs binds no file"]
    if "touched_blobs" in rec and not _blob_map_sound(tb):
        return ["touched_blobs holds an entry that is not a path and a blob id"]
    if "witness_blobs" in rec and not _blob_map_sound(rec.get("witness_blobs")):
        return ["witness_blobs is not a map of paths to blob ids"]
    if "touched_blobs" not in rec:
        return ["witness_blobs without touched_blobs binds no touched file"]
    touched = rec.get("touched")
    if "covered_by_claim" not in rec and (
            not isinstance(touched, list) or set(tb) != {t for t in touched if isinstance(t, str)}):
        return ["touched_blobs does not bind exactly the files the break touched"]
    return []


def binds_by_blobs(rec):
    """True when a record is judged by its blob maps: a claim or req carrying both, its
    witness naming at least one test file. An empty witness binds no test, so a test edited
    after the proof would go unseen: that record, like one without both maps (written
    before the blob binding) and a deviation, is judged by its whole-tree fingerprint."""
    return (isinstance(rec, dict) and rec.get("kind") in ("claim", "req")
            and all(isinstance(rec.get(k), dict) for k in BLOB_MAPS)
            and bool(rec["witness_blobs"]))


def blob_drift(rec, blobs):
    """The paths a record binds (`touched_blobs` and `witness_blobs`) whose blob in `blobs`
    — {path: blob id} of the tree judged — is another one, or none. [] for a record that
    does not bind by blobs (binds_by_blobs): its fingerprint binds it."""
    if not binds_by_blobs(rec):
        return []
    maps = [rec.get(k) for k in BLOB_MAPS]
    return sorted({str(p) for m in maps for p, b in m.items() if blobs.get(p) != b})


def validate(rec, fingerprint=None, expect=None, allow_legacy=False, blobs=None):
    """Problems with a record, [] when valid. Shared by the audit and the commit gate
    (hooks/git-ref-gate.sh).

    The tree a record is judged against: `blobs` ({path: blob id}) and `fingerprint`,
    both of that tree. A claim or req record carrying `touched_blobs` and a non-empty
    `witness_blobs` is judged by the blobs of the files they bind; any other by the
    whole-tree `fingerprint` (binds_by_blobs). Neither given: no tree is compared (replay re-runs the
    break instead). A record with `touched_blobs` judged with no `blobs` falls back to
    the fingerprint, the stricter rule.

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
    if "shell" in rec and rec["shell"] not in ("bash", "sh"):
        p.append(f"shell {rec['shell']!r} is not one this tool runs a test under (bash, sh)")
    bound = binds_by_blobs(rec)
    if kind in ("claim", "req") and any(k in rec for k in BLOB_MAPS):
        p.extend(touched_blobs_problems(rec))
    fpr = rec.get("fingerprint")
    if not isinstance(fpr, str) or not HEX64.match(fpr):
        p.append("no valid fingerprint")
    elif bound and blobs is not None:
        moved = blob_drift(rec, blobs)
        if moved:
            p.append("proven on a different tree than this one: "
                     f"{', '.join(moved[:5])} changed since the proof")
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
