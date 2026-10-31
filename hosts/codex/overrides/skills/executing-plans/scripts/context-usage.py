#!/usr/bin/env python3
"""Report the current Codex session's context size from its rollout.

Why this exists: a plan executor deciding whether to hand off to a fresh session
needs a measured reason, not a feeling that "the context is getting long". Codex
writes every turn's token accounting into the session's rollout file, so the context
size at the latest turn is a number the executor can read rather than guess.

CODEX FORK. The core reads a Claude Code transcript and resolves the window from a
model table. Codex keeps neither: it writes a rollout under
`$CODEX_HOME/sessions/<Y>/<M>/<D>/rollout-*-<thread id>.jsonl` (CODEX_HOME defaults to
~/.codex), and each `token_count` row there records the window itself. So this fork
replaces the session reader, the stage-boundary reader and the window resolution, and
drops what only a Claude Code session feeds: the model table, the configured-model
lookup, and the live-window sidecar the Claude Code planning mod writes (with its
`--write-sidecar` writer). Every rule, the commit-subject reader, the disjointness test
and the rollover-request lookup are the core's, unchanged.

What it reads from the rollout:

    session  `--transcript PATH` if given; else the rollout whose name ends in
             `$CODEX_THREAD_ID` (Codex sets it in a tool shell, and it is the
             rollout's `session_meta` id); else the newest rollout whose
             `session_meta` cwd is this cwd; else verdict `unknown`, naming what
             was looked for.
    now      the LAST `event_msg` `token_count` row's
             `info.last_token_usage.input_tokens`, which already counts cached input.
             A row whose input_tokens is 0 is skipped: Codex writes one right after
             every compaction, a placeholder that is never `now` or a baseline.
    window   the last non-zero `info.model_context_window` seen. `--window N` wins.
    compact  a `compacted` row resets the stage-cost baseline, so no cost spans one.
    boundary an `event_msg` `item_completed` row whose `item.type` is
             `CommandExecution`, whose `status` is `completed`, and whose
             `item.command[-1]` runs a `git commit` with `Stage N green` in its
             SUBJECT; its cost is taken at the last `token_count` row before it. A
             command that was only issued, or that failed, made no commit to count.

Codex calls the rollout format "not a stable interface". A row shape this fork does
not recognise is skipped, and a rollout with no `token_count` row is verdict `unknown`.

Verdicts: `handoff` when pct > 50, else `continue`; `unknown` for anything the
script cannot prove. An owner's rollover request — the supervisor's request file,
naming the id the supervisor's identity command gives this session, read only by handoff-envelope.py's
reader (no second parser) — is `handoff` whatever else holds (rule requested); the
executor runs this script only at a gate, so the request still lands at one. The
request is looked up at the git top level, else the nearest directory holding `.claude/plan-progress.json`, else cwd —
the one handoff root the handoff protocol names, where the supervisor writes it. A reader that cannot load says so on
stderr and changes no verdict. Every verdict carries a `reason` naming the rule and numbers.
An `unknown` verdict never stops a run: exit 0. Exit 2 only on bad CLI usage.

Stdlib only.
"""
import argparse
import glob
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

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


def stage_committed(row):
    """Return the stage number a rollout row's executed command commits as green, or None.

    Only an `event_msg` `item_completed` row carrying a `CommandExecution` item whose
    `status` is `completed` counts: that is the command having RUN and succeeded. A
    `failed` one made no commit to count. Its `command` is an argv list whose last
    element is the shell script (`["/bin/bash", "-lc", "<script>"]`).
    """
    payload = row.get("payload")
    if row.get("type") != "event_msg" or not isinstance(payload, dict):
        return None
    if payload.get("type") != "item_completed":
        return None
    item = payload.get("item")
    if not isinstance(item, dict) or item.get("type") != "CommandExecution":
        return None
    if item.get("status") != "completed":
        return None
    argv = item.get("command")
    if not isinstance(argv, list) or not argv or not isinstance(argv[-1], str):
        return None
    for subject in commit_subject(argv[-1]):
        m = STAGE_GREEN.search(subject)
        if m:
            return int(m.group(1))
    return None


def _rows(path):
    """Yield each JSON object row of a rollout; malformed and non-object lines are skipped."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _session_cwd(path):
    """Return the `session_meta` payload's cwd, or None."""
    try:
        for row in _rows(path):
            if row.get("type") == "session_meta":
                payload = row.get("payload")
                return payload.get("cwd") if isinstance(payload, dict) else None
    except OSError:
        return None
    return None


def codex_home(env, home):
    """Codex's home: $CODEX_HOME when set, else ~/.codex."""
    return env.get("CODEX_HOME") or os.path.join(home, ".codex")


def locate_transcript(arg, env, home, cwd):
    """Return (path or None, reason when None)."""
    if arg:
        return arg, None
    root = os.path.join(codex_home(env, home), "sessions")
    tid = env.get("CODEX_THREAD_ID")
    if tid:
        hits = sorted(glob.glob(os.path.join(root, "*", "*", "*",
                                             "rollout-*-" + glob.escape(tid) + ".jsonl")))
        if hits:
            return hits[0], None

    def mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:        # pruned between the glob and the sort
            return -1.0

    def real(path):
        try:
            return os.path.realpath(path)
        except (OSError, ValueError):
            return path

    here = real(cwd)
    rollouts = glob.glob(os.path.join(root, "*", "*", "*", "rollout-*.jsonl"))
    for path in sorted(rollouts, key=mtime, reverse=True):
        rec = _session_cwd(path)
        if isinstance(rec, str) and real(rec) == here:
            return path, None
    looked = f"CODEX_THREAD_ID={tid}" if tid else "CODEX_THREAD_ID unset"
    return None, (f"no --transcript, {looked}, and no rollout under {root}/*/*/*/ "
                  f"records cwd {cwd}")


def measure(path):
    """Read the rollout. Returns a dict, or None when the file cannot be read.

    Keys: now (int or None), window (int or None), model (str or None), rows (int),
    stage_costs (list), compactions (int).

    A stage's cost is the context at its `Stage N green` command minus the baseline:
    the previous green command, or the first `token_count` row of the session. A
    `compacted` row resets the baseline to the first `token_count` row after it, so
    no delta ever spans a compaction.
    """
    now = window = model = None
    rows = compactions = 0
    baseline = None
    after_compaction = False
    stage_costs = []
    try:
        for row in _rows(path):
            kind = row.get("type")
            payload = row.get("payload")
            if kind == "compacted":
                compactions += 1
                baseline, after_compaction = None, True
                continue
            if not isinstance(payload, dict):
                continue
            if kind == "turn_context" and isinstance(payload.get("model"), str):
                model = payload["model"]
                continue
            if kind == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict) or not isinstance(info.get("last_token_usage"), dict):
                    continue
                try:
                    ctx = int(info["last_token_usage"].get("input_tokens") or 0)
                    win = info.get("model_context_window")
                    win = int(win) if win is not None else None
                except (TypeError, ValueError):
                    continue
                # A zero-usage token_count follows every compaction: a placeholder,
                # never a baseline and never `now`.
                if ctx <= 0:
                    continue
                now, rows = ctx, rows + 1
                if win:
                    window = win
                if baseline is None:
                    baseline = ctx
                continue
            stage = stage_committed(row)
            if stage is not None and now is not None and baseline is not None:
                stage_costs.append({"stage": stage, "cost": now - baseline, "from": baseline,
                                    "at": now, "after_compaction": after_compaction})
                baseline, after_compaction = now, False
    except OSError:
        return None
    return {"now": now, "window": window, "model": model, "rows": rows,
            "stage_costs": stage_costs, "compactions": compactions}


def sidecar_root(cwd, require_state=False):
    """Where the sidecar lives: the nearest directory at or above cwd holding
    .claude/plan-progress.json, found as plan-progress.py's find_state() finds it;
    else cwd, or None with `require_state`. The executor may run this script from
    below the repo root. Kept from the core for request_root(), its one caller here."""
    try:
        start = pathlib.Path(cwd).resolve()
        for d in (start, *start.parents):
            if (d / ".claude" / "plan-progress.json").is_file():
                return str(d)
    except (OSError, ValueError):
        pass
    return None if require_state else cwd


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
    """Where the next sub-plan runs, when that is another repository a reader can carry it to."""
    if not (args.sub_plan_boundary and args.plan):
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import handoff_destination
    return handoff_destination.other_root(args.plan, cwd, env)


def build(args, env, cwd, home):
    res = {"now": None, "window": None, "window_source": None, "pct": None,
           "stage_costs": [], "last_stage_cost": None, "projected_pct": None,
           "model": None, "transcript": None, "compactions": None, "disjoint": None,
           "_sub_plan_boundary": args.sub_plan_boundary,
           "_requested": owner_requested(env, cwd),
           "_other_root": other_root(args, env, cwd)}
    path, why = locate_transcript(args.transcript, env, home, cwd)
    res["transcript"] = path
    if path is None:
        res["_unknown"] = why
        return res
    m = measure(path)
    if m is None:
        res["_unknown"] = f"rollout {path} cannot be read"
        return res
    if m["now"] is None:
        res["_unknown"] = f"rollout {path} has no token_count row"
        return res
    res["now"], res["model"] = m["now"], m["model"]
    res["stage_costs"], res["compactions"] = m["stage_costs"], m["compactions"]
    if m["stage_costs"]:
        res["last_stage_cost"] = m["stage_costs"][-1]["cost"]
    if args.window:
        window, source = args.window, "--window"
    else:
        window, source = m["window"], "rollout model_context_window"
    res["window_source"] = source
    if window is None:
        res["_unknown"] = (f"rollout {path} records no model_context_window and no --window "
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
    ap.add_argument("--transcript", help="rollout JSONL path (overrides the thread id)")
    ap.add_argument("--window", type=positive_int, help="context window in tokens (wins)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--plan", help="plan file, to judge the next stage's disjointness")
    ap.add_argument("--next-stage", type=positive_int,
                    help="stage about to open (default: last stage green here + 1)")
    ap.add_argument("--sub-plan-boundary", action="store_true",
                    help="a master plan's sub-plan just closed: handoff unless pct < 25, "
                         "or always when --plan's next sub-plan runs in another repository")
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
