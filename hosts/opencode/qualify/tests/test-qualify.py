#!/usr/bin/env python3
"""The OpenCode qualify.py and its host-install-check.py branch, against a fake opencode
(no network, no model).

  run      a synthetic package plus a skills-only plugin dir pass every case, in the
           recorded install shape (a `plugin` entry for the package, `skills.paths` for the dir)
  mutants  each misbehaviour of the fake fails the case named for it, and the run: a skill
           left out, the agents left out, a stray command, an answer with no skill load,
           and a write into the owner's OpenCode config
  inputs   exit 2 for: a scratch home that is the owner's, a dir with no skills/, a package
           whose main module is missing, evidence inside a plugin dir, and no --model at
           the dispatcher
  check    host-install-check.py --host opencode runs the fake in a scratch home it deletes
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUALIFY = HERE.parent / "qualify.py"
FAKE = HERE / "fake_opencode.py"
REPO = HERE.parents[3]
CHECK = REPO / "scripts/host-install-check.py"
FAILS = []
LINGER_PLUGINS = []
EXTRA_LINGER_ARGS = ["--model", "stub/m"]


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def package(root, skills, agents=(), commands=(), main="./src/index.ts"):
    write(root / "package.json", json.dumps({"name": root.name, "main": main}) + "\n")
    write(root / "src/index.ts", "export default {};\n")
    for s in skills:
        write(root / f"skills/{s}/SKILL.md", f"---\nname: {s}\n---\n")
    for a in agents:
        write(root / f"agents/{a}.md", "---\nmode: subagent\n---\n")
    for c in commands:
        write(root / f"commands/{c}.md", "x\n")
    return root


def fake_bin(root, mode, owner, linger=""):
    path = root / f"bin-{mode}{linger}/opencode"
    write(path, f"#!/bin/sh\nFAKE_MODE={mode} FAKE_OWNER={owner} FAKE_LINGER={linger} exec {sys.executable} {FAKE} \"$@\"\n")
    path.chmod(0o755)
    return path


def qualify(work, tag, plugins, mode="ok", extra=(), home=None):
    owner = work / "owner"
    owner.mkdir(exist_ok=True)
    cred = work / "auth.json"
    write(cred, '{"token": "fake"}\n')
    args = [sys.executable, str(QUALIFY), "--run", "--home", str(home or work / f"h-{tag}"),
            "--workdir", str(work / f"w-{tag}"), "--owner-home", str(owner), "--model", "stub/m",
            "--credentials", str(cred), "--bin", str(fake_bin(work, mode, owner))]
    for d, n in plugins:
        args += ["--plugin", str(d), n]
    return subprocess.run(args + list(extra), capture_output=True, text=True, timeout=120)


def LINGER_RUN(work, tag):
    """One qualify run whose fake host leaves a background child behind."""
    owner = work / "owner"
    owner.mkdir(exist_ok=True)
    cred = work / "auth.json"
    write(cred, '{"token": "fake"}\n')
    args = [sys.executable, str(QUALIFY), "--run", "--home", str(work / "h-linger"),
            "--workdir", str(work / "w-linger"), "--owner-home", str(owner),
            "--credentials", str(cred), "--bin", str(fake_bin(work, "ok", owner, tag))]
    args += EXTRA_LINGER_ARGS
    for d, n in LINGER_PLUGINS:
        args += ["--plugin", str(d), n]
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def probe_id_case():
    """The backlog probe seeds an entry the backlog skill reads as one (`BL-` and three
    digits), and the answer check names that id, which the prompt does not carry: a
    placeholder such as BL-NNN is no entry, and an id the prompt gives away proves no read."""
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location("qualify_probe_id", QUALIFY)
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    pid = getattr(q, "PROBE_ID", "")
    check(re.fullmatch(r"BL-\d{3}", pid) is not None and pid not in q.BACKLOG_PROMPT,
          f"the backlog probe seeds a real entry id ({pid or 'none'}), absent from the prompt")


def no_proc_cases(work):
    """run_host on a machine with no /proc (macOS): the session is still found and killed,
    through ps, and the leader is not reaped before its session is scanned (a reaped
    leader's pid, the session id, could be reused)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("qualify_under_test", QUALIFY)
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    tag = f"np{os.getpid()}"
    real_listdir, real_kill = os.listdir, q.kill_session
    unreaped = []

    def no_proc(p=".", *a, **k):
        if str(p) == "/proc":
            raise FileNotFoundError(2, "No such file or directory", "/proc")
        return real_listdir(p, *a, **k)

    def kill_and_note(sid):
        try:
            unreaped.append(os.waitid(os.P_PID, sid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None)
        except ChildProcessError:
            unreaped.append(False)
        real_kill(sid)

    os.listdir, q.kill_session = no_proc, kill_and_note
    try:
        rc = q.run_host(["/bin/sh", "-c", f"{sys.executable} -c 'import time; time.sleep(600)' LINGER-{tag} & exit 0"],
                        str(work), dict(os.environ), 30, subprocess.DEVNULL)
    except Exception as e:  # the crash this case exists to catch
        rc = repr(e)
    finally:
        os.listdir, q.kill_session = real_listdir, real_kill
    got = subprocess.run(["pgrep", "-f", f"LINGER-{tag}"], capture_output=True, text=True)
    subprocess.run(["pkill", "-f", f"LINGER-{tag}"])
    check(rc == 0 and got.stdout.strip() == "",
          f"with no /proc, run_host returns the exit code and kills the session (rc={rc!r}, left={got.stdout.split()})")
    if hasattr(os, "waitid"):
        check(unreaped == [True], f"the leader is reaped only after its session is scanned ({unreaped})")


def main():
    with tempfile.TemporaryDirectory() as t:
        work = Path(t)
        pkg = package(work / "pkg", ["backlog", "brainstorming"], ["code-reviewer"], ["backlog"])
        pdir = work / "pdir"
        write(pdir / "skills/extra-x/SKILL.md", "---\nname: extra-x\n---\n")
        write(pdir / "commands/extra-x.md", "x\n")
        pl = [(pkg, "pkg"), (pdir, "pdir")]
        global LINGER_PLUGINS
        LINGER_PLUGINS = pl

        print("run")
        got = qualify(work, "ok", pl)
        check(got.returncode == 0, f"a package and a plugin dir pass every case (rc={got.returncode})\n{got.stdout}{got.stderr}")
        conf = json.loads((work / "h-ok/.config/opencode/opencode.json").read_text())
        root = str(work / "h-ok/.local/share/opencode-plugins")
        check(not (work / "h-ok/.local/share/opencode/auth.json").exists(),
              "the login copy is gone from the scratch home after the run")
        bare_pkg = package(work / "barepkg", ["backlog"])
        got = qualify(work, "barepkg", [(bare_pkg, "barepkg")])
        fails = [l for l in got.stdout.splitlines() if l.startswith(("FAIL agent-discovery", "FAIL command-discovery"))]
        check(got.returncode == 1 and len(fails) == 2 and all("nothing to compare" in l for l in fails),
              f"a package with no agents or commands fails both, nothing to compare (rc={got.returncode}) {fails}")
        check(conf.get("plugin") == [root + "/pkg/src/index.ts"]
              and conf.get("skills", {}).get("paths") == [root + "/pdir/skills"],
              f"opencode.json is in the recorded install shape: {conf}")

        print("mutants")
        for mode, case, why in (("miss", "skill-discovery", "emitted, not listed: "),
                                ("noagent", "agent-discovery", "code-reviewer"),
                                ("xcmd", "command-discovery", "listed, not emitted: stray"),
                                ("noskill", "backlog-skill", "never loaded backlog"),
                                ("owner", "owner-home-untouched", "changed")):
            got = qualify(work, mode, pl, mode)
            line = next((l for l in got.stdout.splitlines() if l.startswith(f"FAIL {case}")), "")
            check(got.returncode == 1 and why in line,
                  f"{mode}: fails {case} naming '{why}' (rc={got.returncode}) {line!r}")

        tag = f"q{os.getpid()}"
        owner = work / "owner"
        args = [sys.executable, str(QUALIFY)]
        got = subprocess.run(["pgrep", "-f", f"LINGER-{tag}"], capture_output=True, text=True)
        check(got.stdout.strip() == "", "no lingering fake child before the run")
        LINGER_RUN(work, tag)
        got = subprocess.run(["pgrep", "-f", f"LINGER-{tag}"], capture_output=True, text=True)
        check(got.stdout.strip() == "", f"a background child the host leaves is killed when its turn ends: {got.stdout.split()}")
        subprocess.run(["pkill", "-f", f"LINGER-{tag}"])
        no_proc_cases(work)
        probe_id_case()

        print("inputs")
        got = qualify(work, "own", pl, home=work / "owner")
        check(got.returncode == 2, f"the owner's own home exits 2 (rc={got.returncode})")
        bare = work / "bare"
        bare.mkdir()
        got = qualify(work, "bare", [(bare, "bare")])
        check(got.returncode == 2, f"a dir with no skills/ exits 2 (rc={got.returncode})")
        nomain = package(work / "nomain", ["a"], main="./src/missing.ts")
        got = qualify(work, "nomain", [(nomain, "nomain")])
        check(got.returncode == 2, f"a package whose main module is missing exits 2 (rc={got.returncode})")
        got = qualify(work, "ev", pl, extra=["--evidence", str(pkg / "evidence")])
        check(got.returncode == 2, f"evidence inside a plugin dir exits 2 (rc={got.returncode})")
        repo = work / "checkout"
        sub = package(repo / "packages" / "built", ["backlog"], ["a"], ["c"])
        subprocess.run(["git", "init", "-q", "--template=", str(repo)], check=True)
        got = qualify(work, "evco", [(sub, "built")], extra=["--evidence", str(repo / "docs" / "ev")])
        check(got.returncode == 2, f"evidence inside the git checkout holding a plugin exits 2 (rc={got.returncode})")
        got = subprocess.run([sys.executable, str(CHECK), "--host", "opencode", "--isolated"],
                             capture_output=True, text=True, timeout=60)
        check(got.returncode == 2 and "--model" in got.stderr,
              f"host-install-check --host opencode without --model exits 2 (rc={got.returncode})")

        print("check")
        tmp = work / "tmp"
        tmp.mkdir()
        env = dict(os.environ, TMPDIR=str(tmp))
        got = subprocess.run([sys.executable, str(CHECK), "--host", "opencode", "--isolated",
                              "--model", "stub/m", "--credentials", str(work / "auth.json"),
                              "--bin", str(fake_bin(work, "ok", work / "owner"))],
                             capture_output=True, text=True, env=env, timeout=300)
        check(got.returncode == 0, f"host-install-check --host opencode passes the real build against the fake "
                                   f"(rc={got.returncode})\n{got.stdout[-800:]}{got.stderr[-400:]}")
        check(not any(tmp.iterdir()), "host-install-check deletes its scratch home")
    if FAILS:
        print(f"{len(FAILS)} failure(s)")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
