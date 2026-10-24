#!/usr/bin/env python3
"""Tests for scripts/validate-stack-routing.py's classification rules.

The live routing table holds no row that trips the FAIL branches below, so the
validator passing on it says nothing about them. Each case here is one way a row
could name something this plugin cannot dispatch while still reading as fine.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "validate-stack-routing.py")
spec = importlib.util.spec_from_file_location("vsr", SCRIPT)
vsr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vsr)

FAILURES = []
AGENTS = {"design-handoff-reproducer": "planning"}
SKILLS = {"applying-design-handoff"}


def check(cond, msg):
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)


def sev(name, skill=False):
    return vsr.classify(name, AGENTS, SKILLS, want_skill=skill)[0]


def run_table(rows):
    """Run the real validator over a throwaway plugin whose routing table is `rows`."""
    return run_doc("| Task | Subagent type | Skill |\n|---|---|---|\n" + rows)


def run_doc(doc):
    """Run the real validator over a throwaway plugin whose stack-routing.md is `doc`."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "plugin")
        skill = os.path.join(root, "skills", "applying-design-handoff")
        dpa = os.path.join(root, "skills", "dispatching-parallel-agents")
        os.makedirs(skill)
        os.makedirs(os.path.join(dpa, "references"))
        shutil.copytree(os.path.dirname(SCRIPT), os.path.join(dpa, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(root, "agents"))
        with open(os.path.join(root, "agents", "code-reviewer.md"), "w") as fh:
            fh.write("---\nname: code-reviewer\n---\n")
        for d in (skill, dpa):
            with open(os.path.join(d, "SKILL.md"), "w") as fh:
                fh.write("x\n")
        with open(os.path.join(dpa, "references", "stack-routing.md"), "w") as fh:
            fh.write(doc)
        return subprocess.run([sys.executable, os.path.join(dpa, "scripts", "validate-stack-routing.py")],
                              capture_output=True, text=True)


# A sibling plugin's id, built in parts so this file names no plugin but its own.
SIBLING = "other-plugin" + ":" + "stack-expert"
TAG = "*(optional — if installed)*"

print("validate-stack-routing — a row naming another plugin fails:")
r = run_table(f"| stack | `{SIBLING}` {TAG} | — |\n")
check(r.returncode == 1 and SIBLING in r.stdout,
      f"a planted sibling-plugin row FAILS, even tagged optional (rc={r.returncode})")
r = run_table(f"| stack | `{SIBLING}` | — |\n")
check(r.returncode == 1, f"...and untagged (rc={r.returncode})")
r = run_table(f"| stack | `general-purpose` | `stack-skill` {TAG} |\n")
check(r.returncode == 1 and "stack-skill" in r.stdout,
      f"a tag does not excuse a skill this plugin does not ship (rc={r.returncode})")
r = run_table("| review | `planning:code-reviewer` | — |\n"
              "| stack | an installed agent whose description matches the stack; otherwise "
              "`general-purpose` | the stack's skill, if one is installed |\n")
check(r.returncode == 0, f"a shipped row and the discover-or-fallback rule row pass (rc={r.returncode})")

print("validate-stack-routing — every cell of every table is scanned:")
OK_ROW = "| Task | Subagent type | Skill |\n|---|---|---|\n| review | `planning:code-reviewer` | — |\n"
r = run_doc(OK_ROW + "\nprose\n\n| Routed agent | Can run a test? | Can commit? |\n|---|---|---|\n"
            f"| `{SIBLING}` | yes | yes |\n")
check(r.returncode == 1 and SIBLING in r.stdout,
      f"an id in the capability table's first cell FAILS (rc={r.returncode})")
r = run_doc("| Task | Subagent type | Skill | Notes |\n|---|---|---|---|\n"
            f"| stack | `general-purpose` | — | `{SIBLING}` |\n")
check(r.returncode == 1 and SIBLING in r.stdout,
      f"an id in a 4th column FAILS (rc={r.returncode})")
r = run_table(f"| stack | `general-purpose`, else {SIBLING} | — |\n")
check(r.returncode == 1 and SIBLING in r.stdout,
      f"an id written without backticks FAILS (rc={r.returncode})")
r = run_table(f"| {SIBLING} work | `general-purpose` | — |\n")
check(r.returncode == 1 and SIBLING in r.stdout,
      f"an unbackticked id in the task cell FAILS (rc={r.returncode})")
r = run_doc(OK_ROW + "\n| Routed agent | Can run a test? | Can commit? |\n|---|---|---|\n"
            "| `planning:code-reviewer` | yes | **yes** — unrestricted shell |\n"
            "| an installed stack agent | only if its grant runs it | only with a shell |\n")
check(r.returncode == 0, f"a clean capability table passes (rc={r.returncode})")

print("validate-stack-routing — classification:")
check(sev("planning:design-handoff-reproducer") == "OK", "a shipped planning agent passes")
check(sev("planning:design-handof-reproducer") == "FAIL", "a planning: typo fails")
check(sev(SIBLING) == "FAIL", "another plugin's agent id fails")
check(sev("mystery-agent") == "FAIL", "a bare agent that is neither built in nor shipped fails")
check(sev("design-handoff-reproducer") == "WARN", "a bare shipped agent warns to use its namespaced form")
check(sev("general-purpose") == "OK", "a built-in passes")
check(sev("applying-design-handoff", skill=True) == "OK", "a shipped skill passes")
check(sev("stack-skill", skill=True) == "FAIL", "an unshipped skill fails")
check(sev(SIBLING, skill=True) == "FAIL", "another plugin's skill id fails")

print("validate-stack-routing — an empty sweep fails:")
with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "plugin")
    skill = os.path.join(root, "skills", "dispatching-parallel-agents")
    os.makedirs(os.path.join(skill, "references"))
    shutil.copytree(os.path.dirname(SCRIPT), os.path.join(skill, "scripts"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(root, "agents"))
    with open(os.path.join(root, "agents", "a.md"), "w") as fh:
        fh.write("---\nname: a\n---\n")
    with open(os.path.join(skill, "SKILL.md"), "w") as fh:
        fh.write("x\n")
    with open(os.path.join(skill, "references", "stack-routing.md"), "w") as fh:
        fh.write("| Task | Subagent type | Skill |\n|---|---|---|\n| x | plain words | none |\n")
    r = subprocess.run([sys.executable, os.path.join(skill, "scripts", "validate-stack-routing.py")],
                       capture_output=True, text=True)
    check(r.returncode == 1 and "empty sweep" in r.stdout,
          f"a table naming nothing exits 1 instead of passing over zero names (rc={r.returncode})")

print()
if FAILURES:
    print(f"FAIL: {len(FAILURES)} check(s) failed")
    sys.exit(1)
print("OK")
