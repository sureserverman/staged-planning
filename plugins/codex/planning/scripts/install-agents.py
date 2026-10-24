#!/usr/bin/env python3
"""Install this plugin's agent roles into a Codex home; never overwrite a role.

A Codex plugin cannot ship agent roles: Codex reads them from $CODEX_HOME/agents/*.toml
($CODEX_HOME unset means ~/.codex). So the roles ship as templates in this plugin's
agents/ and this script copies them there, on request. Each role is named
`planning:<agent>` and stored as `planning-<agent>.toml`, so it cannot collide with a role
of the user's own.

Every role gets one status:
  present   the installed file is this template, byte for byte
  missing   no file there (with --install: installed, then present)
  differs   a file is there and is not this template (the user's edit, or another
            version of the plugin); it is never replaced, and --install leaves it
  refused   the path is not a regular file (a symlink, a directory, a FIFO)

  (default)   report each role's status, its sha256 and destination
  --install   install every missing role; each is written to a temporary file and
              linked into place, which fails if the name appeared meanwhile, so a role
              is either whole or absent
  --json      the same report as JSON

Exit 3 when any role differs or is refused, or when --install leaves a role anything but
present; 2 on a usage error or a broken template set; else 0 (a report listing missing
roles is a successful report). Needs Python 3.11 or later (tomllib).
"""
import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("install-agents.py needs Python 3.11 or later (it reads TOML with tomllib)")
import tomllib  # noqa: E402

ROLES = ("architecture-researcher", "claim-verifier", "code-reviewer",
         "design-handoff-reproducer", "goal-evaluator")
KEYS = ("description", "developer_instructions", "model", "model_reasoning_effort")


def status(target, data):
    """One role's status at its destination, read without following a link or blocking."""
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        return "missing"
    if not stat.S_ISREG(st.st_mode):
        return "refused"
    with open(target, "rb") as fh:
        return "present" if fh.read() == data else "differs"


def install(dest, target, data):
    """Write `data` at `target` whole or not at all; never replace an existing name."""
    fd, tmp = tempfile.mkstemp(dir=dest, prefix=".install-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, target)
    finally:
        os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--codex-home", type=Path,
                    default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    ap.add_argument("--install", action="store_true", help="install the missing roles")
    ap.add_argument("--json", action="store_true", help="report as JSON")
    args = ap.parse_args()
    source = Path(__file__).resolve().parents[1] / "agents"
    files = {f"planning-{r}.toml": r for r in ROLES}
    if not source.is_dir() or {p.name for p in source.glob("*.toml")} != set(files):
        ap.error(f"{source} must hold exactly the role templates {', '.join(sorted(files))}")
    templates = {}
    for name, role in files.items():
        path = source / name
        try:
            if path.is_symlink():
                raise ValueError("a symlink")
            data = path.read_bytes()
            doc = tomllib.loads(data.decode("utf-8"))
        except (OSError, ValueError) as e:
            ap.error(f"unreadable role template {name}: {e}")
        if doc.get("name") != f"planning:{role}" or not all(
                isinstance(doc.get(k), str) and doc[k] for k in KEYS):
            ap.error(f"role template {name} must be named planning:{role} and set {', '.join(KEYS)}")
        templates[name] = (data, doc)
    dest = args.codex_home / "agents"
    # Only the paths this script writes through are checked: a Codex home that is itself a
    # link to elsewhere (a dotfiles checkout) is the user's own layout, not an attack.
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        ap.error(f"refusing a role destination that is not a plain directory: {dest}")
    records, bad = [], 0
    for name in sorted(files):
        data, doc = templates[name]
        target = dest / name
        st = status(target, data)
        if st == "missing" and args.install:
            dest.mkdir(parents=True, exist_ok=True)
            try:
                install(dest, target, data)
            except FileExistsError:
                pass  # another writer got there first; report what is there now
            st = status(target, data)
        bad += st in ("differs", "refused")
        records.append({"name": doc["name"], "file": name, "status": st,
                        "sha256": hashlib.sha256(data).hexdigest(), "destination": str(target),
                        "model": doc["model"], "model_reasoning_effort": doc["model_reasoning_effort"]})
    if args.json:
        print(json.dumps({"roles": records}, indent=2, sort_keys=True))
    else:
        for r in records:
            print(f"{r['name']}: {r['status']}; sha256={r['sha256']}; destination={r['destination']}")
    if bad:
        print(f"install-agents: {bad} role(s) differ or are not files; they were left as they "
              "are (remove one by hand to reinstall it)", file=sys.stderr)
        return 3
    return 0 if all(r["status"] == "present" for r in records) or not args.install else 3


if __name__ == "__main__":
    sys.exit(main())
