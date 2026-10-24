#!/usr/bin/env python3
"""No Cursor or OpenCode output names a skill the Claude way, `/planning:<skill>`.

Both hosts invoke skills by their bare names (each host.yaml's names ruling). The build
rewrote `/planning:` in core text while core text held one; once none did, the rule changed
no file and the build refuses a rule that changes nothing, so it was dropped. This check is
what stays: a `/planning:` that new core text brings in fails here instead of shipping.
It reads the committed outputs, which `build.py --check` keeps equal to their sources.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUTS = [REPO / "plugins" / "cursor" / "planning", REPO / "packages" / "opencode"]
SKIP_DIRS = {"node_modules", "test", "tests"}

hits, seen = [], 0
for out in OUTPUTS:
    if not out.is_dir():
        hits.append(f"{out.relative_to(REPO)}: missing")
        continue
    for p in sorted(out.rglob("*")):
        if not p.is_file() or SKIP_DIRS & set(p.relative_to(out).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        seen += 1
        for n, line in enumerate(text.splitlines(), 1):
            if "/planning:" in line:
                hits.append(f"{p.relative_to(REPO)}:{n}: {line.strip()[:120]}")
if hits:
    print("FAIL: Claude-style /planning:<skill> names in a bare-name host's output:")
    print("\n".join(f"  {h}" for h in hits))
    sys.exit(1)
print(f"OK — {seen} files in the Cursor and OpenCode outputs name no /planning: skill")
