#!/usr/bin/env python3
"""Which plugin ids each host loads, checked against what must and must not be there.

    host-status.py --host <claude|codex|cursor|opencode> | --all
                   --expect <id> [--expect <id>]... [--forbid <id>,<id>...]

An id is `<plugin>@<marketplace>`. Each host is read where it keeps its plugins, with its
home taken from the environment (HOME, CLAUDE_CONFIG_DIR, CODEX_HOME, XDG_CONFIG_HOME), so
the same code reads a throwaway home and a real one:

  claude    `claude plugin list --json`, the enabled entries
  codex     `codex plugin list`, the rows installed and enabled
  cursor    each `~/.cursor/plugins/local/*/`, by the id its `agent-plugin.json` declares
  opencode  each `opencode.json` `plugin` entry and `skills.paths` entry, by the
            `agent-plugin.json` of the package it names

Claude Code and Codex record the marketplace a plugin came from. Cursor and OpenCode do
not, and a name plus a repository URL cannot recover it (a marketplace may be published
from a repository of another name), so a package for them declares its own id. A copy that
declares none is `<name>@local`: on Cursor the plugin.json name, on OpenCode a loose copy in
the config's `skills/` of a skill a declared package ships.

An `--expect` id fails when it is missing, and when a second copy of the same plugin name
loads beside it: two copies of one plugin is the state a cutover must not leave. A
`--forbid` id fails when present. Exit 0 when every check holds, 1 when one fails, 2 on
usage or when a host cannot be read (a host CLI that will not run is never a pass).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

HOSTS = ("claude", "codex", "cursor", "opencode")
IDENT = "agent-plugin.json"


class Unreadable(Exception):
    """The host's state could not be read: exit 2."""


def _home():
    return Path(os.environ.get("HOME") or Path.home())


def _cli(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable(f"`{' '.join(argv)}` cannot run: {e}")
    if r.returncode != 0:
        raise Unreadable(f"`{' '.join(argv)}` exited {r.returncode}: "
                         f"{(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def _declared(root):
    """The id `root/agent-plugin.json` declares, or None."""
    try:
        ident = json.loads((Path(root) / IDENT).read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError, AttributeError):
        return None
    return ident if isinstance(ident, str) and "@" in ident else None


def claude():
    try:
        rows = json.loads(_cli(["claude", "plugin", "list", "--json"]))
    except ValueError as e:
        raise Unreadable(f"`claude plugin list --json` is not JSON: {e}")
    return [r["id"] for r in rows if isinstance(r, dict) and r.get("enabled") is True
            and isinstance(r.get("id"), str)]


def codex():
    out = []
    for line in _cli(["codex", "plugin", "list"]).splitlines():
        m = re.match(r"^(\S+@\S+)\s+(.+?)\s{2,}", line)
        if m and "installed" in m.group(2) and "enabled" in m.group(2) \
                and "not installed" not in m.group(2):
            out.append(m.group(1))
    return out


def cursor():
    out = []
    local = _home() / ".cursor" / "plugins" / "local"
    for d in sorted(local.iterdir()) if local.is_dir() else []:
        manifest = d / ".cursor-plugin" / "plugin.json"
        if not manifest.is_file():
            continue
        ident = _declared(d)
        if ident is None:
            try:
                name = json.loads(manifest.read_text(encoding="utf-8")).get("name")
            except (OSError, ValueError) as e:
                raise Unreadable(f"{manifest}: {e}")
            ident = f"{name or d.name}@local"
        out.append(ident)
    return out


def _package_root(path):
    """The nearest directory at or above `path` holding a package's id or manifest."""
    p = Path(path)
    for d in [p] + list(p.parents):
        if (d / IDENT).is_file() or (d / "package.json").is_file():
            return d
    return None


def opencode():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / "opencode"
    cfg_file = base / "opencode.json"
    if not cfg_file.is_file():
        return []
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"{cfg_file}: {e}")
    roots = []
    for entry in cfg.get("plugin") or []:
        if isinstance(entry, str) and entry.startswith("file://"):
            roots.append(_package_root(unquote(urlparse(entry).path)))
        elif isinstance(entry, str) and not entry.startswith(("http:", "https:")):
            roots.append(_package_root(base / "node_modules" / entry))
    paths = (cfg.get("skills") or {}).get("paths") if isinstance(cfg.get("skills"), dict) else []
    for entry in paths or []:
        if isinstance(entry, str):
            roots.append(_package_root(Path(os.path.expanduser(entry)).parent))
    out, shipped = [], {}
    for root in roots:
        ident = _declared(root) if root else None
        if ident:
            out.append(ident)
            skills = root / "skills"
            names = {s.name for s in skills.iterdir()} if skills.is_dir() else set()
            shipped.setdefault(ident.split("@")[0], set()).update(names)
    loose = base / "skills"
    present = {s.name for s in loose.iterdir()} if loose.is_dir() else set()
    for name, names in shipped.items():
        if present & names:
            out.append(f"{name}@local")
    return out


READERS = {"claude": claude, "codex": codex, "cursor": cursor, "opencode": opencode}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="host-status", description=__doc__.split("\n")[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--host")
    which.add_argument("--all", action="store_true")
    ap.add_argument("--expect", action="append", default=[], metavar="ID")
    ap.add_argument("--forbid", default="", metavar="ID,ID")
    args = ap.parse_args(argv)
    if args.host and args.host not in HOSTS:
        ap.error(f"--host must be one of {', '.join(HOSTS)}")
    forbid = [f for f in args.forbid.split(",") if f]
    problems = []
    for host in HOSTS if args.all else [args.host]:
        try:
            loaded = READERS[host]()
        except Unreadable as e:
            print(f"host-status: {host}: {e}", file=sys.stderr)
            return 2
        print(f"{host}: {', '.join(loaded) or '(nothing)'}")
        for ident in args.expect:
            name = ident.split("@")[0]
            if ident not in loaded:
                problems.append(f"{host}: {ident} missing")
            others = [i for i in loaded if i.split("@")[0] == name and i != ident]
            if ident in loaded and others:
                problems.append(f"{host}: {ident} loads beside {', '.join(others)}")
        problems += [f"{host}: {f} present" for f in forbid if f in loaded]
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
