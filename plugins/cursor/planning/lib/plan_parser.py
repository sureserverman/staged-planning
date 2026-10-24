#!/usr/bin/env python3
"""plan_parser — the one plan-format contract every script reads plans through.

Pure functions and compiled regexes, stdlib only, no I/O on import. Scripts load it by
file path from the plugin root (`<root>/lib/plan_parser.py`) rather than restating any
regex here, because a change to one of these patterns changes done/total math, gate
state and backlog candidates in every consumer at once; one definition means one
place to change and nothing to drift. The one function that reads files is
`plan_blocked()`, and only when called with a path (it follows a master's sub-plan
links).

What it answers:
  - the per-task Status contract: STATUS_RE, status_state(), and the markers it cannot
    read (ANY_STATUS_RE, STATUS_LINE_RE, contract_warnings())
  - master and light detection: is_master_plan(), is_light_plan(), SUBPLAN_RE and the
    two link regexes MASTER_BACKLINK_RE / SUBPLAN_LINK_RE with link_target()
  - terminal markers: **Completed:**, **Abandoned:** (plan_terminal_state()) and
    **Blocked-accepted:**, plus the gate-checkbox state (gate_item_state(),
    plan_blocked())
  - backlog candidates: parse_plan() (Status-authoritative path, else the legacy
    unchecked-bullet heuristic, plus Deferred sections on both)
  - filename stamps: plan_date(), stale_age_days()

The full rule set is documented in skills/planning-projects/references/plan-parser.md.
"""
import datetime
import re
from pathlib import Path


def plan_date(fname):
    """The filename's YYYY-MM-DD stamp, or the "0000-00-00" sentinel.

    The sentinel is right for a "was this commit later than the plan" comparison
    (every commit counts as later) and wrong for staleness; see stale_age_days().
    """
    m = re.match(r"(\d{4}-\d{2}-\d{2})", fname)
    return m.group(1) if m else "0000-00-00"


STALE_DAYS = 90


def stale_age_days(fname, today=None):
    """Days since the plan's filename date stamp, or None when the name carries no
    usable stamp: staleness unknown, never assumed.

    Deliberately not plan_date(): its sentinel would read as infinitely old here and
    mark every unstamped file stale, the opposite of the documented fallback.
    """
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", fname)
    if not m:
        return None
    try:
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:          # e.g. 2026-13-45 in a filename
        return None
    return ((today or datetime.date.today()) - d).days


TASK_RE = re.compile(r"^###\s+Task\s+(\d+\.\d+):\s*(.+)$")
STAGE_RE = re.compile(r"^##\s+Stage\s+\d+:")
GATE_RE = re.compile(r"^###\s+Stage\s+\d+\s+Gate")
DEFERRED_RE = re.compile(r"^###?\s+Deferred\s*$")
UNCHECKED = re.compile(r"^\s*-\s*\[ \]\s+(.+)$")
CHECKED = re.compile(r"^\s*-\s*\[x\]\s+", re.I)
H2 = re.compile(r"^##\s+")
SECTION = re.compile(r"^##+\s+")
HR = re.compile(r"^---\s*$")
BULLET = re.compile(r"^\s*-\s+(.+)$")
# Stage-gate acceptance criteria are not deferred work. They appear either under a
# header naming a "Gate" (### Stage N Gate, #### … Gate) or under a bold marker
# (**Stage Gate:**, **Acceptance Criteria:**) above a list of `- [ ]` checks.
GATE_WORD = re.compile(r"\bGate\b", re.I)
GATE_BOLD = re.compile(
    r"^\s*\*\*\s*(?:stage\s+)?"
    r"(?:gate|acceptance(?:\s+criteria)?|verification|exit\s+criteria|success\s+criteria)\b.*\*\*",
    re.I)
PREFLIGHT_RE = re.compile(r"^##+\s+Preflight", re.I)
# `## Decisions in force` records the constraints binding a plan. Its bullets are
# declarations, not work. The format mandates non-checkbox bullets, but a convention
# the parser does not enforce is one an author eventually breaks, and a stray `- [ ]`
# there would become a false candidate on every plan that records a decision.
DECISIONS_RE = re.compile(r"^##+\s+Decisions in force", re.I)
STAGEHDR_RE = re.compile(r"^##\s+Stage\s+(\d+)", re.I)
GATEHDR_RE = re.compile(r"^###\s+Stage\s+(\d+)\s+Gate", re.I)

# ---------------------------------------------------------------------------
# PLAN-STATUS CONTRACT. A change to this one regex silently alters done/total math
# in every consumer at once, so the reasons live here, at the owner.
#
# (a) `[~]` IS a parsed state: "partial / in flight". It counts toward TOTAL, never
#     toward DONE. Counting it done would let a plan report 100% with work
#     outstanding; leaving it out of the class would drop the task from both
#     numerator and denominator, so the plan would look smaller instead of less
#     finished. parse_plan() emits a candidate for it with signal `status-partial`,
#     distinct from `status-unexecuted`: started-and-unfinished is not never-begun.
#
#     Consumers MUST classify through status_state() and MUST NOT test
#     `group(1) != " "`: under this class that idiom reads a partial task as DONE.
#
# (b) Abandonment is a STRUCTURED marker, not a prose heuristic:
#         **Abandoned:** YYYY-MM-DD — <reason>
#     mirroring the `**Completed:**` close-out line, parsed by ABANDONED_RE.
#
#     A banner heuristic over prose like "OBSOLETE — DO NOT IMPLEMENT" would read
#     unbounded natural language, with false positives (a plan about deprecating
#     something, a quoted banner) and false negatives ("shelved", "do not build").
#     A false positive hides live work, silently. A deterministic parser must not
#     take a fuzzy signal as authoritative. ABANDON_HINT_RE detects banner prose
#     only so consumers can surface a NON-SUPPRESSING advisory.
# ---------------------------------------------------------------------------
STATUS_RE = re.compile(r"^\s*-\s*\*\*Status:\*\*\s*\[([ xX~])\]")

# Every bracketed Status marker, including the ones the contract does not recognise.
# A marker outside STATUS_RE's class matches nothing, so its task counts toward
# neither done nor total and vanishes, and its plan reads MORE finished than it is:
# the optimistic direction, and the one that gets acted on. Consumers take the
# DIFFERENCE against STATUS_RE rather than keeping a list of known-bad markers, so a
# marker nobody has invented yet is caught the day it appears.
ANY_STATUS_RE = re.compile(r"^\s*-\s*\*\*Status:\*\*\s*\[([^\]\n]*)\]")

# Terminal-state markers, anchored at column 0. ABANDONED_RE is authoritative;
# ABANDON_HINT_RE is advisory only and is consulted by no suppression decision.
ABANDONED_RE = re.compile(r"^\*\*Abandoned:\*\*\s*(.+)$", re.M)
# The close-out line executing-plans appends ("**Completed:** YYYY-MM-DD — commits:
# ..."). The `## ` alternative is a heading dialect authors also write; leaving it out
# would offer an already-closed plan as "all tasks done, no close-out line". Anchored
# at line start in both forms: a `Completed:` mid-sentence is prose.
COMPLETED_RE = re.compile(r"^(?:##\s*)?\*{0,2}Completed:\*{0,2}\s*(.+)$", re.M)

# EVERY Status line, whatever follows the colon, including ones with no bracket. A
# task written `- **Status:** done` matches neither regex above, so a plan with one
# `[x]` task and one such line would read 1/1, every task done, with a whole task
# invisible.
STATUS_LINE_RE = re.compile(r"^\s*-\s*\*\*Status:\*\*\s*(.*)$")
ABANDON_HINT_RE = re.compile(
    r"^[>#*_\s]{0,8}\b(OBSOLETE|SUPERSEDED|ABANDONED|DO NOT IMPLEMENT)\b", re.M)

# A master plan's sub-plan register entry, the counterpart of TASK_RE: a master has no
# `### Task N.N` headings, so a Status-counting consumer reads it as 0/0 unless it
# counts these.
#
# `### Sub-plan 2: Client library` -> ("2", "Client library")
#
# Authors zero-pad the number and use an em-dash as readily as a bare digit and a
# colon (`### Sub-plan 01 — Example lane`), so both match.
#
# NOT matched, deliberately: the bare-ordinal form `### 01. Foundation`. Recognising
# it needs the match scoped to the `## Sub-plans` section, because `### 01.` is too
# generic to claim anywhere in a document. contract_warnings() reports it instead.
SUBPLAN_RE = re.compile(r"^###\s+Sub-plan\s+0*(\d+)\s*[:—–-]\s*(.+)$")
# Master detection: the filename suffix or the first heading; either alone suffices.
MASTER_HEADING_RE = re.compile(r"^#\s+Master Plan:", re.M)
# Light detection, the same two signals: the `-light-plan.md` suffix or the
# `# Light Plan:` heading. The candidate parser never needs it (a Light plan is a
# Status-field plan); executing-plans and the format checks do.
LIGHT_HEADING_RE = re.compile(r"^#\s+Light Plan:", re.M)

# The two links that associate a master with its sub-plans, one per direction:
#
#   Master: ./2026-08-06-topic-master-plan.md            (sub-plan, below Date:)
#   - **Plan:** ./2026-08-06-topic-sub-01-x-plan.md      (master register entry)
#
# Both capture to end of line rather than one token, because a second written form,
# `[name.md](./name.md)`, appears on both sides; a token capture would swallow the
# whole link, resolve to nothing, and read the master as childless.
#
# NOT scoped to a section, the same posture as STATUS_RE and SUBPLAN_RE: a stray
# `Master:`-prefixed line elsewhere would group a plan under the wrong master.
MASTER_BACKLINK_RE = re.compile(r"^Master:\s*(.+?)\s*$", re.M)
SUBPLAN_LINK_RE = re.compile(r"^\s*-\s*\*\*Plan:\*\*\s*(.+?)\s*$", re.M)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def link_target(raw):
    """The path a `Master:` / `- **Plan:**` line points at, or None.

    Normalises the two written forms to one relative path. Returns None rather than a
    guess for anything else: an unresolvable link should leave a sub-plan ungrouped,
    never grouped under the wrong master.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    m = MD_LINK_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    else:
        parts = raw.split()
        raw = parts[0] if parts else ""
    return raw.strip("`<>'\" ") or None


def is_master_plan(text, path=None):
    """Whether this document is a master plan (a register of sub-plans)."""
    if path is not None and str(path).endswith("-master-plan.md"):
        return True
    return bool(MASTER_HEADING_RE.search(text))


def is_light_plan(text, path=None):
    """Whether this document is a Light plan (one stage, a few tasks)."""
    if path is not None and str(path).endswith("-light-plan.md"):
        return True
    return bool(LIGHT_HEADING_RE.search(text))


def status_state(ch):
    """Classify a STATUS_RE capture into the contract's three states.

    The ONLY sanctioned way to read a Status character. Consumers must not test the
    captured character themselves: `!= " "` silently reads `[~]` as done.
    """
    if ch == "~":
        return "partial"
    if ch in ("x", "X"):
        return "done"
    return "open"


# --- GATE-CHECKBOX CONTRACT ---------------------------------------------------
# A gate check is a different marker from a task Status and has its own state set,
# but it lives here for the same reason STATUS_RE does: one definition, so "the gate
# passed" cannot mean one thing in one consumer and another elsewhere.
#
# `[~]` means BLOCKED: the check could not be run in this environment. It is not
# "partially done" and not a softer `[x]`. honest-gates makes the three-way split
# load-bearing (GREEN ran and passed, RED ran and failed, BLOCKED could not run), and
# only BLOCKED needs a marker, because a RED gate is repaired, not recorded.
#
# Scope: plan_has_blocked_gate() reads ONE plan's own gate blocks. A master carries no
# `### Stage N Gate` section (its gate boxes live in its sub-plan files), which is
# why plan_blocked() propagates.
GATE_ITEM_RE = re.compile(r"^\s*-\s*\[([ xX~])\]")


def gate_item_state(ch):
    """Classify a GATE_ITEM_RE capture. The ONLY sanctioned way to read one.

    Deliberately different words from status_state(): a task is `partial` because
    work is under way, a gate check is `blocked` because a command could not run.
    Sharing the vocabulary would invite sharing the treatment.
    """
    if ch == "~":
        return "blocked"
    if ch in ("x", "X"):
        return "done"
    return "open"


def plan_has_blocked_gate(text):
    """True when any stage-gate checkbox in the plan is `[~]`.

    Scoped between a `### Stage N Gate` heading and the next `###`, so a Preflight or
    research checklist elsewhere in the document is never mistaken for gate state.
    """
    in_gate = False
    for line in text.splitlines():
        if line.startswith("###"):
            in_gate = bool(GATEHDR_RE.match(line))
            continue
        if in_gate:
            m = GATE_ITEM_RE.match(line)
            if m and gate_item_state(m.group(1)) == "blocked":
                return True
    return False


# --- BLOCKED ACCEPTANCE ------------------------------------------------------------
# `[~]` overrules a human-authored `**Completed:**`, because proof outranks claim. On
# its own that rule leaves an author no honest way to close such a plan:
# `**Completed:**` no longer retires it, `**Abandoned:**` would be untrue, and editing
# `[~]` to `[x]` would falsify the record. It would penalise hardest the plans that
# used `[~]` most honestly, which is how a convention dies.
#
# `**Blocked-accepted:** <date> — <why>` is the author's answer. It does not claim the
# gate ran; it records that someone looked, understood, and closed the plan anyway.
# Terminal, like the other two markers, and it carries its reason.
BLOCKED_ACCEPTED_RE = re.compile(r"^\*\*Blocked-accepted:\*\*\s*(.+)$", re.M)

# --- Out-of-contract markers: one warner, beside the regexes it is a difference against
#
# Authors write a marker several ways; the parser accepts one. The PARSER STAYS STRICT
# and the mistake is reported where it is made. Widening the regexes loses on blast
# radius: tolerating an indented `**Blocked-accepted:**` also lets one inside a quoted
# example close a plan; accepting `### 01.` as a register opener also matches any
# such heading in a document; accepting more close-out spellings also matches prose
# that merely mentions them. Each widening trades a rare miss for a routine false read
# in the OPTIMISTIC direction: it reports work as finished.
FENCE_RE = re.compile(r"^\s*```")
INDENTED_ACCEPTED_RE = re.compile(r"^[ \t]+\*\*Blocked-accepted:\*\*")
# A heading that opens a register entry the way an author might, but that SUBPLAN_RE
# does not read: `### 01. Foundation`, `### 1) Domain contracts`.
ORDINAL_HEADING_RE = re.compile(r"^###\s+0*\d+\s*[.)]\s+\S")
# A line that presents itself as a close-out but is not the recognised form. The
# discriminator is WHERE THE BOLD CLOSES: a close-out marker ends its bold right after
# the colon (`**Close-out (2026-08-03):**`), while a report line keeps going inside it
# (`**Close-out evaluator: PASS, ...**`). "Close-out" is also a common section label
# (`**Close-out notes:**`), and labelling a section is not claiming completion, so it
# only counts when it carries a date. "Completed" is never used as a label.
NEAR_COMPLETED_RE = re.compile(
    r"^(?:##\s*)?\*\*(?:Completed[^*\n]*?|Close-out\s*\(\d{4}-\d{2}-\d{2}\)\s*):\*\*",
    re.I)


def contract_warnings(text, path=None):
    """(code, line_no, excerpt) for every marker this contract cannot read.

    A DIFFERENCE against the authoritative regexes, never an enumerated list of known
    bad spellings: a list goes stale, silently, the first time someone invents a form
    nobody predicted. Silent on a well-formed document.

    Codes: MARKER-IN-FENCE, STATUS-OUT-OF-CONTRACT, ACCEPTANCE-INDENTED,
    CLOSE-OUT-DIALECT, REGISTER-DIALECT.
    """
    out = []
    master = is_master_plan(text, path)
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue

        if in_fence:
            # None of the parsers is fence-aware, so a literal example of the syntax
            # inside a ``` block parses as a real marker. Teaching every regex about
            # fences is a larger change than the risk warrants; a warning costs nothing.
            if (STATUS_RE.match(line) or TASK_RE.match(line)
                    or SUBPLAN_RE.match(line) or COMPLETED_RE.match(line)):
                out.append(("MARKER-IN-FENCE", i, line.strip()[:80]))
            continue

        # `[!]` and friends match STATUS_RE not at all: the task is ABSENT, and the
        # plan reads as more complete than it is.
        if not STATUS_RE.match(line):
            m = STATUS_LINE_RE.match(line)
            if m:
                out.append(("STATUS-OUT-OF-CONTRACT", i,
                            (m.group(1).strip() or "(empty)")[:80]))

        # The marker parses only at column 0. Indented under the gate item it accepts,
        # the natural place, it parses as absent and the plan stays open.
        if INDENTED_ACCEPTED_RE.match(line):
            out.append(("ACCEPTANCE-INDENTED", i, line.strip()[:80]))

        # A close-out in an unrecognised dialect leaves the plan in flight forever.
        if NEAR_COMPLETED_RE.match(line) and not COMPLETED_RE.match(line):
            out.append(("CLOSE-OUT-DIALECT", i, line.strip()[:80]))

        # A master whose register uses bare ordinals reads 0/0, with no sub-plan the
        # register can be checked against.
        if master and ORDINAL_HEADING_RE.match(line) and not SUBPLAN_RE.match(line):
            out.append(("REGISTER-DIALECT", i, line.strip()[:80]))

    return out


_MAX_SUBPLAN_DEPTH = 2       # a master links sub-plans; a sub-plan is not a master


def blocked_acceptance(text):
    """The `**Blocked-accepted:**` reason, or None."""
    m = BLOCKED_ACCEPTED_RE.search(text)
    return m.group(1).strip() if m else None


NOT_A_PLAN_SUFFIXES = ("-design.md", "-architecture.md", "-done.md")


def is_not_a_plan(path):
    """Whether this document's FILENAME says it is not a plan.

    `plans/` folders also hold `*-design.md` (a brainstorming design), `*-architecture.md`
    (an architecture decision) and `*-done.md` (a backlog completion record). None
    carries tasks, and counting them as plans nobody started distorts that number.

    Anchored on the hyphen-delimited final token, which is load-bearing: a real plan
    can carry `design` inside its name (`…-gui-redesign-plan.md`), and a substring test
    would hide it. Case is not folded: the rule matches only the forms it was written
    for, because a filename heuristic that guesses wrong hides a real plan.
    """
    return Path(path).name.endswith(NOT_A_PLAN_SUFFIXES)


def plan_blocked(text, path=None, _depth=0):
    """(is_blocked, why): the ONE question every consumer asks about blockage.

    Consumers call this rather than plan_has_blocked_gate(): that predicate answers
    "does this file contain a `[~]` gate box", a different question that misses a
    master and ignores acceptance.

    ACCEPTANCE: `**Blocked-accepted:**` closes a plan whose gate could not run. Checked
    first, so an accepted plan is never blocked.

    PROPAGATION: a master carries no gate section of its own, so it is blocked when any
    sub-plan it links is. Acceptance propagates the same way: a master whose sub-plans
    are all accepted is not blocked. This is the one function here that reads files,
    and only when `path` is given.

    Degrades rather than raising: an unresolvable or unreadable sub-plan link is not
    evidence of blockage, and a status tool that throws on a broken link is worse than
    one that under-reports a rare case.
    """
    if blocked_acceptance(text):
        return False, None
    if plan_has_blocked_gate(text):
        return True, "a stage-gate check is `[~]` BLOCKED"
    if path is None or _depth >= _MAX_SUBPLAN_DEPTH:
        return False, None
    try:
        if not is_master_plan(text, Path(path)):
            return False, None
    except Exception:
        return False, None
    base = Path(path).parent
    hit = []
    for link in SUBPLAN_LINK_RE.findall(text):
        target = (base / link.strip()).resolve()
        try:
            sub = target.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue                      # a link that resolves nowhere is not blockage
        if plan_blocked(sub, target, _depth + 1)[0]:
            hit.append(target.name)
    if hit:
        return True, "blocked sub-plan(s): " + ", ".join(sorted(hit))
    return False, None


def plan_terminal_state(text):
    """(abandoned, advisory, reason) for one plan's full text.

    `abandoned` is True only on the structured marker, and `reason` carries the
    marker's own text (None when not abandoned), so a consumer can list a suppressed
    plan with its reason. `advisory` is a short note when banner prose is present
    WITHOUT the marker: surfaced to the operator, never acted on.

    Deliberately NOT called by parse_plan(). Abandonment is a ranking signal (an
    abandoned plan is not recommended as next work); candidate extraction keeps
    emitting its open tasks, because those are proposed for human acceptance, and
    suppressing them would let a one-line marker delete work from the only view that
    still lists it.
    """
    am = ABANDONED_RE.search(text)
    if am:
        return True, None, am.group(1).strip()
    m = ABANDON_HINT_RE.search(text)
    if m:
        return False, (f"looks abandoned ({m.group(1).lower()} banner) but "
                       f"carries no **Abandoned:** marker — not suppressed"), None
    return False, None, None


def parse_plan_status(text, plan_rel):
    """Candidates from a plan that carries per-task `- **Status:**` fields.

    A Task N.N with `Status: [ ]` emits ONE candidate (signal `status-unexecuted`,
    title = the task description); `[~]` emits one with signal `status-partial`;
    `[x]` emits nothing. Raw unchecked bullets are ignored entirely: Status is the only
    task-state source, and git stage evidence is not consulted. Deferred blocks still
    surface. A master's register entries are `### Sub-plan N:` headings, so their
    Status fields have no Task context and emit nothing.
    """
    out = []
    cur_stage = None
    cur_task = None
    in_deferred = False
    defer_n = 0
    for line in text.splitlines():
        if SECTION.match(line):
            in_deferred = bool(DEFERRED_RE.match(line))
            cur_task = None
        sh = STAGEHDR_RE.match(line)
        if sh:
            cur_stage = int(sh.group(1))
        tm = TASK_RE.match(line)
        if tm:
            cur_task = (tm.group(1), tm.group(2).strip())
        if in_deferred:
            bm = BULLET.match(line)
            if bm:
                defer_n += 1
                title = re.sub(r"^\[[ x]\]\s*", "", bm.group(1).strip())
                out.append({"source": f"{plan_rel} — Deferred / bullet {defer_n}",
                            "title": title, "signal": "deferred-section"})
            continue
        sm = STATUS_RE.match(line)
        if sm and cur_task:
            st = status_state(sm.group(1))
            if st != "done":
                num, desc = cur_task
                loc = f"Stage {cur_stage} / Task {num}" if cur_stage else f"Task {num}"
                out.append({"source": f"{plan_rel} — {loc}",
                            "title": desc,
                            "signal": ("status-unexecuted" if st == "open"
                                       else "status-partial")})
            cur_task = None       # one Status field per task; consume it
    return out


def parse_plan(text, plan_rel, done_stages):
    """Backlog candidates from one plan's text.

    A plan carrying any `- **Status:** [.]` field takes the authoritative path
    (parse_plan_status). A legacy plan falls back to the heuristic: every unchecked
    `- [ ]` (outside Preflight, `Decisions in force` and gate blocks) whose enclosing
    Stage is NOT in `done_stages`, plus all Deferred bullets. `done_stages` is the set
    of stage numbers the caller found confirmed executed (for example by commits
    dated on or after the plan); this module never runs git itself.

    Each candidate is {"source": "<plan_rel> — <locator>", "title": ..., "signal": ...}.
    """
    # Detection requires the checkbox, matching STATUS_RE: a checkbox-less
    # `- **Status:** Draft` line must NOT capture the file for the authoritative path,
    # which would silently drop its legacy candidates. The class must stay in lockstep
    # with STATUS_RE's: if `~` were missing here, an all-partial plan would match
    # nothing, fall to the heuristic, and emit its gate bullets instead of its tasks.
    if re.search(r"(?m)^\s*-\s*\*\*Status:\*\*\s*\[[ xX~]\]", text):
        return parse_plan_status(text, plan_rel)
    out = []
    lines = text.splitlines()
    cur_stage = None
    in_preflight = False
    in_decisions = False
    in_deferred = False
    in_gate = False
    defer_n = 0
    for line in lines:
        if SECTION.match(line):
            in_preflight = bool(PREFLIGHT_RE.match(line))
            in_decisions = bool(DECISIONS_RE.match(line))
            in_deferred = bool(DEFERRED_RE.match(line))
            # A header naming a "Gate" opens an acceptance-criteria block; any other
            # header (a Task, a new Stage, Deferred, …) closes it.
            in_gate = bool(GATE_WORD.search(line))
        elif GATE_BOLD.match(line):
            in_gate = True            # bold marker form, e.g. **Stage Gate:**
        elif HR.match(line):
            in_gate = False
        sh = STAGEHDR_RE.match(line) or GATEHDR_RE.match(line)
        if sh:
            cur_stage = int(sh.group(1))
        if in_deferred:
            bm = BULLET.match(line)
            if bm:
                defer_n += 1
                title = re.sub(r"^\[[ x]\]\s*", "", bm.group(1).strip())
                out.append({"source": f"{plan_rel} — Deferred / bullet {defer_n}",
                            "title": title, "signal": "deferred-section"})
            continue
        um = UNCHECKED.match(line)
        if um and not in_preflight and not in_decisions and not in_gate:
            if cur_stage is None or cur_stage not in done_stages:
                loc = f"Stage {cur_stage}" if cur_stage else "checklist"
                # rstrip the 50-char slice so the Source has no trailing space: dedup
                # compares stripped Source strings, so both sides must be stripped.
                snippet = um.group(1).strip()[:50].rstrip()
                out.append({"source": f"{plan_rel} — {loc} / unchecked: {snippet}",
                            "title": um.group(1).strip(),
                            "signal": "unchecked-open"})
    return out
