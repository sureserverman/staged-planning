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
request.json that is too large or a link, and compares its session id.

Every subprocess runs with PLANNING_SUPERVISOR_ID_CMD stripped unless a case sets
it, inside temp dirs and fixture git repos made with `git init`.

Stdlib only.
"""
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
