#!/usr/bin/env python3
"""Qualify built OpenCode plugins by installing them into a throwaway HOME and asking OpenCode what loaded.

OpenCode has no plugin manifest. The recorded install shape (hosts/opencode/host.yaml
install_shape) is what this harness writes into the scratch HOME's opencode.json:
  - a package (a dir with package.json) is copied to
    <home>/.local/share/opencode-plugins/<name> and loaded by local path, an entry in
    `plugin` naming its `main`; its config hook adds its skills path, agents and commands;
  - a plugin dir without package.json (skills/ only) is copied the same way and its
    skills/ goes into `skills.paths`. Its commands and permission entries are that
    plugin's own installer's to write, so they are not installed or compared here.

Cases, in order:
  - the listings need no model: `opencode debug skill` must list, under the copies,
    exactly the skills each build emitted; `opencode debug config` must carry exactly the
    agents and the commands each package emitted. A set difference is printed and fails,
    and so does a build side with nothing to compare.
  - the backlog: `opencode run -m <model>` in a repo whose docs/backlog.md holds
    a `## BL-<three digits> — probe entry` heading (PROBE_ID) asks the backlog skill for the open entries. The transcript
    must show the skill tool loading `backlog`, and the answer must name that id. `opencode
    run` can refuse a tool call and still exit 0, so the transcript decides, not the exit.

The first --plugin is the one under test; later ones come in the same way, by argument,
so this code names no other plugin or repo.

Usage:
  qualify.py --run --home H --workdir D --plugin DIR NAME [--plugin DIR NAME]... --model ID
             [--credentials FILE] [--evidence E] [--bin BIN] [--owner-home O]

--run refuses the invoking user's own HOME (or --owner-home); scripts/host-install-check.py
--isolated is the caller that makes H a scratch dir. Every opencode call gets HOME=H and,
from the caller's environment, only PATH, the locale and TMPDIR. --credentials is the
OpenCode login file (default: the invoking user's ~/.local/share/opencode/auth.json); it is
copied, mode 600, to H/.local/share/opencode/auth.json and nowhere else, and removed when the
run ends (a SIGKILL leaves it). The invoking
user's ~/.config/opencode (opencode.json, opencode.jsonc, config.json, skills, commands,
agents, plugins) is hashed before and after, and a change fails the run. --evidence writes
E/results.json and the backlog transcript, and refuses a dir inside this repo or the git
checkout holding a plugin. Exit 0 when every case passed, 1 when one failed, 2 on an input this harness cannot
judge.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCHEMA = "opencode-qualify.v1"
TIMEOUT = 600
OWNER_FILES = ("opencode.json", "opencode.jsonc", "config.json", "skills", "commands", "agents",
               "plugins")
CASES = [
    ("install", "each plugin is copied byte for byte to <home>/.local/share/opencode-plugins/<name>"),
    ("skill-discovery", "`opencode debug skill` lists, under the copies, exactly the skills "
     "each build emitted"),
    ("agent-discovery", "`opencode debug config` carries exactly the agents each package emitted"),
    ("command-discovery", "`opencode debug config` carries exactly the commands each package "
     "emitted"),
    ("backlog-skill", "the backlog skill, run by name, loads through the skill tool and "
     "answers the probe id"),
    ("owner-home-untouched", "the invoking user's ~/.config/opencode hashes the same before "
     "and after"),
]
# The backlog probe's entry id: `BL-` and three digits, the form the backlog skill reads.
# Joined at run time so the source carries no register id of its own.
PROBE_ID = "BL-" + "417"
BACKLOG_PROMPT = ("Use the backlog skill to list the open entries in this repository's "
                  "backlog. Reply with the entry ids only.")


class Unjudgeable(Exception):
    pass


def checkout_root(path):
    """The git checkout that holds path, else path itself: evidence must stay out of it."""
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    top = r.stdout.strip()
    return Path(top).resolve() if r.returncode == 0 and top else Path(path).resolve()


def session_pids(sid):
    """Every live process in session sid: field 6 of /proc/<pid>/stat, or, with no /proc
    (macOS), each pid `ps` lists whose getsid is sid, as clean-machine-run.sh does."""
    try:
        entries = os.listdir("/proc")
    except OSError:
        entries = []
    if "self" not in entries:
        out = subprocess.run(["ps", "-A", "-o", "pid=,stat="], capture_output=True, text=True,
                             check=True).stdout
        pids = []
        for line in out.splitlines():
            f = line.split()
            if len(f) < 2 or f[1].startswith("Z"):
                continue
            try:
                if os.getsid(int(f[0])) == sid:
                    pids.append(int(f[0]))
            except (OSError, ValueError):
                pass
        return pids
    pids = []
    for d in entries:
        if not d.isdigit():
            continue
        try:
            stat = open(f"/proc/{d}/stat").read()
        except OSError:
            continue
        fields = stat[stat.rindex(")") + 2:].split()
        if len(fields) > 3 and fields[3] == str(sid) and fields[0] != "Z":
            pids.append(int(d))
    return pids


def kill_session(sid):
    """Kill every process left in the host call's session: the host starts workers (a
    worker server, language servers) that outlive the call, with the scratch HOME as
    theirs. Like clean-machine-run.sh's kill_session; a child that starts a session of
    its own escapes it."""
    for _ in range(50):
        pids = session_pids(sid)
        for p in pids:
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
        if not pids:
            return
        time.sleep(0.1)


def run_host(cmd, cwd, env, timeout, stdout):
    """(exit code or "timeout") for one host call, run as the leader of its own session
    and with that session killed afterwards."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=stdout, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    timed_out = False
    try:
        wait_unreaped(proc, timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        kill_session(proc.pid)
        rc = proc.wait()
    return "timeout" if timed_out else rc


def wait_unreaped(proc, timeout):
    """Wait for the leader to exit but leave it unreaped where os.waitid allows: while it
    is a zombie its pid, the session id kill_session scans for, cannot be reused."""
    if not hasattr(os, "waitid"):
        proc.wait(timeout=timeout)
        return
    deadline = time.monotonic() + timeout
    while os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        time.sleep(0.05)


def tree_hashes(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in ("__pycache__", "node_modules"))
        for f in filenames:
            p = Path(dirpath) / f
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def owner_fingerprint(home):
    h = hashlib.sha256()
    base = home / ".config" / "opencode"
    for name in OWNER_FILES:
        top = base / name
        if top.is_file():
            h.update(f"{top}\0{hashlib.sha256(top.read_bytes()).hexdigest()}\n".encode())
        elif top.is_dir():
            for rel, digest in sorted(tree_hashes(top).items()):
                h.update(f"{top}/{rel}\0{digest}\n".encode())
    return h.hexdigest()


def package_main(d):
    """A package's entry module, relative to its dir, or None for a skills-only plugin dir."""
    pj = d / "package.json"
    if not pj.is_file():
        return None
    try:
        doc = json.loads(pj.read_text())
    except ValueError:
        raise Unjudgeable(f"{pj} is not JSON")
    main = doc.get("main") if isinstance(doc, dict) else None
    if not isinstance(main, str) or not (d / main).is_file():
        raise Unjudgeable(f"{pj} names no main module that exists")
    return main


def stems(d, pattern="*.md"):
    return sorted(p.stem for p in d.glob(pattern)) if d.is_dir() else []


def emitted_skills(out):
    d = out / "skills"
    return sorted(p.name for p in d.iterdir() if (p / "SKILL.md").is_file()) if d.is_dir() else []


def init_repo(path, env):
    path.mkdir(parents=True)
    for cmd in (["git", "init", "-q", "--template="], ["git", "config", "user.name", "Qualify"],
                ["git", "config", "user.email", "qualify@example.com"]):
        subprocess.run(cmd, cwd=path, env=env, check=True, capture_output=True)


class Run:
    def __init__(self, args, plugins):
        self.args, self.plugins = args, plugins
        self.home = Path(args.home).resolve()
        self.work = Path(args.workdir).resolve()
        self.root = self.home / ".local" / "share" / "opencode-plugins"
        self.cases, self.transcripts = [], {}
        keep = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
        self.env = {**keep, "HOME": str(self.home), "TERM": "dumb"}

    def record(self, case, ok, detail=""):
        self.cases.append({"case": case, "status": "passed" if ok else "failed",
                           "detail": detail})
        print(f"{'ok  ' if ok else 'FAIL'} {case}" + (f": {detail}" if detail else ""))

    def opencode(self, cwd, *args, timeout=TIMEOUT):
        """(stdout, exit). stdout goes to a file, not a pipe: a large listing piped to a
        reader came back cut short."""
        out = self.work / f".out-{os.getpid()}"
        with open(out, "w") as fh:
            rc = run_host([self.args.bin, *args], cwd, self.env, timeout, fh)
        text = out.read_text(errors="replace")
        out.unlink()
        return text, rc

    def run(self, owner_home):
        before = owner_fingerprint(owner_home)
        self.work.mkdir(parents=True, exist_ok=True)
        cred = self.home / ".local" / "share" / "opencode" / "auth.json"
        cred.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            shutil.copyfile(self.args.credentials, cred)
        finally:
            os.umask(old)
        os.chmod(cred, 0o600)
        try:
            self.install()
            self.listings()
            self.backlog()
        finally:
            # The login copy lives only while the host runs: a kept or reused scratch
            # HOME never holds it afterwards.
            cred.unlink(missing_ok=True)
        after = owner_fingerprint(owner_home)
        self.record("owner-home-untouched", before == after,
                    "" if before == after else "the invoking user's OpenCode config changed")
        status = "passed" if all(c["status"] == "passed" for c in self.cases) else "failed"
        return {"schema": SCHEMA, "status": status, "cases": self.cases,
                "plugins": [{"dir": str(d), "name": n} for d, n, _ in self.plugins]}

    def install(self):
        problems, conf = [], {"$schema": "https://opencode.ai/config.json", "plugin": [],
                              "skills": {"paths": []}}
        for src, name, main in self.plugins:
            dest = self.root / name
            if dest.exists():
                problems.append(f"{name}: {dest} already exists")
                continue
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
            if tree_hashes(dest) != tree_hashes(src):
                problems.append(f"{name}: the copy differs from the build")
            if main:
                conf["plugin"].append(str(dest / main))
            else:
                conf["skills"]["paths"].append(str(dest / "skills"))
        cfg = self.home / ".config" / "opencode" / "opencode.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(conf, indent=2) + "\n")
        self.record("install", not problems, "; ".join(problems))

    def listings(self):
        repo = self.work / "listing"
        init_repo(repo, self.env)
        text, rc = self.opencode(repo, "debug", "skill", timeout=180)
        try:
            skills = json.loads(text)
        except ValueError:
            skills = None
        if rc != 0 or not isinstance(skills, list):
            self.record("skill-discovery", False, f"`opencode debug skill` gave no JSON list (exit {rc})")
        else:
            prefix = str(self.root) + os.sep
            listed = set()
            for s in skills:
                loc = os.path.normpath(s.get("location", "")) if isinstance(s, dict) else ""
                parts = loc[len(prefix):].split(os.sep) if loc.startswith(prefix) else []
                if len(parts) == 4 and parts[1] == "skills" and parts[3] == "SKILL.md":
                    listed.add((parts[0], parts[2]))
            want = {(n, s) for d, n, _ in self.plugins for s in emitted_skills(d)}
            self.diff("skill-discovery", want, listed, lambda x: f"{x[0]}/{x[1]}")
        text, rc = self.opencode(repo, "debug", "config", timeout=180)
        try:
            conf = json.loads(text)
        except ValueError:
            conf = None
        if rc != 0 or not isinstance(conf, dict):
            self.record("agent-discovery", False, f"`opencode debug config` gave no JSON (exit {rc})")
            self.record("command-discovery", False, "`opencode debug config` gave no JSON")
            return
        packages = [d for d, _, main in self.plugins if main]
        self.diff("agent-discovery", {a for d in packages for a in stems(d / "agents")},
                  set(conf.get("agent") or {}), str)
        self.diff("command-discovery", {c for d in packages for c in stems(d / "commands")},
                  set(conf.get("command") or {}), str)

    def diff(self, case, want, have, show):
        missing, extra = sorted(want - have), sorted(have - want)
        self.record(case, bool(want) and not missing and not extra, "; ".join(x for x in (
            not want and "the builds emitted none: nothing to compare",
            missing and "emitted, not listed: " + ", ".join(map(show, missing)),
            extra and "listed, not emitted: " + ", ".join(map(show, extra))) if x))

    def backlog(self):
        repo = self.work / "backlog"
        init_repo(repo, self.env)
        (repo / "docs").mkdir()
        (repo / "docs" / "backlog.md").write_text(
            f"# Backlog\n\n## {PROBE_ID} — probe entry\n\n- **Added:** 2026-01-01\n"
            "- **What:** a probe entry.\n")
        for cmd in (["git", "add", "-A"], ["git", "-c", "core.hooksPath=/dev/null", "commit", "-q",
                                           "-m", "qualify: seed"]):
            subprocess.run(cmd, cwd=repo, env=self.env, check=True, capture_output=True)
        text, rc = self.opencode(repo, "run", "-m", self.args.model, "--format", "json",
                                 BACKLOG_PROMPT)
        self.transcripts["backlog"] = text
        loaded, answer = False, []
        for line in text.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            part = e.get("part") if isinstance(e, dict) else None
            if not isinstance(part, dict):
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            if part.get("type") == "tool" and part.get("tool") == "skill" \
                    and (state.get("input") or {}).get("name") == "backlog" \
                    and state.get("status") == "completed":
                loaded = True
            elif part.get("type") == "text" and isinstance(part.get("text"), str):
                answer.append(part["text"])
        why = [w for w, bad in ((f"exit {rc}", rc != 0),
                                ("the skill tool never loaded backlog", not loaded),
                                (f"the answer does not name {PROBE_ID}", PROBE_ID not in "".join(answer)))
               if bad]
        self.record("backlog-skill", not why, "; ".join(why))


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="store_true", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--plugin", nargs=2, action="append", metavar=("DIR", "NAME"), required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--credentials")
    ap.add_argument("--evidence", metavar="DIR")
    ap.add_argument("--bin", default="opencode")
    ap.add_argument("--owner-home")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    try:
        owner = Path(args.owner_home or Path.home()).resolve()
        home = Path(args.home).resolve()
        if home == owner:
            raise Unjudgeable(f"--home {home} is the invoking user's own HOME")
        args.credentials = args.credentials or str(owner / ".local/share/opencode/auth.json")
        if not os.path.isfile(args.credentials):
            raise Unjudgeable("the OpenCode login file is not a file (give --credentials)")
        if shutil.which(args.bin) is None and not os.access(args.bin, os.X_OK):
            raise Unjudgeable(f"{args.bin} is not on PATH")
        args.bin = shutil.which(args.bin) or str(Path(args.bin).absolute())
        plugins = []
        for d, name in args.plugin:
            p = Path(d).resolve()
            if not p.is_dir() or not (p / "skills").is_dir():
                raise Unjudgeable(f"{p} is not a built OpenCode plugin (no skills/)")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                raise Unjudgeable(f"plugin name {name!r} is not a directory name")
            plugins.append((p, name, package_main(p)))
        if args.evidence:
            ev = Path(args.evidence).resolve()
            for root in [REPO] + [checkout_root(p) for p, _, _ in plugins]:
                if ev == root or root in ev.parents:
                    raise Unjudgeable(f"--evidence {ev} is inside {root}; transcripts carry scratch paths")
        run = Run(args, plugins)
        evidence = run.run(owner)
    except Unjudgeable as e:
        print(f"qualify: {e}", file=sys.stderr)
        return 2
    if args.evidence:
        out = Path(args.evidence)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")
        for name, text in run.transcripts.items():
            (out / f"transcript-{name}.jsonl").write_text(text)
    print(f"qualify: {evidence['status']} — "
          f"{sum(c['status'] == 'passed' for c in evidence['cases'])} passed, "
          f"{sum(c['status'] == 'failed' for c in evidence['cases'])} failed")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
