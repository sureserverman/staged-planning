#!/usr/bin/env python3
"""Qualify built Cursor plugins by installing them into a throwaway HOME and asking Cursor what loaded.

Cursor has no plugin command: a local plugin is a directory under
~/.cursor/plugins/local/<name>. This harness copies each plugin there, then runs three
headless `cursor-agent -p` turns in scratch git repos (a model answers each):
  - the listing: the session prints every skill it was given, with the SKILL.md path
    Cursor gave it (a path Cursor gives relative to a root variable such as $1 is
    expanded), and every custom subagent it can launch. Skills under the local plugin
    dir are compared, as sets, with the model-invocable skills each build emitted
    (Cursor gives the session no skill whose front matter sets disable-model-invocation:
    true; those run only as /<name> and are reported, not compared). Agents are compared
    with the agents/*.md each build emitted, one-sided: the session also lists Cursor's
    own and other plugins' agents, with no path to tell them apart. A difference is
    printed and fails the case, and so does a build side with nothing to compare.
  - the backlog: in a repo whose docs/backlog.md holds a `## BL-<three digits> — probe entry` heading (PROBE_ID), the
    backlog skill is asked for the open entries. The answer must name that id, and the
    transcript must show the session reading the backlog skill's own SKILL.md from the
    first plugin (Cursor loads a skill by reading it).
  - the dispatch: in a repo with a plan in flight, the session launches one subagent.
    The plugin's preToolUse(Task) hook must leave exactly one `dispatch` line per
    tool_use_id in .claude/dispatch-log.jsonl, matched to the Task calls the transcript
    shows. Zero lines fail, a doubled line fails (one call logged by two hook
    registrations), and so does a transcript showing no Task call.

The first --plugin is the one under test (its backlog skill, its dispatch hook); later
ones come in the same way, by argument, so this code names no other plugin or repo.

Usage:
  qualify.py --run --home H --workdir D --plugin DIR NAME [--plugin DIR NAME]...
             [--credentials FILE] [--model ID] [--evidence E] [--bin BIN]
             [--owner-home O]

--run refuses the invoking user's own HOME (or --owner-home); scripts/host-install-check.py
--isolated is the caller that makes H a scratch dir. Every cursor-agent call gets HOME=H
and, from the caller's environment, only PATH, the locale and TMPDIR. --credentials is the
Cursor login file (default: the invoking user's ~/.config/cursor/auth.json); it is copied,
mode 600, to H/.config/cursor/auth.json and nowhere else, and removed when the run ends
(a SIGKILL leaves it). The invoking user's
~/.cursor/hooks.json and ~/.cursor/plugins/local are hashed before and after, and a change
fails the run (Cursor's own plugin cache is left out: Cursor syncs it by itself).
--evidence writes E/results.json and the three transcripts, and refuses a dir inside this
repo or the git checkout holding a plugin: transcripts carry scratch paths. Exit 0 when
every case passed, 1 when one failed, 2 on an input this harness cannot judge.
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
SCHEMA = "cursor-qualify.v1"
TIMEOUT = 600
CASES = [
    ("install", "each plugin is copied byte for byte to <home>/.cursor/plugins/local/<name>"),
    ("skill-discovery", "the skills listed under the local plugin dir are exactly the "
     "model-invocable skills each build emitted (a disable-model-invocation skill is slash-only "
     "and never listed)"),
    ("agent-discovery", "every agent each build emitted is listed as launchable"),
    ("backlog-skill", "the backlog skill, run by name, reads its own SKILL.md from the first "
     "plugin and answers the probe id"),
    ("dispatch-once", "one subagent launch leaves exactly one dispatch line per tool_use_id"),
    ("owner-home-untouched", "the invoking user's ~/.cursor/hooks.json and plugins/local hash "
     "the same before and after"),
]
LIST_PROMPT = (
    "Do not invoke any skill, do not read any file and do not run any tool. Print a line "
    "BEGIN-LIST. If your skill paths are given relative to root variables such as $0 or $1, "
    "first print one line `root <variable> <the full folder it stands for>` for each. Then, "
    "for every skill you were given, one line `skill <the full path of its SKILL.md>`, with "
    "any root variable replaced by its folder. Then, for every custom subagent your Task tool "
    "can launch (leave out the built-in ones), one line `agent <its name>`. Then a line "
    "END-LIST, and nothing else.")
# The backlog probe's entry id: `BL-` and three digits, the form the backlog skill reads.
# Joined at run time so the source carries no register id of its own.
PROBE_ID = "BL-" + "417"
BACKLOG_PROMPT = ("Use the backlog skill to list the open entries in this repository's "
                  "backlog. Reply with the entry ids only.")
DISPATCH_PROMPT = (
    "Use your Task tool exactly once: launch the code-reviewer subagent with the prompt "
    "`Reply with exactly REVIEW-OK and do nothing else.` Launch no other subagent, run no "
    "shell command and edit no file. When it returns, stop.")
PROBE_PLAN = """# Light Plan: dispatch probe

## Stage 1: Probe

### Task 1.1: Probe
- **Status:** [ ]
- **Test:** `true`

### Stage 1 Gate
- [ ] `true`
"""


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
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for f in filenames:
            p = Path(dirpath) / f
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def owner_fingerprint(home):
    h = hashlib.sha256()
    for top in (home / ".cursor" / "hooks.json", home / ".cursor" / "plugins" / "local"):
        if top.is_file():
            h.update(f"{top}\0{hashlib.sha256(top.read_bytes()).hexdigest()}\n".encode())
        elif top.is_dir():
            for rel, digest in sorted(tree_hashes(top).items()):
                h.update(f"{top}/{rel}\0{digest}\n".encode())
    return h.hexdigest()


def emitted_skills(out):
    """(model-invocable, slash-only) skill names. Cursor keeps a skill whose front matter sets
    `disable-model-invocation: true` out of the session's skill list: it runs only as
    /<name>, so a listing cannot show it."""
    d = out / "skills"
    shown, hidden = [], []
    for p in sorted(d.iterdir()) if d.is_dir() else []:
        if (p / "SKILL.md").is_file():
            head = (p / "SKILL.md").read_text(errors="replace").split("\n---", 1)[0]
            slash = re.search(r"^disable-model-invocation:\s*true\s*$", head, re.M)
            (hidden if slash else shown).append(p.name)
    return shown, hidden


def emitted_agents(out):
    names = []
    for p in sorted((out / "agents").glob("*.md")) if (out / "agents").is_dir() else []:
        m = re.search(r"^name:\s*['\"]?([A-Za-z0-9._-]+)", p.read_text(errors="replace"), re.M)
        names.append(m.group(1) if m else p.stem)
    return names


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for v in node.values():
            walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            walk(v, fn)


def events(text):
    for line in text.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def answer_text(text):
    """The session's final answer: the result event's text, else every assistant text."""
    result, parts = None, []
    for e in events(text):
        if isinstance(e, dict) and e.get("type") == "result" and isinstance(e.get("result"), str):
            result = e["result"]
        elif isinstance(e, dict) and e.get("type") == "assistant":
            walk(e.get("message"), lambda n: parts.append(n["text"])
                 if n.get("type") == "text" and isinstance(n.get("text"), str) else None)
    return result if result is not None else "".join(parts)


def skill_reads(text):
    """Paths of SKILL.md files the session read successfully (readToolCall)."""
    reads = []

    def fn(n):
        rtc = n.get("readToolCall")
        if isinstance(rtc, dict) and isinstance(rtc.get("args"), dict) \
                and isinstance(rtc["args"].get("path"), str) \
                and isinstance(rtc.get("result"), dict) and "success" in rtc["result"]:
            reads.append(os.path.normpath(rtc["args"]["path"]))
    for e in events(text):
        walk(e, fn)
    return reads


def task_call_ids(text):
    """The call ids of the Task tool calls the transcript shows started."""
    ids = []

    def fn(n):
        tc = n.get("tool_call")
        if n.get("subtype") == "started" and isinstance(tc, dict) and "taskToolCall" in tc \
                and isinstance(n.get("call_id"), str) and n["call_id"] not in ids:
            ids.append(n["call_id"])
    for e in events(text):
        walk(e, fn)
    return ids


def init_repo(path, env):
    path.mkdir(parents=True)
    for cmd in (["git", "init", "-q", "--template="], ["git", "config", "user.name", "Qualify"],
                ["git", "config", "user.email", "qualify@example.com"]):
        subprocess.run(cmd, cwd=path, env=env, check=True, capture_output=True)


def commit_all(path, env):
    for cmd in (["git", "add", "-A"], ["git", "-c", "core.hooksPath=/dev/null", "commit", "-q",
                                       "-m", "qualify: seed"]):
        subprocess.run(cmd, cwd=path, env=env, check=True, capture_output=True)


class Run:
    def __init__(self, args, plugins):
        self.args, self.plugins = args, plugins
        self.home = Path(args.home).resolve()
        self.work = Path(args.workdir).resolve()
        self.local = self.home / ".cursor" / "plugins" / "local"
        self.cases, self.transcripts = [], {}
        keep = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
        self.env = {**keep, "HOME": str(self.home), "TERM": "dumb"}

    def record(self, case, ok, detail=""):
        self.cases.append({"case": case, "status": "passed" if ok else "failed",
                           "detail": detail})
        print(f"{'ok  ' if ok else 'FAIL'} {case}" + (f": {detail}" if detail else ""))

    def agent(self, name, cwd, prompt):
        cmd = [self.args.bin, "-p", "--trust", "--force", "--output-format", "stream-json"]
        if self.args.model:
            cmd += ["--model", self.args.model]
        log = self.work / f".out-{name}"
        with open(log, "w") as fh:
            rc = run_host(cmd + [prompt], cwd, self.env, TIMEOUT, fh)
        out = log.read_text(errors="replace")
        log.unlink()
        self.transcripts[name] = out
        return out, rc

    def run(self, owner_home):
        before = owner_fingerprint(owner_home)
        cred = self.home / ".config" / "cursor" / "auth.json"
        cred.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            shutil.copyfile(self.args.credentials, cred)
        finally:
            os.umask(old)
        os.chmod(cred, 0o600)
        try:
            self.install()
            self.listing()
            self.backlog()
            self.dispatch()
        finally:
            # The login copy lives only while the host runs: a kept or reused scratch
            # HOME never holds it afterwards.
            cred.unlink(missing_ok=True)
        after = owner_fingerprint(owner_home)
        self.record("owner-home-untouched", before == after,
                    "" if before == after else "the invoking user's Cursor hooks or local plugins changed")
        status = "passed" if all(c["status"] == "passed" for c in self.cases) else "failed"
        return {"schema": SCHEMA, "status": status, "cases": self.cases,
                "plugins": [{"dir": str(d), "name": n} for d, n in self.plugins]}

    def install(self):
        problems = []
        for src, name in self.plugins:
            dest = self.local / name
            if dest.exists():
                problems.append(f"{name}: {dest} already exists")
                continue
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
            if tree_hashes(dest) != tree_hashes(src):
                problems.append(f"{name}: the copy differs from the build")
        self.record("install", not problems, "; ".join(problems))

    def listing(self):
        repo = self.work / "listing"
        init_repo(repo, self.env)
        out, rc = self.agent("listing", repo, LIST_PROMPT)
        text = answer_text(out)
        m = re.search(r"BEGIN-LIST\s*\n(.*?)\n\s*END-LIST", text, re.S)
        if rc != 0 or not m:
            self.record("skill-discovery", False, f"no listing came back (exit {rc})")
            self.record("agent-discovery", False, "no listing came back")
            return
        lines = [l.strip().strip("`").strip() for l in m.group(1).splitlines()]
        prefix = str(self.local) + os.sep
        listed, agents, roots = set(), set(), {}
        # Cursor may give skill paths relative to root variables ($0/<skill>/SKILL.md, a
        # root standing for a skills folder); a path still written that way is expanded.
        for l in lines:
            m2 = re.match(r"root\s+(\$\d+)\s+(\S.*)$", l)
            if m2:
                roots[m2.group(1)] = m2.group(2).strip().strip("`").rstrip("/")
        for l in lines:
            if l.startswith("skill "):
                raw = l[6:].strip().strip("`")
                m2 = re.match(r"(\$\d+)(/.*)$", raw)
                if m2 and m2.group(1) in roots:
                    raw = roots[m2.group(1)] + m2.group(2)
                p = os.path.normpath(raw)
                parts = p[len(prefix):].split(os.sep) if p.startswith(prefix) else []
                if len(parts) == 4 and parts[1] == "skills" and parts[3] == "SKILL.md":
                    listed.add((parts[0], parts[2]))
            elif l.startswith("agent "):
                agents.add(l[6:].strip().strip("`").split(":")[-1])
        want = {(n, s) for d, n in self.plugins for s in emitted_skills(Path(d))[0]}
        slash = sorted(f"{n}/{s}" for d, n in self.plugins for s in emitted_skills(Path(d))[1])
        missing, extra = sorted(want - listed), sorted(listed - want)
        self.record("skill-discovery", bool(want) and not missing and not extra,
                    "; ".join(x for x in (
                        not want and "the builds emitted no model-invocable skill: nothing to compare",
                        missing and "emitted, not listed: " + ", ".join(f"{n}/{s}" for n, s in missing),
                        extra and "listed, not emitted: " + ", ".join(f"{n}/{s}" for n, s in extra),
                        slash and "slash-only, not listable: " + ", ".join(slash)) if x))
        # One-sided: the session also lists Cursor's built-in agents and other plugins'
        # agents, with no path to tell them apart, so only a missing agent is a finding.
        want_agents = {a for d, _ in self.plugins for a in emitted_agents(Path(d))}
        gone = sorted(want_agents - agents)
        self.record("agent-discovery", bool(want_agents) and not gone,
                    "the builds emitted no agent: nothing to compare" if not want_agents
                    else "emitted, not listed: " + ", ".join(gone) if gone else "")

    def backlog(self):
        repo = self.work / "backlog"
        init_repo(repo, self.env)
        (repo / "docs").mkdir()
        (repo / "docs" / "backlog.md").write_text(
            f"# Backlog\n\n## {PROBE_ID} — probe entry\n\n- **Added:** 2026-01-01\n"
            "- **What:** a probe entry.\n")
        commit_all(repo, self.env)
        out, rc = self.agent("backlog", repo, BACKLOG_PROMPT)
        own = os.path.normpath(str(self.local / self.plugins[0][1] / "skills" / "backlog" / "SKILL.md"))
        read = own in skill_reads(out)
        named = PROBE_ID in answer_text(out)
        why = [w for w, bad in ((f"exit {rc}", rc != 0),
                                ("the backlog skill's SKILL.md was not read", not read),
                                (f"the answer does not name {PROBE_ID}", not named)) if bad]
        self.record("backlog-skill", not why, "; ".join(why))

    def dispatch(self):
        repo = self.work / "dispatch"
        init_repo(repo, self.env)
        (repo / "docs" / "plans").mkdir(parents=True)
        (repo / "docs" / "plans" / "probe-light-plan.md").write_text(PROBE_PLAN)
        commit_all(repo, self.env)
        (repo / ".claude").mkdir()
        (repo / ".claude" / "plan-progress.json").write_text(json.dumps(
            {"plan": "docs/plans/probe-light-plan.md", "phase": "task", "stage": 1,
             "task": "1.1", "task_desc": "probe"}) + "\n")
        out, rc = self.agent("dispatch", repo, DISPATCH_PROMPT)
        log = repo / ".claude" / "dispatch-log.jsonl"
        rows = []
        for line in (log.read_text(errors="replace").splitlines() if log.is_file() else []):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("event") == "dispatch":
                rows.append(row)
        ids = [r.get("tool_use_id") for r in rows]
        calls = task_call_ids(out)
        why = []
        if not rows:
            why.append(f"no dispatch line was logged (exit {rc}; {len(calls)} Task call(s) in the transcript)")
        if any(not isinstance(i, str) or not i for i in ids):
            why.append("a dispatch line carries no tool_use_id")
        doubled = sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1})
        if doubled:
            why.append("doubled dispatch line(s) for " + ", ".join(doubled))
        if not calls:
            why.append("the transcript shows no Task call, so the log cannot be matched to one")
        elif len(set(ids)) != len(calls):
            why.append(f"{len(set(ids))} logged id(s) for {len(calls)} Task call(s)")
        self.record("dispatch-once", not why, "; ".join(why))


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="store_true", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--plugin", nargs=2, action="append", metavar=("DIR", "NAME"), required=True)
    ap.add_argument("--credentials")
    ap.add_argument("--model")
    ap.add_argument("--evidence", metavar="DIR")
    ap.add_argument("--bin", default="cursor-agent")
    ap.add_argument("--owner-home")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    try:
        owner = Path(args.owner_home or Path.home()).resolve()
        home = Path(args.home).resolve()
        if home == owner:
            raise Unjudgeable(f"--home {home} is the invoking user's own HOME")
        args.credentials = args.credentials or str(owner / ".config" / "cursor" / "auth.json")
        if not os.path.isfile(args.credentials):
            raise Unjudgeable("the Cursor login file is not a file (give --credentials)")
        if shutil.which(args.bin) is None and not os.access(args.bin, os.X_OK):
            raise Unjudgeable(f"{args.bin} is not on PATH")
        args.bin = shutil.which(args.bin) or str(Path(args.bin).absolute())
        plugins = []
        for d, name in args.plugin:
            p = Path(d).resolve()
            if not (p / ".cursor-plugin" / "plugin.json").is_file() or not (p / "skills").is_dir():
                raise Unjudgeable(f"{p} is not a built Cursor plugin (no .cursor-plugin/plugin.json or skills/)")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                raise Unjudgeable(f"plugin name {name!r} is not a directory name")
            plugins.append((p, name))
        if args.evidence:
            ev = Path(args.evidence).resolve()
            for root in [REPO] + [checkout_root(p) for p, _ in plugins]:
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
