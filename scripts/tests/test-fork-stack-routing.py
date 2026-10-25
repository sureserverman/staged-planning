#!/usr/bin/env python3
"""Every host fork of validate-stack-routing.py runs against its own build.

The validator checks that the routing table names only agents and skills its plugin
ships. A host fork of it is meant to run in that host's build output (its source folder
holds only the files the host overrides), so this suite builds each forked host into a
scratch dir and runs the built copy there. Core's copy runs from scripts/run-tests.sh and
Codex's from hosts/codex/tests/test-codex-build.py; this covers every other fork, found by
listing hosts/*/overrides, so a fork added later is run without editing this file.

  each fork   the built validator exits 0 on its own build
  break       a table row naming an agent the build does not ship exits non-zero
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REL = "skills/dispatching-parallel-agents/scripts/validate-stack-routing.py"
TABLE = "skills/dispatching-parallel-agents/references/stack-routing.md"
COVERED_ELSEWHERE = {"codex"}
FAILS = []


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[-600:].replace("\n", "\n     | "))


hosts = sorted(os.path.relpath(p, os.path.join(REPO, "hosts")).split(os.sep)[0] for p in
               glob.glob(os.path.join(REPO, "hosts", "*", "overrides", REL)))
hosts = [h for h in hosts if h not in COVERED_ELSEWHERE]
check(bool(hosts), f"at least one host fork to run ({hosts})")

tmp = tempfile.mkdtemp(prefix="fork-stack-routing-")
try:
    for host in hosts:
        out = os.path.join(tmp, host)
        b = subprocess.run([sys.executable, "-B", os.path.join(REPO, "build", "build.py"),
                            "--host", host, "--no-lock-check", "--out", out],
                           cwd=REPO, capture_output=True, text=True)
        if b.returncode != 0:
            check(False, f"{host}: the build succeeds", b.stdout + b.stderr)
            continue
        r = subprocess.run([sys.executable, "-B", os.path.join(out, REL)],
                           capture_output=True, text=True)
        check(r.returncode == 0, f"{host}: the built validator passes its own table",
              r.stdout + r.stderr)
        table = os.path.join(out, TABLE)
        with open(table) as fh:
            text = fh.read()
        sep = text.index("\n|---")
        row_at = text.index("\n", sep + 1) + 1
        with open(table, "w") as fh:
            fh.write(text[:row_at] + "| Example stack | `example-missing-agent` | — |\n"
                     + text[row_at:])
        r = subprocess.run([sys.executable, "-B", os.path.join(out, REL)],
                           capture_output=True, text=True)
        check(r.returncode != 0, f"{host}: a row naming an agent the build lacks fails it",
              r.stdout + r.stderr)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if FAILS else 0)
