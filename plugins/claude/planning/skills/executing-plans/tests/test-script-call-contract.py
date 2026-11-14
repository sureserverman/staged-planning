#!/usr/bin/env python3
"""Contract suite: every host's executing-plans trunk shows the calls it mandates.

    python3 core/skills/executing-plans/tests/test-script-call-contract.py

WHAT THIS SUITE IS REALLY GUARDING. The 2026-11-13 audit counted 1,065 `plan-state.py`
calls against 468 task commits and 138 `prove-claim.py` argument errors: the trunk
described the calls in prose and pointed at a reference for the rest, so a run guessed,
and guessed again after every handoff. So each built trunk carries the calls
literally — `prove-claim.py claim`, and `plan-state.py` `init`, a task `transition`
and `finish` with their stdin payloads — and each is parsed back through the script
that ships beside that trunk, so a call the script would refuse cannot be shown. Each
trunk also tells the run to `check` an owner decision it writes mid-run, because the
audited refusals (an `applies to:` word the reader cannot place) came from entries
written during a run that nothing checked until the answer was needed.

`<N>`, the last receipt's revision, is the one placeholder the parser types; it is
filled with 1 before parsing. Every other `<…>` is parsed as written. Parsing includes
the scripts' own rules beyond argparse (`ExampleParser(check=...)`), so a prove-claim
call missing its build flag is refused here. The three plan-state calls are then run
for real, in order, in a scratch repo: parsing alone cannot show that a payload carries
the fields its operation needs.
"""
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
spec = importlib.util.spec_from_file_location("usage_examples", HERE / "test-usage-examples.py")
UE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(UE)

TRUNKS = {build: build / "skills/executing-plans/SKILL.md" for build in UE.BUILDS}
PREFIX = "python3 <planning-plugin>/skills/executing-plans/scripts/"
CALL = re.compile(r"(?:echo '[^'\n]*' \| )?" + re.escape(PREFIX) +
                  r"(prove-claim|plan-state)\.py (?=[a-z])[^`\n]*--repo[^`\n]*")
CHECK_RULE = re.compile(
    r"mid-run answer into `## Owner decisions`, run\s+"
    r"`python3 <planning-plugin>/skills/executing-plans/scripts/owner-decision\.py check <plan>`"
    r"\s+and fix the entry until it exits 0")

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
        print("        | " + str(detail)[:900].replace("\n", "\n        | "))


def parsed(build, script, call):
    """(namespace dict, None) when the script's own parser accepts the call, else (None, why)."""
    rel = f"skills/executing-plans/scripts/{script}.py"
    stdin, words, why = UE.call_of(call, rel)
    if why:
        return None, why
    if stdin is not None:
        try:
            json.loads(stdin)
        except ValueError as e:
            return None, f"its stdin payload is not JSON ({e}): {stdin}"
    words = ["1" if w == "<N>" else w for w in words]
    r = UE.wrapped("parse", build / rel, words)
    if r.returncode != 0 or not r.stdout.startswith("PARSED "):
        return None, f"refused by {script}.py: {r.stderr.strip()[-300:]}"
    return json.loads(r.stdout[len("PARSED "):]), None


def run_state_calls(build, seen):
    """init, the task transition and finish, as the trunk shows them, run in order."""
    script = build / "skills/executing-plans/scripts/plan-state.py"
    rel = "skills/executing-plans/scripts/plan-state.py"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        UE.git_repo(repo)
        plan = repo / "fixture-plan.md"
        plan.write_text(UE.PLAN_FIXTURE)
        revision = 0
        for op in ("init", "transition", "finish"):
            stdin, words, _ = UE.call_of(seen[("plan-state", op)], rel)
            fill = {"<plan>": str(plan), "<repo>": str(repo), "<id>": f"contract-{op}",
                    "<N>": str(revision)}
            words = [fill.get(w, w) for w in words]
            stdin = stdin.replace("<plan>", str(plan))
            r = subprocess.run([sys.executable, str(script), *words], input=stdin,
                               capture_output=True, text=True, timeout=60)
            try:
                receipt = json.loads(r.stdout)
            except ValueError:
                receipt = {}
            if r.returncode != 0 or receipt.get("status") != "ok":
                return False, f"`{op}` as the trunk shows it fails when run: {r.stdout}{r.stderr}"
            revision = receipt["revision"]
    return True, "init, the task transition and finish, as shown, run in order"


AGENT = re.compile(r"python3 <scripts>/prove-claim\.py claim (?:[^\n]*\\\n)*[^\n]*")


def agent_call(build):
    """The claim-verifier agent's one complete `prove-claim.py claim` call, parsed.
    Its other prove-claim mentions are `…` fragments, not calls."""
    found = [f for f in build.glob("agents/*claim-verifier*") if f.is_file()]
    if len(found) != 1:
        return False, f"{len(found)} claim-verifier agent files"
    m = AGENT.search(found[0].read_text())
    if not m:
        return False, f"{found[0].name}: no complete `prove-claim.py claim` call"
    call = " ".join(m.group(0).replace("\\\n", " ").split())
    call = call.replace("python3 <scripts>/", PREFIX)
    stdin, words, why = UE.call_of(call, "skills/executing-plans/scripts/prove-claim.py")
    if why:
        return False, why
    # K, the claim's number, and <budget>, seconds, are typed: filled as a caller would.
    words = [{"K": "1", "<budget>": "3600"}.get(w, w) for w in words]
    r = UE.wrapped("parse", build / "skills/executing-plans/scripts/prove-claim.py", words)
    if r.returncode != 0:
        return False, f"{found[0].name}: its claim call is refused: {r.stderr.strip()[-300:]}"
    return True, f"{found[0].name}: its claim call is one prove-claim accepts"


def main():
    for build, trunk in TRUNKS.items():
        label = str(trunk.relative_to(REPO))
        if not trunk.is_file():
            bad(f"{label}: missing")
            continue
        text = trunk.read_text()
        calls = [m.group(0).rstrip() for m in CALL.finditer(text)]
        seen = {}
        for call in calls:
            script = "prove-claim" if "prove-claim.py" in call else "plan-state"
            ns, why = parsed(build, script, call)
            if why:
                bad(f"{label}: a call the trunk shows is refused: {call}", why)
                continue
            key = ns.get("mode") if script == "prove-claim" else ns.get("operation")
            seen.setdefault((script, key), call)
        want = [("prove-claim", "claim"), ("plan-state", "init"),
                ("plan-state", "transition"), ("plan-state", "finish")]
        for script, op in want:
            if (script, op) in seen:
                ok(f"{label}: shows a `{script}.py {op}` call its script accepts")
            else:
                bad(f"{label}: shows no `{script}.py {op}` call with --repo",
                    "\n".join(calls) or "(no calls found)")
        claim = seen.get(("prove-claim", "claim"), "")
        if claim and not re.search(r"--claim 1\b", claim):
            bad(f"{label}: its prove-claim call does not pass the claim's number (--claim 1)", claim)
        transition = seen.get(("plan-state", "transition"), "")
        if transition and '"task":' not in transition:
            bad(f"{label}: its transition call is not a task transition", transition)
        if all(("plan-state", op) in seen for op in ("init", "transition", "finish")):
            good, msg = run_state_calls(build, seen)
            (ok if good else bad)(f"{label}: {msg}")
        good, msg = agent_call(build)
        (ok if good else bad)(f"{build.relative_to(REPO)}: {msg}")
        if CHECK_RULE.search(" ".join(text.split())):
            ok(f"{label}: tells the run to check an owner decision it writes")
        else:
            bad(f"{label}: does not tell the run to run `owner-decision.py check <plan>` "
                "after writing an owner's mid-run answer")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed or not passed else 0


if __name__ == "__main__":
    sys.exit(main())
