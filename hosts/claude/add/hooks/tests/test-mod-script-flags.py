#!/usr/bin/env python3
"""Every script mode the planning mod runs exists in the script it runs.

The mod (planning/hooks/mod/*.ts) runs Python scripts with `$.process.run([...])`,
passing each mode as its own array element: `'--json'`, `'--inputs'`,
`'--write-sidecar'`. A grep over `plan-progress.py ... --json` text matches only
the comments that mention a mode, never the argv element that passes it, so a
sweep built on that grep passes while measuring nothing. This
suite reads the argv literals and RUNS each one against its file's own script:
a mode passes when one of the scripts that file names spells it exactly and,
run with it, exits 0 and prints JSON. A mode renamed on either side, or a
script constant moved, fails.

Run: python3 planning/hooks/tests/test-mod-script-flags.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(PLUGIN, "hooks", "mod")
# In a built plugin the scripts sit beside the mod. In this repo's source tree the mod is
# in the Claude layer (hosts/claude/add/) and the scripts it calls are in core/, which is
# what the build lays on top of each other — so the scripts are read from core/ there.
if not os.path.isdir(os.path.join(PLUGIN, "skills")):
    PLUGIN = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(PLUGIN))), "core")
    if not os.path.isdir(os.path.join(PLUGIN, "skills")):
        sys.exit(f"FAIL: no skills/ beside the mod or in {PLUGIN} — not a plugin tree")

SCRIPT_CONST = re.compile(r"""const\s+\w+\s*=\s*'((?:skills|hooks)/[^']+\.py)'""")
FLAG = re.compile(r"""'(--[a-z][a-z-]*)'""")

FAILURES = []


def check(cond, msg):
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)


def accepts(script, flag, cwd):
    """Whether the script names `flag` exactly, as a quoted literal, and `script flag`
    exits 0 and prints JSON, fed an empty JSON object. Both halves: a script whose
    default mode prints JSON for any argument would pass the run alone, and
    argparse would take an abbreviation the source never spells."""
    try:
        with open(os.path.join(PLUGIN, script), encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return False
    if f'"{flag}"' not in source and f"'{flag}'" not in source:
        return False
    try:
        r = subprocess.run([sys.executable, "-I", os.path.join(PLUGIN, script), flag],
                           input="{}", capture_output=True, text=True, timeout=30, cwd=cwd)
        json.loads(r.stdout)
        return r.returncode == 0
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return False


def sources():
    for name in sorted(os.listdir(MOD)):
        if name.endswith((".ts", ".tsx")) and ".test." not in name and name != "testing.ts":
            with open(os.path.join(MOD, name), encoding="utf-8") as fh:
                yield name, fh.read()


def main():
    seen = 0
    with tempfile.TemporaryDirectory(prefix="modflags-") as cwd:
        for name, text in sources():
            flags = sorted(set(FLAG.findall(text)))
            scripts = SCRIPT_CONST.findall(text)
            for script in scripts:
                check(os.path.isfile(os.path.join(PLUGIN, script)),
                      f"{name}: script constant {script} names a file in the plugin")
            for flag in flags:
                seen += 1
                ok = any(accepts(s, flag, cwd) for s in scripts)
                check(ok, f"{name}: {flag} is accepted by {' or '.join(scripts) or 'no script it names'}")
    # The population is non-empty: an extraction that silently finds nothing is
    # the failure this suite exists to replace.
    check(seen >= 3, f"found {seen} mode flag(s) in the mod's process.run arrays (expected at least 3)")
    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("OK — every script mode the planning mod runs is accepted by its script")
    return 0


if __name__ == "__main__":
    sys.exit(main())
