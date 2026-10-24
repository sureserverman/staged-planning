#!/usr/bin/env python3
"""hooks-install.py — the planning hooks on Cursor: check their wiring, clear entries an
older installer left in ~/.cursor/hooks.json, and install the proof-record git hook in a
project.

    python3 <plugin>/scripts/hooks-install.py --status | --install | --remove [--dry-run] [--home DIR]
    python3 <plugin>/scripts/hooks-install.py --status | --install | --remove --repo R

WHERE THE HOOKS RUN. Every planning hook ships on the plugin route, in this plugin's
hooks/hooks.json, which Cursor runs wherever the plugin is installed: the plan-continue
hook, the commit gate and the dispatch log. An entry for the same script in the user's
~/.cursor/hooks.json runs beside the plugin's, so one call fires twice (measured; see
hosts/cursor/host.yaml in the source repo). So this script writes NO user entries:

  --install   removes planning entries an older installer wrote to ~/.cursor/hooks.json
              (only those whose command is one of this plugin's hook scripts, in this
              plugin's hooks folder or a local plugin folder named `planning`), and
              writes nothing else there;
  --status    reports the plugin's own wiring and any such leftover entries
              (exit 0 when the plugin's hooks.json wires all three and nothing is left
              over, 1 otherwise);
  --remove    the same clean-up as --install;
  --dry-run   prints what --install or --remove would change and writes nothing;
  --home DIR  reads DIR/.cursor/hooks.json instead of the user's (for tests).

The user's hooks.json is shared with other tools and the user's own hooks. A file this
script cannot parse, or whose shape it does not recognise, makes it exit 1 without
writing; anything it rewrites is backed up beside it first, and its mode is kept.

THE GIT HOOK (--repo R). The proof-record check runs as git's `reference-transaction`
hook (hooks/git-ref-gate.sh), which refuses a `Stage N green` commit without a proof
record for every claim of every task of stage N. --install --repo writes a shim into R's
git hooks directory (`git rev-parse --git-path hooks`) that execs this plugin's
git-ref-gate.sh by absolute path; while a plan is in flight, the commit gate denies git
commands in a repo without it. The shim lets every update through, and says the gate is
OFF, when the plugin copy it points at is gone. A hooks directory outside the repo (a
shared core.hooksPath) is refused, as is replacing a `reference-transaction` hook that is
not this installer's.

Every path is resolved from this file's own plugin folder, never a fixed install path.
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# <plugin>/scripts/hooks-install.py: the plugin root is one up.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = PLUGIN_ROOT / "hooks"
# The scripts the plugin's hooks.json wires. None of them is written to the user's file.
SCRIPTS = ("plan-continue.sh", "commit-gate.sh", "dispatch-log.sh")
# The local plugin folder an older installer's entries pointed into.
OLD_PLUGIN_NAME = "planning"


def die(msg, code=1):
    print(f"hooks-install: {msg}", file=sys.stderr)
    sys.exit(code)


def config_path(home):
    return Path(home) / ".cursor" / "hooks.json"


def our_dirs(home):
    """Every hooks folder an entry of ours can point into, as given and resolved."""
    dirs = {HOOKS_DIR, Path(home) / ".cursor" / "plugins" / "local" / OLD_PLUGIN_NAME / "hooks"}
    out = set()
    for d in dirs:
        out.add(str(d))
        try:
            out.add(str(d.resolve()))
        except OSError:
            pass
    return out


def is_ours(entry, home):
    """True only for an entry whose command is one of this plugin's hook scripts INSIDE a
    hooks folder this plugin owns. It decides what is deleted from a shared file, so it
    goes by location, never by file name alone: another vendor's `hooks/commit-gate.sh`
    is not ours."""
    if not isinstance(entry, dict):
        return False
    cmd = entry.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    path = Path(cmd.strip().strip("\"'"))
    if path.name not in SCRIPTS or not path.is_absolute():
        return False
    dirs = our_dirs(home)
    if str(path.parent) in dirs:
        return True
    try:
        return str(path.parent.resolve()) in dirs
    except OSError:
        return False


def load(path):
    """(data, existed). Any shape this cannot safely edit exits 1 WITHOUT writing."""
    if not path.exists():
        return {"version": 1, "hooks": {}}, False
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        die(f"cannot read {path}: {e}")
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON ({e}); refusing to touch it. Fix or move the file "
            "and re-run.")
    if not isinstance(data, dict):
        die(f"{path} must be a JSON object, found {type(data).__name__}; refusing to touch it.")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        die(f"{path}: `hooks` must be an object, found {type(hooks).__name__}; refusing to "
            "touch it.")
    for name, entries in hooks.items():
        if not isinstance(entries, list):
            die(f"{path}: `hooks.{name}` must be an array, found {type(entries).__name__}; "
                "refusing to touch it.")
    return data, True


def detect_indent(path, default=2):
    try:
        for line in path.read_text().splitlines()[1:]:
            stripped = line.lstrip(" ")
            if stripped and stripped != line:
                return len(line) - len(stripped)
    except OSError:
        pass
    return default


def write(path, data, indent):
    """Atomic replace through a symlink to its target, with a timestamped backup and the
    file's own mode kept."""
    if path.is_symlink():
        try:
            path = Path(os.path.realpath(path))
        except OSError as e:
            die(f"cannot resolve symlink {path}: {e}")
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_suffix(f".json.bak-{stamp}"))
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".hooks-", suffix=".json")
    except OSError as e:
        die(f"cannot back up or replace {path}: {e}")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=indent)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        die(f"cannot write {path}: {e}")


def leftovers(data, home):
    """[(event, entry)] for every planning entry an older installer left."""
    return [(ev, e) for ev, entries in sorted((data.get("hooks") or {}).items())
            for e in entries if is_ours(e, home)]


def plugin_wiring():
    """{script: [event, ...]} from this plugin's own hooks/hooks.json, or None."""
    try:
        doc = json.loads((HOOKS_DIR / "hooks.json").read_text())
        out = {}
        for ev, entries in doc["hooks"].items():
            for e in entries:
                name = Path(str(e.get("command", ""))).name
                out.setdefault(name, []).append(ev)
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def cmd_status(home):
    path = config_path(home)
    data, _ = load(path)
    wiring = plugin_wiring()
    ok = True
    if wiring is None:
        print(f"! {HOOKS_DIR / 'hooks.json'} is missing or unreadable — reinstall the plugin")
        ok = False
    else:
        for s in SCRIPTS:
            evs = wiring.get(s)
            if evs:
                print(f"plugin route — {s} on {', '.join(evs)}")
            else:
                print(f"! plugin route — {s} is not wired in {HOOKS_DIR / 'hooks.json'}")
                ok = False
            if not (HOOKS_DIR / s).is_file():
                print(f"! {HOOKS_DIR / s} does not exist")
                ok = False
    left = leftovers(data, home)
    if left:
        ok = False
        print(f"! {len(left)} planning entr{'y' if len(left) == 1 else 'ies'} left in {path} "
              "beside the plugin's own, so each runs twice — `--install` removes them:")
        for ev, e in left:
            print(f"  - {ev}: {e.get('command')}")
    else:
        print(f"no planning entries in {path}")
    return 0 if ok else 1


def cmd_clean(home, dry_run, verb):
    path = config_path(home)
    data, existed = load(path)
    left = leftovers(data, home) if existed else []
    if dry_run:
        print(f"hooks-install: dry run, nothing written — {path}")
        print("  user entries to write: none (every planning hook runs from the plugin's "
              "hooks/hooks.json)")
        if left:
            print("  entries an older installer left, to remove:")
            for ev, e in left:
                print(f"    - {ev}: {e.get('command')}")
        else:
            print("  entries an older installer left, to remove: none")
        return 0
    if verb == "install":
        print("no user entries to write: every planning hook runs from the plugin's "
              "hooks/hooks.json")
    if not left:
        print(f"nothing to remove — no planning entries in {path}")
        return 0
    hooks = data["hooks"]
    for ev in {ev for ev, _ in left}:
        kept = [e for e in hooks[ev] if not is_ours(e, home)]
        if kept:
            hooks[ev] = kept
        else:
            hooks.pop(ev)   # no empty array left behind in someone else's config
    write(path, data, detect_indent(path))
    for ev, e in left:
        print(f"removed — `{ev}` entry {e.get('command')} from {path}")
    return 0


# ---------------------------------------------------------------- git hook
GIT_HOOK = HOOKS_DIR / "git-ref-gate.sh"
HOOK_NAME = "reference-transaction"
SHIM_MARK = "planning commit gate"
SHIM_LINE2 = f"# {SHIM_MARK} — installed by hooks-install.py"


def shim_text():
    q = str(GIT_HOOK).replace("'", "'\\''")
    return ("#!/bin/sh\n"
            f"{SHIM_LINE2} --install --repo; remove with --remove --repo\n"
            f"if [ ! -x '{q}' ]; then\n"
            f"  echo \"{SHIM_MARK}: '{q}' is missing — the commit gate is OFF; "
            "re-run hooks-install.py --install --repo\" >&2\n"
            "  exit 0\n"
            "fi\n"
            f"exec '{q}' \"$@\"\n")


def within(path, base):
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def shim_is_ours(hook):
    """This installer's own second line — not the marker anywhere, which a foreign hook
    that merely mentions the gate would match."""
    try:
        lines = hook.read_text(errors="replace")[:4096].splitlines()
    except OSError:
        return False
    return len(lines) > 1 and lines[1].startswith(SHIM_LINE2)


def shim_is_current(hook):
    """Ours AND effective: executable (git skips a hook without its exec bit) and
    byte-identical to what this installer writes (an edited shim proves nothing)."""
    try:
        return os.access(hook, os.X_OK) and hook.read_text(errors="replace") == shim_text()
    except OSError:
        return False


def repo_hook(repo):
    r = Path(repo).resolve()
    top = subprocess.run(["git", "-C", str(r), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        die(f"{r} is not a git work tree")
    top = Path(top.stdout.strip())
    hooks = subprocess.run(["git", "-C", str(r), "rev-parse", "--git-path", "hooks"],
                           capture_output=True, text=True).stdout.strip()
    hd = Path(hooks) if os.path.isabs(hooks) else r / hooks
    common = subprocess.run(["git", "-C", str(r), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    common = Path(common) if os.path.isabs(common) else r / common
    if not any(within(hd, base) for base in (top, common)):
        die(f"{hd}, git's hooks directory for {top}, is outside the repo (a shared or global "
            "core.hooksPath); a shim there would gate every repo that uses it. Refusing. Give "
            "this repo its own core.hooksPath, then re-run.")
    return top, hd, hd / HOOK_NAME


def git_status(repo):
    top, _hd, hook = repo_hook(repo)
    if shim_is_ours(hook) and not shim_is_current(hook):
        print(f"not installed — {hook} is ours but altered or not executable; re-run --install")
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


def git_install(repo):
    top, hd, hook = repo_hook(repo)
    if hook.exists() or hook.is_symlink():
        if not shim_is_ours(hook):
            die(f"{hook} already exists and is not ours; refusing to replace it. Chain it by "
                f"hand (call {GIT_HOOK} from it with the same argument and stdin) or move it, "
                "then re-run.")
        if shim_is_current(hook):
            print(f"already installed — {hook} unchanged")
            return 0
    hd.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=hd, prefix=f".{HOOK_NAME}-")
    with os.fdopen(fd, "w") as out:
        out.write(shim_text())
    os.chmod(tmp, 0o755)
    os.replace(tmp, hook)
    print(f"installed — git {HOOK_NAME} hook in {top}")
    print(f"  {hook} -> {GIT_HOOK}")
    return 0


def git_remove(repo):
    top, _hd, hook = repo_hook(repo)
    if not shim_is_ours(hook):
        print(f"nothing to remove — no planning {HOOK_NAME} hook in {top}")
        return 0
    hook.unlink()
    print(f"removed — git {HOOK_NAME} hook from {top}")
    return 0


def main():
    # allow_abbrev=False: `--rem` would otherwise run --remove past commit-gate.sh, which
    # matches the full flag.
    ap = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Check the planning hooks' wiring on Cursor and clear entries an older "
                    "installer left in ~/.cursor/hooks.json; with --repo, install the "
                    "proof-record git reference-transaction hook in one project repo.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true",
                   help="clear leftover planning entries; write no user entries")
    g.add_argument("--status", action="store_true",
                   help="report the wiring (exit 0 clean, 1 not)")
    g.add_argument("--remove", action="store_true", help="clear leftover planning entries")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what --install or --remove would change; write nothing")
    ap.add_argument("--home", help="the home folder whose .cursor/hooks.json is read "
                                   "(default: the user's)")
    ap.add_argument("--repo", help="act on this repo's git reference-transaction hook instead")
    args = ap.parse_args()
    if not (args.install or args.status or args.remove or args.dry_run):
        ap.error("one of --install, --status, --remove or --dry-run is required")
    home = Path(args.home) if args.home else Path(os.path.expanduser("~"))
    if args.repo:
        if args.dry_run:
            ap.error("--dry-run does not apply to --repo")
        if args.install:
            return git_install(args.repo)
        if args.remove:
            return git_remove(args.repo)
        return git_status(args.repo)
    if args.status:
        return cmd_status(home)
    return cmd_clean(home, args.dry_run, "remove" if args.remove else "install")


if __name__ == "__main__":
    sys.exit(main())
