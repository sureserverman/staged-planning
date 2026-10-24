#!/usr/bin/env python3
"""Fixture tests for scripts/backlog-unify.py — the per-project `backlog unify`.

The cases that matter: candidates come from the plans in the project's records home
(found through lib/records_home.py, never a fixed path); a candidate whose Source is
already in backlog.md is never appended twice; a dry run writes nothing; and a records
home that is configured but unreachable stops the command instead of falling back to
the repo. Every fixture is synthetic and built at run time.

Stdlib only.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "backlog-unify.py"
FAILURES = []

PLAN = """# Project Plan: demo
Date: 2026-10-01

## Stage 1: work

### Task 1.1: first thing
- **Status:** [x]

### Task 1.2: second thing
- **Status:** [ ]

### Task 1.3: third thing
- **Status:** [~]

### Stage 1 Gate
- [ ] a gate check is never a backlog candidate
"""


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def env_for(cfg, xdg):
    env = dict(os.environ, XDG_CONFIG_HOME=str(xdg))
    env.pop("STAGED_PLANNING_CONFIG", None)
    if cfg is not None:
        env["STAGED_PLANNING_CONFIG"] = str(cfg)
    return env


def run(repo, env, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--project", str(repo), *args],
                          capture_output=True, text=True, env=env)


def resolver(tmp, body):
    script = tmp / "resolver.sh"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(0o755)
    cfg = tmp / "config.yaml"
    cfg.write_text(f"records_resolver: [{script}]\n")
    return cfg


def main():
    tmp = Path(tempfile.mkdtemp(prefix="backlog-unify-"))
    xdg = tmp / "xdg"
    xdg.mkdir()
    repo = tmp / "repo"
    (repo / "docs" / "plans").mkdir(parents=True)
    (repo / "docs" / "plans" / "2026-10-01-demo-plan.md").write_text(PLAN)

    print("no records configuration: the repo's docs/ is the records home")
    r = run(repo, env_for(None, xdg))
    check(r.returncode == 0 and "2 new" in r.stdout and "DRY-RUN" in r.stdout,
          f"dry run reports the two open tasks (rc={r.returncode}, {r.stdout!r} {r.stderr!r})")
    check(not (repo / "docs" / "backlog.md").exists(), "a dry run writes nothing")
    check("records go to the repo's docs/" in r.stderr and "no records resolver" not in r.stderr,
          f"an exit 3 says records go to the repo's docs/, never that no resolver exists "
          f"(a configured one can return 3) ({r.stderr!r})")
    cfg3 = resolver(tmp, "exit 3")
    r = run(repo, env_for(cfg3, xdg))
    check(r.returncode == 0 and "records go to the repo's docs/" in r.stderr
          and "no records resolver" not in r.stderr,
          f"...and a configured resolver's exit 3 says the same (rc={r.returncode}, {r.stderr!r})")
    r = run(repo, env_for(None, xdg), "--write")
    text = (repo / "docs" / "backlog.md").read_text() if (repo / "docs" / "backlog.md").exists() else ""
    check(r.returncode == 0 and text.count("\n## BL-") + text.startswith("## BL-") == 2,
          f"--write appends one BL entry per open task ({text[:300]!r})")
    check("second thing" in text and "third thing" in text and "first thing" not in text,
          "a done task is not a candidate; unexecuted and partial ones are")
    check("a gate check" not in text, "a stage-gate bullet is never a candidate")
    check("status-unexecuted" in text and "status-partial" in text, "each entry names its signal")
    before = text
    r = run(repo, env_for(None, xdg), "--write")
    after = (repo / "docs" / "backlog.md").read_text()
    check(r.returncode == 0 and after == before and "0 new" in r.stdout,
          f"a second --write is a no-op: dedup is by Source (rc={r.returncode}, {r.stdout!r})")

    print("a configured resolver moves the records home")
    home = tmp / "home"
    (home / "plans").mkdir(parents=True)
    (home / "plans" / "2026-10-02-other-plan.md").write_text(PLAN.replace("demo", "other"))
    cfg = resolver(tmp, f'echo "{home}"')
    r = run(repo, env_for(cfg, xdg), "--write")
    check(r.returncode == 0 and (home / "backlog.md").exists(),
          f"the backlog is written in the resolver's home (rc={r.returncode}, {r.stderr!r})")
    check("other-plan" in (home / "backlog.md").read_text(),
          "candidates come from the resolver's plans/, not the repo's")

    print("an unreachable records home stops, and nothing is written")
    cfg = resolver(tmp, "echo store offline >&2; exit 2")
    stamp = (repo / "docs" / "backlog.md").read_text()
    r = run(repo, env_for(cfg, xdg), "--write")
    check(r.returncode == 2 and "store offline" in r.stderr,
          f"resolver exit 2 -> exit 2 with its message (rc={r.returncode}, {r.stderr!r})")
    check((repo / "docs" / "backlog.md").read_text() == stamp, "the repo backlog is untouched")

    print("usage")
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                       env=env_for(None, xdg), cwd=str(tmp))
    check(r.returncode == 2, f"no --project outside a git repo exits 2 (rc={r.returncode})")

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S)")
        return 1
    print("\nall backlog-unify cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
