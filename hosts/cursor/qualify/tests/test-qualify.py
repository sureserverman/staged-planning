#!/usr/bin/env python3
"""The Cursor qualify.py and its host-install-check.py branch, against a fake cursor-agent
(no network, no model).

  run      a synthetic plugin plus a second one pass every case; a slash-only skill is
           reported and not compared
  mutants  each misbehaviour of the fake fails the case named for it, and the run: a skill
           left out of or added to the listing, the agents left out, an answer with no
           read of the backlog skill, a doubled dispatch line, no dispatch line, and a
           write into the owner's Cursor hooks
  inputs   exit 2 for: a scratch home that is the owner's, a dir that is not a built Cursor
           plugin, evidence inside a plugin dir, and a missing login file
  check    host-install-check.py --host cursor runs the fake in a scratch home it deletes
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUALIFY = HERE.parent / "qualify.py"
FAKE = HERE / "fake_cursor_agent.py"
REPO = HERE.parents[3]
CHECK = REPO / "scripts/host-install-check.py"
FAILS = []
LINGER_PLUGINS = []
EXTRA_LINGER_ARGS = []


def check(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def plugin(root, name, skills, agents=(), slash=()):
    write(root / ".cursor-plugin/plugin.json", json.dumps({"name": name}) + "\n")
    for s in skills:
        write(root / f"skills/{s}/SKILL.md", f"---\nname: {s}\ndescription: x\n---\n")
    for s in slash:
        write(root / f"skills/{s}/SKILL.md",
              f"---\nname: {s}\ndescription: x\ndisable-model-invocation: true\n---\n")
    for a in agents:
        write(root / f"agents/{a}.md", f"---\nname: {a}\ndescription: x\n---\n")
    return root


def fake_bin(root, mode, owner, linger=""):
    """qualify.py passes no FAKE_* through, so the mode is baked into the wrapper."""
    path = root / f"bin-{mode}{linger}/cursor-agent"
    write(path, f"#!/bin/sh\nFAKE_MODE={mode} FAKE_OWNER={owner} FAKE_LINGER={linger} exec {sys.executable} {FAKE} \"$@\"\n")
    path.chmod(0o755)
    return path


def qualify(work, tag, plugins, mode="ok", extra=()):
    owner = work / "owner"
    owner.mkdir(exist_ok=True)
    cred = work / "auth.json"
    write(cred, '{"token": "fake"}\n')
    args = [sys.executable, str(QUALIFY), "--run", "--home", str(work / f"h-{tag}"),
            "--workdir", str(work / f"w-{tag}"), "--owner-home", str(owner),
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
        p1 = plugin(work / "p1", "toy", ["backlog", "brainstorming"], ["code-reviewer"],
                    slash=["hooks"])
        p2 = plugin(work / "p2", "other", ["other-skill"])
        pl = [(p1, "toy"), (p2, "other")]
        global LINGER_PLUGINS
        LINGER_PLUGINS = pl

        print("run")
        got = qualify(work, "ok", pl)
        check(got.returncode == 0, f"two plugins pass every case (rc={got.returncode})\n{got.stdout}{got.stderr}")
        check("slash-only, not listable: toy/hooks" in got.stdout,
              "a disable-model-invocation skill is reported as slash-only")
        check(not (work / "h-ok/.config/cursor/auth.json").exists(),
              "the login copy is gone from the scratch home after the run")
        noag = plugin(work / "noag", "noag", ["backlog"])
        got = qualify(work, "noag", [(noag, "noag")])
        line = next((l for l in got.stdout.splitlines() if l.startswith("FAIL agent-discovery")), "")
        check(got.returncode == 1 and "nothing to compare" in line,
              f"a build with no agents fails agent-discovery, nothing to compare (rc={got.returncode}) {line!r}")

        got = qualify(work, "roots", pl, "roots")
        check(got.returncode == 0, f"skill paths written as root variables with root lines are expanded "
                                   f"(rc={got.returncode})\n{got.stdout}")

        print("mutants")
        for mode, case, why in (("miss", "skill-discovery", "emitted, not listed: "),
                                ("extra", "skill-discovery", "/never-built"),
                                ("noagent", "agent-discovery", "code-reviewer"),
                                ("bareroots", "skill-discovery", "emitted, not listed: "),
                                ("noread", "backlog-skill", "was not read"),
                                ("double", "dispatch-once", "doubled"),
                                ("nolog", "dispatch-once", "no dispatch line"),
                                ("notask", "dispatch-once", "no Task call"),
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

        print("inputs")
        owner = work / "owner"
        args = [sys.executable, str(QUALIFY), "--run", "--home", str(owner), "--workdir",
                str(work / "wx"), "--owner-home", str(owner), "--plugin", str(p1), "toy",
                "--credentials", str(work / "auth.json"), "--bin", str(fake_bin(work, "ok", owner))]
        got = subprocess.run(args, capture_output=True, text=True, timeout=60)
        check(got.returncode == 2, f"the owner's own home exits 2 (rc={got.returncode})")
        bare = work / "bare"
        bare.mkdir()
        got = qualify(work, "bare", [(bare, "bare")])
        check(got.returncode == 2, f"a dir that is not a built Cursor plugin exits 2 (rc={got.returncode})")
        got = qualify(work, "ev", pl, extra=["--evidence", str(p1 / "evidence")])
        check(got.returncode == 2, f"evidence inside a plugin dir exits 2 (rc={got.returncode})")
        repo = work / "checkout"
        sub = plugin(repo / "ports" / "built", "built", ["backlog"], ["code-reviewer"])
        subprocess.run(["git", "init", "-q", "--template=", str(repo)], check=True)
        got = qualify(work, "evco", [(sub, "built")], extra=["--evidence", str(repo / "docs" / "ev")])
        check(got.returncode == 2, f"evidence inside the git checkout holding a plugin exits 2 (rc={got.returncode})")
        got = subprocess.run([sys.executable, str(QUALIFY), "--run", "--home", str(work / "hc"),
                              "--workdir", str(work / "wc"), "--owner-home", str(owner),
                              "--plugin", str(p1), "toy", "--credentials", str(work / "none.json"),
                              "--bin", str(fake_bin(work, "ok", owner))],
                             capture_output=True, text=True, timeout=60)
        check(got.returncode == 2, f"a missing login file exits 2 (rc={got.returncode})")

        print("check")
        tmp = work / "tmp"
        tmp.mkdir()
        env = dict(os.environ, TMPDIR=str(tmp))
        got = subprocess.run([sys.executable, str(CHECK), "--host", "cursor", "--isolated",
                              "--credentials", str(work / "auth.json"),
                              "--bin", str(fake_bin(work, "ok", owner))],
                             capture_output=True, text=True, env=env, timeout=300)
        check(got.returncode == 0, f"host-install-check --host cursor passes the real build against the fake "
                                   f"(rc={got.returncode})\n{got.stdout[-800:]}{got.stderr[-400:]}")
        check(not any(tmp.iterdir()), "host-install-check deletes its scratch home")
    if FAILS:
        print(f"{len(FAILS)} failure(s)")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
