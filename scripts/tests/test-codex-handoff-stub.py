#!/usr/bin/env python3
"""The Codex build's handoff writer names its session through the neutral protocol.

No Codex override touches the handoff: the writer learns its session id by running
$PLANNING_SUPERVISOR_ID_CMD, as on every host. This builds the Codex output to a scratch
dir, points that variable at a stub supervisor that prints one fixed id, and runs the
built handoff-envelope.py `ready`:

  supervised    the envelope carries "protocol": "planning-handoff" and the stub's id
  unsupervised  with the variable unset, `ready` prints `unsupervised` and writes nothing
  same file     the built script is core's, byte for byte
"""
import filecmp
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join("skills", "executing-plans", "scripts", "handoff-envelope.py")
SESSION = "stub-session-0001"
HANDOFF = "h-" + "0123456789abcdef0123"
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-handoff-stub-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    built = os.path.join(out, SCRIPT)
    check(filecmp.cmp(built, os.path.join(REPO, "core", SCRIPT), shallow=False),
          "the Codex build ships core's handoff-envelope.py unchanged")
    stub = os.path.join(tmp, "supervisor-id")
    with open(stub, "w") as fh:
        fh.write("#!/bin/sh\necho %s\n" % SESSION)
    os.chmod(stub, 0o755)
    root = os.path.join(tmp, "project")
    os.makedirs(root)
    subprocess.run(["git", "init", "-q", "--template=", root], check=True)
    plan = os.path.join(root, "p-plan.md")
    with open(plan, "w") as fh:
        fh.write("# Project Plan: stub\n")

    def ready(env_cmd):
        env = {k: v for k, v in os.environ.items() if k != "PLANNING_SUPERVISOR_ID_CMD"}
        if env_cmd is not None:
            env["PLANNING_SUPERVISOR_ID_CMD"] = env_cmd
        return subprocess.run([sys.executable, built, "ready", "--root", root, "--handoff-id",
                               HANDOFF, "--plan", plan], cwd=root, env=env,
                              capture_output=True, text=True)

    r = ready(None)
    written = glob.glob(os.path.join(root, ".claude", "handoffs", "*"))
    check(r.returncode == 0 and "unsupervised" in r.stdout and not written,
          f"unset: `ready` writes nothing ({r.stdout.strip()!r}, {len(written)} file(s))")
    r = ready(stub)
    envelopes = [p for p in glob.glob(os.path.join(root, ".claude", "handoffs", "*.json"))
                 if HANDOFF in os.path.basename(p)]
    doc = {}
    if len(envelopes) == 1:
        with open(envelopes[0]) as fh:
            doc = json.load(fh)
    check(r.returncode == 0 and doc.get("protocol") == "planning-handoff"
          and doc.get("managed_session_id") == SESSION and doc.get("event") == "HANDOFF_READY",
          f"supervised: the ready envelope names the stub's session ({r.stderr.strip()[-160:]})")
finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
