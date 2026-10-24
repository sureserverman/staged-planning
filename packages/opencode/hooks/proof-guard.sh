#!/usr/bin/env bash
# proof-guard.sh — Claude Code PreToolUse hook (matcher Bash): the commit gate stays on.
#
# INERT UNLESS OPTED IN. A plugin's hooks.json hook runs for every user who enables
# the plugin; there is no per-hook opt-in, so this hook decides for itself to do
# nothing. It acts only in a repo whose git `reference-transaction` hook is the
# shim proof-hooks-install.py writes (the project opted in) AND which has a plan
# in flight (.claude/plan-progress.json, read by plan_continue_classify.read_state;
# any phase counts).
# Everywhere else it prints nothing and exits 0 — no decision at all.
#
# WHAT IT DENIES. The git ref hook (hooks/git-ref-gate.sh) refuses an unproven
# task commit by every route git has; the one way around it is to stop git running
# it. So, in a gated repo the command can reach (the payload's cwd, each `cd <dir>`,
# each `git -C <dir>`), it denies a command whose text:
#   - mentions `hooksPath`, any case — the key must be spelled out to be set;
#   - names the hook file (`reference-transaction`) or the `.git/hooks` directory;
#   - runs proof-hooks-install.py --remove — the user removes the gate, with `!`,
#     which no hook sees.
# It parses no commands beyond those text rules: a command parser is one more
# place for a hole (a quoted `;` is enough), and the ref hook does not need this guard to read a
# commit. It is a rail against an agent switching the gate off, not a sandbox:
# shell quoting or globbing (`core.hooks""Path`, `rm .git/hook[s]/*`), deleting
# .claude/plan-progress.json (no plan in flight, nothing gated — and the executor
# retains terminal v2 state; unowned legacy state may be removed at close-out) and the Write/Edit tools all get past it.
# What it buys is that the gate is never switched off by an ordinary command.
#
# IT FAILS OPEN on its own errors: a payload it cannot read, a git it cannot run.
#
# IT STEPS ASIDE UNDER CURSOR. cursor-agent runs a Claude Code plugin's hooks too, and
# its payload carries a top-level `cursor_version` key. The Cursor build of this plugin
# has its own commit gate, so a payload with that key gets no decision from this one.
set -uo pipefail
PAYLOAD="$(cat)"
# Every deny rule needs one of these strings in the command; without one, no
# Python starts — this runs on every Bash call of every user.
# bash's own match, not grep: a pipe can SIGPIPE the writer under pipefail and a here-string
# can fail to make its temp file, and either would turn a match into a miss — here, allow.
shopt -s nocasematch
[[ $PAYLOAD =~ hookspath|reference-transaction|\.git/hooks|proof-hooks-install ]] || exit 0
shopt -u nocasematch
# The payload goes on fd 3 through a pipe, not in the environment: one environment string is
# capped at 128 KiB, and an exec that fails on a larger one would allow the command.
printf '%s' "$PAYLOAD" | \
PROOF_GUARD_HOOKS="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" 2>/dev/null && pwd)" \
python3 -I - 3<&0 <<'PY' || exit 0
import json, os, re, stat, subprocess, sys
from pathlib import Path

MARK = "planning commit gate"  # in the shim proof-hooks-install.py writes
HOOK_NAME = "reference-transaction"


def none(note=None):
    if note:
        sys.stderr.write(f"proof-guard: {note}\n")
    sys.exit(0)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "plan_continue_classify",
        Path(os.environ.get("PROOF_GUARD_HOOKS", "")) / "plan_continue_classify.py")
    pcc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pcc)
except Exception as e:
    none(f"cannot load plan_continue_classify.py ({e})")
try:
    with os.fdopen(3, encoding="utf-8", errors="replace") as fh:
        payload = json.loads(fh.read() or "")
except Exception:
    none("payload is not JSON")
if not isinstance(payload, dict) or "cursor_version" in payload:
    none()
ti = payload.get("tool_input")
command = ti.get("command") if isinstance(ti, dict) else None
if not isinstance(command, str):
    none()


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True,
                          timeout=10)


# ---- every repo the command can reach (over-inclusive on purpose: a deny here
# is a reason handed to the model, never a trapped session)
cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
starts = [m.strip("\"'") for m in re.findall(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", command)]
starts += [m.strip("\"'") for m in re.findall(r"\bcd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)", command)]
starts += [cwd] if cwd else []
repos = []
for s in starts:
    p = Path(os.path.expanduser(s))
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    try:
        top = git(p, "rev-parse", "--show-toplevel")
    except Exception:
        continue
    r = Path(top.stdout.strip()) if top.returncode == 0 else None
    if r and r not in repos:
        repos.append(r)


def opted_in(repo):
    """Our shim is the repo's reference-transaction hook, in a hooks directory the
    repo owns — the installer's own tests: its second line (an altered shim is still
    a repo that opted in), and not a shared core.hooksPath, which it refuses."""
    try:
        hooks = git(repo, "rev-parse", "--git-path", "hooks").stdout.strip()
        hd = Path(hooks) if os.path.isabs(hooks) else repo / hooks
        common = git(repo, "rev-parse", "--git-common-dir").stdout.strip()
        common = Path(common) if os.path.isabs(common) else repo / common
        if not any(hd.resolve().is_relative_to(b.resolve()) for b in (repo, common)):
            return False
        with open(hd / HOOK_NAME, errors="replace") as fh:
            lines = fh.read(4096).splitlines()
        return len(lines) > 1 and lines[1].startswith(f"# {MARK} — installed by")
    except Exception:
        return False


def in_flight(repo):
    """True when the repo's state file names a plan, read by the Stop hook's own
    reader (plan_continue_classify.read_state: no symlink below the repo root is
    followed). Any phase counts, as in git-ref-gate.sh."""
    state = pcc.read_state(repo)
    if isinstance(state, dict) and state.get("state_status") == "state_error":
        sys.stderr.write("proof-guard: state_error; execution snapshot cannot establish a plan\n")
        return False
    if pcc.finished(state, repo):
        return False
    plan = state.get("plan") if isinstance(state, dict) else None
    return isinstance(plan, str) and bool(plan)


gated = [r for r in repos if opted_in(r) and in_flight(r)]
if not gated:
    none()
where = ", ".join(str(r) for r in gated)
inst = "proof-hooks-install.py"

if re.search(r"hookspath", command, re.I):
    deny(f"Denied: a plan is in flight in {where}, which opted into the proof-record commit "
         "gate, and this command mentions `hooksPath`. git must keep running the gate from the "
         "repo's own hooks directory; core.hooksPath is the one setting that would point it "
         "elsewhere. If the mention is only in a commit message or a document, reword it.")
if re.search(rf"{HOOK_NAME}|\.git/hooks", command):
    deny(f"Denied: a plan is in flight in {where}, and this command names the git "
         f"{HOOK_NAME} hook or the hooks directory — the proof-record commit gate. Prove the "
         "task with prove-claim.py instead; only the user switches the gate off.")
if inst in command and re.search(r"--remove\b", command):
    deny(f"Denied: a plan is in flight in {where}; removing the proof-record commit gate is "
         "the user's decision, not the agent's. Ask the user. They can remove it themselves "
         f"by typing `! python3 <planning>/skills/executing-plans/scripts/{inst} --remove "
         "--repo <repo>` in the prompt.")
none()
PY
exit 0
