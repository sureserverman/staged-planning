#!/usr/bin/env python3
"""Fixture tests for decisions-relevant.py — the decisions scan.

The scan reads the project's own register (`<records home>/decisions.md`, found through
lib/records_home.py) and then every further register a configured records resolver
lists for the project (`records_home.py --decision-registers`), in that order. Cases:

  - no configuration: the repo's docs/decisions.md is the register, and a project with
    none is `absent`, never an error;
  - a resolver's home and its extra registers are digested, project first;
  - superseded entries are included and marked; a malformed block is flagged, never
    dropped; a duplicate id is reported;
  - a records home that is configured but unreachable is exit 2, never an empty digest.

Every fixture is synthetic and built at run time. Stdlib only.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "decisions-relevant.py"
FAILURES = []

PROJECT_T = """# Decisions

---

## @002 — Newer rule

- **Decided:** 2026-10-02
- **Status:** accepted
- **Domains:** records
- **Source:** a plan
- **Reason:** The newer constraint. More text follows here.

## @001 — Older rule

- **Decided:** 2026-10-01
- **Status:** superseded by @002
- **Domains:** records
- **Source:** a plan
- **Reason:** What was believed before.

## @003 - a heading with a plain hyphen

- **Decided:** 2026-10-03
- **Status:** accepted
"""

EXTRA_T = """# Shared register

## @XX-001 — A rule for every project on this stack

- **Decided:** 2026-09-01
- **Status:** accepted
- **Reason:** Shared across projects.

## @XX-001 — The same id again

- **Decided:** 2026-09-02
- **Status:** accepted
- **Reason:** A collision.
"""


D = "DE" + "C-"   # built at run time so this file holds no literal register id
PROJECT = PROJECT_T.replace("@", D)
EXTRA = EXTRA_T.replace("@", D)


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def run(repo, env, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--project", str(repo), *extra],
                          capture_output=True, text=True, env=env)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="decisions-relevant-"))
    xdg = tmp / "xdg"
    xdg.mkdir()
    base = dict(os.environ, XDG_CONFIG_HOME=str(xdg))
    base.pop("STAGED_PLANNING_CONFIG", None)
    repo = tmp / "repo"
    (repo / "docs").mkdir(parents=True)

    print("no configuration")
    r = run(repo, base, "--format", "json")
    d = json.loads(r.stdout) if r.returncode == 0 else {}
    check(r.returncode == 0 and d.get("project_register") == "absent" and d.get("extra") == [],
          f"no register yet is `absent`, not an error (rc={r.returncode}, {r.stdout[:200]!r})")
    (repo / "docs" / "decisions.md").write_text(PROJECT)
    r = run(repo, base, "--format", "json")
    d = json.loads(r.stdout) if r.returncode == 0 else {"project": [], "project_register": None}
    ids = [row["id"] for row in d["project"]]
    check(d["project_register"] == "present" and ids[:2] == [D + "002", D + "001"],
          f"the repo's docs/decisions.md is digested ({ids})")
    old = [row for row in d["project"] if row["id"] == D + "001"]
    check(bool(old) and old[0]["superseded"], "a superseded entry is included and marked")
    bad = [row for row in d["project"] if row["malformed"]]
    check(len(bad) == 1 and bad[0]["id"] is None, "a malformed heading is flagged, never dropped")
    check(bool(d["project"]) and d["project"][0]["reason"] == "The newer constraint.",
          "the reason is cut to its first sentence")

    print("a configured resolver: the home's register, then the extra registers")
    home = tmp / "home"
    home.mkdir()
    (home / "decisions.md").write_text(PROJECT.replace("Newer rule", "Home rule"))
    extra = tmp / "shared.md"
    extra.write_text(EXTRA)
    script = tmp / "resolver.sh"
    script.write_text('#!/bin/sh\n'
                      'case "$*" in *--decision-registers*) echo "%s";; *) echo "%s";; esac\n'
                      % (extra, home))
    script.chmod(0o755)
    cfg = tmp / "config.yaml"
    cfg.write_text(f"records_resolver: [{script}]\n")
    env = dict(base, STAGED_PLANNING_CONFIG=str(cfg))
    r = run(repo, env, "--format", "json")
    d = json.loads(r.stdout) if r.returncode == 0 else {"project": [], "extra": []}
    check(r.returncode == 0 and bool(d["project"]) and d["project"][0]["title"] == "Home rule",
          f"the project register comes from the resolver's home (rc={r.returncode}, {r.stderr!r})")
    ex = d.get("extra", [])
    check(len(ex) == 1 and ex[0]["path"] == str(extra)
          and [row["id"] for row in ex[0]["rows"]] == [D + "XX-001", D + "XX-001"],
          f"the listed extra register is digested after it ({ex!r:.300})")
    check(bool(ex) and any("more than one block" in e for e in ex[0]["errors"]),
          "a duplicate id in an extra register is reported")
    r = run(repo, env)
    out = r.stdout
    check("Home rule" in out and "A rule for every project" in out
          and out.index("Home rule") < out.index("A rule for every project"),
          "text mode prints the project's register first, then the extras")

    print("unreachable is exit 2")
    script.write_text("#!/bin/sh\necho store offline >&2\nexit 2\n")
    r = run(repo, env)
    check(r.returncode == 2 and "store offline" in r.stderr,
          f"a configured but unreachable records home is exit 2 (rc={r.returncode})")
    script.write_text('#!/bin/sh\n'
                      'case "$*" in *--decision-registers*) echo down >&2; exit 2;; *) echo "%s";; esac\n'
                      % home)
    r = run(repo, env)
    check(r.returncode == 2, f"an unreachable extra-register listing is exit 2 (rc={r.returncode})")

    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} check(s) failed")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
