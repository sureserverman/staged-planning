#!/usr/bin/env python3
"""plan-progress — statusline progress bar for executing-plans.

Reads the Claude Code statusline JSON on stdin, walks up from cwd to find
.claude/plan-progress.json (maintained by the executing-plans skill at each
execution transition), parses the referenced plan file with the authoritative
plan-parser regexes from the plugin's lib/plan_parser.py (one contract,
one implementation), and prints a filled progress bar over the plan's Status
fields plus the current stage / task / phase.

It prints SEVERAL lines, not one, and the state file is not the only
source. How many: up to MAX_BARS (3) non-master plans, PLUS
every in-flight master plan for the project — masters are exempt from the cap,
so the line count has no fixed ceiling and "three" is wrong.
The GROUP containing the plan a session is executing
leads -- which is that plan itself, unless it is a sub-plan, in which case its
master prints above it and the phase indicator sits on the indented child.
Below come other in-flight plans for the same project, discovered in its
records home. A consequence worth stating plainly:
a project with in-flight plans renders
bars even when NO execution is running there and no state file exists at all.
What it prints is "this project has unfinished plans", not only "this session
is executing one".

Prints NOTHING when there is nothing to say — no state file AND no discoverable
in-flight plan. Degradation is GRANULAR rather than all-or-nothing: one
unreadable plan costs its own line and leaves its siblings standing, and a
records home that has gone away costs the discovered bars but not the pinned one.
Safe to chain after any existing statusline command; a broken environment costs
lines, never noise.
"""
import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

# Reuse the authoritative plan-parser pieces from the plugin's lib/ (loaded by
# file path, so this module's sys.path is untouched). The plan-status contract
# (what `[ ]` / `[x]` / `[~]` mean) is defined and argued once, at
# lib/plan_parser.py's STATUS_RE — read it there before changing anything here. This module classifies via pu.status_state() and
# never tests the captured character directly: a partial task counts toward
# the bar's denominator but never fills it.
_LIB = Path(__file__).resolve().parents[3] / "lib"
_PARSER = _LIB / "plan_parser.py"
_spec = importlib.util.spec_from_file_location("staged_planning_plan_parser", _PARSER)
pu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pu)

BAR_WIDTH = 20
STALE_AFTER_H = 12  # a state file this old is probably a crashed session

# Palette: every colour clears WCAG 3:1 -- the bar for non-text UI elements, which
# is what a status-line glyph is -- against BOTH a white and a black terminal
# background. A palette tuned for a dark terminal only measures 1.66:1 (YELLOW)
# and 2.72:1 (PURPLE) on white, so the preflight flag and the remediation
# counter are effectively invisible there -- and the remediation
# counter is precisely the signal that exists to make a quietly-looping gate
# visible.
#
# Clearing a bar against both grounds confines a colour to a narrow luminance
# band, because contrast on white wants it dark and contrast on black wants it
# light. These were chosen by holding each role's hue, requiring it stay
# recognisably that hue (HSV saturation >= 70%, value >= 55% -- a status line
# codes by colour, so a colour that reads as mud has lost its job), and then
# maximising the worst of the two contrasts. All five land at 4.38:1 or better
# on both, which also clears the stricter 4.5:1 text bar in four of five cases.
# test-plan-progress.py recomputes these from the escape codes and fails below
# 3:1, so the property is pinned rather than merely documented.
GREEN = "\033[38;2;0;140;47m"      # 4.38:1 white / 4.79:1 black
RED = "\033[38;2;219;54;48m"       # 4.58:1 white / 4.58:1 black
YELLOW = "\033[38;2;148;112;6m"    # 4.59:1 white / 4.58:1 black
CYAN = "\033[38;2;22;129;145m"     # 4.58:1 white / 4.58:1 black
PURPLE = "\033[38;2;162;62;250m"   # 4.56:1 white / 4.61:1 black
DIM = "\033[2m"
RESET = "\033[0m"


# pathlib raises ValueError -- NOT OSError -- for a path containing a NUL byte
# ("embedded null byte"). Every guard in this file that means "this path is
# unusable, degrade" therefore has to name both, and a bare `except OSError` is
# a hole wherever the path came from text rather than from a directory listing.
# Three sources feed such paths: the `cwd` in the statusline's stdin JSON, the
# `plan` field of the state file, and the `Master:` / `- **Plan:**` links read
# out of plan PROSE. One NUL in a sub-plan's backlink would blank the whole
# status line, pinned bar included, on every redraw.
#
# WHICH calls raise is not uniform, and guessing it wrong opens the hole. Measured on CPython 3.12: `stat()`, `resolve()` and `read_text()`
# RAISE, while `is_file()`, `is_dir()` and `exists()` SWALLOW it internally
# (pathlib classes a NUL path as non-encodable and returns False). The guards
# below therefore load-bear on the first group and are belt-and-braces on the
# second; test-plan-progress.py pins both halves, so a future pathlib that
# changes either one fails loudly rather than silently reopening this.
BAD_PATH = (OSError, ValueError)


def find_state(start):
    try:
        d = Path(start).resolve()
    except BAD_PATH:
        return None
    for p in [d, *d.parents]:
        try:
            f = p / ".claude" / "plan-progress.json"
            if f.is_file():
                return f
        except BAD_PATH:
            continue
    return None


# --- records discovery ------------------------------------------------------
# Everything below returns None rather than raising or printing: this code runs on
# EVERY statusline redraw, in every project, on machines this repo does not control,
# where the only acceptable failure is a missing bar.

def repo_root_of(state_file):
    """The repo root implied by a state file at <root>/.claude/plan-progress.json."""
    return state_file.parent.parent


# A configured resolver runs on every redraw, so this caller caps it far below the
# contract's 10 s: a slow or hung resolver costs one redraw this long, then no bars.
RESOLVER_TIMEOUT_S = 2.0


def _records_home():
    """lib/records_home.py loaded by file path, or None if it cannot be loaded."""
    try:
        spec = importlib.util.spec_from_file_location("staged_planning_records_home",
                                                      _LIB / "records_home.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.TIMEOUT = RESOLVER_TIMEOUT_S
        return mod
    except Exception:
        return None


def records_plans_dir(repo_root):
    """The `plans/` directory of this repo's records home, or None.

    The records home comes from lib/records_home.py, read-only: exit 0 is a configured
    resolver's home, exit 3 is the repo default `<repo>/docs`. Exit 2 (a resolver that
    is configured but cannot reach its storage) is None — no bars — never the repo
    default: bars built from in-tree plans while the configured store is unreachable
    would be a false picture, and absent bars are honest.
    """
    # `repo_root` reaches here from the statusline's stdin `cwd` when no state file
    # exists, so it is untrusted text; guarded here rather than left to render()'s
    # outer try, because the corpus sweep calls this function raw on purpose.
    try:
        repo_root = Path(repo_root).resolve()
    except BAD_PATH:
        return None
    rh = _records_home()
    if rh is None:
        return None
    try:
        code, home, _ = rh.resolve(str(repo_root))
    except Exception:
        return None
    if code not in (0, 3) or not home:
        return None
    plans = Path(home) / "plans"
    try:
        return plans if plans.is_dir() else None
    except BAD_PATH:
        # an unreadable or unmounted path raises rather than returning False
        return None


def parse_plan(text, path=None):
    """(done, total, stage_count) via the lib/plan_parser.py Status contract.

    A `[~]` partial task counts toward `total` but never toward `done`, so the
    bar shows the plan as less finished rather than shorter — classification
    goes through pu.status_state(), never `!= " "` (which would fill the bar
    for an in-flight task).
    """
    if pu.is_master_plan(text, path):
        return parse_master(text)
    stages = set()
    done = total = 0
    in_task = False
    for line in text.splitlines():
        sh = pu.STAGEHDR_RE.match(line)
        if sh:
            stages.add(int(sh.group(1)))
        if pu.TASK_RE.match(line):
            in_task = True
        sm = pu.STATUS_RE.match(line)
        if sm and in_task:
            total += 1
            done += pu.status_state(sm.group(1)) == "done"
            in_task = False
    return done, total, len(stages)


def parse_master(text):
    """(done, total, stage_count) for a MASTER plan, from its sub-plan register.

    A master has no `### Task N.N` headings, so the ordinary counter reads every
    master as 0/0 — indistinguishable from a plan nobody has started, so no
    master could ever classify as in flight.

    Its progress is its register: one `### Sub-plan N:` entry per sub-plan, each
    with a `- **Status:**` the master's own close-out flips. stage_count is 0 —
    a master has sub-plans, not stages, so `S2/4` would be a category error.
    Sub-plan registers also carry `**Gate:**` blocks of `- [ ]` checkboxes;
    those are not Status lines and STATUS_RE does not match them.
    """
    done = total = 0
    in_entry = False
    for line in text.splitlines():
        if pu.SUBPLAN_RE.match(line):
            in_entry = True
            continue
        sm = pu.STATUS_RE.match(line)
        if sm and in_entry:
            total += 1
            done += pu.status_state(sm.group(1)) == "done"
            in_entry = False        # one Status per entry; consume it
    return done, total, 0


def plan_is_eligible(text, path=None):
    """Whether a plan counts as 'in flight' and so earns a bar.

    Eligible = STARTED but not CLOSED OUT:
      started    -> at least one Status classified `done` or `partial`
      closed out -> a **Completed:** or **Abandoned:** line

    A MASTER plan is exempt from the `started` half: it is
    visible whenever it is not closed out. A master with no
    sub-plan yet begun is still work the project has committed to, and its bar
    reads 0/N rather than being invisible. "Not closed out" means NEITHER
    **Completed:** NOR **Abandoned:** -- abandonment is the other terminal
    marker, and suppressing on it is the plan-status contract's existing rule,
    so the exemption widens what counts as started and nothing else.

    Classification goes through pu.status_state(), never a test on the captured
    character: `!= " "` reads `[~]` as done, so a blocked task would count as
    finished. Both terminal markers come from pu as well, so this file
    restates no part of the plan-status contract.

    Deliberately NOT eligible: an all-`[ ]` non-master plan (authored, never
    started -- a bar reading 0/13 is noise), a plan with no Status fields at all
    (the checkbox-era legacy and *-design.md documents), and anything closed out.
    """
    started = False
    in_entry = False
    # A master's progress lives in its `### Sub-plan N:` register, not in Task
    # headings it does not have. Counting only TASK_RE would make no master
    # eligible -- every one would read as "authored, never started".
    is_master = pu.is_master_plan(text, path)
    opener = pu.SUBPLAN_RE if is_master else pu.TASK_RE
    for line in text.splitlines():
        if opener.match(line):
            in_entry = True
            continue
        sm = pu.STATUS_RE.match(line)
        if sm and in_entry:
            in_entry = False
            if pu.status_state(sm.group(1)) in ("done", "partial"):
                started = True
    if not started and not is_master:
        return False
    if pu.ABANDONED_RE.search(text):
        return False
    # A close-out line retires a plan — UNLESS a gate check could not be run.
    # Without this the three consumers of one contract would disagree about the
    # same plan: one calls it in flight, the audit calls it blocked, and this
    # renderer shows no bar at all. One definition means a change cannot alter
    # what "the gate passed" means in one consumer and not another.
    if pu.COMPLETED_RE.search(text):
        return pu.plan_blocked(text, path)[0]
    return True


MAX_BARS = 3

# The date stamp a plan filename opens with (2026-08-06-<slug>-plan.md).
# Recency comes from THIS, never from the file's modification time:
# a plan directory that was copied or migrated gives every plan the same
# modification time, so that timestamp measures a copy operation rather than
# when the work happened.
# (test-plan-progress.py pins this two ways: case_ordering_ignores_mtime reads the
# source of date_stamp/_rank and asserts neither names a stat field, and the
# ordering test utimes the oldest plan to 2038 and asserts the order does not
# move. The check is scoped to those two functions: a grep of the whole file for
# the field name would ban mtime for cache invalidation too — a different and
# necessary use — and match explanatory comments like this one.)
DATE_STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def date_stamp(path):
    """The filename's leading date stamp, or "" when it has none.

    "" sorts last under reverse=True, so an unstamped plan ranks below every
    stamped one instead of crashing the sort or jumping to the front.
    """
    m = DATE_STAMP_RE.match(path.name)
    return m.group(1) if m else ""


def _same_file(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except BAD_PATH:
        return False


def _rank(path):
    # name as tiebreaker so same-day plans have a stable, reproducible order
    return (date_stamp(path), path.name)


CACHE_NAME = "plan-progress-cache.json"
CACHE_VERSION = 3   # v3: the cache carries a `masters` list


def rule_signature():
    """A fingerprint of the CODE that produced a cache's verdicts, or None.

    scan_signature() below fingerprints the plans DIRECTORY, so the cache
    correctly rebuilds whenever a plan file changes. That does not fingerprint the
    ELIGIBILITY RULE, and that is an independent axis: when `plan_is_eligible`
    itself changes, every cache on disk keeps serving verdicts computed by the
    OLD rule against a directory whose signature is still perfectly valid — and
    keeps doing so forever, because nothing in the key can ever notice. Only an
    unrelated edit to some plan file breaks the spell.

    Not something a test catches: a change to the rule
    leaves existing caches serving the old verdicts, so a feature can ship and
    never fire — and any other output that depends on the verdict, like the tree
    glyphs that render master bars, stays stale with it.

    Deliberately a digest of the two whole source files rather than of the
    rule's individual functions and regexes. Eligibility depends on
    plan_is_eligible, TASK_RE, SUBPLAN_RE, STATUS_RE, COMPLETED_RE,
    ABANDONED_RE, status_state and is_master_plan; enumerating those here would
    create exactly the lockstep site that drifts, which is the bug class this
    key exists to close. Over-invalidating on a comment edit costs one ~12 ms
    rescan, once.

    CONTENT, not (mtime, size): a deployment that preserves timestamps across a
    real edit —
    `rsync -a`, some Docker COPY layers, a same-second checkout — leaves
    (mtime, size) identical while the rule underneath has changed, which is
    precisely the silent-stale failure this function exists to prevent, sneaking
    back in through the key itself. Measured: 0.048 ms against a 33 ms redraw.
    """
    out = []
    for f in (Path(__file__), _PARSER):
        try:
            out.append(hashlib.sha256(Path(f).read_bytes()).hexdigest())
        except BAD_PATH:
            return None     # rule unknown -> decline the cache, never trust a stale one
    return out

# Instrumentation for the cache test. Counting actual plan-file READS is the
# only honest way to assert "the cache was used": a timing assertion passes on
# a fast machine whether or not the cache works, which is the test-that-cannot-
# fail shape.
PLAN_READS = 0


def _read_plan(path):
    global PLAN_READS
    PLAN_READS += 1
    return path.read_text(errors="ignore")


def scan_signature(plans_dir):
    """A fingerprint of the plans directory, or None if it cannot be read.

    Per-file (name, modification time, size) — NOT the directory's own
    timestamp. Verified on this platform:
    a directory's timestamp moves when an entry is added, removed or renamed,
    and does NOT move when a file's CONTENT changes. A cache keyed on it would
    therefore go stale on exactly the edit that matters most here — a Status
    flip during execution — so the bar would show yesterday's eligibility for
    the entire run the bar exists to narrate.

    Size alone does not rescue it either: `- **Status:** [ ]` and
    `- **Status:** [x]` are the same number of bytes.

    Cheap by design: a stat per file, no reads. The reads are what this caches.

    ACCEPTED RESIDUAL RISK, named because rule_signature() below rejects the
    identical shortcut and silence here would read as oversight. (name, mtime,
    size) misses a content change that preserves the timestamp -- `rsync -a`, a
    restored backup, some Docker COPY layers -- exactly as it does for the rule.
    To reproduce: flip `[ ]` to `[x]` (same byte length), restore the
    mtime, and the cache serves the stale verdict forever with zero reads.
    Not fixed the same way, deliberately: rule_signature hashes TWO files, while
    this covers every plan in the directory (~50), and hashing them means
    READING them all -- which is the precise cost this cache exists to avoid.
    Content-addressing here would leave the cache saving only the parse, turning
    a 4x saving into nearly none. The trade is a real edit going unseen only
    when a tool deliberately preserves timestamps; ordinary edits, including the
    Status flips this bar narrates, always move mtime.
    """
    try:
        out = []
        for f in sorted(Path(plans_dir).glob("*.md")):
            st = f.stat()
            out.append([f.name, st.st_mtime_ns, st.st_size])
        return out
    except BAD_PATH:
        return None


def _safe_cache_name(name):
    """Whether a filename read back from the cache may be joined to plans_dir.

    The cache is trusted to skip the reads, so nothing downstream re-validates
    what it names. `Path(plans_dir) / "/etc/passwd"` DISCARDS plans_dir and
    yields /etc/passwd, and "../../x" is preserved literally — so a planted
    cache entry becomes an arbitrary file read whose name is then displayed in
    the user's terminal chrome. Bare filenames only (CWE-22).
    """
    return (isinstance(name, str)
            and name not in ("", ".", "..")
            and not os.path.isabs(name)
            and os.sep not in name
            and (os.altsep is None or os.altsep not in name))


def _is_file(path):
    """`path.is_file()` that cannot raise.

    pathlib swallows only ENOENT / ENOTDIR / EBADF / ELOOP; **EACCES is not in
    that set**, so `is_file()` on a path inside an unreadable directory raises
    PermissionError. Same platform detail as records_plans_dir's `is_dir()`
    guard above, and the pinned plan is the common case, so an unguarded call
    would raise on every redraw whose plans directory has become unreadable.
    """
    try:
        return path.is_file()
    except BAD_PATH:
        return False


def _read_cache(cache_file):
    if cache_file is None:
        return None
    try:
        data = json.loads(Path(cache_file).read_text(encoding="utf-8"))
    except Exception:
        # Missing, truncated, corrupt, not JSON, wrong encoding — every one of
        # them means "rebuild", never "raise". A cache that can break the
        # statusline is worse than no cache.
        return None
    return data if isinstance(data, dict) else None


def _write_cache(cache_file, plans_dir, signature, names, rule, masters=()):
    if cache_file is None or rule is None:
        return              # an unkeyed cache is worse than none — see rule_signature()
    try:
        p = Path(cache_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({
            "version": CACHE_VERSION,
            "rule": rule,
            "plans_dir": str(plans_dir),
            "signature": signature,
            "eligible": names,
            # Masterhood is cached beside eligibility because the cap needs
            # it and only the FILENAME half of it can be recovered from
            # a name: `# Master Plan:` in the first heading is equally valid, so
            # recomputing on a cache hit would mean reading every plan file --
            # the exact cost this cache exists to avoid.
            "masters": list(masters),
        }), encoding="utf-8")
        os.replace(tmp, p)
    except BAD_PATH:
        pass  # an unwritable cache is a missed optimisation, not a failure


def discover_plans(plans_dir, pinned=None, cache_file=None):
    """The plans to render, newest first by filename date stamp.

    `pinned` is the plan the state file names. It is included UNCONDITIONALLY
    when it exists — not merely bumped up the ranking — because it is the plan
    actually being executed. A plan can legitimately be mid-execution and
    ineligible: one at 0/13 has been started by a human but carries no `[x]`
    yet, and the bar shows it. Eligibility governs which OTHER plans earn a bar, not
    whether the executing one does.

    MAX_BARS bounds NON-MASTER plans only; eligible masters are added on top of
    that budget rather than competing for its slots. The cap selects by date
    stamp and knows nothing of the master->sub-plan association that
    group_plans() then renders, so under one shared budget a 4th eligible plan
    newer than a master would evict the MASTER — and, because `-master-plan.md`
    sorts below `-sub-NN-` within a shared date stamp, the parent would be
    dropped FIRST, leaving its children flat and glyphless: a tree with no root.
    Exempting masters dissolves the question "which plan gets dropped to make
    room for a master?" rather than answering it.

    THE NUMBER OF MASTERS IS UNBOUNDED BY THIS CODE, and that is a deliberate
    consequence of the exemption rather than an oversight. A project renders
    `3 + (its open masters)` bars. Any figure observed for it is an OBSERVED
    MAXIMUM on one set of plans at one moment — not a bound anything enforces,
    and not a number a future maintainer may rely on.

    If the count ever does read as too many, the lever is a SEPARATE cap on
    masters, never a shared one — the point of the exemption is that a master
    must not lose its slot to its own children.
    """
    pinned_r = None
    if pinned is not None:
        try:
            pinned_r = Path(pinned).resolve()
        except BAD_PATH:
            pinned_r = None

    eligible = []       # eligible non-masters — these compete for MAX_BARS
    masters = []        # eligible masters — exempt from the cap
    pinned_is_master = False
    if plans_dir is not None:
        plans_dir = Path(plans_dir)
        sig = scan_signature(plans_dir)
        rule = rule_signature()
        cached = _read_cache(cache_file) if (sig is not None and rule is not None) else None
        if (cached is not None
                # `version` is checked, so a future format change
                # invalidates rather than misreads.
                and cached.get("version") == CACHE_VERSION
                and cached.get("rule") == rule
                and cached.get("plans_dir") == str(plans_dir)
                and cached.get("signature") == sig
                and isinstance(cached.get("eligible"), list)
                and isinstance(cached.get("masters"), list)):
            cached_masters = {n for n in cached["masters"] if _safe_cache_name(n)}
            # dict.fromkeys, not the raw list: _write_cache builds its names
            # from a directory glob and so can never emit a duplicate, but a
            # TAMPERED cache can — and that is the threat model _safe_cache_name
            # already exists for. A repeated name would otherwise spend two of
            # the three non-master slots on one plan and make group_plans()
            # render the same master's group twice. Not a traversal; a way to
            # spend the bar budget on nothing.
            for name in dict.fromkeys(cached["eligible"]):
                if _safe_cache_name(name):
                    (masters if name in cached_masters else eligible).append(
                        plans_dir / name)
        elif sig is not None:
            for f in sorted(plans_dir.glob("*.md")):
                try:
                    text = _read_plan(f)
                    if plan_is_eligible(text, f):
                        (masters if pu.is_master_plan(text, f) else eligible).append(f)
                except BAD_PATH:
                    continue  # deleted or unreadable mid-scan — never raise
            _write_cache(cache_file, plans_dir, sig,
                         [f.name for f in eligible + masters], rule,
                         [f.name for f in masters])

        # The pinned plan is added below on its own terms, so it must not also
        # arrive through either list.
        if pinned_r is not None:
            eligible = [f for f in eligible if not _same_file(f, pinned_r)]
            before = len(masters)
            masters = [f for f in masters if not _same_file(f, pinned_r)]
            pinned_is_master = len(masters) < before

    eligible.sort(key=_rank, reverse=True)
    masters.sort(key=_rank, reverse=True)

    chosen = []
    capped = 0          # how many of the MAX_BARS non-master slots are taken
    if pinned_r is not None and _is_file(pinned_r):
        chosen.append(pinned_r)
        # A pinned MASTER does not spend a capped slot, for the same reason no
        # other master does. When the pinned plan is a master that is itself
        # closed out it is absent from `masters` and so counted here — which is
        # the conservative direction: it costs one non-master bar, never a
        # master's slot.
        if not pinned_is_master:
            capped += 1
    for f in eligible:
        if capped >= MAX_BARS:
            break
        chosen.append(f)
        capped += 1
    chosen.extend(masters)
    chosen.sort(key=_rank, reverse=True)
    return chosen


# Tree glyphs for a master's sub-plans. Box-drawing rather than ASCII `|-`
# because every other glyph in this file is already non-ASCII (█ ░ ⚙ ▶ ◆ ⚑),
# so a terminal that mangles these was already mangling the bar itself.
TREE_MID = "├─ "
TREE_LAST = "└─ "


def _plan_text(path):
    """A plan's text, or "" — grouping must never cost a bar."""
    try:
        return _read_plan(path)
    except BAD_PATH:
        return ""


def master_of(text, path):
    """The path this sub-plan's `Master:` backlink names, or None."""
    m = pu.MASTER_BACKLINK_RE.search(text)
    if not m:
        return None
    target = pu.link_target(m.group(1))
    return path.parent / target if target else None


def subplans_of(text, path):
    """Every path this master's register `- **Plan:**` lines name, in order.

    Order is load-bearing: it is the register's dependency order, which is what
    a reader expects children to be listed in, and it is the only ordering that
    survives a sub-plan whose filename date stamp does not match its number.
    """
    out = []
    for m in pu.SUBPLAN_LINK_RE.finditer(text):
        target = pu.link_target(m.group(1))
        if target:
            out.append(path.parent / target)
    return out


def group_plans(paths, pinned=None):
    """[(path, prefix)] — each master immediately above its own sub-plans.

    Presentation only. This reorders and prefixes what discovery already chose;
    it never adds a plan and never drops one, so the cap and the eligibility
    filter keep their meaning. A sub-plan
    whose master is not among the chosen plans therefore renders
    top level, no glyph — which is the COMMON case, since a master earns
    its own bar on its own eligibility and often has none.

    `pinned` keeps the plan this session is executing at the top. It is the plan's GROUP that is hoisted, not the
    plan: when the pinned plan is a sub-plan, its master has to stay above it or
    the tree glyphs point at nothing.
    """
    # Path keys throughout: discover_plans() already deduplicates by _same_file,
    # so no two entries here name one file under two spellings.
    texts = {p: _plan_text(p) for p in paths}
    masters = [p for p in paths if pu.is_master_plan(texts[p], p)]

    # Union of the two links, not either alone: the backlink is missing from
    # some sub-plans and the register entry from others, and a sub-plan is a
    # sub-plan if EITHER side says so.
    register = {m: subplans_of(texts[m], m) for m in masters}
    parent_of = {}
    for p in paths:
        if p in masters:
            continue
        back = master_of(texts[p], p)
        for m in masters:
            if ((back is not None and _same_file(back, m))
                    or any(_same_file(c, p) for c in register[m])):
                parent_of[p] = m
                break

    def child_order(master, kid):
        # Register position first; a child linked only by its backlink has none
        # and falls back to filename order. The two never compare against each
        # other, so the mixed key types below never meet.
        for i, c in enumerate(register[master]):
            if _same_file(c, kid):
                return (0, i)
        return (1, _rank(kid))

    groups = []
    for m in masters:
        kids = [p for p in paths if parent_of.get(p) == m]
        kids.sort(key=lambda k: child_order(m, k))
        groups.append([m] + kids)
    for p in paths:
        if p not in masters and p not in parent_of:
            groups.append([p])

    # A group ranks by its NEWEST member, so grouping never pushes a recent
    # sub-plan below an older unrelated plan just because its master is old.
    def group_rank(g):
        holds_pinned = pinned is not None and any(_same_file(x, pinned) for x in g)
        return (holds_pinned, max(_rank(x) for x in g))

    groups.sort(key=group_rank, reverse=True)

    # The text is handed on rather than dropped: these files were just read to
    # work out the structure, and render_*() would otherwise read them again.
    out = []
    for g in groups:
        out.append((g[0], "", plan_name(g[0]), texts[g[0]]))
        for i, kid in enumerate(g[1:]):
            glyph = TREE_LAST if i == len(g) - 2 else TREE_MID
            out.append((kid, f"{DIM}{glyph}{RESET}", relative_name(kid, g[0]), texts[kid]))
    return out


# Width. Bars only read as a stack if they start at the same column,
# and plan names run to 90 characters (a date stamp, a topic, then a
# `sub-NN-<slug>` tail), which alone would push a bar off any terminal.
NAME_WIDTH = 46     # visible chars for the name column, tree prefix included
                    # Measured in CHARACTERS, which is correct for the
                    # date-stamped ASCII plan filenames and is the assumption
                    # this column's alignment rests on -- see clip()'s note on CJK.
NOTE_WIDTH = 44     # visible chars for free-text task_desc / blocked note
ELLIPSIS = "…"

# Visible width is NOT len(): every line here carries SGR escapes, and a colour
# change is zero columns wide. Aligning on len() lines up the escape bytes
# instead of the glyphs, so a coloured line and an uncoloured one drift apart by
# exactly the length of their colour codes -- which is why the pinned bar (CYAN)
# and a discovered bar (DIM) are the pair that exposes it.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(s):
    return len(ANSI_RE.sub("", s))


# Control characters are STRIPPED before anything is measured or cut, and ESC is
# the one that matters. Everything this renderer emits goes straight to a
# terminal, and three of its inputs are text somebody else wrote: a plan's
# FILENAME, and the state file's `task_desc` and `note`. A literal ESC in any of
# them is at best a colour nobody authorised; at worst clip() cuts through the
# middle of the CSI sequence and emits an UNTERMINATED one, which then consumes
# the bytes that follow as its own parameters -- including this file's RESET,
# leaving the user's terminal recoloured after the status line ends (CWE-150).
# For example: clip("\x1b[35mHELLO", 3) -> "\x1b[…".
#
# Stripping rather than escaping, because there is no legitimate control
# character in a plan name or a one-line task description, and a status line has
# no way to display one usefully.
# C1 (U+0080-U+009F) as well: U+009B is a one-byte CSI to a terminal in 8-bit mode.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


# Invisible format characters (Cf: bidi overrides that reorder what follows,
# zero-width marks) and lone surrogates (Cs) are dropped too: the classes
# plan_continue_classify.py's clean() drops, and the band's own scrub.
HIDDEN_CATEGORIES = ("Cf", "Cs")


def plain(s):
    """`s` with control and hidden characters removed. Not optional — see CONTROL_RE."""
    if not isinstance(s, str):
        return ""
    s = CONTROL_RE.sub("", s)
    if s.isascii():
        return s
    return "".join(c for c in s if unicodedata.category(c) not in HIDDEN_CATEGORIES)


SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def rgb_hex(values):
    """`#rrggbb` for three SGR parameters, or None unless each is 0..255 in ASCII digits.

    Length is checked before int(): an SGR parameter is unbounded, and int() of a
    string over 4300 digits raises ValueError (Python 3.11+)."""
    if len(values) != 3 or not all(v.isascii() and v.isdigit() and len(v) <= 3 and int(v) <= 255
                                   for v in values):
        return None
    return "#" + "".join(f"{int(v):02x}" for v in values)


def sgr_hex(code):
    """`#rrggbb` for one of this file's `38;2;r;g;b` colour constants."""
    m = SGR_RE.fullmatch(code)
    parts = m.group(1).split(";") if m else []
    hexed = rgb_hex(parts[2:]) if parts[:2] == ["38", "2"] else None
    if hexed is None:
        raise ValueError(f"not a 24-bit colour: {code!r}")
    return hexed


def palette():
    """The five role colours as hex, read from the constants the text uses."""
    return {"green": sgr_hex(GREEN), "red": sgr_hex(RED), "yellow": sgr_hex(YELLOW),
            "cyan": sgr_hex(CYAN), "purple": sgr_hex(PURPLE)}


def tail_parts(raw):
    """(`tail`, `tail_spans`) for the part of a line after its bar.

    `tail` is the text plain and stripped. `tail_spans` is the same text split at
    the line's own SGR codes into `{text, color, dim}`: `38;2;r;g;b` sets `color`
    to `#rrggbb`, `2` sets `dim`, `0` (or an empty code) clears both. Each span's
    text goes through plain(), so text from the plan or the state file reaches a
    span with no control or hidden character, and the span texts join to `tail`.
    Colours come from the escape codes themselves, so a front end drawing the
    spans cannot drift from the status line.
    """
    spans, color, dim, pos = [], None, False, 0

    def take(seg):
        text = plain(seg)
        if text:
            spans.append({"text": text, "color": color, "dim": dim})

    for m in SGR_RE.finditer(raw):
        take(raw[pos:m.start()])
        pos = m.end()
        params = m.group(1).split(";") if m.group(1) else ["0"]
        i = 0
        while i < len(params):
            p = params[i]
            if p in ("", "0"):
                color, dim = None, False
            elif p == "2":
                dim = True
            elif p == "22":
                dim = False
            elif p == "39":
                color = None
            elif p == "38":
                # Only `38;2;r;g;b` is a colour here; any other 38 form ends the
                # code, so its parameters are never read as dim or reset.
                if i + 4 < len(params) and params[i + 1] == "2":
                    color = rgb_hex(params[i + 2:i + 5])
                    i += 4
                else:
                    break
            i += 1
    take(raw[pos:])
    # The same .strip() as `tail`, applied at the ends of the span list.
    while spans and not spans[0]["text"].lstrip():
        spans.pop(0)
    if spans:
        spans[0]["text"] = spans[0]["text"].lstrip()
    while spans and not spans[-1]["text"].rstrip():
        spans.pop()
    if spans:
        spans[-1]["text"] = spans[-1]["text"].rstrip()
    return "".join(sp["text"] for sp in spans), spans


def plan_id(path):
    """A short stable id for a plan: the first 8 hex of the sha1 of its resolved path."""
    try:
        key = str(Path(path).resolve())
    except (*BAD_PATH, RuntimeError):   # RuntimeError: a symlink loop, Python <= 3.12
        key = str(path)
    return hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()[:8]


def clip(s, width):
    """`s` cut to `width` VISIBLE columns, ending in … when anything was lost.

    Takes PLAIN text only — pass it through plain() first if it came from a
    filename or the state file. It counts columns with len(), so an escape
    sequence would be measured as its bytes and could be cut in half; plain()
    is what makes that unreachable rather than merely discouraged. Escape
    safety rests on that precondition, not on this function.

    Width is measured in CHARACTERS, which is correct for the aligned column
    (date-stamped ASCII filenames by plan convention) and WRONG for CJK text,
    where each glyph occupies two terminal columns. The error is OVERSHOOT, not
    undershoot: a 44-character CJK clip measures roughly 88 columns, about
    double the intended budget, not "a little short". It still never MISALIGNS anything, because notes are
    clipped and never padded against a sibling; it just overruns. Accepted for
    now: these fields are written in English, and a column-aware width belongs
    with the whole-line bound, not here.
    """
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    # No `if width > 1 else ELLIPSIS` branch: at width 1 this is s[:0] + ELLIPSIS,
    # which already IS ELLIPSIS. Such a guard would be dead code: deleting it
    # changes nothing. One expression, no precedence question.
    return s[: width - 1] + ELLIPSIS


def plan_name(path):
    """The display name: the filename minus its plan suffix."""
    name = plain(Path(path).name)
    for suffix in ("-light-plan.md", "-plan.md", ".md"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def relative_name(child, master):
    """A sub-plan's name with the prefix it shares with its master removed.

    A tree already says who the parent is, so repeating the parent's name on
    every child spends the column on the one thing the indent has established
    and truncates away the one thing it has not.

    The consequence without it: names are clipped from the TAIL, but a
    sub-plan's distinguishing part -- `sub-NN-<slug>` -- IS the tail, while the
    shared date stamp and topic eat the column ahead of it, so every child of
    one master can render the byte-identical string `<date>-<shared topic>…`.
    Different plans, different bars, nothing to tell them apart. The relationship read; the
    identity did not.

    Matched on whole `-`-separated TOKENS, never on raw characters, and only
    when at least four of them agree. Both halves of that rule matter: a
    character-wise common prefix of `2026-08-01-alpha-master` and
    `2026-08-02-alpha-sub-01-foundation` is `2026-08-0`, which would cut the
    child down to `02-alpha-sub-01-foundation` — a fragment of the DATE
    promoted to the front of the name, reading as a plan called "02-alpha…".

    Four tokens means the whole date stamp (`2026`, `08`, `04`) plus at least
    one shared topic word, i.e. evidence of a genuinely shared subject rather
    than two plans that merely share a day. A child whose name diverges from its
    master's earlier than that keeps its full name: there is nothing redundant
    to remove, and the indent already says whose child it is.
    """
    c, p = plan_name(child), plan_name(master)
    ct, pt = c.split("-"), p.split("-")
    shared = 0
    for a, b in zip(ct, pt):
        if a != b:
            break
        shared += 1
    if shared >= 4 and len(ct) > shared:
        return "-".join(ct[shared:])
    return c


def name_column(labels, prefixes):
    """The shared visible width the name column should take.

    The widest label that fits, so a single bar is padded to its own width and
    therefore not padded at all -- which is what keeps the one-plan golden
    byte-identical while three plans align. The tree prefix counts toward the
    width, so a child's name gets less room and its bar still lands on the same
    column as its master's. Measures the LABEL that will be displayed, not the
    filename: a child shows its name relative to its master, and measuring the
    full filename here would reserve a column nothing ever fills.
    """
    widest = 0
    for label, prefix in zip(labels, prefixes):
        widest = max(widest, visible_len(prefix) + len(label))
    return min(widest, NAME_WIDTH)


def bar(done, total):
    filled = round(BAR_WIDTH * done / total) if total else 0
    return (
        f"{DIM}▐{RESET}{GREEN}{'█' * filled}{RESET}"
        f"{DIM}{'░' * (BAR_WIDTH - filled)}▌{RESET}"
    )


# The state file has TWO dialects.
# references/progress-state-file.md specifies `phase` as one of six keywords,
# `stage` as an integer and `task` as "N.M". Writers also put prose
# into those same keys and the integers in `stage_index`/`stage_total`
# beside them -- a file can carry, e.g. (invented):
#   "phase": "STOPPED — Stage 2 re-gate FAILED; awaiting user direction"
#   "stage_index": 2, "stage_total": 2   (and no `stage` or `task` at all)
# Neither side is simply wrong: the richer file is more useful to a human
# reading it, so the renderer does not demand that writers comply. It
# reads the ints when they are there, interpolates `stage`/`task` only when they
# are the shape the schema promises, and otherwise says NOTHING -- a status line
# has one line's worth of room, so a paragraph pasted into it is worse than a
# missing field.
KNOWN_PHASES = ("preflight", "task", "gate", "closeout", "blocked", "handoff")
TASK_ID_RE = re.compile(r"^\d+\.\d+$")


def _int(v):
    """`v` when it is a real int, else None.

    `type(v) is int`, not isinstance: bool subclasses int, so a stray
    `"stage_index": true` would otherwise render as stage 1. Same discipline
    the remediation_round field already uses below.
    """
    return v if type(v) is int else None


def _stage_int(v):
    """A POSITIVE int, else None.

    Stages are 1-indexed everywhere in the format (`## Stage 1 — …`), so 0 and
    negatives are malformed rather than edge cases, and both degrade to "no
    stage position" instead of rendering `S0/3` or `S-1/3`. Stated as its own
    predicate because the precedence below then has no falsy-but-valid value
    left to trip over: an `_int(a) or _int(b)` form would silently let `stage`
    win over an explicit `stage_index: 0`.
    """
    n = _int(v)
    return n if n is not None and n > 0 else None


def stage_position(state, stage_count):
    """(index, total) for the `S2/4` part, or None when the file does not say.

    Among VALID values, `stage_index`/`stage_total` win over `stage` — a file
    carrying both is one where `stage` holds prose. `stage_total` in turn wins
    over the count parsed from the plan: a sub-plan mid-master knows its own
    stage total, and a master's parsed count is 0 by design.
    """
    idx, total = stage_pair(state, stage_count)
    return (idx, total) if idx is not None and total is not None else None


def stage_pair(state, stage_count):
    """(index, total), each None when unknown — stage_position()'s two halves.

    Split out so `--json` can report a stage whose total is unknown (and vice
    versa) while the text keeps printing `S2/4` only when it has both.
    """
    idx = _stage_int(state.get("stage_index"))
    if idx is None:
        idx = _stage_int(state.get("stage"))
    total = _stage_int(state.get("stage_total"))
    if total is None:
        total = _stage_int(stage_count)
    return idx, total


def blocker_note(state):
    if state.get('schema_version')==2 and isinstance(state.get('blocker'),dict):
        blocker=state['blocker']
        if state.get('phase')=='handoff':
            return blocker.get('reason') or ''
        return (blocker.get('prevented_operation') or '')+'; dependency: '+(blocker.get('dependency') or '')
    return state.get('note') or state.get('task_desc') or ''


def phase_part(state):
    phase = state.get("phase", "task")
    if phase not in KNOWN_PHASES:
        # A prose phase would otherwise fall through every branch into the task
        # case and render a bare "▶ " with nothing after it.
        # An unrecognised phase means the file is telling us something this bar
        # has no room for, so it says nothing at all.
        return ""
    stage = _stage_int(state.get("stage_index"))
    if stage is None:
        stage = _stage_int(state.get("stage"))
    if phase == "preflight":
        return f"{YELLOW}⚑ preflight{RESET}"
    if phase == "gate":
        # `S{stage}` only when there IS one; otherwise it would render "SNone gate"
        # for a gate whose stage the file did not record.
        part = (f"{PURPLE}◆ S{stage} gate{RESET}" if stage is not None
                else f"{PURPLE}◆ gate{RESET}")
        # Only present when a gate is being re-run after a failure; a gate on its
        # first round renders with no round counter.
        rem = remediation(state)
        if rem is not None:
            rnd, total = rem
            colour = RED if rnd >= total else YELLOW
            part += f" {colour}↻{rnd}/{total}{RESET}"
        return part
    if phase == "closeout":
        return f"{GREEN}✔ close-out{RESET}"
    if phase == "blocked":
        note = blocker_note(state)
        note = clip(plain(note), NOTE_WIDTH)
        return f"{RED}✘ blocked{RESET}" + (f" {DIM}{note}{RESET}" if note else "")
    if phase == "handoff":
        # A deliberate stop at a gate on a context-usage.py `handoff` verdict, not
        # a failure -- hence YELLOW, not blocked's RED. `reason` is that script's
        # `reason:` text verbatim, bounded exactly like the blocked note.
        reason = clip(plain(blocker_note(state) if state.get('schema_version')==2 else state.get("reason") or ""), NOTE_WIDTH)
        return f"{YELLOW}⏸ HANDOFF{RESET}" + (f" {DIM}{reason}{RESET}" if reason else "")
    task = state.get("task")
    desc = state.get("task_desc")
    desc = clip(plain(desc), NOTE_WIDTH)
    if isinstance(task, str) and TASK_ID_RE.match(task):
        label = f"T{task} "
    else:
        # Everything that is not a schema-shaped "N.M" loses only the LABEL.
        # A value such as `"task": "close-out: example review passes still
        # running"` (invented) is one a run can write; interpolated raw it
        # puts a sentence where `T3.1` belongs and pushes every other bar off the
        # line, so it is dropped. But `task_desc` is free text BY SCHEMA and is
        # not implicated by a malformed sibling field — returning "" here would
        # discard a perfectly good desc and contradict the `task is None` case two
        # lines up, where the same desc is kept. One rule: a bad `task` costs the
        # `T…` label, nothing else.
        label = ""
    if not label and not desc:
        return ""       # nothing to say -- the bare glyph was noise, not data
    # The separator between label and desc belongs BETWEEN them, not welded to
    # the label: with no desc a welded separator leaves a trailing space inside
    # the phase part, which shows once a marker follows it ("T1.3  ⚠").
    sep = " " if (label and desc) else ""
    return f"{GREEN}▶ {label.rstrip()}{sep}{RESET}{desc}"


def remediation(state):
    """(round, budget) when a remediation round is recorded, else None."""
    rnd = state.get("remediation_round")
    # `type(... ) is int`, not isinstance: bool subclasses int, so a malformed
    # `"remediation_round": true` would otherwise render as round 1.
    if type(rnd) is not int or rnd <= 0:
        return None
    budget = state.get("remediation_budget")
    # The fallback duplicates the default stated in ../SKILL.md ("Remediation
    # budget — default 2 rounds per gate"); test-gate-remediation-contract.py
    # asserts the two stay equal, so change both or neither.
    total = budget if type(budget) is int and budget > 0 else DEFAULT_REMEDIATION_BUDGET
    return rnd, total


def staleness(state):
    hours = stale_hours(state)
    return f" {DIM}(stale {hours}h){RESET}" if hours is not None else ""


def stale_hours(state):
    """Whole hours since `updated` when that is STALE_AFTER_H or more, else None."""
    upd = state.get("updated")
    if not upd:
        return None
    try:
        ts = datetime.datetime.fromisoformat(upd.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    # AttributeError covers a non-string `updated` (a number, a list) reaching
    # .replace(); the parse guard is total, so no junk in this optional field
    # can cost the bar.
    #
    # A date-only `updated` ("2026-08-29") parses fine but lands OFFSET-NAIVE,
    # and subtracting it from an aware now() raises TypeError -- which the
    # ValueError guard above does not catch. That exception would reach render()'s
    # per-line `except Exception: continue`, so one out-of-contract field would
    # silently delete the PINNED bar while every other plan's bar (which never
    # calls this function) kept rendering: a master bar visible with the
    # sub-plan actually being executed missing.
    # Assume UTC, which is what the field is documented to carry.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    age = datetime.datetime.now(datetime.timezone.utc) - ts
    hours = age.total_seconds() / 3600
    if hours >= STALE_AFTER_H:
        return int(hours)
    return None


LAG_TOLERANCE = 1   # tasks; one is a task in flight, two is a stall
# ../SKILL.md § Step 3.5 states this number in prose; the contract suite asserts
# the two are equal. ONE copy in this file — the renderer's fallback and
# --budget-check's ceiling are the same rule, and two literals would let the bar
# and the stop disagree about when a budget is spent.
DEFAULT_REMEDIATION_BUDGET = 2
# `Dispatch: YES|NO` is the task field; `Parallel:` is its old spelling, which
# existing plans keep forever, so both are read.
DISPATCH_YES_RE = re.compile(r"^\s*-\s*\*\*(?:Dispatch|Parallel):\*\*\s*YES\b", re.I)


def status_lag(state, text, plan_path):
    """` ⚠ status lag N` when the plan file trails the live run, else "".

    `Status` flips can stop mid-plan: tasks keep completing and the markers
    stop moving. The RULE is not what is missing (Step 3.3 rule 5 says flip it
    in the same change as the work); the SIGNAL is. Everything else that could
    notice fires after the fact: a later
    plan-status sweep classifies finished-but-unmarked plans, and a
    flip audit catches the bulk catch-up flip a stall eventually produces. Both
    report damage already in the file.

    Both artifacts are already maintained at every transition. This function
    only notices that they disagree, and says so while the run is still going.

    LAG counts the SEQUENTIAL tasks between the last marker that moved (`[x]` or
    `[~]`) and the task the state file names, plus the current one. `Dispatch:
    YES` siblings (old spelling `Parallel: YES`, still accepted) are excluded:
    they are dispatched together and do not finish in document order, so an
    unmarked one is concurrency the plan asked for.

    NOT extended to master plans, deliberately. The state-file contract
    (`../references/progress-state-file.md`) says a master's state file always
    points at the SUB-PLAN currently executing, so a master's own register is
    never the file this function reads. Branching on is_master_plan() would
    need a test for a state shape the contract says cannot occur — green, and
    measuring nothing. A master register that stops
    being flipped is still undetected here; that is a real residual, recorded
    rather than papered over, and it needs a different mechanism because the
    register flip happens at a sub-plan close-out, outside any task transition. Silent when the state names no task, when the task is not found in the
    plan, or when nothing is flipped yet and the run is still in the first
    couple of tasks.
    """
    lag, missing = lag_of(state, text)
    if missing:
        return f" {RED}⚠ not in plan{RESET}"
    if lag is None:
        return ""
    return f" {YELLOW}⚠ status lag {lag}{RESET}"


def lag_of(state, text):
    """(lag, not_in_plan) — status_lag()'s finding as data, for both outputs.

    lag is the task count when it exceeds LAG_TOLERANCE, else None;
    not_in_plan is True when the state names a task the plan does not have.
    """
    cur = state.get("task")
    if not isinstance(cur, str) or not cur.strip():
        return None, False
    cur = cur.strip()
    # A `task` that is not schema-shaped is phase_part()'s problem, not a lag
    # signal: it already drops the label for exactly these values. Reporting
    # them here would paste a prose `task` back into the bar.
    if not TASK_ID_RE.match(cur):
        return None, False
    order, last_marked = [], -1
    for line in text.splitlines():
        tm = pu.TASK_RE.match(line)
        if tm:
            order.append({"num": tm.group(1), "state": None, "parallel": False})
            continue
        if not order:
            continue
        sm = pu.STATUS_RE.match(line)
        if sm and order[-1]["state"] is None:
            order[-1]["state"] = pu.status_state(sm.group(1))
        elif DISPATCH_YES_RE.match(line):
            order[-1]["parallel"] = True
    # Measured from the last marker that MOVED, not the last `[x]`. The lag is
    # about markers that stop moving, and `[~]` is a marker that moved — warning
    # on a correctly in-flight task would be a false positive against the very
    # state the contract defines to express it.
    for i, t in enumerate(order):
        if t["state"] in ("done", "partial"):
            last_marked = i
    if not order:
        # No heading this parser recognises — `#### Task N.M`, an em-dash form,
        # a suffixed id. Such headings exist in real plans, and some plans
        # have nothing but. The state file is not diverging from those plans;
        # THIS parser cannot read them, and saying "not in plan" about a task
        # sitting in the file the user is looking at is a warning that teaches
        # the reader to distrust the next one.
        return None, False
    try:
        cur_i = [t["num"] for t in order].index(cur)
    except ValueError:
        # NOT folded into the silent cases. The state naming a task the plan no
        # longer has is a WORSE divergence than an ordinary lag — the plan was
        # edited under a run whose markers had already stopped — and silence
        # would make it indistinguishable from nothing to report.
        return None, True
    # `Dispatch: YES` siblings (or the old `Parallel: YES`) are dispatched
    # together and do not finish in document order, so an unmarked one between
    # the last marker and the current task is the format's own first-class
    # concurrency, not a stall. Counting it
    # would make the warning fire on sanctioned behaviour — and a signal that cries
    # wolf on the thing the plan told it to expect is worse than the silence it
    # replaces, because it teaches the reader to ignore it.
    gap = [t for t in order[last_marked + 1:cur_i] if not t["parallel"]]
    lag = len(gap) + 1
    if lag <= LAG_TOLERANCE:
        return None, False
    return lag, False


def pinned_plan_path(state, state_file):
    """The absolute path of the plan a state file names.

    A relative `plan` is anchored to the REPO ROOT (.claude's parent), never to
    the process cwd — the statusline runs from wherever the user happens to be.
    This is a shared helper rather than inline code because two places must
    agree: if render() re-parsed `state["plan"]` itself and kept it relative,
    both discover_plans()'s exclusion and render()'s own post-filter would
    resolve it against the OS cwd. The pinned plan would then fail to match
    itself and render twice — once with its phase part, once as a discovered
    stranger — whenever a relative `plan` points inside the discovered plans
    directory, which is exactly the shape of the `docs/plans` fallback. It would
    also burn a MAX_BARS slot that a genuinely different plan should have.
    """
    plan = Path(state["plan"])
    if not plan.is_absolute():
        plan = state_file.parent.parent / plan
    return plan


def _bar_line(name, done, total, colour, width):
    """`⚙ <name padded> <bar> <done>/<total> (<pct>%)` — the shared opening.

    Shared because render_pinned() and render_other() both open with it,
    differing only in the colour and in the tail one of them appends. Two
    copies would have to be edited in lockstep — the lockstep-drift shape
    rule_signature()'s own docstring names as the class it exists to prevent,
    one layer up. Two callers, one definition.

    `width > 0`, NOT `if width:` — a tree-prefixed child gets
    `width - visible_len(prefix)`, which is NEGATIVE when the caller fell back
    to width=0, and a negative width is truthy. clip() then returns "" and
    ljust() does nothing, so the line would render a complete, correctly-numbered
    bar with an EMPTY NAME: a wrong bar rather than a missing one, which is the
    single outcome render() says it exists to avoid.

    THIS guard is the load-bearing one, and the suite pins it directly (revert
    it to `if width:` and the -3/-1 cases fail). render()'s call site also
    clamps, which is redundant given this line -- verified by mutation, removing
    the clamp fails nothing -- and is kept only so the negative case is visible
    where it arises rather than only where it is absorbed.
    """
    if width > 0:
        name = clip(name, width).ljust(width)
    out = f"{colour}⚙ {name}{RESET} "
    if total:
        pct = done * 100 // total
        out += f"{bar(done, total)} {done}/{total} {DIM}({pct}%){RESET}"
    return out


def blocked_gate_marker(text, plan_path=None):
    """` ⊘ GATE BLOCKED` when any stage-gate check in the plan is `[~]`, else "".

    A property of the PLAN, not of the phase, so it renders whether or not this
    session is the one executing — a plan whose gate could not be run is blocked
    for whoever looks at it next, and the bar is often the only place anyone
    looks. Appended rather than woven into the counts: the task counts are about
    tasks and stay honest; without this a plan reads as finished because
    nothing on the line speaks for the gate.

    Reads the contract through lib/plan_parser.py, like every other marker here.

    NAMED `GATE BLOCKED`, not `BLOCKED`, because phase_part() already renders
    `✘ blocked <note>` in the same colour on the same line for a different
    subject — an execution this session has STOPPED, versus a gate check that
    could not be proven, possibly in an earlier session. Both can appear at
    once. gate_item_state() argues for not sharing vocabulary with
    status_state()'s `partial`; the same care is owed to this file's own
    vocabulary one screen away.
    """
    return f" {RED}⊘ GATE BLOCKED{RESET}" if pu.plan_blocked(text, plan_path)[0] else ""


STAGE_DEPS_RE = re.compile(r"^\*\*Depends on:\*\*\s*(.*)$")
_VD = None


def _stage_refs(value):
    """validate-dispatch.py's `stage_refs()`, loaded on first use.

    One parser for a stage's `Depends on:` value, not two: real plans write
    `Stages 1–3`, `Stages 2 and 3`, parentheticals and a `**Blocks:**` on the
    same line, and that function already reads all of them. Loaded lazily so a
    redraw with no stage in the state file never pays for it.
    """
    global _VD
    if _VD is None:
        path = Path(__file__).resolve().parents[2] / "planning-projects" / "scripts" / "validate-dispatch.py"
        spec = importlib.util.spec_from_file_location("validate_dispatch", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _VD = mod
    return _VD.stage_refs(value)


def unpassed_dependencies(text, stage):
    """Stage numbers `stage` depends on whose gate is not fully `[x]`.

    Without it a stage can close before the gate it depends on although it
    reads `Depends on: Stage 3 gate`: if nothing parses a stage-level
    `**Depends on:**`, the field is decoration.

    The dependency line is the one between `## Stage N` and its first `###`
    heading — a task's `- **Depends on:**` is a list item and never matches.
    A gate passes only when it has at least one check and every check is
    `[x]`: an open `[ ]` and a BLOCKED `[~]` both fail it, and a dependency
    with no gate checks at all is unproven, not passed.
    """
    deps, gates = set(), {}
    cur, in_head, gate = None, False, None
    for line in text.splitlines():
        m = pu.STAGEHDR_RE.match(line)
        if m and not line.startswith("###"):
            cur, in_head, gate = int(m.group(1)), True, None
            continue
        if line.startswith("#"):
            in_head = False
            g = pu.GATEHDR_RE.match(line)
            gate = int(g.group(1)) if g else None
            if gate is not None:
                gates.setdefault(gate, [])
            continue
        if in_head and cur == stage:
            d = STAGE_DEPS_RE.match(line.strip())
            if d:
                deps.update(_stage_refs(d.group(1)))
        if gate is not None:
            item = pu.GATE_ITEM_RE.match(line)
            if item:
                gates[gate].append(pu.gate_item_state(item.group(1)))
    deps.discard(stage)
    return sorted(n for n in deps
                  if not gates.get(n) or any(s != "done" for s in gates[n]))


def stage_order_marker(state, text):
    """` ⊘ STAGE ORDER` when the state file's stage depends on an unpassed gate.

    Blank if the parser cannot load: a redraw must never fail, and
    `--stage-order-check` — the gate — exits 2 on the same failure.
    """
    return f" {RED}⊘ STAGE ORDER{RESET}" if stage_order_broken(state, text) else ""


def stage_order_broken(state, text):
    """Whether stage_order_marker() shows — the state's stage depends on a gate
    that is not fully `[x]`. False wherever the marker is blank."""
    stage = state.get("stage")
    if not isinstance(stage, int) or isinstance(stage, bool):
        return False
    try:
        bad = unpassed_dependencies(text, stage)
    except Exception:
        return False
    return bool(bad)


def render_pinned(state_file, state=None, width=0, label=None, text=None):
    """The one line for the plan the state file names.

    Kept as its own function, taking the state file rather than a plan path,
    because its output is pinned byte-for-byte by a golden of the one-plan
    output. render() below composes it with the rest.

    `text` lets the caller pass the plan's contents it has already read.
    group_plans() reads every chosen plan to work out the master/child
    structure, so without it each chosen file (up to MAX_BARS non-masters plus every open master) would be read TWICE per
    redraw — passing it is free, and it closes a (tiny) window where the
    two reads could disagree about the same file.

    The line itself is built by pinned_row(), which also returns the same
    figures as data for `--json`.
    """
    return pinned_row(state_file, state, width=width, label=label, text=text)["line"]


def _group_fields(name, plan, done, total, role, gate_mark):
    """A `--json` group, every phase-part field null until a pinned row fills it."""
    return {"name": name, "plan": str(plan), "id": plan_id(plan),
            "done": done, "total": total, "role": role, "depth": 0, "gate_blocked": bool(gate_mark),
            "stage": None, "stage_count": None, "task": None, "phase": None,
            "stale_hours": None, "remediation_round": None,
            "remediation_budget": None, "blocked_note": None,
            "status_lag": None, "task_not_in_plan": None, "stage_order": None}


def execution_module():
    spec = importlib.util.spec_from_file_location('execution_state',
              Path(__file__).resolve().with_name('plan_state.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def projection_state(state_file):
    """Legacy display is compatible; owned/versioned display must validate."""
    module = execution_module()
    try:
        owner = module.owner_of(repo_root_of(state_file))
    except Exception:
        owner = None  # compatible legacy display outside a registered Git run
    owned = False
    if owner is not None:
        try:
            owned = module.read_pointer(owner) is not None
        except Exception as exc:
            raise ValueError('state_error: invalid execution discovery metadata') from exc
    if owned:
        outcome = module.result(repo_root_of(state_file), 'show', {})
        if outcome['status'] != 'ok':
            raise ValueError('state_error: ' + outcome.get('message', outcome['status']))
        return outcome['state']
    # No run pointer: keep the legacy renderer's silence for unusable legacy
    # files. A parsed version marker still requires the shared owned reader.
    state = json.loads(state_file.read_text())
    if isinstance(state, dict) and 'schema_version' in state:
        outcome = module.result(repo_root_of(state_file), 'show', {})
        if outcome['status'] != 'ok':
            raise ValueError('state_error: ' + outcome.get('message', outcome['status']))
        return outcome['state']
    return state


def missing_projection_error(cwd):
    """A run pointer survives snapshot loss; no Git run remains ordinary idle."""
    try:
        probe = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode == 0:
            outcome = execution_module().result(probe.stdout.strip(), 'show', {})
            if outcome['status'] == 'state_error':
                return 'state_error: ' + outcome.get('message', 'invalid execution snapshot')
    except Exception:
        pass
    return None


def pinned_row(state_file, state=None, width=0, label=None, text=None):
    """{"line", "fields", "text", "path"} for the pinned plan.

    `line` is render_pinned()'s line and `fields` its `--json` group. Both come
    from one read of the plan, and done/total/stage count from one
    parse_plan() call. The markers then re-scan that same text, once each, and
    each JSON marker field comes from the same helper as its text marker.
    """
    if state is None:
        state = projection_state(state_file)
    plan = pinned_plan_path(state, state_file)
    if text is None:
        text = plan.read_text(errors="ignore")
    done, total, stage_count = parse_plan(text, plan)
    name = label if label is not None else plan_name(plan)
    gate_mark = blocked_gate_marker(text, plan)
    bar_line = _bar_line(name, done, total, CYAN, width)
    out = bar_line + gate_mark

    # Built as a list so the ` · ` separator is emitted only when something
    # actually follows it. Appended unconditionally before a possibly-empty
    # phase, it would leave a dangling "(100%) · " for a file this renderer
    # cannot read.
    tail = []
    pos = stage_position(state, stage_count)
    if pos:
        tail.append(f"S{pos[0]}/{pos[1]}")
    part = phase_part(state)
    if part:
        tail.append(part)
    if state.get('schema_version')==2 and state.get('qualification') in ('no_go','blocked'):
        tail.append('qualification '+state['qualification'])
    if tail:
        if total:
            out += f" {DIM}·{RESET} "
        out += " ".join(tail)
    out += status_lag(state, text, plan)
    out += stage_order_marker(state, text)
    out += staleness(state)

    fields = _group_fields(name, plan, done, total, "pinned", gate_mark)
    # Everything the line shows after its bar, as plain text: a front end that
    # draws its own bar (the Claude Code band) shows this verbatim rather than
    # re-deriving the phase part and markers.
    fields["tail"], fields["tail_spans"] = tail_parts(out[len(bar_line):])
    fields["stage"], fields["stage_count"] = stage_pair(state, stage_count)
    task = state.get("task")
    fields["task"] = task if isinstance(task, str) and TASK_ID_RE.match(task) else None
    phase = state.get("phase", "task")
    fields["phase"] = phase if isinstance(phase, str) and phase in KNOWN_PHASES else None
    fields["stale_hours"] = stale_hours(state)
    # The RECORDED round, whatever the phase -- what --budget-check reads. The
    # text shows it inside the gate phase only.
    rem = remediation(state)
    if rem is not None:
        fields["remediation_round"], fields["remediation_budget"] = rem
    if fields["phase"] == "blocked":
        # Unclipped: the text cuts it to NOTE_WIDTH, the JSON has no column.
        fields["blocked_note"] = plain(blocker_note(state)) or None
    fields["status_lag"], fields["task_not_in_plan"] = lag_of(state, text)
    # true exactly when the text shows ` ⊘ STAGE ORDER`; never null on a pinned
    # group, always null on the others (they have no state to read a stage from).
    fields["stage_order"] = stage_order_broken(state, text)
    return {"line": out, "fields": fields, "text": text, "path": plan}


def render_other(plan_path, width=0, label=None, text=None):
    """A bar line for a discovered plan that is NOT the one being executed.

    No phase part and no staleness marker: those describe an execution this
    session is driving, and nothing is driving these. Here that distinction
    falls out of not having a state to read.
    """
    return other_row(plan_path, width=width, label=label, text=text)["line"]


def other_row(plan_path, width=0, label=None, text=None):
    """{"line", "fields", "text", "path"} for a discovered plan — see render_other()."""
    if text is None:
        text = _read_plan(plan_path)
    done, total, _ = parse_plan(text, plan_path)
    name = label if label is not None else plan_name(plan_path)
    gate_mark = blocked_gate_marker(text, plan_path)
    role = "master" if pu.is_master_plan(text, plan_path) else "other"
    fields = _group_fields(name, plan_path, done, total, role, gate_mark)
    fields["tail"], fields["tail_spans"] = tail_parts(gate_mark)
    return {"line": _bar_line(name, done, total, DIM, width) + gate_mark,
            "fields": fields, "text": text, "path": plan_path}


STAGE_NAME_RE = re.compile(r"^##\s+Stage\s+\d+\s*(?:[:—–-]\s*)?(.*?)\s*$", re.I)


def plan_detail(text, path):
    """The pinned plan's stages, each with its gate tally and its tasks.

    Same contract readers as the bar: pu.STAGEHDR_RE / TASK_RE / STATUS_RE /
    GATEHDR_RE / GATE_ITEM_RE, and a task's `status` is pu.status_state()'s
    word for its first Status line (`done`, `partial`, `open`), or null when it
    has none the contract recognises. Tasks above the first `## Stage` heading
    (a light plan has none) go in a stage whose number and name are null.
    """
    stages, by_num, gates = [], {}, {}
    cur, task, gate = None, None, None
    for line in text.splitlines():
        sh = pu.STAGEHDR_RE.match(line)
        if sh:
            num = int(sh.group(1))
            task, gate = None, None
            # A heading repeating a stage number (`## Stage 1 Gate Report`, a
            # re-run's) is that stage's, as parse_plan() counts stages as a set.
            if num in by_num:
                cur = by_num[num]
                continue
            nm = STAGE_NAME_RE.match(line)
            cur = {"number": num, "name": plain(nm.group(1) if nm else "") or None,
                   "gate_checked": 0, "gate_total": 0, "tasks": []}
            stages.append(cur)
            by_num[num] = cur
            continue
        if line.startswith("#"):
            gate = None
            g = pu.GATEHDR_RE.match(line)
            if g:
                gate = int(g.group(1))
                gates.setdefault(gate, [])
                task = None
                continue
        tm = pu.TASK_RE.match(line)
        if tm:
            if cur is None:
                cur = {"number": None, "name": None,
                       "gate_checked": 0, "gate_total": 0, "tasks": []}
                stages.append(cur)
            task = {"id": tm.group(1), "title": plain(tm.group(2)).strip(), "status": None}
            cur["tasks"].append(task)
            continue
        if line.startswith("#"):
            task = None
            continue
        if gate is not None:
            item = pu.GATE_ITEM_RE.match(line)
            if item:
                gates[gate].append(pu.gate_item_state(item.group(1)))
            continue
        sm = pu.STATUS_RE.match(line)
        if sm and task is not None and task["status"] is None:
            task["status"] = pu.status_state(sm.group(1))
    for num, items in gates.items():
        if num in by_num:
            by_num[num]["gate_checked"] = sum(s == "done" for s in items)
            by_num[num]["gate_total"] = len(items)
    return {"plan": str(path), "name": plan_name(path), "stages": stages}


def build_model(cwd, with_detail=False):
    """THE model: {"groups": [row, ...], "detail": dict|None, "details": dict}.

    Both outputs are read off it -- render() takes each row's `line`,
    `--json` takes each row's `fields` -- so the text bars and the JSON groups
    come from one discovery, one grouping and one read per plan, and cannot
    disagree about which plans there are or what they count.

    `detail` is the pinned plan's stage/task breakdown. It is built only when
    `with_detail` asks for it, so a statusline redraw never pays for a scan
    it would throw away. It is None otherwise, and None when no pinned bar
    rendered. `details` is the same breakdown for every row, keyed by its `id`,
    built from the text each row already read (no extra file read); a row whose
    breakdown cannot be built maps to None. Also only under `with_detail`.

    Every step degrades to "fewer rows", never to an exception -- see render().
    """
    state_file = find_state(cwd)
    state = pinned = None
    state_error = None
    if state_file is None:
        # find_state cannot discover a deleted owned snapshot. The common-dir
        # run pointer distinguishes that interruption from an idle repository.
        state_error = missing_projection_error(cwd)
        if state_error:
            print(state_error, file=sys.stderr)
    if state_file is not None:
        try:
            # ONE read, one anchoring. Re-reading to recompute `pinned` would
            # race executing-plans' overwrite-not-patch state writes: a rewrite
            # landing between the two reads would make the second one fail and
            # silently disable dedup for that redraw.
            state = projection_state(state_file)
            pinned = pinned_plan_path(state, state_file)
        except Exception as exc:
            if 'state_error:' in str(exc):
                state_error = str(exc)
                print(state_error, file=sys.stderr)
            state = pinned = None   # an unreadable state file pins nothing

    chosen = []
    try:
        root = repo_root_of(state_file) if state_file is not None else Path(cwd)
        plans_dir = records_plans_dir(root)
        if plans_dir is not None:
            cache = root / ".claude" / CACHE_NAME
            chosen = discover_plans(plans_dir, pinned=pinned, cache_file=cache)
    except Exception:
        chosen = []                 # discovery is additive: never costs the pinned bar

    # Discovery normally returns the pinned plan itself, but it returns nothing
    # at all when the records home has no plans directory, that directory is
    # unreadable, or the scan raised. The plan this session is executing has to
    # render in every one of those cases -- it is the bar that matters most.
    if pinned is not None and _is_file(pinned) and not any(
            _same_file(p, pinned) for p in chosen):
        chosen.insert(0, pinned)

    # BAD_PATH above fixes the root cause; this bounds the blast radius of the
    # NEXT one. group_plans() is the only step between having the plans and
    # printing them, so anything it raises costs every bar at once — including
    # the pinned bar the whole function above works to preserve. Grouping is
    # decoration; losing it must cost the glyphs, never the lines.
    try:
        grouped = group_plans(chosen, pinned=pinned)
    except Exception:
        grouped = [(p, "", plan_name(p), None) for p in chosen]

    # ONE width for every line, computed from the paths before anything is
    # rendered -- so a child's bar lands on the same column as its master's.
    # Cheap: plan_name() reads the filename, never the file.
    try:
        width = name_column([lab for _, _, lab, _ in grouped],
                            [pre for _, pre, _, _ in grouped])
    except Exception:
        width = 0       # unaligned bars beat no bars -- see group_plans() above

    rows, detail, details = [], None, {}
    for path, prefix, label, text in grouped:
        # `width - visible_len(prefix)` goes NEGATIVE when the width fallback
        # above fired. _bar_line() is what actually handles that (and is what
        # the suite pins); this clamp is redundant, kept so the negative case is
        # named where it arises instead of only where it is absorbed.
        avail = max(0, width - visible_len(prefix))
        # Per line, not per block: an unreadable plan costs its own bar and
        # leaves its siblings standing.
        try:
            if state is not None and pinned is not None and _same_file(path, pinned):
                row = pinned_row(state_file, state, width=avail, label=label, text=text)
                try:
                    if with_detail:
                        detail = plan_detail(row["text"], row["path"])
                except Exception:
                    detail = None   # the breakdown is extra; it never costs the bar
            else:
                row = other_row(path, width=avail, label=label, text=text)
        except Exception:
            continue
        row["line"] = prefix + row["line"]
        if prefix:
            row["fields"]["depth"] = 1
            if row["fields"]["role"] == "other":
                row["fields"]["role"] = "child"
        if with_detail:
            try:
                # The pinned row's breakdown is `detail`, already built: one parse per plan.
                pinned_row_here = row["fields"]["role"] == "pinned"
                details[row["fields"]["id"]] = (
                    detail if pinned_row_here else plan_detail(row["text"], row["path"]))
            except Exception:
                details[row["fields"]["id"]] = None   # extra; never costs the bar
        rows.append(row)
    model = {"groups": rows, "detail": detail, "details": details}
    if state_error:
        model.update(state_status='state_error', state_message=state_error)
    return model


def render(cwd):
    """Every line the status line should carry, in order — possibly none.

    The pinned plan (the one the state file names) keeps render_pinned()'s exact
    byte-for-byte output, and its group leads. Other in-flight plans for the
    same project follow, each master immediately above its own sub-plans.
    It returns a LIST rather than a string: main() prints each element on its own line, so a second bar costs a line rather
    than a rewrite.

    Every step degrades to "fewer lines", never to an exception — this is still
    the statusline. Note which corpus lane proves what: lane A (`python3
    plan-progress.py`) comes through main() into here and so exercises the
    guards in build_model(); lane B deliberately BYPASSES this function to call
    the discovery surface raw, precisely so those guards cannot mask a function
    that fails to degrade on its own. Reading lane B as evidence about this
    function's exception safety gets it exactly backwards.
    """
    return [row["line"] for row in build_model(cwd)["groups"]]


def render_json(cwd):
    """The `--json` document for `cwd`: build_model() with the lines left out.

    `groups[]` is one object per text line, in the same order. Its `role` is
    `pinned` (the state file's plan), else `master` (a master plan), else
    `child` (a sub-plan under its master's bar), else `other`; `depth` is 1
    under a tree glyph. The phase-part fields are null except on the pinned
    group. `stage_order` is a boolean: true exactly when the text shows
    ` ⊘ STAGE ORDER`. `status_lag` is the lagging task count or null, and
    `task_not_in_plan` is the text's ` ⚠ not in plan`. `tail` is the line's
    own text after its bar, plain (no SGR, no control characters): a front end
    that draws its own bar shows it verbatim instead of re-deriving the phase
    part and markers. `tail_spans` is that text split at the line's own colour
    codes, `[{text, color, dim}]` (see tail_parts()), and `id` is a short stable
    id for the plan (plan_id()).

    The document also carries `palette`, the five role colours as hex, and
    `details`, every group's stage/task breakdown keyed by its `id`. `detail`
    stays the pinned plan's.
    """
    model = build_model(cwd, with_detail=True)
    output = {"groups": [row["fields"] for row in model["groups"]],
                       "detail": model["detail"], "details": model["details"],
                       "palette": palette()}
    for key in ('state_status', 'state_message'):
        if key in model:
            output[key] = model[key]
    return json.dumps(output, ensure_ascii=False)


def budget_check(cwd):
    """Read-only compatibility wrapper; plan-state owns reservation/accounting.

    Legacy positive counters are ambiguous, so require evidenced migration rather
    than diagnosing them as exhausted. Idle legacy projections stay readable.
    """
    sf = find_state(cwd)
    try:
        if sf is not None:
            state = projection_state(sf)
            if not isinstance(state, dict):
                raise ValueError('state is not an object')
            if 'schema_version' not in state:
                rnd = state.get('remediation_round')
                if rnd is None and 'remediation_round' not in state:
                    return 0  # labeled legacy compatibility, not mutation authority
                print('state_error: legacy round requires evidenced migration', file=sys.stderr)
                return 3
        module = execution_module()
        if sf is None:
            probe = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                                   capture_output=True, text=True, timeout=10)
            if probe.returncode != 0:
                return 0  # no_active_plan outside a Git run
        outcome = module.budget_result(cwd)
        if outcome['status'] not in ('ok', 'no_active_plan'):
            print(outcome['status'] + ': ' + outcome.get('message', ''), file=sys.stderr)
        return module.EXITS[outcome['status']]
    except Exception as exc:
        print('state_error: cannot read execution state (' + type(exc).__name__ + ')', file=sys.stderr)
        return 3


ROSTER_ITEM_RE = re.compile(r"^\s*- \[.\] .*Dispatch roster")
# Any list item ends the roster, not only a checkbox: a plain `- **Probe results:**`
# bullet after it that names another task would otherwise count as rostered.
ROSTER_END_RE = re.compile(r"^\s*(- |#)")
ROSTER_COUNT_RE = re.compile(r"\b(\d+)\s+of\s+\d+\s+tasks\b|\b(0)\s+tasks\b")
TASK_REF_RE = re.compile(r"\bTask\s+(\d+\.\d+)\b")
# A commit belongs to the task its subject OPENS with (`Stage 4 Task 4.1: …`).
# A task named later in the subject is a cross-reference, and counting it would
# let one task's `dispatched` trailer reconcile another it merely mentions.
COMMIT_TASK_RE = re.compile(r"^(?:Stage\s+\d+\s+)?Task\s+(\d+\.\d+)\b")
AUTHORISED_INLINE = "inline (user authorised)"
# The routing table's own inline route, `Executor: inline (routing table — no <stack>
# agent on this host)`: a routing outcome accepted at Preflight, not a deviation, so it
# reconciles, and is counted as its own term, never as dispatched. Inert on a host whose
# table always names an agent, so one script serves every host.
TABLE_ROUTED_INLINE = "inline (routing table"


def roster_body(text):
    """Preflight's `Dispatch roster` item as one line, or None.

    The item wraps across continuation lines, so it runs until the next
    list item (checkbox or not), a heading, or a blank line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not ROSTER_ITEM_RE.match(line):
            continue
        item = [line]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or ROSTER_END_RE.match(nxt):
                break
            item.append(nxt)
        return " ".join(item)
    return None


def parse_roster(text):
    """(count, [task ids]) from Preflight's `Dispatch roster` item, or None."""
    body = roster_body(text)
    if body is None:
        return None
    m = ROSTER_COUNT_RE.search(body)
    count = int(m.group(1) or m.group(2)) if m else None
    return count, list(dict.fromkeys(TASK_REF_RE.findall(body)))


# A roster entry routing a task inline by the table: `Task 4.2 → inline (routing table …`.
ROSTER_INLINE_RE = re.compile(r"\bTask\s+(\d+\.\d+)\s*(?:→|->)\s*`?inline \(routing table")


def dispatch_check(args):
    """Exit status for `--dispatch-check <plan> [--since <ref>]`: 0 when every
    rostered task is reconciled, 2 otherwise.

    Reconciling Preflight's roster by reading trailers and writing prose permits
    one failure: a rostered task run inline under a bare `Executor: inline`, and
    a close-out that reports the plan done. Reconciled means ANY of the task's commits carries a
    `dispatched …` trailer or the explicit `inline (user authorised)`; an empty
    trailer is `unknown`, never `inline`. Every failure path — unreadable plan,
    not a git repo, bad ref — is a FAIL: line and exit 2, never a silent 0.
    """
    def fail(msg):
        print(f"FAIL: {msg}", file=sys.stderr)
        return 2

    rest = args[args.index("--dispatch-check") + 1:]
    since = None
    if "--since" in rest:
        j = rest.index("--since")
        if j + 1 >= len(rest):
            return fail("--since needs a ref")
        since = rest[j + 1]
        del rest[j:j + 2]
        if since.startswith("-"):
            return fail(f"bad --since ref: {since}")
    if not rest:
        return fail("usage: plan-progress.py --dispatch-check <plan> [--since <ref>]")
    plan = rest[0]
    try:
        text = Path(plan).read_text()
    except BAD_PATH as e:
        return fail(f"cannot read plan {plan}: {e}")

    roster = parse_roster(text)
    if roster is None:
        return fail(f"roster missing — no `Dispatch roster` item in {plan}")
    count, ids = roster
    # A table-routed trailer reconciles only a task the roster itself routed inline:
    # the routing outcome is accepted at Preflight, never claimed afterwards.
    table_inline = set(ROSTER_INLINE_RE.findall(roster_body(text) or ""))
    if count is None:
        return fail("roster count unreadable — expected `<n> of <m> tasks` or `0 tasks`")
    if count == 0:
        print("dispatch: 0 of 0 rostered tasks dispatched")
        return 0
    if count != len(ids):
        return fail(f"roster says {count} tasks but lists {len(ids)} task ids")

    rng = f"{since}..HEAD" if since else "HEAD"
    try:
        r = subprocess.run(
            ["git", "log", "--format=%s%x1f%(trailers:key=Executor,valueonly,unfold)%x1e", rng],
            capture_output=True, text=True)
    except OSError as e:
        return fail(f"cannot run git: {e}")
    if r.returncode != 0:
        why = (r.stderr.strip().splitlines() or ["git log failed"])[0]
        return fail(f"git log {rng}: {why}")

    seen = {}  # task id -> list of Executor values across its commits
    for rec in r.stdout.split("\x1e"):
        if "\x1f" not in rec:
            continue
        subject, trailer = rec.split("\x1f", 1)
        values = [v.strip() for v in trailer.splitlines() if v.strip()] or ["unknown"]
        m = COMMIT_TASK_RE.match(subject.strip())
        if m:
            seen.setdefault(m.group(1), []).extend(values)

    dispatched = 0
    table_routed = 0
    unreconciled = []
    for tid in ids:
        values = seen.get(tid)
        if not values:
            unreconciled.append((tid, f"no commit in {rng}"))
            continue
        if any(v.startswith("dispatched") for v in values):
            dispatched += 1
        elif tid in table_inline and any(v.startswith(TABLE_ROUTED_INLINE) for v in values):
            table_routed += 1
        elif AUTHORISED_INLINE not in values:
            unreconciled.append(
                (tid, "Executor: " + ", ".join(dict.fromkeys(values))))
    for tid, why in unreconciled:
        print(f"FAIL: Task {tid} — rostered Dispatch: YES, not reconciled ({why})",
              file=sys.stderr)
    tail = f"; {table_routed} table-routed inline" if table_routed else ""
    print(f"dispatch: {dispatched} of {count} rostered tasks dispatched{tail}")
    return 2 if unreconciled else 0


def stage_order_check(cwd, args=()):
    """Exit status for `--stage-order-check [--stage N] [--plan <path>]`: 0 when the
    stage may open, 2 when a stage it depends on has a gate that is not fully `[x]`.

    Run at stage open, before the stage's first task — and so BEFORE the state file
    moves to it. `--stage N` names the stage being opened; without it the check reads
    the file's `stage`, which at that moment is the stage already running (so the check
    would pass a Stage 4 opened over an open Stage 3 gate). `--plan` names the plan when there is no state file to read it from.

    Without `--stage`, silent 0 where no stage is open — no state file, or no `stage`.
    With `--stage`, the caller asked about a specific stage, so a plan that cannot be
    found or read exits 2: an unreadable plan cannot prove the order holds.
    """
    args = list(args)

    def opt(name):
        if name not in args:
            return None
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else ""

    stage_arg, plan_arg = opt("--stage"), opt("--plan")
    state, sf = {}, find_state(cwd)
    if sf is None:
        error = missing_projection_error(cwd)
        if error:
            print(error, file=sys.stderr)
            return 3
    if sf is not None:
        try:
            state = projection_state(sf)
        except (OSError, ValueError) as e:
            print(f"FAIL: cannot read {sf}: {e}", file=sys.stderr)
            return 3 if 'state_error:' in str(e) else 2
        if not isinstance(state, dict):
            state = {}
    if stage_arg is not None:
        try:
            stage = int(stage_arg)
        except ValueError:
            print(f"FAIL: --stage takes a stage number (got {stage_arg!r})", file=sys.stderr)
            return 2
    else:
        stage = state.get("stage")
        if not isinstance(stage, int) or isinstance(stage, bool):
            return 0
    if plan_arg:
        plan = Path(plan_arg)
    elif state.get("plan") and sf is not None:
        plan = pinned_plan_path(state, sf)
    elif stage_arg is not None:
        print("FAIL: no plan to read — pass --plan or write the state file first",
              file=sys.stderr)
        return 2
    else:
        return 0
    try:
        text = plan.read_text(errors="ignore")
    except BAD_PATH as e:
        print(f"FAIL: cannot read plan {plan}: {e}", file=sys.stderr)
        return 2
    bad = unpassed_dependencies(text, stage)
    for n in bad:
        print(f"FAIL: Stage {stage} depends on Stage {n}, whose gate is not fully [x]",
              file=sys.stderr)
    return 2 if bad else 0


def main():
    if "--budget-check" in sys.argv[1:]:
        sys.exit(budget_check(os.getcwd()))
    if "--stage-order-check" in sys.argv[1:]:
        try:
            status = stage_order_check(os.getcwd(), sys.argv[1:])
        except Exception as e:
            print(f"FAIL: --stage-order-check crashed: {e!r}", file=sys.stderr)
            status = 2
        sys.exit(status)
    if "--dispatch-check" in sys.argv[1:]:
        # Its own handler: the bottom-of-file one exits 0, and a gate that
        # crashes must never read as a gate that passed.
        try:
            status = dispatch_check(sys.argv[1:])
        except Exception as e:
            print(f"FAIL: --dispatch-check crashed: {e!r}", file=sys.stderr)
            status = 2
        sys.exit(status)
    if "--json" in sys.argv[1:]:
        # Its own handler, not the bottom-of-file one that exits 0: a crash
        # outside build_model() -- unreadable stdin, a stdin that is not a JSON
        # object -- is a FAIL line and exit 2 rather than a silent 0. It does
        # NOT make an empty `groups` proof that nothing is in flight:
        # build_model() degrades like the text bars do, so a broken records
        # home, an unreadable state file or a plan that cannot be read costs rows
        # silently and can leave `{"groups": [], "detail": null}`.
        extra = [a for a in sys.argv[1:] if a != "--json"]
        if extra:
            print(f"FAIL: --json takes no other arguments (got {' '.join(extra)})",
                  file=sys.stderr)
            sys.exit(2)
        try:
            raw = sys.stdin.read()
            data = json.loads(raw) if raw.strip() else {}
            cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or "."
            out = render_json(cwd)
        except Exception as e:
            print(f"FAIL: --json crashed: {e!r}", file=sys.stderr)
            sys.exit(2)
        print(out)
        sys.exit(0)
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or "."
    for line in render(cwd):
        print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A statusline must never print a traceback — blank line beats noise.
        # SystemExit is not an Exception, so --budget-check's status survives
        # this handler; that is load-bearing, not incidental.
        sys.exit(0)
