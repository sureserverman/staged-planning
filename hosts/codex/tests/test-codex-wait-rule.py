#!/usr/bin/env python3
"""Codex's "wait for the answers" rule reaches both skills that ask the owner questions.

hosts/codex/host.yaml inserts `### On Codex: wait for the answers` into brainstorming and
planning-projects with a rewrite whose pattern is anchored on a heading of each skill. The
build refuses a rewrite that changes no file, but not one that lands twice, or one whose
inserted text loses its heading. This test builds the Codex host into a scratch directory
and asserts the heading is in each built skill exactly once, naming the skill when it is
not, so the rule is checked in the output a Codex user gets rather than in the build's
own bookkeeping.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
HEADING = "### On Codex: wait for the answers"
SKILLS = ("brainstorming", "planning-projects")
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-wait-rule-")
out = os.path.join(tmp, "out")
try:
    r = subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                        "--out", out], cwd=REPO, capture_output=True, text=True)
    check(r.returncode == 0, f"the codex build succeeds ({r.stderr.strip()[-300:]})")
    if r.returncode == 0:
        for name in SKILLS:
            path = os.path.join(out, "skills", name, "SKILL.md")
            text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            n = text.count(HEADING)
            check(n == 1, f"{name}: the built Codex skill carries {HEADING!r} once (found {n})")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if FAILS:
    print(f"\n{len(FAILS)} failure(s):")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("\nOK")
