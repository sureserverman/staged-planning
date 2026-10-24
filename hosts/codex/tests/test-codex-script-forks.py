#!/usr/bin/env python3
"""The Codex script forks and hook wiring, from the Codex build.

  context-usage.py  reads a Codex session rollout: `now` is the last token_count row's
                    input tokens and the window its model_context_window; a rollout with
                    no token_count row is verdict `unknown`, never a guess
  plan-progress.py  a bare call prints usage and exits 64 (the renderer is gone); the
                    budget check is core's, refusing a hand-written legacy round
  hooks.json        wires exactly Stop, PreToolUse (Bash), SubagentStart and SubagentStop
                    to files the build ships
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-forks-test-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    scripts = os.path.join(out, "skills", "executing-plans", "scripts")
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, ".claude"))
    subprocess.run(["git", "init", "-q", "--template=", repo], check=True)

    rollout = os.path.join(tmp, "rollout.jsonl")
    rows = [{"type": "session_meta", "payload": {"id": "thread-1", "cwd": repo}}]
    for n in (120000, 450000):
        rows.append({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": n}, "model_context_window": 1000000}}})
    with open(rollout, "w") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    r = subprocess.run([sys.executable, os.path.join(scripts, "context-usage.py"), "--transcript",
                        rollout], cwd=repo, capture_output=True, text=True)
    check("now=450000" in r.stdout and "window=1000000" in r.stdout,
          f"context-usage reads the last token_count row ({r.stdout.strip()[-160:]})")
    with open(rollout, "w") as fh:
        fh.write(json.dumps(rows[0]) + "\n")
    r = subprocess.run([sys.executable, os.path.join(scripts, "context-usage.py"), "--transcript",
                        rollout], cwd=repo, capture_output=True, text=True)
    check("verdict=unknown" in r.stdout, f"a rollout with no token_count row is unknown "
          f"({r.stdout.strip()[-120:]})")

    pp = os.path.join(scripts, "plan-progress.py")
    r = subprocess.run([sys.executable, pp], cwd=repo, capture_output=True, text=True)
    check(r.returncode == 64, f"a bare plan-progress call exits 64 ({r.returncode})")

    with open(os.path.join(repo, "p-plan.md"), "w") as fh:
        fh.write("# Project Plan: p\n")

    def budget(**extra):
        with open(os.path.join(repo, ".claude", "plan-progress.json"), "w") as fh:
            json.dump({"plan": "p-plan.md", "phase": "gate", "stage": 1,
                       "updated": "2099-01-01T00:00:00Z", **extra}, fh)
        return subprocess.run([sys.executable, pp, "--budget-check"], cwd=repo,
                              capture_output=True, text=True)

    # Core's owned-state protocol refuses a hand-written legacy round, and the fork keeps
    # that check byte-identical: a remediation round is recorded through plan-state.py.
    # The positive control is an idle legacy state, which stays readable (exit 0), so an
    # exit 3 below is the refusal itself, not a fork that cannot run at all.
    r = budget()
    check(r.returncode == 0, f"the budget check reads an idle legacy state ({r.returncode} "
          f"{r.stderr.strip()[-120:]})")
    r = budget(remediation_round=1)
    check(r.returncode == 3 and "legacy round requires evidenced migration" in r.stderr,
          f"the budget check refuses a hand-written legacy round, as core does "
          f"({r.returncode} {r.stderr.strip()[-120:]})")

    with open(os.path.join(out, "hooks", "hooks.json")) as fh:
        hooks = json.load(fh)["hooks"]
    check(set(hooks) == {"Stop", "PreToolUse", "SubagentStart", "SubagentStop"}
          and hooks["PreToolUse"][0].get("matcher") == "Bash",
          f"hooks.json wires the four events, PreToolUse on Bash ({sorted(hooks)})")
    named = [re.search(r"\$\{PLUGIN_ROOT\}/(\S+?)\"", h["command"]).group(1)
             for ev in hooks.values() for m in ev for h in m["hooks"]]
    check(all(os.path.isfile(os.path.join(out, n)) for n in named),
          f"every hook command names a file the build ships ({named})")
finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
