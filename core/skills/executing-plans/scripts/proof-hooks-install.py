#!/usr/bin/env python3
"""proof-hooks-install.py — opt one project into the proof-record commit gate.

    python3 proof-hooks-install.py --install | --status | --remove --repo R

Installs, reports or removes a shim in R's git hooks directory that execs the
plugin's `hooks/git-ref-gate.sh` as git's `reference-transaction` hook: from then
on, while a plan is in flight in R, a commit whose subject names one of its tasks
lands only with valid prove-claim.py records for the claims the plan requires.

WHY OPT-IN, PER PROJECT. A plugin's hooks.json reaches every user who enables the
plugin; a gate that refuses commits must not. So the gate is a git hook, written
into one repo by this script when the user runs it, and nothing runs it by
default.

WHERE THE SHIM GOES. `git rev-parse --git-path hooks`, which honours
core.hooksPath and linked worktrees — the directory git will actually run from.
A hooks directory outside the repo (a global or shared core.hooksPath) is
refused: a shim there would opt in every repo that uses it. The shim execs the
hook by absolute path, so it follows the plugin copy that
installed it. When that copy is gone (a plugin update can move it), the shim lets
every update through and SAYS the gate is off on each one, rather than blocking
every ref update in the repo or going quiet; `--status` reports it and re-running
`--install` re-points it.

WHAT IT WILL NOT DO. It refuses to replace a `reference-transaction` hook that is
not its own (chain it by hand instead), and `--remove` deletes only its own shim.
"Installed" means ours, executable (git skips a hook without its exec bit) AND
byte-identical to what this script writes (an edited shim proves nothing).
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# <plugin-root>/skills/executing-plans/scripts/ -> the plugin root is the directory that
# holds skills/, found by name rather than by a fixed depth.
PLUGIN_ROOT = next(p for p in Path(__file__).resolve().parents if p.name == "skills").parent
GIT_HOOK = PLUGIN_ROOT / "hooks" / "git-ref-gate.sh"
HOOK_NAME = "reference-transaction"
SHIM_MARK = "planning commit gate"

_STALE = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"


def _warn_if_stale():
    # A stale cached copy would point the shim at an older plugin's hook.
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass


def die(msg, code=1):
    print(f"proof-hooks-install: {msg}", file=sys.stderr)
    sys.exit(code)


def shim_text():
    q = str(GIT_HOOK).replace("'", "'\\''")
    return ("#!/bin/sh\n"
            f"# {SHIM_MARK} — installed by proof-hooks-install.py --install --repo; "
            "remove with --remove --repo\n"
            f"if [ ! -x '{q}' ]; then\n"
            f"  echo \"{SHIM_MARK}: '{q}' is missing — the commit gate is OFF; "
            "re-run proof-hooks-install.py --install --repo\" >&2\n"
            "  exit 0\n"
            "fi\n"
            f"exec '{q}' \"$@\"\n")


def repo_hook(repo):
    r = Path(repo).resolve()
    top = subprocess.run(["git", "-C", str(r), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        die(f"{r} is not a git work tree")
    hooks = subprocess.run(["git", "-C", str(r), "rev-parse", "--git-path", "hooks"],
                           capture_output=True, text=True).stdout.strip()
    hd = Path(hooks) if os.path.isabs(hooks) else r / hooks
    top = Path(top.stdout.strip())
    common = subprocess.run(["git", "-C", str(r), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    common = Path(common) if os.path.isabs(common) else r / common
    if not any(within(hd, base) for base in (top, common)):
        die(f"{hd}, git's hooks directory for {top}, is outside the repo (a shared or "
            "global core.hooksPath); a shim there would opt in every repo that uses it. "
            "Refusing. Give this repo its own core.hooksPath, then re-run.")
    return top, hd, hd / HOOK_NAME


def within(path, base):
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


SHIM_LINE2 = f"# {SHIM_MARK} — installed by proof-hooks-install.py"


def shim_is_ours(hook):
    """Our shim's own second line — not the marker anywhere, which a foreign hook
    that merely mentions the gate would match, and be overwritten or deleted."""
    try:
        lines = hook.read_text(errors="replace")[:4096].splitlines()
    except OSError:
        return False
    return len(lines) > 1 and lines[1].startswith(SHIM_LINE2)


def shim_is_current(hook):
    """Ours AND effective: executable and byte-identical to what we write."""
    try:
        return os.access(hook, os.X_OK) and hook.read_text(errors="replace") == shim_text()
    except OSError:
        return False


def status(repo):
    top, _hd, hook = repo_hook(repo)
    if shim_is_ours(hook) and not shim_is_current(hook):
        print(f"not installed — {hook} is ours but altered, re-pointed or not executable; "
              "re-run --install")
        return 1
    if shim_is_ours(hook):
        print(f"installed — git {HOOK_NAME} hook in {top} ({hook})")
        if not GIT_HOOK.exists():
            print(f"  ! {GIT_HOOK} does not exist — the shim lets every update through")
            return 1
        return 0
    if hook.exists() or hook.is_symlink():
        print(f"not installed — {hook} is another {HOOK_NAME} hook (not ours, left alone)")
    else:
        print(f"not installed — no {HOOK_NAME} hook in {top}")
    return 1


def install(repo):
    top, hd, hook = repo_hook(repo)
    if hook.exists() or hook.is_symlink():
        if not shim_is_ours(hook):
            die(f"{hook} already exists and is not ours; refusing to replace it. Chain it "
                f"by hand (call {GIT_HOOK} from it with the same argument and stdin) or move "
                "it, then re-run.")
        if shim_is_current(hook):
            print(f"already installed — {hook} unchanged")
            return 0
    hd.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=hd, prefix=f".{HOOK_NAME}-")
    try:
        with os.fdopen(fd, "w") as out:
            out.write(shim_text())
        os.chmod(tmp, 0o755)
        os.replace(tmp, hook)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        die(f"cannot write {hook}: {e}")
    print(f"installed — git {HOOK_NAME} hook in {top}")
    print(f"  {hook} -> {GIT_HOOK}")
    if not GIT_HOOK.exists():
        print(f"  ! warning: {GIT_HOOK} does not exist — the gate is off until it does",
              file=sys.stderr)
    return 0


def remove(repo):
    top, _hd, hook = repo_hook(repo)
    if not shim_is_ours(hook):
        print(f"nothing to remove — no planning {HOOK_NAME} hook in {top}")
        return 0
    hook.unlink()
    print(f"removed — git {HOOK_NAME} hook from {top}")
    return 0


def main():
    _warn_if_stale()
    # allow_abbrev=False: `--rem` would otherwise run --remove past the PreToolUse
    # guard, which matches the full flag.
    ap = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Opt one project repo into the proof-record commit gate "
                    "(a git reference-transaction hook).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--install", action="store_true", help="write our shim")
    g.add_argument("--status", action="store_true",
                   help="report whether the shim is installed (exit 0 installed, 1 not)")
    g.add_argument("--remove", action="store_true", help="delete our shim, only ours")
    ap.add_argument("--repo", required=True, help="the project repo to act on")
    args = ap.parse_args()
    if args.install:
        return install(args.repo)
    if args.remove:
        return remove(args.repo)
    return status(args.repo)


if __name__ == "__main__":
    sys.exit(main())
