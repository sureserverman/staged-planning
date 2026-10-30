#!/usr/bin/env bash
# commit-gate.sh — Cursor `beforeShellExecution` hook: the proof-record git hook stays on.
#
# WHY THIS EXISTS. A `Stage N green` commit needs prove-claim.py records for every claim
# of every task of stage N, and the check that enforces it is git's
# `reference-transaction` hook (hooks/git-ref-gate.sh): git runs it whenever a ref moves,
# whatever command moved it — `--no-verify`, `-n`, `commit-tree` + `update-ref`,
# cherry-pick and merge included (measured on git 2.43). The ways around it are to point
# git at another hooks directory (`core.hooksPath`), to remove the hook file, or never to
# install it. This hook closes those three while a plan is in flight.
#
# It parses no commands: a parse of shell text has holes (a quoted `;` splits a message
# and hides what follows). While a plan is in flight (.claude/plan-progress.json, read by
# plan_continue_classify.read_state: no symlink below the repo root is followed; in a
# linked worktree with none, the main worktree's — run_root) in any
# repo the command can reach — each `git -C <dir>`, each `cd <dir>`, the payload's `cwd`
# and `workspace_roots` — it denies:
#   - a command whose text mentions `hooksPath`, in any case, anywhere: the key must be
#     spelled out to be set, so no parse is needed to see it;
#   - a command that names the hook file (`hooks/reference-transaction`), other than the
#     installer;
#   - the installer's `--remove`: switching the gate off is the user's decision, made in
#     their own terminal;
#   - any git command while the planning shim is not installed — executable,
#     byte-identical to what the installer writes, in a hooks directory the repo owns (a
#     shared core.hooksPath gates other repos too) — naming the command that installs it.
#     This is what makes proof on by default.
# In every repo the command can reach, plan in flight or not, it denies a `git … commit`
# while a prove-claim.py run is in progress (its lock held: it may have a break applied)
# or an interrupted run's journal is left (its break may still be in the tree), because
# `git commit -a` would carry the break. Only prove-claim takes that lock or writes that
# journal (plan_continue_classify.live_proof_break).
# With no plan in flight (no execution state, an untrusted one, no plan named, or the
# named plan gone) it denies one thing more: a git commit whose text names `Stage N green`,
# because a stage closed with no state could never be checked. Everything else is allowed.
# A snapshot the gate cannot read or that names another branch (`state_error`, which a
# detached HEAD gives in a worktree whose run started on a branch) and a finished run
# are not "no plan": the gate allows them, so a new plan started after a finished one
# is ungated until `plan-state.py init` records it.
# A message that merely mentions hooksPath is denied too; the deny says why. These are
# text rules, a rail and not a sandbox: a command that hides a word from them (a glob,
# split quoting, an interpreter's -c, a message read from a file) is not seen; where the git
# hook is installed it still checks every `Stage N green` commit, and with no plan in flight
# nothing requires it to be.
#
# THE ANSWER. beforeShellExecution is a permission hook: every exit prints JSON,
# {"permission":"allow"} or {"permission":"deny","user_message":…,"agent_message":…}.
#
# IT FAILS OPEN on its own errors —
# with one exception:
# when the install check's git calls error or time out, it cannot tell whether the shim
# is installed, and denies as "not installed". CURSOR_COMMIT_GATE=0 disables it — set in
# Cursor's environment, which the agent's commands do not reach.
set -uo pipefail
allow() { printf '{"permission":"allow"}\n'; exit 0; }
PAYLOAD="$(cat)"
[[ "${CURSOR_COMMIT_GATE:-1}" == "0" ]] && allow
command -v python3 >/dev/null 2>&1 || allow
HOOK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" 2>/dev/null && pwd)"
# -I (isolated): `python3 -` otherwise puts the cwd first on sys.path. The payload goes on
# fd 3 through a pipe: one environment string is capped at 128 KiB, and an exec that fails
# on a larger one would allow the command.
# pipefail off here: a writer cut short by SIGPIPE must not add a second answer.
set +o pipefail
printf '%s' "$PAYLOAD" | COMMIT_GATE_HOOKS="${HOOK_DIR:-}" python3 -I - 3<&0 <<'PY' || allow
import importlib.util, json, os, re, subprocess, sys
from pathlib import Path

HOOK_NAME = "reference-transaction"
HOOKS = Path(os.environ.get("COMMIT_GATE_HOOKS", ""))
INSTALLER = HOOKS.parent / "scripts" / "hooks-install.py"


def allow(note=None):
    if note:
        sys.stderr.write(f"commit-gate: {note}\n")
    print(json.dumps({"permission": "allow"}))
    sys.exit(0)


def deny(user, agent):
    print(json.dumps({"permission": "deny", "user_message": user, "agent_message": agent}))
    sys.exit(0)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.dont_write_bytecode = True
try:
    pcc = load("plan_continue_classify", HOOKS / "plan_continue_classify.py")
except Exception as e:
    allow(f"cannot load plan_continue_classify.py ({e}); allowing")
try:
    with os.fdopen(3, encoding="utf-8", errors="replace") as fh:
        payload = json.loads(fh.read() or "{}")
except Exception:
    allow("payload is not JSON; allowing")
if not isinstance(payload, dict):
    allow()
command = payload.get("command")
if not isinstance(command, str):
    ti = payload.get("tool_input")
    command = ti.get("command") if isinstance(ti, dict) else None
if not isinstance(command, str):
    allow()


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True,
                          timeout=10)


# ---- every repo the command can reach (over-inclusive on purpose: a deny here is a
# message to the agent, never a trapped session)
cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else None
starts = [m.strip("\"'") for m in re.findall(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", command)]
starts += [m.strip("\"'") for m in re.findall(r"\bcd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)", command)]
starts += [cwd] if cwd else []
roots = payload.get("workspace_roots")
starts += [r for r in roots if isinstance(r, str)] if isinstance(roots, list) else []
base = cwd or next((r for r in starts if os.path.isabs(r)), None)
repos = []
for s in starts:
    p = Path(os.path.expanduser(s))
    if not p.is_absolute() and base:
        p = Path(base) / p
    try:
        top = git(p, "rev-parse", "--show-toplevel")
    except Exception:
        continue
    r = Path(top.stdout.strip()) if top.returncode == 0 else None
    if r and r not in repos:
        repos.append(r)


if pcc.mentions_git_commit(command):
    for r in repos:
        try:
            live = pcc.live_proof_break(r)
        except Exception:
            continue
        if live:
            deny("Command blocked: a prove-claim.py run may have a break applied in this repo.",
                 f"This command was denied because it commits in {r}, and {live}")


UNREADABLE = []  # main worktrees' state files present but unreadable, named in the deny


def run_root(repo):
    """The worktree whose run gates `repo`, its state, and whether that state is the main
    worktree's unreadable one. .claude/plan-progress.json is git-ignored, so each worktree
    has its own: the repo's own run first, and only when it has none in flight (no state, or
    a finished run) the main worktree's — the parent of the common git directory when that
    is named `.git` (git-worktree(1)), as git-ref-gate.sh reads it."""
    state = pcc.read_state(repo)
    if isinstance(state, dict) and state.get("state_status") == "state_error":
        return repo, state, False
    if state is not None and not pcc.finished(state, repo):
        return repo, state, False
    try:
        r = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    except Exception:
        return repo, state, False
    common = Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    if common is None or common.name != ".git" or common.parent.resolve() == repo.resolve():
        return repo, state, False  # the main worktree itself, or a bare repository's linked one
    main = common.parent
    main_state = pcc.read_state(main)
    path = main / ".claude" / "plan-progress.json"
    if (main_state is None and os.path.lexists(path)) or (
            isinstance(main_state, dict) and main_state.get("state_status") == "state_error"):
        if str(path) not in UNREADABLE:
            UNREADABLE.append(str(path))
        return repo, None, True
    if main_state is None or pcc.finished(main_state, main):
        return repo, state, False
    return main, main_state, False


def in_flight(repo):
    """True when the repo's state file names a plan that is not finished — the main
    worktree's when a linked worktree has none (run_root). Any phase counts, as in
    git-ref-gate.sh."""
    root, state, _ = run_root(repo)
    if isinstance(state, dict) and state.get("state_status") == "state_error":
        return False
    if pcc.finished(state, root):
        return False
    plan = state.get("plan") if isinstance(state, dict) else None
    return isinstance(plan, str) and bool(plan)


def unstated(repo):
    """True when no execution state names a plan: none, an untrusted one, no plan named,
    or the named plan gone — or the main worktree's state, read for a linked worktree with
    none, present but unreadable. A state_error and a finished plan are not this case."""
    root, state, unreadable = run_root(repo)
    if unreadable:
        return True
    if isinstance(state, dict) and state.get("state_status") == "state_error":
        return False
    if pcc.finished(state, root):
        return False
    plan = state.get("plan") if isinstance(state, dict) else None
    if not isinstance(plan, str) or not plan:
        return True
    return not (Path(plan) if os.path.isabs(plan) else root / plan).is_file()


# A git commit whose text names `Stage N green`: the plan convention's stage close.
STAGE_GREEN_COMMIT = re.compile(r"\bgit\b.*\bcommit\b.*\bstage\s+\d+\s+green\b", re.I | re.S)

gated = [r for r in repos if in_flight(r)]
if not gated:
    if STAGE_GREEN_COMMIT.search(command) and any(unstated(r) for r in repos):
        deny("Command blocked: a Stage N green commit with no plan in flight.",
             "This command was denied because it commits `Stage N green` while no execution "
             "state names a plan in this repo, so the stage could never be checked"
             + "".join(f" ({p} is present but unreadable or untrusted)" for p in UNREADABLE)
             + ". Record "
             "the run first — `python3 <planning-plugin>/skills/executing-plans/scripts/"
             "plan-state.py init` (executing-plans § Progress state file) — and commit "
             "again; if this commit closes no plan's stage, reword its subject.")
    allow()
installer = "hooks-install.py" in command

if re.search(r"hookspath", command, re.I):
    deny("Command blocked: a plan is in flight and this command mentions core.hooksPath.",
         "This command was denied because it mentions `hooksPath`. While a plan is in flight, "
         "git must run the proof-record hook from the repo's own hooks directory, and "
         "core.hooksPath is the one setting that would point git elsewhere. If the mention is "
         "only in a commit message or a document, reword it.")
if re.search(r"hooks/" + HOOK_NAME, command) and not installer:
    deny("Command blocked: a plan is in flight and this command touches the git hook.",
         f"This command was denied because it names the git {HOOK_NAME} hook, which checks "
         "proof records on every Stage N green commit while a plan is in flight. Manage it "
         f"only with python3 {INSTALLER} --install|--status|--remove --repo <repo>.")
if installer and re.search(r"--remove\b", command):
    deny("Command blocked: a plan is in flight; removing the commit gate is the user's decision.",
         "This command was denied because it removes the planning commit gate while a plan is "
         "in flight. Switching the gate off is the user's decision, not the agent's. Ask the "
         "user; they can run it in their own terminal:\n"
         f"  python3 {INSTALLER} --remove --repo <repo>")
if re.search(r"\bgit\b", command) and not installer:
    # "Installed" is the installer's own test: executable and byte-identical to the shim
    # it writes. The marker alone passes an edited or non-executable file.
    try:
        hi = load("hooks_install", INSTALLER)
    except Exception as e:
        allow(f"cannot load {INSTALLER} ({e}); allowing")
    for r in gated:
        hook = None
        try:
            hooks = git(r, "rev-parse", "--git-path", "hooks").stdout.strip()
            hook = Path(hooks) if os.path.isabs(hooks) else r / hooks
            common = git(r, "rev-parse", "--git-common-dir").stdout.strip()
            common = Path(common) if os.path.isabs(common) else r / common
            # A hooks directory the repo owns, as the installer requires: a shared one
            # gates other repos too, and the installer refuses to write there.
            owned = any(hi.within(hook, b) for b in (r, common))
            ours = owned and hi.shim_is_current(hook / HOOK_NAME)
        except Exception:
            owned, ours = True, False
        if not owned:
            deny("Command blocked: this repo's git hooks directory is shared, so the commit "
                 "gate cannot be installed here.",
                 f"A plan is in flight in {r}, but git's hooks directory for it, {hook}, is "
                 "outside the repo (a shared or global core.hooksPath). The installer refuses "
                 "to write there, because a shim in it would gate every repo that uses it. "
                 "Ask the user to choose one of: give this repo its own core.hooksPath (then "
                 "run the install command below), or start Cursor with CURSOR_COMMIT_GATE=0 "
                 "to run this plan without the commit gate.\n"
                 f"  python3 {INSTALLER} --install --repo {r}")
        if not ours:
            deny("Command blocked: the proof-record git hook is not installed in this repo.",
                 f"A plan is in flight in {r}, but its git {HOOK_NAME} hook is not the planning "
                 "commit gate, so its Stage N green commit would not be checked for proof "
                 f"records. Install it, then run the command again:\n"
                 f"  python3 {INSTALLER} --install --repo {r}\n"
                 "If another reference-transaction hook is already there, the installer "
                 "refuses and says so: ask the user.")
allow()
PY
exit 0
