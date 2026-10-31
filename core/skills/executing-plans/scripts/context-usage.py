#!/usr/bin/env python3
"""Report the current Claude Code session's context size from its transcript.

Why this exists: a plan executor deciding whether to hand off to a fresh session
needs a measured reason, not a feeling that "the context is getting long". Claude
Code writes every assistant turn's API usage into the session transcript, so the
context size at the latest turn is a number the executor can read rather than guess.

The value is exact: it is the sum the API itself reported for the last turn.

    now = input_tokens + cache_read_input_tokens + cache_creation_input_tokens

taken from the LAST main-thread assistant row that carries a usage block. Skipped:
`"isSidechain": true` rows (subagent turns — their context is not this one's),
`"model": "<synthetic>"` rows (client-written placeholders with all-zero usage),
and malformed lines.

Transcript location: `--transcript PATH` if given (the Stop hook receives
`transcript_path`), else `$HOME/.claude/projects/*/<CLAUDE_CODE_SESSION_ID>.jsonl`.

Window resolution — the transcript records no window, and the model id carries no
1M marker (a session running with the `opus[1m]` setting logs plain `claude-opus-…`):

    1. `--window N` wins.
    2. The live session's window from <root>/.claude/plan-context.json, written by the
       planning mod beside the state file: <root> is the nearest directory at or
       above cwd holding .claude/plan-progress.json (plan-progress.py's rule), else
       cwd. Used only when the file is a regular file owned by this user
       (no symlink at `.claude` or the file), at most 64 KiB, a JSON object whose
       `session_id` equals CLAUDE_CODE_SESSION_ID, whose `window` is a positive int
       (not a bool), and whose `updated` (ISO-8601 with a zone) is under 15 min old and at
       most 60 s in the future. Anything else falls through silently.
    3. The base window from MODEL_WINDOWS, by exact model id (a dated `-YYYYMMDD`
       suffix is also accepted).
    4. Upgraded to 1M only when the table says the model supports 1M AND there is
       evidence: a `[1m]` suffix on the configured model (ANTHROPIC_MODEL, then
       `model` in <cwd>/.claude/settings.local.json, <cwd>/.claude/settings.json,
       $HOME/.claude/settings.json — first found wins), or a context already
       observed in this transcript above the base window.
    5. A model not in the table has no window → verdict `unknown`.

Verdicts: `handoff` when pct > 50, else `continue`; `unknown` for anything the
script cannot prove. An owner's rollover request — the supervisor's request file,
naming the id the supervisor's identity command gives this session, read only by handoff-envelope.py's
reader (no second parser) — is `handoff` whatever else holds (rule requested); the
executor runs this script only at a gate, so the request still lands at one. The
request is looked up at the git top level, else the state root (above), else cwd —
the one handoff root the handoff protocol names, where the supervisor writes it. A reader that cannot load says so on
stderr and changes no verdict. Every verdict carries a `reason` naming the rule and numbers.
An `unknown` verdict never stops a run: exit 0. Exit 2 only on bad CLI usage.

Stdlib only.
"""
import argparse
import datetime
import glob
import importlib.util
import json
import os
import pathlib
import re
import stat
import subprocess
import sys

# Source: the "Current Models" tables of Anthropic's claude-api skill, and
#   claude-opus-5-5 from https://platform.claude.com/docs/en/about-claude/models/overview
#   "Context window" row (1M tokens), as of 2026-09-22.
# model id -> (base window, supports a 1M window). Every 1M model there states 1M
# as its default, so for those the base already is 1M. A model the doc does not
# list is left out on purpose — it resolves to verdict `unknown`, never a guess.
MODEL_WINDOWS = {
    "claude-fable-5-1": (1_000_000, True),
    "claude-opus-5-5": (1_000_000, True),
    "claude-mythos-5-1": (1_000_000, True),
    "claude-fable-5": (1_000_000, True),
    "claude-mythos-5": (1_000_000, True),
    "claude-opus-5": (1_000_000, True),
    "claude-opus-4-8": (1_000_000, True),
    "claude-opus-4-7": (1_000_000, True),
    "claude-opus-4-6": (1_000_000, True),
    "claude-sonnet-5": (1_000_000, True),
    "claude-sonnet-4-6": (1_000_000, True),
    "claude-haiku-4-5": (200_000, False),
}
ONE_M = 1_000_000

# The live-window sidecar (Window resolution step 2).
SIDECAR = "plan-context.json"
MAX_SIDECAR_BYTES = 64 * 1024
SIDECAR_MAX_AGE_S = 15 * 60
SIDECAR_FUTURE_S = 60

HANDOFF_PCT = 50.0
# Floor under the dead-weight and sub-plan-boundary rules: below it a fresh session buys
# too little to be worth the handoff.
FLOOR_PCT = 25.0

STAGE_HEAD = re.compile(r"^## Stage (\d+)\b", re.M)
FIELD = re.compile(r"^\s*- \*\*(Scope|Test):\*\*(.*)$", re.M)
# A path token: something with a slash, or a name with a file extension.
PATH_TOKEN = re.compile(r"[\w.\-]*[A-Za-z_][\w\-]*\.[A-Za-z][A-Za-z0-9]{0,6}\b|[\w.\-]+/[\w.\-/]+")

DATED = re.compile(r"-\d{8}$")
# A stage boundary is the assistant turn whose Bash call runs `git ... commit` in command
# position (line start, or after ; & | or a paren) with `Stage N green` in the message's
# SUBJECT. Both halves are load-bearing, measured: a `git log --grep "Stage 1 green"`
# commits nothing; a command that writes test source containing the commit string puts
# `git` inside a quoted literal; a gate-fix commit may mention the phrase in its body.
GIT_COMMIT = re.compile(r"(?:^|[;&|(])[ \t]*(?P<git>git)\b[^;&|]*?(?<=\s)commit(?=\s|$)(?P<rest>.*)")
HEREDOC = re.compile(r"""<<(-?)[ \t]*['"]?(\w+)['"]?""")
MSG_ARG = re.compile(r"""(?<!\S)(?:-[A-Za-z]*m|--message)(?:[ \t]+|=)?(?P<q>["']?)"""
                     r"""(?P<pf>\$\((?:printf[ \t]*["'])?)?(?P<s>.*)""")
STAGE_GREEN = re.compile(r"\bStage (\d+) green\b")
# `-F <file>` / `--file <file>` / `--file=<file>`; `-F -` reads a heredoc instead.
FILE_ARG = re.compile(r"""(?<!\S)(?:-[A-Za-z]*F|--file)(?:[ \t]+|=)(?P<f>[^\s;&|]+)""")
# The file a heredoc line writes: `cat > f <<EOF`, `cat <<EOF > f`, `tee f <<EOF`.
REDIRECT = re.compile(r"""(?:>{1,2}|\btee[ \t]+)[ \t]*(?P<f>[^\s;&|<>]+)""")


def _unquote(word):
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"" else word


def _scan_quotes(text, state):
    """Return the shell quote state after `text`, starting from `state` (None, "'" or '"').

    Enough of the shell's rules to tell a command from a string: single quotes take
    everything literally, a backslash escapes outside them, an apostrophe inside double
    quotes is just a character, and an unquoted `#` at a word start begins a comment.
    """
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if state == "'":
            if c == "'":
                state = None
        elif c == "\\":
            i += 1
        elif state == '"':
            if c == '"':
                state = None
        elif c in "'\"":
            state = c
        elif c == "#" and (i == 0 or text[i - 1] in " \t;&|("):
            break
        i += 1
    return state


def commit_subject(cmd):
    """Yield the subject line of every `git commit` the command runs.

    Line by line: a heredoc body is skipped whole (it is data — Python source, a message),
    except that a commit's own heredoc yields its first line as the subject; a `git` token
    inside a quote still open at that point — on its line or carried from an earlier one —
    is a string, not a command. `git commit -F <file>` takes the first line of a heredoc
    the same command wrote to that file, matched by the target's text (`$S/m.txt` names
    the same file in both places). A message file written any other way is not read, so
    such a commit is not a boundary.
    """
    lines = cmd.split("\n")
    i = 0
    carry = None            # quote state carried in from the previous line
    written = {}            # heredoc target text -> its body's first line
    while i < len(lines):
        line = lines[i]
        for m in GIT_COMMIT.finditer(line):
            if _scan_quotes(line[:m.start("git")], carry) is not None:
                continue
            rest = m.group("rest")
            f = FILE_ARG.search(rest)
            if f and _unquote(f.group("f")) != "-":
                if _unquote(f.group("f")) in written:
                    yield written[_unquote(f.group("f"))]
            elif HEREDOC.search(rest):
                if i + 1 < len(lines):
                    yield lines[i + 1]
            else:
                a = MSG_ARG.search(rest)
                if a:
                    subject = a.group("s")
                    if a.group("q") and not a.group("pf"):
                        subject = re.split(r'(?<!\\)' + a.group("q"), subject, 1)[0]
                    yield subject.split("\\n", 1)[0]
        h = HEREDOC.search(line)
        carry = _scan_quotes(line, carry)
        i += 1
        if h:
            tag, dash = h.group(2), h.group(1)
            target = REDIRECT.search(line)
            if target and i < len(lines):
                written[_unquote(target.group("f"))] = lines[i]
            while i < len(lines) and (lines[i].lstrip("\t") if dash else lines[i]) != tag:
                i += 1
            i += 1


def stage_committed(msg):
    """Return the stage number a turn's Bash call commits as green, or None."""
    content = msg.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != "Bash" or not isinstance(block.get("input"), dict):
            continue
        cmd = block["input"].get("command")
        if not isinstance(cmd, str):
            continue
        for subject in commit_subject(cmd):
            m = STAGE_GREEN.search(subject)
            if m:
                return int(m.group(1))
    return None


def locate_transcript(arg, env, home):
    """Return (path or None, reason when None)."""
    if arg:
        return arg, None
    sid = env.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None, "no --transcript and CLAUDE_CODE_SESSION_ID is unset"
    hits = sorted(glob.glob(os.path.join(home, ".claude", "projects", "*",
                                         glob.escape(sid) + ".jsonl")))
    if not hits:
        return None, f"no transcript for session {sid} under {home}/.claude/projects/*/"
    return hits[0], None


def measure(path):
    """Read the transcript. Returns a dict, or None when the file cannot be read.

    Keys: now (int or None), model (str or None), max_seen (int), rows (int),
    stage_costs (list), compactions (int).

    A stage's cost is the context at its `Stage N green` turn minus the baseline: the
    previous green turn, or the first turn of the session. A compaction row resets the
    baseline to the first turn after it, so no delta ever spans a compaction.
    """
    now = model = None
    max_seen = rows = compactions = 0
    baseline = None
    after_compaction = False
    stage_costs = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("type") == "user" and row.get("isCompactSummary") is True:
                compactions += 1
                baseline, after_compaction = None, True
                continue
            if row.get("type") != "assistant":
                continue
            if row.get("isSidechain") is True:
                continue
            msg = row.get("message")
            if not isinstance(msg, dict) or msg.get("model") == "<synthetic>":
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            try:
                ctx = (int(usage.get("input_tokens") or 0)
                       + int(usage.get("cache_read_input_tokens") or 0)
                       + int(usage.get("cache_creation_input_tokens") or 0))
            except (TypeError, ValueError):
                continue
            now, model = ctx, msg.get("model")
            max_seen = max(max_seen, ctx)
            rows += 1
            if baseline is None:
                baseline = ctx
            stage = stage_committed(msg)
            if stage is not None:
                stage_costs.append({"stage": stage, "cost": ctx - baseline, "from": baseline,
                                    "at": ctx, "after_compaction": after_compaction})
                baseline, after_compaction = ctx, False
    return {"now": now, "model": model, "max_seen": max_seen, "rows": rows,
            "stage_costs": stage_costs, "compactions": compactions}


def configured_model(env, cwd, home):
    """Return (source, model string) for the configured model, or None."""
    if env.get("ANTHROPIC_MODEL"):
        return "ANTHROPIC_MODEL", env["ANTHROPIC_MODEL"]
    for path in (os.path.join(cwd, ".claude", "settings.local.json"),
                 os.path.join(cwd, ".claude", "settings.json"),
                 os.path.join(home, ".claude", "settings.json")):
        # O_NONBLOCK: a FIFO in a cloned repo's .claude/ would block open() forever;
        # this way it reads empty and is skipped as malformed. Links are still
        # followed: dotfile managers link settings.json.
        try:
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            # OSError, ValueError, and the TypeError a non-blocking text read raises
            # on a FIFO with a writer and no data: all the same answer.
            continue
        if isinstance(data, dict) and isinstance(data.get("model"), str) and data["model"]:
            return path, data["model"]
    return None


def read_sidecar(cwd):
    """The parsed <cwd>/.claude/plan-context.json as a dict, or None for any failure;
    live_window() passes sidecar_root(cwd) as `cwd`.

    The same hardened read as core/hooks/plan_continue_classify.py (read_state,
    read_own_file): opened one component at a time — cwd, then `.claude` with
    O_NOFOLLOW | O_DIRECTORY, then the file with O_NOFOLLOW | O_NONBLOCK (a FIFO
    would otherwise block the open) — and checked on the open fd: regular file,
    owned by this user, at most MAX_SIDECAR_BYTES.
    """
    fds = []
    try:
        fds.append(os.open(cwd, os.O_RDONLY | os.O_DIRECTORY))
        fds.append(os.open(".claude", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                           dir_fd=fds[-1]))
        fds.append(os.open(SIDECAR, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=fds[-1]))
        st = os.fstat(fds[-1])
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or st.st_size > MAX_SIDECAR_BYTES):
            return None
        fh = os.fdopen(fds[-1], "r", encoding="utf-8", errors="replace")
        fds.pop()
        with fh:
            data = json.loads(fh.read(MAX_SIDECAR_BYTES + 1))
    except Exception:
        return None
    finally:
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
    return data if isinstance(data, dict) else None


def sidecar_root(cwd, require_state=False):
    """Where the sidecar lives: the nearest directory at or above cwd holding
    .claude/plan-progress.json, found as plan-progress.py's find_state() finds it;
    else cwd, or None with `require_state`. The executor may run this script from
    below the repo root, and the writer (--write-sidecar) uses this same function,
    so the two cannot disagree about where the file is."""
    try:
        start = pathlib.Path(cwd).resolve()
        for d in (start, *start.parents):
            if (d / ".claude" / "plan-progress.json").is_file():
                return str(d)
    except (OSError, ValueError):
        pass
    return None if require_state else cwd


def _count(v, top=None):
    """A non-negative int (no bool) at most `top`, else the sentinel False."""
    if type(v) is not int or v < 0 or (top is not None and v > top):
        return False
    return v


def write_sidecar(cwd, payload):
    """--write-sidecar: store the live window the planning mod hands over on stdin.

    Only `{session_id, window, tokens, percent, updated}` is written, each checked;
    anything else is dropped and a bad field writes nothing. Written at
    sidecar_root(cwd, require_state=True), never without a state file. The
    directory is a cloned repo's, so nothing is followed: `.claude` opens
    O_NOFOLLOW | O_DIRECTORY and must be this user's, the bytes go to a fresh
    O_EXCL | O_NOFOLLOW temporary beside it, and a rename puts it in place — a
    rename replaces whatever link or hardlink sat at the name instead of writing
    through it. Returns whether the file was written; never raises.
    """
    if not isinstance(payload, dict):
        return False
    sid, updated = payload.get("session_id"), payload.get("updated")
    window = payload.get("window")
    tokens = None if payload.get("tokens") is None else _count(payload.get("tokens"))
    percent = None if payload.get("percent") is None else _count(payload.get("percent"), 100)
    if (not isinstance(sid, str) or not 0 < len(sid) <= 200
            or type(window) is not int or window <= 0
            or tokens is False or percent is False
            or not isinstance(updated, str) or not 0 < len(updated) <= 40):
        return False
    body = json.dumps({"session_id": sid, "window": window, "tokens": tokens,
                       "percent": percent, "updated": updated}) + "\n"
    root = sidecar_root(cwd, require_state=True)
    if root is None:
        return False
    fds, tmp = [], f".{SIDECAR}.{os.getpid()}.tmp"
    try:
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
        fds.append(os.open(".claude", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                           dir_fd=fds[0]))
        if os.fstat(fds[1]).st_uid != os.getuid():
            return False
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                     dir_fd=fds[1])
        try:
            os.write(fd, body.encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, SIDECAR, src_dir_fd=fds[1], dst_dir_fd=fds[1])
        tmp = None
        return True
    except Exception:
        return False
    finally:
        if tmp is not None and len(fds) == 2:
            try:
                os.unlink(tmp, dir_fd=fds[1])
            except OSError:
                pass
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass


def live_window(env, cwd, now=None):
    """The window the live session reported in its sidecar, or None (see step 2)."""
    sid = env.get("CLAUDE_CODE_SESSION_ID")
    data = read_sidecar(sidecar_root(cwd)) if sid else None
    if not data or data.get("session_id") != sid:
        return None
    window = data.get("window")
    if type(window) is not int or window <= 0:
        return None
    updated = data.get("updated")
    if not isinstance(updated, str):
        return None
    try:
        ts = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    age = ((now or datetime.datetime.now(datetime.timezone.utc)) - ts).total_seconds()
    if not -SIDECAR_FUTURE_S <= age < SIDECAR_MAX_AGE_S:
        return None
    return window


def request_root(cwd):
    """The handoff root (the handoff protocol's) a rollover request lives under: the git top level —
    the same `<repo root>` session-handoff.md writes envelopes under — else the state
    root, else cwd."""
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return sidecar_root(cwd, require_state=True) or cwd


def owner_requested(env, cwd):
    """True when the supervisor's rollover request names this session. The reader is
    handoff-envelope.py's, imported rather than copied. A malformed or absent request
    is False. A reader that cannot be loaded is also False, but said on stderr: a
    silently dead reader would drop every owner request with nothing to show for it."""
    here = pathlib.Path(__file__).resolve().parent
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("handoff_envelope",
                                                      here / "handoff-envelope.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        reader, id_cmd_var = mod.request_pending, mod.ID_CMD_VAR
    except Exception as e:  # noqa: BLE001 — reported, then the measured rules decide
        print(f"context-usage: cannot load handoff-envelope.py ({type(e).__name__}: {e}); "
              "an owner rollover request cannot be read", file=sys.stderr)
        return False
    finally:
        sys.dont_write_bytecode = prior
    if not (env.get(id_cmd_var) or "").strip():
        return False                 # unsupervised: no request can name this session
    return bool(reader(request_root(cwd), env))


def table_entry(model):
    if not model:
        return None
    base = model[:-4] if model.endswith("[1m]") else model
    if base in MODEL_WINDOWS:
        return MODEL_WINDOWS[base]
    return MODEL_WINDOWS.get(DATED.sub("", base))


def resolve_window(model, window_arg, max_seen, configured, live=None):
    """Return (window or None, window_source)."""
    if window_arg:
        return window_arg, "--window"
    if live:
        return live, "window from live session"
    entry = table_entry(model)
    if entry is None:
        return None, "unlisted model"
    base, supports_1m = entry
    if supports_1m and base < ONE_M:
        if model.endswith("[1m]"):
            return ONE_M, "table+[1m] (transcript model id)"
        if configured and configured[1].endswith("[1m]"):
            return ONE_M, f"table+[1m] ({configured[0]}: {configured[1]})"
        if max_seen > base:
            return ONE_M, f"table+observed ({max_seen} > base {base})"
    return base, "table"


def stage_paths(plan_text):
    """Map stage number -> (set of path basenames, has_scope) from Scope:/Test: lines."""
    heads = list(STAGE_HEAD.finditer(plan_text))
    out = {}
    for i, h in enumerate(heads):
        body = plan_text[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(plan_text)]
        paths, has_scope = set(), False
        for f in FIELD.finditer(body):
            has_scope = has_scope or f.group(1) == "Scope"
            for tok in PATH_TOKEN.findall(f.group(2)):
                name = os.path.basename(tok.rstrip("/.,;:"))
                if name:
                    paths.add(name)
        out[int(h.group(1))] = (paths, has_scope)
    return out


def disjointness(plan_path, next_stage, done):
    """Return (True | False | "unknown", why) — is next_stage disjoint from every done stage?

    Paths are compared by basename, so a file named once in full and once bare still
    overlaps; a stage without any Scope: field cannot be judged and yields "unknown".
    Known false overlap: a prose abbreviation shaped like name.ext ("e.g.", "Node.js")
    recurring in two stages' fields counts as a shared path — it errs toward continue.
    """
    try:
        with open(plan_path, encoding="utf-8", errors="replace") as fh:
            stages = stage_paths(fh.read())
    except (OSError, ValueError):
        return "unknown", f"plan {plan_path} cannot be read"
    done = sorted(set(done) - {next_stage})
    if not done:
        return "unknown", "no other stage was committed green in this session"
    if next_stage not in stages:
        return "unknown", f"plan has no Stage {next_stage}"
    for n in [next_stage] + done:
        if n not in stages or not stages[n][1]:
            return "unknown", f"Stage {n} has no Scope: field"
    shared = set()
    for n in done:
        shared |= stages[next_stage][0] & stages[n][0]
    if shared:
        return False, f"Stage {next_stage} shares {', '.join(sorted(shared))} with this session's stages"
    return True, (f"Stage {next_stage} shares no Scope:/Test: path with stage(s) "
                  f"{', '.join(map(str, done))} done this session")


def verdict(result):
    """Return (verdict, reason) for a result dict built by main().

    Rules, in order — each reason names its rule and the numbers:
      requested          owner's rollover request for this session -> handoff, always
      other repository   next sub-plan runs elsewhere and a v2 reader is advertised -> handoff
      sub-plan boundary  handoff unless pct < 25
      first stage        no stage committed green this session -> continue, always
      context            pct > 50, or pct + last_stage_cost_pct > 50 -> handoff
      dead weight        next stage disjoint from this session's stages and pct > 25 -> handoff
    Anything unproven is `unknown`, which never stops a run.
    """
    if result.get("_requested"):
        return "handoff", "rule requested: owner asked for a rollover"
    if result.get("_other_root"):
        return "handoff", (f"rule sub-plan boundary: the next sub-plan runs in another "
                           f"repository, {result['_other_root']}")
    if result.get("_unknown"):
        return "unknown", result["_unknown"]
    pct, proj = result["pct"], result["projected_pct"]
    nums = (f"now={result['now']} of window={result['window']} "
            f"({result['window_source']}) is {pct}%")
    if result.get("_sub_plan_boundary"):
        if pct < FLOOR_PCT:
            return "continue", f"rule sub-plan boundary: {nums} < {FLOOR_PCT:g}% floor"
        return "handoff", f"rule sub-plan boundary: {nums} >= {FLOOR_PCT:g}% floor"
    if result["last_stage_cost"] is None:
        return "continue", (f"rule first stage: no Stage N green commit in this session, "
                            f"so the first stage of a session always runs; {nums}")
    if pct > HANDOFF_PCT:
        return "handoff", f"rule context: {nums} > {HANDOFF_PCT:g}%"
    if proj > HANDOFF_PCT:
        return "handoff", (f"rule context: {nums} + last_stage_cost={result['last_stage_cost']} "
                           f"projects {proj}% > {HANDOFF_PCT:g}%")
    dj = result.get("disjoint")
    if dj is True and pct > FLOOR_PCT:
        return "handoff", (f"rule dead weight: {result['_disjoint_why']}, and {nums} "
                           f"> {FLOOR_PCT:g}% floor")
    tail = f"; disjoint={dj} ({result['_disjoint_why']})" if dj is not None else ""
    return "continue", (f"rule context: {nums}, projected {proj}% <= {HANDOFF_PCT:g}%{tail}")


def other_root(args, env, cwd):
    """(root, why) for a sub-plan boundary: where the next sub-plan runs when that is another
    repository a reader can carry it to, and why that could not be decided, if so. A helper
    that cannot be loaded is said on stderr, then the measured rules decide."""
    if not args.sub_plan_boundary:
        return None, None
    if not args.plan:
        if "2" in env.get("PLANNING_HANDOFF_VERSIONS", "1").split(","):
            return None, "no --plan"
        return None, None
    here = str(pathlib.Path(__file__).resolve().parent)
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location(
            "handoff_destination", os.path.join(here, "handoff_destination.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.other_root(args.plan, cwd, env)
    except Exception as e:  # noqa: BLE001 — reported, then the measured rules decide
        print(f"context-usage: cannot check the next sub-plan's repository "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        return None, type(e).__name__
    finally:
        sys.dont_write_bytecode = prior


def build(args, env, cwd, home):
    res = {"now": None, "window": None, "window_source": None, "pct": None,
           "stage_costs": [], "last_stage_cost": None, "projected_pct": None,
           "model": None, "transcript": None, "compactions": None, "disjoint": None,
           "_sub_plan_boundary": args.sub_plan_boundary,
           "_requested": owner_requested(env, cwd),
           "_other_root": None, "_other_root_why": None}
    res["_other_root"], res["_other_root_why"] = other_root(args, env, cwd)
    path, why = locate_transcript(args.transcript, env, home)
    res["transcript"] = path
    if path is None:
        res["_unknown"] = why
        return res
    m = measure(path)
    if m is None:
        res["_unknown"] = f"transcript {path} cannot be read"
        return res
    if m["now"] is None:
        res["_unknown"] = f"transcript {path} has no main-thread assistant row with usage"
        return res
    res["now"], res["model"] = m["now"], m["model"]
    res["stage_costs"], res["compactions"] = m["stage_costs"], m["compactions"]
    if m["stage_costs"]:
        res["last_stage_cost"] = m["stage_costs"][-1]["cost"]
    window, source = resolve_window(m["model"], args.window, m["max_seen"],
                                    configured_model(env, cwd, home), live_window(env, cwd))
    res["window_source"] = source
    if window is None:
        res["_unknown"] = (f"model {m['model']!r} is not in MODEL_WINDOWS and no --window "
                           f"was given; now={m['now']}")
        return res
    res["window"] = window
    res["pct"] = round(m["now"] / window * 100, 1)
    if res["last_stage_cost"] is not None:
        res["projected_pct"] = round(res["pct"] + res["last_stage_cost"] / window * 100, 1)
    if args.plan:
        done = [c["stage"] for c in m["stage_costs"]]
        nxt = args.next_stage or (done[-1] + 1 if done else None)
        if nxt is None:
            res["disjoint"], res["_disjoint_why"] = "unknown", "no stage committed green yet"
        else:
            res["disjoint"], res["_disjoint_why"] = disjointness(args.plan, nxt, done)
    return res


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}")
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0: {n}")
    return n


def fmt(v):
    return "null" if v is None else str(v)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="context-usage")
    ap.add_argument("--transcript", help="transcript JSONL path (overrides the session id)")
    ap.add_argument("--window", type=positive_int, help="context window in tokens (wins)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--plan", help="plan file, to judge the next stage's disjointness")
    ap.add_argument("--next-stage", type=positive_int,
                    help="stage about to open (default: last stage green here + 1)")
    ap.add_argument("--sub-plan-boundary", action="store_true",
                    help="a master plan's sub-plan just closed: handoff unless pct < 25, "
                         "or always when --plan's next sub-plan runs in another repository")
    ap.add_argument("--write-sidecar", action="store_true",
                    help="store the live window JSON on stdin as the sidecar (the planning "
                         "mod's writer); prints {\"written\": bool}, always exits 0")
    args = ap.parse_args(argv)

    if args.write_sidecar:
        try:
            payload = json.loads(sys.stdin.read(MAX_SIDECAR_BYTES + 1) or "null")
        except Exception:
            payload = None
        print(json.dumps({"written": write_sidecar(os.getcwd(), payload)}))
        return 0

    res = build(args, os.environ, os.getcwd(), os.path.expanduser("~"))
    res["verdict"], res["reason"] = verdict(res)
    if res["_other_root_why"] and res["verdict"] != "handoff":
        res["reason"] += (f"; the next sub-plan's repository was not checked "
                          f"({res['_other_root_why']}), so another repository may be next")
    for k in [k for k in res if k.startswith("_")]:
        res.pop(k)

    if args.format == "json":
        print(json.dumps(res))
    else:
        print(f"context-usage: verdict={res['verdict']} now={fmt(res['now'])} "
              f"window={fmt(res['window'])} pct={fmt(res['pct'])} "
              f"projected_pct={fmt(res['projected_pct'])} disjoint={fmt(res['disjoint'])} "
              f"reason: {res['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
