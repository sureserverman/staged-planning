#!/usr/bin/env python3
"""install-agents.py, from the Codex build, against scratch Codex homes.

  report      a fresh home reports every role `missing` and exits 0, writing nothing
  install     --install writes every role, byte for byte, and a re-run reports `present`
  differs     a role the user edited is reported `differs`, never replaced, while a
              missing one beside it is still installed; exit 3
  refused     a directory or a FIFO at a role's path is reported `refused`, with no
              traceback and no hang; a symlinked agents dir is refused outright
  linked home a Codex home that is itself a symlink (a dotfiles layout) installs
  json        --json lists every role with its status
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ROLES = ["architecture-researcher", "claim-verifier", "code-reviewer",
         "design-handoff-reproducer", "goal-evaluator"]
FAILS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


tmp = tempfile.mkdtemp(prefix="codex-install-test-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "codex",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    script = os.path.join(out, "scripts", "install-agents.py")

    def run(home, *args):
        r = subprocess.run([sys.executable, script, "--codex-home", home, *args],
                           capture_output=True, text=True, timeout=20)
        return r.returncode, r.stdout + r.stderr

    def statuses(home):
        r = subprocess.run([sys.executable, script, "--codex-home", home, "--json"],
                           capture_output=True, text=True, timeout=20)
        return {x["name"]: x["status"] for x in json.loads(r.stdout)["roles"]}

    home = os.path.join(tmp, "h1")
    rc, o = run(home)
    check(rc == 0 and o.count(": missing;") == 5 and not os.path.exists(home),
          f"a fresh home reports five roles missing and writes nothing ({rc})")
    rc, o = run(home, "--install")
    agents = os.path.join(home, "agents")
    same = all(open(os.path.join(agents, f"planning-{r}.toml"), "rb").read()
               == open(os.path.join(out, "agents", f"planning-{r}.toml"), "rb").read()
               for r in ROLES)
    check(rc == 0 and same, f"--install writes every role byte for byte ({rc})")
    check(set(statuses(home).values()) == {"present"}, "a re-run reports every role present")

    with open(os.path.join(agents, "planning-code-reviewer.toml"), "a") as fh:
        fh.write("# my edit\n")
    os.remove(os.path.join(agents, "planning-claim-verifier.toml"))
    rc, o = run(home, "--install")
    st = statuses(home)
    check(rc == 3 and st["planning:code-reviewer"] == "differs"
          and st["planning:claim-verifier"] == "present"
          and open(os.path.join(agents, "planning-code-reviewer.toml")).read().endswith("# my edit\n"),
          f"an edited role is kept and reported, a missing one still installed ({rc})")

    home2 = os.path.join(tmp, "h2")
    os.makedirs(os.path.join(home2, "agents", "planning-goal-evaluator.toml"))
    os.mkfifo(os.path.join(home2, "agents", "planning-claim-verifier.toml"))
    rc, o = run(home2, "--install")
    st = statuses(home2)
    check(rc == 3 and "Traceback" not in o and st["planning:goal-evaluator"] == "refused"
          and st["planning:claim-verifier"] == "refused" and st["planning:code-reviewer"] == "present",
          f"a directory and a FIFO are refused, with no traceback or hang ({rc})")

    home3 = os.path.join(tmp, "h3")
    os.makedirs(home3)
    os.symlink(os.path.join(tmp, "elsewhere"), os.path.join(home3, "agents"))
    rc, o = run(home3, "--install")
    check(rc == 2 and not os.path.exists(os.path.join(tmp, "elsewhere")),
          f"a symlinked agents dir is refused, writing nothing through it ({rc})")

    real = os.path.join(tmp, "dotfiles-codex")
    os.makedirs(real)
    os.symlink(real, os.path.join(tmp, "linked-home"))
    rc, o = run(os.path.join(tmp, "linked-home"), "--install")
    check(rc == 0 and len(os.listdir(os.path.join(real, "agents"))) == 5,
          f"a Codex home that is itself a symlink installs ({rc})")
finally:
    shutil.rmtree(tmp)

print(f"\n{'FAIL' if FAILS else 'OK'}: {len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
