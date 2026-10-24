#!/usr/bin/env python3
"""The Codex build, from the real sources, holds what the Codex host promises.

Built to a scratch directory, so the committed plugins/codex/planning is not what is
judged: `build.py --check` already proves the committed copy equals a fresh build, and
this proves the fresh build is right.

  frontmatter  every SKILL.md opens with frontmatter that parses, whose name is its
               directory and whose description fits Codex's 120-character catalog budget
  rewrites     no Markdown file keeps ${CLAUDE_PLUGIN_ROOT} or a /planning:<skill> call
  manifest     .codex-plugin/plugin.json carries VERSION, names the hooks file, and no
               root plugin.json ships (on Codex one hides every plugin hook)
  tests        no tests, fixtures or test-fixtures directory ships
  agents       no Claude Markdown agent ships, and the stack-routing validator finds the
               TOML roles that do
  loads        every override that loads another file by path lists its core
               dependencies under depends_on in overrides.lock
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LIMIT = 120
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-build-test-")
out = os.path.join(tmp, "out")
try:
    r = subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                        "--out", out], cwd=REPO, capture_output=True, text=True)
    check(r.returncode == 0, f"the codex build succeeds ({r.stderr.strip()[-200:]})")
    skills = sorted(d for d in os.listdir(os.path.join(out, "skills")))
    check(len(skills) >= 11, f"the skills ship ({len(skills)})")
    for name in skills:
        with open(os.path.join(out, "skills", name, "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        doc = yaml.safe_load(m.group(1)) if m else None
        check(isinstance(doc, dict) and doc.get("name") == name,
              f"{name}: frontmatter parses and names its directory")
        desc = (doc or {}).get("description")
        check(isinstance(desc, str) and 0 < len(desc) <= LIMIT,
              f"{name}: description within {LIMIT} characters ({len(desc or '')})")
    md = [os.path.join(d, n) for d, _, ns in os.walk(out) for n in ns if n.endswith(".md")]
    left = [os.path.relpath(p, out) for p in md
            if re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}|(^|[^$\w/.])/planning:",
                         open(p, encoding="utf-8").read(), re.M)]
    check(not left, f"no Markdown keeps a Claude plugin path or /planning: call ({left[:5]})")
    with open(os.path.join(REPO, "VERSION")) as fh:
        version = fh.read().strip()
    with open(os.path.join(out, ".codex-plugin", "plugin.json")) as fh:
        manifest = json.load(fh)
    check(manifest.get("version") == version and manifest.get("hooks") == "./hooks/hooks.json",
          f"the manifest carries VERSION and the hooks file ({manifest.get('version')})")
    check(not os.path.exists(os.path.join(out, "plugin.json")), "no root plugin.json")
    test_dirs = [os.path.relpath(d, out) for d, _, _ in os.walk(out)
                 if os.path.basename(d) in ("tests", "fixtures", "test-fixtures")]
    check(not test_dirs, f"no test directory ships ({test_dirs[:5]})")
    md_agents = sorted(f for f in os.listdir(os.path.join(out, "agents")) if f.endswith(".md"))
    check(not md_agents, f"no Claude Markdown agent ships ({md_agents})")
    r = subprocess.run([sys.executable, "-B", os.path.join(
        out, "skills/dispatching-parallel-agents/scripts/validate-stack-routing.py")],
        capture_output=True, text=True)
    check(r.returncode == 0, f"the stack-routing validator finds the TOML roles "
          f"({(r.stdout + r.stderr).strip()[-160:]})")
    with open(os.path.join(REPO, "hosts/codex/overrides.lock")) as fh:
        lock = yaml.safe_load(fh) or {}
    ovr = os.path.join(REPO, "hosts/codex/overrides")
    unlisted = []
    for d, _, fs in os.walk(ovr):
        for f in fs:
            rel = os.path.relpath(os.path.join(d, f), ovr)
            with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                loads = "spec_from_file_location" in fh.read()
            if loads and not (lock.get(rel) or {}).get("depends_on"):
                unlisted.append(rel)
    check(not unlisted, f"every override that loads a file by path lists depends_on ({unlisted})")
finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
