#!/usr/bin/env python3
"""plan-flip-audit.py — checkbox flips need evidence.

CURSOR FORK. On Cursor a stage's claims are proven once, at its gate, after the
reviews and their fixes: task commits carry code only, and the stage's records land
with its `Stage N green` commit. So findings 8 and 9 skip the tasks of the stage in
flight — the stage .claude/plan-progress.json names for this plan, in phase
preflight, task or gate, with no gate box ticked and no `Stage N green` in
HEAD's history (open_stage()). Anything else holds every ticked task to its proof,
so a stage that claims its gate passed without the commit is still judged. And on
Cursor EVERY claim of a ticked task needs a record, not only its first claim and the
ones that name their break "(red if …)": the verifier proves the whole stage at once,
and the git ref hook (hooks/git-ref-gate.sh) refuses `Stage N green` without a
record for each claim, so this audit counts the same set.

    plan-flip-audit.py <plan.md> [--since <rev>] [--flip-threshold N]
                       [--vocab-file F] [--require-all-checks] [--json]
                       [--repo DIR]
    plan-flip-audit.py <plan.md> --snapshot [--repo DIR]

Reports ten patterns, each a way an executor can ship a green gate over work
that had not happened, or burn turns on one (10):

  1. more than N (default 6) boxes becoming `[x]` in one commit, with fewer than
     N task commits in the range behind them — the bulk regex flip. The boxes
     under a `### Stage N Gate` heading are not counted once a `Stage N green`
     commit is in the range: ticking a gate with its commit is the procedure.
     Nor are up to N Preflight boxes once a probe artefact backs them (finding 3's
     evidence) in that commit or earlier; more than N is a bulk flip whatever is committed.
  2. a ticked box whose own text carries what voids it. Two tiers: a STRONG
     phrase voids alone and is `blocking` (no device / soft residual / exit 2 /
     exit 78 / stubbed / mocked / waived / Not done: / shouted BLOCKED); a WEAK
     qualifier (amended / partial / skipped / manual / blocked / exit 1 / ...)
     is `advisory` when two co-occur, or when one stands in an amendment
     parenthetical that discloses no was-value. See void_hit() for why.
  3. a Preflight access/device box ticked in a commit carrying no probe output
  4. a `**Completed:**` line or master-register tick standing over a gate line
     that matches (2), in this file or a linked sub-plan
  5. a `(judgment)` box ticked in a commit with no evaluator/reviewer artefact
  6. a ticked box recording an OWNER decision ("Owner confirms …", "user
     approves …") that carries no quote of the owner's words — `blocking`
  7. an amendment's `was:` value still standing, unannotated, elsewhere in the
     plan — `advisory` (it may be a true historical statement; say which)
  8. a ticked task with a Test claim — on Cursor every claim, see CURSOR FORK
     above — that has no valid prove-claim.py record (proof/<plan>/<task>/
     claim-K.json, bound to the commit that last wrote it, or with proof/ local
     to its stage's `Stage N green` commit or a commit naming the task) — `blocking`; a claim
     recorded as a claim deviation, or only self-reported `mutation:` lines —
     `advisory`. Needs --repo; without it, reported NOT RUN.
  9. a ticked task with a requirement clause that has neither a valid
     req-K.json nor a deviation-K.json record — `advisory`, always: requirement
     accounting carries no blocking mandate until it is measured. Needs --repo.
 10. a `Stage N gate remediation` (or `Stage N gate, remediation`) commit, dated
     on or after the plan's own date, whose Stage N gate has a `**Live check` line
     and whose message has no `fixture-sweep:` trailer — `advisory`, always (see
     LIVE_CHECK for the measured rate, why, and the same-date attribution limit).
     Needs --repo.

Exit 0 = no findings, 1 = a blocking finding, 4 = advisory findings only, 2 =
usage/IO error (never clean), 3 = no findings but some checks could not run (only
with --require-all-checks). A crash must never be
readable as "clean", which is why 2 is reserved rather than reusing 1, and why
main() is wrapped so an unexpected exception exits 2 rather than letting
Python's default exit 1 masquerade as "findings". (That handler prints to
stderr and emits no document, so a --json caller sees empty stdout with exit 2 —
check the exit code before parsing.)

COVERAGE IS PART OF THE OUTPUT, NOT A FOOTNOTE. Findings 2, 4, 6 and 7 read the
file on disk. Findings 1, 3 and 5 read git history, and there are ordinary situations
where that history does not exist — a plan living in a records home that is not
a git repository is the common case, and a plan file that is untracked
inside a repo that HAS history is the subtler one. An audit that answered "no
findings" in either case would be asserting a clean bill over three checks it
never ran, which is the same act it exists to detect. So every run reports which
checks ran and which did not, the not-run banner goes to stderr where a caller
cannot drop it by reading only stdout, --json carries both lists, and a caller
that must not tolerate partial coverage passes --require-all-checks to get a
distinct exit code instead of a green one.

THE BASELINE, for a plan with no git history. A plan whose records home is not
a git repository gives findings 1, 3 and 5 nothing to read, so for such plans
they could never run and exit 3 would be the normal case. An executor could then
tick every Preflight box of a plan in one edit, owner confirmation included,
with nothing able to notice. So `--snapshot`, run once when the plan is loaded, copies the plan
into `<repo>/.claude/plan-baseline/`. Later runs on a plan outside git compare
the file on disk against that copy instead of against a parent commit, and take
their evidence (task commits, probe artefacts, review ledgers) from the
PROJECT repo's commits since the snapshot. Weaker than history mode, and said
so: the copy is one state, not a per-commit series, so evidence anywhere in
the range counts for every flip in it. A second `--snapshot` is refused — a
re-snapshot after ticking would launder every flip since — and a baseline whose
text no longer matches its recorded hash exits 2, never clean. Hand-editing
both is still possible; this raises the cost of a fake, it does not stop one.

HOW A TICK IS DETECTED, and why it is not a diff. Pairing removed `[ ]` lines
against added `[x]` lines in the commit diff, keyed on exact text, misses the
canonical fake outright: an executor amending a gate ticks the box AND appends
the amendment in the same edit, which changes the text and breaks the key. So
this audit compares STATE, not diffs — the set of ticked
boxes in the file at the commit against the set at its parent. A box that is
ticked now and was not before is a flip, whether its text changed, whether it
was appended already-ticked, and whether or not the diff pairs cleanly. Identity
is a normalized key with the trailing amendment parenthetical stripped, so
ticking-plus-amending stays the same box.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# The two shapes a done-marker takes in a plan's PROSE. The bare bullet box is
# the common one; `- **Status:** [x]` is the per-task marker every plan this repo
# produces uses. `+`/`1.` bullets are accepted because markdown does.
#
# There is deliberately NO table-cell pattern here. A master register's sub-plan
# ticks are not read through it: that half of finding 4 lives in
# `register_ticks()`, which does its own confined search and never calls
# `boxes()`. Measured over 601 plans, all those one owner's records homes held at an earlier count than the 775 below (undated), a table pattern matched ZERO lines while feeding ordinary risk/status tables
# ("| example-risk | [x] | N/A |") into the void-tick scan as false positives.
# It would be dead for any honest purpose and live for the wrong one.
BULLET_BOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[([ xX])\]\s*(.*)$")
LABELED_BOX = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])\s*(\*\*[^*]+\*\*:?)\s*\[([ xX])\]\s*(.*)$")

# A trailing amendment parenthetical is commentary ABOUT the box, not part of
# its identity — stripping it is what lets "tick it and amend it in one commit"
# still resolve to the same box across the parent/child comparison.
AMEND_TAIL = re.compile(r"\s*\*?\([^()]*\)\*?\s*$")
EMPHASIS = re.compile(r"[*`_]+")

# TWO TIERS, because a single word cannot tell a voided tick from an honest one.
#
# Measured over 188 plans from one owner's records homes, one project's plans excluded
# (undated): a flat vocabulary produced a 39.8% hard
# false-positive rate and lit up 31.4% of all plans. The dominant cause was bare
# `amended` (44% of hits) -- which in these plans is a CEREMONY KEYWORD that
# executing-plans § Amending authored ceremony REQUIRES an honest executor to
# write. A detector that fires on the disclosure protocol punishes the behaviour
# it exists to encourage, and under "a finding is a RED gate" it would be
# switched off within a week, after which it catches nothing.
#
# So: a STRONG phrase voids a tick on its own -- it says the work did not
# happen. A WEAK qualifier voids only in company: two of them on one line. That
# keeps `(amended — exit 2; no device)` and `(amended — skipped the clean
# step)` firing while `(amended at Preflight … was: 3 of 7 tasks)` stays quiet.
VOID_STRONG = [
    r"\bsoft\s+residual\b",
    r"\bnot\s+(fully\s+)?automated\b",
    r"\bno\s+(CM-?4s?|devices?|hardware|boards?|endpoints?|profiles?|MCU)\b",
    r"\bnot\s+(run|executed|reachable|available|attached|present|actuated|done)\b",
    r"\bnever\s+(ran|run|executed|asserted)\b",
    r"\bstill\s+(open|pending|outstanding)\b",
    r"\bwithout\s+(a\s+|the\s+|dual\s+|recoverable\s+)?"
    r"(hardware|devices?|CM-?4s?|boards?|MCU|endpoints?|profiles?)\b",
    # These have no honest sense in an amendment on a ticked gate line. Nothing
    # in § Amending authored ceremony asks an executor to write them, and no
    # honest homonym appears across the measured plan corpus. `exit 2` and
    # `exit 78` in particular say the check failed: a hardware box reading
    # `(amended — exit 2)` records a check that did not pass, and
    # 78 is the code this very skill defines as the only recordable BLOCKED.
    # Bare `exit 1` stays weak: it is the PASS of the `! grep` idiom.
    r"\bexit\s+(code\s+)?(2|78)\b",
    r"\bstub(bed|s)?\b", r"\bmocked\b", r"\bsimulated\b", r"\bwaived\b",
]
# Case-SENSITIVE: the shouted forms are how a plan records a real stop. Lowercase
# "blocked"/"partial"/"skipped" are ordinary words (a routing enum can carry a
# Blocked value) and live in the weak tier instead.
VOID_STRONG_CASED = [r"\bBLOCKED\b", r"\bSKIPPED\b", r"\bPARTIAL\b"]

VOID_WEAK = [
    r"\bamended\b",
    # `exit 0` is the passing outcome; so is `exit 1` for the `! grep` idiom
    # these plans use constantly, which is why this is weak and not strong.
    r"\bpartial(ly)?\b", r"\bskipped\b", r"\bdeferred\b", r"\bwaived\b",
    r"\bmanual(ly)?\b", r"\bexit\s+(code\s+)?1\b",
    r"\bresidual\b", r"\bblocked\b", r"\bunreachable\b",
    r"\bN/A\b", r"\bTODO\b",
]

# Spans where the vocabulary is QUOTED rather than ASSERTED. A gate line reading
# ``! rg -n 'soft residual|BLOCKED' Makefile`` is the anti-stub check itself, and
# flagging it would be the detector tripping over its own detector.
# Test-runner summaries ("1840 passed, 31 skipped") are the other big class.
QUOTED_SPAN = re.compile(r"`[^`]*`|~~[^~]*~~")
# A TOOL'S OWN NAME IS NEVER A CONFESSION. `\bstub\b` matches inside
# `example-stub-audit` because a hyphen is a word boundary — so a gate report that
# CITES an audit tool by name would be flagged as a ticked box confessing a stub.
# The list holds this plugin's script names that contain a flagged word (on any
# host), plus a hyphenated `*-audit` name WITH its script extension, the shape an
# outside audit tool a gate report may cite takes. A bare `<word>-audit` is prose and
# stays matched: "mocked-device-audit passed" is a confession. A mechanical check over
# plan prose must not key on a word inside a tool's name. Masked like a quoted span,
# before any matching.
TOOL_NAME = re.compile(
    r"\b(?:[a-z][a-z0-9]*(?:-[a-z0-9]+)*-audit\.(?:sh|py)\b|"
    r"(?:plan-flip-audit|probe-device|plan-continue|plan-progress|hooks-install|"
    r"statusline-install)(?:\.(?:sh|py))?\b)")
# "gate not blocked", "complete, not partial", "no residual", "not the old stub".
NEGATED = re.compile(r"\b(no|not|never|zero|without|non)\b[^.]{0,30}$", re.I)
NEGATED_HYPHEN = re.compile(r"non-\s*$", re.I)
# "27 skipped", "31 skipped" — a count, not a confession.
COUNTED = re.compile(r"\d+\s*$")
# What § Amending authored ceremony REQUIRES an amendment to carry: the
# was-value, or the rule that authorised it. Its presence is the whole
# difference between a disclosed amendment and a bare claim that something
# changed — and it is what makes a lone qualifier honest rather than suspect.
DISCLOSED = re.compile(r"\bwas:|\bper\s|\bsee\s|§|\bmeasured\b|\bverified\b", re.I)

ACCESS_VOCAB = re.compile(
    r"\baccess\b|\breachable\b|\bdevice\b|\bhardware\b|\bcredential"
    r"|\btoolchain\b|\bserial\b|\bssh\b|\bflash\b|\bon\s+desk\b",
    re.I,
)

# Finding 3's evidence: a probe artefact ADDED OR MODIFIED in that same commit.
# Deliberately anchored to an evidence-ish directory segment or an explicit
# probe/serial filename — an unrelated `security-history.jsonl`, which projects
# commit routinely, must not launder a flip.
PROBE_PATH = re.compile(
    r"(^|/)(evidence|probes?|transcripts?)(/|$)"
    r"|(^|/)[^/]*probe[^/]*\.(txt|log|json|jsonl|out)$",
    re.I,
)

# Finding 5's evidence: a structured evaluator/review ledger line (the shape the
# gate report actually writes) or a review artefact path — not merely the word
# "review" appearing somewhere in a commit message.
REVIEW_REF = re.compile(
    r"^\s*(evaluator|review|reviewer)\s*:\s*\S", re.I | re.M
)
REVIEW_PATH = re.compile(
    r"(^|/)(reviews?|evaluations?)(/|$)|(^|/)[^/]*(review|evaluat)[^/]*\.(md|json|txt)$",
    re.I,
)

COMPLETED = re.compile(r"^\s*\*\*Completed:\*\*", re.I)
JUDGMENT = re.compile(r"\(judgment\)", re.I)
STAGE_GREEN = re.compile(r"^Stage\s+(\d+)\s+green\b", re.I)
# A stage's gate checklist as planning-projects writes it: `### Stage N Gate`.
GATE_HEAD = re.compile(r"^\s*#{1,5}\s+Stage\s+(\d+)\b[^\n]*\bGate\b", re.I)
MD_LINK = re.compile(r"\(([^()]+?\.md)\)")
BARE_MD = re.compile(r"([A-Za-z0-9._\-/]+\.md)")

HISTORY_CHECKS = (1, 3, 5)
STATIC_CHECKS = [2, 4, 6, 7]

# Finding 6: a box whose claim IS an owner decision — the box OPENS with it.
# Measured over 775 plans, all those one owner's records homes then held (undated), matching the phrase
# anywhere fired on 44
# plans, nearly all on prose: app behaviour that waits on the user, a note that owner
# approval is pending, a pointer to a decision recorded further down. A box whose claim is the
# owner's act states it first. Decision verbs only. "Owner
# runs `sudo apt install …`" or "owner creates the repo" describe HOW a box gets
# satisfied, and the box's own command proves the result — requiring a quote
# there would fire on every Preflight that needs a sudo step, and a detector
# that reds honest plans gets switched off. "Owner confirms the acceptance
# extends to …" has no command behind it: the owner's words are the only
# evidence there can be, so a tick without them is the executor's say-so.
OWNER_DECISION = re.compile(
    r"^(?:\*\*\(judgment\)\*\*\s*|\(judgment\)\s*|the\s+)?"
    r"(owner|user)(?:'s)?\s+"
    r"(confirm(?:s|ed|ation)?|approv(?:es|ed|al)|accept(?:s|ed|ance)?"
    r"|decid(?:es|ed)|decision|choos(?:es)|chose|agree(?:s|d)?"
    r"|sign(?:s|ed)?[\s-]+off|authori[sz](?:es|ed|ation))\b",
    re.I,
)
# The attestation integration.md already demands for a review opt-out, applied
# here: who, optionally when, and the words in quotes —
# `owner, YYYY-MM-DD: "keep"` (the form a decision register records owner calls in).
ATTESTED = re.compile(
    r"\b(owner|user)\b[^\"“”\n]{0,30}:\s*[\"“][^\"”\n]{2,}[\"”]",
    re.I,
)

# Finding 7: the was-value of an amendment. Only a BACKTICKED value that looks
# like an identifier — one token, a digit in it (a commit, a version, a serial)
# — is swept. Measured over the same 775 plans, also sweeping paths and
# commands fired on 9 plans, nearly all false: an amended gate command or file
# path is routinely still valid elsewhere ("`etc/app.toml`", "tasks 2.1, 2.2").
# A superseded commit or version number standing elsewhere is the real case.
WAS_VALUE = re.compile(r"\bwas:\s*`([^`]+)`", re.I)
DISTINCTIVE = re.compile(r"^[^\s/]*[0-9][^\s/]*$")
# A line that is itself an amendment, or says it is historical, is the
# disclosure — not a survivor.
STALE_EXEMPT = re.compile(r"\bwas:|\bamended\b|\bhistorical(ly)?\b", re.I)

# Finding 8: a task's Test proves something only if it was seen to FAIL when
# the thing it claims is broken. A test of a path setting can pass with the
# setting unset and with it pointing nowhere, and a commit can record one
# `mutation:` line for the easiest of several claims.
# So EVERY claim of a ticked task needs a prove-claim.py record on Cursor (see
# every_claim); the self-reported `mutation:` line is the retired form, read only
# as legacy.
# Claims are counted the way plans write them:
# `<command>` — claim; claim; claim.
TASK_HEAD = re.compile(r"^\s*#{2,5}\s+Task\s+(\d+\.\d+)\b", re.I)
ANY_HEAD = re.compile(r"^\s*#{1,5}\s")
STATUS_TICKED = re.compile(r"^\s*[-*+]\s*\*\*Status:\*\*\s*\[[xX]\]")
TEST_FIELD = re.compile(r"^\s*[-*+]\s*\*\*Test:\*\*\s*(.*)$")
# The tasks a commit SUBJECT names. One reader for the audit and the git ref hook
# (hooks/git-ref-gate.sh), so they cannot disagree about which commit is whose:
# case-insensitive, "Task 2.1", "task-2.1", "Task #2.1", "Tasks 2.1 and 2.2",
# "Task 1.1 + Task 1.2", and ranges within a stage, "Tasks 2.4-2.7".
TASK_LIST = re.compile(
    r"\btasks?\b\s*[:#-]?\s*(\d+\.\d+(?:\s*(?:,|&|\+|/|\band\b|\bto\b|-|\u2013|\u2014)\s*"
    r"(?:tasks?\b\s*[:#-]?\s*)?\d+\.\d+)*)", re.I)
TASK_RANGE_SEP = re.compile(r"^\s*(?:-|\u2013|\u2014|\bto\b)\s*$", re.I)


def subject_tasks(subject):
    """{'2.1', ...}: every task id the subject line names, ranges expanded."""
    out = set()
    for m in TASK_LIST.finditer(subject or ""):
        span = m.group(1)
        ids = list(re.finditer(r"\d+\.\d+", span))
        for i, cur in enumerate(ids):
            out.add(cur.group(0))
            if i == 0:
                continue
            prev = ids[i - 1]
            sep = re.sub(r"(?i)tasks?\b\s*[:#-]?", "", span[prev.end():cur.start()])
            (a_major, a_minor), (b_major, b_minor) = (
                map(int, prev.group(0).split(".")), map(int, cur.group(0).split(".")))
            if TASK_RANGE_SEP.match(sep) and a_major == b_major and a_minor < b_minor <= a_minor + 50:
                out.update(f"{a_major}.{n}" for n in range(a_minor + 1, b_minor))
    return out


# ---- The stage's own fields, and the two gate reports bound to them -------------
# Shared by stage-brief.py (which writes the report skeletons and the evaluator's
# brief) and the git hook (which reads the reports in the `Stage N green` commit),
# so the text a report must quote and the text the plan holds come from one parser.
STAGE_SECTION = re.compile(r"^\s*##\s+Stage\s+(\d+)\b")
STAGE_FIELD = re.compile(r"^\s*\*\*([A-Za-z][A-Za-z ]*):\*\*\s*(.*)$")
FIELD_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
CONTINUATION = re.compile(r"^\s+\S")
# A report's own labels. A value runs until the next of these, so an evidence line that
# merely looks like a label (`Error: …`) stays part of the evidence.
REPORT_LABELS = ("Assumption", "Checked", "Result", "Verdict", "Evidence")
REPORT_LABEL = re.compile(rf"^\s*(?:{'|'.join(REPORT_LABELS)})\s*:", re.I)
# `holds`, alone or with a note set off by a dash or brackets ("holds — on both devices",
# "holds (both devices)"); never "holds only on …" or "holds, but …", which qualify it.
HOLDS = re.compile(r"^holds\.?\s*(?:(?:—|–|--?)\s+.*|\(.*\))?\s*$", re.I)


def _is_stage(heading_number, stage):
    try:
        return int(heading_number) == int(stage)
    except (TypeError, ValueError):
        return False


def _stage_lines(text, stage):
    """The lines of `## Stage <stage>` before its first `###` heading."""
    out, inside = [], False
    for line in text.splitlines():
        m = STAGE_SECTION.match(line)
        if m:
            if inside:
                break
            inside = _is_stage(m.group(1), stage)
            continue
        if not inside:
            continue
        if ANY_HEAD.match(line):
            break
        out.append(line)
    return out


def _is_note_line(line):
    """A line that is only history notes, e.g. `*(amended <date> — owner: "…")*`."""
    return bool(line.strip()) and not strip_notes(line).strip()


def stage_fields(text, stage):
    """{field name: {"text": rest of its line, "items": [bullets under it]}} for the
    stage-level `**Field:**` lines of `## Stage <stage>`, history notes stripped.
    Bullets may be `-`, `*`, `+` or numbered; an indented line continues the bullet
    above it; a line holding only notes is skipped. Task blocks and the gate are not
    stage fields; the walk stops at the first `###` heading. An unindented line that
    follows a field's bullets without being one is kept as that field's `stray`: it is
    most likely a wrapped bullet, and ending the field there would drop what follows.
    One directly under the field's own line, before any bullet, wraps that line: it
    joins the field's text."""
    out, cur, wrap = {}, None, False
    for line in _stage_lines(text, stage):
        f = STAGE_FIELD.match(line)
        if f:
            cur = f.group(1).strip().lower()
            out[cur] = {"text": " ".join(strip_notes(f.group(2)).split()), "items": []}
            wrap = True
            continue
        if not line.strip():
            wrap = False
        if not cur or not line.strip() or _is_note_line(line):
            continue
        if wrap and not FIELD_ITEM.match(line):
            out[cur]["text"] = " ".join((out[cur]["text"] + " " + strip_notes(line)).split())
            continue
        wrap = False
        item = FIELD_ITEM.match(line)
        if item:
            out[cur]["items"].append(" ".join(strip_notes(item.group(1)).split()))
        elif CONTINUATION.match(line) and out[cur]["items"]:
            items = out[cur]["items"]
            items[-1] = " ".join((items[-1] + " " + strip_notes(line)).split())
        else:
            if out[cur]["items"]:
                out[cur].setdefault("stray", line.strip())
            cur = None
    return out


def stage_outcomes(text, stage):
    """The stage's Outcomes bullets, in plan order, notes stripped; [] if it has none."""
    return stage_fields(text, stage).get("outcomes", {}).get("items", [])


def outcomes_stray(text, stage):
    """The first unindented non-bullet line directly under the stage's Outcomes, or None."""
    return stage_fields(text, stage).get("outcomes", {}).get("stray")


def has_outcomes_field(text, stage):
    """True when the stage carries an `**Outcomes:**` field, whether or not any bullet
    under it parses — a field the parser cannot read is still a stage with Outcomes."""
    return "outcomes" in stage_fields(text, stage)


def _sections(report, title):
    """{K: body} for every `## <title> K` section of a report."""
    out, cur = {}, None
    for line in report.splitlines():
        m = re.match(rf"^\s*##\s+{title}\s+(\d+)\s*$", line, re.I)
        if m:
            cur = int(m.group(1))
            out[cur] = []
            continue
        if re.match(r"^\s*#{1,2}\s", line):
            cur = None
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _label(body, name):
    """The value after the FIRST `<name>:` in a section, joined with its continuation
    lines up to the next report label. A second `<name>:` further down — pasted into
    the evidence, say — is evidence, not a second value."""
    take, got = False, []
    for line in body.splitlines():
        if not take:
            m = re.match(rf"^\s*{name}\s*:\s*(.*)$", line, re.I)
            if m:
                take = True
                if m.group(1).strip():
                    got.append(m.group(1).strip())
            continue
        if REPORT_LABEL.match(line):
            break
        if line.strip():
            got.append(line.strip())
    return " ".join(got)


def _quote(body):
    """The `> ` block directly under a section's heading (blank lines before it aside)."""
    got = []
    for line in body.splitlines():
        if line.strip().startswith(">"):
            got.append(line.strip()[1:].strip())
        elif got or line.strip():
            break
    return " ".join(" ".join(got).split())


def demo_problems(report, outcomes):
    """Why a stage's demo report does not cover its Outcomes, or [] when it does.

    One `## Outcome K` per plan Outcome, its `> ` quote equal to the plan's text
    (whitespace aside), a first `Verdict:` of `holds`, and non-empty `Evidence:`. The
    quote is what stops a brief or a report from paraphrasing an Outcome away: a
    written brief drops Outcomes and lets a test suite stand in for the demo."""
    probs = []
    secs = _sections(report or "", "Outcome")
    for k, want in enumerate(outcomes, 1):
        body = secs.get(k)
        if body is None:
            probs.append(f"Outcome {k}: no section in the demo report")
            continue
        if _quote(body) != want:
            probs.append(f"Outcome {k}: the quoted text is not the plan's Outcome word for word")
            continue
        verdict = _label(body, "Verdict")
        if not HOLDS.match(verdict):
            probs.append(f"Outcome {k}: verdict is {verdict.lower() or 'empty'!r}, not 'holds'")
        if len(_label(body, "Evidence")) < 20:
            probs.append(f"Outcome {k}: no evidence — the commands run and what was seen")
    return probs


def premise_outcomes(report):
    """The Outcomes the premise worksheet recorded at Step 3.0, in order."""
    out, inside = [], False
    for line in (report or "").splitlines():
        if re.match(r"^\s*Outcomes:\s*$", line):
            inside = True
            continue
        if inside:
            item = FIELD_ITEM.match(line)
            if item:
                out.append(" ".join(item.group(1).split()))
            elif CONTINUATION.match(line) and out:
                out[-1] = " ".join((out[-1] + " " + line).split())
            else:
                break
    return out


def outcomes_block_raw(text, stage):
    """The stage's `**Outcomes:**` line and every line under it, notes and all."""
    lines, take = [], False
    for line in _stage_lines(text, stage):
        f = STAGE_FIELD.match(line)
        if f:
            take = f.group(1).strip().lower() == "outcomes"
            if take:
                lines.append(line)
            continue
        if take and line.strip() and (FIELD_ITEM.match(line) or CONTINUATION.match(line)
                                      or _is_note_line(line)):
            lines.append(line)
        elif line.strip():
            take = False
    return "\n".join(lines)


def outcome_drift_problems(premise_report, plan_text, stage):
    """Outcomes recorded at Step 3.0 that the plan no longer states word for word.

    Dropping or rewording an Outcome after Step 3.0 changes what the stage is judged
    on, and that is the owner's call: it stands only when the Outcomes' amendment
    notes quote them (`owner, <date>: "<their words>"`), one note per Outcome changed,
    so a single old note cannot excuse every later drop. Otherwise an executor whose
    demo finds an Outcome unreachable can delete it, regenerate the report and pass."""
    baseline = premise_outcomes(premise_report)
    current = stage_outcomes(plan_text, stage)
    gone = [o for o in baseline if o not in current]
    if not gone or len(ATTESTED.findall(outcomes_block_raw(plan_text, stage))) >= len(gone):
        return []
    return [f"Outcome recorded at Step 3.0 is no longer in the plan, and no owner words "
            f"approve the change: {o[:90]}" for o in gone]


DECLARED_TIER = re.compile(r"review-scope:\s*`?\s*(none|light|standard|high)\b", re.I)


def declared_tier(text):
    """The review-scope tier the plan declares (its first `review-scope: <tier>`), or None."""
    m = DECLARED_TIER.search(text or "")
    return m.group(1).lower() if m else None


def demo_opted_out(report):
    """True when the demo report holds a `## Not demoed` section quoting the owner's words
    (`owner, <date>: "<words>"`): the evidenced opt-out that stands in for a demo. A
    reason with no owner's words is the executor's, and is not one."""
    m = re.search(r"^\s*##\s+Not demoed\s*$(.*?)(?=^\s*##\s|\Z)", report or "", re.M | re.S | re.I)
    return bool(m and ATTESTED.search(m.group(1)))


def premise_problems(report):
    """Why a stage's premise worksheet is not filled in, or [] when it is.

    At least one `## Premise K`, each with Assumption, Checked, Result and a
    Verdict of `holds` or `not checkable here — <why>`. A `false` verdict is the
    Stop condition "the plan's premise is false", so it never makes a gate."""
    probs = []
    secs = _sections(report or "", "Premise")
    if not secs:
        return ["no `## Premise K` entry — Step 3.0 was not recorded"]
    for k, body in sorted(secs.items()):
        for name in ("Assumption", "Checked", "Result"):
            if not _label(body, name):
                probs.append(f"Premise {k}: {name} is empty")
        verdict = _label(body, "Verdict").lower()
        if re.match(r"^false\b", verdict):
            probs.append(f"Premise {k}: false — the plan's premise does not hold; this is a Stop "
                         "condition, not a gate")
        elif not (HOLDS.match(verdict) or
                  (verdict.startswith("not checkable here") and len(verdict) > len("not checkable here") + 3)):
            probs.append(f"Premise {k}: verdict must be 'holds', 'false' or "
                         "'not checkable here — <why>', got " + repr(verdict or "empty"))
    return probs
MUTATION_LINE = re.compile(r"^\s*mutation\s*:\s*\S", re.I | re.M)

# Finding 9: the task DESCRIPTION is a contract too, not context. A task's Test
# can pass — the expected files are in the build output — while requirements in
# its description are not met: a toolchain version copied instead of read from
# the one the build pins, a build step that skips the rebuild after its source
# changes although the task requires one. The Test
# cannot see either. So the task's commit carries one line per
# requirement clause: `req: <clause> -> <how it was verified>`, or
# `deviation: <clause> -> <what differs and why>` — a disclosed deviation is a
# finding a reader can judge, a silent one is not. Clauses are the `;`- and
# sentence-separated parts of the task's plain bullets, with code spans masked.
REQ_LINE = re.compile(r"^\s*(req|deviation)\s*:\s*\S", re.I | re.M)
FIELD_BULLET = re.compile(r"^\s*[-*+]\s*\*\*[^*]+:\*\*")
PLAIN_BULLET = re.compile(r"^\s*[-*+]\s+(\S.*)$")
CLAUSE_SPLIT = re.compile(r";|\.\s+(?=[A-Z`(*])")

# Finding 10: a remediation round that re-runs a live or device-bound check is
# proven on the host first, against every capture of that kind, and the sweep is
# recorded as a `fixture-sweep:` trailer (gate-failure-procedure.md § Remediation
# that re-runs a live check: a fix fitted to one capture fails on the next, and each
# retry costs a slow live turn). A gate's live check is a box whose text opens
# `**Live check`.
#
# Measured 2026-10-06 over 144 plans (one owner's plans with git history) and that
# history: 4 hits,
# 0 true. Two were
# rounds that reworded prose, or re-ran the live check and passed with no capture of
# that kind to sweep. The other two belonged to another plan executed the same day:
# commits are matched by stage number and date, not by plan, so plans sharing a date
# and stage numbers — sub-plans especially — read each other's remediations. Plans
# that never write the `**Live check` marker are out of reach entirely. The date bound
# (commits from the plan's filename date on) is measured too: without it the corpus
# gives two more hits, another plan's earlier rounds.
# Advisory, always: 0 true of 4, and a commit cannot show whether its round re-ran the
# live check, nor which plan it belongs to. The gate report says that
# (gate-authoring.md § A gate heuristic ships with a severity axis and a measured
# trigger rate).
REMEDIATION = re.compile(r"\bStage\s+(\d+)\s+gate,?\s+remediation\b", re.I)
LIVE_CHECK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[ xX]\]\s*\*\*Live check", re.I)
FIXTURE_SWEEP = re.compile(r"^\s*fixture-sweep\s*:\s*\S", re.I | re.M)
PLAN_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")

# The staleness probe lives in the plugin's lib/, not beside this file: loaded by
# explicit path, as in check-master-register.py, so a stale plugin-cache copy says so
# before it audits or proves anything under yesterday's rules.
_STALE = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"


def _warn_if_stale():
    try:
        spec = importlib.util.spec_from_file_location("staleness_probe", _STALE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.warn_if_stale(__file__)
    except Exception:  # noqa: BLE001 — a probe that cannot load must never stop the command
        pass


class Bail(Exception):
    """Usage/IO failure — always exit 2, never 1."""


def die(msg):
    raise Bail(msg)


def git(repo, *args):
    """Run git. Returns (stdout, None) on success, (None, reason) on failure.

    A missing binary, a 'dubious ownership' refusal and 'not a repository' are
    materially different situations and get materially different reasons —
    collapsing all three into 'not inside a git repository' would be false for
    two of them and would send a reader looking in the wrong
    place. errors='replace' because a plan file may legitimately contain bytes
    that are not UTF-8, and a decode error must not escape as a bare crash.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            errors="replace",
            # A translated git turns every message-matching branch into a wrong
            # answer; pin the locale rather than parse an unknown language.
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except FileNotFoundError:
        return None, "git binary not found on PATH"
    except OSError as e:
        return None, f"could not run git: {e}"
    if r.returncode != 0:
        # next(iter(...)): stderr == "\n" is truthy but strips to "", and
        # "".splitlines() is [] -- an IndexError on the error path.
        fallback = f"git {' '.join(args[:2])} exited {r.returncode}"
        return None, next(iter((r.stderr or "").strip().splitlines()), fallback)
    return r.stdout, None


def gout(repo, *args):
    """git() keeping only stdout, or None."""
    out, _ = git(repo, *args)
    return out


# ------------------------------------------------------------------ parsing

def norm_key(body):
    """Identity of a checkbox, stable across ticking-and-amending."""
    b = AMEND_TAIL.sub("", body)
    b = EMPHASIS.sub("", b)
    b = re.sub(r"\s+", " ", b).strip().lower()
    return b[:80]


def boxes(text):
    """Every checkbox in a file's text: (ticked, key, body, line_no, raw)."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = LABELED_BOX.match(line)
        if m:
            ticked, body = m.group(2).lower() == "x", f"{m.group(1)} {m.group(3)}"
            out.append((ticked, norm_key(body), body.strip(), i, line))
            continue
        m = BULLET_BOX.match(line)
        if m:
            ticked, body = m.group(1).lower() == "x", m.group(2)
            out.append((ticked, norm_key(body), body.strip(), i, line))
            continue
    return out


def compile_vocab(vocab_file, replace=False):
    """(strong, strong_cased, weak) matchers; --vocab-file EXTENDS the weak tier.

    Extending is the safe default: a user adding a project word must not
    silently disable the other patterns, which is what a wholesale rebind would
    do -- a fail-open reachable by using the feature as documented. Extra patterns join the WEAK tier, so a bare project keyword
    still needs a co-signal before it can void a tick.
    """
    strong, cased, weak = list(VOID_STRONG), list(VOID_STRONG_CASED), list(VOID_WEAK)
    if vocab_file:
        pth = Path(vocab_file)
        if not pth.is_file():
            die(f"--vocab-file not found: {pth}")
        extra = [ln.strip() for ln in pth.read_text(errors="replace").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        if not extra:
            die(f"--vocab-file is empty: {pth}")
        if replace:
            strong, cased, weak = extra, [], []
        else:
            weak = weak + extra
    try:
        return (re.compile("|".join(strong), re.I) if strong else None,
                re.compile("|".join(cased)) if cased else None,
                re.compile("|".join(weak), re.I) if weak else None)
    except re.error as e:
        die(f"--vocab-file contains an invalid pattern: {e}")


# ------------------------------------------------------------------- static

def void_hit(raw, vocab):
    """The phrase that voids this tick, or None. `vocab` is (strong, cased, weak).

    Two tiers, because one word cannot separate a voided tick from an honest
    one. A STRONG phrase says outright that the work did not happen and voids on
    its own. A WEAK qualifier voids only with a second signal on the same line --
    another weak term or a strong one.

    Measured on 188 plans (one owner's, one project's left out, undated), a flat vocabulary
    was 39.8% hard false positives and lit 31.4% of plans, driven by bare `amended`: the word this
    plugin's own amendment protocol REQUIRES an honest executor to write.
    `(amended — exit 2; no device)` still fires -- three signals. `(amended at
    Preflight … was: 3 of 7 tasks)` does not, and neither does a
    `Blocked` routing-enum value or the `! grep … — exit 1, no hits` idiom whose exit 1
    is a PASS.

    Filters applied before any of it: spans inside backticks or ~~strikethrough~~
    are blanked (a gate line that greps FOR this vocabulary is the anti-stub
    check, not a confession), a term with a negation word up to 30 characters before
    it (no full stop between) is skipped, and a
    term preceded by a count is read as a count ("27 skipped").
    """
    strong, cased, weak = vocab
    masked = QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), raw)
    masked = TOOL_NAME.sub(lambda m: " " * len(m.group(0)), masked)

    def live(m):
        pre = masked[max(0, m.start() - 40):m.start()]
        if NEGATED.search(pre) or NEGATED_HYPHEN.search(pre):
            return False
        return not COUNTED.search(pre)

    for matcher in (strong, cased):
        if matcher:
            for m in matcher.finditer(masked):
                if live(m):
                    return m.group(0), "blocking"
    if weak:
        hits = [m.group(0) for m in weak.finditer(masked) if live(m)]
        # Two independent qualifiers, not the same word twice.
        if len({h.lower() for h in hits}) >= 2:
            return " + ".join(hits[:3]), "advisory"
        # A LONE qualifier must never be silence. It is advisory when it sits in
        # the trailing amendment parenthetical and that parenthetical discloses
        # nothing: `*(amended)*` on a gate line asserts that something changed
        # while withholding the was-value § Amending authored ceremony requires,
        # so it is exactly the shape that rule exists to forbid. The same word in
        # running prose ("under the amended validator") is not an amendment, and
        # the same word WITH its disclosure ("amended at Preflight … was: …") is
        # the protocol being followed. This rewards disclosure rather than
        # punishing the word, as a flat vocabulary would.
        if hits:
            tail = AMEND_TAIL.search(masked)
            if tail and any(h in tail.group(0) for h in hits) \
                    and not DISCLOSED.search(tail.group(0)):
                return hits[0] + " (undisclosed amendment)", "advisory"
    return None


def scan_void_ticks(path, text, vocab):
    """Finding 2 — a ticked box whose own line carries what voids it."""
    out = []
    for ticked, _key, body, line, raw in boxes(text):
        hit = void_hit(raw, vocab)
        if ticked and hit:
            phrase, severity = hit
            out.append({
                "finding": 2,
                "severity": severity,
                "rule": ("ticked box states outright that the work did not happen"
                         if severity == "blocking"
                         else "amendment discloses no was-value"
                         if "undisclosed" in phrase
                         else "ticked box carries two qualifiers that may void it"),
                "file": str(path), "line": line, "text": body,
                "matched": phrase,
            })
    return out


def scan_owner_attestation(path, text):
    """Finding 6 — a ticked owner decision with no quote of the owner."""
    out = []
    for ticked, _key, body, line, raw in boxes(text):
        if not ticked:
            continue
        # A decision phrase inside backticks is quoted, not claimed.
        masked = QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), body)
        m = OWNER_DECISION.search(masked.strip())
        if not m or ATTESTED.search(raw):
            continue
        out.append({
            "finding": 6, "severity": "blocking",
            "rule": "ticked box records an owner decision but quotes no owner "
                    "words (expected: owner, <date>: \"<their words>\")",
            "file": str(path), "line": line, "text": body,
            "matched": m.group(0),
        })
    return out


def scan_stale_was_values(path, text):
    """Finding 7 — an amended value still standing elsewhere in the plan."""
    lines = text.splitlines()
    values = {}
    for i, line in enumerate(lines, 1):
        for m in WAS_VALUE.finditer(line):
            v = m.group(1).strip()
            if len(v) >= 6 and DISTINCTIVE.search(v):
                values.setdefault(v, i)
    out = []
    for v, amended_at in values.items():
        for i, line in enumerate(lines, 1):
            if v in line and not STALE_EXEMPT.search(line):
                out.append({
                    "finding": 7, "severity": "advisory",
                    "rule": f"value amended away at line {amended_at} still "
                            "stands here unannotated — update it, or mark it "
                            "historical",
                    "file": str(path), "line": i, "text": line.strip()[:200],
                    "matched": v,
                })
    return out


def task_blocks(text):
    """Every task block: {id, line (Status line if ticked), test, desc}."""
    out, cur = [], None
    for i, line in enumerate(text.splitlines(), 1):
        m = TASK_HEAD.match(line)
        if m:
            cur = {"id": m.group(1), "line": None, "test": "", "desc": ""}
            out.append(cur)
            continue
        if ANY_HEAD.match(line):
            cur = None
            continue
        if cur is None:
            continue
        if STATUS_TICKED.match(line):
            cur["line"] = i
        t = TEST_FIELD.match(line)
        if t:
            cur["test"] = t.group(1)
        elif not FIELD_BULLET.match(line):
            d = PLAIN_BULLET.match(line)
            if d:
                cur["desc"] += " " + d.group(1)
    return out


def ticked_tasks(text):
    """Ticked tasks in the plan: (task id, Status line number, Test text)."""
    out = task_blocks(text)
    return [(t["id"], t["line"], t["test"]) for t in out if t["line"]]


def _masked(text):
    """`text` with every code span blanked to spaces, so positions still line up."""
    return QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), text)


# An amendment or superseded note is the plan's HISTORY, written by the amendment
# protocol — never a requirement or a claim. Counted as clauses, a note would
# split on its own `;` and `. ` and inflate a task's count with requirements
# that are not there.
# Only a note that reads as history is stripped — it carries a date, a `was:`
# value or a `by commit` — and it is found on the MASKED text, so a code span is
# never part of one. Otherwise wrapping a requirement in `*(amended: …)*` would
# quietly drop it from the count, and with it the proof it needs.
# `added` is Step 3.0's marker on Outcomes derived at execution: "*(added at execution, <date>)*".
ANNOTATION = re.compile(r"\s*\*\((?:amended|superseded|historical|added)\b.*?\)\*", re.S | re.I)
HISTORY_MARK = re.compile(r"\d{4}-\d{2}-\d{2}|\bwas:|\bby commit\b", re.I)


def strip_notes(text):
    """`text` without its history notes (see ANNOTATION)."""
    masked, out, last = _masked(text), [], 0
    for m in ANNOTATION.finditer(masked):
        if HISTORY_MARK.search(m.group(0)):
            out.append(text[last:m.start()])
            last = m.end()
    out.append(text[last:])
    return "".join(out)


def requirement_clauses(desc):
    """The requirement clauses of a task description, as their original text.

    Split where the masked text has a separator, so a `;` or `. ` inside a code
    span never splits; filtered on the text with code spans removed, so a clause
    that is only a code span is not a requirement. prove-claim.py reads clause K
    from here, so the audit and the tool can never number them differently.
    """
    desc = strip_notes(desc)
    if not QUOTED_SPAN.sub("", desc).strip():
        return []
    masked, parts, last = _masked(desc), [], 0
    for m in CLAUSE_SPLIT.finditer(masked):
        parts.append(desc[last:m.start()])
        last = m.end()
    parts.append(desc[last:])
    return [p.strip() for p in parts if len(QUOTED_SPAN.sub("", p).strip()) > 2]


def count_requirements(desc):
    """Requirement clauses in a task description; 0 when it has none."""
    return len(requirement_clauses(desc))


def claim_clauses(test):
    """The claims of a Test field, as their original text.

    The `;`-separated clauses after the field's ` — `; a field with no ` — ` is
    one claim, the whole field. Same masking rule as requirement_clauses.
    """
    test = strip_notes(test)
    masked, sep = _masked(test), " \u2014 "
    if sep not in masked:
        return [test.strip()]
    start = masked.index(sep) + len(sep)
    parts, last = [], start
    for i in range(start, len(masked)):
        if masked[i] == ";":
            parts.append(test[last:i])
            last = i + 1
    parts.append(test[last:])
    out = [p.strip() for p in parts if QUOTED_SPAN.sub("", p).strip()]
    return out or [test.strip()]


def count_claims(test):
    """Claims in a Test field: the `;`-separated clauses after its ` — `."""
    return len(claim_clauses(test))


def every_claim(test):
    """The claim numbers a ticked task must prove on Cursor: all of them, 1..n."""
    return list(range(1, count_claims(test) + 1))


def claim_deviation_problems(rec, fingerprint, expect):
    """Problems with a claim deviation record (kind `claim-deviation`, stored at
    claim-K.json), [] when valid. It discloses a claim no repo patch can break —
    its evidence lives outside the repo — so it is reported, never proof."""
    p = []
    if not isinstance(rec, dict) or rec.get("kind") != "claim-deviation":
        return ["not a claim deviation"]
    _kind, task, k, text = expect
    if rec.get("task") != task or rec.get("index") != k:
        p.append(f"records Task {rec.get('task')} #{rec.get('index')}, not Task {task} #{k}")
    if text is not None and rec.get("text") != text:
        p.append("recorded against different wording than the plan now has")
    if not isinstance(rec.get("why"), str) or len(rec["why"].strip()) < 10:
        p.append("a claim deviation without a reason")
    fpr = rec.get("fingerprint")
    if not isinstance(fpr, str) or not re.match(r"^[0-9a-f]{64}$", fpr):
        p.append("no valid fingerprint")
    elif fingerprint and fpr != fingerprint:
        p.append("recorded on a different tree than this one")
    return p


def task_commit_evidence(repo):
    """{task id: [commits naming it, mutation: lines across them]}, or None."""
    log = gout(repo, "log", "--format=%x1e%H%x00%s%x00%b", "HEAD")
    if log is None:
        return None
    ev = {}
    for rec in log.split("\x1e"):
        if "\x00" not in rec:
            continue
        _sha, subj, body = (rec.split("\x00", 2) + [""])[:3]
        muts = len(MUTATION_LINE.findall(body))
        reqs = len(REQ_LINE.findall(body))
        for tid in subject_tasks(subj):
            entry = ev.setdefault(tid, [0, 0, 0])
            entry[0] += 1
            entry[1] += muts
            entry[2] += reqs
    return ev


_PC = None


def _prove_claim():
    """prove-claim.py, loaded once: the record format and its validator live there."""
    global _PC
    if _PC is None:
        spec = importlib.util.spec_from_file_location(
            "prove_claim", Path(__file__).resolve().parent / "prove-claim.py")
        _PC = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PC)
    return _PC


def proof_kept_local(repo, stem):
    """True when the plan's proof records are on disk, none is tracked, and git ignores all of them.

    Tracking decides first, in the index AND at HEAD: a tracked record is read from HEAD
    even if proof/ is later ignored or the record dropped from the index, so an
    uncommitted edit to it is never trusted. Untracked records that git does not ignore
    were forgotten rather than kept local on purpose — one such record is enough — so
    they stay "no record" in committed mode.
    """
    pc = _prove_claim()
    where = f"{pc.PROOF_DIR}/{stem}/"
    for tracked in (gout(repo, "ls-files", "--", where),
                    gout(repo, "ls-tree", "-r", "--name-only", "HEAD", "--", where)):
        if tracked is None or tracked.strip():
            return False
    base = Path(repo) / pc.PROOF_DIR / stem
    records = sorted(base.glob("*/*.json")) if base.is_dir() else []
    if not records:
        return False
    # One call per record: check-ignore's batch output quotes unusual paths.
    return all(gout(repo, "check-ignore", "-q", "--", r.relative_to(Path(repo)).as_posix())
               is not None for r in records)


def proof_records(repo, plan):
    """{task: {(kind, k): problems}} for the plan's proof records, or None.

    Committed records (the default) are read from the COMMITTED tree and validated against
    the fingerprint of the commit that last wrote each record: proof is bound to the code
    committed with it, so a record that does not match its own commit was proven on some
    other tree. A project may instead keep proof/ out of git, because a record copies the
    plan's path and wording and the plans live outside the repo. Then the records are read
    from disk and bound to the commits whose subject names their task, or to a `Stage N green`
    commit for their stage's number (the tree the gate's verifier proves on; any such commit
    in HEAD's history binds, an earlier plan's included, as any commit naming the task
    does): a record matching none of them was proven on a tree that was never committed. `problems` is [] for a
    valid record.
    """
    pc = _prove_claim()
    stem = Path(plan).stem
    try:
        blocks = {t["id"]: t for t in task_blocks(Path(plan).read_text(errors="replace"))}
    except OSError:
        blocks = {}

    def clause(task, kind, k):
        """The plan's current wording of the clause a record proves, or None."""
        t = blocks.get(task)
        if t is None:
            return None
        items = claim_clauses(t["test"]) if kind == "claim" else requirement_clauses(t["desc"])
        return items[k - 1] if 1 <= k <= len(items) else None

    pat = re.compile(rf"{pc.PROOF_DIR}/{re.escape(stem)}/(\d+\.\d+)/"
                     r"(claim|req|deviation)-(\d+)\.json$")
    fps = {}

    def fingerprint(sha):
        if sha and sha not in fps:
            try:
                fps[sha] = pc.commit_fingerprint(repo, sha)
            except Exception:  # noqa: BLE001 — an unreadable commit is a problem, not a crash
                fps[sha] = None
        return fps.get(sha)

    local = proof_kept_local(repo, stem)
    if local:
        base = Path(repo) / pc.PROOF_DIR / stem
        entries = []
        for f in sorted(base.glob("*/*.json")) if base.is_dir() else []:
            rel = f"{pc.PROOF_DIR}/{stem}/{f.parent.name}/{f.name}"
            try:
                raw = f.read_text()
            except OSError:
                raw = None
            entries.append((rel, raw))
        log = gout(repo, "log", "--format=%H%x00%s", "HEAD") or ""
        task_shas, green_shas = {}, {}
        for line in log.splitlines():
            sha, _, subj = line.partition("\x00")
            for tid in subject_tasks(subj):
                task_shas.setdefault(tid, []).append(sha)
            # On Cursor every task is proven at its stage's gate, on the tree the
            # `Stage N green` commit records, so that commit is a binding too. Any plan's
            # commit for that stage number binds, as any commit naming the task does.
            green = STAGE_GREEN.match(subj.strip())
            if green:
                green_shas.setdefault(green.group(1), []).append(sha)
    else:
        listing = gout(repo, "ls-tree", "-r", "--name-only", "HEAD", "--",
                       f"{pc.PROOF_DIR}/{stem}/")
        if listing is None:
            return None
        entries = [(rel, gout(repo, "show", f"HEAD:{rel}")) for rel in listing.split()]

    def judge(rec, fp, kind, task, k, text, rel):
        """(problems, notes) for one record against one fingerprint."""
        notes = {}
        if not fp:
            return ["its commit is unreadable"], notes
        if text is None:
            return [f"the plan has no {kind} {k} in Task {task}"], notes
        if kind == "claim" and isinstance(rec, dict) and rec.get("kind") == "claim-deviation":
            problems = claim_deviation_problems(rec, fp, (kind, task, k, text))
            if not problems:
                # Disclosed, not proven: the claim stays open, finding 8 names it.
                notes[("claim-deviation", k)] = rec["why"].strip()
                problems = ["recorded as a claim deviation"]
            return problems, notes
        try:
            problems = pc.validate(rec, fp, (kind, task, k, text), allow_legacy=True)
        except Exception as e:  # noqa: BLE001 — a record that crashes is not valid
            problems = [f"malformed record ({e.__class__.__name__})"]
        if not problems and pc.is_legacy(rec) and local:
            # No commit added it, so its add date — what makes schema 1 legacy — is unknown.
            problems = ["a schema-1 record kept outside git — its add date is unknown, and it "
                        "was never shown able to fail"]
        elif not problems and pc.is_legacy(rec):
            added = first_added(repo, rel)
            if added is None or added >= datetime.datetime.fromisoformat(LEGACY_CUTOFF):
                problems = ["a schema-1 req check added after the schema-2 cutover "
                            "— never shown able to fail"]
        if kind == "req" and isinstance(rec, dict) and "covered_by_claim" in rec:
            notes[("cites", k)] = rec["covered_by_claim"]
        if not problems and pc.is_legacy(rec):
            # A schema-1 req check: seen to pass, never to fail. Counted as met so
            # history is not re-litigated, and reported (finding 9, advisory).
            notes[("legacy", k)] = True
        return problems, notes

    out = {}
    for rel, raw in entries:
        m = pat.match(rel)
        if not m:
            continue
        try:
            rec = json.loads(raw) if raw is not None else {"_unreadable": "unreadable"}
        except (ValueError, RecursionError):  # RecursionError: deep nesting
            rec = {"_unreadable": "not JSON"}
        kind, task, k = m.group(2), m.group(1), int(m.group(3))
        text = clause(task, kind, k)
        if local:
            shas = green_shas.get(task.split(".")[0], []) + task_shas.get(task, [])
            if not shas:
                problems, notes = [f"no commit names Task {task} and no `Stage {task.split('.')[0]} green` commit exists, so the record is bound to no committed tree"], {}
            else:
                # The newest candidate decides (the stage's green commit first), unless another matches.
                # A valid claim deviation matches too: it carries a marker problem, not a fault.
                def matched(p, n, k=k):
                    return not p or ("claim-deviation", k) in n
                problems, notes = judge(rec, fingerprint(shas[0]), kind, task, k, text, rel)
                for sha in shas[1:]:
                    if matched(problems, notes):
                        break
                    p2, n2 = judge(rec, fingerprint(sha), kind, task, k, text, rel)
                    if matched(p2, n2):
                        problems, notes = p2, n2
        else:
            sha = (gout(repo, "log", "-1", "--format=%H", "--", rel) or "").strip()
            problems, notes = judge(rec, fingerprint(sha), kind, task, k, text, rel)
        for key_, val in notes.items():
            out.setdefault(task, {})[key_] = val
        out.setdefault(task, {})[(kind, k)] = problems
    return out


def task_numbers(ids):
    """{'1.1', ...} from task ids, whether bare ('1.1') or whole 'Task 1.1' strings."""
    return {m.group(0) for i in ids for m in [re.search(r"\d+\.\d+", str(i))] if m}


# LEGACY_CUTOFF is the cutover instant: from it on, a req check is schema 2 (proven
# by a break). A schema-1 req check is legacy only when the commit that first added
# it is older than the cutover; one added later is what a hand-written
# record would look like. No writer of schema 1 req records exists, so every
# schema-1 req record is in the second group.
LEGACY_CUTOFF = "2026-10-04T10:07:25+00:00"


def first_added(repo, rel):
    """Commit date (aware datetime) of the commit that first added `rel`, or None."""
    out = gout(repo, "log", "--diff-filter=A", "--format=%cI", "--", rel)
    lines = (out or "").split()
    try:
        return datetime.datetime.fromisoformat(lines[-1]) if lines else None
    except ValueError:
        return None


def proven_tasks(repo, plan):
    """Task ids with at least one valid claim record at HEAD — proof the tool watched.

    Finding 1 credits a task commit once per such task: a commit that carries
    Tasks 1.1 and 1.2 with records for both did the work of two. A subject that
    merely NAMES six tasks still counts once (named-not-proven), because naming costs nothing
    and a valid record cannot be written without the tool watching a real run.
    """
    try:
        recs = proof_records(repo, plan) or {}
    except Exception:  # noqa: BLE001 — no credit is the safe answer
        return set()
    try:
        blocks = {b["id"]: b for b in task_blocks(Path(plan).read_text(errors="replace"))}
    except OSError:
        return set()
    # EVERY claim of the task proven, not one of them: one record would
    # otherwise buy a batched task the same credit as a proven one. A claim
    # deviation is disclosed, not proven, and earns no credit.
    return {t for t, got in recs.items() if t in blocks and every_claim(blocks[t]["test"])
            and all(got.get(("claim", k)) == [] for k in every_claim(blocks[t]["test"]))}


def stray_proof(repo):
    """Committed files under proof/ that are not record paths — proof/ is excluded from
    every fingerprint, so anything there rides along unbound."""
    pc = _prove_claim()
    listing = gout(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", pc.PROOF_DIR)
    if not listing:
        return []
    return [p for p in listing.split("\0") if p and not pc.RECORD_PATH.match(p)]


IN_FLIGHT_PHASES = ("preflight", "task", "gate")


def _state_for(repo, plan):
    """(state, stage) when the run state names THIS plan; else None. The state is read
    by the hooks' own reader, from this plugin's layout, so the audit and the hooks
    agree on which run is in flight."""
    try:
        spec = importlib.util.spec_from_file_location(
            "plan_continue_classify",
            Path(__file__).resolve().parents[3] / "hooks" / "plan_continue_classify.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        state = mod.read_state(str(repo))
        if not isinstance(state, dict):
            return None
        named = Path(str(state["plan"]))
        if not named.is_absolute():
            named = Path(repo) / named
        if named.resolve() != Path(plan).resolve():
            return None
        stage = state["stage"]
        if isinstance(stage, bool) or not isinstance(stage, int):
            return None
        return state, stage
    except Exception:  # noqa: BLE001 — no state read means no stage is exempt
        return None


def _gate_ticked(text, stage):
    """True when any box under `### Stage <stage> Gate` is ticked."""
    gates = gate_box_stages(text)
    return any(ticked and gates.get(ln) == str(stage)
               for ticked, _k, _b, ln, _r in boxes(text))


def _has_green(repo, stage):
    """True/False whether HEAD's history has `Stage <stage> green`; None if git cannot say."""
    subjects = gout(repo, "log", "--format=%s", "HEAD")
    if subjects is None:
        return None
    return any((m := STAGE_GREEN.match(s.strip())) and m.group(1) == str(stage)
               for s in subjects.splitlines())


def unrecorded_gate(repo, plan):
    """The stage, as a string, that is claimed done but has no `Stage N green` commit;
    else None.

    Claimed done means the run state names this plan with phase `stage-complete` or
    `closeout`, or the plan's own gate boxes for that stage are ticked. The git hook
    checks proof on the `Stage N green` commit, so a stage that ticks its gate and never
    makes that commit is never checked; the Cursor stop hook asks this function and
    holds the turn until the gate is run. Phase `blocked` or `handoff` is a recorded
    stop and answers None. Unreadable or unexpected input answers None (the stop hook
    fails open)."""
    got = _state_for(repo, plan)
    if got is None:
        return None
    state, stage = got
    phase = str(state.get("phase", "")).strip().lower()
    if phase in ("blocked", "handoff"):
        return None
    claimed = phase in ("stage-complete", "closeout")
    if not claimed:
        try:
            claimed = _gate_ticked(Path(plan).read_text(errors="replace"), stage)
        except OSError:
            return None
    if not claimed or _has_green(repo, stage) is not False:
        return None
    return str(stage)


def open_stage(repo, plan):
    """The stage whose proof is not yet due, as a string, or None.

    It is the stage the run state names for THIS plan while that stage is still being
    worked (phase preflight, task or gate), its gate boxes are not ticked, and the
    history holds no `Stage N green` commit for it. Anything else answers None, which
    holds every ticked task to its proof: a stage that claims its gate passed, with
    every box ticked and nothing committed, is not exempt."""
    got = _state_for(repo, plan)
    if got is None:
        return None
    state, stage = got
    if str(state.get("phase", "")).strip().lower() not in IN_FLIGHT_PHASES:
        return None
    try:
        if _gate_ticked(Path(plan).read_text(errors="replace"), stage):
            return None
    except OSError:
        return None
    if _has_green(repo, stage) is not False:
        return None
    return str(stage)


def scan_task_mutations(path, text, repo):
    """Finding 8 — a ticked task whose required Test claims are not proven.

    A claim is proven by a prove-claim.py record: the tool watched the test pass,
    fail under the break, and the tree come back. `mutation:` lines in commit
    bodies are the retired, self-reported form — an executor can write false ones —
    so a task carrying only those is "legacy, unverified" (advisory): never
    clean, never blocking, and a plan executed before the tool stays visible
    without being re-run.
    """
    ev, proofs = task_commit_evidence(repo), proof_records(repo, path)
    if ev is None or proofs is None:
        return None
    out = []
    stray = stray_proof(repo)
    if stray:
        out.append({"finding": 8, "severity": "blocking", "file": str(path), "line": None,
                    "text": "proof/",
                    "rule": f"{len(stray)} file(s) under proof/ are not proof records — proof/ is "
                            f"outside every fingerprint, so nothing else may live there: "
                            f"{', '.join(stray[:5])}"})
    stem = Path(path).stem
    if proof_kept_local(repo, stem):
        out.append({"finding": 8, "severity": "advisory", "file": str(path), "line": None,
                    "text": f"{_prove_claim().PROOF_DIR}/{stem}/",
                    "rule": f"proof records for {stem} are kept outside git: each is read from "
                            "disk and bound to its stage's `Stage N green` commit or to the commits "
                            "naming its task in their subject"})
    in_flight = open_stage(repo, path)
    for tid, line, test in ticked_tasks(text):
        if tid.split(".")[0] == in_flight:
            continue  # proven at its stage gate, which has not happened yet
        required = every_claim(test)
        n = len(required)
        got = proofs.get(tid, {})
        commits, muts = ev.get(tid, [0, 0, 0])[:2]
        unproven = [k for k in required if got.get(("claim", k), ["no record"])]
        devs = [k for k in unproven if ("claim-deviation", k) in got]
        unproven = [k for k in unproven if k not in devs]
        base = {"finding": 8, "file": str(path), "line": line, "text": f"Task {tid}"}
        if devs:
            out.append({**base, "severity": "advisory",
                        "rule": f"Task {tid}: claim(s) {devs} recorded as deviations, not proven — "
                                + "; ".join(f"claim {k}: {got[('claim-deviation', k)]}"
                                            for k in devs[:4])})
        if not unproven:
            continue
        if commits == 0 and not got:
            out.append({**base, "severity": "advisory",
                        "rule": f"ticked task has no commit naming 'Task {tid}' in "
                                f"{repo.name} — per-task commits are mandatory"})
        elif not got and muts:
            out.append({**base, "severity": "advisory",
                        "rule": f"Task {tid}: legacy, unverified — {muts} self-reported "
                                "`mutation:` line(s) and no proof record; nothing shows "
                                "its test can fail"})
        else:
            why = "; ".join(f"claim {k}: {(got.get(('claim', k)) or ['no record'])[0]}"
                            for k in unproven[:4])
            out.append({**base, "severity": "blocking",
                        "rule": f"Task {tid}: {len(unproven)} of {n} required claim(s) have no "
                                f"valid proof record — {why}"})
    return out


def scan_task_requirements(path, text, repo):
    """Finding 9 — a ticked task whose description's requirements are not shown met.

    Each requirement clause needs a valid `req-K.json` (a passing check, or a
    proven claim covering it) or a `deviation-K.json` (reported, advisory). A task
    with no commit is finding 8's to report. Legacy `req:` lines alone: advisory.
    """
    ev, proofs = task_commit_evidence(repo), proof_records(repo, path)
    if ev is None or proofs is None:
        return None
    out = []
    in_flight = open_stage(repo, path)
    for t in task_blocks(text):
        if not t["line"] or t["id"].split(".")[0] == in_flight:
            continue
        n = count_requirements(t["desc"])
        got = proofs.get(t["id"], {})
        commits, _muts, reqs = ev.get(t["id"], [0, 0, 0])
        if n == 0 or (commits == 0 and not got):
            continue
        open_, devs, legacy = [], [], []
        n_claims = count_claims(t["test"])
        for k in range(1, n + 1):
            req, dev = got.get(("req", k)), got.get(("deviation", k))
            cites = got.get(("cites", k))
            if req == [] and cites is not None and (
                    not isinstance(cites, int) or not 1 <= cites <= n_claims
                    or got.get(("claim", cites)) != []):
                # A req "covered by claim J" is only as good as claim J's proof.
                req = [f"cites claim {cites}, which is missing or not a valid proof"]
            if req == []:
                if got.get(("legacy", k)):
                    legacy.append(k)
                continue
            if dev == []:
                devs.append(k)
                continue
            open_.append((k, (req or dev or ["no record"])[0]))
        base = {"finding": 9, "file": str(path), "line": t["line"], "text": f"Task {t['id']}"}
        if open_ and not got and reqs:
            out.append({**base, "severity": "advisory",
                        "rule": f"Task {t['id']}: legacy, unverified — {reqs} self-reported "
                                "`req:`/`deviation:` line(s) and no proof record"})
        elif open_:
            # Advisory, never blocking: no blocking mandate until measured.
            why = "; ".join(f"requirement {k}: {p}" for k, p in open_[:4])
            out.append({**base, "severity": "advisory",
                        "rule": f"Task {t['id']}: {len(open_)} of {n} requirement(s) not "
                                f"shown met — {why}"})
        elif devs:
            out.append({**base, "severity": "advisory",
                        "rule": f"Task {t['id']}: requirement(s) {devs} recorded as "
                                "deviations — name each in the gate report"})
        if not open_ and legacy:
            out.append({**base, "severity": "advisory",
                        "rule": f"Task {t['id']}: requirement(s) {legacy} checked by legacy "
                                "schema-1 records — the check was seen to pass, never to fail"})
    return out


def live_check_stages(text):
    """Stage numbers whose `### Stage N Gate` holds a `**Live check` box."""
    lines = text.splitlines()
    return {stage for i, stage in gate_box_stages(text).items()
            if LIVE_CHECK.match(lines[i - 1])}


def scan_live_remediations(path, text, repo):
    """Finding 10 — a live-check gate's remediation commit with no fixture sweep.

    Read from the PROJECT repo's history, from the plan's own date on (its
    filename's YYYY-MM-DD prefix): a `Stage 1 gate remediation` from a plan the
    repo executed earlier is not this plan's. Advisory, always — see LIVE_CHECK.
    """
    log = gout(repo, "log", "--date=short", "--format=%x1e%H%x00%cd%x00%s%x00%b", "HEAD")
    if log is None:
        return None
    stages = live_check_stages(text)
    m = PLAN_DATE.match(Path(path).name)
    since = m.group(1) if m else ""
    out = []
    for rec in log.split("\x1e"):
        if rec.count("\x00") < 3:
            continue
        sha, date, subj, body = rec.split("\x00", 3)
        hit = REMEDIATION.search(subj)
        if not hit or date < since or hit.group(1) not in stages:
            continue
        if FIXTURE_SWEEP.search(body):
            continue
        out.append({
            "finding": 10, "severity": "advisory",
            "rule": f"Stage {hit.group(1)}'s gate has a **Live check line and this "
                    "remediation commit records no `fixture-sweep:` trailer — say in "
                    "the gate report whether the round re-ran the live check, and "
                    "against which captures the fix was proven first",
            "file": str(path), "line": None, "commit": sha[:8], "text": subj.strip(),
        })
    return out


def linked_plans(path, text):
    """Sub-plans referenced from this plan, confined to its own subtree."""
    root, found, seen = path.resolve().parent, [], set()
    for line in text.splitlines():
        for m in list(MD_LINK.finditer(line)) + list(BARE_MD.finditer(line)):
            try:
                cand = (root / m.group(1)).resolve()
            except (OSError, ValueError):
                continue
            # Containment: a plan may link its siblings, never `../elsewhere`.
            if root not in cand.parents and cand.parent != root:
                continue
            if cand == path.resolve() or cand in seen or not cand.is_file():
                continue
            seen.add(cand)
            found.append(cand)
    return found


def register_ticks(text):
    """Ticks inside a `## Sub-plans` register."""
    out, in_reg = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*#{1,4}\s", line):
            in_reg = bool(re.match(r"^\s*#{1,4}\s+Sub-plans\b", line, re.I))
            continue
        if in_reg and re.search(r"\[[xX]\]", line):
            out.append((i, line.strip()))
    return out


def scan_completed_over_void(path, text, vocab, own_dirty):
    """Finding 4 — a done-marker standing over a self-voiding gate line."""
    dirty = list(own_dirty)
    for sub in linked_plans(path, text):
        try:
            dirty += scan_void_ticks(sub, sub.read_text(errors="replace"), vocab)
        except OSError:
            continue
    if not dirty:
        return []

    sev = "blocking" if any(d.get("severity") == "blocking" for d in dirty) else "advisory"
    # Cite the blocking entries FIRST: a reader told "blocking" and handed four
    # advisory citations has been pointed away from the evidence.
    ordered = ([d for d in dirty if d.get("severity") == "blocking"]
               + [d for d in dirty if d.get("severity") != "blocking"])
    ev = "; ".join(f"{Path(d['file']).name}:{d['line']}" for d in ordered[:4])
    if len(ordered) > 4:
        ev += f" (+{len(ordered) - 4} more)"

    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if COMPLETED.match(line):
            out.append({
                "finding": 4, "severity": sev,
                "rule": "**Completed:** stands over a gate line that voids itself",
                "file": str(path), "line": i, "text": line.strip(), "evidence": ev,
            })
    for i, line in register_ticks(text):
        out.append({
            "finding": 4, "severity": sev,
            "rule": "master-register tick stands over a gate line that voids itself",
            "file": str(path), "line": i, "text": line, "evidence": ev,
        })
    return out


# ------------------------------------------------------------------ history

def file_at(repo, rev, rel):
    """File text at a rev, '' when genuinely absent there, None when git failed.

    Existence is decided by `git cat-file -e`'s EXIT STATUS, not by matching
    English in git's stderr. A string-matching test with a catch-all on the
    substring "path" would let a repo path merely containing that word turn an
    unrelated git failure into "file absent" -- which this function reports as
    "" and the caller reads as an empty, clean file.
    """
    if gout(repo, "cat-file", "-e", f"{rev}:{rel}") is None:
        # Distinguish "the rev itself is unreachable" (a real failure) from
        # "the rev is fine, the path is not in it" (genuinely absent).
        if gout(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}") is None:
            return None
        return ""
    out, _err = git(repo, "show", f"{rev}:{rel}")
    return out


def touched_paths(repo, sha):
    """Added/modified paths at a commit, plus its raw --name-status rows."""
    rows = [r for r in (gout(repo, "show", "--name-status", "-M", "--format=", sha)
                        or "").split("\n") if r.strip()]
    am = [r.split("\t", 1)[1] for r in rows
          if "\t" in r and r.split("\t", 1)[0][:1] in ("A", "M")]
    return am, rows


def rename_source(rows, rel):
    """The pre-rename path of `rel` at this commit, or None.

    Without this, `git mv` fabricates a full bulk-flip finding: the parent
    lookup uses the CURRENT path, finds nothing there, and every already-ticked
    box reads as newly ticked. Under "a finding is a RED gate" that turns an
    ordinary plan-file reorganisation into a failed gate.
    """
    for row in rows:
        parts = row.split("\t")
        if parts and parts[0].startswith("R") and len(parts) == 3 and parts[2] == rel:
            return parts[1]
    return None


def newly_ticked(repo, sha, rel, rows=None):
    """Boxes ticked at `sha` that were not ticked at its parent.

    State comparison, not diff pairing — see the module docstring. Returns
    (entries, error) where entries are (key, body, line) and a non-None error
    means this commit could not be examined and the caller must NOT treat it as
    clean.
    """
    after = file_at(repo, sha, rel)
    if after is None:
        return None, f"could not read the plan at {sha[:8]}"
    parents = gout(repo, "rev-list", "--parents", "-n", "1", sha)
    before = ""
    if parents and len(parents.split()) > 1:
        # Follow a rename so the parent lookup compares like with like.
        prev_rel = rename_source(rows or [], rel) or rel
        before = file_at(repo, f"{sha}^", prev_rel)
        if before is None:
            return None, f"could not read the plan at {sha[:8]}^"
    return tick_delta(before, after), None


def tick_delta(before, after):
    """Boxes ticked in `after` that were not ticked in `before`: (key, body, line).

    Counter, not set: 21 gate boxes reading the same text are 21 boxes. Set
    membership would collapse them to one and hand the bulk-flip rule a count
    of 1, which is a bypass you get for free by writing repetitive gates.
    """
    prev = Counter(k for t, k, _b, _l, _r in boxes(before) if t)
    seen, res = Counter(), []
    for t, k, b, ln, _r in boxes(after):
        if not t:
            continue
        seen[k] += 1
        if seen[k] > prev[k]:
            res.append((k, b, ln))
    return res


def gate_box_stages(text):
    """{line number: stage} for every box under a `### Stage N Gate` heading."""
    out, stage = {}, None
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*#{1,5}\s", line):
            m = GATE_HEAD.match(line)
            stage = m.group(1) if m else None
            continue
        if stage and (BULLET_BOX.match(line) or LABELED_BOX.match(line)):
            out[i] = stage
    return out


def green_stages(subjects):
    """Stage numbers that have a `Stage N green` commit among `subjects`."""
    return {m.group(1) for s in subjects for m in [STAGE_GREEN.match(s.strip())] if m}


def preflight_lines(text):
    """Line numbers (1-based, as boxes() reports them) inside the `## Preflight` section."""
    out, inside = set(), False
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*#{1,4}\s", line):
            inside = bool(re.match(r"^\s*#{1,4}\s+Preflight\b", line, re.I))
            continue
        if inside:
            out.add(i)
    return out


def unbacked(entries, text, green, probed=False, cap=0):
    """Flips finding 1 counts: all but the gate boxes of a stage whose `Stage N green`
    commit is in the range. A gate's boxes are ticked together with that commit —
    that is the procedure, not a bulk flip — and counting them would make every
    honest plan trip finding 1 at its second gate (5 task flips + 2 gate boxes =
    7 > 6), and then never again once task commits reach the threshold.

    Likewise the Preflight boxes once a probe artefact backs them (`probed`: the same
    evidence that clears finding 3) — but only up to `cap` of them. Six Preflight boxes
    and three task ticks would make an honest first gate 9 > 6; a probe file is
    blind to which box it backs, so it may not clear more Preflight boxes than the
    threshold would tolerate with no evidence at all. Membership is by line, never by
    text: a gate box repeating a Preflight line verbatim is not a Preflight box."""
    gates = gate_box_stages(text)
    out = [e for e in entries if gates.get(e[2]) not in green]
    if probed:
        pre = preflight_lines(text)
        pf = [e for e in out if e[2] in pre]
        if len(pf) <= cap:
            out = [e for e in out if e[2] not in pre]
    return out


def preflight_keys(text):
    out, inside = set(), False
    for line in text.splitlines():
        if re.match(r"^\s*#{1,4}\s", line):
            inside = bool(re.match(r"^\s*#{1,4}\s+Preflight\b", line, re.I))
            continue
        if inside:
            for _t, k, _b, _l, _r in boxes(line):
                out.add(k)
    return out


def history_findings(repo, rel, path, text, since, threshold):
    """Findings 1, 3, 5. Returns (findings, errors)."""
    # --follow so a renamed plan keeps its history rather than looking new.
    shas_out = gout(repo, "log", "--format=%H", "--reverse", "--follow",
                    f"{since}..HEAD", "--", rel)
    if shas_out is None:
        return [], ["could not list commits touching the plan"], 0
    shas = shas_out.split()

    # Commits, not mentions: count COMMITS whose subject matches, not regex occurrences -- one
    # subject reading "Task 1.1 Task 1.2 ... Task 1.6" is one commit. And a task
    # commit must contain WORK: six `git commit --allow-empty -m "Task 1.N"`,
    # or six commits touching only the plan file, otherwise buy a free pass
    # through the bulk-flip rule for the price of six empty commits.
    subj_out = gout(repo, "log", "--format=%H%x00%s", f"{since}..HEAD")
    task_ids, task_commits = set(), 0
    if subj_out:
        for row in subj_out.split("\n"):
            if "\x00" not in row:
                continue
            csha, subj = row.split("\x00", 1)
            ids = sorted(subject_tasks(subj))
            if not ids:
                continue
            am, _rows = touched_paths(repo, csha)
            if not any(pth != rel for pth in am):
                continue
            task_commits += 1
            task_ids.update(i if isinstance(i, str) else i[0] for i in ids)
    # Distinct task identifiers, so six commits all titled "Task 1.1" are one.
    task_commits = min(task_commits, len(task_ids)) if task_ids else task_commits
    task_commits = max(task_commits, len(task_numbers(task_ids) & proven_tasks(repo, path)))

    pre = preflight_keys(text)
    green = green_stages(row.split("\x00", 1)[1] for row in (subj_out or "").split("\n")
                         if "\x00" in row)
    out, errors, total_flips = [], [], 0
    # Finding 1's probe evidence: a probe artefact in this commit or any earlier one in
    # the range (baseline mode reads the whole range; this is the same rule, ordered).
    order = (gout(repo, "rev-list", "--reverse", f"{since}..HEAD") or "").split()
    first_probe = next((i for i, c in enumerate(order)
                        if any(PROBE_PATH.search(p) for p in touched_paths(repo, c)[0])), None)
    position = {c: i for i, c in enumerate(order)}

    for sha in shas:
        touched, rows = touched_paths(repo, sha)
        entries, err = newly_ticked(repo, sha, rel, rows)
        if err:
            errors.append(err)
            continue
        if not entries:
            continue
        probed = any(PROBE_PATH.search(p) for p in touched)
        probed_by = first_probe is not None and position.get(sha, -1) >= first_probe
        counted = unbacked(entries, file_at(repo, sha, rel) or "", green, probed_by, threshold)
        total_flips += len(counted)
        short = sha[:8]
        msg = gout(repo, "log", "-1", "--format=%s%n%b", sha) or ""

        if len(counted) > threshold and task_commits < threshold:
            out.append({
                "finding": 1, "severity": "blocking",
                "rule": (f"{len(counted)} boxes became [x] in one commit with only "
                         f"{task_commits} task commit(s) in the range"),
                "file": str(path), "line": None, "commit": short,
                "text": msg.splitlines()[0] if msg else "",
                "evidence": f"threshold {threshold}",
            })

        if not probed:
            for key, body, line in entries:
                if key in pre or ACCESS_VOCAB.search(body):
                    out.append({
                        "finding": 3, "severity": "blocking",
                        "rule": "access/device box ticked with no probe output "
                                "in the same commit",
                        "file": str(path), "line": line, "commit": short,
                        "text": body,
                        "evidence": f"commit touched: {', '.join(touched[:5]) or '(none)'}",
                    })

        if not REVIEW_REF.search(msg) and not any(REVIEW_PATH.search(p)
                                                  for p in touched):
            for _key, body, line in entries:
                if JUDGMENT.search(body):
                    out.append({
                        "finding": 5, "severity": "blocking",
                        "rule": "(judgment) box ticked with no evaluator or "
                                "reviewer artefact in the commit",
                        "file": str(path), "line": line, "commit": short,
                        "text": body,
                        "evidence": f"subject: {msg.splitlines()[0] if msg else ''}",
                    })

    # Split-the-flip: the same 21 boxes spread over four commits of six
    # defeats every per-commit threshold. Judge the range in aggregate too.
    if (total_flips > threshold and task_commits < threshold
            and not any(f["finding"] == 1 for f in out)):
        out.append({
            "finding": 1, "severity": "blocking",
            "rule": (f"{total_flips} boxes became [x] across {len(shas)} commits "
                     f"in the range with only {task_commits} task commit(s)"),
            "file": str(path), "line": None, "commit": f"{since[:8]}..HEAD",
            "text": "aggregate over the range",
            "evidence": f"threshold {threshold}",
        })
    return out, errors, len(shas)


# ----------------------------------------------------------------- baseline

def baseline_path(root, plan):
    """Where the snapshot of `plan` lives: one file per plan, keyed by its path."""
    key = hashlib.sha256(str(plan.resolve()).encode()).hexdigest()[:16]
    return root / ".claude" / "plan-baseline" / f"{key}.json"


def project_root(args):
    root = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
    if not root.is_dir():
        die(f"--repo is not a directory: {root}")
    return root


def take_snapshot(args):
    """--snapshot: record the plan as loaded, before execution ticks anything."""
    path = Path(args.plan)
    if not path.is_file():
        die(f"plan file not found: {path}")
    root = project_root(args)
    bp = baseline_path(root, path)
    if bp.exists():
        # Refusing is the guard. A baseline re-taken after ticking makes every
        # flip before it invisible, which is the whole fraud this file detects.
        die(f"baseline already exists: {bp}. A second snapshot would launder "
            "every flip made since the first. Delete it by hand only when "
            "starting a NEW execution of this plan.")
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        die(f"cannot read {path}: {e}")
    head = gout(root, "rev-parse", "--verify", "--quiet", "HEAD")
    doc = {
        "plan": str(path.resolve()),
        "captured_at": datetime.datetime.now(datetime.timezone.utc)
                       .isoformat(timespec="seconds"),
        "repo_head": head.strip() if head else None,
        "ticked_at_capture": sum(1 for t, *_ in boxes(text) if t),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text": text,
    }
    try:
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps(doc, indent=1))
    except OSError as e:
        die(f"cannot write baseline {bp}: {e}")
    print(f"plan-flip-audit: baseline written {bp}")
    print(f"  {doc['ticked_at_capture']} box(es) already ticked at capture; "
          f"repo HEAD {doc['repo_head'][:8] if doc['repo_head'] else '(no commits yet)'}")
    return 0


def load_baseline(bp, path):
    """The baseline doc. A baseline that exists but cannot be trusted is exit 2."""
    try:
        doc = json.loads(bp.read_text(errors="replace"))
        text = doc["text"]
        recorded = doc["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        die(f"baseline {bp} is unreadable: {e}")
    if hashlib.sha256(text.encode()).hexdigest() != recorded:
        die(f"baseline {bp} does not match its own hash — it was edited after "
            "capture, so it is not evidence of anything")
    if doc.get("plan") != str(path.resolve()):
        die(f"baseline {bp} records a different plan: {doc.get('plan')}")
    return doc


def baseline_findings(root, path, text, base, threshold):
    """Findings 1, 3, 5 against the baseline. Returns (findings, errors, n).

    Evidence comes from the PROJECT repo's commits since the snapshot's HEAD.
    No repo, or no commits, means no evidence — not a pass.
    """
    flips = tick_delta(base["text"], text)
    since = base.get("repo_head")
    shas = []
    if gout(root, "rev-parse", "--verify", "--quiet", "HEAD"):
        rng = f"{since}..HEAD" if since else "HEAD"
        out, err = git(root, "rev-list", rng)
        if out is None:
            return [], [f"cannot list commits {rng} in {root}: {err}"], 0
        shas = out.split()

    task_ids, task_commits = set(), 0
    probed = reviewed = False
    subjects = []
    for sha in shas:
        msg = gout(root, "log", "-1", "--format=%s%n%b", sha) or ""
        subjects.append(msg.splitlines()[0] if msg else "")
        am, _rows = touched_paths(root, sha)
        ids = sorted(subject_tasks(msg.splitlines()[0] if msg else ""))
        if ids and am:
            task_commits += 1
            task_ids.update(ids)
        if any(PROBE_PATH.search(p) for p in am):
            probed = True
        if REVIEW_REF.search(msg) or any(REVIEW_PATH.search(p) for p in am):
            reviewed = True
    task_commits = min(task_commits, len(task_ids)) if task_ids else task_commits
    task_commits = max(task_commits, len(task_numbers(task_ids) & proven_tasks(root, path)))

    out, where = [], "baseline..HEAD"
    counted = unbacked(flips, text, green_stages(subjects), probed, threshold)
    if len(counted) > threshold and task_commits < threshold:
        out.append({
            "finding": 1, "severity": "blocking",
            "rule": (f"{len(counted)} boxes became [x] since the baseline with "
                     f"only {task_commits} task commit(s) in {root.name}"),
            "file": str(path), "line": None, "commit": where,
            "text": f"baseline captured {base.get('captured_at')}",
            "evidence": f"threshold {threshold}",
        })
    pre = preflight_keys(text)
    if not probed:
        for key, body, line in flips:
            if key in pre or ACCESS_VOCAB.search(body):
                out.append({
                    "finding": 3, "severity": "blocking",
                    "rule": "access/device box ticked since the baseline with no "
                            "probe output committed in the project repo",
                    "file": str(path), "line": line, "commit": where,
                    "text": body,
                    "evidence": f"{len(shas)} commit(s) since the baseline, none "
                                "adding a probe artefact",
                })
    if not reviewed:
        for _key, body, line in flips:
            if JUDGMENT.search(body):
                out.append({
                    "finding": 5, "severity": "blocking",
                    "rule": "(judgment) box ticked since the baseline with no "
                            "evaluator or reviewer artefact in the project repo",
                    "file": str(path), "line": line, "commit": where,
                    "text": body,
                    "evidence": f"{len(shas)} commit(s) since the baseline",
                })
    return out, [], len(shas)


def resolve_since(repo, rel, explicit):
    if explicit:
        if gout(repo, "rev-parse", "--verify", "--quiet",
                f"{explicit}^{{commit}}") is None:
            return None, f"--since {explicit!r} does not resolve to a commit"
        return explicit, f"--since {explicit}"
    # The stage's first commit == the child of the previous "Stage N green".
    # The whole log rather than a fixed window: an `-n 200` cap would silently
    # change the answer on any repo with more commits than the cap since that
    # boundary, which is a wrong result dressed as a default.
    log = gout(repo, "log", "--format=%H%x00%s", "HEAD")
    if log:
        rows = [r for r in log.split("\n") if "\x00" in r]
        for row in rows[1:]:
            sha, subj = row.split("\x00", 1)
            if STAGE_GREEN.match(subj.strip()):
                return sha, f"default: previous stage boundary {sha[:8]} ({subj.strip()})"
    first = (gout(repo, "log", "--format=%H", "--reverse", "--", rel) or "").split()
    if first:
        return first[0], f"default: first commit touching the plan ({first[0][:8]})"
    return None, "no commit in this repository touches the plan file"


# --------------------------------------------------------------------- main

def build(args):
    path = Path(args.plan)
    if not path.is_file():
        die(f"plan file not found: {path}")
    if args.vocab_replace and not args.vocab_file:
        die("--vocab-replace requires --vocab-file (alone it is a silent no-op)")
    if args.flip_threshold < 1:
        die("--flip-threshold must be >= 1 "
            "(0 would silently disable the bulk-flip check)")
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        die(f"cannot read {path}: {e}")

    vocab = compile_vocab(args.vocab_file, args.vocab_replace)
    coverage = {}
    own_dirty = scan_void_ticks(path, text, vocab)
    findings = list(own_dirty)
    findings += scan_completed_over_void(path, text, vocab, own_dirty)
    findings += scan_owner_attestation(path, text)
    findings += scan_stale_was_values(path, text)
    checks_run, not_run = list(STATIC_CHECKS), []

    def skip(reason):
        return [{"finding": n, "reason": reason} for n in HISTORY_CHECKS]

    def from_baseline(no_history):
        """No git history for the plan: fall back to its --snapshot baseline."""
        nonlocal checks_run
        root = project_root(args)
        bp = baseline_path(root, path)
        if not bp.is_file():
            return skip(f"{no_history}; no baseline at {bp} — run "
                        "`plan-flip-audit.py <plan> --snapshot` when the plan "
                        "is loaded, before anything is ticked")
        base = load_baseline(bp, path)
        hf, errors, examined = baseline_findings(
            root, path, text, base, args.flip_threshold)
        if errors:
            return [{"finding": n, "reason": "; ".join(errors[:3])}
                    for n in HISTORY_CHECKS]
        findings.extend(hf)
        coverage["since_note"] = (
            f"baseline {bp.name} captured {base.get('captured_at')} with "
            f"{base.get('ticked_at_capture', '?')} box(es) already ticked")
        coverage["commits_examined"] = examined
        coverage["baseline"] = str(bp)
        checks_run = sorted(set(checks_run) | set(HISTORY_CHECKS))
        return []

    top, err = git(path.resolve().parent, "rev-parse", "--show-toplevel")
    if top is None:
        not_run = from_baseline(f"{path.parent}: {err}")
    else:
        repo = Path(top.strip())
        try:
            rel = str(path.resolve().relative_to(repo))
        except ValueError:
            rel = str(path.resolve())
        # Untracked plan: a plan that is untracked has no history, however much the
        # REPOSITORY has. Without this the tool would report every check run
        # over zero commits and exit 0 — a clean bill it never earned.
        tracked = gout(repo, "ls-files", "--error-unmatch", "--", rel) is not None
        if not tracked:
            not_run = from_baseline(f"{path.name} is not tracked in {repo}")
        else:
            since, note = resolve_since(repo, rel, args.since)
            if since is None:
                not_run = skip(note)
            else:
                hf, errors, examined = history_findings(
                    repo, rel, path, text, since, args.flip_threshold)
                findings += hf
                coverage["since"] = since
                coverage["since_note"] = note
                coverage["commits_examined"] = examined
                if errors:
                    not_run = [{"finding": n, "reason": "; ".join(errors[:3])}
                               for n in HISTORY_CHECKS]
                elif examined == 0:
                    # A range with no commits touching the plan examined nothing.
                    # Reporting every check as run there is the module docstring's own failure
                    # mode: a clean bill over checks that never ran.
                    not_run = skip(f"no commit in {note} touches {path.name} — "
                                   "history-based checks examined nothing")
                else:
                    checks_run = sorted(set(STATIC_CHECKS) | set(HISTORY_CHECKS))

    # Finding 8 reads the PROJECT repo, where the task commits are. Only an
    # explicit --repo names it: a cwd guess could read some other repo's
    # history and report a clean bill for this plan.
    if args.repo:
        root = project_root(args)
        top8 = gout(root, "rev-parse", "--show-toplevel")
        has_head = top8 and gout(root, "rev-parse", "--verify", "--quiet", "HEAD")
        f8 = scan_task_mutations(path, text, Path(top8.strip())) if has_head else None
        f9 = scan_task_requirements(path, text, Path(top8.strip())) if has_head else None
        f10 = scan_live_remediations(path, text, Path(top8.strip())) if has_head else None
        for n, fs in ((8, f8), (9, f9), (10, f10)):
            if fs is None:
                not_run.append({"finding": n, "reason": f"{root} is not a git repository "
                                f"with commits — finding {n} reads the task commits there"})
            else:
                findings.extend(fs)
                checks_run = sorted(set(checks_run) | {n})
    else:
        for n in (8, 9, 10):
            not_run.append({"finding": n, "reason": f"no --repo: finding {n} reads the task "
                            "commits in the project repo; pass --repo <project root>"})

    findings.sort(key=lambda f: (f["finding"], f.get("line") or 0))
    doc = {
        "plan": str(path),
        "findings": findings,
        "checks_run": checks_run,
        "checks_not_run": not_run,
    }
    doc.update(coverage)
    return doc


def report(doc, args):
    findings, not_run = doc["findings"], doc["checks_not_run"]
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        if findings:
            print(f"plan-flip-audit: {len(findings)} finding(s) in {doc['plan']}")
            for f in findings:
                loc = f"{f['file']}:{f['line']}" if f.get("line") else \
                      f"{f['file']}:{f.get('commit', '?')}"
                print(f"  [finding {f['finding']} · {f.get('severity','blocking')}] {loc}")
                print(f"      {f['rule']}")
                print(f"      {f['text']}")
                if f.get("evidence"):
                    print(f"      evidence: {f['evidence']}")
        else:
            print(f"plan-flip-audit: no findings in {doc['plan']}")
        print(f"  checks run: {', '.join(str(c) for c in doc['checks_run'])}")
        if doc.get("baseline"):
            print(f"  range: {doc['since_note']} — "
                  f"{doc.get('commits_examined', 0)} project commit(s) since")
        elif doc.get("since_note"):
            print(f"  range: {doc['since_note']} — "
                  f"{doc.get('commits_examined', 0)} commit(s) touching the plan")

    if not_run:
        ns = ", ".join(str(c["finding"]) for c in not_run)
        print(f"plan-flip-audit: NOT RUN — findings {ns}: {not_run[0]['reason']}",
              file=sys.stderr)
        print("plan-flip-audit: this run checked only the file on disk; "
              "it is not a clean bill for the checks above.", file=sys.stderr)

    if any(f.get("severity") == "blocking" for f in findings):
        return 1
    if findings:
        # Advisory only: real findings that need naming in the gate report, but
        # not a RED gate. If both returned 1, a caller gating on $? could not
        # tell them apart, which would make the severity split unusable by the
        # very invocation the skill mandates.
        return 4
    if not_run and args.require_all_checks:
        return 3
    return 0


def main():
    _warn_if_stale()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("plan")
    ap.add_argument("--since")
    ap.add_argument("--flip-threshold", type=int, default=6)
    ap.add_argument("--vocab-file",
                    help="file of extra regex patterns, one per line; EXTENDS the "
                         "built-in vocabulary unless --vocab-replace is given")
    ap.add_argument("--vocab-replace", action="store_true",
                    help="use --vocab-file INSTEAD of the built-in vocabulary "
                         "(disables all built-in patterns)")
    ap.add_argument("--require-all-checks", action="store_true",
                    help="exit 3 when any check could not run, even with no findings")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--snapshot", action="store_true",
                    help="record the plan as loaded into <repo>/.claude/plan-baseline/ "
                         "and exit; refuses if a baseline already exists")
    ap.add_argument("--repo",
                    help="the project repo the plan is executed in (default: cwd); "
                         "holds the baseline and supplies the evidence commits")
    args = ap.parse_args()
    if args.snapshot:
        sys.exit(take_snapshot(args))
    sys.exit(report(build(args), args))


if __name__ == "__main__":
    try:
        main()
    except Bail as e:
        print(f"plan-flip-audit: {e}", file=sys.stderr)
        sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:  # never let a crash exit 1 and read as "findings"
        print(f"plan-flip-audit: internal error: {e.__class__.__name__}: {e}",
              file=sys.stderr)
        sys.exit(2)
