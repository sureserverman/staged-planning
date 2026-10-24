#!/usr/bin/env python3
"""Report the current OpenCode session's context size from its session store.

Why this exists: a plan executor deciding whether to hand off to a fresh session
needs a measured reason, not a feeling that "the context is getting long". OpenCode
records every model call's token accounting in its session store, so the context size
at the latest call is a number the executor can read rather than guess. The stop rules
this number feeds are session-handoff.md's.

OPENCODE FORK. The core reads a Claude Code transcript and resolves the window from a
model table. OpenCode keeps neither: it writes sessions, messages and message parts to
a SQLite store, and its models cache records each model's context window. So this fork
replaces the session reader, the stage-boundary reader and the window resolution, and
drops what only a Claude Code session feeds: the model table, the configured-model
lookup, and the live-window sidecar the Claude Code planning mod writes (with its
`--write-sidecar` writer). It also drops the rollover-request rule: the supervised
handoff is not carried on OpenCode, so no supervisor's request can name this session,
and the rules stay four. Every other rule, the commit-subject reader and the
disjointness test are the core's, unchanged.

What it reads, from `$XDG_DATA_HOME/opencode/opencode.db` (default
`~/.local/share/opencode/opencode.db`), opened read-only (`mode=ro`); the store runs in
WAL mode, so SQLite may create its `-shm`/`-wal` side files, as OpenCode itself does:

    session  `--session ID` if given; else the newest top-level `session` row (no
             `parent_id`: a subagent's session shares its parent's directory) whose
             `directory` is this cwd, by `time_updated`. OpenCode puts no session id
             in a tool shell's environment, so two sessions open in one directory can
             measure the wrong one: the reason names the session read; re-run with
             `--session` when it is not yours.
    now      the LAST assistant message's `tokens.input + tokens.cache.read +
             tokens.cache.write`. The `session` table's token columns are running
             totals, not context. A message whose sum is 0 is skipped: an errored or
             unfinished call records none.
    window   `limit.context` for that message's `providerID`/`modelID` in
             `$XDG_CACHE_HOME/opencode/models.json` (default `~/.cache/opencode/`), the
             models cache OpenCode writes itself; a model it does not list is verdict
             `unknown`. `--window N` wins.
    compact  an assistant message with `summary: true` resets the stage-cost
             baseline, so no cost spans one. Its own tokens are the summarising call's,
             the context before compaction, so it is a marker, never `now` or a baseline.
    boundary a `part` row of the session with `type: "tool"`, `tool: "bash"` and
             `state.status: "completed"`, whose `state.input.command` runs a `git
             commit` with `Stage N green` in its SUBJECT; its cost is taken at the
             context of the message that issued it. A part still running, or one in
             state `error`, is not a boundary: its commit did not run or did not succeed.

`--transcript PATH` is kept as an alias that takes a store path, so a test needs no
`HOME`. The store's schema is OpenCode's internal one, not a published interface; a row
this fork does not recognise is skipped, and a session with no usage is `unknown`.

Verdicts: `handoff` when pct > 50, else `continue`; `unknown` for anything the
script cannot prove. Every verdict carries a `reason` naming the rule and numbers.
An `unknown` verdict never stops a run: exit 0. Exit 2 only on bad CLI usage.

Stdlib only.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.parse

HANDOFF_PCT = 50.0
# Floor under the dead-weight and sub-plan-boundary rules: below it a fresh session buys
# too little to be worth the handoff.
FLOOR_PCT = 25.0

STAGE_HEAD = re.compile(r"^## Stage (\d+)\b", re.M)
FIELD = re.compile(r"^\s*- \*\*(Scope|Test):\*\*(.*)$", re.M)
# A path token: something with a slash, or a name with a file extension.
PATH_TOKEN = re.compile(r"[\w.\-]*[A-Za-z_][\w\-]*\.[A-Za-z][A-Za-z0-9]{0,6}\b|[\w.\-]+/[\w.\-/]+")

# A stage boundary is the executed command that runs `git ... commit` in command
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



def _json(text):
    """A row's `data` column as a dict, or None when it is not a JSON object."""
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def stage_committed(part):
    """Return the stage number a `part` row's executed command commits as green, or None.

    Only a `bash` tool part in state `completed` counts: the command RAN and exited.
    A part still `pending`/`running` has not run yet; one in `error` made no commit to
    count.
    """
    if part.get("type") != "tool" or part.get("tool") != "bash":
        return None
    state = part.get("state")
    if not isinstance(state, dict) or state.get("status") != "completed":
        return None
    inp = state.get("input")
    cmd = inp.get("command") if isinstance(inp, dict) else None
    if not isinstance(cmd, str):
        return None
    for subject in commit_subject(cmd):
        m = STAGE_GREEN.search(subject)
        if m:
            return int(m.group(1))
    return None


def _usage(msg):
    """input + cache.read + cache.write of an assistant message, or 0."""
    tokens = msg.get("tokens")
    if not isinstance(tokens, dict):
        return 0
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    try:
        return int(tokens.get("input") or 0) + int(cache.get("read") or 0) + int(cache.get("write") or 0)
    except (TypeError, ValueError):
        return 0


def _connect(db):
    """A read-only connection to the store, or None when it cannot be opened."""
    try:
        uri = "file:" + urllib.parse.quote(os.path.abspath(db)) + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        con.execute("select 1 from session limit 1")
        return con
    except sqlite3.Error:
        return None


def default_db(env, home):
    return os.path.join(env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"),
                        "opencode", "opencode.db")


def default_models(env, home):
    return os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"),
                        "opencode", "models.json")


def locate_session(con, session, cwd):
    """Return (session id or None, reason when None)."""
    if session:
        row = con.execute("select id from session where id = ?", (session,)).fetchone()
        return (row[0], None) if row else (None, f"no session {session} in the store")

    def real(path):
        try:
            return os.path.realpath(path)
        except (OSError, ValueError):
            return path

    here = real(cwd)
    rows = con.execute("select id, directory from session where parent_id is null "
                       "order by time_updated desc, id desc").fetchall()
    for sid, directory in rows:
        if isinstance(directory, str) and real(directory) == here:
            return sid, None
    return None, f"no --session and no top-level session in the store records directory {cwd}"


def measure(con, sid):
    """Read one session's messages and parts. Returns a dict, or None on a store error.

    Keys: now (int or None), model (str or None), provider (str or None), rows (int),
    stage_costs (list), compactions (int).

    A stage's cost is the context at its `Stage N green` command minus the baseline:
    the previous green command, or the first counted message of the session. A
    `summary: true` message resets the baseline to the first counted message after it,
    so no delta ever spans a compaction.
    """
    now = model = provider = None
    rows = compactions = 0
    baseline = None
    after_compaction = False
    stage_costs = []
    try:
        msgs = con.execute("select id, data from message where session_id = ? "
                           "order by time_created, id", (sid,)).fetchall()
        parts = {}
        for mid, data in con.execute("select message_id, data from part where session_id = ? "
                                     "order by time_created, id", (sid,)):
            parts.setdefault(mid, []).append(data)
    except sqlite3.Error:
        return None
    for mid, data in msgs:
        msg = _json(data)
        if msg is None or msg.get("role") != "assistant":
            continue
        if msg.get("summary") is True:
            compactions += 1
            baseline, after_compaction = None, True
            continue
        ctx = _usage(msg)
        if ctx > 0:
            now, rows = ctx, rows + 1
            if isinstance(msg.get("modelID"), str):
                model = msg["modelID"]
                provider = msg.get("providerID") if isinstance(msg.get("providerID"), str) else None
            if baseline is None:
                baseline = ctx
        for pdata in parts.get(mid, ()):
            part = _json(pdata)
            stage = stage_committed(part) if part else None
            if stage is not None and now is not None and baseline is not None:
                stage_costs.append({"stage": stage, "cost": now - baseline, "from": baseline,
                                    "at": now, "after_compaction": after_compaction})
                baseline, after_compaction = now, False
    return {"now": now, "model": model, "provider": provider, "rows": rows,
            "stage_costs": stage_costs, "compactions": compactions}


def model_window(path, provider, model):
    """`limit.context` for provider/model in the models cache, or None."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        win = int(data[provider]["models"][model]["limit"]["context"])
        return win if win > 0 else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


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
      sub-plan boundary  handoff unless pct < 25
      first stage        no stage committed green this session -> continue, always
      context            pct > 50, or pct + last_stage_cost_pct > 50 -> handoff
      dead weight        next stage disjoint from this session's stages and pct > 25 -> handoff
    Anything unproven is `unknown`, which never stops a run.
    """
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



def build(args, env, cwd, home):
    res = {"now": None, "window": None, "window_source": None, "pct": None,
           "stage_costs": [], "last_stage_cost": None, "projected_pct": None,
           "model": None, "transcript": None, "session": None, "compactions": None,
           "disjoint": None, "_sub_plan_boundary": args.sub_plan_boundary}
    db = args.transcript or default_db(env, home)
    res["transcript"] = db
    if not os.path.isfile(db):
        res["_unknown"] = f"no OpenCode store at {db}"
        return res
    con = _connect(db)
    if con is None:
        res["_unknown"] = f"store {db} cannot be opened read-only"
        return res
    try:
        sid, why = locate_session(con, args.session, cwd)
        res["session"] = sid
        if sid is None:
            res["_unknown"] = why
            return res
        m = measure(con, sid)
    except sqlite3.Error as e:
        res["_unknown"] = f"store {db} cannot be read: {e}"
        return res
    finally:
        con.close()
    if m is None:
        res["_unknown"] = f"store {db} cannot be read"
        return res
    if m["now"] is None:
        res["_unknown"] = f"session {sid} has no assistant message with usage"
        return res
    res["now"] = m["now"]
    res["model"] = f"{m['provider']}/{m['model']}" if m["provider"] else m["model"]
    res["stage_costs"], res["compactions"] = m["stage_costs"], m["compactions"]
    if m["stage_costs"]:
        res["last_stage_cost"] = m["stage_costs"][-1]["cost"]
    models = args.models or default_models(env, home)
    if args.window:
        window, source = args.window, f"session {sid}, --window"
    else:
        window = model_window(models, m["provider"], m["model"])
        source = f"session {sid}, {res['model']} limit.context in {models}"
    res["window_source"] = source
    if window is None:
        res["_unknown"] = (f"session {sid}: {res['model']} has no limit.context in {models} "
                           f"and no --window was given; now={m['now']}")
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
    ap.add_argument("--session", help="OpenCode session id (default: newest top-level for cwd)")
    ap.add_argument("--transcript", help="opencode.db path (default: the XDG data dir's)")
    ap.add_argument("--models", help="models.json path (default: the XDG cache dir's)")
    ap.add_argument("--window", type=positive_int, help="context window in tokens (wins)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--plan", help="plan file, to judge the next stage's disjointness")
    ap.add_argument("--next-stage", type=positive_int,
                    help="stage about to open (default: last stage green here + 1)")
    ap.add_argument("--sub-plan-boundary", action="store_true",
                    help="a master plan's sub-plan just closed: handoff unless pct < 25")
    args = ap.parse_args(argv)

    res = build(args, os.environ, os.getcwd(), os.path.expanduser("~"))
    res["verdict"], res["reason"] = verdict(res)
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
