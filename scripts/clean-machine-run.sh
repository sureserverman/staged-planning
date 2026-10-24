#!/usr/bin/env bash
# One headless run of the plugin on a clean machine: a throwaway HOME that holds only the
# login credentials and the plugins named on the command line, a toy git repo with one
# failing test, and one fixed prompt that drives brainstorm -> Light plan -> execute
# through its gate. It then checks that the workflow ran, where the plan landed, that the
# toy test now passes, and that nothing changed in the --watch dirs.
#
# Why this exists: a plugin that passes its own suite on the author's machine can still
# depend on that machine (a sibling plugin, a config file, a notes folder). Only a run
# with nothing else installed shows that. The verdict is six facts, all required for PASS:
#   - at least one --plugin was installed (a run with none exits 2);
#   - skills_seen holds planning:brainstorming, planning:planning-projects and
#     planning:executing-plans, in that order (a Skill call counts only when its
#     tool_result came back and is not an error);
#   - records_under equals --expect;
#   - toy_test_exit is 0: the toy's own test (python3 -I tests/test_calc.py, isolated so no
#     user site-packages or usercustomize in the throwaway HOME can fake it), which the
#     session must not edit, run inside the toy repo after the session under the same clean env;
#   - outside_changes is empty;
#   - the session exited 0.
#
# What is measured, and what is not:
#   - outside_changes covers the --watch dirs (each resolved through symlinks), from
#     before the plugin install and --setup until after the session, by mtime and ctime,
#     and the temp dirs: /tmp and, when it differs (a caller's TMPDIR), the dir the run
#     root lives in. A name created at the top level of either, owned by this user, during
#     the run (other than the run root and the evidence path's top folder there) is an
#     outside change too. The session's TMPDIR is <run root>/tmp, so a host's own scratch
#     stays inside the run. Not exact: a name any other process of this user creates there
#     during the run (another session, a parallel harness run's own root) is reported too;
#     a write into the evidence path's top folder is hidden; a rewrite of a name that
#     already existed, or a write anywhere else on the machine, is not seen. The listing
#     is portable (python3, not GNU find); if it fails, the run fails. CLEAN_MACHINE_SYS_TMP
#     replaces /tmp (the suite points it at its own dir).
#   - Plan candidates are new *.md files whose first `# ` heading is a planning record title
#     (`# Design:`, `# Light Plan:`, `# Project Plan:` or `# Master Plan:`), in the toy repo,
#     the throwaway HOME (its plugin dir too, less the files that were there before the
#     session), the plugin's install copies (less the files the install put there) and the
#     --watch dirs. The title decides, not the path, because a host can
#     sync other docs into a fresh HOME. Titles match case-insensitively. A plan written
#     anywhere else, or without such a title, is not seen. A design alone is not a plan:
#     with no Light, Project or Master Plan title among the candidates, records_under is
#     none.
#   - Each --plugin marketplace is installed from a copy inside the run's temp root: a git
#     repo's committed tree (`git archive HEAD`), else the directory as it is. A host
#     installs a local marketplace in place, so without the copy the plugin's own writes
#     (a Python bytecode cache, say) would land in the source checkout. A real install
#     lands in the host's plugin cache, which the copy stands in for, and the run tests
#     what is committed, not the working tree. `git archive` honours .gitattributes
#     (export-ignore, export-subst) and leaves submodules out, as a packaged release would.
#     A marketplace that is a subdirectory of a repo, or not a repo, is copied as it is,
#     working-tree files included. host.log names which copy each plugin got.
#   - The session runs under env -i, but PATH is passed through, so it still finds the
#     tools on this machine's PATH: a residual dependency on this machine.
#   - On Codex (--host codex) the login file is $CODEX_HOME/auth.json, the plugin command is
#     `plugin add`, and the session is `codex exec --json -s workspace-write -C <toy>`. The
#     sandbox keeps a workspace's .git read-only, which stops the commits executing-plans
#     makes, so <toy>/.git is added with --add-dir (the Claude path allows `git` the same
#     way); so is the test vault. Hooks stay untrusted: no trust is written and none is
#     bypassed. The session is not --ephemeral, because its rollout under $CODEX_HOME/sessions
#     is the only record of which skills it loaded; the rollout stays in the throwaway HOME
#     and goes with it. A skill counts in skills_seen when the rollout shows Codex injected it
#     (a `$planning:<skill>` mention it resolved) from that skill's own SKILL.md (in a
#     folder named for the skill, under the named plugin's dir) in the HOME's plugin cache. A skill the model opens by
#     itself is not counted. Codex injects every mentioned
#     skill at the start of the turn, sorted by name, so on Codex the verdict needs all three
#     injected and does not judge their order. Only those injections are
#     copied into the transcript, never the whole rollout, which also names the account.
#     Codex may refresh the login in the auth copy during the session. Whether that retires
#     the token in the --credentials file was not measured: pass a login made for these runs
#     if that matters. The source file itself is only read, never written.
#     The workspace-write sandbox also lets the session write the system temp dir, and the
#     throwaway HOME lives there: the session could change its own auth copy, plugin cache
#     or rollout, and a write elsewhere in the temp dir is not seen unless it is a --watch dir.
#   - On Cursor (--host cursor) the login file is $HOME/.config/cursor/auth.json, each
#     --plugin is copied to $HOME/.cursor/plugins/local/<id> (there is no plugin command),
#     and the session is `cursor-agent -p --trust --force --output-format stream-json`. A skill
#     counts in skills_seen when the transcript shows a successful readToolCall of its own
#     SKILL.md (<id>/skills/<skill>/SKILL.md under that local dir; the name is
#     <id less any @...>:<skill>). Cursor loads a skill by reading it, so a read is the
#     record. As on Codex, the three must be present; their order is not judged.
#   - On OpenCode (--host opencode) the login file is $HOME/.local/share/opencode/auth.json
#     and --model is required (with none, the default model can be one the provider has
#     retired). Each --plugin is copied to $HOME/.local/share/opencode-plugins/<id> and
#     written into $HOME/.config/opencode/opencode.json in the recorded install shape
#     (hosts/opencode/host.yaml install_shape): a package (a dir with package.json) loads
#     by local path, a `plugin` entry naming its main module; a plugin dir without one
#     adds its skills/ to `skills.paths`. Such a dir's commands and permission entries are
#     its own installer's to write, so a --setup script runs that step. The flow is three
#     `opencode run -m <model> --format json` prompts, one per step, each naming its skill
#     (auto-trigger is unreliable there); the second and third --continue the session.
#     A skill counts in skills_seen when the transcript shows a completed `skill` tool call
#     whose metadata.dir is that skill's own folder in an installed copy
#     (<id>/skills/<skill> under .local/share/opencode-plugins, holding its SKILL.md); the
#     name is <id>:<skill>, and the three must come from the first --plugin.
#     `opencode run` can refuse a write and still exit 0, which is why
#     records_under is always read from disk.
#   - The session leads its own session. When it ends, every process in that session is
#     killed, then its process group, so a background child cannot write after the check,
#     even one that moved to a process group of its own. A child that starts a new session
#     of its own (setsid) escapes that.
#
# Usage:
#   clean-machine-run.sh --credentials <file> --evidence <dir>
#       --plugin <marketplace-dir> <plugin@mkt> [--plugin <marketplace-dir> <plugin@mkt>]...
#       [--host claude|codex|cursor|opencode]
#       [--home-file <relpath>=<src>]... [--test-vault <dir>] [--setup <script>]
#       [--watch <dir>]... [--expect docs|test-vault] [--model <id>] [--exec <bin>]
#
#   --credentials  the host's login file; copied, mode 600, into the throwaway HOME only
#                  (Claude: $HOME/.claude/.credentials.json; Codex: $HOME/.codex/auth.json;
#                  Cursor: $HOME/.config/cursor/auth.json;
#                  OpenCode: $HOME/.local/share/opencode/auth.json)
#   --evidence     where asserts.json, transcript.jsonl and host.log are written; must be
#                  outside this repo (transcripts carry machine paths)
#   --host         default claude; claude, codex, cursor or opencode (others exit 2)
#   --plugin       a local marketplace dir and the plugin id to install from it; at least
#                  one is required, and it is repeatable. On Cursor the dir is the plugin
#                  itself and the id may be a bare name (the local dir's name); on OpenCode
#                  the dir is the built package or plugin dir and the id is a bare name
#                  (the install dir's name).
#   --home-file    place <src> at $HOME/<relpath> in the throwaway HOME; repeatable
#   --test-vault   copied to $CLEAN_HOME/test-vault before --setup runs
#   --setup        run once after the plugins are installed, with CLEAN_HOME and CLEAN_HOST
#                  (the --host) set, and CLEAN_TEST_VAULT when --test-vault is given
#   --watch        a dir that must not change during the run; repeatable, and at least one
#                  is required (only these dirs are checked for outside changes)
#   --expect       where the plan must land: docs (<toy>/docs/, default) or test-vault
#   --model        passed to the session; required on OpenCode
#   --exec         replaces the host binary (the suite passes a stub)
#
# Evidence paths are rewritten to labels: <toy>, <home>, <test-vault>, <plugin:N>,
# <watch:N>, <run>. The credentials are never printed, logged or copied anywhere else.
# The secrets of the --credentials file are read before anything runs, into memory only
# (never an argument list or the session's environment): every string value of 20+ chars,
# or of 8+ chars under a key naming a token, key or secret; for a file that is not JSON,
# its whole stripped content and each 16+ character word of it. They are redacted from the
# evidence (the transcript, the log, the plan and outside-change names, the host version
# and the error), as is any 16+ character piece of one and any secret the copy holds after
# the session. A run whose evidence needed a redaction fails. The copy is shredded
# (or removed) on every exit path that can be trapped, and the throwaway root with it;
# a SIGKILL cannot be trapped, so after one the copy and the root remain.
#
# Exit: 0 pass; 1 the run failed or an assertion did not hold; 2 usage error.
set -uo pipefail

usage() { sed -n '/^# Usage:/,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//'; }
die2() { echo "clean-machine-run: $*" >&2; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

CREDS=""; EVID=""; HOST=claude; EXPECT=docs; MODEL=""; EXEC=""; SETUP=""; TV_SRC=""
PLUGIN_DIRS=(); PLUGIN_IDS=(); HOME_FILES=(); WATCHES=()

need() { [ "$2" -ge 2 ] || die2 "$1 needs a value"; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --credentials) need "$1" "$#"; CREDS="$2"; shift 2 ;;
        --evidence)    need "$1" "$#"; EVID="$2"; shift 2 ;;
        --host)        need "$1" "$#"; HOST="$2"; shift 2 ;;
        --plugin)      [ "$#" -ge 3 ] || die2 "--plugin needs <marketplace-dir> <plugin@mkt>"
                       PLUGIN_DIRS+=("$2"); PLUGIN_IDS+=("$3"); shift 3 ;;
        --home-file)   need "$1" "$#"; HOME_FILES+=("$2"); shift 2 ;;
        --test-vault)  need "$1" "$#"; TV_SRC="$2"; shift 2 ;;
        --setup)       need "$1" "$#"; SETUP="$2"; shift 2 ;;
        --watch)       need "$1" "$#"; WATCHES+=("$2"); shift 2 ;;
        --expect)      need "$1" "$#"; EXPECT="$2"; shift 2 ;;
        --model)       need "$1" "$#"; MODEL="$2"; shift 2 ;;
        --exec)        need "$1" "$#"; EXEC="$2"; shift 2 ;;
        *) die2 "unknown argument '$1' (see --help)" ;;
    esac
done

case "$HOST" in
    claude|codex|cursor|opencode) ;;
    *) die2 "--host must be claude, codex, cursor or opencode" ;;
esac
if [ "$HOST" = opencode ]; then
    [ -n "$MODEL" ] || die2 "--host opencode needs --model: with none, the default model can be one the provider has retired"
fi
# The credentials path is never echoed, so a mistyped one cannot reach a log.
[ -n "$CREDS" ] || die2 "--credentials is required"
[ -f "$CREDS" ] && [ -r "$CREDS" ] || die2 "the --credentials file is not a readable file"
[ -n "$EVID" ] || die2 "--evidence is required"
case "$EXPECT" in docs|test-vault) ;; *) die2 "--expect must be docs or test-vault" ;; esac
[ "$EXPECT" = test-vault ] && [ -z "$TV_SRC" ] && die2 "--expect test-vault needs --test-vault"
[ -z "$TV_SRC" ] || [ -d "$TV_SRC" ] || die2 "--test-vault is not a directory: $TV_SRC"
[ -z "$SETUP" ] || [ -f "$SETUP" ] || die2 "--setup is not a file: $SETUP"
[ -z "$SETUP" ] || SETUP="$(cd "$(dirname "$SETUP")" && pwd -P)/$(basename "$SETUP")"
[ "${#WATCHES[@]}" -ge 1 ] || die2 "give at least one --watch dir: with none, outside changes are not measured"
[ "${#PLUGIN_IDS[@]}" -ge 1 ] || die2 "give at least one --plugin: a run with none proves nothing about a plugin"
for id in ${PLUGIN_IDS[@]+"${PLUGIN_IDS[@]}"}; do
    if [ "$HOST" = cursor ]; then
        # The id names a dir under .cursor/plugins/local, so it must not be . or ..
        [[ "$id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*(@[A-Za-z0-9._-]+)?$ ]] || die2 "--plugin id must be <plugin> or <plugin>@<marketplace>: $id"
    elif [ "$HOST" = opencode ]; then
        # The id names a dir under .local/share/opencode-plugins.
        [[ "$id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die2 "--plugin id must be a bare name: $id"
    else
        [[ "$id" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$ ]] || die2 "--plugin id must be <plugin>@<marketplace>: $id"
    fi
done
for i in ${PLUGIN_DIRS[@]+"${!PLUGIN_DIRS[@]}"}; do
    [ -d "${PLUGIN_DIRS[$i]}" ] || die2 "--plugin dir is not a directory: ${PLUGIN_DIRS[$i]}"
done
# Each watch is measured at its resolved path, so a symlinked dir is searched, not skipped.
WATCH_REAL=()
for w in ${WATCHES[@]+"${WATCHES[@]}"}; do
    [ -d "$w" ] || die2 "--watch is not a directory: $w"
    WATCH_REAL+=("$(cd "$w" && pwd -P)")
done
for hf in ${HOME_FILES[@]+"${HOME_FILES[@]}"}; do
    rel="${hf%%=*}"; src="${hf#*=}"
    [ "$rel" != "$hf" ] && [ -n "$rel" ] && [ -n "$src" ] || die2 "--home-file must be <relpath>=<src>"
    case "$rel" in /*) die2 "--home-file relpath must be relative: $rel" ;; esac
    case "/$rel/" in */../*) die2 "--home-file relpath must not contain '..': $rel" ;; esac
    norm="$(printf '/%s/' "$rel" | tr -s /)"
    while [ "${norm#*/./}" != "$norm" ]; do norm="${norm%%/./*}/${norm#*/./}"; done
    norm="${norm#/}"; norm="${norm%/}"
    case "$norm" in .claude/.credentials.json|.codex/auth.json|.config/cursor/auth.json|.local/share/opencode/auth.json) die2 "--home-file cannot place the credentials; use --credentials" ;; esac
    [ -f "$src" ] || die2 "--home-file source is not a file: $src"
done

if [ -n "$EXEC" ]; then
    [ -f "$EXEC" ] && [ -x "$EXEC" ] || die2 "--exec is not an executable file: $EXEC"
    HOST_BIN="$(cd "$(dirname "$EXEC")" && pwd -P)/$(basename "$EXEC")"
else
    BIN_NAME="$HOST"; [ "$HOST" = cursor ] && BIN_NAME=cursor-agent
    HOST_BIN="$(command -v "$BIN_NAME")" || die2 "$BIN_NAME is not on PATH"
fi

# The secrets come from the original file, before anything runs, so a session that rewrites
# or deletes the copy cannot hide what it printed. They live only in this unexported
# variable: python reads the file on stdin and they reach finish() through a pipe.
# The same code reads the copy after the session (finish), in case the session rotated it.
# Short metadata (a scope, a tier) is not a secret unless it sits under a token/key/secret key,
# nor is a bare timestamp (Codex's last_refresh), which any log line of the same minute holds.
SECRETS_PY='
import json, re, sys
KEYED = re.compile("token|key|secret", re.I)
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
found = []
def collect(node, keyed=False):
    if isinstance(node, dict):
        for k, v in node.items():
            collect(v, keyed or bool(KEYED.search(str(k))))
    elif isinstance(node, list):
        for v in node:
            collect(v, keyed)
    elif isinstance(node, str) and ((len(node) >= 20 and not STAMP.match(node))
                                    or (keyed and len(node) >= 8)):
        found.append(node)
text = sys.stdin.buffer.read().decode("utf-8", "replace")
try:
    collect(json.loads(text))
except ValueError:
    whole = text.strip()
    if len(whole) >= 8:
        found.append(whole)
    found += [w for w in whole.split() if len(w) >= 16]
print(json.dumps(found))
'
SECRETS="$(python3 -c "$SECRETS_PY" < "$CREDS")" || die2 "could not read the --credentials file"

EVID_CREATED=""
[ -d "$EVID" ] || { mkdir -p "$EVID" || die2 "cannot create --evidence dir"; EVID_CREATED=1; }
EVID="$(cd "$EVID" && pwd -P)"
case "$EVID/" in "$REPO_ROOT"/*)
    [ -n "$EVID_CREATED" ] && rmdir "$EVID" 2>/dev/null
    die2 "--evidence must be outside this repo (transcripts carry machine paths)" ;;
esac

# ---- the throwaway root: everything from here on is removed on exit ----------------
ROOT=""; CRED_COPY=""; SPID=""
# session_pids <sid>: the live processes of session <sid>; never the harness's own session.
session_pids() {
    python3 -c '
import os, subprocess, sys
sid = int(sys.argv[1])
if sid <= 1 or sid == os.getsid(0):
    sys.exit(0)
out = subprocess.run(["ps", "-A", "-o", "pid=,stat="], capture_output=True, text=True).stdout
for line in out.splitlines():
    f = line.split()
    if len(f) < 2 or f[1].startswith("Z"):
        continue
    try:
        if os.getsid(int(f[0])) == sid:
            print(f[0])
    except (OSError, ValueError):
        pass
' "$1" 2>/dev/null
}
# kill_session <sid>: SIGKILL every process in session <sid>, then its process group, and
# wait until none is left (5 s at most).
kill_session() {
    local _ pids
    for _ in $(seq 1 50); do
        pids="$(session_pids "$1")"
        [ -n "$pids" ] && kill -KILL $pids 2>/dev/null
        kill -KILL -- -"$1" 2>/dev/null
        [ -z "$pids" ] && ! kill -0 -- -"$1" 2>/dev/null && return 0
        sleep 0.1
    done
}
cleanup() {
    local rc=$?
    if [ -n "$SPID" ]; then
        kill -TERM -- -"$SPID" 2>/dev/null || kill "$SPID" 2>/dev/null
        wait "$SPID" 2>/dev/null; kill_session "$SPID"
    fi
    if [ -n "$CRED_COPY" ] && [ -e "$CRED_COPY" ]; then
        if command -v shred >/dev/null 2>&1; then shred -u "$CRED_COPY" 2>/dev/null || rm -f "$CRED_COPY"
        else rm -f "$CRED_COPY"; fi
    fi
    if [ -n "$ROOT" ] && [ -d "$ROOT" ]; then chmod -R u+w "$ROOT" 2>/dev/null; rm -rf "$ROOT"; fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/clean-machine.XXXXXX")" || { echo "clean-machine-run: mktemp failed" >&2; exit 1; }
ROOT="$(cd "$ROOT" && pwd -P)"
CH="$ROOT/home"; TOY="$ROOT/toy"; TV=""
# The session's scratch stays in the run; /tmp and the temp dir the run root sits in are
# checked for names the run created at their top level (see the header).
SYS_TMP="$(dirname "$ROOT")"; SESS_TMP="$ROOT/tmp"; mkdir -p "$SESS_TMP"
TMP_DIRS=("${CLEAN_MACHINE_SYS_TMP:-/tmp}" "$SYS_TMP")
# list_tmp: the full path of each top-level name this user owns in the temp dirs, each dir
# resolved and listed once. Any error but a name vanishing mid-listing exits non-zero.
list_tmp() {
    python3 -c 'import os, sys
uid, seen = os.getuid(), set()
for d in sys.argv[1:]:
    r = os.path.realpath(d)
    if r in seen:
        continue
    seen.add(r)
    with os.scandir(r) as it:
        for e in it:
            try:
                if e.stat(follow_symlinks=False).st_uid == uid:
                    print(os.path.join(r, e.name))
            except FileNotFoundError:
                pass' "${TMP_DIRS[@]}" | LC_ALL=C sort
}
TMP_BEFORE="$ROOT/tmp-before.txt"; TMP_AFTER="$ROOT/tmp-after.txt"
LOG="$ROOT/host.log"; RAW="$ROOT/transcript.raw.jsonl"
MARKER="$ROOT/marker"; SMARKER="$ROOT/session-marker"; BEFORE="$ROOT/plugins-before.txt"
PLANS="$ROOT/plans.txt"; OUTSIDE="$ROOT/outside.txt"
: > "$LOG"; : > "$RAW"; : > "$PLANS"; : > "$OUTSIDE"; : > "$BEFORE"
SESSION_RC=""; HOST_VERSION=""; TOY_RC=""

# Where each host keeps its config, login file and plugin command.
HOSTENV=(); ADD_CMD=""
case "$HOST" in
    claude) CONF="$CH/.claude"; CRED_DIR="$CONF"; CRED_NAME=.credentials.json; ADD_CMD=install
            HOSTENV=(CLAUDE_CONFIG_DIR="$CONF") ;;
    codex)  CONF="$CH/.codex"; CRED_DIR="$CONF"; CRED_NAME=auth.json; ADD_CMD=add
            HOSTENV=(CODEX_HOME="$CONF") ;;
    cursor) CONF="$CH/.cursor"; CRED_DIR="$CH/.config/cursor"; CRED_NAME=auth.json ;;
    opencode) CONF="$CH/.config/opencode"; CRED_DIR="$CH/.local/share/opencode"; CRED_NAME=auth.json ;;
esac
cenv() { env -i PATH="$PATH" HOME="$CH" TMPDIR="$SESS_TMP" ${HOSTENV[@]+"${HOSTENV[@]}"} TERM=dumb "$@"; }

# finish <error-or-empty>: label the evidence, write asserts.json, decide the exit.
finish() {
    local verdict copy_secrets
    copy_secrets="$( { python3 -c "$SECRETS_PY" < "$CRED_COPY"; } 2>/dev/null )" || copy_secrets="[]"
    verdict="$(CMR_FIRST_ID="${PLUGIN_IDS[0]:-}" python3 - "$EVID" "$RAW" "$LOG" "$PLANS" "$OUTSIDE" "$TOY" "$CH" "$TV" \
        "$EXPECT" "${SESSION_RC:-}" "$HOST_VERSION" "$1" "$ROOT" "$BEFORE" "${TOY_RC:-}" "$HOST" "$CONF" \
        ${PLUGIN_DIRS[@]+"${PLUGIN_DIRS[@]}"} -- ${WATCHES[@]+"${WATCHES[@]}"} \
        3< <(printf '%s\n%s\n' "$SECRETS" "$copy_secrets") <<'PY'
import json, os, sys
(evid, raw, log, plans, outside, toy, home, tv, expect, rc, version, error, root, before,
 toy_rc, host, conf), rest = sys.argv[1:18], sys.argv[18:]
cut = rest.index("--")
plugins, watches = rest[:cut], rest[cut + 1:]
first_id = os.environ.get("CMR_FIRST_ID", "")
os.umask(0o077)

# The secrets of the original credentials file, read before the session, and those the
# copy holds now (in case the session rotated it) arrive on fd 3, one JSON list per line.
secrets = []
with os.fdopen(3, encoding="utf-8") as fh:
    for l in fh:
        try:
            secrets += [s for s in json.loads(l) if isinstance(s, str)]
        except ValueError:
            pass
# A 16+ character piece of a secret (a prefix, say) is as good as the secret: every
# 16-character window of each long secret is looked for, and each run of matches redacted.
GRAM = 16
grams = {sec[i:i + GRAM] for sec in secrets if len(sec) >= GRAM for i in range(len(sec) - GRAM + 1)}
short = sorted({sec for sec in secrets if len(sec) < GRAM}, key=len, reverse=True)
redactions = 0
def redact(text):
    global redactions
    spans = []
    for i in range(len(text) - GRAM + 1 if grams else 0):
        if text[i:i + GRAM] in grams:
            if spans and i <= spans[-1][1]:
                spans[-1][1] = i + GRAM
            else:
                spans.append([i, i + GRAM])
    if spans:
        redactions += len(spans)
        parts, last = [], 0
        for a, b in spans:
            parts += [text[last:a], "<redacted>"]
            last = b
        text = "".join(parts) + text[last:]
    for sec in short:
        if sec in text:
            redactions += text.count(sec)
            text = text.replace(sec, "<redacted>")
    return text

labels = {root: "<run>", home: "<home>", toy: "<toy>"}
if tv:
    labels[tv] = "<test-vault>"
for kind, dirs in (("plugin", plugins), ("watch", watches)):
    for n, d in enumerate(dirs, 1):
        for form in {d.rstrip("/") or "/", os.path.realpath(d)}:
            labels.setdefault(form, f"<{kind}:{n}>")
# The installed copy of each plugin marketplace carries the same label as its source.
for n in range(1, len(plugins) + 1):
    labels[os.path.join(root, f"plugin-{n}")] = f"<plugin:{n}>"
order = sorted(labels, key=len, reverse=True)

def label(text):
    for p in order:
        text = text.replace(p, labels[p])
    return text

def lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [l.rstrip("\n") for l in fh if l.strip()]

def under(path, base):
    return path == base or path.startswith(base.rstrip("/") + "/")

# A Skill call counts only when its tool_result (matched by tool_use_id) came back and is
# not an error: is_error set, or a text that opens with "Unknown skill", "Error" or the
# host's <tool_use_error> tag.
# On Codex the harness copies the rollout's skill injections into the raw transcript as
# codex_skill lines; one counts only when its path is the named skill's own SKILL.md under
# the HOME's plugin cache.
# On Cursor a skill counts when a readToolCall of its own SKILL.md (<id>/skills/<skill>/
# SKILL.md under the HOME's .cursor/plugins/local) came back with a success result.
# On OpenCode a skill counts when a skill tool call completed and its metadata.dir is the
# named skill's own folder (<id>/skills/<skill>, holding SKILL.md) under the HOME's
# .local/share/opencode-plugins: a co-visible copy elsewhere is not the plugin's.
uses, results, injected, reads, served = [], {}, [], [], []
cache = os.path.join(conf, "plugins", "cache") + "/"
local = os.path.join(home, ".cursor", "plugins", "local") + "/"
ocroot = os.path.join(home, ".local", "share", "opencode-plugins") + "/"
def opencode_skill(st):
    if not isinstance(st, dict) or st.get("status") != "completed":
        return
    name = (st.get("input") or {}).get("name")
    d = (st.get("metadata") or {}).get("dir")
    if not (isinstance(name, str) and isinstance(d, str)):
        return
    p = os.path.normpath(d)
    parts = p[len(ocroot):].split("/") if p.startswith(ocroot) else []
    if len(parts) == 3 and parts[1] == "skills" and parts[2] == name \
            and os.path.isfile(os.path.join(p, "SKILL.md")):
        served.append(parts[0] + ":" + name)
def cursor_read(rtc):
    args, res = rtc.get("args"), rtc.get("result")
    if not (isinstance(args, dict) and isinstance(args.get("path"), str)
            and isinstance(res, dict) and "success" in res):
        return
    p = os.path.normpath(args["path"])
    parts = p[len(local):].split("/") if p.startswith(local) else []
    if len(parts) == 4 and parts[1] == "skills" and parts[3] == "SKILL.md":
        reads.append(parts[0].split("@", 1)[0] + ":" + parts[2])
def walk(node):
    if isinstance(node, dict):
        if isinstance(node.get("readToolCall"), dict):
            cursor_read(node["readToolCall"])
        if node.get("type") == "tool" and node.get("tool") == "skill":
            opencode_skill(node.get("state"))
        if node.get("type") == "codex_skill" and isinstance(node.get("name"), str) \
                and isinstance(node.get("path"), str) \
                and os.path.normpath(node["path"]).startswith(cache) \
                and os.path.basename(node["path"]) == "SKILL.md" \
                and os.path.normpath(node["path"])[len(cache):].split("/")[1:2] \
                    == node["name"].split(":", 1)[:1] \
                and os.path.basename(os.path.dirname(os.path.normpath(node["path"]))) \
                    == node["name"].split(":", 1)[-1]:
            injected.append(node["name"])
        if node.get("type") == "tool_use" and node.get("name") == "Skill":
            s = (node.get("input") or {}).get("skill")
            if isinstance(s, str):
                uses.append((node.get("id"), s))
        elif node.get("type") == "tool_result" and isinstance(node.get("tool_use_id"), str):
            results[node["tool_use_id"]] = node
        for v in node.values():
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)
def result_ok(res):
    if not isinstance(res, dict) or res.get("is_error"):
        return False
    body = res.get("content")
    if isinstance(body, list):
        body = "".join(b["text"] for b in body if isinstance(b, dict) and isinstance(b.get("text"), str))
    text = body.lstrip() if isinstance(body, str) else ""
    return not text.startswith(("Unknown skill", "Error", "<tool_use_error>"))

with open(os.path.join(evid, "transcript.jsonl"), "w", encoding="utf-8") as out:
    for l in lines(raw):
        try:
            walk(json.loads(l))
        except ValueError:
            pass
        out.write(label(redact(l)) + "\n")
with open(os.path.join(evid, "host.log"), "w", encoding="utf-8") as out:
    out.write("".join(label(redact(l)) + "\n" for l in lines(log)))
skills = []
for uid, s in uses:
    if host == "claude" and isinstance(uid, str) and result_ok(results.get(uid)) and s not in skills:
        skills.append(s)
for s in injected:
    if host == "codex" and s not in skills:
        skills.append(s)
for s in reads:
    if host == "cursor" and s not in skills:
        skills.append(s)
for s in served:
    if host == "opencode" and s not in skills:
        skills.append(s)

# Files the plugin install put under the HOME's plugin dir before the session are not plans.
plan_paths = sorted(set(lines(plans)) - set(lines(before)))

def title(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for l in fh:
                if l.startswith("# "):
                    return l.strip().lower()
    except OSError:
        pass
    return ""

# A design is a candidate, but a run that wrote no plan has not planned.
has_plan = any(title(p).startswith(("# light plan:", "# project plan:", "# master plan:"))
               for p in plan_paths)
if not plan_paths or not has_plan:
    where = "none"
elif all(under(p, os.path.join(toy, "docs")) for p in plan_paths):
    where = "docs"
elif tv and all(under(p, tv) for p in plan_paths):
    where = "test-vault"
else:
    where = "elsewhere"

asserts = {
    "records_under": where,
    "plan_files": [label(redact(p)) for p in plan_paths],
    "outside_changes": [label(redact(p)) for p in sorted(set(lines(outside)))],
    "skills_seen": skills,
    "host_version": label(redact(version)),
    "exit": int(rc) if rc.lstrip("-").isdigit() else None,
    "toy_test_exit": int(toy_rc) if toy_rc.lstrip("-").isdigit() else None,
}
want = ["planning:brainstorming", "planning:planning-projects", "planning:executing-plans"]
if host == "opencode":
    # OpenCode has no plugin namespace: the three come from the first --plugin's copy.
    want = [first_id + ":" + w.split(":", 1)[1] for w in want]
seen = iter(skills)
skills_ok = all(w in seen for w in want) if host == "claude" else set(want) <= set(skills)
error = label(redact(error))
if not plugins:
    error = (error + "; " if error else "") + "no plugin was installed"
if redactions:
    error = (error + "; " if error else "") + f"the session exposed the credentials ({redactions} redacted)"
if error:
    asserts["error"] = error
with open(os.path.join(evid, "asserts.json"), "w", encoding="utf-8") as out:
    json.dump(asserts, out, indent=2)
    out.write("\n")
ok = (not error and bool(plugins) and skills_ok and where == expect
      and asserts["toy_test_exit"] == 0 and not asserts["outside_changes"] and asserts["exit"] == 0)
print("PASS" if ok else "FAIL", where, len(asserts["outside_changes"]), asserts["exit"],
      f"toy_test={asserts['toy_test_exit']}", "skills=" + (("in-order" if host == "claude" else "present") if skills_ok else "missing"),
      f"(expect {expect}{'; ' + error if error else ''})")
PY
)" || { echo "clean-machine-run: could not write the evidence" >&2; exit 1; }
    echo "clean-machine-run: $verdict"
    case "$verdict" in PASS*) exit 0 ;; *) exit 1 ;; esac
}

# 1-2. The throwaway HOME: the credentials (mode 600), the home files, the test vault.
mkdir -p "$CONF" "$CRED_DIR" && chmod 700 "$CH" "$CONF" "$CRED_DIR"
CRED_COPY="$CRED_DIR/$CRED_NAME"
( umask 077; cp "$CREDS" "$CRED_COPY" ) 2>/dev/null && chmod 600 "$CRED_COPY" \
    || finish "copying the credentials failed"
for hf in ${HOME_FILES[@]+"${HOME_FILES[@]}"}; do
    rel="$(printf '%s' "${hf%%=*}" | tr -s /)"; rel="${rel#./}"; src="${hf#*=}"
    mkdir -p "$(dirname "$CH/$rel")" && cp "$src" "$CH/$rel" || finish "placing --home-file $rel failed"
done
if [ -n "$TV_SRC" ]; then
    TV="$CH/test-vault"
    cp -R "$TV_SRC" "$TV" || finish "copying --test-vault failed"
fi

# The watch check starts here, so a write into a --watch dir by the host binary, the
# plugin install or --setup is caught as well as one by the session.
list_tmp > "$TMP_BEFORE" || finish "listing the temp dirs failed"
touch "$MARKER"
HOST_VERSION="$(cenv "$HOST_BIN" --version 2>/dev/null | head -n 1)"

# 3. Plugins, each from a copy of its local marketplace (see the header).
for i in ${PLUGIN_DIRS[@]+"${!PLUGIN_DIRS[@]}"}; do
    src="$(cd "${PLUGIN_DIRS[$i]}" && pwd -P)"
    d="$ROOT/plugin-$((i+1))"
    mkdir -p "$d" || finish "copying <plugin:$((i+1))> failed"
    if [ "$(git -C "$src" rev-parse --show-toplevel 2>/dev/null)" = "$src" ]; then
        dirty=""; [ -n "$(git --no-optional-locks -C "$src" status --porcelain 2>/dev/null)" ] && dirty=", working tree dirty"
        echo "== plugin copy <plugin:$((i+1))>: committed tree (git archive HEAD $(git -C "$src" rev-parse --short=12 HEAD 2>/dev/null)$dirty)" >> "$LOG"
        { git -C "$src" archive --format=tar -o "$ROOT/plugin-$((i+1)).tar" HEAD \
          && tar -xf "$ROOT/plugin-$((i+1)).tar" -C "$d"; } >> "$LOG" 2>&1 \
            || finish "copying <plugin:$((i+1))>'s committed tree failed"
    else
        echo "== plugin copy <plugin:$((i+1))>: directory as it is (cp -R)" >> "$LOG"
        cp -R "$src/." "$d" >> "$LOG" 2>&1 || finish "copying <plugin:$((i+1))> failed"
    fi
    if [ "$HOST" = cursor ]; then
        # Cursor has no plugin command: a plugin is a dir under ~/.cursor/plugins/local.
        t="$CONF/plugins/local/${PLUGIN_IDS[$i]}"
        { echo "== plugin install <plugin:$((i+1))> -> <home>/.cursor/plugins/local/${PLUGIN_IDS[$i]}"
          [ ! -e "$t" ] && mkdir -p "$t" && cp -R "$d/." "$t/" 2>&1; } >> "$LOG" \
            || finish "plugin install ${PLUGIN_IDS[$i]} failed"
        continue
    fi
    if [ "$HOST" = opencode ]; then
        # The recorded install shape: copy, then name it in opencode.json (see the header).
        t="$CH/.local/share/opencode-plugins/${PLUGIN_IDS[$i]}"
        { echo "== plugin install <plugin:$((i+1))> -> <home>/.local/share/opencode-plugins/${PLUGIN_IDS[$i]}"
          [ ! -e "$t" ] && mkdir -p "$t" && cp -R "$d/." "$t/" 2>&1 \
          && python3 - "$t" "$CONF/opencode.json" 2>&1 <<'PY'
import json, os, sys
plugin, config = sys.argv[1:]
try:
    with open(config) as fh:
        conf = json.load(fh)
except FileNotFoundError:
    conf = {"$schema": "https://opencode.ai/config.json"}
pj = os.path.join(plugin, "package.json")
if os.path.isfile(pj):
    main = json.load(open(pj)).get("main")
    if not isinstance(main, str) or not os.path.isfile(os.path.join(plugin, main)):
        sys.exit("the package names no main module that exists")
    conf.setdefault("plugin", []).append(os.path.normpath(os.path.join(plugin, main)))
elif os.path.isdir(os.path.join(plugin, "skills")):
    conf.setdefault("skills", {}).setdefault("paths", []).append(os.path.join(plugin, "skills"))
else:
    sys.exit("neither a package (package.json) nor a plugin dir (skills/)")
with open(config, "w") as fh:
    json.dump(conf, fh, indent=2)
    fh.write("\n")
PY
        } >> "$LOG" || finish "plugin install ${PLUGIN_IDS[$i]} failed"
        continue
    fi
    { echo "== plugin marketplace add <plugin:$((i+1))>"
      cenv "$HOST_BIN" plugin marketplace add "$d" 2>&1; } >> "$LOG" \
        || finish "plugin marketplace add for <plugin:$((i+1))> failed"
    { echo "== plugin install ${PLUGIN_IDS[$i]}"
      cenv "$HOST_BIN" plugin "$ADD_CMD" "${PLUGIN_IDS[$i]}" 2>&1; } >> "$LOG" \
        || finish "plugin install ${PLUGIN_IDS[$i]} failed"
done

# Setup runs after the plugins, in the clean environment.
if [ -n "$SETUP" ]; then
    set -- CLEAN_HOME="$CH" CLEAN_HOST="$HOST"
    [ -n "$TV" ] && set -- "$@" CLEAN_TEST_VAULT="$TV"
    if [ -x "$SETUP" ]; then set -- "$@" "$SETUP"; else set -- "$@" bash "$SETUP"; fi
    { echo "== setup"; ( cd "$CH" && cenv "$@" 2>&1 ); } >> "$LOG" || finish "--setup failed"
fi

# 4. The toy repo: one module, one failing test, one commit. Its identity is repo-local,
# so the session can commit with no global git config in the throwaway HOME.
mkdir -p "$TOY/tests"
printf 'def add(a, b):\n    return a - b\n' > "$TOY/calc.py"
# The test's text is kept here too, so an edited test is caught instead of run.
TOY_TEST_SRC="$(cat <<'EOF'
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from calc import add

assert add(2, 3) == 5, f"add(2, 3) returned {add(2, 3)}, expected 5"
print("ok")
EOF
)"
printf '%s\n' "$TOY_TEST_SRC" > "$TOY/tests/test_calc.py"
printf '__pycache__/\n' > "$TOY/.gitignore"
( cd "$TOY" && cenv git init -q --template= . && cenv git checkout -q -b main 2>/dev/null
  cenv git config user.name "Clean Machine" && cenv git config user.email clean-machine@example.com \
  && cenv git add -A && cenv git commit -q -m "toy: add() and its failing test" ) >> "$LOG" 2>&1 \
    || finish "creating the toy repo failed"

# 5. The session. The prompt never says where records go: that is what is under test.
# Codex loads a plugin skill named in the prompt as $<plugin>:<skill>; Claude by its Skill tool;
# Cursor and OpenCode by the skill's plain name.
P='planning:'; [ "$HOST" = codex ] && P='$planning:'
case "$HOST" in cursor|opencode) P='' ;; esac
PRE='This is an unattended test run. Nobody can answer questions, so use the answers given here and do not ask any.'
S1='1. Use the '"$P"'brainstorming skill to design a fix for the failing test in this repository (python3 tests/test_calc.py). Answers to its questions: the goal is that add(a, b) returns a + b; the scope is calc.py only; no new dependencies; success means python3 tests/test_calc.py exits 0; that test is the bug this fix is for, so it fails until the fix lands and its failure is the starting RED, not a broken baseline. The design is approved as written.'
S2='2. Use the '"$P"'planning-projects skill to write a Light plan for that design. Save it wherever the skill saves plans by default.'
S3='3. Use the '"$P"'executing-plans skill to execute that plan through its gate, committing with git as the skill directs. Stop when the gate is green or has failed.'
PROMPT="$PRE
$S1
$S2
$S3"
if [ "$HOST" = cursor ]; then
    # --force: headless -p otherwise waits for approval on each shell and write call.
    set -- -p --trust --force --output-format stream-json
    [ -n "$MODEL" ] && set -- "$@" --model "$MODEL"
    set -- "$@" "$PROMPT"
elif [ "$HOST" = opencode ]; then
    set --   # the three prompts are built per step below
elif [ "$HOST" = codex ]; then
    set -- exec --json -s workspace-write -C "$TOY" --add-dir "$TOY/.git"
    [ -n "$MODEL" ] && set -- "$@" -m "$MODEL"
    [ -n "$TV" ] && set -- "$@" --add-dir "$TV"
    set -- "$@" "$PROMPT"
else
    set -- -p "$PROMPT" --output-format stream-json --verbose --permission-mode acceptEdits
    [ -n "$MODEL" ] && set -- "$@" --model "$MODEL"
    [ -n "$TV" ] && set -- "$@" --add-dir "$TV"
    set -- "$@" --allowedTools Read Edit Write Glob Grep Skill Agent TodoWrite \
        "Bash(git *)" "Bash(python3 *)" "Bash(bash *)"
fi

# What the plugin dirs held before the session: those files are the install's, not plans.
find "$CONF/plugins" "$CH/.local/share/opencode-plugins" "$ROOT"/plugin-* -type f -print 2>/dev/null > "$BEFORE"
touch "$SMARKER"
{ echo "== session"; } >> "$LOG"
# The session leads its own session and process group (setsid, else python's os.setsid),
# so every process in it, background children too, can be killed when it ends.
if command -v setsid >/dev/null 2>&1; then NEWGRP=(setsid)
else NEWGRP=(python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])'); fi
# In the background, so a trapped signal ends the session at once instead of after it.
run_session() {
    ( cd "$TOY" && exec "${NEWGRP[@]}" env -i PATH="$PATH" HOME="$CH" TMPDIR="$SESS_TMP" ${HOSTENV[@]+"${HOSTENV[@]}"} \
          TERM=dumb "$HOST_BIN" "$@" ) >> "$RAW" 2>> "$LOG" < /dev/null &
    SPID=$!
    wait "$SPID"; SESSION_RC=$?
    kill_session "$SPID"
    SPID=""
}
if [ "$HOST" = opencode ]; then
    # One prompt per step, each naming its skill; a failed step ends the flow.
    for step in "$S1" "$S2" "$S3"; do
        set -- run -m "$MODEL" --format json
        [ "$step" = "$S1" ] || set -- "$@" --continue
        echo "== session step ${step%%.*}" >> "$LOG"
        run_session "$@" "$PRE
$step"
        [ "$SESSION_RC" -eq 0 ] || break
    done
else
    run_session "$@"
fi
# Codex: the skills the rollout shows injected, one codex_skill line each (see the header).
if [ "$HOST" = codex ]; then
    python3 - "$CONF/sessions" >> "$RAW" 2>> "$LOG" <<'PY'
import glob, json, os, re, sys
TAG = re.compile(r"\A<skill>\n<name>([^<\n]+)</name>\n<path>([^<\n]+)</path>")
for path in sorted(glob.glob(os.path.join(sys.argv[1], "**", "rollout-*.jsonl"), recursive=True)):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            p = item.get("payload") if isinstance(item, dict) else None
            if not (isinstance(p, dict) and p.get("type") == "message" and p.get("role") == "user"):
                continue
            for part in p.get("content") or []:
                m = TAG.match(part.get("text", "")) if isinstance(part, dict) else None
                if m:
                    print(json.dumps({"type": "codex_skill", "name": m.group(1), "path": m.group(2)}))
PY
fi

# 6. The toy's own test, unedited, in the same clean env. It runs before the watch check,
# so a write it makes outside is caught too.
TOY_ERR=""
if [ "$(cat "$TOY/tests/test_calc.py" 2>/dev/null)" = "$TOY_TEST_SRC" ]; then
    { echo "== toy test"; ( cd "$TOY" && cenv python3 -I tests/test_calc.py 2>&1 ); } >> "$LOG"
    TOY_RC=$?
else
    TOY_ERR="the session edited or removed tests/test_calc.py"
fi

# 7. Where the plan landed (new since the session began), and what changed in the
# --watch dirs since before the plugin install. mtime or ctime: a backdated write still
# moves ctime.
# The plugin's install copies are searched too: a plan written there is a plan.
for base in "$TOY" "$CH" "$ROOT"/plugin-* ${WATCH_REAL[@]+"${WATCH_REAL[@]}"}; do
    [ -d "$base" ] || continue
    find "$base" \( -path "$TOY/.git" -o -path "$EVID" -o -path "$ROOT" \) -prune -o \
         -type f -name '*.md' \( -newer "$SMARKER" -o -cnewer "$SMARKER" \) -print 2>/dev/null
done | while IFS= read -r f; do
    # A UTF-8 byte-order mark before the title does not hide it.
    LC_ALL=C grep -a -m1 -E $'^(\xef\xbb\xbf)?# ' "$f" 2>/dev/null | LC_ALL=C sed $'s/^\xef\xbb\xbf//' \
        | grep -qiE '^# (Design|Light Plan|Project Plan|Master Plan):' && printf '%s\n' "$f"
done >> "$PLANS"
for w in ${WATCH_REAL[@]+"${WATCH_REAL[@]}"}; do
    find "$w" \( -path "$ROOT" -o -path "$EVID" \) -prune -o \
         \( -newer "$MARKER" -o -cnewer "$MARKER" \) -print 2>/dev/null >> "$OUTSIDE"
done
# Names created at the temp dirs' top level during the run, less the run root and the
# evidence path's own top folder in each.
list_tmp > "$TMP_AFTER" || finish "listing the temp dirs failed"
EV_TOPS=()
for d in "${TMP_DIRS[@]}"; do
    d="$(cd "$d" 2>/dev/null && pwd -P)" || continue
    case "$EVID/" in "$d"/*) t="${EVID#"$d"/}"; EV_TOPS+=("$d/${t%%/*}") ;; esac
done
LC_ALL=C comm -13 "$TMP_BEFORE" "$TMP_AFTER" | while IFS= read -r n; do
    [ "$n" = "$ROOT" ] && continue
    for t in ${EV_TOPS[@]+"${EV_TOPS[@]}"}; do [ "$n" = "$t" ] && continue 2; done
    printf '%s\n' "$n"
done >> "$OUTSIDE"

finish "$TOY_ERR"
