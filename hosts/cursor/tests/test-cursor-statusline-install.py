#!/usr/bin/env python3
"""The Cursor statusline-install.py writes the ONE statusLine key in ~/.cursor/cli-config.json.

What the Cursor fork changes from core: the config file (~/.cursor/cli-config.json, not
~/.claude/settings.json); no version-pinned `sh -c` resolver, since Cursor installs a
plugin to ~/.cursor/plugins/local/<plugin> with no version segment; "checkout" judged by
the path (under .cursor/plugins/ or not) rather than by the entry being literal; and a
notice, at install, that a custom statusLine replaces the native Cursor footer.

Builds the Cursor plugin into a scratch dir and runs the BUILT installer from three
places: the build output (a checkout), a copy under $HOME/.cursor/plugins/local/planning
(an install), and a copy in a cache-shaped `plugins/cache/<m>/<p>/<version>/` tree. HOME
is a fresh scratch dir for every case, so nothing reads or writes the real one.

  install    writes {type, command} into ~/.cursor/cli-config.json and creates no
             ~/.claude; the command is a literal `bash "<chain>"` from every location,
             a cache-shaped one included; the native-footer notice goes to stderr
  checkout   from the build output it warns "installed from a checkout"; from
             ~/.cursor/plugins/local it does not
  status     not wired -> "(native Cursor footer intact)"; wired from an install -> no
             checkout line; wired from a checkout -> the checkout line
  repeat     a second install is a no-op that says so
  keys       the user's other keys survive install and remove; a user `padding` on our
             entry survives a repair, and a fresh install writes none
  foreign    another statusLine is refused without --force and left untouched
  remove     deletes our key and says the native footer returns
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REL = os.path.join("skills", "executing-plans", "scripts")
FORK = os.path.join(REPO, "hosts", "cursor", "overrides", REL, "statusline-install.py")
FAILS = []
NOTICE = "REPLACES both native Cursor footer rows"
CHECKOUT_WARN = "installed from a checkout"


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[:600].replace("\n", "\n     | "))


tmp = tempfile.mkdtemp(prefix="cursor-statusline-install-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "cursor",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith(("CURSOR_", "CLAUDE_", "PLAN_STATUSLINE"))}
    sys.dont_write_bytecode = True
    n = [0]

    def fresh_home(config=None):
        n[0] += 1
        home = os.path.join(tmp, f"home-{n[0]}")
        os.makedirs(home)
        if config is not None:
            os.makedirs(os.path.join(home, ".cursor"))
            with open(os.path.join(home, ".cursor", "cli-config.json"), "w") as fh:
                json.dump(config, fh, indent=2)
        return home

    def place(root):
        """A copy of the built plugin at `root`; returns its installer."""
        shutil.copytree(out, root)
        return os.path.join(root, REL, "statusline-install.py")

    def run(script, home, *args):
        r = subprocess.run([sys.executable, script, *args], cwd=tmp, capture_output=True,
                           text=True, env=dict(env0, HOME=home))
        return r

    def config(home):
        p = os.path.join(home, ".cursor", "cli-config.json")
        if not os.path.exists(p):
            return None
        with open(p) as fh:
            return json.load(fh)

    def chain_of(script):
        return os.path.join(os.path.dirname(script), "statusline-chain.sh")

    checkout = os.path.join(out, REL, "statusline-install.py")
    with open(checkout, "rb") as a, open(FORK, "rb") as b:
        check(a.read() == b.read(), "the built statusline-install.py is the Cursor override")

    # ---- install from an installed copy
    home = fresh_home()
    installed = place(os.path.join(home, ".cursor", "plugins", "local", "planning"))
    r = run(installed, home, "--install")
    want = {"type": "command", "command": f'bash "{chain_of(installed)}"'}
    check(r.returncode == 0 and (config(home) or {}).get("statusLine") == want,
          "--install writes {type, command} with a literal chain path into "
          "~/.cursor/cli-config.json", (r.returncode, config(home), r.stdout, r.stderr))
    check(not os.path.exists(os.path.join(home, ".claude")),
          "--install creates nothing under ~/.claude", sorted(os.listdir(home)))
    check(NOTICE in r.stderr, "--install says on stderr that the native Cursor footer is replaced",
          r.stderr)
    check(CHECKOUT_WARN not in r.stderr,
          "from ~/.cursor/plugins/local the install is not called a checkout", r.stderr)
    r = run(installed, home, "--status")
    check(r.returncode == 0 and "wired to this installer's chain script" in r.stdout
          and "(a checkout" not in r.stdout and "differs from" not in r.stdout,
          "--status on an installed entry reports it wired, current and not a checkout", r.stdout)
    r = run(installed, home, "--install")
    check(r.returncode == 0 and "already wired; nothing to do" in r.stdout
          and NOTICE not in r.stderr, "a second --install is a no-op that says so",
          (r.stdout, r.stderr))

    # ---- install from a checkout
    home = fresh_home()
    r = run(checkout, home, "--install")
    check(r.returncode == 0 and CHECKOUT_WARN in r.stderr,
          "from the build output (not under .cursor/plugins/) the install warns it is a "
          "checkout", r.stderr)
    r = run(checkout, home, "--status")
    check("(a checkout" in r.stdout, "--status on a checkout entry says so", r.stdout)

    # ---- a cache-shaped location still gets a literal path
    home = fresh_home()
    cached = place(os.path.join(tmp, "cache-root", "plugins", "cache", "example-market",
                                "planning", "1.2.3"))
    r = run(cached, home, "--install")
    cmd = ((config(home) or {}).get("statusLine") or {}).get("command", "")
    check(r.returncode == 0 and cmd == f'bash "{chain_of(cached)}"' and "sh -c" not in cmd,
          "a cache-shaped install location gets a literal `bash \"<chain>\"`, no version "
          "resolver", (r.returncode, cmd, r.stderr))

    # ---- status with nothing wired
    home = fresh_home({"editor": {"vimMode": True}})
    r = run(installed, home, "--status")
    check(r.returncode == 0 and "not wired" in r.stdout
          and "(native Cursor footer intact)" in r.stdout,
          "--status with no statusLine says the native Cursor footer is intact", r.stdout)

    # ---- the user's other keys, and their padding
    home = fresh_home({"editor": {"vimMode": True}, "permissions": {"allow": ["Shell(ls)"]}})
    r = run(installed, home, "--install")
    c = config(home) or {}
    check(r.returncode == 0 and c.get("editor") == {"vimMode": True}
          and c.get("permissions") == {"allow": ["Shell(ls)"]}
          and set(c.get("statusLine", {})) == {"type", "command"},
          "--install keeps the user's other keys and writes no padding of its own", c)
    old = {"type": "command", "padding": 2,
           "command": 'bash "/opt/old-place/statusline-chain.sh"'}
    home = fresh_home({"statusLine": old})
    r = run(installed, home, "--install")
    sl = (config(home) or {}).get("statusLine", {})
    check(r.returncode == 0 and sl.get("padding") == 2
          and sl.get("command") == f'bash "{chain_of(installed)}"' and "Repaired" in r.stdout,
          "repairing our own entry re-points it and keeps the user's padding", (sl, r.stdout))

    # ---- a statusLine this tool did not write
    foreign = {"type": "command", "command": "echo mine"}
    home = fresh_home({"statusLine": foreign})
    r = run(installed, home, "--install")
    check(r.returncode == 1 and "refusing to overwrite without --force" in r.stderr
          and (config(home) or {}).get("statusLine") == foreign,
          "a foreign statusLine is refused without --force and left as it was",
          (r.returncode, r.stderr, config(home)))
    r = run(installed, home, "--remove")
    check(r.returncode == 1 and (config(home) or {}).get("statusLine") == foreign,
          "--remove refuses a foreign statusLine without --force", (r.returncode, r.stderr))

    # ---- remove
    home = fresh_home({"editor": {"vimMode": True}})
    run(installed, home, "--install")
    r = run(installed, home, "--remove")
    c = config(home) or {}
    check(r.returncode == 0 and "statusLine" not in c and c.get("editor") == {"vimMode": True}
          and "native Cursor footer returns" in r.stdout,
          "--remove deletes our key, keeps the rest, and says the native footer returns",
          (r.returncode, c, r.stdout))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
