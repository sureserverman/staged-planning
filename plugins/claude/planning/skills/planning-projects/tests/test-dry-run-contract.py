#!/usr/bin/env python3
"""Structure suite for the dry run — run directly (CI convention):

    python3 core/skills/planning-projects/tests/test-dry-run-contract.py

A new Standard plan is tried before it is presented, and records what came back in its
`## Preflight` section's `**Dry run**` block; `validate-gate-checks.py --authoring` checks
the record. What it pins, in each of the four host builds:

  1. The planning-projects trunk's § Checklist — Before Presenting the Plan carries a sixth
     command-decided item, `python3 scripts/validate-gate-checks.py --authoring <plan>`
     reporting zero DRY-RUN-MISSING; its count reads "Six"; the built validator accepts
     that call (with the fixture plan for `<plan>`) and passes the fixture.
  2. The trunk's reference map routes to `references/dry-run.md`.
  3. The build ships `references/dry-run.md`; it names the block's three lines and the
     commands that are never run.
  4. The plan template carries the block, and its own example, with the placeholders
     filled as an author would, passes the built validator under `--authoring` (red if
     the template's block and the validator disagree on a label).
  5. The authoring checklist (Standard) carries the dry-run item and says "six".
  6. The trunk's § Phase 2 — Stage Breakdown states the `*(needs: …)*` note on an Outcome
     the session cannot show (the checklist and the catalog cite that section for it).
"""
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[4]
BUILDS = ["plugins/claude/planning", "plugins/codex/planning", "plugins/cursor/planning",
          "packages/opencode"]
FIXTURE = REPO / "core/skills/planning-projects/tests/fixtures/dry-run-plan.md"
FAILS = []


def check(cond, msg, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        FAILS.append(msg)
        if detail:
            print("      | " + str(detail)[:700].replace("\n", "\n      | "))


def section(text, title):
    m = re.search(rf"(?ms)^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text)
    return m.group(1) if m else ""


def fill(template):
    """The template's plan, its `[placeholders]` filled as an author would."""
    m = re.search(r"(?ms)^```markdown\n(.*?)^```\s*$", template)
    plan = m.group(1) if m else ""
    plan = plan.replace("**Risk:** LOW | MEDIUM | HIGH", "**Risk:** LOW")
    return re.sub(r"\[(?![ xX~]\])[^\]\n]*\]", "filled", plan)   # every placeholder, no checkbox


def validate(build, words):
    script = REPO / build / "skills/planning-projects/scripts/validate-gate-checks.py"
    return subprocess.run([sys.executable, str(script), *words], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


for build in BUILDS:
    root = REPO / build / "skills/planning-projects"
    trunk = (root / "SKILL.md").read_text(encoding="utf-8") if (root / "SKILL.md").is_file() else ""
    checklist = section(trunk, "Checklist — Before Presenting the Plan")
    check("Six command-decided items are restated here:" in checklist,
          f"1 {build}: the trunk's checklist restates six command-decided items")
    calls = [c for c in re.findall(r"`([^`]*validate-gate-checks\.py --authoring[^`]*)`", checklist)]
    items = [l for l in checklist.splitlines()
             if l.startswith("- [ ]") and "--authoring" in l and "zero DRY-RUN-MISSING" in l]
    check(len(calls) == 1 and len(items) == 1,
          f"1 {build}: one checklist item runs `validate-gate-checks.py --authoring <plan>` "
          f"and asks for zero DRY-RUN-MISSING", calls)
    if calls:
        words = shlex.split(calls[0])
        at = next((i for i, w in enumerate(words) if w.endswith("validate-gate-checks.py")), None)
        args = [str(FIXTURE) if w == "<plan>" else w for w in words[at + 1:]] if at is not None else []
        r = validate(build, args)
        check(at is not None and words[0] == "python3" and r.returncode == 0
              and "DRY-RUN-MISSING" not in r.stdout + r.stderr,
              f"1 {build}: the built validator accepts the trunk's call and passes the fixture",
              (args, r.returncode, (r.stdout + r.stderr)[-400:]))
    phase2 = " ".join(section(trunk, "Phase 2 — Stage Breakdown").split())
    check("*(needs:" in phase2 and "cannot show" in phase2,
          f"6 {build}: § Phase 2 states the needs: note on an Outcome the session cannot show")
    rows = [l for l in section(trunk, "Reference map").splitlines()
            if l.startswith("| `references/dry-run.md`")]
    check(len(rows) == 1, f"2 {build}: the reference map routes to references/dry-run.md")

    ref = root / "references/dry-run.md"
    text = ref.read_text(encoding="utf-8") if ref.is_file() else ""
    flat = " ".join(text.split())
    check(ref.is_file(), f"3 {build}: ships references/dry-run.md")
    check(all(f"{n}:" in text for n in ("Preflight", "Commands", "Premises"))
          and "**Dry run**" in text,
          f"3 {build}: dry-run.md names the **Dry run** block and its three lines")
    never = section(text, "What is never run")
    check(all(w in never for w in ("branch switch", "push", "install", "migration", "deploy",
                                    "5 minutes")) and "recorded as not run" in flat,
          f"3 {build}: dry-run.md names the commands that are never run, recorded as not run")

    tpath = root / "references/plan-document-template.md"
    template = tpath.read_text(encoding="utf-8") if tpath.is_file() else ""
    plan = fill(template)
    check("**Dry run**" in section(plan, "Preflight"),
          f"4 {build}: the plan template's Preflight carries the **Dry run** block")
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "2026-11-17-template-plan.md"
        p.write_text(plan, encoding="utf-8")
        r = validate(build, ["--authoring", str(p)])
        out = r.stdout + r.stderr
        check(plan.strip() and "gate check(s) across" in out and "DRY-RUN-MISSING" not in out,
              f"4 {build}: the template's own example, filled, passes --authoring",
              out[-500:])
        cut = re.sub(r"(?m)^- Premises: .*\n", "", plan)
        p.write_text(cut, encoding="utf-8")
        r = validate(build, ["--authoring", str(p)])
        check(cut != plan and "DRY-RUN-MISSING" in r.stdout + r.stderr,
              f"4 {build}: the same template with its Premises: line cut is refused",
              (r.stdout + r.stderr)[-300:])

    cl = root / "references/authoring-checklist.md"
    ctext = cl.read_text(encoding="utf-8") if cl.is_file() else ""
    standard = section(ctext, "Checklist — Standard plans")
    check("restates six of them" in ctext
          and any("--authoring" in l and "DRY-RUN-MISSING" in l and "dry-run.md" in l
                  for l in standard.splitlines() if l.startswith("- [ ]")),
          f"5 {build}: the Standard authoring checklist carries the dry-run item and says six")

print()
if FAILS:
    print(f"{len(FAILS)} failure(s)")
    sys.exit(1)
print("all checks passed")
