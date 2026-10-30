#!/usr/bin/env python3
"""The Cursor validate-stack-routing.py holds the routing table to names Cursor can dispatch.

What the Cursor fork changes from core: Cursor has no plugin namespace, so it dispatches
an agent by its bare name. The fork's built-ins are `generalPurpose` and `explore` (core:
`general-purpose`, `Explore`); a bare shipped agent name is OK (core: WARN, use the
namespaced id); and every `<plugin>:<name>` id is a FAIL, this plugin's own included
(core: OK when it names an agent or skill shipped here).

Builds the Cursor plugin into a scratch dir. The first case runs the BUILT validator over
the built plugin's own table. The rest copy the built scripts/ into a throwaway plugin
whose stack-routing.md is the case's table, and run the validator there, as the script
resolves its plugin root from its own location.

  shipped table   the built validator passes the built Cursor table, with no WARN
  built-ins       `generalPurpose` and `explore` pass; `general-purpose` and `Explore` fail
  bare names      a shipped agent and a shipped skill pass by bare name, with no WARN; an
                  agent or skill not shipped here fails
  namespaced      `planning:<agent>` and `planning:<skill>` fail, backticked or not, and
                  the message names the bare form; another plugin's id fails
  empty root      a plugin root with no agents or skills fails, never passes empty
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REL = os.path.join("skills", "dispatching-parallel-agents", "scripts")
FORK = os.path.join(REPO, "hosts", "cursor", "overrides", REL, "validate-stack-routing.py")
FAILS = []
HEAD = "| Task | Subagent type | Skill |\n|---|---|---|\n"
# Another plugin's id, built in parts so this file names no plugin but its own.
SIBLING = "other-plugin" + ":" + "stack-expert"


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[:600].replace("\n", "\n     | "))


tmp = tempfile.mkdtemp(prefix="cursor-stack-routing-")
try:
    out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(REPO, "build", "build.py"), "--host", "cursor",
                    "--no-lock-check", "--out", out], cwd=REPO, check=True, capture_output=True)
    built = os.path.join(out, REL, "validate-stack-routing.py")
    env0 = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    n = [0]

    def run(script):
        return subprocess.run([sys.executable, script], cwd=tmp, capture_output=True, text=True,
                              env=env0)

    def run_doc(doc, agents=("code-reviewer",), skills=("applying-design-handoff",)):
        """The built validator over a throwaway plugin whose stack-routing.md is `doc`."""
        n[0] += 1
        root = os.path.join(tmp, f"plugin-{n[0]}")
        dpa = os.path.join(root, "skills", "dispatching-parallel-agents")
        os.makedirs(os.path.join(dpa, "references"))
        shutil.copytree(os.path.dirname(built), os.path.join(dpa, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(root, "agents"))
        for a in agents:
            with open(os.path.join(root, "agents", f"{a}.md"), "w") as fh:
                fh.write(f"---\nname: {a}\ndescription: x\n---\n")
        for s in skills:
            os.makedirs(os.path.join(root, "skills", s), exist_ok=True)
            with open(os.path.join(root, "skills", s, "SKILL.md"), "w") as fh:
                fh.write("x\n")
        if skills:
            with open(os.path.join(dpa, "SKILL.md"), "w") as fh:
                fh.write("x\n")
        with open(os.path.join(dpa, "references", "stack-routing.md"), "w") as fh:
            fh.write(doc)
        return run(os.path.join(dpa, "scripts", "validate-stack-routing.py"))

    def table(rows):
        return run_doc(HEAD + rows)

    with open(built, "rb") as a, open(FORK, "rb") as b:
        check(a.read() == b.read(), "the built validate-stack-routing.py is the Cursor override")

    # ---- the shipped table
    r = run(built)
    check(r.returncode == 0 and "0 FAIL, 0 WARN" in r.stdout,
          "the built validator passes the built Cursor routing table with no WARN",
          (r.returncode, r.stdout))

    # ---- built-ins
    r = table("| search | `explore` then `generalPurpose` | — |\n")
    check(r.returncode == 0 and "0 FAIL, 0 WARN" in r.stdout,
          "`generalPurpose` and `explore` are Cursor's built-ins", (r.returncode, r.stdout))
    for name in ("general-purpose", "Explore"):
        r = table(f"| search | `{name}` | — |\n")
        check(r.returncode == 1 and name in r.stdout,
              f"`{name}` is not a Cursor built-in and fails", (r.returncode, r.stdout))

    # ---- bare names
    r = table("| review | `code-reviewer` | `applying-design-handoff` |\n")
    check(r.returncode == 0 and "0 FAIL, 0 WARN" in r.stdout,
          "a shipped agent and a shipped skill pass by bare name, with no WARN",
          (r.returncode, r.stdout))
    r = table("| review | `no-such-agent` | — |\n")
    check(r.returncode == 1 and "no-such-agent" in r.stdout,
          "a bare agent name not shipped here fails", (r.returncode, r.stdout))
    r = table("| review | `code-reviewer` | `no-such-skill` |\n")
    check(r.returncode == 1 and "no-such-skill" in r.stdout,
          "a bare skill name not shipped here fails", (r.returncode, r.stdout))

    # ---- namespaced ids
    r = table("| review | `planning:code-reviewer` | — |\n")
    check(r.returncode == 1 and "Cursor dispatches by the bare name 'code-reviewer'" in r.stdout,
          "`planning:<agent>` fails even though the agent ships here, naming the bare form",
          (r.returncode, r.stdout))
    r = table("| review | `code-reviewer` | `planning:applying-design-handoff` |\n")
    check(r.returncode == 1 and "planning:applying-design-handoff" in r.stdout,
          "`planning:<skill>` fails even though the skill ships here", (r.returncode, r.stdout))
    r = run_doc("| Step | Note |\n|---|---|\n| review | dispatch planning:code-reviewer |\n")
    check(r.returncode == 1 and "planning:code-reviewer" in r.stdout,
          "an unbackticked `planning:<agent>` in an untyped column fails",
          (r.returncode, r.stdout))
    r = table(f"| stack | `{SIBLING}` | — |\n")
    check(r.returncode == 1 and SIBLING in r.stdout and "names another plugin" in r.stdout,
          "another plugin's id fails", (r.returncode, r.stdout))

    # ---- nothing to validate against
    r = run_doc(HEAD + "| review | `code-reviewer` | — |\n", agents=(), skills=())
    check(r.returncode == 1 and "nothing can be validated" in r.stdout,
          "a plugin root with no agents or skills fails rather than passing empty",
          (r.returncode, r.stdout))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
sys.exit(1 if FAILS else 0)
