#!/usr/bin/env python3
"""Install this repo's built plugin into a host and check what the host loaded.

Each host has its own harness under hosts/<host>/qualify/; this script picks one by
--host. There is none for `claude`.
  - codex: qualify.py's `needs_model: false` cases install from this checkout's
    .agents/plugins/marketplace.json, compare the host's skill and hook discovery with
    the build's output, install the agent roles, then disable, remove and unregister. No
    model turn runs, and no hook is trusted.
  - cursor: copies plugins/cursor/planning into the scratch HOME's
    .cursor/plugins/local/planning, then three headless model turns: the skills and agents
    the session lists against the build's, the backlog skill by name, and one subagent
    launch that must log one dispatch line per tool_use_id. It needs the Cursor login
    (--credentials, default the invoking user's ~/.config/cursor/auth.json).
  - opencode: copies packages/opencode into the scratch HOME and loads it by local path
    from opencode.json; compares OpenCode's own skill, agent and command listings (no
    model) with the build's, then runs the backlog skill by name with --model. It needs
    the OpenCode login (--credentials, default the invoking user's
    ~/.local/share/opencode/auth.json) and --model.

--isolated makes a scratch HOME (and, on Codex, CODEX_HOME) under the system temp dir, runs
there, and deletes it on a normal exit, an error, Ctrl-C, TERM or HUP (not on SIGKILL).
  - Codex: the scratch dir holds no credentials. qualify.py gives every codex call that HOME
    and CODEX_HOME and only PATH, the locale, TERM and TMPDIR from this environment, and
    fingerprints the invoking user's Codex home (config.toml, agents/, plugins/) before and
    after; a change fails the run.
  - Cursor and OpenCode: the model turns need the login, so qualify.py copies the login file
    into the scratch HOME for the run and removes it when the run ends (a SIGKILL leaves it,
    and --keep keeps the dir without it). Every host call gets HOME, TERM=dumb and only PATH,
    the locale and TMPDIR from this environment, and the invoking user's host config is
    fingerprinted before and after.
The plugin installs from this checkout's working tree, not its last commit. Without --isolated
the script refuses: a check that installs and removes plugins does not run in a real
profile.

  --host codex --isolated [--plugin-id ID] [--extra-marketplace DIR --extra-plugin ID]...
                          [--evidence DIR] [--keep]
  --host cursor --isolated [--extra-marketplace DIR --extra-plugin NAME]... [--credentials F]
                           [--model ID] [--evidence DIR] [--keep]
  --host opencode --isolated --model ID [--extra-marketplace DIR --extra-plugin NAME]...
                             [--credentials F] [--evidence DIR] [--keep]

--extra-marketplace/--extra-plugin add a second plugin from another checkout, by argument.
On Cursor and OpenCode the DIR is that plugin's built output and NAME its install name.
--evidence writes DIR/results.json (and, on Cursor and OpenCode, the transcripts); it records
scratch and checkout paths as they are, so qualify.py refuses a DIR inside this repo or inside
the git checkout that holds any plugin. --keep leaves the scratch dir in place and prints its path.

Exit 0 when every case passed, 1 when one failed, 2 on a usage error or an input the
harness cannot judge.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QUALIFY = {h: REPO / "hosts" / h / "qualify" / "qualify.py" for h in ("codex", "cursor", "opencode")}
BUILT = {"cursor": (REPO / "plugins/cursor/planning", "planning"),
         "opencode": (REPO / "packages/opencode", "opencode-staged-planning")}


def owner_codex_home():
    """The Codex home the invoking environment uses: $CODEX_HOME, else ~/.codex."""
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", required=True)
    ap.add_argument("--isolated", action="store_true")
    ap.add_argument("--plugin-id", default="planning@staged-planning")
    ap.add_argument("--extra-marketplace", action="append", default=[])
    ap.add_argument("--extra-plugin", action="append", default=[])
    ap.add_argument("--evidence")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--credentials")
    ap.add_argument("--model")
    ap.add_argument("--codex", default="codex", help=argparse.SUPPRESS)
    ap.add_argument("--bin", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.host not in ("claude", "codex", "cursor", "opencode"):
        ap.error("--host must be claude, codex, cursor or opencode")
    if args.host not in QUALIFY:
        print(f"host-install-check: --host {args.host}: no install harness for this host yet",
              file=sys.stderr)
        return 2
    if not args.isolated:
        print("host-install-check: refusing to install into a real profile; pass --isolated",
              file=sys.stderr)
        return 2
    if len(args.extra_marketplace) != len(args.extra_plugin):
        ap.error("each --extra-marketplace needs one --extra-plugin")

    def stop(signum, _frame):
        raise SystemExit(128 + signum)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    if args.host == "opencode" and not args.model:
        ap.error("--host opencode needs --model: with none, the default model can be one the "
                 "provider has retired")
    scratch = Path(tempfile.mkdtemp(prefix="host-install-check-"))
    home = scratch / "home"
    if args.host == "codex":
        owner = owner_codex_home()
        codex = str(Path(args.codex).absolute()) if os.sep in args.codex else args.codex
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True)
        cmd = [sys.executable, str(QUALIFY[args.host]), "--run", "--codex-home", str(codex_home),
               "--workdir", str(scratch / "work"), "--marketplace", str(REPO),
               "--plugin-id", args.plugin_id, "--owner-codex-home", str(owner),
               "--codex", codex]
        for market, ident in zip(args.extra_marketplace, args.extra_plugin):
            cmd += ["--extra-marketplace", str(Path(market).absolute()), "--extra-plugin", ident]
    else:
        # The harness refuses the invoking user's own HOME and hashes their host config.
        home.mkdir(parents=True)
        out, name = BUILT[args.host]
        cmd = [sys.executable, str(QUALIFY[args.host]), "--run", "--home", str(home),
               "--workdir", str(scratch / "work"), "--plugin", str(out), name,
               "--owner-home", str(Path.home())]
        for market, ident in zip(args.extra_marketplace, args.extra_plugin):
            cmd += ["--plugin", str(Path(market).absolute()), ident]
        for flag, val in (("--credentials", args.credentials), ("--model", args.model),
                          ("--bin", args.bin and str(Path(args.bin).absolute()))):
            if val:
                cmd += [flag, val if flag != "--credentials" else str(Path(val).absolute())]
    if args.evidence:
        cmd += ["--evidence", str(Path(args.evidence).absolute())]
    # qualify.py reads the invoking environment to know whose home to refuse, and sets
    # HOME (and CODEX_HOME on Codex) itself for every host call.
    try:
        return subprocess.run(cmd, cwd=scratch).returncode
    finally:
        if args.keep:
            print(f"host-install-check: scratch kept at {scratch}", file=sys.stderr)
        else:
            shutil.rmtree(scratch, ignore_errors=True)
            if scratch.exists():
                print(f"host-install-check: could not delete {scratch}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
