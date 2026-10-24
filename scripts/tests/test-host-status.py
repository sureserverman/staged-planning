#!/usr/bin/env python3
"""Fixture tests for scripts/host-status.py.

Four fixture homes, one per host. Each loads `planning@staged-planning`; a second case on
each adds a copy the gate must not miss. On Claude Code and Codex the host names its
source, so the second copy is `planning@example-market` and `--forbid` catches it. On Cursor
and OpenCode no marketplace is recorded, so a copy that declares no id reads
`planning@local`, and `--expect planning@staged-planning` fails on the duplicate. Every id
here is invented. Stdlib only.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "host-status.py")
OURS = "planning@staged-planning"
FAILURES = []


def check(cond, msg, detail=""):
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)
        if detail:
            print(f"        | {str(detail)[:600]}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def fake_bin(root, name, out_file):
    """A fake host CLI that prints a file for `plugin list` and fails for anything else."""
    path = os.path.join(root, "bin", name)
    write(path, "#!/bin/sh\n"
                f'[ "$1 $2" = "plugin list" ] || exit 2\ncat "{out_file}"\n')
    os.chmod(path, 0o755)


def run(root, *args):
    env = {"PATH": os.path.join(root, "bin") + os.pathsep + "/usr/bin:/bin",
           "HOME": os.path.join(root, "home"),
           "CLAUDE_CONFIG_DIR": os.path.join(root, "home", ".claude"),
           "CODEX_HOME": os.path.join(root, "home", ".codex")}
    r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                       env=env, timeout=60)
    return r.returncode, r.stdout + r.stderr


def claude_home(root, ids):
    out = os.path.join(root, "claude-list.json")
    write(out, json.dumps([{"id": i, "enabled": True, "scope": "user"} for i in ids]
                          + [{"id": "off@other-market", "enabled": False, "scope": "user"}]))
    fake_bin(root, "claude", out)


def codex_home(root, ids):
    out = os.path.join(root, "codex-list.txt")
    rows = "".join(f"{i:<30} installed, enabled  1.0.0  /src/{i}\n" for i in ids)
    write(out, "Marketplace `example`\n\nPLUGIN                         STATUS              VERSION  SOURCE\n"
               + rows + f"{'gone@example':<30} not installed       1.0.0  remote\n")
    fake_bin(root, "codex", out)


def package(root, rel, ident, skills=("executing-plans",)):
    base = os.path.join(root, rel)
    if ident:
        write(os.path.join(base, "agent-plugin.json"), json.dumps({"id": ident}))
    for s in skills:
        write(os.path.join(base, "skills", s, "SKILL.md"), f"---\nname: {s}\n---\n")
    return base


def cursor_home(root, copies):
    for name, ident in copies:
        base = package(root, f"home/.cursor/plugins/local/{name}", ident)
        write(os.path.join(base, ".cursor-plugin", "plugin.json"),
              json.dumps({"name": name.split("-")[0], "version": "1.0.0"}))


def opencode_home(root, loose_copy):
    pkg = package(root, "pkgs/planning-oc", OURS)
    write(os.path.join(pkg, "package.json"), json.dumps({"name": "opencode-example"}))
    write(os.path.join(pkg, "src", "index.ts"), "export default {}\n")
    extra = package(root, "pkgs/extra", "extra@example-tools", skills=("extra-skill",))
    cfg = {"plugin": [f"file://{pkg}/src/index.ts"],
           "skills": {"paths": [os.path.join(extra, "skills")]}}
    write(os.path.join(root, "home", ".config", "opencode", "opencode.json"), json.dumps(cfg))
    if loose_copy:
        write(os.path.join(root, "home", ".config", "opencode", "skills", "executing-plans",
                           "SKILL.md"), "---\nname: executing-plans\n---\n")


def case(host, setup):
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "home"))
        setup(root)
        return {
            "expect": run(root, "--host", host, "--expect", OURS),
            "forbid": run(root, "--host", host, "--expect", OURS, "--forbid",
                          "planning@example-market,planning@local"),
        }


print("host-status — which plugin ids each host loads")
for host, clean, dirty in [
    ("claude", lambda r: claude_home(r, [OURS]),
     lambda r: claude_home(r, [OURS, "planning@example-market"])),
    ("codex", lambda r: codex_home(r, [OURS]),
     lambda r: codex_home(r, [OURS, "planning@example-market"])),
    ("cursor", lambda r: cursor_home(r, [("planning", OURS)]),
     lambda r: cursor_home(r, [("planning", OURS), ("planning-old", None)])),
    ("opencode", lambda r: opencode_home(r, False), lambda r: opencode_home(r, True)),
]:
    c = case(host, clean)
    check(c["expect"][0] == 0 and OURS in c["expect"][1],
          f"{host}: the plugin it loads is reported and --expect passes", c["expect"])
    check(c["forbid"][0] == 0, f"{host}: --forbid of an id it does not load passes", c["forbid"])
    d = case(host, dirty)
    if host in ("claude", "codex"):
        check(d["forbid"][0] == 1 and "planning@example-market" in d["forbid"][1],
              f"{host}: --forbid names a second copy from another marketplace", d["forbid"])
    else:
        check(d["expect"][0] == 1 and "planning@local" in d["expect"][1],
              f"{host}: a copy that declares no id reads planning@local and fails --expect "
              "as a duplicate", d["expect"])

with tempfile.TemporaryDirectory() as root:
    os.makedirs(os.path.join(root, "home"))
    rc, out = run(root, "--host", "cursor", "--expect", OURS)
    check(rc == 1 and "missing" in out, "an expected id a host does not load is reported missing",
          out)
    claude_home(root, [OURS])
    rc, out = run(root, "--host", "claude", "--expect", OURS, "--expect", "extra@example-tools")
    check(rc == 1 and "extra@example-tools" in out, "every --expect is checked, not the first",
          out)
    rc, out = run(root, "--host", "nonesuch", "--expect", OURS)
    check(rc == 2, "an unknown host is a usage error (exit 2)", out)
    os.remove(os.path.join(root, "bin", "claude"))
    rc, out = run(root, "--host", "claude", "--expect", OURS)
    check(rc == 2 and "claude" in out, "a host CLI that cannot run is exit 2, never a pass", out)

if FAILURES:
    print(f"\n{len(FAILURES)} failure(s)")
    sys.exit(1)
print("\nall passed")
