#!/usr/bin/env python3
"""qualify.py and scripts/host-install-check.py, against a fake codex (no network, no model).

  list        every case prints with a needs_model tag, both tags occur, and at least 13
              cases run without a model
  run         a synthetic plugin under a non-default identity passes every case; a second
              plugin with no hooks and no agents passes with its agent cases not applicable
  mutants     each misbehaviour of the fake fails the case named for it, and the run
  compare     --compare-evidence passes on a fresh record, and fails once the output gains
              a skill or loses a hook; an unreadable record exits 2
  inputs      exit 2 for: an identity the marketplace does not list, a scratch home that is
              the owner's (by --owner-codex-home or $CODEX_HOME), evidence inside a
              plugin's checkout, and a codex binary that does not run
  dispatcher  host-install-check.py refuses a host with no harness and a real profile (exit 2),
              runs codex in a scratch home that it deletes afterwards, and leaves the
              owner's Codex home as it was
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUALIFY = HERE.parent / "qualify.py"
FAKE = HERE / "fake_codex.py"
REPO = HERE.parents[3]
CHECK = REPO / "scripts/host-install-check.py"
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def fake_bin(root):
    """An executable `codex` that runs the fake under this interpreter, after sourcing the
    fake's settings from bin/fake.env (qualify does not pass the caller's FAKE_* through)."""
    path = root / "bin/codex"
    write(path, f"#!/bin/sh\n[ -f \"{root}/bin/fake.env\" ] && . \"{root}/bin/fake.env\"\n"
                f"exec {sys.executable} {FAKE} \"$@\"\n")
    path.chmod(0o755)
    return path


def fake_env(codex, **settings):
    """Write the settings the fake `codex` wrapper sources on every call."""
    write(codex.parent / "fake.env", "".join(f"export {k}={shlex.quote(str(v))}\n"
                                            for k, v in settings.items()))


INSTALLER = '''import argparse, json, sys
from pathlib import Path
ap = argparse.ArgumentParser()
ap.add_argument("--codex-home", type=Path)
ap.add_argument("--install", action="store_true")
ap.add_argument("--json", action="store_true")
a = ap.parse_args()
src = Path(__file__).resolve().parents[1] / "agents"
dest = a.codex_home / "agents"
rows = []
for t in sorted(src.glob("*.toml")):
    if a.install:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / t.name).write_bytes(t.read_bytes())
    have = (dest / t.name).exists()
    rows.append({"name": t.stem, "file": t.name, "status": "present" if have else "missing"})
if a.json:
    print(json.dumps({"roles": rows}))
'''


def market(root, market_name, plugin, hooks=True, agents=True):
    """A marketplace checkout with one built plugin under out/<plugin>."""
    out = root / "out" / plugin
    write(root / ".agents/plugins/marketplace.json", json.dumps({
        "name": market_name, "plugins": [{"name": plugin, "source": {
            "source": "local", "path": f"./out/{plugin}"}, "policy": {}, "category": "x"}]}))
    write(out / ".codex-plugin/plugin.json", json.dumps({"name": plugin, "version": "1.0.0"}))
    for skill in ("alpha", "beta"):
        write(out / f"skills/{skill}/SKILL.md", f"# {skill}\n\nSee [the guide](guide.md) "
              f"and `[an example](nowhere.md)`.\n")
        write(out / f"skills/{skill}/guide.md", "guide\n")
    write(out / "scripts/tool.py", "import json\nimport helper\n")
    write(out / "scripts/helper.py", "X = 1\n")
    if hooks:
        defs = {"Stop": [{"hooks": [{"type": "command", "timeout": 10,
                                     "command": 'bash "${PLUGIN_ROOT}/hooks/stop.sh"'}]}],
                "PreToolUse": [{"matcher": "Bash", "hooks": [{
                    "type": "command", "timeout": 10,
                    "command": 'bash "${PLUGIN_ROOT}/hooks/guard.sh"'}]}],
                "SubagentStart": [{"hooks": [{"type": "command", "timeout": 5,
                                              "command": 'bash "${PLUGIN_ROOT}/hooks/log.sh"'}]}],
                "SubagentStop": [{"hooks": [{"type": "command", "timeout": 5,
                                             "command": 'bash "${PLUGIN_ROOT}/hooks/log.sh"'}]}]}
        write(out / "hooks/hooks.json", json.dumps({"hooks": defs}))
        for h in ("stop", "guard", "log"):
            write(out / f"hooks/{h}.sh", "exit 0\n")
    if agents:
        write(out / "agents/role-a.toml", 'name = "role-a"\n')
        write(out / "agents/role-b.toml", 'name = "role-b"\n')
        write(out / "scripts/install-agents.py", INSTALLER)
    return out


def run_qualify(work, *args, env=None):
    return subprocess.run([sys.executable, str(QUALIFY), *args], capture_output=True,
                          text=True, env=env or os.environ.copy(), cwd=work, timeout=120)


def qualify_run(work, codex, markets, mutate="", extra=True, evidence=None, owner=None):
    home = work / f"home-{mutate or 'clean'}"
    if home.exists():
        shutil.rmtree(home)
    owner = owner or work / "owner"
    owner.mkdir(exist_ok=True)
    fake_env(codex, FAKE_CODEX_MUTATE=mutate, FAKE_OWNER=owner)
    env = os.environ.copy()
    args = ["--run", "--codex", str(codex), "--codex-home", str(home), "--workdir",
            str(work / "w"), "--marketplace", str(markets[0]), "--plugin-id",
            "toy@fixture-market", "--owner-codex-home", str(owner)]
    if extra:
        args += ["--extra-marketplace", str(markets[1]), "--extra-plugin", "extra@other-market"]
    if evidence:
        args += ["--evidence", str(evidence)]
    return run_qualify(work, *args, env=env)


def failed_cases(stdout):
    return sorted({" ".join(line.split()[1:3]).rstrip(":") for line in stdout.splitlines()
                   if line.startswith("FAIL ")})


def main():
    work = Path(tempfile.mkdtemp(prefix="test-qualify-"))
    try:
        codex = fake_bin(work)
        m1, m2 = work / "m1", work / "m2"
        market(m1, "fixture-market", "toy")
        out2 = market(m2, "other-market", "extra", hooks=False, agents=False)

        print("list")
        got = run_qualify(work, "--list")
        rows = [r.split("\t") for r in got.stdout.splitlines() if r.strip()]
        tags = [r[1] for r in rows if len(r) == 3]
        check(got.returncode == 0 and len(tags) == len(rows) >= 13,
              f"--list prints {len(rows)} tab-separated cases, each tagged")
        check(set(tags) == {"needs_model=true", "needs_model=false"}, f"both tags occur ({set(tags)})")
        check(tags.count("needs_model=false") >= 13,
              f"{tags.count('needs_model=false')} cases run without a model (>= 13)")

        print("run")
        ev = work / "evidence"
        got = qualify_run(work, codex, (m1, m2), evidence=ev)
        check(got.returncode == 0, f"a clean fake run passes (rc={got.returncode}: "
              f"{failed_cases(got.stdout)} {got.stderr[-300:]})")
        data = json.loads((ev / "results.json").read_text())
        ids = {p["id"] for p in data["plugins"]}
        check(ids == {"toy@fixture-market", "extra@other-market"},
              f"the evidence records both identities as given ({ids})")
        toy = next(p for p in data["plugins"] if p["id"] == "toy@fixture-market")
        extra = next(p for p in data["plugins"] if p["id"] == "extra@other-market")
        # Skill ids are joined at run time: a quoted <plugin>:<skill> literal of a plugin that
        # is not this repo's reads as a foreign id to check-portable.
        check(toy["skills_seen"] == [":".join(("toy", s)) for s in ("alpha", "beta")] and len(toy["hooks_seen"]) == 4,
              f"the toy plugin's two skills and four hooks are recorded ({toy['skills_seen']})")
        check(extra["hooks_seen"] == [] and extra["skills_seen"] == [":".join(("extra", s)) for s in ("alpha", "beta")],
              "the extra plugin records its skills and no hooks")
        na = sorted(r["id"] for r in data["cases"] if r["status"] == "not-applicable")
        check(na == ["agent-install", "agent-report", "hook-rendering"],
              f"only the extra plugin's agent and hook-rendering cases are not applicable ({na})")
        check(all(r["needs_model"] for r in data["not_run"]) and data["not_run"]
              and not any(r["id"].startswith("model-") for r in data["cases"]),
              "model cases are listed as not run, never as results")

        print("mutants")
        for mutate, case in (("extra-skill", "toy@fixture-market skill-discovery"),
                             ("trusted-hook", "toy@fixture-market hook-untrusted"),
                             ("drop-hook", "toy@fixture-market hook-discovery"),
                             ("wrong-id", "toy@fixture-market plugin-add"),
                             ("keep-cache", "toy@fixture-market plugin-remove"),
                             ("corrupt-cache", "toy@fixture-market installed-integrity"),
                             ("touch-owner", "toy@fixture-market owner-home-untouched"),
                             ("ignore-disable", "toy@fixture-market plugin-disable"),
                             ("bad-render", "toy@fixture-market hook-rendering"),
                             ("drop-role", "toy@fixture-market agent-report")):
            got = qualify_run(work, codex, (m1, m2), mutate=mutate, extra=False)
            check(got.returncode == 1 and case in failed_cases(got.stdout),
                  f"{mutate}: fails {case} (rc={got.returncode}, failed {failed_cases(got.stdout)})")
            if (work / "owner/config.toml").exists():
                (work / "owner/config.toml").unlink()

        (m1 / "out/toy/hooks/stop.sh").unlink()
        write(m1 / "out/toy/skills/alpha/broken.md", "see [gone](gone.md)\n")
        got = qualify_run(work, codex, (m1, m2), extra=False)
        check(got.returncode == 1 and failed_cases(got.stdout) == ["toy@fixture-market package-static"]
              and "hooks/stop.sh is missing" in got.stdout and "gone.md" in got.stdout,
              f"a missing hook target and a broken link fail package-static ({failed_cases(got.stdout)})")
        write(m1 / "out/toy/hooks/stop.sh", "exit 0\n")
        (m1 / "out/toy/skills/alpha/broken.md").unlink()

        print("compare")
        got = run_qualify(work, "--compare-evidence", str(ev))
        check(got.returncode == 0, f"a fresh record matches the output (rc={got.returncode} {got.stdout})")
        write(out2 / "skills/stray/SKILL.md", "# stray\n")
        got = run_qualify(work, "--compare-evidence", str(ev))
        check(got.returncode == 1 and "extra@other-market" in got.stdout,
              f"a stray skill dir in the output fails the compare (rc={got.returncode})")
        shutil.rmtree(out2 / "skills/stray")
        hooks = json.loads((m1 / "out/toy/hooks/hooks.json").read_text())
        del hooks["hooks"]["Stop"]
        write(m1 / "out/toy/hooks/hooks.json", json.dumps(hooks))
        got = run_qualify(work, "--compare-evidence", str(ev))
        check(got.returncode == 1 and "hooks.json changed" in got.stdout,
              f"a dropped hook definition fails the compare (rc={got.returncode})")
        got = run_qualify(work, "--compare-evidence", str(work / "nowhere"))
        check(got.returncode == 2, f"an unreadable record exits 2 (rc={got.returncode})")

        print("inputs")
        got = run_qualify(work, "--run", "--codex", str(codex), "--codex-home", str(work / "h"),
                          "--workdir", str(work / "w"), "--marketplace", str(m1),
                          "--plugin-id", "toy@another-market")
        check(got.returncode == 2, f"an identity the marketplace does not name exits 2 (rc={got.returncode})")
        got = run_qualify(work, "--run", "--codex", str(codex), "--codex-home", str(work / "owner"),
                          "--workdir", str(work / "w"), "--marketplace", str(m1),
                          "--plugin-id", "toy@fixture-market", "--owner-codex-home",
                          str(work / "owner"))
        check(got.returncode == 2, f"a scratch home that is the owner's exits 2 (rc={got.returncode})")
        got = run_qualify(work, "--run", "--codex", str(codex), "--codex-home", str(work / "h"),
                          "--workdir", str(work / "w"), "--marketplace", str(m1),
                          "--plugin-id", "toy@fixture-market",
                          env=dict(os.environ, CODEX_HOME=str(work / "h")))
        check(got.returncode == 2, f"a home that is $CODEX_HOME exits 2 without --owner-codex-home "
              f"(rc={got.returncode})")
        got = run_qualify(work, "--run", "--codex", str(codex), "--codex-home", str(work / "h2"),
                          "--workdir", str(work / "w"), "--marketplace", str(m1),
                          "--plugin-id", "toy@fixture-market", "--evidence", str(m1 / "ev"))
        check(got.returncode == 2 and not (m1 / "ev").exists(),
              f"evidence inside a plugin's checkout exits 2 and writes nothing (rc={got.returncode})")
        got = run_qualify(work, "--run", "--codex", str(work / "no-such-codex"), "--codex-home",
                          str(work / "h3"), "--workdir", str(work / "w"), "--marketplace", str(m1),
                          "--plugin-id", "toy@fixture-market")
        check(got.returncode == 2, f"a codex binary that does not run exits 2 (rc={got.returncode})")

        print("dispatcher")
        for args, why in ((["--host", "claude", "--isolated"], "a host with no harness"),
                          (["--host", "codex"], "a real profile")):
            got = subprocess.run([sys.executable, str(CHECK), *args], capture_output=True,
                                 text=True, timeout=60)
            check(got.returncode == 2, f"refuses {why} with exit 2 (rc={got.returncode})")
        owner = work / "dispatch-owner"
        write(owner / "config.toml", "owner = true\n")
        seen = work / "seen.txt"
        tmp = work / "tmp"
        tmp.mkdir()
        fake_env(codex, FAKE_CODEX_SEEN=seen)
        env = dict(os.environ, CODEX_HOME=str(owner), TMPDIR=str(tmp), OPENAI_API_KEY="probe")
        got = subprocess.run([sys.executable, str(CHECK), "--host", "codex", "--isolated",
                              "--codex", str(codex)], capture_output=True, text=True,
                             env=env, timeout=300)
        homes = set(seen.read_text().split()) if seen.exists() else set()
        check(got.returncode == 0, f"the real Codex build passes against the fake "
              f"(rc={got.returncode}: {failed_cases(got.stdout)} {got.stderr[-300:]})")
        check(homes and all(h.startswith(str(tmp)) for h in homes),
              f"every codex call ran with HOME and CODEX_HOME in a scratch dir under the temp "
              f"dir, and saw no OPENAI_API_KEY ({sorted(homes)[:3]})")
        check(list(tmp.iterdir()) == [], f"the scratch dir is deleted ({list(tmp.iterdir())})")
        check((owner / "config.toml").read_text() == "owner = true\n"
              and sorted(p.name for p in owner.iterdir()) == ["config.toml"],
              "the owner's Codex home is as it was")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{len(FAILS)} FAILURE(S)" if FAILS else "\nall qualify cases passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
