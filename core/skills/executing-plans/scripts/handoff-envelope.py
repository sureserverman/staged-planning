#!/usr/bin/env python3
"""Write and check the files a supervised session handoff leaves for its supervisor.

Why this exists: when a plan executor hands off to a fresh session, the supervisor
(the program that launched it) must learn that the handoff is ready, whether the
fresh session took it, and why it failed if it did not. Files under
<root>/.claude/handoffs/ are that channel. This script is the one writer and the one
reader on the planning side, so the protocol is spelled in one place.

Subcommands, each with `--root <repo>`:

    new-id           print `h-` + 20 lowercase hex chars (secrets.token_hex(10))
    ready            write <id>.ready.json     (event HANDOFF_READY)
    accept           write <id>.accepted.json  (event HANDOFF_ACCEPTED)
    fail             write <id>.failed.json    (event HANDOFF_FAILED, --code required)
    plan             print the `plan` a valid <id>.ready.json names, else print no-ready, exit 3
    verify           exit 0 when the handoff checks out, else print a failure code, exit 3
    request-pending  exit 0 when request.json asks this managed session to hand off, else 1

Protocol, version 1. Every envelope has exactly these keys:

    {"protocol": "planning-handoff", "version": 1, "event": ...,
     "handoff_id": ..., "managed_session_id": ..., "timestamp": ..., "plan": ...}

`failed` adds `failure_code`. `plan` is an absolute path (os.path.abspath of --plan).
`fail` takes --plan as optional, so its key set stays the same: `plan` is null when
--plan is not given. `managed_session_id` is the supervisor's id for this session. `timestamp` is
ISO-8601 UTC, `YYYY-MM-DDTHH:MM:SSZ`. request.json (written by the supervisor) is
`{"protocol", "version", "managed_session_id", "requested_at"}`. The public spec is the
plugin's references/handoff-protocol.md.

Ids. A handoff id matches ^h-[0-9a-f]{20}$; a --handoff-id that does not exits 2. A
managed session id is 1-128 chars of [A-Za-z0-9_-].

Identity. The writer learns this session's id from the supervisor, by running
$PLANNING_SUPERVISOR_ID_CMD: split with shlex, run without a shell, in its own
process group, killed after 5 s. Exit 0 with exactly one line that is a valid managed
session id is the id. No environment variable is ever read as the id itself: a session
id inherited by a child or a copied shell would name the wrong session. The command runs
in the writer's own working folder and environment, plus PLANNING_HANDOFF_ROOT set to the
call's resolved root (os.path.realpath of --root), where the envelope is written or the
request read; it is never an argument, so a command that takes none still works.

Unsupervised. `ready`, `accept` and `fail` write nothing, print `unsupervised` and exit
0 when the variable is unset or blank, or the command cannot run, exits non-zero, times
out, or prints anything but one valid id line. Unset or blank is silent; a set command
that gives no id also prints one line to stderr, `PLANNING_SUPERVISOR_ID_CMD is set but
gave no session id: <cannot start|exit N|timed out|no single valid id line>`, so a
broken supervisor setup is visible. request-pending stays silent, and checks that
request.json is there and valid before it runs the command, so a gate with no request
starts no process.

One outcome per handoff. `accept` and `fail` first claim the id by creating
handoffs/.<id>.claim with O_EXCL; when it exists — this id was already accepted or
failed, by this session or another — they write nothing, print `refused` to stderr and
exit 1. So two runs given one id cannot both own the plan, and a late `fail` cannot
overwrite an `accepted`. A claim whose envelope then fails to write is removed again.

Root. `--root` is the handoff root the protocol names: the git top level of the project
(session-handoff.md's `<repo root>`), the same root context-usage.py reads a request at.

Writes follow context-usage.py's write_sidecar. The root opens as a directory; then
`.claude` and `handoffs` each open O_NOFOLLOW | O_DIRECTORY relative to the parent fd
(made with mkdir there first if missing) and must be owned by this user. The bytes go
to a fresh O_EXCL | O_NOFOLLOW temp file beside the target, and a rename puts it in
place, so a link planted at the name is replaced, never written through. The temp
name carries random bytes, and the bytes are written in full or the write is refused.
Every write also makes sure handoffs/.gitignore holds exactly `*`: one that is
missing, empty or different is rewritten the same temp-then-rename way, so an
interrupted first write cannot leave envelopes unignored. A refused write prints
`refused` to stderr and exits 1.

Reads open each component O_NOFOLLOW (the file also O_NONBLOCK) and refuse: a link,
anything but a regular file, more than 4096 bytes, non-JSON, a protocol other than
`planning-handoff`, a version other than 1, a handoff id failing its pattern, an
invalid managed session id. A refused read counts as absent.

verify --handoff-id ID --plan PATH checks, in this order, and prints the first failure:

    no-ready         <id>.ready.json is absent or refused, is not HANDOFF_READY, or
                     names another handoff id
    plan-missing     the plan is not a readable regular file of at most 8 MiB
    id-mismatch      the plan's LAST `**RESUME HERE (` block has no `handoff_id:` line,
                     or its first one names another id
    cwd-mismatch     realpath of the block's `cwd:` value != realpath(root)
    branch-mismatch  the block's `branch:` value != `git -C <root> branch --show-current`

A block starts at a line beginning, in column 0, with `**RESUME HERE (` — the
template's heading, `**RESUME HERE (<date>):**`, with `handoff_id: <id>` on the next
line; so prose that merely mentions the block, an indented copy, and a demoted
`**Earlier RESUME HERE` are not blocks. Lines inside a ``` or ~~~ fence are never a
block start: a quoted template is an example. A block runs to the next block start,
the next markdown heading, or end of file. Within it the first `handoff_id:`, `cwd:`
and `branch:` fields are read wherever they sit on a line (the template puts `plan:`,
`cwd:` and `branch:` on one line), skipping the `reason:` line, which quotes a verdict
or a gate check verbatim and may contain either word; the value is the next
whitespace-free token with backticks stripped, so list markers, backticks and a
trailing `(at abc1234)` note are tolerated. A path containing spaces is not supported.

Importable: request_pending(root, env) -> bool, for context-usage.py to load through
importlib (the hyphenated filename prevents a plain import).

Exit codes: 0 ok; 1 refused write / no pending request; 2 bad CLI usage; 3 verify failed.

Stdlib only.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import secrets
import select
import shlex
import signal
import stat
import subprocess
import sys
import time

# The wire id, an interface the supervisor matches on: never rename it with prose.
PROTOCOL = "planning-handoff"
VERSION = 1
ID_CMD_VAR = "PLANNING_SUPERVISOR_ID_CMD"
ROOT_VAR = "PLANNING_HANDOFF_ROOT"   # set for the id command, never read
ID_CMD_TIMEOUT_S = 5
ID_CMD_MAX_BYTES = 256          # a valid id is at most 128 chars plus its newline
CLAUDE_DIR = ".claude"
HANDOFF_DIR = "handoffs"
REQUEST = "request.json"
MAX_READ_BYTES = 4096
MAX_PLAN_BYTES = 8 * 1024 * 1024
GITIGNORE = ".gitignore"
GITIGNORE_BODY = b"*\n"
HANDOFF_ID_RE = re.compile(r"h-[0-9a-f]{20}")
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
FAILURE_CODES = ("id-mismatch", "no-ready", "cwd-mismatch", "branch-mismatch", "plan-missing")
EVENTS = {"ready": ("HANDOFF_READY", "ready"),
          "accept": ("HANDOFF_ACCEPTED", "accepted"),
          "fail": ("HANDOFF_FAILED", "failed")}

BLOCK_START = re.compile(r"^\*\*RESUME HERE \(")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
MD_HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")

# Explicit path, as in prove-claim.py, so a stale plugin-cache copy says so before it
# writes an envelope another program parses under yesterday's protocol.
_STALE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.realpath(__file__))))), "lib", "staleness.py")


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass
REASON_LINE = re.compile(r"^\s*(?:[-*]\s+)?`?reason:")
FIELD_RE = {k: re.compile(r"(?<![\w-])" + k + r":\s*`?([^\s`]+)")
            for k in ("handoff_id", "cwd", "branch")}


def valid_handoff_id(v):
    return isinstance(v, str) and HANDOFF_ID_RE.fullmatch(v) is not None


def valid_session_id(v):
    return isinstance(v, str) and SESSION_ID_RE.fullmatch(v) is not None


def new_id():
    return "h-" + secrets.token_hex(10)


def _close_all(fds):
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def read_handoff_file(root, name):
    """The parsed <root>/.claude/handoffs/<name> as a dict, or None for any refusal.

    Opened one component at a time: root, then `.claude` and `handoffs` with
    O_NOFOLLOW | O_DIRECTORY, then the file with O_NOFOLLOW | O_NONBLOCK (a FIFO
    would otherwise block the open). Checked on the open fd: a regular file of at most
    MAX_READ_BYTES. Then the protocol, the version and any id it carries.
    """
    fds = []
    try:
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
        for d in (CLAUDE_DIR, HANDOFF_DIR):
            fds.append(os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=fds[-1]))
        fds.append(os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1]))
        st = os.fstat(fds[-1])
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_READ_BYTES:
            return None
        raw = os.read(fds[-1], MAX_READ_BYTES + 1)
        if len(raw) > MAX_READ_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    finally:
        _close_all(fds)
    if (not isinstance(data, dict) or data.get("protocol") != PROTOCOL
            or type(data.get("version")) is not int or data["version"] != VERSION):
        return None
    if "handoff_id" in data and not valid_handoff_id(data["handoff_id"]):
        return None
    if not valid_session_id(data.get("managed_session_id")):
        return None
    return data


CANNOT_START, TIMED_OUT, BAD_LINE = "cannot start", "timed out", "no single valid id line"


def identity(env, root=None):
    """(id, None) from the supervisor's identity command, or (None, why) when unsupervised.

    `why` is None when the variable is unset or blank (no supervisor: nothing to report),
    else one of CANNOT_START, `exit N`, TIMED_OUT or BAD_LINE. `env` supplies only the
    command. With `root`, the command's environment is the writer's own plus ROOT_VAR set
    to os.path.realpath(root); its argv and working folder stay as they are. Its stdout must be exactly one line holding a valid managed session id. The
    command runs in its own session, and the bound is a deadline on reading and on the
    exit, never a wait for end-of-file: a descendant that left the process group can hold
    stdout open forever, and it is not waited for.
    """
    raw = env.get(ID_CMD_VAR)
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    try:
        argv = shlex.split(raw)
    except ValueError:
        return None, CANNOT_START
    if not argv:
        return None, CANNOT_START
    child_env = None if root is None else dict(os.environ, **{ROOT_VAR: os.path.realpath(root)})
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True,
                                env=child_env)
    except (OSError, ValueError):
        return None, CANNOT_START
    deadline = time.monotonic() + ID_CMD_TIMEOUT_S
    out, ok, why = b"", False, TIMED_OUT
    try:
        fd = proc.stdout.fileno()
        while True:
            if len(out) > ID_CMD_MAX_BYTES:
                why = BAD_LINE                  # more than one id line can hold
                break
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                break
            chunk = os.read(fd, ID_CMD_MAX_BYTES + 1 - len(out))
            if not chunk:
                ok = True                       # end of output, within the bound
                break
            out += chunk
        if ok:
            left = deadline - time.monotonic()
            if left <= 0:
                ok = False
            else:
                code = proc.wait(timeout=left)
                if code != 0:
                    ok, why = False, f"exit {code}"
    except subprocess.TimeoutExpired:
        ok, why = False, TIMED_OUT
    except (OSError, ValueError):
        ok, why = False, CANNOT_START
    finally:
        if proc.poll() is None or not ok:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.kill()
            except OSError:
                pass
        proc.stdout.close()
        proc.wait()
    if not ok:
        return None, why
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        return None, BAD_LINE
    if text.endswith("\n"):
        text = text[:-1]
    if "\n" in text or "\r" in text or not valid_session_id(text):
        return None, BAD_LINE
    return text, None


def supervised_session_id(env, root=None):
    """This session's id from the supervisor's identity command, or None (unsupervised)."""
    return identity(env, root)[0]


def request_pending(root, env):
    """True when <root>/.claude/handoffs/request.json is valid and its
    managed_session_id equals the id the supervisor's identity command gives
    (`env` supplies the command); False otherwise, including when unsupervised.

    The request is read first, so a gate with no request (the usual case) starts no
    process; the command runs only when there is a valid request to match."""
    data = read_handoff_file(root, REQUEST)
    if data is None:
        return False
    sid = supervised_session_id(env, root)
    return sid is not None and data.get("managed_session_id") == sid


def _open_owned_dir(name, parent_fd):
    """Open `name` under parent_fd without following a link, creating it if missing;
    it must be this user's. Returns the fd or raises."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        fd = os.open(name, flags, dir_fd=parent_fd)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise PermissionError(f"{name} is not owned by this user")
    return fd


def _replace_at(hfd, name, body):
    """Put `body` at `name` in the directory hfd: a fresh O_EXCL | O_NOFOLLOW temp with
    a random name, written in full, then renamed over `name`. Raises on any failure,
    after removing its temp."""
    tmp = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=hfd)
    try:
        try:
            view = memoryview(body)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
        os.replace(tmp, name, src_dir_fd=hfd, dst_dir_fd=hfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=hfd)
        except OSError:
            pass
        raise


def _gitignore_ok(hfd):
    try:
        fd = os.open(GITIGNORE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=hfd)
    except OSError:
        return False
    try:
        return (stat.S_ISREG(os.fstat(fd).st_mode)
                and os.read(fd, len(GITIGNORE_BODY) + 1) == GITIGNORE_BODY)
    finally:
        os.close(fd)


def write_handoff_file(root, name, body, claim=None):
    """Write `body` (bytes) to <root>/.claude/handoffs/<name>, first making sure
    handoffs/.gitignore is exactly `*`. With `claim`, first create that file with O_EXCL
    and refuse when it exists. Returns whether it was written; never raises."""
    fds = []
    try:
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
        fds.append(_open_owned_dir(CLAUDE_DIR, fds[-1]))
        fds.append(_open_owned_dir(HANDOFF_DIR, fds[-1]))
        if not _gitignore_ok(fds[-1]):
            _replace_at(fds[-1], GITIGNORE, GITIGNORE_BODY)
        if claim is not None:
            os.close(os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=fds[-1]))
        try:
            _replace_at(fds[-1], name, body)
        except BaseException:
            if claim is not None:      # no outcome was written: free the id for a retry
                try:
                    os.unlink(claim, dir_fd=fds[-1])
                except OSError:
                    pass
            raise
        return True
    except Exception:
        return False
    finally:
        _close_all(fds)


def envelope(event, handoff_id, session_id, plan, failure_code=None):
    body = {"protocol": PROTOCOL, "version": VERSION, "event": event,
            "handoff_id": handoff_id, "managed_session_id": session_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
                                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "plan": os.path.abspath(plan) if plan is not None else None}
    if event == "HANDOFF_FAILED":
        body["failure_code"] = failure_code
    return body


def last_block(text):
    """The lines of the last RESUME HERE block in `text`, or None when there is none."""
    blocks, cur, fenced = [], None, False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            if cur is not None:
                cur.append(line)
            continue
        if not fenced and BLOCK_START.match(line):
            cur = [line]
            blocks.append(cur)
        elif MD_HEADING.match(line):
            cur = None
        elif cur is not None:
            cur.append(line)
    return blocks[-1] if blocks else None


def block_field(lines, key):
    for line in lines:
        if REASON_LINE.match(line):
            continue
        m = FIELD_RE[key].search(line)
        if m:
            return m.group(1)
    return None


def current_branch(root):
    try:
        r = subprocess.run(["git", "-C", root, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def read_plan(plan):
    """The plan's text, or None unless it is a regular file of at most MAX_PLAN_BYTES.
    The path may be a link (plans may live outside the repo); O_NONBLOCK keeps a FIFO from
    blocking the open."""
    try:
        fd = os.open(plan, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_PLAN_BYTES:
            return None
        chunks, size = [], 0
        while size <= MAX_PLAN_BYTES:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_PLAN_BYTES:
            return None
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def read_ready(root, handoff_id):
    """The valid HANDOFF_READY envelope for this id, or None."""
    ready = read_handoff_file(root, f"{handoff_id}.ready.json")
    if (ready is None or ready.get("event") != "HANDOFF_READY"
            or ready.get("handoff_id") != handoff_id):
        return None
    return ready


def verify(root, handoff_id, plan):
    """None when the handoff checks out, else the failure code."""
    if read_ready(root, handoff_id) is None:
        return "no-ready"
    text = read_plan(plan)
    if text is None:
        return "plan-missing"
    lines = last_block(text)
    if lines is None or block_field(lines, "handoff_id") != handoff_id:
        return "id-mismatch"
    cwd = block_field(lines, "cwd")
    if cwd is None or os.path.realpath(os.path.expanduser(cwd)) != os.path.realpath(root):
        return "cwd-mismatch"
    branch = current_branch(root)
    if not branch or block_field(lines, "branch") != branch:
        return "branch-mismatch"
    return None


def handoff_id_arg(text):
    if not valid_handoff_id(text):
        raise argparse.ArgumentTypeError(f"not a handoff id (^h-[0-9a-f]{{20}}$): {text!r}")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="handoff-envelope")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new-id", help="print a fresh handoff id")
    p.add_argument("--root", required=True)
    for cmd in ("ready", "accept"):
        p = sub.add_parser(cmd, help=f"write <id>.{EVENTS[cmd][1]}.json")
        p.add_argument("--root", required=True)
        p.add_argument("--handoff-id", required=True, type=handoff_id_arg)
        p.add_argument("--plan", required=True)
    p = sub.add_parser("fail", help="write <id>.failed.json")
    p.add_argument("--root", required=True)
    p.add_argument("--handoff-id", required=True, type=handoff_id_arg)
    p.add_argument("--code", required=True, choices=FAILURE_CODES)
    p.add_argument("--plan", help="plan file (recorded as null when omitted)")
    p = sub.add_parser("plan", help="print the plan <id>.ready.json names; exit 3 no-ready")
    p.add_argument("--root", required=True)
    p.add_argument("--handoff-id", required=True, type=handoff_id_arg)
    p = sub.add_parser("verify", help="check a handoff; exit 3 with a failure code")
    p.add_argument("--root", required=True)
    p.add_argument("--handoff-id", required=True, type=handoff_id_arg)
    p.add_argument("--plan", required=True)
    p = sub.add_parser("request-pending", help="exit 0 when a handoff is requested of us")
    p.add_argument("--root", required=True)
    _warn_if_stale()
    args = ap.parse_args(argv)

    if args.cmd == "new-id":
        print(new_id())
        return 0
    if args.cmd == "request-pending":
        return 0 if request_pending(args.root, os.environ) else 1
    if args.cmd == "plan":
        ready = read_ready(args.root, args.handoff_id)
        plan = ready.get("plan") if ready else None
        if not isinstance(plan, str) or not os.path.isabs(plan):
            print("no-ready")
            return 3
        print(plan)
        return 0
    if args.cmd == "verify":
        code = verify(args.root, args.handoff_id, args.plan)
        if code is None:
            return 0
        print(code)
        return 3

    sid, why = identity(os.environ, args.root)
    if sid is None:
        if why is not None:
            print(f"{ID_CMD_VAR} is set but gave no session id: {why}", file=sys.stderr)
        print("unsupervised")
        return 0
    event, suffix = EVENTS[args.cmd]
    body = envelope(event, args.handoff_id, sid, args.plan, getattr(args, "code", None))
    name = f"{args.handoff_id}.{suffix}.json"
    claim = f".{args.handoff_id}.claim" if args.cmd in ("accept", "fail") else None
    if not write_handoff_file(args.root, name, (json.dumps(body) + "\n").encode("utf-8"),
                              claim):
        print(f"refused: could not write {name} under {args.root}/.claude/handoffs"
              + (" (this handoff was already accepted or failed)" if claim else ""),
              file=sys.stderr)
        return 1
    print(os.path.join(os.path.abspath(args.root), CLAUDE_DIR, HANDOFF_DIR, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
