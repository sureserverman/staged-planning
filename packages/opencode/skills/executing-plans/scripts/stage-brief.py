#!/usr/bin/env python3
"""stage-brief.py — the two reports a stage gate is judged on, generated from the plan.

    python3 stage-brief.py premise --plan <plan> --repo <repo> --stage N
    python3 stage-brief.py demo    --plan <plan> --repo <repo> --stage N

`premise` (Step 3.0, before the first task) writes proof/<plan>/stage-N/premise.md:
the stage's Goal, Outcomes and Risk, and an entry per assumption to fill in —
what was checked, on the real environment, and what came back. It prints the
file's path and what to do with it.

`demo` (the gate) writes proof/<plan>/stage-N/demo.md with every Outcome quoted
word for word, and prints the evaluator's brief. Pass the brief to the evaluator
EXACTLY as printed: it is generated so that nobody has to write it, because a
written brief drifts — it paraphrases Outcomes, drops one, and lets a test suite
stand in for the demo.

The `Stage N green` commit carries both files; the git hook refuses it unless
every Outcome's section quotes the plan, holds, and carries evidence, and every
premise is recorded (plan-flip-audit's demo_problems / premise_problems).
An existing file is never overwritten: delete it to start again.

Exit 0 written or already present · 2 bad arguments, or the stage has no
Outcomes (nothing to demo or to bind; Step 3.0 derives them first).
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _audit():
    spec = importlib.util.spec_from_file_location("plan_flip_audit", HERE / "plan-flip-audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PFA = _audit()

# The staleness probe lives in the plugin's lib/, not beside this file: loaded by
# explicit path, as in plan-flip-audit.py, so a stale plugin-cache copy says so before
# it writes a brief under yesterday's rules.
_STALE = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass


def platform(repo):
    """What the user starts from, judged by the files the project's build reads."""
    r = Path(repo)
    if any((r / f).exists() for f in ("settings.gradle", "settings.gradle.kts",
                                       "app/build.gradle", "app/build.gradle.kts")):
        return "android"
    manifest = r / "manifest.json"
    if manifest.is_file():
        try:
            if "manifest_version" in json.loads(manifest.read_text()):
                return "browser-extension"
        except (OSError, ValueError):
            pass
    pkg = r / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text()).get("scripts", {})
            if any(k in scripts for k in ("dev", "start", "preview", "serve")):
                return "web"
        except (OSError, ValueError):
            pass
    return "command-line"


def devices():
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("\tdevice")]


PLATFORM_HOWTO = {
    "android": """Android. Another app is the probe; the screen is uiautomator. Never start the app
under test by class name (`am start -n`) except for its own launcher entry.
If an installed platform stage-verify skill for Android ships a probe app (one
that shares files to the app under test, asks it for files as another app does,
and reads what it hands onward), use it by that skill's own instructions: share
to the app with and without a read grant, ask it for a file, and check what came
back is readable, by name, size and content. With no such probe, drive the app
from the apps a user would share from, by uiautomator.
Crashes: adb -s <serial> logcat -d | grep "FATAL EXCEPTION".""",
    "browser-extension": """Browser extension. Load the built extension into a real browser profile
(Firefox: `web-ext run`; Chromium: --load-extension) and drive pages and the
extension's UI with browser automation, as a user would. Never call the
extension's functions directly.""",
    "web": """Web app. Start the app with its own script (package.json), then use it in a real
browser through automation (e.g. `npx playwright`): navigate, click, type, read
what the page shows. Never call the app's modules or API handlers directly.""",
    "command-line": """Command line or library. Build it the way it ships, then run it from a shell
with real inputs, as its user would; read its output, exit code and files.
Never import its modules in place of running it.""",
}


def plan_title(text):
    """The plan's `# <Kind> Plan: <title>` line, or its first heading."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "(untitled)"


def gate_lines(text, stage):
    """Every box under `### Stage <stage> Gate`, as written, notes and all."""
    out, inside = [], False
    for line in text.splitlines():
        if PFA.GATE_HEAD.match(line):
            inside = PFA._is_stage(PFA.GATE_HEAD.match(line).group(1), stage)
            continue
        if inside and PFA.ANY_HEAD.match(line):
            break
        if inside and PFA.BULLET_BOX.match(line):
            out.append(line.strip())
    return out


def master_goal(plan, text):
    """A sub-plan's master register Goal: the `**Goal:**` of the register entry whose
    `**Plan:**` names this file, in the master its `Master:` line points at. None for a
    plan with no master, or when the master cannot be read."""
    m = re.search(r"^Master:\s*(\S+)", text, re.M)
    if not m:
        return None
    try:
        master = (Path(plan).resolve().parent / m.group(1)).read_text(errors="replace")
    except OSError:
        return None
    name, entry = Path(plan).name, None
    for block in re.split(r"(?m)^###\s+", master):
        if re.search(r"^\s*-\s*\*\*Plan:\*\*\s*\S*" + re.escape(name), block, re.M):
            entry = block
            break
    g = re.search(r"^\s*-\s*\*\*Goal:\*\*\s*(.+)$", entry or "", re.M)
    return g.group(1).strip() if g else None


def stage_paths(plan, repo, stage):
    d = Path(repo) / PFA._prove_claim().PROOF_DIR / Path(plan).stem / f"stage-{stage}"
    return d / "premise.md", d / "demo.md"


def write_new(path, body):
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return True


def premise(plan, repo, stage, text):
    f = PFA.stage_fields(text, stage)
    outcomes = PFA.stage_outcomes(text, stage)
    path, _ = stage_paths(plan, repo, stage)
    lines = [f"# Stage {stage} premises — {Path(plan).stem}", "",
             f"Goal: {f.get('goal', {}).get('text', '(none)')}",
             f"Risk: {f.get('risk', {}).get('text', '(none)')}", "",
             "Outcomes:"] + [f"- {o}" for o in outcomes] + [
             "",
             "These Outcomes are what `Stage N green` is checked against. Changing one after",
             "this point needs the owner's words in its amendment note: owner, <date>: \"<words>\".",
             "",
             "One entry per thing the Goal, Outcomes or Risk assume about what the code does",
             "not control (the platform, another app, a permission, the engine, a service).",
             "Check each on the real environment before building on it. Verdict: holds, false,",
             "or not checkable here — <why>. A false premise is a Stop condition.", ""]
    lines += ["## Premise 1", "Assumption: ", "Checked: ", "Result: ", "Verdict: ", ""]
    made = write_new(path, "\n".join(lines))
    print(f"{'wrote' if made else 'exists'}: {path}")
    print("Fill in one `## Premise K` per assumption (copy the block), each checked by a command")
    print("on the real environment. Commit it with the stage's work; `Stage N green` needs it.")


def demo(plan, repo, stage, text):
    f = PFA.stage_fields(text, stage)
    outcomes = PFA.stage_outcomes(text, stage)
    prem_path, path = stage_paths(plan, repo, stage)
    unchecked = []
    if prem_path.is_file():
        for k, body in sorted(PFA._sections(prem_path.read_text(), "Premise").items()):
            if PFA._label(body, "Verdict").lower().startswith("not checkable"):
                unchecked.append(PFA._label(body, "Assumption"))
    kind = platform(repo)
    env = ", ".join(devices()) if kind == "android" else "(see below)"
    lines = [f"# Stage {stage} demo — {Path(plan).stem}", "", f"Environment: {env}", "",
             "Fill in Verdict and Evidence under each Outcome. Do not edit the quoted lines.", ""]
    for k, o in enumerate(outcomes, 1):
        lines += [f"## Outcome {k}", f"> {o}", "Verdict: ", "Evidence:", "", ""]
    made = write_new(path, "\n".join(lines))
    rel = path.relative_to(repo)
    print(f"# {'wrote' if made else 'exists'}: {path}")
    print("# Dispatch the demo evaluator with everything below this line, unchanged.\n")
    goals = [l for l in gate_lines(text, stage) if "(goal)" in l]
    mgoal = master_goal(plan, text)
    print(f"""You are the Stage {stage} demo evaluator. You did not build this. Do not read the
source or the diff: use the product, as its user would, and record what you saw.

Plan: {plan_title(text)}
Plan goal, as its gate checks it: {' / '.join(goals) if goals else '(no (goal) check at this gate)'}""")
    if mgoal:
        print(f"Master register Goal: {mgoal}")
    print(f"""Stage goal: {f.get('goal', {}).get('text', '')}
Gate criteria:""")
    for line in gate_lines(text, stage) or ["(none listed)"]:
        print(f"  {line}")
    print(f"""Who: {f.get('outcomes', {}).get('text', '')}
Outcomes:""")
    for k, o in enumerate(outcomes, 1):
        print(f"  {k}. {o}")
    print(f"""Premises not checked yet: {'; '.join(unchecked) if unchecked else 'none'}
Environment: {env}
Repo: {repo}

For each Outcome:
1. Start where that user starts, by the route they take. Never by class name, test
   hook, internal entry point, or a test suite standing in for the user.
2. Do what they do, then cause each failure the Outcome names.
3. Record the commands you ran and what came back: screen text, the result the
   caller got, crash lines.
If an Outcome cannot be reached by the user's route with the tools below, its verdict
is "cannot reach by the user's route" — do not substitute a test.

How, on this platform —
{PLATFORM_HOWTO[kind]}

Write your results into {rel}: under each `## Outcome K`, keep the quoted line exactly,
set `Verdict:` to holds / does not hold / cannot reach by the user's route, and put the
commands and what you saw under `Evidence:`. "Does not hold", "cannot reach", a crash,
or "the user gets nothing" is Blocking, and so is a stage whose finished output already
falls short of the plan goal with no later stage planned to change it. Other defects are
Material or Minor; list
them after the Outcomes. A FAIL with no Blocking finding is a PASS with residuals.
Wait on any background job you start by its own completion (the harness notification,
`wait <pid>`, or a sentinel file the job writes last), never by searching for its name.
Return only after your background work has finished or been stopped, and say which.
Return the same table and findings in your reply.""")


def main(argv=None):
    _warn_if_stale()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kind", choices=("premise", "demo"))
    ap.add_argument("--plan", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--stage", required=True, type=int)
    a = ap.parse_args(argv)
    try:
        text = Path(a.plan).read_text(errors="replace")
    except OSError as e:
        print(f"stage-brief: cannot read the plan: {e}", file=sys.stderr)
        return 2
    repo = str(Path(a.repo).resolve())
    if not PFA.stage_outcomes(text, a.stage):
        print(f"stage-brief: Stage {a.stage} has no **Outcomes:** — derive them first "
              "(executing-plans Step 3.0, item 1).", file=sys.stderr)
        return 2
    (premise if a.kind == "premise" else demo)(a.plan, repo, a.stage, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
