#!/usr/bin/env python3
"""Every public entry point warns when it runs from a superseded plugin cache.

Two halves, because either alone can pass while measuring nothing:

  - a SWEEP over every `def main(` script under the plugin's skills: each is either
    wired (it loads lib/staleness.py and calls warn_if_stale) or listed as not wired,
    with a reason. A new entry point that is neither fails here, so the list cannot
    silently fall behind the code.
  - a RUN of every wired script from a cache-shaped copy of the plugin, behind a
    checkout that advertises a newer version: each must print the warning on stderr,
    even when it then refuses its arguments.

Stdlib only; every fixture is built at run time.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
MARKET = "example-market"
FAILURES = []

WIRED = [
    ("backlog", "backlog-unify.py"),
    ("decisions", "decisions-relevant.py"),
    ("executing-plans", "check-master-register.py"),
    ("executing-plans", "handoff-envelope.py"),
    ("executing-plans", "plan-flip-audit.py"),
    ("executing-plans", "stage-brief.py"),
    ("executing-plans", "proof-hooks-install.py"),
    ("executing-plans", "prove-claim.py"),
    ("executing-plans", "review-ledger-check.py"),
]

NOT_WIRED = {
    ("executing-plans", "plan-state.py"):
        "stdin protocol CLI over a validated owning worktree; its stdout is a parsed JSON "
        "receipt and it reads no records home",
    ("executing-plans", "evaluation-ledger.py"):
        "immutable evidence CLI over an explicit local ledger; its stdout is parsed JSON "
        "and it reads no records home",
    ("executing-plans", "plan-progress.py"):
        "status-line renderer: runs on every prompt render, where a warning is noise on "
        "every keystroke",
    ("executing-plans", "statusline-install.py"): "one-shot installer, run by hand",
    ("executing-plans", "context-usage.py"):
        "reads the session transcript; its stdout is parsed JSON at every gate",
    ("planning-projects", "validate-gate-checks.py"): "validator over the plan paths it is given",
    ("planning-projects", "validate-dispatch.py"): "validator over the plan paths it is given",
    ("dispatching-parallel-agents", "validate-stack-routing.py"): "validator over in-repo tables",
    ("applying-design-handoff", "validate-handoff-pack.py"): "validator over a handoff pack path",
    ("project-maturity", "audit-detectors.py"): "detector library run against a repo path",
}


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def sweep():
    print("sweep — every entry point is wired or listed with a reason:")
    found = set()
    for d in sorted((PLUGIN / "skills").glob("*/scripts")):
        skill = d.parent.name
        for p in sorted(d.glob("*.py")):
            if p.name.startswith("_"):
                continue
            if re.search(r"^def main\(", p.read_text(encoding="utf-8", errors="replace"), re.M):
                found.add((skill, p.name))
    listed = set(WIRED) | set(NOT_WIRED)
    check(not (found - listed), f"no unlisted entry point (unlisted: {sorted(found - listed) or 'none'})")
    check(not (listed - found), f"no stale listing (gone: {sorted(listed - found) or 'none'})")
    for skill, name in WIRED:
        text = (PLUGIN / "skills" / skill / "scripts" / name).read_text(encoding="utf-8", errors="replace")
        check("warn_if_stale" in text and '"lib"' in text and "staleness.py" in text,
              f"{skill}/{name} loads lib/staleness.py and calls warn_if_stale")


def run_from_cache():
    print("run — each wired script warns from a stale cache, even on a refused run:")
    tmp = Path(tempfile.mkdtemp(prefix="stale-wiring-"))
    cache = tmp / "plugins" / "cache" / MARKET / "planning" / "0.0.1"
    shutil.copytree(PLUGIN, cache, ignore=shutil.ignore_patterns("tests", "__pycache__", "node_modules"))
    checkout = tmp / "checkout"
    (checkout / ".claude-plugin").mkdir(parents=True)
    (checkout / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": MARKET, "plugins": [{"name": "planning", "version": "9.9.9"}]}))
    env = dict(os.environ, STAGED_PLANNING_CHECKOUT=str(checkout), HOME=str(tmp / "home"),
               XDG_CONFIG_HOME=str(tmp / "xdg"))
    env.pop("STAGED_PLANNING_NO_STALE_WARNING", None)
    env.pop("STAGED_PLANNING_CONFIG", None)
    for skill, name in WIRED:
        script = cache / "skills" / skill / "scripts" / name
        r = subprocess.run([sys.executable, str(script), "--no-such-flag-xyz"],
                           capture_output=True, text=True, env=env, cwd=str(tmp), timeout=60)
        check("from the plugin cache" in r.stderr,
              f"{skill}/{name} warns (rc={r.returncode}, stderr={r.stderr[:160]!r})")
    env["STAGED_PLANNING_NO_STALE_WARNING"] = "1"
    r = subprocess.run([sys.executable, str(cache / "skills" / "executing-plans" / "scripts"
                                            / "prove-claim.py"), "--no-such-flag-xyz"],
                       capture_output=True, text=True, env=env, cwd=str(tmp), timeout=60)
    check("from the plugin cache" not in r.stderr, "the opt-out silences it")
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    sweep()
    run_from_cache()
    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
