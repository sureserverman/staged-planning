#!/usr/bin/env python3
"""statusline-install — manage the ONE `statusLine` key in the user's global
~/.claude/settings.json, pointing it at the sibling statusline-chain.sh.

Why this script exists: a Claude Code plugin's settings.json only supports
`agent` and `subagentStatusLine` as contribution points — `statusLine` is not
one of them. So exactly one line in the user's *global* settings.json is
irreducible, and this script is what writes/repairs/removes that line so the
user never has to hand-edit JSON.

CLI:
    statusline-install.py               install/repair the pointer (default)
    statusline-install.py --install     same, explicit
    statusline-install.py --status      report what is currently wired
    statusline-install.py --remove      remove the statusLine key
    statusline-install.py --force       (with --install) overwrite a
                                         statusLine this script did not install

Settings path is ~/.claude/settings.json, resolved via Path.home() (which
honors the HOME environment variable) so tests can point it at a temp dir.
"""
import argparse
import hashlib
import json
import re
import os
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Self-locating target: never hard-code a checkout path. The chain script is
# always the sibling of this file, wherever the plugin happens to be installed.
TARGET_PATH = Path(__file__).resolve().parent / "statusline-chain.sh"
TARGET = str(TARGET_PATH)

# A plugin installs to a VERSION-PINNED directory
# (~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/...), and that path
# changes on every version bump. `statusLine` is not a plugin contribution point,
# so `/reload-plugins` — which re-points hooks, MCP and LSP servers — cannot
# re-point it, and the old directory is cleaned up after roughly two weeks. A
# literal absolute path baked in at install time therefore expires silently,
# taking the user's *base* statusline down with it (the chain script is what
# invokes the base, so a missing chain script loses both lines, not just the bar).
#
# So when this script is running from inside a version-pinned install, the
# command written to settings.json resolves the newest installed version at
# render time instead of freezing today's. Versions are ordered by a numeric
# field sort (0.9.0 sorts below 0.37.0, which a lexical sort gets backwards). The
# `[ -n "$p" ]` guard
# means a cache with no match prints nothing rather than a "command not found"
# line, preserving the never-noisy contract the chain script itself keeps.
VERSION_PINNED_RE = re.compile(
    r"^(?P<prefix>.*/plugins/cache/[^/]+/[^/]+)/(?P<version>[^/]+)/(?P<suffix>.*)$"
)


BASH_INVOCATION_RE = re.compile(r'^bash\s+"?([^"]+)"?\s*$')

# The `PLAN_STATUSLINE_BASE=<path> ` prefix chain_through() writes, so a later
# repair can recognise and carry it rather than silently dropping it. Parsed
# with shlex so a quoted path containing spaces round-trips.
BASE_PREFIX_RE = re.compile(r"^PLAN_STATUSLINE_BASE=(?P<base>('[^']*'|\"[^\"]*\"|\S+))\s+")

# The chain script's own name, matched as a PATH COMPONENT rather than as a
# substring anywhere in the command (see is_ours).
CHAIN_NAME = "statusline-chain.sh"
CHAIN_PATH_RE = re.compile(r"[^\s\"';|&]*" + re.escape(CHAIN_NAME))


def split_base_prefix(command):
    """(base_path_or_None, remainder) for a command chain_through() may have written.

    A repair install must carry a preserved base forward instead of rebuilding
    the command from scratch: a plain `merged.update(desired)` would overwrite
    `command` with the unprefixed form, so a --force install that carefully
    preserved the user's statusline would be undone by the very next plain
    --install. And a --status that compared against the unprefixed command
    would always report a preserved entry as "differs — run `--install` to
    repair", steering the user into exactly the call that destroys it.
    """
    m = BASE_PREFIX_RE.match(str(command or ""))
    if not m:
        return None, str(command or "")
    base = m.group("base")
    if base[:1] in ("'", '"') and base[-1:] == base[:1]:
        base = base[1:-1]
    return base, str(command)[m.end():]


def base_emits_own_bar(base_path):
    """Whether a candidate base statusline already renders a plan-progress bar.

    A hand-written wrapper statusline can be a `bash <script>` invocation that
    itself runs plan-progress.py. Chaining it in as the base would produce the
    bar TWICE — once from the wrapper, once from the chain script — and nothing
    at install or render time would say so.
    """
    try:
        return "plan-progress.py" in Path(base_path).read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        return False


def chain_through(displaced):
    """A `PLAN_STATUSLINE_BASE=<path> ` prefix that preserves a displaced statusline.

    Without it --force discards whatever it replaces. The chain script only ever
    runs $HOME/.claude/statusline.sh as its base, and settings.json has no way
    to supply PLAN_STATUSLINE_BASE — so a user whose statusline was a script at
    any other path would lose it in every project, and get a blank line whenever
    no plan is executing. Where the displaced entry is a plain `bash <script>`, we
    can keep it as the base instead of destroying it.

    Returns (prefix, reason). `prefix` is "" when the displaced command is not a
    shape we can safely chain — better to hand the user their old command back
    in a message than to guess wrong — and `reason` says which case applied so
    the caller can explain it:

        "ok"          chained
        "not-a-dict"  the entry is a bare string, not a {type, command} object
        "unchainable" node/deno/bun, a pipeline, anything with its own arguments
        "missing"     the script named no longer exists on disk
        "doubles-bar" the script already prints a plan-progress bar of its own
    """
    if not isinstance(displaced, dict):
        return "", "not-a-dict"
    m = BASH_INVOCATION_RE.match(str(displaced.get("command", "")).strip())
    if not m:
        return "", "unchainable"
    base = m.group(1)
    if not os.path.isfile(base):
        return "", "missing"
    if base_emits_own_bar(base):
        return "", "doubles-bar"
    return f"PLAN_STATUSLINE_BASE={shlex.quote(base)} ", "ok"


def resolve_command(target=TARGET):
    """The shell command to write into settings.json, plus how it was derived.

    Returns (command, mode) where mode is "versioned" or "literal". A literal
    path is correct for a dev checkout — it is stable there — and is the honest
    fallback anywhere the version-pinned layout is not recognised.

    Every literal path component is shell-quoted and only the version `*` is
    left to expand. Interpolated bare, the glob would word-split on a HOME
    containing a space, `ls` would match nothing, and the guard below would then
    exec nothing — losing the user's BASE statusline too, since the chain script is
    what invokes it, with empty stdout and empty stderr to explain it. That is
    the loudest possible failure rendered completely invisible.

    Version selection sorts the version component numerically field by field
    rather than with `sort -V`, which is a GNU extension absent from the BSD
    sort on macOS — a platform this repo explicitly supports. A missing `-V`
    would fail the same silent way.
    """
    m = VERSION_PINNED_RE.match(target)
    if not m:
        # Double quotes already handle a space here; only the glob below needs
        # more. Escape properly in the one case double-quoting cannot survive,
        # a `"` in the path itself.
        if '"' in target:
            return f"bash {shlex.quote(target)}", "literal"
        return f'bash "{target}"', "literal"
    script = (
        "d=%s; s=%s; "
        'p=$(for f in "$d"/*/"$s"; do '
        '[ -f "$f" ] || continue; '
        'v=${f#"$d"/}; v=${v%%%%/*}; '
        'printf "%%s\t%%s\n" "$v" "$f"; '
        "done | sort -t. -k1,1n -k2,2n -k3,3n | tail -1 | cut -f2-); "
        '[ -n "$p" ] && exec bash "$p"'
    ) % (shlex.quote(m.group("prefix")), shlex.quote(m.group("suffix")))
    return f"sh -c {shlex.quote(script)}", "versioned"


def get_settings_path():
    path = Path.home() / ".claude" / "settings.json"
    # Resolve through a symlinked settings.json. os.replace() unlinks the
    # destination symlink and swaps a regular file into its place, which would
    # silently orphan a dotfile-manager's real file (chezmoi/stow keep the
    # managed copy elsewhere and symlink it here) — the user's edits would land
    # somewhere nothing syncs. Following the link writes where they expect.
    if path.is_symlink():
        try:
            return path.resolve()
        except OSError:
            return path
    return path


def entry_mode(command):
    """"versioned" or "literal" for an already-written entry, or None.

    Judged from the entry's own text so a reader of --status learns about the
    entry in their settings.json rather than about whichever copy of this script
    they happened to invoke.
    """
    if not isinstance(command, str) or not command:
        return None
    stripped = command.strip()
    # split_base_prefix drops any PLAN_STATUSLINE_BASE=... the user chained in.
    _base, rest = split_base_prefix(stripped)
    rest = (rest or stripped).strip()
    if rest.startswith("sh -c "):
        return "versioned"
    if rest.startswith("bash "):
        return "literal"
    return None


def desired_entry():
    return {"type": "command", "command": resolve_command()[0]}


def is_ours(entry):
    """Whether a statusLine entry is one this installer wrote.

    Structural, never string equality against today's absolute path: the path
    changes when the plugin moves (dev checkout to marketplace, one version to
    the next), and that relocation is exactly what this tooling exists to
    survive. Shared by --status and --install so the two cannot disagree about
    the same file.

    Matched as a whole PATH COMPONENT, not as a substring of the command. A raw
    `"statusline-chain.sh" in command` test would also claim ownership of a
    third-party entry that merely mentions the name — `bash
    ~/bin/my-statusline-chain.sh`, a comment, an argument, a path to an old
    backup — and a bare --install would then "repair" it, bypassing the very
    --force gate README.md promises for a statusLine this tool did not write.
    """
    if not isinstance(entry, dict):
        return False
    command = str(entry.get("command", ""))
    return any(
        os.path.basename(hit) == CHAIN_NAME for hit in CHAIN_PATH_RE.findall(command)
    )


# How many timestamped backups of settings.json to keep. Each is a full copy of a
# file that can hold `env` API keys, so the pile is bounded rather than endless;
# ten is enough to walk back through a bad session and small enough to stay tidy.
BACKUP_KEEP = 10

# What backup() writes: `<settings name>.bak.` + datetime's %Y%m%dT%H%M%S%f, which
# is exactly 20 digits with a `T` at index 8. Anchored so pruning can only ever
# remove a file this script created.
BACKUP_NAME_RE = re.compile(r"\.bak\.\d{8}T\d{12}$")


def detect_indent(text):
    """The original file's indent string, so a rewrite preserves its formatting.

    Re-serialising every write at a fixed `indent=2` would make `--remove`
    fail to restore a 4-space or tab-indented settings.json byte-for-byte: the
    content would round-trip, the bytes would not. Returns None for a compact
    (single-line) file, which json.dump treats as no pretty-printing.
    """
    m = re.search(r"^([ \t]+)\"", text, re.M)
    if not m:
        return None
    indent = m.group(1)
    return indent if "\t" in indent else len(indent)


def warn(msg):
    """A non-fatal notice on stderr. stdout stays parseable for --status."""
    print(f"statusline-install: {msg}", file=sys.stderr)


def die(msg):
    print(f"statusline-install: {msg}", file=sys.stderr)
    sys.exit(1)


def stamp_of(path):
    """A content digest identifying the file's exact bytes, or None if absent.

    (mtime_ns, size) has a blind spot: macOS HFS+ carries ONE-SECOND mtime
    granularity, and macOS is an explicitly supported platform here. A
    same-second edit that also keeps the byte length — swapping a `"dark"` theme
    for `"lite"`, say, which is the same length — is invisible to it. That is precisely the "Claude Code
    wrote something in the window" case this guard exists to catch, so a guard that
    misses it is the guard not working on one of its two target platforms.

    Hashing costs almost nothing: settings.json is a few kilobytes, so this is
    microseconds, once per install, on a path that already reads the whole file
    anyway.

    Not a security boundary — it answers "did these bytes change", not "who
    changed them", and a deliberate forgery is out of scope.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_settings_for_write(path):
    """Load settings.json for a write operation. Never overwrites malformed
    or non-object JSON — dies with a clear message instead.

    Returns (data, existed, stamp) — stamp identifies the exact bytes read, so
    write_settings can refuse if another process changes them in the window.
    """
    if not path.exists():
        return {}, False, None
    try:
        # Explicit encoding: read_text() defaults to the locale encoding, so
        # under LC_ALL=C a settings.json holding any non-ASCII byte would die
        # with an unactionable "'ascii' codec can't decode". write_settings()
        # names its encoding too.
        #
        # utf-8-sig, not utf-8: an editor that writes a BOM (Notepad, some VS
        # Code setups) would get "refusing to modify ... malformed JSON", which
        # sends the user to hand-edit a file that is not malformed. utf-8-sig
        # strips a BOM when present and is identical to utf-8 when absent, so
        # it costs nothing on the common path. The WRITE stays plain utf-8, so
        # a BOM'd file is normalised rather than carrying it forever.
        # ONE read, hashed and decoded from the same bytes. A separate read for
        # the stamp would let an edit landing in the gap give a stamp of the OLD
        # bytes and `data` parsed from the NEW ones — so write_settings would
        # later refuse a write whose data already incorporated that edit. That
        # fails safe, but it is a wider version
        # of the very race the stamp exists to close, and it sits UPSTREAM of the
        # residual window documented in write_settings rather than inside it.
        raw_bytes = path.read_bytes()
        stamp = hashlib.sha256(raw_bytes).hexdigest()
        raw = raw_bytes.decode("utf-8-sig")
    except OSError as e:
        die(f"cannot read {path}: {e}")
    except UnicodeDecodeError as e:
        die(f"refusing to modify {path}: it is not valid UTF-8 ({e}). Re-save it as UTF-8, or remove it, before retrying.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        die(
            f"refusing to modify {path}: it contains malformed JSON ({e}). "
            "Fix or remove it by hand before retrying."
        )
    if not isinstance(data, dict):
        die(f"refusing to modify {path}: top-level JSON value is not an object. Settings must be a JSON object; fix or remove it by hand before retrying.")
    return data, True, stamp


def prune_backups(path, keep=None):
    """Drop all but the newest `keep` backups of `path`. Never raises.

    Backups accumulate one per install, each a full copy of a file that can hold
    `env` API keys and an `apiKeyHelper`, so an unbounded pile is both clutter
    and a widening secret surface. Sorted by NAME, which is sound because the
    suffix is a fixed-width UTC-ish timestamp — no stat() call, so a backup whose
    mtime was clobbered still sorts correctly.

    Pruning failure is never fatal: the backup we just took is what the caller
    needs, and losing an old one is not worth aborting an install over.
    """
    keep = BACKUP_KEEP if keep is None else keep
    try:
        entries = list(path.parent.glob(path.name + ".bak.*"))
        # backup()'s own mkstemp sentinel is `<name>.bak.<random>.tmp`, which this
        # glob matches. Normally its finally-block unlinks it, but a SIGKILL, OOM
        # or power loss skips that — and mkstemp's letter-led random suffix sorts
        # AFTER the digit-led timestamps, so an orphan would rank "newest", never
        # age out, and permanently hold a retention slot. Each crash would eat
        # another slot until real backups stopped surviving at all. So: never
        # count a .tmp as a backup, and sweep orphans on sight regardless of age.
        for orphan in [e for e in entries if e.name.endswith(".tmp")]:
            try:
                orphan.unlink()
            except OSError:
                pass
        # Only OUR OWN backups are eligible. The name this writes is
        # `<name>.bak.<%Y%m%dT%H%M%S%f>` — 20 digits and one `T`, nothing else — so anything
        # not matching that shape was put there by someone else and is not ours
        # to delete.
        #
        # The filter is not optional. Eviction takes the lexically smallest and
        # digits sort before letters, so a hand-name is never the oldest — but
        # that holds only for a LETTER-led name. `settings.json.bak.1`,
        # `.bak.0-original` and `.bak.2024-01-01-manual` all sort among the
        # timestamps and would be deleted, silently — measured, not theorised.
        # A test using `.bak.mine`, the one kind of hand-name that reasoning
        # covers, cannot show the filter is unnecessary.
        existing = sorted(e for e in entries if BACKUP_NAME_RE.search(e.name))
        for stale in existing[:-keep] if keep else existing:
            try:
                stale.unlink()
            except OSError:
                pass
    except OSError:
        pass


def backup(path):
    """Timestamped backup next to settings.json, taken before any write.

    Written the same way write_settings() writes: temp file in the SAME
    directory, fsync, then os.replace(). A plain write_bytes() would leave a
    TRUNCATED .bak when the copy hits ENOSPC or EIO part-way — the original untouched, but
    the one artifact the rollback path depends on silently unreliable. A partial
    backup is worse than no backup, because it looks like one.
    """
    ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    backup_path = path.with_name(path.name + f".bak.{ts}")
    tmp_path = None
    try:
        data = path.read_bytes()
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".bak.", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # Inherit the source's mode rather than the umask. mkstemp creates at
        # 0600 and write_bytes() would create at 0666 & ~umask — typically
        # 0644 — so a settings.json deliberately chmod'd 0600 because it carries
        # `env` API keys or an apiKeyHelper would leave a world-readable copy of
        # those secrets sitting in ~/.claude forever. Set BEFORE the rename, so the
        # file is never briefly visible at the wrong mode under its final name.
        os.chmod(tmp_path, path.stat().st_mode & 0o7777)
        os.replace(tmp_path, backup_path)
        # The rename itself is not durable until the DIRECTORY entry is synced.
        # Ordinarily pedantic; load-bearing here because the hardlink branch
        # writes settings.json in place immediately afterwards, and the accepted
        # cost of that in-place write rests on this backup existing after a power loss.
        try:
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
        tmp_path = None
    except OSError as e:
        die(f"could not create backup at {backup_path}: {e}")
    finally:
        # A failed backup leaves nothing behind — not a truncated .bak, and not
        # the temp file either.
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    prune_backups(path)
    return backup_path


def write_settings(path, data, existed, stamp=None):
    """Write settings.json, atomically where that is possible.

    An ORDINARY file goes through a temp file in the same directory then
    os.replace(). A HARDLINKED one is written in place instead, trading
    atomicity to keep the links the user established — so "atomic"
    is true of this function's common path and deliberately not of all of it.
    The paragraphs below describe the atomic path; the hardlink branch carries
    its own reasoning where it forks.

    An interrupted run must never leave a truncated settings.json — the
    replace is atomic on POSIX, and the temp file lives next to the target so
    the replace can't cross a filesystem boundary.
    """
    # Refuse to write over a file that changed since we read it — BEFORE taking
    # a backup, so a refusal has no side effects at all.
    #
    # The atomic replace protects against a TORN settings.json, never a STALE
    # one: the whole file is held in memory between load and write, so anything
    # Claude Code itself wrote in that window — a /config theme change, a
    # permission approval — would be overwritten by our older copy and gone,
    # with nothing to trace the loss back to this script. Milliseconds wide, but
    # this is global config another process edits by design.
    #
    # Checked here rather than just before the replace: by then backup() would
    # already have run and captured the CONCURRENT version, so the message would be naming a backup of the very
    # edit it is protecting. Refusing first means nothing was created, nothing
    # was changed, and the user's file is exactly as their other process left it.
    #
    # Residual, stated rather than implied: an edit landing between this check
    # and the replace a few lines below is still possible. Closing that needs a
    # lock on a file another process does not cooperate on, which is a larger
    # design than this defect warrants.
    if existed and stamp is not None:
        now = stamp_of(path)
        if now is None:
            die(f"cannot re-read {path} to check it is unchanged; refusing rather "
                f"than writing over a file whose current contents are unknown. "
                f"Nothing was created or changed.")
        if now != stamp:
            die(f"{path} changed on disk while this ran — another process "
                f"(most likely Claude Code itself) wrote it between the read and "
                f"the write. Refusing rather than discarding that edit. Nothing "
                f"was created or changed; your file is as the other process left "
                f"it. Re-run to pick up the new contents.")

    # The file did not exist when we read it, but does now: another process
    # created it in the window. Every protection below is gated on `existed`,
    # which was decided at READ time — so without this the staleness check is
    # skipped, no backup is taken, nlink stays 0, and the atomic replace
    # silently discards whatever that process just wrote. Same defect class as
    # the concurrent-EDIT case, for the creation case, and the one path where
    # this file's guards all fail open together.
    if not existed and path.exists():
        die(f"{path} was created while this ran — another process (most likely "
            f"Claude Code itself) wrote it after this read it as absent. "
            f"Refusing rather than overwriting it unseen. Nothing was created or "
            f"changed. Re-run to pick up its contents.")

    indent = 2
    prev_mode = None
    backup_path = None
    if existed:
        backup_path = backup(path)
        try:
            prev_mode = path.stat().st_mode & 0o7777
            indent = detect_indent(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            indent = 2
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        die(f"cannot create {path.parent}: {e}")
    # ensure_ascii=False keeps non-ASCII values (display names, non-English
    # paths) as the bytes the user wrote, instead of re-escaping "café" to
    # "café" — semantically equal, but not the verbatim survival this
    # promises. indent comes from the original file so its formatting survives.
    text = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"

    # A hardlinked settings.json is written IN PLACE, not replaced.
    #
    # os.replace() swaps a whole inode, so a file that is one of several
    # hardlinks loses the link — count drops to 1 and every other path keeps the
    # old content forever, diverging silently with nothing to notice it. That is
    # the same damage get_settings_path() already refuses to do to a SYMLINK,
    # for the reason stated there: following the link "writes where they
    # expect". A hardlink is the same user-established topology and gets the
    # same answer.
    #
    # The cost is real and is not hidden: an in-place write is not atomic, so an
    # interrupted one can leave this file truncated where the replace path could
    # not. Two things bound it — backup() has already run by this point and is
    # itself atomic, so a complete copy exists before a byte is touched; and the
    # warning below tells the user which guarantee they are on. Refusing the
    # install instead would break the dotfile-manager setup this exists to
    # support.
    nlink = 0
    if existed:
        try:
            nlink = path.stat().st_nlink
        except OSError as e:
            # Refuse rather than guess. Defaulting to 0 here would route to the
            # atomic replace — which is exactly the link-breaking behaviour this
            # branch exists to prevent — and would do it silently, with nothing
            # to distinguish it from a legitimate single-link file. That is a
            # fail-OPEN default on the one question this code exists to answer.
            # backup() and the prev_mode stat both succeeded a few lines above,
            # so a failure here is anomalous rather than routine, and the file's
            # established posture on "cannot determine" is to refuse (malformed
            # JSON, non-object top level, non-UTF-8 all die). A retry costs the
            # user nothing; a silently orphaned dotfile-manager link costs them
            # a divergence they will not notice.
            die(f"cannot determine whether {path} is hardlinked ({e}); "
                f"refusing to write rather than risk breaking a link. "
                f"{path} is unchanged, and a backup of it is at {backup_path}. "
                f"Retry once the file is readable.")
    # TOCTOU: a link created or removed between this stat and the write below
    # takes whichever path the stat saw. Accepted — backup() has already run on
    # either path, and this is a single-user config file rather than a security
    # boundary.
    if nlink > 1:
        warn(
            f"{path} has {nlink} hard links; writing in place to keep them. "
            f"This single write is not atomic. If it is interrupted, restore "
            f"from {backup_path}."
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            # The only path in this file that can leave settings.json partially
            # written: open(path, "w") truncates before writing, and this branch
            # deliberately forgoes the atomic replace to keep the hard links. A
            # bare errno here would leave the user staring at [Errno 28] with no
            # idea their global config may now be damaged, or that a good copy
            # exists a filename away.
            die(f"failed part-way through writing {path}: {e}. Because this file "
                f"has hard links it was written in place, so it may now be "
                f"INCOMPLETE. A complete copy from before this run is at "
                f"{backup_path} — restore it with: cp {backup_path} {path}")
        return

    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            # Durability: the rename is atomic, but without this the data may
            # not have reached disk when the rename does, so a crash can leave
            # an empty file where valid settings used to be.
            f.flush()
            os.fsync(f.fileno())
        # mkstemp always creates at 0600, and os.replace() swaps the whole
        # inode — mode included. Without this, every write silently narrows a
        # deliberately group-readable settings.json to owner-only.
        if prev_mode is not None:
            os.chmod(tmp_path, prev_mode)
        os.replace(tmp_path, path)
    except OSError as e:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        die(f"failed writing {path}: {e}")


def cmd_status():
    path = get_settings_path()
    if not path.exists():
        print(f"statusLine: not wired ({path} does not exist)")
        return 0
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        print(f"statusline-install: cannot read {path}: {e}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as e:
        print(f"statusline-install: {path} is not valid UTF-8: {e}", file=sys.stderr)
        return 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"statusline-install: {path} is not valid JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"statusline-install: {path} top-level JSON is not an object", file=sys.stderr)
        return 1
    entry = data.get("statusLine")
    if entry is None:
        print(f"statusLine: not wired in {path}")
        return 0
    if is_ours(entry):
        current = entry.get("command", "")
        print(f"statusLine: wired to this installer's chain script\n  {current}")
        # Which COPY the WIRED ENTRY points at — read off the entry itself, not
        # off resolve_command(), which answers for the script currently running.
        # Those differ exactly when it matters: running a checkout's --status to
        # inspect a settings.json an installed copy wrote is a routine
        # developer workflow, and asking the running script would then report
        # "checkout" about an entry that is nothing of the kind — a false
        # diagnostic on the one surface built to be trustworthy about this.
        #
        # The two shapes are unambiguous: a versioned entry is the `sh -c`
        # version-scanning wrapper, a literal one is a bare `bash "<path>"`.
        if entry_mode(current) == "literal":
            print("  (a checkout, not a published plugin version — this renders "
                  "from a working tree and can diverge from the installed copy)")
        # Compare only the part AFTER any preserved-base prefix. Comparing the
        # whole string, a chained entry would never equal a fresh install's
        # command, so --status would permanently advise `--install` to "repair"
        # it — and that install would then drop the base: the tool would
        # recommend the one action that destroys the config it just preserved.
        base, rest = split_base_prefix(current)
        if base:
            print(f"  (chained after your own statusline: {base})")
        if rest != desired_entry()["command"]:
            print("  (differs from what a fresh install would write — "
                  "run `--install` to repair)")
        return 0
    print(f"statusLine: wired to something else: {entry!r}")
    return 0


def cmd_install(force):
    path = get_settings_path()
    data, existed, stamp = load_settings_for_write(path)
    desired = desired_entry()
    mode = resolve_command()[1]
    current = data.get("statusLine")

    if current == desired:
        print(f"statusLine already wired; nothing to do.\n  {desired['command']}")
        # The no-op path still discloses the mode. Without this, the SECOND and
        # every later install from a checkout would say nothing — and a repeat
        # install is the common case, so the disclosure would have been missing exactly
        # when someone is checking whether their setup is right.
        if mode == "literal":
            warn("this is a checkout, not a published plugin version — the wired "
                 "path points at a working tree and can diverge from the "
                 "installed copy.")
        return 0

    # "Is this entry ours?" must be a STRUCTURAL question, not string equality
    # against today's absolute path. Exact-match would say "third-party" whenever
    # the plugin moves — dev checkout to marketplace install, or one version to
    # the next — which is the relocation this tooling exists to survive, and it
    # would turn a routine repair into a refusal demanding --force. It would also
    # misclassify an entry the user has merely added a supported `padding` key
    # to. Anything invoking a script named statusline-chain.sh is ours to repair.
    ours = is_ours(current)

    if current is not None and not ours and not force:
        print(
            f"statusline-install: statusLine is already set to something else: {current!r}\n"
            "statusline-install: refusing to overwrite without --force.",
            file=sys.stderr,
        )
        return 1

    # Preserve any extra keys the user added to their entry (e.g. `padding`);
    # --force replacing a third-party entry wholesale is correct, repairing our
    # own by discarding their tuning is not.
    merged = dict(current) if ours and isinstance(current, dict) else {}
    merged.update(desired)
    if ours and isinstance(current, dict):
        # Carry a previously preserved base forward. Without this, repairing our
        # own entry would rebuild `command` from desired_entry() alone and
        # silently drop the PLAN_STATUSLINE_BASE prefix a --force install added —
        # so the user's own statusline would survive the install that displaced
        # it and be destroyed by the next routine repair.
        base, _rest = split_base_prefix(current.get("command", ""))
        if base:
            merged["command"] = (
                f"PLAN_STATUSLINE_BASE={shlex.quote(base)} " + merged["command"]
            )
    prefix, reason, shown = None, None, None
    if current is not None and not ours:
        prefix, reason = chain_through(current)
        # `current` may be a bare string rather than a {type, command} object;
        # .get() on it would raise AttributeError and turn --force, the
        # documented escape hatch, into an unactionable crash.
        shown = current.get("command") if isinstance(current, dict) else current
        if prefix:
            merged["command"] = prefix + merged["command"]
    data["statusLine"] = merged
    # These NOTEs are deferred until AFTER the write returns, and that ordering is
    # the whole point. They tell the user their old statusline "is preserved in the
    # backup" — a claim about an artifact that only exists if the write actually
    # happened. Printed beforehand, a refusal (a concurrent edit, an unreadable
    # link count, a failed backup) would produce two contradictory paragraphs in
    # one run: "it is preserved in the backup", then "nothing was created or changed".
    # Both cannot be true, and the reader has no way to tell which is.
    write_settings(path, data, existed, stamp)
    if prefix:
        # Deferred for the same reason the NOTEs below are: it reports what the
        # write DID, and printed beforehand it would stand next to a refusal
        # saying nothing had been written.
        print(f"Preserved your previous statusline as the base: {shown}")
    if mode == "literal":
        warn(
            "installed from a checkout, not a published plugin version.\n"
            "  The path written into settings.json points at this working tree, so\n"
            "  every session in every project will render from it rather than from\n"
            "  the installed plugin — the two can then diverge silently, which is\n"
            "  the failure a hand-written wrapper causes and this installer exists\n"
            "  to prevent. Correct and expected while developing; re-run this from\n"
            "  an installed version to pin it to the published copy."
        )

    if current is not None and not ours and not prefix:
        if reason == "doubles-bar":
            warn(f"your previous statusline was NOT chained in:\n"
                 f"  {shown}\n"
                 f"  It runs plan-progress.py itself, so chaining it would print the\n"
                 f"  plan progress bar twice. It is preserved in the backup beside\n"
                 f"  settings.json; delete it once this install renders correctly.")
        else:
            warn(f"replaced a statusline this tool cannot chain through:\n"
                 f"  {shown}\n"
                 f"  It is preserved in the backup beside settings.json. To keep it "
                 f"as the base, set PLAN_STATUSLINE_BASE to a bash script path.")
    action = "Repaired" if current is not None else "Installed"
    print(f"{action} statusLine -> {merged['command']} in {path}")
    print("Note: on Claude Code 2.1.288 or later the planning plugin already draws "
          "these bars as a band above the prompt; this status-line bar is for older "
          "builds and other hosts, and `--remove` takes it out again.")
    return 0


def cmd_remove(force):
    path = get_settings_path()
    if not path.exists():
        print(f"Nothing to remove: {path} does not exist.")
        return 0
    data, existed, stamp = load_settings_for_write(path)
    if "statusLine" not in data:
        print(f"statusLine not present in {path}; nothing to do.")
        return 0
    # --remove is a destructive action on a key this tool may not own, so it
    # takes the SAME ownership gate as --install. Without it, a user with a
    # hand-configured statusLine who runs `/planning:statusline remove` to tidy
    # up would lose their own configuration silently — while core/README.md
    # promises this installer "refuses to clobber a third-party statusLine
    # without --force", a promise a reader reasonably reads as covering remove.
    if not is_ours(data["statusLine"]) and not force:
        print(
            "statusline-install: statusLine was not installed by this tool: "
            f"{data['statusLine']!r}\n"
            "statusline-install: refusing to remove it without --force.",
            file=sys.stderr,
        )
        return 1
    # If our entry chained a base the user already had, --remove restores THAT
    # rather than deleting the key. Deleting outright would make remove the
    # inverse of a fresh install but not of a --force install: a user whose own
    # statusline was preserved as the base would lose it entirely on remove, recoverable
    # only from a .bak they had no reason to know about — while README.md says
    # remove merely "takes it back out".
    base, _rest = split_base_prefix(
        data["statusLine"].get("command", "")
        if isinstance(data["statusLine"], dict)
        else ""
    )
    if base:
        restored = {"type": "command", "command": f'bash "{base}"'}
        for k, v in data["statusLine"].items():
            if k not in ("type", "command"):
                restored[k] = v
        data["statusLine"] = restored
        write_settings(path, data, existed, stamp)
        print(f"Removed the plan bar and restored your previous statusline in {path}.\n"
              f"  {restored['command']}")
        return 0
    del data["statusLine"]
    write_settings(path, data, existed, stamp)
    print(f"Removed statusLine from {path}.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Manage the statusLine key in ~/.claude/settings.json."
    )
    parser.add_argument("--install", action="store_true", help="write/repair the pointer (default)")
    parser.add_argument("--status", action="store_true", help="report what is currently wired")
    parser.add_argument("--remove", action="store_true", help="remove the statusLine key")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a statusLine this script did not install",
    )
    args = parser.parse_args()

    if args.status:
        return cmd_status()
    if args.remove:
        return cmd_remove(args.force)
    return cmd_install(args.force)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # a CLI tool must never hand the user a traceback
        print(f"statusline-install: unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
