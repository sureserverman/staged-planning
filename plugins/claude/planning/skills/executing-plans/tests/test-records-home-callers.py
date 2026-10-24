#!/usr/bin/env python3
"""Every script that reads plans finds them through lib/records_home.py.

One stub resolver names a records home outside the repo, holding a synthetic master
and sub-plan, while the repo's own docs/plans holds a decoy. Each caller is run as its
CLI and must report what is in the resolver's home, never the decoy:

  - plan-progress.py (the status-line bars) discovers the home's in-flight plan;
  - check-master-register.py, given no directory, audits the home's plans/;
  - backlog-unify.py takes its candidates from the home's plans/.

A caller that still reads the repo default while a resolver is configured fails here.
Stdlib only; every fixture is built at run time.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
PROGRESS = SKILLS / "executing-plans" / "scripts" / "plan-progress.py"
REGISTER = SKILLS / "executing-plans" / "scripts" / "check-master-register.py"
UNIFY = SKILLS / "backlog" / "scripts" / "backlog-unify.py"
FAILURES = []

MASTER = """# Master Plan: home-master
Date: 2026-10-01

## Sub-plans

### Sub-plan 1: the home sub-plan
- **Status:** [x]
- **Plan:** ./2026-10-01-home-sub-01-work-plan.md
- **Goal:** g
- **Depends on:** none
- **Blocks:** none
- **Parallel:** YES

**Gate:**
- [ ] a cross-plan check
"""

SUB = """# Project Plan: home sub-plan
Date: 2026-10-01
Master: ./2026-10-01-home-master-plan.md

## Stage 1: work

### Task 1.1: started
- **Status:** [x]

### Task 1.2: home-only open task
- **Status:** [ ]
"""

DECOY = """# Project Plan: decoy
Date: 2026-10-01

## Stage 1: work

### Task 1.1: started
- **Status:** [x]

### Task 1.2: decoy-only open task
- **Status:** [ ]
"""


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="records-callers-"))
    repo = tmp / "repo"
    (repo / "docs" / "plans").mkdir(parents=True)
    (repo / "docs" / "plans" / "2026-10-01-decoy-plan.md").write_text(DECOY)
    subprocess.run(["git", "init", "-q", "--template=", str(repo)], check=True)
    home = tmp / "home"
    (home / "plans").mkdir(parents=True)
    (home / "plans" / "2026-10-01-home-master-plan.md").write_text(MASTER)
    (home / "plans" / "2026-10-01-home-sub-01-work-plan.md").write_text(SUB)
    script = tmp / "resolver.sh"
    script.write_text(f'#!/bin/sh\necho "{home}"\n')
    script.chmod(0o755)
    cfg = tmp / "config.yaml"
    cfg.write_text(f"records_resolver: [{script}]\n")
    xdg = tmp / "xdg"
    xdg.mkdir()
    env = dict(os.environ, STAGED_PLANNING_CONFIG=str(cfg), XDG_CONFIG_HOME=str(xdg))

    print("plan-progress discovers plans in the resolver's home")
    r = subprocess.run([sys.executable, str(PROGRESS), "--json"],
                       input=json.dumps({"cwd": str(repo)}), capture_output=True, text=True,
                       env=env)
    out = r.stdout
    check(r.returncode == 0 and "home-sub-01-work" in out and "decoy" not in out,
          f"the bars come from the home, not the repo decoy (rc={r.returncode}, {out[:300]!r})")

    print("check-master-register audits the home's plans/ when given no directory")
    r = subprocess.run([sys.executable, str(REGISTER), "--project", str(repo), "--json"],
                       capture_output=True, text=True, env=env)
    try:
        findings = json.loads(r.stdout)["findings"]
    except ValueError:
        findings = None
    paths = [f["path"] for f in findings or []]
    check(findings is not None and any(str(home) in p for p in paths)
          and not any("decoy" in p for p in paths),
          f"it reports the home's unclosed sub-plan (rc={r.returncode}, {r.stdout[:300]!r} {r.stderr[:200]!r})")

    r = subprocess.run([sys.executable, str(REGISTER), str(tmp / "no-such-dir"), "--json"],
                       capture_output=True, text=True, env=env)
    check(r.returncode == 2 and "no-such-dir" in r.stderr,
          f"a plans directory that does not exist is exit 2, never a clean audit (rc={r.returncode})")
    bare = tmp / "bare-home"
    bare.mkdir()
    bscript = tmp / "bare-resolver.sh"
    bscript.write_text(f'#!/bin/sh\necho "{bare}"\n')
    bscript.chmod(0o755)
    bcfg = tmp / "bare-config.yaml"
    bcfg.write_text(f"records_resolver: [{bscript}]\n")
    r = subprocess.run([sys.executable, str(REGISTER), "--project", str(repo)],
                       capture_output=True, text=True, env=dict(env, STAGED_PLANNING_CONFIG=str(bcfg)))
    check(r.returncode == 2 and "no plans/" in r.stderr,
          f"a records home with no plans/ is exit 2, never a clean audit of nothing "
          f"(rc={r.returncode}, {r.stdout!r} {r.stderr!r})")
    r = subprocess.run([sys.executable, str(REGISTER), "--project", str(repo), "--json"],
                       capture_output=True, text=True, env=dict(env, STAGED_PLANNING_CONFIG=str(bcfg)))
    check(r.returncode == 2 and "no plans/" in r.stderr and r.stdout == "",
          f"...with --json too: the message on stderr, nothing on stdout "
          f"(rc={r.returncode}, {r.stdout!r} {r.stderr!r})")
    (bare / "plans").write_text("not a directory\n")
    r = subprocess.run([sys.executable, str(REGISTER), "--project", str(repo)],
                       capture_output=True, text=True, env=dict(env, STAGED_PLANNING_CONFIG=str(bcfg)))
    check(r.returncode == 2 and "no plans/" in r.stderr,
          f"a records home whose plans is a file is exit 2 (rc={r.returncode}, {r.stderr!r})")
    norepo = tmp / "norepo"
    norepo.mkdir()
    subprocess.run(["git", "init", "-q", "--template=", str(norepo)], check=True)
    nocfg = dict(env, XDG_CONFIG_HOME=str(xdg))
    nocfg.pop("STAGED_PLANNING_CONFIG", None)
    r = subprocess.run([sys.executable, str(REGISTER), "--project", str(norepo)],
                       capture_output=True, text=True, env=nocfg)
    check(r.returncode == 2 and "no plans/" in r.stderr,
          f"the default <repo>/docs home with no plans/ is exit 2 too (rc={r.returncode}, {r.stderr!r})")
    xcfg = tmp / "down-config.yaml"
    dscript = tmp / "down-resolver.sh"
    dscript.write_text("#!/bin/sh\necho down >&2\nexit 2\n")
    dscript.chmod(0o755)
    xcfg.write_text(f"records_resolver: [{dscript}]\n")
    r = subprocess.run([sys.executable, str(REGISTER), "--project", str(repo)],
                       capture_output=True, text=True, env=dict(env, STAGED_PLANNING_CONFIG=str(xcfg)))
    check(r.returncode == 2, f"an unreachable records home is exit 2 (rc={r.returncode})")

    print("backlog-unify takes its candidates from the home's plans/")
    r = subprocess.run([sys.executable, str(UNIFY), "--project", str(repo)],
                       capture_output=True, text=True, env=env)
    check(r.returncode == 0 and "1 new" in r.stdout,
          f"one candidate, from the home's sub-plan (rc={r.returncode}, {r.stdout!r} {r.stderr!r})")
    r = subprocess.run([sys.executable, str(UNIFY), "--project", str(repo), "--write"],
                       capture_output=True, text=True, env=env)
    written = (home / "backlog.md").read_text() if (home / "backlog.md").exists() else ""
    check("home-only open task" in written and "decoy" not in written
          and not (repo / "docs" / "backlog.md").exists(),
          "the entry is written in the home's backlog.md, and the repo's is untouched")

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S)")
        return 1
    print("\nall records-home caller cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
