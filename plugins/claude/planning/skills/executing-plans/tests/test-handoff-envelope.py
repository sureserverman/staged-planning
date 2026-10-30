#!/usr/bin/env python3
"""Fixture suite for scripts/handoff-envelope.py — run directly (CI convention):
    python3 core/skills/executing-plans/tests/test-handoff-envelope.py

Asserts the script's contract: `new-id` mints distinct `h-` + 20-hex ids; each
envelope carries exactly the version-1 protocol keys; `ready`/`accept`/`fail`
write nothing when the supervisor id command ($PLANNING_SUPERVISOR_ID_CMD) is unset,
empty, prints anything but one safe id line, exits non-zero or times out — and never
fall back to a session id in the environment; a `.claude` or `.claude/handoffs`
that is a link gets no write, and the file it points at stays as it was; `verify`
names its failure code with exit 3 — id-mismatch (wrong id, or the right one only
above the final block), cwd-mismatch, branch-mismatch, no-ready, plan-missing — and
exits 0 when the final RESUME HERE block agrees; the request reader rejects a
request.json that is too large or a link, and compares its session id; every writer
refuses an envelope over the reader's limit before writing, printing the size and the
limit and leaving nothing in the handoff root, and each names the reader's constant.

Every subprocess runs with PLANNING_SUPERVISOR_ID_CMD stripped unless a case sets
it, inside temp dirs and fixture git repos made with `git init`.

Stdlib only.
"""
import ast
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "handoff-envelope.py")
import shlex

ENV_VAR = "PLANNING_SUPERVISOR_ID_CMD"
PROTOCOL = "planning-handoff"
ID_RE = re.compile(r"h-[0-9a-f]{20}")      # used with fullmatch: `$` admits a trailing \n
SID = "sup-session_01"
BASE_KEYS = {"protocol", "version", "event", "handoff_id", "managed_session_id",
             "timestamp", "plan"}

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        FAILURES.append(msg)


def id_cmd(sid):
    """An identity command printing `sid` as its one line ('' is the empty variable)."""
    return "" if sid == "" else shlex.join([sys.executable, "-c", f"print({sid!r})"])


def env_for(sid=None, cmd=None):
    env = {k: v for k, v in os.environ.items() if k != ENV_VAR}
    if cmd is not None:
        env[ENV_VAR] = cmd
    elif sid is not None:
        env[ENV_VAR] = id_cmd(sid)
    return env


def run(args, sid=None, cwd=None, cmd=None, env=None):
    """Run the script; return (rc, stdout, stderr)."""
    r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                       env=env if env is not None else env_for(sid, cmd),
                       cwd=cwd or tempfile.gettempdir(), timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git_repo(parent, name, branch):
    """A fresh repo on `branch`; returns its path."""
    d = pathlib.Path(parent) / name
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "-q", "-b", branch], check=True)
    return d


def tree(d):
    """Every path under d, relative, sorted (empty list when d is absent)."""
    d = pathlib.Path(d)
    if not d.exists():
        return []
    return sorted(str(p.relative_to(d)) for p in d.rglob("*"))


def block(hid, cwd, branch, date="2026-10-05"):
    lines = [f"**RESUME HERE ({date}):**"]
    if hid is not None:
        lines.append(f"handoff_id: {hid}")
    lines += ["reason: rule context: now=1 of window=2 (table) is 50.1% > 50%",
              f"plan: /some/plan.md   cwd: {cwd}   branch: {branch} (at `abc1234`)",
              "next: Task 2.1 — something",
              "`dispatch: 0 of 0`  `review: none`  `residuals: none`",
              "**Decisions in force:** none recorded", ""]
    return "\n".join(lines)


def plan_with(path, *blocks):
    path.write_text("# A plan\n\n## Stage 1\n\nStatus: [x]\n\n" + "\n".join(blocks),
                    encoding="utf-8")
    return path


def plan_path(length):
    """An absolute path of exactly `length` chars, in legal 200-char components."""
    path = (("/" + "d" * 199) * (length // 200 + 1))[:length]
    return path[:-1] + "d" if path.endswith("/") else path


def v1_size(event, hid, sid, plan, **extra):
    """The bytes a version-1 envelope takes on disk, its newline included."""
    body = {"protocol": PROTOCOL, "version": 1, "event": event, "handoff_id": hid,
            "managed_session_id": sid, "timestamp": "2026-01-01T00:00:00Z", "plan": plan, **extra}
    return len(json.dumps(body, separators=(",", ":"))) + 1


def v1_plan_for(size, event, hid, sid, **extra):
    """A plan path that makes this version-1 envelope exactly `size` bytes."""
    return plan_path(size - v1_size(event, hid, sid, "", **extra))


def numbers(text):
    """The numbers a refusal prints, leaving out the digits of a handoff id."""
    return {int(n) for n in re.findall(r"\d+", re.sub(r"h-[0-9a-f]{20}", "", text))}


def fixture_repo(parent, name):
    """A fresh repo on branch `feature`, with no template hooks; returns its real path."""
    d = pathlib.Path(parent) / name
    subprocess.run(["git", "init", "-q", "--template=", "-b", "feature", str(d)], check=True)
    return pathlib.Path(os.path.realpath(d))


def plan_state(root, operation, revision, payload):
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(SCRIPT), "plan-state.py"),
                        operation, "--repo", str(root), "--expected-revision", str(revision),
                        "--operation-id", f"fixture-{operation}-{revision}"],
                       input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"fixture plan-state {operation} failed: {r.stdout}{r.stderr}")


def deep_file(root, length):
    """A regular file under `root` whose absolute path is exactly `length` chars."""
    prefix = str(root) + "/"
    name = "local-plan.md"
    chunks, left = [], length - len(prefix) - len(name) - 1
    while left > 0:
        n = min(left, 200)
        if left - n == 1:       # a component needs a char and its slash
            n -= 1
        chunks.append("d" * n)
        left -= n + 1
    target = pathlib.Path(prefix + "/".join(chunks)) if chunks else pathlib.Path(root)
    target.mkdir(parents=True, exist_ok=True)
    return target / name


def v2_ready(parent, name, length, hid):
    """Run `ready --next` for a held same-root plan at a path of `length` chars."""
    root = fixture_repo(parent, name)
    plan = deep_file(root, length)
    plan.write_text("# Project Plan: synthetic\n## Stage 1: Work\n### Task 1.1: Work\n"
                    "- **Status:** [ ]\n### Stage 1 Gate\n- [ ] synthetic check\n"
                    f"\n**RESUME HERE (2026-01-01):**\nhandoff_id: {hid}\ncwd: {root}\n"
                    f"branch: feature\nplan: {plan}\nnext: Task 1.1\n", encoding="utf-8")
    plan_state(root, "init", 0, {"plan": str(plan), "source": "Fixture owner authorized work",
                                 "scope": "Synthetic fixture only", "stage": 1, "task": "1.1"})
    plan_state(root, "set-blocker", 1, {
        "disposition": "handoff", "prevented_operation": "synthetic successor work",
        "evidence": "synthetic measured stage gate", "dependency": "synthetic adoption",
        "remaining_work": ["synthetic next task"], "reason": "rule requested: synthetic rollover",
        "handoff_id": hid})
    env = dict(env_for(SID), PLANNING_HANDOFF_VERSIONS="1,2")
    return (root, *run(["ready", "--root", str(root), "--handoff-id", hid, "--plan", str(plan),
                        "--next", "Task 1.1"], env=env, cwd=str(root)))


tmp = tempfile.mkdtemp(prefix="handoff-envelope-test-")
try:
    print("script exists")
    check(os.path.isfile(SCRIPT), f"{SCRIPT} exists")

    # 1. new-id
    print("new-id")
    ids = []
    for _ in range(100):
        rc, out, _err = run(["new-id", "--root", tmp])
        ids.append(out if rc == 0 else None)
    check(all(i is not None and ID_RE.fullmatch(i) for i in ids),
          f"100 new-id values all match ^h-[0-9a-f]{{20}}$ (first: {ids[0]!r})")
    check(len(set(ids)) == 100, f"100 new-id values are distinct ({len(set(ids))})")

    rc, _out, _err = run(["ready", "--root", tmp, "--handoff-id", "h-123", "--plan", "/p.md"],
                         sid=SID)
    check(rc == 2 and os.path.isfile(SCRIPT),
          f"a --handoff-id failing the pattern exits 2 ({rc})")
    check(not (pathlib.Path(tmp) / ".claude").exists(), "and writes nothing")

    # 2. exact keys per event
    print("envelope keys")
    r2 = pathlib.Path(tmp) / "keys"
    r2.mkdir()
    hid = "h-" + "a" * 20
    fid = "h-" + "f" * 20       # fail's own id: accept already claimed `hid`
    plan_rel = "plan.md"
    hdir = r2 / ".claude" / "handoffs"
    cases = (
        ("ready", ["--plan", plan_rel], "ready", "HANDOFF_READY", BASE_KEYS),
        ("accept", ["--plan", plan_rel], "accepted", "HANDOFF_ACCEPTED", BASE_KEYS),
        ("fail", ["--code", "cwd-mismatch", "--plan", plan_rel], "failed", "HANDOFF_FAILED",
         BASE_KEYS | {"failure_code"}),
    )
    for cmd, extra, suffix, event, keys in cases:
        cid = fid if cmd == "fail" else hid
        rc, out, err = run([cmd, "--root", str(r2), "--handoff-id", cid, *extra], sid=SID,
                           cwd=str(r2))
        f = hdir / f"{cid}.{suffix}.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        check(rc == 0 and isinstance(data, dict) and set(data) == keys,
              f"{cmd} -> {f.name} has exactly {sorted(keys)} "
              f"({rc}, {sorted(data) if isinstance(data, dict) else data}, {err})")
        if isinstance(data, dict):
            check(data.get("protocol") == PROTOCOL and data.get("version") == 1
                  and data.get("event") == event and data.get("handoff_id") == cid
                  and data.get("managed_session_id") == SID
                  and data.get("plan") == str(r2 / plan_rel)
                  and isinstance(data.get("timestamp"), str)
                  and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|\+00:00)$",
                               data["timestamp"]),
                  f"{cmd} values: protocol/version/event/id/session/absolute plan/UTC timestamp "
                  f"({data})")
    try:
        fdata = json.loads((hdir / f"{fid}.failed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fdata = {}
    check(fdata.get("failure_code") == "cwd-mismatch", "fail records its failure_code")
    hid2 = "h-" + "b" * 20
    rc, _out, _err = run(["fail", "--root", str(r2), "--handoff-id", hid2, "--code", "no-ready"],
                         sid=SID)
    try:
        d2 = json.loads((hdir / f"{hid2}.failed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d2 = None
    check(rc == 0 and isinstance(d2, dict) and set(d2) == BASE_KEYS | {"failure_code"}
          and d2.get("plan") is None,
          f"fail without --plan keeps the exact key set, plan null ({d2})")
    rc, _out, _err = run(["fail", "--root", str(r2), "--handoff-id", hid2, "--code", "bogus"],
                         sid=SID)
    check(rc == 2 and os.path.isfile(SCRIPT), f"fail --code outside the five codes exits 2 ({rc})")
    gi = hdir / ".gitignore"
    check(gi.is_file() and gi.read_text(encoding="utf-8") == "*\n",
          "a `*` .gitignore appears in .claude/handoffs on the first envelope")

    print("one outcome per handoff")
    acc = hdir / f"{hid}.accepted.json"
    before = acc.read_bytes()
    for cmd, extra in (("accept", ["--plan", plan_rel]), ("fail", ["--code", "no-ready"])):
        rc, _o, err = run([cmd, "--root", str(r2), "--handoff-id", hid, *extra], sid="other_1")
        check(rc == 1 and "already accepted or failed" in err and acc.read_bytes() == before
              and not (hdir / f"{hid}.failed.json").exists(),
              f"a second {cmd} of an accepted id is refused and changes nothing "
              f"(red if accept is not exclusive) ({rc}, {err[:80]!r})")
    rc, _o, err = run(["accept", "--root", str(r2), "--handoff-id", fid, "--plan", plan_rel],
                      sid=SID)
    check(rc == 1 and not (hdir / f"{fid}.accepted.json").exists(),
          f"accept after fail is refused ({rc})")
    rc, out, _e = run(["accept", "--root", str(r2), "--handoff-id", "h-" + "9" * 20,
                       "--plan", plan_rel])
    check(rc == 0 and out == "unsupervised" and not (hdir / (".h-" + "9" * 20 + ".claim")).exists(),
          "unsupervised accept claims nothing")
    leftovers = [n for n in tree(hdir) if n.endswith(".tmp")]
    check(not leftovers, f"no temp files left behind ({leftovers})")

    # 3. unsupervised -> nothing written
    print("unsupervised")
    for label, sid in (("unset", None), ("empty", "")):
        r3 = pathlib.Path(tmp) / f"unsup-{label}"
        r3.mkdir()
        outs = []
        for cmd, extra in (("ready", ["--plan", "p.md"]), ("accept", ["--plan", "p.md"]),
                           ("fail", ["--code", "id-mismatch"])):
            rc, out, err = run([cmd, "--root", str(r3), "--handoff-id", hid, *extra], sid=sid)
            outs.append((rc, out, err))
        check(all(o == (0, "unsupervised", "") for o in outs),
              f"env {label}: ready/accept/fail exit 0 printing 'unsupervised', nothing on "
              f"stderr ({outs})")
        check(tree(r3 / ".claude" / "handoffs") == [],
              f"env {label}: nothing exists under .claude/handoffs/ ({tree(r3)})")
    stub = pathlib.Path(tmp) / "id-stub.py"
    stub.write_text("import sys, time\n"
                    "mode = sys.argv[1]\n"
                    "if mode == 'two': print('sup-one'); print('sup-two')\n"
                    "elif mode == 'sleep': time.sleep(6); print('sup-late')\n"
                    "elif mode == 'exit3': print('sup-three'); sys.exit(3)\n"
                    "elif mode == 'bad': print('bad/id')\n"
                    "elif mode == 'cr': sys.stdout.write('sup-one\\r\\n')\n"
                    "elif mode == 'nul': sys.stdout.write('sup-one\\x00\\n')\n"
                    "elif mode == 'space': sys.stdout.write('sup-one \\n')\n"
                    "elif mode == 'blank': sys.stdout.write('sup-one\\n\\n')\n"
                    "elif mode == 'empty': sys.stdout.write('\\n')\n"
                    "elif mode == 'long': print('a' * 129)\n"
                    "elif mode == 'latin1': sys.stdout.buffer.write(b'sup-\\xe9\\n')\n"
                    "elif mode == 'flood': sys.stdout.write('a' * 10_000_000)\n"
                    "elif mode == 'nonl': sys.stdout.write('sup-nonl')\n", encoding="utf-8")
    # Every plausible session-id variable holds a valid id in each case below, so a script
    # that reads one after its id command fails goes red here.
    fallback = {n: SID for n in ("SESSION_ID", "SUPERVISOR_SESSION_ID", "PLANNING_SESSION_ID",
                                 "PLANNING_SUPERVISOR_ID", "MANAGED_SESSION_ID",
                                 "CLAUDE_CODE_SESSION_ID")}
    def why(reason):
        """The one stderr line a set-but-unusable id command must produce."""
        return f"{ENV_VAR} is set but gave no session id: {reason}"
    BADLINE = "no single valid id line"
    for label, mode, reason in (
            ("prints two lines", "two", BADLINE), ("sleeps 6 s", "sleep", "timed out"),
            ("exits 3", "exit3", "exit 3"), ("prints an unsafe id", "bad", BADLINE),
            ("ends its line with CR", "cr", BADLINE), ("prints a NUL", "nul", BADLINE),
            ("adds a trailing space", "space", BADLINE), ("adds a blank line", "blank", BADLINE),
            ("prints an empty line", "empty", BADLINE), ("prints 129 chars", "long", BADLINE),
            ("prints non-UTF-8", "latin1", BADLINE), ("floods stdout", "flood", BADLINE)):
        r3 = pathlib.Path(tmp) / f"unsup-cmd-{mode}"
        r3.mkdir()
        env3 = dict(env_for(cmd=shlex.join([sys.executable, str(stub), mode])), **fallback)
        rc, out, err = run(["ready", "--root", str(r3), "--handoff-id", hid, "--plan", "p.md"],
                           env=env3)
        check(rc == 0 and out == "unsupervised" and tree(r3 / ".claude") == [],
              f"an id command that {label}, with session ids in the environment: "
              f"unsupervised, nothing written ({rc}, {out!r})")
        check(err == why(reason),
              f"an id command that {label}: stderr names why, {reason!r} "
              f"(red if a broken supervisor setup is silent) ({err!r})")
    r3 = pathlib.Path(tmp) / "cmd-nonl"
    r3.mkdir()
    rc, out, _err = run(["ready", "--root", str(r3), "--handoff-id", hid, "--plan", "p.md"],
                        cmd=shlex.join([sys.executable, str(stub), "nonl"]))
    try:
        nonl = json.loads((r3 / ".claude" / "handoffs" / f"{hid}.ready.json").read_text())
    except (OSError, ValueError):
        nonl = {}
    check(rc == 0 and nonl.get("managed_session_id") == "sup-nonl",
          f"one id line without a final newline is the id ({rc}, {nonl.get('managed_session_id')!r})")
    # A descendant that leaves the process group and keeps stdout open must not hang the
    # writer: the 5 s bound holds whatever the command starts.
    r3 = pathlib.Path(tmp) / "unsup-cmd-setsid"
    r3.mkdir()
    import time as _time
    t0 = _time.monotonic()
    rc, out, _err = run(["ready", "--root", str(r3), "--handoff-id", hid, "--plan", "p.md"],
                        env=dict(env_for(cmd="sh -c 'setsid sleep 30 & echo sup-one'"), **fallback))
    took = _time.monotonic() - t0
    check(rc == 0 and out == "unsupervised" and tree(r3 / ".claude") == [] and took < 9,
          f"an id command whose setsid grandchild holds stdout: unsupervised within the bound "
          f"(red if the writer waits for EOF) ({rc}, {out!r}, {took:.1f}s)")
    check(_err == why("timed out"), f"and stderr says it timed out ({_err!r})")
    r3 = pathlib.Path(tmp) / "unsup-cmd-missing"
    r3.mkdir()
    rc, out, _err = run(["ready", "--root", str(r3), "--handoff-id", hid, "--plan", "p.md"],
                        env=dict(env_for(cmd=str(pathlib.Path(tmp) / "no-such-command")),
                                 **fallback))
    check(rc == 0 and out == "unsupervised" and tree(r3 / ".claude") == [],
          f"an id command that cannot run: unsupervised, nothing written ({rc}, {out!r})")
    check(_err == why("cannot start"), f"and stderr says it cannot start ({_err!r})")
    r3 = pathlib.Path(tmp) / "unsup-cmd-unquoted"
    r3.mkdir()
    rc, out, err = run(["accept", "--root", str(r3), "--handoff-id", hid, "--plan", "p.md"],
                       cmd="echo 'unbalanced")
    check(rc == 0 and out == "unsupervised" and tree(r3 / ".claude") == []
          and err == why("cannot start"),
          f"an id command that does not split (an open quote): unsupervised, stderr says it "
          f"cannot start ({rc}, {out!r}, {err!r})")
    r3 = pathlib.Path(tmp) / "unsup-blank-silent"
    r3.mkdir()
    rc, out, err = run(["fail", "--root", str(r3), "--handoff-id", hid, "--code", "no-ready"],
                       cmd="   ")
    check(rc == 0 and out == "unsupervised" and err == "",
          f"a blank (spaces only) id command is silent: unset, not broken ({rc}, {out!r}, {err!r})")
    # No fallback to the environment: a session id under any plausible variable name, with no
    # id command, writes nothing — a writer that reads one fails here.
    r3 = pathlib.Path(tmp) / "unsup-envonly"
    r3.mkdir()
    env_only = env_for()
    env_only.update(fallback)
    rc, out, _err = run(["ready", "--root", str(r3), "--handoff-id", hid, "--plan", "p.md"],
                        env=env_only)
    check(rc == 0 and out == "unsupervised" and tree(r3 / ".claude") == [],
          f"a session id in the environment with no id command writes nothing ({rc}, {out!r})")
    src = pathlib.Path(SCRIPT).read_text(encoding="utf-8")
    reads = set(re.findall(r"""environ(?:\.get)?\(?\[?\s*["']([A-Z_]+)["']""", src))
    reads |= set(re.findall(r"""\benv\.get\(\s*["']([A-Z_]+)["']""", src))
    reads |= set(re.findall(r"""getenv\(\s*["']([A-Z_]+)["']""", src))
    check(reads <= {ENV_VAR} and "environ[" not in src.replace("os.environ[", ""),
          f"the script reads no environment variable but the id command's ({sorted(reads)})")

    # 4. linked .claude/handoffs and .claude are refused
    print("links refused")
    r4 = pathlib.Path(tmp) / "linked"
    (r4 / ".claude").mkdir(parents=True)
    target = pathlib.Path(tmp) / "link-target"
    target.mkdir()
    (r4 / ".claude" / "handoffs").symlink_to(target)
    rc, _out, _err = run(["ready", "--root", str(r4), "--handoff-id", hid, "--plan", "p.md"],
                         sid=SID)
    check(rc != 0 and tree(target) == [] and (r4 / ".claude" / "handoffs").is_symlink(),
          f"a handoffs dir that is a link gets no write; what it points at stays empty ({rc}, {tree(target)})")
    r4b = pathlib.Path(tmp) / "linked-claude"
    r4b.mkdir()
    target_b = pathlib.Path(tmp) / "link-target-b"
    target_b.mkdir()
    (r4b / ".claude").symlink_to(target_b)
    rc, _out, _err = run(["accept", "--root", str(r4b), "--handoff-id", hid, "--plan", "p.md"],
                         sid=SID)
    check(rc != 0 and tree(target_b) == [],
          f"a .claude that is a link gets no write; what it points at stays empty ({rc}, {tree(target_b)})")
    # A planted link at the envelope name is replaced, never written through.
    r4c = pathlib.Path(tmp) / "linked-file"
    (r4c / ".claude" / "handoffs").mkdir(parents=True)
    victim = pathlib.Path(tmp) / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    (r4c / ".claude" / "handoffs" / f"{hid}.ready.json").symlink_to(victim)
    rc, _out, _err = run(["ready", "--root", str(r4c), "--handoff-id", hid, "--plan", "p.md"],
                         sid=SID)
    check(rc == 0 and victim.read_text(encoding="utf-8") == "keep"
          and not (r4c / ".claude" / "handoffs" / f"{hid}.ready.json").is_symlink(),
          f"a link at the envelope's name is replaced; the file it named is untouched ({rc})")

    # 5 + 6. verify
    print("verify")
    plans = pathlib.Path(tmp) / "plans"
    plans.mkdir()
    repo = git_repo(tmp, "repo", "feat/handoff")
    rc_b = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                          capture_output=True, text=True).stdout.strip()
    check(rc_b == "feat/handoff", f"fixture repo is on feat/handoff ({rc_b!r})")
    good = "h-" + "c" * 20
    other = "h-" + "d" * 20
    rc, _out, err = run(["ready", "--root", str(repo), "--handoff-id", good,
                         "--plan", str(plans / "good.md")], sid=SID)
    check(rc == 0, f"fixture ready written ({rc}, {err})")

    def verify(plan, hid=good, root=repo):
        return run(["verify", "--root", str(root), "--handoff-id", hid, "--plan", str(plan)])

    p_ok = plan_with(plans / "good.md", block(other, repo, "feat/handoff", "2026-10-01"),
                     block(good, repo, "feat/handoff"))
    rc, out, err = verify(p_ok)
    check(rc == 0, f"verify exits 0 when the last block matches ({rc}, {out!r}, {err!r})")
    # Template-shaped variants: list marker and backticks.
    p_ok2 = plan_with(plans / "good2.md",
                      "**RESUME HERE (2026-10-05):**\n"
                      f"- `handoff_id: {good}`\n"
                      "reason: x\n"
                      f"plan: `/p.md`   cwd: `{repo}`   branch: `feat/handoff`\n")
    rc, out, err = verify(p_ok2)
    check(rc == 0, f"verify tolerates list markers and backticks ({rc}, {out!r}, {err!r})")

    for label, plan, code in (
        ("a wrong id", plan_with(plans / "wrong-id.md", block(other, repo, "feat/handoff")),
         "id-mismatch"),
        ("the right id only in an earlier block",
         plan_with(plans / "earlier.md", block(good, repo, "feat/handoff", "2026-10-01"),
                   block(other, repo, "feat/handoff")), "id-mismatch"),
        ("no handoff_id in the last block",
         plan_with(plans / "no-id.md", block(good, repo, "feat/handoff", "2026-10-01"),
                   block(None, repo, "feat/handoff")), "id-mismatch"),
        ("a wrong cwd", plan_with(plans / "wrong-cwd.md", block(good, plans, "feat/handoff")),
         "cwd-mismatch"),
        ("a wrong branch", plan_with(plans / "wrong-branch.md", block(good, repo, "main")),
         "branch-mismatch"),
        ("an unreadable plan", plans / "absent.md", "plan-missing"),
    ):
        rc, out, err = verify(plan)
        check(rc == 3 and out == code, f"verify: {label} -> exit 3 {code} ({rc}, {out!r})")

    # A quoted template, prose naming the block, and an indented copy after the real
    # block are not blocks: the real block stays the last one.
    p_noise = plan_with(plans / "noise.md", block(good, repo, "feat/handoff"),
                        "## Notes\n\n```\n" + block(other, plans, "main") + "```\n",
                        "~~~\n" + block(other, plans, "main") + "~~~\n",
                        "**RESUME HERE blocks are written at a gate.**\n",
                        "  " + block(other, plans, "main").replace("\n", "\n  "))
    rc, out, err = verify(plans / "noise.md")
    check(rc == 0,
          f"a heading after the real block ends it without discarding it; fenced, prose and "
          f"indented copies after it are not blocks ({rc}, {out!r})")
    p_noise2 = plan_with(plans / "noise2.md", block(good, repo, "feat/handoff"),
                         "```\n" + block(other, plans, "main") + "```\n",
                         "**RESUME HERE blocks are written at a gate.**\n",
                         "  " + block(other, plans, "main").replace("\n", "\n  "))
    rc, out, err = verify(p_noise2)
    check(rc == 0, f"a fenced template, a prose mention and an indented copy after the real "
                   f"block are not blocks (red if BLOCK_START matches them) ({rc}, {out!r})")
    rc, out, _e = run(["plan", "--root", str(repo), "--handoff-id", good])
    check(rc == 0 and out == str(plans / "good.md"),
          f"plan prints the plan the ready envelope names ({rc}, {out!r})")
    rc, out, _e = run(["plan", "--root", str(repo), "--handoff-id", "h-" + "e" * 20])
    check(rc == 3 and out == "no-ready", f"plan with no ready -> exit 3 no-ready ({rc}, {out!r})")
    p_reason = plan_with(plans / "reason.md",
                         block(good, repo, "feat/handoff").replace(
                             "reason: rule context:",
                             "reason: [~] `branch: main` and `cwd: /elsewhere` hold — rule context:"))
    rc, out, err = verify(p_reason)
    check(rc == 0, f"cwd:/branch: quoted in the reason: line are not read as the block's "
                   f"(red if the reason line is searched) ({rc}, {out!r})")
    fifo_plan = plans / "fifo.md"
    os.mkfifo(fifo_plan)
    rc, out, _err = verify(fifo_plan)
    check(rc == 3 and out == "plan-missing", f"verify: a FIFO plan -> plan-missing, no hang ({rc}, {out!r})")
    rc, out, _err = verify(p_ok, hid="h-" + "e" * 20)
    check(rc == 3 and out == "no-ready", f"verify: a missing ready -> exit 3 no-ready ({rc}, {out!r})")
    # A ready that is too big, or reached through a link, counts as absent.
    big = repo / ".claude" / "handoffs" / f"{good}.ready.json"
    saved = big.read_text(encoding="utf-8") if big.is_file() else "{}"
    obj = json.loads(saved)
    obj["pad"] = "x" * 5000
    big.write_text(json.dumps(obj), encoding="utf-8")
    rc, out, _err = verify(p_ok)
    check(rc == 3 and out == "no-ready", f"verify: a 5 KiB ready -> no-ready ({rc}, {out!r})")
    big.write_text(saved, encoding="utf-8")
    repo2 = git_repo(tmp, "repo2", "feat/handoff")
    (repo2 / ".claude").mkdir()
    (repo2 / ".claude" / "handoffs").symlink_to(repo / ".claude" / "handoffs")
    p_r2 = plan_with(plans / "repo2.md", block(good, repo2, "feat/handoff"))
    rc, out, _err = verify(p_r2, root=repo2)
    check(rc == 3 and out == "no-ready",
          f"verify: a ready reached through a linked handoffs dir -> no-ready ({rc}, {out!r})")
    rc, out, _err = verify(p_ok)
    check(rc == 0, f"verify is green again on the restored fixture ({rc}, {out!r})")

    # 7. request-pending
    print("request-pending")
    r7 = pathlib.Path(tmp) / "req"
    (r7 / ".claude" / "handoffs").mkdir(parents=True)
    req = r7 / ".claude" / "handoffs" / "request.json"
    good_req = {"protocol": PROTOCOL, "version": 1, "managed_session_id": SID,
                "requested_at": "2026-10-05T10:00:00Z"}

    def pending(sid):
        return run(["request-pending", "--root", str(r7)], sid=sid)[0]

    check(pending(SID) == 1, "no request.json -> exit 1")
    sleeper = shlex.join([sys.executable, str(stub), "sleep"])
    t0 = _time.monotonic()
    rc, _o, _e = run(["request-pending", "--root", str(r7)], cmd=sleeper)
    took = _time.monotonic() - t0
    check(rc == 1 and took < 1.0,
          f"no request.json: request-pending returns without running the id command "
          f"(red if the 6 s command runs first) ({rc}, {took:.2f}s)")
    req.write_text(json.dumps(good_req), encoding="utf-8")
    check(pending(SID) == 0, "a valid matching request.json -> exit 0")
    check(pending("someone-else") == 1, "a non-matching session id -> exit 1")
    check(pending(None) == 1, "no id command -> exit 1")
    req.write_text(json.dumps(dict(good_req, protocol="other-handoff")), encoding="utf-8")
    check(pending(SID) == 1, "a foreign handoff protocol id is not accepted -> exit 1")
    req.write_text(json.dumps(good_req), encoding="utf-8")
    req.write_text(json.dumps(dict(good_req, pad="x" * 5000)), encoding="utf-8")
    check(req.stat().st_size > 4096 and pending(SID) == 1,
          f"request.json over the 4 KiB cap -> exit 1 ({req.stat().st_size} bytes)")
    req.write_text(json.dumps(dict(good_req, version=2)), encoding="utf-8")
    check(pending(SID) == 1, "an unknown version -> exit 1")
    req.write_text(json.dumps(dict(good_req, protocol="other")), encoding="utf-8")
    check(pending(SID) == 1, "an unknown protocol -> exit 1")
    req.unlink()
    elsewhere = pathlib.Path(tmp) / "req-elsewhere.json"
    elsewhere.write_text(json.dumps(good_req), encoding="utf-8")
    req.symlink_to(elsewhere)
    check(pending(SID) == 1, "a symlinked request.json -> exit 1")
    req.unlink()
    os.mkfifo(req)
    check(pending(SID) == 1, "a FIFO at request.json -> exit 1, no hang")
    req.unlink()
    req.mkdir()
    check(pending(SID) == 1, "a directory at request.json -> exit 1")
    req.rmdir()
    req.write_text(json.dumps(dict(good_req, managed_session_id="bad id!")), encoding="utf-8")
    check(pending("bad id!") == 1, "an invalid managed_session_id -> exit 1")
    req.write_text(json.dumps(good_req), encoding="utf-8")
    rc, _o, _e = run(["request-pending", "--root", str(r7 / ".claude")], sid=SID)
    check(rc == 1, "a request is read only at <root>/.claude/handoffs, not one level off")

    print(".gitignore")
    r8 = pathlib.Path(tmp) / "gi"
    (r8 / ".claude" / "handoffs").mkdir(parents=True)
    gi = r8 / ".claude" / "handoffs" / ".gitignore"
    gi.write_text("", encoding="utf-8")         # an interrupted first write
    rc, _o, err = run(["ready", "--root", str(r8), "--handoff-id", "h-" + "a" * 20,
                       "--plan", "p.md"], sid=SID)
    check(rc == 0 and gi.read_text(encoding="utf-8") == "*\n",
          f"an empty .gitignore is rewritten to `*` (red if only created with O_EXCL) "
          f"({rc}, {gi.read_text(encoding='utf-8')!r})")
    gi.write_text("!keep\n", encoding="utf-8")
    run(["accept", "--root", str(r8), "--handoff-id", "h-" + "a" * 20, "--plan", "p.md"], sid=SID)
    check(gi.read_text(encoding="utf-8") == "*\n", "a .gitignore with other content is rewritten")
    leftovers = [n for n in tree(r8 / ".claude" / "handoffs") if n.endswith(".tmp")]
    check(leftovers == [], f"no temp file is left behind ({leftovers})")

    spec = importlib.util.spec_from_file_location("handoff_envelope", SCRIPT)
    mod = None
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 - report any import failure as a check
        print(f"  import error: {e!r}")
    fn = getattr(mod, "request_pending", None)
    check(callable(fn), "request_pending is importable via importlib")
    if mod is not None:
        r9 = pathlib.Path(tmp) / "claimfree"
        r9.mkdir()
        real = mod._replace_at

        def boom(hfd, name, body):
            if name.endswith(".accepted.json"):
                raise OSError("disk full")
            return real(hfd, name, body)
        mod._replace_at = boom
        hid9 = "h-" + "7" * 20
        wrote = mod.write_handoff_file(str(r9), f"{hid9}.accepted.json", b"{}", f".{hid9}.claim")
        mod._replace_at = real
        check(wrote is False and not (r9 / ".claude" / "handoffs" / f".{hid9}.claim").exists(),
              "a claim whose envelope fails to write is removed, so a retry is not refused "
              "(red if the claim outlives the failed write)")

        # A claim appears whole in one step, so no kill leaves an empty one.
        kid = "h-" + "7" * 20
        kname, kclaim = f"{kid}.accepted.json", f".{kid}.claim"
        accepted = {"event": "HANDOFF_ACCEPTED", "handoff_id": kid, "managed_session_id": "s-a",
                    "plan": "p.md", "timestamp": "2026-10-30T10:00:00Z"}
        kbody = json.dumps(accepted).encode() + b"\n"

        def fresh(name):
            root = pathlib.Path(tmp) / name
            (root / ".claude" / "handoffs").mkdir(parents=True)
            return root, root / ".claude" / "handoffs"

        def killed_writer(root, patch):
            code = ("import importlib.util, os, sys\n"
                    f"spec = importlib.util.spec_from_file_location('w', {str(SCRIPT)!r})\n"
                    "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
                    + patch +
                    f"mod.write_handoff_file({str(root)!r}, {kname!r}, {kbody!r}, {kclaim!r})\n")
            return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).returncode

        after_claim = ("real = mod._replace_at\n"
                       "mod._replace_at = lambda hfd, name, body, exclusive=False: "
                       "os._exit(9) if name.endswith('.json') else real(hfd, name, body, exclusive)\n")

        def writes(root, event, **changes):
            body = dict(accepted, event=event, **changes)
            name = f"{kid}.{'accepted' if event == 'HANDOFF_ACCEPTED' else 'failed'}.json"
            return mod.write_handoff_file(str(root), name, json.dumps(body).encode() + b"\n", kclaim)

        root, hd = fresh("killed-link")
        rc = killed_writer(root, "os.link = lambda *a, **k: os._exit(9)\n")
        check(rc == 9 and not (hd / kclaim).exists(),
              f"a writer killed before the claim's link leaves no claim (red with O_EXCL) ({rc})")
        check(writes(root, "HANDOFF_ACCEPTED") is True, "and the id can be claimed again")

        root, hd = fresh("killed-retry")
        rc = killed_writer(root, after_claim)
        check(rc == 9 and (hd / kclaim).read_bytes() == kbody and not (hd / kname).exists(),
              f"a writer killed after claiming leaves a complete claim, never an empty one ({rc})")
        check(writes(root, "HANDOFF_ACCEPTED", timestamp="2026-10-30T11:00:00Z") is True
              and (hd / kname).read_bytes() == kbody,
              "the same outcome retried finishes it, with the claim's own bytes")
        check(writes(root, "HANDOFF_ACCEPTED", timestamp="2026-10-30T12:00:00Z") is True
              and (hd / kname).read_bytes() == kbody,
              "the same outcome retried after it is published still stands, so its owner knows")
        check(writes(root, "HANDOFF_ACCEPTED", managed_session_id="s-b") is False
              and (hd / kname).read_bytes() == kbody,
              "with the outcome published, another owner backs off")

        root, hd = fresh("killed-forged")
        (hd / kclaim).write_bytes(json.dumps(dict(accepted, handoff_id="h-" + "1" * 20)).encode())
        check(writes(root, "HANDOFF_ACCEPTED") is False and not (hd / kname).exists(),
              "a claim naming another id publishes nothing")

        for field, value in (("managed_session_id", "s-b"), ("plan", "other.md")):
            root, hd = fresh(f"killed-{field}")
            killed_writer(root, after_claim)
            check(writes(root, "HANDOFF_ACCEPTED", **{field: value}) is False
                  and (hd / kname).read_bytes() == kbody,
                  f"another {field} is refused, and the killed writer's outcome reaches the reader")

        root, hd = fresh("killed-fail")
        killed_writer(root, after_claim)
        check(writes(root, "HANDOFF_FAILED", failure_code="x") is False
              and (hd / kname).read_bytes() == kbody and not (hd / f"{kid}.failed.json").exists(),
              "a different event is refused, and the killed writer's outcome reaches the reader")

        root, hd = fresh("killed-empty")
        (hd / kclaim).write_bytes(b"")
        check(writes(root, "HANDOFF_ACCEPTED") is False and not (hd / kname).exists(),
              "an empty claim from an older writer still refuses")

        root, hd = fresh("lost-race")
        real = mod._replace_at

        def beaten(hfd, name, body, exclusive=False):
            if name == kname:
                (hd / kname).write_bytes(kbody)
            return real(hfd, name, body, exclusive)
        mod._replace_at = beaten
        won = mod.write_handoff_file(str(root), kname, kbody, kclaim)
        mod._replace_at = real
        check(won is True and (hd / kclaim).exists() and (hd / kname).read_bytes() == kbody,
              "a claimer whose own outcome another writer published first keeps its claim")

        root, hd = fresh("other-outcome")
        (hd / kname).write_bytes(json.dumps(dict(accepted, managed_session_id="s-z")).encode())
        check(writes(root, "HANDOFF_ACCEPTED") is False,
              "a fresh claim over a different published outcome is refused (red if it reports success)")

        root, hd = fresh("fsync-fails")
        real_fsync = os.fsync
        calls = []

        def flaky_fsync(fd):
            if (hd / kname).exists() and not calls:
                calls.append(fd)
                raise OSError("disk trouble")
            return real_fsync(fd)
        mod.os.fsync = flaky_fsync
        stood = writes(root, "HANDOFF_ACCEPTED")
        mod.os.fsync = real_fsync
        check(calls and stood is True and (hd / kclaim).exists(),
              "a failure after publishing keeps the claim and reports the outcome that stands")
        check(writes(root, "HANDOFF_FAILED", failure_code="x") is False
              and not (hd / f"{kid}.failed.json").exists(),
              "so no second outcome can follow it")

        root, hd = fresh("no-links")
        real_link = mod.os.link

        def no_link(*a, **k):
            raise PermissionError(1, "no hard links here")
        mod.os.link = no_link
        check(writes(root, "HANDOFF_ACCEPTED") is True and (hd / kname).exists() and (hd / kclaim).exists(),
              "on a filesystem without hard links the claim falls back to an exclusive create")
        check(writes(root, "HANDOFF_FAILED", failure_code="x") is False,
              "and it still holds the id")

        root, hd = fresh("no-links-other")
        (hd / kname).write_bytes(json.dumps(dict(accepted, managed_session_id="s-z")).encode())
        before_other = (hd / kname).read_bytes()
        check(writes(root, "HANDOFF_ACCEPTED") is False and (hd / kname).read_bytes() == before_other,
              "without hard links, a different published outcome is neither replaced nor claimed as ours")

        root, hd = fresh("no-links-killed")
        (hd / kclaim).write_bytes(kbody)
        check(writes(root, "HANDOFF_FAILED", failure_code="x") is False and (hd / kname).read_bytes() == kbody,
              "without hard links, a killed writer's complete claim still reaches the reader")

        root, hd = fresh("no-links-full")
        real_write = mod.os.write

        def full_disk(fd, data):
            if (hd / kclaim).exists():
                raise OSError(28, "no space")
            return real_write(fd, data)
        mod.os.write = full_disk
        wrote = writes(root, "HANDOFF_ACCEPTED")
        mod.os.write = real_write
        check(wrote is False and not (hd / kclaim).exists(),
              "without hard links, a write error frees the id instead of burning it")
        mod.os.link = real_link

        root, hd = fresh("links")
        writes(root, "HANDOFF_ACCEPTED")
        check((hd / kclaim).stat().st_nlink == 1, "a claim holds one link when done")
    if callable(fn):
        check(fn(str(r7), {ENV_VAR: id_cmd(SID)}) is True,
              "request_pending(root, env) -> True on a match")
        check(fn(str(r7), {ENV_VAR: id_cmd("x")}) is False, "request_pending -> False on a mismatch")
        check(fn(str(r7), {}) is False, "request_pending -> False with no id command")
        check(fn(str(r7), dict(fallback)) is False,
              "request_pending -> False with only session ids in the environment")
        check(fn(str(r7), dict(fallback, **{ENV_VAR: shlex.join([sys.executable, "-c",
                                                                  "import sys; sys.exit(3)"])}))
              is False, "request_pending -> False when the command fails, whatever the env holds")

    # 9. the id command learns the root the call acts on, in PLANNING_HANDOFF_ROOT
    print("root reaches the id command")
    ROOT_VAR = "PLANNING_HANDOFF_ROOT"
    rlog = pathlib.Path(tmp) / "root-stub.log"
    rstub = pathlib.Path(tmp) / "root-stub.py"
    rstub.write_text("import json, os, sys\n"
                     "with open(sys.argv[1], 'w', encoding='utf-8') as f:\n"
                     f"    json.dump({{'root': os.environ.get({ROOT_VAR!r}), 'argv': sys.argv[1:],\n"
                     "               'cwd': os.getcwd()}, f)\n"
                     f"print({SID!r})\n", encoding="utf-8")
    rcmd = shlex.join([sys.executable, str(rstub), str(rlog)])
    repo_a = git_repo(tmp, "repo-a", "main")
    repo_b = git_repo(tmp, "repo-b", "main")
    real_a, real_b = os.path.realpath(repo_a), os.path.realpath(repo_b)

    def logged(args, env=None):
        """Run the script from repo A; return (rc, the stub's log or None)."""
        if rlog.exists():
            rlog.unlink()
        rc, _o, _e = run(args, cwd=str(repo_a), env=env if env is not None else env_for(cmd=rcmd))
        try:
            return rc, json.loads(rlog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return rc, None

    rc, log = logged(["ready", "--root", str(repo_b), "--handoff-id", "h-" + "1" * 20,
                      "--plan", "p.md"])
    check(rc == 0 and log is not None and log["root"] == real_b,
          f"ready --root <repo B> run from repo A: the id command sees {ROOT_VAR}=realpath(B) "
          f"(red if the root is not passed) ({rc}, {log})")
    check(log is not None and log["argv"] == [str(rlog)],
          f"and its argv is exactly the command's, nothing appended ({log and log['argv']})")
    check(log is not None and log["cwd"] == real_a,
          f"and it runs in the writer's own working folder, not the root ({log and log['cwd']})")
    rc, log = logged(["ready", "--root", str(repo_b), "--handoff-id", "h-" + "2" * 20,
                      "--plan", "p.md"], env=dict(env_for(cmd=rcmd), **{ROOT_VAR: str(repo_a)}))
    check(rc == 0 and log is not None and log["root"] == real_b,
          f"a {ROOT_VAR} already in the writer's environment is replaced by the call's root "
          f"({rc}, {log})")
    link_b = pathlib.Path(tmp) / "link-to-b"
    link_b.symlink_to(repo_b)
    rc, log = logged(["ready", "--root", str(link_b), "--handoff-id", "h-" + "3" * 20,
                      "--plan", "p.md"])
    check(rc == 0 and log is not None and log["root"] == real_b,
          f"a root given through a symlink reaches the command resolved ({rc}, {log})")
    for cmd, extra in (("accept", ["--handoff-id", "h-" + "4" * 20, "--plan", "p.md"]),
                       ("fail", ["--handoff-id", "h-" + "5" * 20, "--code", "no-ready"])):
        rc, log = logged([cmd, "--root", str(repo_b), *extra])
        check(rc == 0 and log is not None and log["root"] == real_b
              and log["argv"] == [str(rlog)],
              f"{cmd} --root <repo B>: the id command sees realpath(B), argv unchanged ({rc}, {log})")
    (repo_b / ".claude" / "handoffs" / "request.json").write_text(json.dumps(good_req),
                                                                  encoding="utf-8")
    rc, log = logged(["request-pending", "--root", str(repo_b)])
    check(rc == 0 and log is not None and log["root"] == real_b
          and log["argv"] == [str(rlog)],
          f"request-pending --root <repo B>: the id command sees realpath(B) ({rc}, {log})")
    if callable(fn):
        if rlog.exists():
            rlog.unlink()
        hit = fn(str(link_b), {ENV_VAR: rcmd})
        try:
            log = json.loads(rlog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log = None
        check(hit is True and log is not None and log["root"] == real_b,
              f"request_pending(root, env), context-usage.py's reader, passes its root "
              f"({hit}, {log})")
    rc, log = logged(["ready", "--root", str(repo_b), "--handoff-id", "h-" + "6" * 20,
                      "--plan", "p.md"], env=env_for())
    check(rc == 0 and log is None and not rlog.exists(),
          f"with {ENV_VAR} unset the id command never runs ({rc}, {log})")

    # 10. the writer refuses what the reader would refuse, before writing anything
    print("oversized envelopes")
    LIMIT = 4096
    over = "h-" + "1" * 20
    for cmd, suffix, event, extra, size_extra in (
            ("ready", "ready", "HANDOFF_READY", [], {}),
            ("accept", "accepted", "HANDOFF_ACCEPTED", [], {}),
            ("fail", "failed", "HANDOFF_FAILED", ["--code", "no-ready"],
             {"failure_code": "no-ready"})):
        r10 = pathlib.Path(tmp) / f"oversized-{cmd}"
        r10.mkdir()
        big_plan = v1_plan_for(5000, event, over, SID, **size_extra)
        rc, _o, err = run([cmd, "--root", str(r10), "--handoff-id", over, "--plan", big_plan, *extra],
                          sid=SID)
        check(rc != 0 and {5000, LIMIT} <= numbers(err),
              f"{cmd}: a plan path making the envelope 5000 B is refused with size and limit "
              f"printed (red if the refusal is generic) ({rc}, {err[:120]!r})")
        check(tree(r10) == [],
              f"{cmd}: nothing appears under the root, no claim and no .claude ({tree(r10)})")
    r10 = pathlib.Path(tmp) / "oversized-retry"
    r10.mkdir()
    big_plan = v1_plan_for(5000, "HANDOFF_ACCEPTED", over, SID)
    run(["accept", "--root", str(r10), "--handoff-id", over, "--plan", big_plan], sid=SID)
    rc, _o, err = run(["fail", "--root", str(r10), "--handoff-id", over, "--code", "no-ready"], sid=SID)
    check(rc == 0, f"a refused accept does not consume the id: fail can still be written ({rc}, {err!r})")

    for size, label in ((4000, "a 4000 B envelope"), (LIMIT, "an envelope exactly at the limit")):
        r10 = pathlib.Path(tmp) / f"within-{size}"
        r10.mkdir()
        fit_plan = v1_plan_for(size, "HANDOFF_READY", over, SID)
        rc, out, err = run(["ready", "--root", str(r10), "--handoff-id", over, "--plan", fit_plan],
                           sid=SID)
        written = r10 / ".claude" / "handoffs" / f"{over}.ready.json"
        check(rc == 0 and written.is_file() and written.stat().st_size == size,
              f"{label} is written at that size ({rc}, {err[:120]!r}, "
              f"{written.stat().st_size if written.is_file() else None})")
        rc, out, err = run(["plan", "--root", str(r10), "--handoff-id", over])
        check(rc == 0 and out == fit_plan,
              f"{label} reads back through the reader, with the same plan ({rc}, {len(out)})")
    r10 = pathlib.Path(tmp) / "one-over"
    r10.mkdir()
    rc, _o, err = run(["ready", "--root", str(r10), "--handoff-id", over, "--plan",
                       v1_plan_for(LIMIT + 1, "HANDOFF_READY", over, SID)], sid=SID)
    check(rc != 0 and {LIMIT + 1, LIMIT} <= numbers(err) and tree(r10) == [],
          f"one byte over the limit is refused, names both numbers, writes nothing ({rc}, {err[:120]!r})")

    print("oversized envelopes, version 2")
    v2id = "h-" + "2" * 20
    # A short path measures this fixture's overhead: the plan path appears three times.
    root, rc, _o, err = v2_ready(tmp, "v2-measure", 300, v2id)
    measured = root / ".claude" / "handoffs" / f"{v2id}.ready.json"
    check(rc == 0 and measured.is_file(), f"a short v2 ready is written ({rc}, {err!r})")
    base = measured.stat().st_size if measured.is_file() else 0
    root, rc, out, err = v2_ready(tmp, "v2-oversize", 1600, v2id)
    check(rc == 3 and out == "oversized-envelope" and LIMIT in numbers(err)
          and any(n > LIMIT for n in numbers(err)),
          f"v2 ready over the limit keeps its code and prints size and limit ({rc}, {out!r}, {err[:120]!r})")
    check(tree(root / ".claude" / "handoffs") == [],
          f"v2 ready over the limit leaves the handoff root empty ({tree(root / '.claude' / 'handoffs')})")
    # This ready fits by itself, but the outcome its successor must write would not.
    root, rc, out, err = v2_ready(tmp, "v2-outcome", 300 + (4000 - base) // 3, v2id)
    check(rc == 3 and out == "oversized-envelope" and LIMIT in numbers(err)
          and any(n > LIMIT for n in numbers(err)),
          f"v2 ready whose largest outcome would not fit prints size and limit "
          f"({rc}, {out!r}, {err[:120]!r})")
    check(tree(root / ".claude" / "handoffs") == [],
          f"and leaves the handoff root empty ({tree(root / '.claude' / 'handoffs')})")
    root, rc, out, err = v2_ready(tmp, "v2-fitting", 300 + (3700 - base) // 3, v2id)
    wrote = rc
    rc, out, err = run(["plan", "--root", str(root), "--handoff-id", v2id])
    check(wrote == 0 and rc == 0 and pathlib.Path(out).is_file(),
          f"a v2 ready whose outcomes fit too is written and read back ({wrote}, {rc}, {err[:120]!r})")

    # A hand-placed ready that fits, with an outcome that cannot: the outcome writer's own check.
    root = fixture_repo(tmp, "v2-fail")
    v2_plan = plan_path(1100)
    planted = {"protocol": PROTOCOL, "version": 2, "event": "HANDOFF_READY", "handoff_id": v2id,
               "managed_session_id": "predecessor", "timestamp": "2026-01-01T00:00:00Z",
               "plan": v2_plan, "source_root": str(root), "source_plan": v2_plan,
               "predecessor_session_id": "predecessor",
               "destination": {"root": str(root), "branch": "feature", "plan": v2_plan,
                               "locator": "Task 1.1", "master_plan": None},
               "selection": {"boundary": False, "subplan": None, "current_subplan": None}}
    hd = root / ".claude" / "handoffs"
    hd.mkdir(parents=True)
    raw_ready = json.dumps(planted, separators=(",", ":")) + "\n"
    padded = plan_path(1100 + (4000 - len(raw_ready)) // 3)
    planted.update(plan=padded, source_plan=padded)
    planted["destination"]["plan"] = padded
    (hd / f"{v2id}.ready.json").write_text(json.dumps(planted, separators=(",", ":")) + "\n",
                                           encoding="utf-8")
    before_fail = tree(hd)
    rc, out, err = run(["fail", "--root", str(root), "--handoff-id", v2id, "--code", "no-ready"],
                       env=dict(env_for("successor"), PLANNING_HANDOFF_VERSIONS="1,2"), cwd=str(root))
    check(rc == 3 and out == "oversized-envelope" and LIMIT in numbers(err)
          and any(n > LIMIT for n in numbers(err)),
          f"a v2 outcome over the limit is refused with size and limit ({rc}, {out!r}, {err[:120]!r})")
    check(tree(hd) == before_fail, f"and no outcome or claim appears ({tree(hd)})")

    # A finished outcome names the plan once, so only a path near the system's own limit fills it.
    root = fixture_repo(tmp, "v2-finished")
    done = deep_file(root, 3950)
    done.write_text("# Project Plan: synthetic\n## Stage 1: Work\n### Task 1.1: Work\n"
                    "- **Status:** [x]\n### Stage 1 Gate\n- [x] synthetic check\n"
                    "**Completed:** 2026-01-01 — synthetic\n", encoding="utf-8")
    plan_state(root, "init", 0, {"plan": str(done), "source": "Fixture owner authorized work",
                                 "scope": "Synthetic fixture only"})
    plan_state(root, "finish", 1, {"evidence": "Synthetic close-out complete"})
    hd = root / ".claude" / "handoffs"
    hd.mkdir(parents=True)
    (hd / "request.json").write_text(json.dumps(
        {"protocol": PROTOCOL, "version": 2, "managed_session_id": SID,
         "requested_at": "2026-01-01T00:00:00Z", "request_id": v2id}), encoding="utf-8")
    rc, out, err = run(["finished", "--root", str(root), "--plan", str(done)],
                       env=dict(env_for(SID), PLANNING_HANDOFF_VERSIONS="1,2"), cwd=str(root))
    check(rc == 3 and out == "oversized-envelope" and LIMIT in numbers(err)
          and any(n > LIMIT for n in numbers(err)),
          f"finished over the limit is refused as oversized with size and limit, not as a stale "
          f"outcome ({rc}, {out!r}, {err[:120]!r})")
    check(tree(hd) == ["request.json"], f"and writes no outcome ({tree(hd)})")

    print("one limit")
    scripts = pathlib.Path(SCRIPT).parent
    writers, parsed = set(), {}
    for path in sorted(scripts.glob("handoff*.py")):
        parsed[path.name] = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.attr if isinstance(n, ast.Attribute) else n.name
                 for n in ast.walk(parsed[path.name])
                 if isinstance(n, (ast.Attribute, ast.FunctionDef))}
        names |= {n.id for n in ast.walk(parsed[path.name]) if isinstance(n, ast.Name)}
        if "write_handoff_file" in names:
            writers.add(path.name)
            check("MAX_READ_BYTES" in names,
                  f"{path.name} refers to the reader's constant by name "
                  f"(red if it bounds its envelope some other way or not at all)")
    check({"handoff-envelope.py", "handoff_v2.py", "handoff_finished.py"} <= writers,
          f"the writers are all found ({sorted(writers)})")
    literals = [(name, n.lineno) for name, t in parsed.items() for n in ast.walk(t)
                if isinstance(n, ast.Constant) and n.value == LIMIT]
    check(len(literals) == 1 and literals[0][0] == "handoff-envelope.py",
          f"the number itself appears once, as the reader's constant ({literals})")
    definitions = [name for name, t in parsed.items() for n in ast.walk(t)
                   if isinstance(n, ast.Assign) and any(
                       isinstance(a, ast.Name) and a.id == "MAX_READ_BYTES" for a in n.targets)]
    check(definitions == ["handoff-envelope.py"], f"and only the reader defines it ({definitions})")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if FAILURES:
    print(f"FAILED — {len(FAILURES)} check(s):")
    for f in FAILURES:
        print(f"  {f}")
    sys.exit(1)
print("OK — handoff-envelope.py mints ids, writes exact protocol envelopes only when "
      "supervised, refuses links and oversized reads, and verifies the last RESUME HERE block")
