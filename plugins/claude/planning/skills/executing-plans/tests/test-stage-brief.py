#!/usr/bin/env python3
"""Fixture suite for stage-brief.py — run directly:

    python3 core/skills/executing-plans/tests/test-stage-brief.py

WHAT THIS SUITE IS REALLY GUARDING. The skeleton stage-brief.py writes and the
check the git hook runs (plan-flip-audit's demo_problems / premise_problems) are
two halves of one contract. If they drift, an evaluator that fills the report in
exactly as told is refused at `Stage N green` — or a report that skips an Outcome
is let through. So every case here fills a generated skeleton the way the brief
says, and asks the hook's own check.
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "stage-brief.py"
spec = importlib.util.spec_from_file_location("pfa", HERE.parent / "scripts" / "plan-flip-audit.py")
PFA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PFA)

passed = failed = 0


def ok(msg):
    global passed
    passed += 1
    print(f"  ok    {msg}")


def bad(msg, detail=""):
    global failed
    failed += 1
    print(f"  FAIL  {msg}")
    if detail:
        print("        | " + str(detail)[:600].replace("\n", "\n        | "))


PLAN = """# Plan

## Stage 2: share

**Goal:** A user can share a cleaned copy from any app.
**Outcomes:** *(added at execution, 2026-10-05)* the user, via another app's share sheet
- Works: the chooser opens with a cleaned copy another app can read.
- A file that is too large → the user sees "file too large" and nothing is shared.
**Risk:** MEDIUM — depends on the sending app's grant.

### Task 2.1: share target
- **Status:** [ ]
- Cleans the shared file.
- **Test:** `true` — it cleans (red if it does not)

## Stage 3: none

**Goal:** Internal refactor.
**Risk:** LOW — nothing user-facing.
"""


def run(*args, repo):
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", str(repo)],
                          capture_output=True, text=True)


def fill(report, verdict="holds", evidence="$ probe.sh share ... -> readable, 0 GPS tags"):
    out = []
    for line in report.splitlines():
        if line.startswith("Verdict:"):
            line = f"Verdict: {verdict}"
        out.append(line)
        if line.startswith("Evidence:"):
            out.append(evidence)
    return "\n".join(out) + "\n"


print("stage-brief.py")
tmp = Path(tempfile.mkdtemp(prefix="stage-brief-"))
plan = tmp / "2026-10-05-x-plan.md"
plan.write_text(PLAN)
repo = tmp / "repo"
repo.mkdir()
(repo / "settings.gradle.kts").write_text("")
outcomes = PFA.stage_outcomes(PLAN, 2)
base = repo / "proof" / plan.stem / "stage-2"

# The Outcomes the hook will hold the report to, with the derivation note stripped.
if outcomes == ["Works: the chooser opens with a cleaned copy another app can read.",
                "A file that is too large → the user sees \"file too large\" and nothing is shared."]:
    ok("stage_outcomes reads the bullets, not the note or the who-line")
else:
    bad("stage_outcomes", outcomes)

r = run("demo", "--plan", str(plan), "--stage", "2", repo=repo)
report = (base / "demo.md").read_text() if (base / "demo.md").is_file() else ""
if r.returncode == 0 and report:
    ok("demo writes the report skeleton")
else:
    bad("demo must write the skeleton", r.stderr)

# Catches: an evaluator told to dispatch "exactly as printed" that gets no background-work rules.
if ("by its own completion" in r.stdout and "finished or been stopped" in r.stdout):
    ok("the printed brief carries both background-work rules")
else:
    bad("the printed brief must carry both background-work rules", r.stdout[-300:])

# Catches: a skeleton the hook rejects even when filled in exactly as told.
probs = PFA.demo_problems(fill(report), outcomes)
if not probs:
    ok("the skeleton, filled in as the brief says, passes the hook's check")
else:
    bad("a correctly filled skeleton must pass", probs)

# Catches: an Outcome dropped from the report.
dropped = "\n".join(l for l in fill(report).split("## Outcome 2")[0].splitlines()) + "\n"
if any("Outcome 2: no section" in x for x in PFA.demo_problems(dropped, outcomes)):
    ok("a report missing an Outcome's section does not pass")
else:
    bad("a dropped Outcome must be reported", PFA.demo_problems(dropped, outcomes))

# Catches: the brief's who-line carrying the plan's derivation note.
if "added at execution" not in r.stdout:
    ok("the brief's who-line has the derivation note stripped")
else:
    bad("note leaked into the brief")

# Catches: an unfilled skeleton passing.
if PFA.demo_problems(report, outcomes):
    ok("the untouched skeleton does not pass")
else:
    bad("an empty report must not pass")

# Catches: the brief not carrying the plan's Outcomes word for word, or offering a fallback.
brief = r.stdout
if all(o in brief for o in outcomes) and "do not substitute a test" in brief and "probe app" in brief:
    ok("the brief quotes every Outcome, forbids a test stand-in, and sends Android to a probe app")
else:
    bad("brief content", brief[:800])

# Catches: a brief that names one host's install path or one sibling plugin. The probe
# is found by discovery: an installed stage-verify skill whose description matches.
if "~/." not in brief and "android-" not in brief and "stage-verify skill" in brief:
    ok("the brief finds the probe by discovery, naming no install path or sibling plugin")
else:
    bad("host path in the brief", brief[:800])

# Catches: an existing report overwritten (an evaluator's results lost).
(base / "demo.md").write_text("KEEP")
run("demo", "--plan", str(plan), "--stage", "2", repo=repo)
if (base / "demo.md").read_text() == "KEEP":
    ok("an existing report is never overwritten")
else:
    bad("demo overwrote an existing report")

r = run("premise", "--plan", str(plan), "--stage", "2", repo=repo)
prem = (base / "premise.md").read_text() if (base / "premise.md").is_file() else ""
if r.returncode == 0 and "Risk: MEDIUM" in prem and all(o in prem for o in outcomes):
    ok("premise writes a worksheet carrying the Goal, Risk and Outcomes")
else:
    bad("premise worksheet", r.stderr + prem[:400])

if PFA.premise_problems(prem):
    ok("the blank worksheet does not pass")
else:
    bad("a blank worksheet must not pass")

filled = prem.replace("Assumption: ", "Assumption: other apps grant read access when sharing") \
             .replace("Checked: ", "Checked: `probe.sh share ... --no-grant` and with a grant") \
             .replace("Result: ", "Result: with a grant the share target reads it") \
             .replace("Verdict: ", "Verdict: not checkable here — no device attached")
if not PFA.premise_problems(filled):
    ok("a filled worksheet passes, 'not checkable here — <why>' included")
else:
    bad("a filled worksheet must pass", PFA.premise_problems(filled))

# Catches: an empty worksheet, and "not checkable here" with no reason.
if PFA.premise_problems("# nothing here\n"):
    ok("a worksheet with no premise entry does not pass")
else:
    bad("an empty worksheet must not pass")
noreason = filled.replace("Verdict: not checkable here — no device attached", "Verdict: not checkable here")
if PFA.premise_problems(noreason):
    ok("'not checkable here' without a reason does not pass")
else:
    bad("a bare 'not checkable here' must not pass")

# Catches: an unchecked premise not reaching the demo brief.
(base / "premise.md").write_text(filled)
(base / "demo.md").unlink()
r = run("demo", "--plan", str(plan), "--stage", "2", repo=repo)
if "Premises not checked yet: other apps grant read access when sharing" in r.stdout:
    ok("a premise not checkable at Step 3.0 is handed to the demo")
else:
    bad("unchecked premises must reach the brief", r.stdout[:600])

# Catches: a brief for a stage with nothing to demo.
r = run("demo", "--plan", str(plan), "--stage", "3", repo=repo)
if r.returncode == 2 and "no **Outcomes:**" in r.stderr:
    ok("a stage without Outcomes gets no brief, and is told to derive them")
else:
    bad("no-Outcomes stage", (r.returncode, r.stderr))

# Outcome drift: the worksheet's Outcomes against the plan's, owner words on a bullet.
recorded = "Outcomes:\n- Works: a.\n- B fails → c.\n\n## Premise 1\n"
plan_reworded = ("## Stage 2: s\n\n**Goal:** g\n**Outcomes:** u\n- Works: a.\n"
                 "- B fails → d. *(amended 2026-10-06 — owner, 2026-10-06: \"say d\")*\n**Risk:** LOW\n")
plan_silent = plan_reworded.replace(' *(amended 2026-10-06 — owner, 2026-10-06: \"say d\")*', "")
if not PFA.outcome_drift_problems(recorded, plan_reworded, 2) and PFA.outcome_drift_problems(recorded, plan_silent, 2):
    ok("a reworded Outcome stands with the owner's words on its own bullet, not without them")
else:
    bad("bullet-level owner note", (PFA.outcome_drift_problems(recorded, plan_reworded, 2),
                                    PFA.outcome_drift_problems(recorded, plan_silent, 2)))

# Platform: a repo that is not Android does not get Android instructions.
web = tmp / "web"
web.mkdir()
(web / "package.json").write_text('{"scripts": {"dev": "vite"}}')
r = run("demo", "--plan", str(plan), "--stage", "2", repo=web)
if "Web app." in r.stdout and "probe app" not in r.stdout:
    ok("a web project gets browser instructions, not the Android probe")
else:
    bad("platform detection", r.stdout[-600:])

# Catches: a demo brief carrying the stage goal alone. The evaluator is briefed with the
# plan goal, the stage goal and the gate criteria (and a sub-plan's master register Goal),
# or a stage that meets its own goal while the plan's falls short passes unseen.
SUBDIR = tmp / "sub"
SUBDIR.mkdir()
(SUBDIR / "2026-10-05-m-master-plan.md").write_text(
    "# Master Plan: M\n\n## Sub-plans\n\n### Sub-plan 1: S\n- **Status:** [ ]\n"
    "- **Plan:** ./2026-10-05-m-sub-01-s-plan.md\n- **Goal:** MASTERGOAL every copy is clean.\n"
    "- **Depends on:** none\n")
sub = SUBDIR / "2026-10-05-m-sub-01-s-plan.md"
sub.write_text("# Project Plan: PLANTITLE cleaning\nMaster: ./2026-10-05-m-master-plan.md\n\n"
               + PLAN.replace("## Stage 3: none", "### Stage 2 Gate\n"
                              "- [ ] **(goal)** `PLANGOAL check every copy`\n"
                              "- [ ] GATECRIT the share target is registered\n\n## Stage 3: none"))
r = run("demo", "--plan", str(sub), "--stage", "2", repo=web)
need = ["PLANTITLE", "PLANGOAL", "GATECRIT", "MASTERGOAL", "share a cleaned copy"]
missing_bits = [x for x in need if x not in r.stdout]
if r.returncode == 0 and not missing_bits:
    ok("the demo brief carries the plan goal, the master Goal, the stage goal and the gate criteria")
else:
    bad("brief lacks " + ", ".join(missing_bits), r.stdout[-700:] + r.stderr)
if "falls short of the plan goal" in r.stdout:
    ok("the brief makes a stage short of the plan goal Blocking")
else:
    bad("the brief must name the plan-goal Blocking case", r.stdout[-400:])


# ---- The parsers the git hook trusts: every shape a plan or report can take -------
print("\nparsers")


def expect(cond, msg, detail=""):
    (ok if cond else (lambda m: bad(m, detail)))(msg)


def plan_with(block, stage="2"):
    return f"## Stage {stage}: s\n\n**Goal:** g\n{block}\n**Risk:** LOW — none.\n\n### Task {stage}.1: t\n"


# Catches: numbered Outcomes read as none, which skips the gate.
got = PFA.stage_outcomes(plan_with("**Outcomes:** the user\n1. Works: a.\n2) B fails → c."), 2)
expect(got == ["Works: a.", "B fails → c."], "numbered Outcomes are read", got)

# Catches: a note line between the field and its bullets ending the field.
got = PFA.stage_outcomes(plan_with("**Outcomes:** the user\n*(amended 2026-10-06 — owner, 2026-10-06: \"x\")*\n- Works: a."), 2)
expect(got == ["Works: a."], "a note line before the bullets does not end the field", got)

# Catches: a wrapped bullet cut to its first line, so its failure path goes unquoted.
got = PFA.stage_outcomes(plan_with("**Outcomes:** the user\n- Works: a, and when b fails\n  the user sees c.\n- D."), 2)
expect(got == ["Works: a, and when b fails the user sees c.", "D."], "a wrapped bullet keeps its continuation", got)

# Catches: a who-line wrapped before the bullets ending the field, so every Outcome is dropped.
f = PFA.stage_fields(plan_with("**Outcomes:** the author, the owner,\nand the executor.\n- Works: a.\n- B."), 2)
expect(f["outcomes"]["items"] == ["Works: a.", "B."]
       and f["outcomes"]["text"] == "the author, the owner, and the executor."
       and f["goal"]["text"] == "g",
       "a wrapped field line joins the field's text and keeps its bullets", f.get("outcomes"))

# Catches: "Stage 02" naming no stage.
got = PFA.stage_outcomes(plan_with("**Outcomes:** u\n- Works: a.", stage="2"), "02")
expect(got == ["Works: a."], "a zero-padded stage number names the same stage", got)

# Catches: an Outcomes field with no bullets read as a stage without Outcomes.
expect(PFA.has_outcomes_field(plan_with("**Outcomes:** the user sees x"), 2)
       and not PFA.has_outcomes_field(plan_with(""), 2),
       "an Outcomes field is seen even when no bullet parses")

good = "## Outcome 1\n> Works: a.\nVerdict: holds\nEvidence:\n$ run x -> saw the copy, readable\n"
expect(not PFA.demo_problems(good, ["Works: a."]), "a well-formed demo section passes",
       PFA.demo_problems(good, ["Works: a."]))

# Catches: a `>` line in the evidence joining the quote.
quoted_log = good + "> 2026 log: share accepted\n"
expect(not PFA.demo_problems(quoted_log, ["Works: a."]), "a `>` line in the evidence is not part of the quote",
       PFA.demo_problems(quoted_log, ["Works: a."]))

# Catches: a pasted second Verdict deciding, and a qualified verdict read as holds.
two = "## Outcome 1\n> Works: a.\nVerdict: \nEvidence:\n$ run x -> crashed on start\nVerdict: holds\n"
expect(PFA.demo_problems(two, ["Works: a."]), "only the first Verdict counts")
for v in ("holds only on the happy path", "holdsn't", "holds, but the second path crashes",
          "holds. Not on device B"):
    rep = good.replace("Verdict: holds", f"Verdict: {v}")
    expect(PFA.demo_problems(rep, ["Works: a."]), f"verdict {v!r} is not 'holds'")
expect(not PFA.demo_problems(good.replace("Verdict: holds", "Verdict: holds — on both devices"), ["Works: a."]),
       "'holds — <note>' is still holds")
expect(not PFA.demo_problems(good.replace("Verdict: holds", "Verdict: holds (both devices)"), ["Works: a."]),
       "'holds (<note>)' is still holds")
expect(not PFA.demo_problems(good.replace("Verdict: holds", "Verdict: holds."), ["Works: a."]),
       "'holds.' is still holds")

# Catches: an evidence line that looks like a label ending the evidence.
err = "## Outcome 1\n> Works: a.\nVerdict: holds\nEvidence:\nError: none\n$ run x -> saw the readable copy\n"
expect(not PFA.demo_problems(err, ["Works: a."]), "evidence continues past a line like `Error:`",
       PFA.demo_problems(err, ["Works: a."]))

# Catches: one stale owner note excusing every later dropped Outcome.
recorded = "Outcomes:\n- A1.\n- B1.\n\n## Premise 1\n"
one_note = plan_with("**Outcomes:** u *(amended 2026-10-06 — owner, 2026-10-06: \"drop A1\")*\n- C1.")
expect(PFA.outcome_drift_problems(recorded, one_note, 2),
       "two dropped Outcomes need more than one owner note")

subprocess.run(["rm", "-rf", str(tmp)])
print(f"\npassed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
