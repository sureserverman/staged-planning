#!/usr/bin/env python3
"""Structure suite for the gate-remediation contract — run directly (CI convention):
    python3 core/skills/executing-plans/tests/test-gate-remediation-contract.py

These are PROSE contracts, not behavior. The suite asserts that the skill text
states the rules an executor must follow at a failed gate; it cannot and does not
verify that an executor obeys them. Stated plainly because a structure suite that
implies behavioral coverage is the exact falsehood class `honest-gates` exists to
catch, and the behavioral-claim rule (group 10) names.

What it pins:
  1. The gate's failure branch states its round budget as a NUMBER, and a plan can
     set its own.
  2. That branch uses the file's one severity scale — Critical / Important /
     Suggestion — and no parallel scale.
  3. The pass rule turns on Critical findings, because "the reviewer found nothing"
     is not a state a judgment agent reliably reaches. It is defined BEFORE the
     failure branch, so it applies to every gate result, including an Important-only
     one that never enters that branch. Two kinds of check cover it:
     "exit criterion DEFINED outside the failure branch" is a *placement* check — the
     definition heading precedes the failure branch, and nothing more. The *content*
     checks — "Important findings are FIXED, not filed" and the per-site
     "Importants bound to the exit criterion at: …" loop — reject a restatement that
     names the rule and then opts out of it. **Measured limit**, stated because a
     guard that overstates itself is what this file exists to catch: screening only
     the text between two anchors misses a negation written just before the first
     one, so the screen also reads NEGATION_LOOKBEHIND characters back. A negation
     further away than that still passes; the guard is strongest against *deletion*.
  4. It describes budget-exhaustion escalation carrying a residual list.
  5. It requires the class sweep to be re-run alongside the narrow re-verification.
  6. Every other site in the file that restates what happens to an Important finding
     is bound to the same criterion — the Light-plan pre-gate review and the
     Integration summary. These are siblings of the same defect class, which is why
     they are checked as a set rather than one at a time.
  7. A sweep of planning/skills/, file by file, for the banned singular phrase
     (BANNED_PHRASE below), which treats one gate repair as one instance. It is a
     sweep because the class-repair rule asks for one: a check of a single site
     stays green while a sibling site carries the phrase.
  8. The Step 3.5 evaluator's brief and the close-out evaluator's brief each ask for
     a severity (Blocking / Material / Minor), not a bare pass/fail; at close-out
     only a Blocking finding stops the merge, and both sites say why a silent
     detector is not the bar.
  9. DEFAULT_REMEDIATION_BUDGET equals the default the
     skill prose documents. One copy in the renderer serves two consumers —
     the bar's `↻N/M` and `--budget-check`'s ceiling — and nothing but this
     assertion couples it to the prose that states the same number.
 10. honest-gates states the behavioral-claim rule with both sub-rules, and the
     three executing-plans sites that must apply it cite it: the per-task review
     brief, the stage review brief, and the skip for docs-only diffs, which also
     names its exception for docs that assert executable behavior. Checked as a set,
     printing each site. Whether a sentence asserts behavior is beyond any script,
     so the mechanical part is that the rule is stated and cited wherever it is used.
 11. (dispatch-fidelity) The dispatch and review contract, pinned at one assertion per
     rule: `Parallel: YES` obligates dispatch (including a lone ready task), Preflight
     probes and rosters it, each per-task commit carries a one-line executor trailer,
     the gate reports dispatched-vs-inline, an unperformable dispatch or review is a
     Stop condition, review skips are closed at two reasons, an opt-out is evidenced,
     and both report sites name the reviewer and the diff.
 11b/c/d. (dispatch precedence) A plan's mandated dispatch needs no
     confirmation turn — the standing caution against calling the Agent tool is
     conditional and the plan's approval IS the request. Pinned with its BOUND at
     equal weight (no plan in play → the caution stands and you ask) and with the
     over-correction recorded as its own failure, because the rule can fail in BOTH
     directions and a guard pinning only the permissive half would readmit the
     second. Plus: the rule appears in both files that decide a dispatch (a set),
     and a sweep of the whole marketplace finds no skill that adds a confirmation
     turn back.
 12. (class repair) The class-repair rule has its own trunk section, states that it
     fires outside a gate, is priced as a command rather than a dispatch,
     carries its outer bound and its un-nameable-class disclosure, and is reached
     from every site where a defect can surface — that last one checked as a SET,
     printing the specific unwired site, since a single-site check stays green
     while a sibling site is unwired.

     **Deliberately small.** One assertion per rule. Pinning English with regexes
     regresses: each guard is prose-dependent, so it needs a meta-guard, which needs a
     meta-meta-guard, and a large harness of them generates more defects than the rules
     it guards. These catch DELETION of a rule, which is how a rule decays; they do not
     pretend to catch every rewording, and no meta-layer is added to make them pretend
     harder.
"""
import os
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
SKILLS_ROOT = HERE.parent.parent  # planning/skills/

# Assembled at runtime rather than written literally: this file lives inside the
# tree it sweeps, so a literal occurrence would make both this check and a gate's
# `! grep -rn ... planning/skills/` permanently red against the very test that
# enforces the rule.
#
# Built with `join`, not `"the culprit " + "task"`: the compiler folds a `+` of two
# string constants into one constant, so the whole phrase would land in the cached
# bytecode under __pycache__, which the sweep below and a gate's `grep -r` both read,
# and the sweep would flag its own bytecode. A `join` call runs at runtime and is
# never folded.
BANNED_PHRASE = " ".join(("the", "culprit", "task"))

FAILURES = []
RAN = []


def ws(pattern):
    """A literal phrase as a wrap-tolerant pattern: every space may be any whitespace run."""
    return re.sub(r" ", r"\\s+", pattern)


def check(name, ok, detail=""):
    RAN.append(name)
    if not ok:
        FAILURES.append(f"{name}: {detail or 'assertion failed'}")


# Matched on word boundaries: a plain substring test finds "not " inside "cannot" and
# "never " inside "whenever", and rejects correct prose.
# The softer words in the second half matter as much as the hard ones: a rule is more
# often weakened than reversed, and "is waived" or "though this is optional" withdraw
# it with no word from the first half. `may` is left out on purpose: the permissive
# sub-plan `Parallel` rule uses it correctly, and banning it fails true prose. Any
# negation list fits one body of text, never all prose.
NEGATION_RE = re.compile(
    r"\b(?:not|never|no|without|isn't|aren't|doesn't|don't|exempt|"
    r"rather than|instead of|unless|except|excluding|optional|optionally|"
    r"waived?|waives|unnecessary|advisory|discretionary|recommended|"
    r"need not|nor)\b",
    re.I,
)

# Availability-based excuses for skipping a review. Scoped to the review/evaluator SUBJECT
# rather than the sentence shape: "Absence of a match is not a gate failure" is the same
# grammar and is CORRECT about a platform stage-verify skill, which is conditionally
# applicable where a code reviewer always applies. `[^.\n]` spans never cross a sentence
# boundary, which is what keeps that line out of the sweep. `fall(?:s|ing)?` rather than a
# bare `fall`: this file lives inside the tree the gate greps.
#
# MEASURED LIMIT: four alternations, not a decision procedure. "cannot be found",
# "unreachable", "if the reviewer is currently unavailable, proceed" all express the same
# idea and evade it. It is defence in depth behind the sentence-anchored check below,
# which is what actually binds the rule.
REVIEW_ESCAPE_RE = re.compile(
    r"(?:missing|absent|unavailable|uninstalled)\s+(?:code-)?(?:reviewer|evaluator)"
    r"|(?:reviewer|evaluator)[^.\n]{0,40}\b(?:isn't|is not|not)\s+installed"
    r"|fall(?:s|ing)? back to the goal-evaluator"
    r"|(?:review|reviewer|evaluator)[^.\n]{0,60}(?:is|are)\s+not\s+a\s+gate\s+failure",
    re.I,
)

# How far *before* a match to look for a negation. A screen limited to the text
# BETWEEN two anchors accepts "*never* tied to the **exit criterion**, filed in the
# `backlog`" — a reversal written the way this defect most often comes back.
# Deliberately tight: at 80+ chars it also swallows the legitimate contrastive
# "surfaced … *rather than* auto-fixed — but they are still bound by the …" that the
# Light-plan text uses, and rejects true prose.
NEGATION_LOOKBEHIND = 30


def flat(s):
    """Collapse whitespace runs so a wrapped phrase still matches a literal-space regex.

    Skill prose is hard-wrapped, so `**exit\\n   criterion**` is one phrase to a reader
    and two tokens to `re` (a wrapped check is truncated in both directions); every
    prose assertion below therefore runs against the flattened block, never the raw
    one.
    """
    return re.sub(r"\s+", " ", s)


def affirms(hay, pattern, flags=re.I | re.S):
    """True when `pattern` matches somewhere with no negation token inside the match.

    A guard a negated restatement can satisfy is not a guard: the natural way this
    defect returns is prose that names the rule only to opt out of it ("... are
    surfaced for triage, NOT bound to the exit criterion"). Any single clean match
    is enough — the same block may legitimately also contain negated prose.
    """
    for m in re.finditer(pattern, hay, flags):
        pre = hay[max(0, m.start() - NEGATION_LOOKBEHIND):m.start()]
        # Never read across a clause boundary. A negation belonging to the PREVIOUS
        # sentence does not negate this claim — without this, "…is *not* a merge
        # blocker: record each Material finding to the `backlog`" is rejected on the
        # strength of a "not" that is part of the sentence before it.
        pre = re.split(r"[.;:]\s|\s[-–—]\s", pre)[-1]
        if not NEGATION_RE.search(pre + m.group(0)):
            return True
    return False


def affirms_predicate(hay, anchor_pat, target_pat, window=200):
    """True when `target` follows `anchor` with no negation BETWEEN the two.

    For requirements whose subject is itself an absence — "when no `Scope:` exists,
    enumerate one" — `affirms()` rejects the subject's own "no", while a plain search
    leaves the predicate wide open. The cost, concretely:
    "When no `Scope:` field exists, the task must NOT attempt to enumerate one"
    satisfies the plain form, i.e. prose stating the exact opposite of the requirement
    passes the check meant to pin it.
    """
    for m in re.finditer(anchor_pat, hay, re.I | re.S):
        span = hay[m.end(): m.end() + window]
        tgt = re.search(target_pat, span, re.I | re.S)
        if not tgt:
            continue
        if not NEGATION_RE.search(span[:tgt.start()] + tgt.group(0)):
            return True
    return False


def affirmed_index(hay, pattern):
    """Index of the first match of `pattern` that is NOT negated, else -1.

    Only the preceding clause is scanned, never the match itself: a token that
    literally begins with "no" would otherwise be rejected by NEGATION_RE at every
    genuine reference.
    """
    for m in re.finditer(pattern, hay, re.I | re.S):
        pre = hay[max(0, m.start() - NEGATION_LOOKBEHIND):m.start()]
        pre = re.split(r"[.;:]\s|\s[-–—]\s", pre)[-1]
        if not NEGATION_RE.search(pre):
            return m.start()
    return -1


# Clause boundaries for affirms_claim, deliberately one-sided. A comma clause BEFORE the
# target states something else, so its negation is not the target's; a comma clause
# AFTER it qualifies the target, so it is screened. A colon ends a clause looking back
# but not looking forward, because a requirement such as `Parallel: YES` holds one.
CLAUSE_START = re.compile(r"[.;:,]\s|\s[-–—]\s|\*\*\s|\bso\b|\brather\b|\bthough\b")
SENTENCE_END = re.compile(r"[.;]\s|\.\*\*|\s[-–—]\s")


def affirms_claim(hay, target_pat):
    """True when `target` appears in a clause that carries no negation.

    Use this for a prose requirement by default. `affirms` and `affirms_predicate` leave
    the screening width to the check's author — a fixed number of characters back, or
    the text between two anchors — so a reversal just outside that width goes unread,
    and the right width shifts every time the prose is edited.

    The unit screened is the clause holding the claim: from the clause boundary before
    it up to the sentence end, both found in the text itself. That catches a negated
    verb ("does not require"), a negated object ("no reason") and a trailing
    withdrawal ("…, though this is optional").

    Use `affirms_predicate` ONLY when the requirement's own subject is an absence
    ("when no concurrent sibling exists, dispatch anyway") — there the clause legitimately
    contains a negation and screening it would reject true prose.
    """
    for m in re.finditer(target_pat, hay, re.I | re.S):
        starts = [b.end() for b in CLAUSE_START.finditer(hay[:m.start()])]
        after = SENTENCE_END.search(hay, m.end())
        span = hay[(starts[-1] if starts else 0): (after.start() if after else len(hay))]
        # Blank out `code spans` first: they hold literals, not prose. The rule "the user
        # can re-mark the tasks `Parallel: NO`" names a FIELD VALUE, and reading its `NO`
        # as a negation rejects the sentence.
        if not NEGATION_RE.search(re.sub(r"`[^`]*`", " ", span)):
            return True
    return False


# Slices whose END anchor matched nothing, so the slice ran to the end of whatever
# it was reading. Recorded centrally rather than guarded call-by-call: a per-call
# `len(block) < N` bound is instance-shaped by construction — it protects the slices
# someone remembered to bound and no others (a dead end anchor reads 33,190 chars for
# one slice and 56,637 across six files for another). A fall-through fails
# OPEN: the assertions still name their site while reading unrelated text, so they can
# pass on prose that has nothing to do with the rule. Detecting it here covers every
# existing caller and every future one.
FELL_THROUGH = []
OVERSIZED = []

# No rule-level slice in this suite is legitimately this long. The largest one is
# Step 3.5's full trunk section at ~12.0k (it grew with the execution-state protocol and
# the stage Outcomes). The bound exists because a fall-through does
# not always leave the end anchor UNMATCHED: a stale end anchor can match a
# case-insensitive bullet in a different reference file, producing a 56,637-char slice
# spanning six files that FELL_THROUGH cannot see. Unmatched-anchor and
# matched-far-away are two shapes of one defect, so both are detected.
MAX_SLICE = 14000


def section(text, start_pat, end_pat):
    """Slice the text between two anchors; returns '' when the start is missing."""
    m = re.search(start_pat, text, re.I)
    if not m:
        return ""
    rest = text[m.start():]
    e = re.search(end_pat, rest[1:], re.I)
    if e is None and end_pat != r"\Z":
        # `\Z` is the one legitimate unbounded end anchor, and only where the slice
        # is scoped to a file that genuinely ends there (see the review_optout note).
        FELL_THROUGH.append(f"{start_pat!r} → {end_pat!r} (read {len(rest)} chars)")
    raw = rest[: e.start() + 1] if e else rest
    out = flat(raw)
    if len(out) > MAX_SLICE:
        OVERSIZED.append(f"{start_pat!r} → {end_pat!r} ({len(out)} chars)")
    return out


def main():
    if not SKILL.is_file():
        print(f"FAIL: {SKILL} not found", file=sys.stderr)
        return 1
    # The skill is the trunk PLUS any reference files it loads on demand. If
    # progressive disclosure moves a rule out of SKILL.md into references/, the rule
    # has not gone away — it has moved, and these assertions exist to catch DELETION
    # (see the module docstring), not relocation. Reading only SKILL.md would fail on
    # a change that removed nothing, and would push authors to keep content in the
    # trunk to satisfy the guard rather than because it belongs there. Slices that must
    # stay scoped to the trunk read SKILL.md directly rather than this concatenation —
    # see review_optout below for why an unbounded end anchor is unsafe here.
    refs = sorted((SKILL.parent / "references").glob("*.md"))
    text = "\n\n".join(
        [SKILL.read_text(encoding="utf-8")]
        + [r.read_text(encoding="utf-8") for r in refs]
    )

    gate_fail = section(text, r"\*\*If the gate fails", r"\*\*If the gate passes")
    check("gate-failure section present", bool(gate_fail),
          "no '**If the gate fails' … '**If the gate passes' block in SKILL.md")

    # 0 — the class-repair rule's own section. Placed inside the gate-failure branch it
    # would apply only at gates, and a defect met during a Red-Green loop, a review or an
    # edit would never be swept. The trunk states it once and every discovery site points
    # at it, so the RULE's own properties are checked here and what the GATE adds is
    # checked on gate_fail. Keeping the two apart lets either section move without
    # unpinning the other.
    REFS_EARLY = SKILL.parent / "references"
    class_rule = section(text, r"## A bug found during execution is a class",
                         r"## Phase 1 — Load and critique")
    check("class-repair rule stated as its own trunk section", bool(class_rule),
          "no '## A bug found during execution is a class' section — the rule is either "
          "deleted or has collapsed back inside a single caller")
    check("the rule fires beyond gates, naming the non-gate discovery sites",
          affirms(class_rule, r"RED test|while editing"),
          "the rule does not say it fires outside a gate; limited to gates, it only "
          "repeats the gate-failure branch")
    check("the gate-failure branch routes to the shared rule",
          affirms(gate_fail, r"A bug found during execution is a class"),
          "the gate-failure branch does not call the shared rule, so the two can drift "
          "back into separate procedures")

    # 0b — the rule is wired at EVERY site a defect can surface, checked as a SET rather
    # than one worked example: an instance-shaped check cannot fail on the siblings that
    # make the class, which is the very defect this rule exists to repair.
    #
    # Each site names the FILE its procedure lives in. Tier-1's machinery and the gate's
    # evaluator and Tier-2 briefs live in references/ (branch-taken text), so reading only
    # the trunk would report three deletions where nothing was deleted.
    #
    # Each site is read from its own file, never from the concatenation: `section()` over
    # trunk+references returns the FIRST match, so with a site in both places only the
    # trunk copy is read and the reference copy can stop routing unseen. A definite file,
    # start anchor and end anchor per site keeps each one at a place a reader can open.
    skill_only = SKILL.read_text(encoding="utf-8")
    REFS = SKILL.parent / "references"
    DISCOVERY_SITES = [
        ("Red-Green loop", SKILL,
         r"\*\*Diagnose before fixing", r"\*\*Respect the cycle budget"),
        ("Tier-1 Critical", REFS / "task-execution.md",
         r"\*\*Critical → blocking", r"\*\*Important / Suggestion"),
        ("Tier-2 review", REFS / "stage-gate.md",
         r"## Deep code review \(Tier 2\)", r"## Decisions-conformance"),
        ("gate evaluator", REFS / "stage-gate.md",
         r"## Independent evaluator for non-command checks",
         r"## Deep code review \(Tier 2\)"),
        ("gate failure", SKILL,
         r"\*\*If the gate fails", r"\*\*If the gate passes"),
    ]
    unwired = []
    for name, path, start, end in DISCOVERY_SITES:
        if not path.is_file():
            unwired.append(f"{name} (no {path.name})")
            continue
        blk = section(path.read_text(encoding="utf-8"), start, end)
        if not blk or not affirms(blk, r"A bug found during execution is a class"):
            unwired.append(name)
    check("every discovery site routes to the class rule: "
          + ", ".join(n for n, _, _, _ in DISCOVERY_SITES),
          not unwired,
          f"these sites do not reach the rule: {', '.join(unwired)} — a bug found there "
          f"is repaired one instance at a time")

    # 0c — the rule's two bounds. Both are deliberate and both are the kind of
    # qualifier a later compression deletes as hedging: without the cost line the rule
    # reads as fundable-by-tier (contradicting the command-cost rule), and without the stop line it
    # reads as a licence to refactor whatever lives near the bug.
    check("the sweep is priced as a command, never a dispatch",
          affirms(class_rule, r"costs a command")
          and affirms(class_rule, r"untiered mandates"),
          "the rule does not state that it costs no agent dispatch, so a reader cannot "
          "tell whether the review tier gates it (a command-cost mandate "
          "is never tiered)")
    check("the sweep's outer bound is stated",
          affirms(class_rule, r"nothing wider"),
          "nothing bounds the sweep to the defect's own predicate, so it reads as "
          "authorisation for unrelated refactoring")
    check("an un-nameable class is disclosed rather than swept by feel",
          affirms(class_rule, r"disclose the limit"),
          "no instruction for the case where the class cannot be expressed as a "
          "command — which is where a sweep silently becomes a guess")
    # 0b-ii — the two obligations that turn "cannot be expressed as a command" from a
    # disclosure into a repair. An absence-shaped class — code paths that should publish
    # a value and do not — enumerated by hand is bounded each time by the mechanism just
    # built, so each review round finds one more member outside the last boundary and
    # every remediation round goes on extending the list. Disclosure alone does not stop
    # that; naming the shape and switching to an invariant does.
    check("the un-nameable class is told what to do instead of enumerating",
          affirms(class_rule, r"absence-shaped"),
          "the trunk names the un-nameable class but not its shape or its remedy, so an "
          "executor discloses an incomplete list and enumerates again next round")
    shapes = (REFS_EARLY / "bug-is-a-class.md")
    shapes_text = shapes.read_text(encoding="utf-8") if shapes.is_file() else ""
    check("the reference distinguishes presence-shaped from absence-shaped classes",
          affirms(shapes_text, r"presence-shaped") and affirms(shapes_text, r"absence-shaped"),
          "bug-is-a-class.md offers only presence-based enumeration techniques (grep the "
          "string, list the siblings, list the callers), none of which can find a call "
          "that is missing")
    check("the reference gives the tell for an absence-shaped class",
          affirms_predicate(shapes_text, r"the tell is the fix",
                            r"absence-shaped", window=200),
          "no way to recognise an absence-shaped class before spending a round on it — "
          "the discriminator is that the repair ADDS a call rather than changing one")
    check("a repeat finding inside a swept class forces a technique change",
          affirms_predicate(shapes_text, r"second finding inside a class",
                            r"misnamed", window=200),
          "a second finding in an already-swept class reads as another instance, so the "
          "executor fixes it and re-sweeps — the oscillation the budget bounds but cannot "
          "converge")

    # Anchored on the definition's own heading. The bare phrase first matches a forward
    # pointer in the Tier-2 paragraph ("per the **exit criterion** below"), giving a
    # 2693-char slice that starts mid-sentence, and the placement check then passes
    # even with the definition deleted.
    exit_block = section(text, r"\*\*Exit criterion\s+—\s+what", r"\*\*If the gate fails")
    check("exit criterion DEFINED outside the failure branch", bool(exit_block),
          "no '**Exit criterion — what …' definition heading before '**If the gate "
          "fails' — a criterion defined only inside the failure branch never fires on "
          "an Important-only gate")

    # The budget is not prose the executor tracks about itself. A rule whose only
    # enforcement is the executor's own memory of how many rounds it has spent lets a
    # 4th round go out after a declared budget of 3 while `plan-progress.json` carries
    # `remediation_round` and nothing reads it as a stop; a command is what replaces it.
    check("the budget is enforced by a command, not by self-tracking",
          re.search(r"--budget-check", gate_fail) is not None,
          "the gate-failure procedure names no mechanical check, so counting the "
          "rounds is still the executor's own bookkeeping about itself")
    check("the check runs BEFORE a further remediation dispatch",
          re.search(r"--budget-check[\s\S]{0,200}?\bbefore\b"
                    r"|\bbefore\b[\s\S]{0,200}?--budget-check",
                    gate_fail, re.I) is not None,
          "nothing says WHEN to run it; a check run after the round it should have "
          "stopped is a receipt, not a gate")
    check("the mandate distinguishes active completion from new admission",
          "completed/active accounts" in gate_fail and "begin-round" in gate_fail
          and "state_error" in gate_fail,
          "validated state, active completion or new-round admission is unnamed")
    check("exhaustion routes to escalation, not to another round",
          re.search(r"escalat", gate_fail, re.I) is not None,
          "the on-exhaustion path is not named, so the natural next move is the "
          "round the budget exists to prevent")
    # Every mandate says which tier or scope rule funds it. This one is a single
    # command with no dispatch, so no tier gates it.
    check("the new mandate states what gates it",
          re.search(r"--budget-check[\s\S]{0,300}?(untiered|every tier)"
                    r"|(untiered|every tier)[\s\S]{0,300}?--budget-check",
                    gate_fail, re.I) is not None,
          "the mandate does not name its tier or scope rule, which the mandate rule requires "
          "of a new mandate")

    # 1 — numeric round budget, overridable by the plan
    budget_nums = re.findall(r"\*\*(\d+)\s+rounds?\*\*|\b(\d+)\s+rounds?\b", gate_fail)
    round_nums = [n for pair in budget_nums for n in pair if n]
    check("numeric remediation-round budget", bool(round_nums),
          "no numeric round count in the gate-failure procedure")
    # One phrase, not two mentions: a `...|budget` alternative subsumes the others, so
    # the assertion would pass on the word "budget" appearing anywhere in the section,
    # however far from the round count. Require the two to sit in one phrase.
    check("the round count is named as a budget",
          re.search(r"budget[^.]{0,80}\b\d+\s+rounds?|\b\d+\s+rounds?[^.]{0,80}budget",
                    gate_fail, re.I) is not None,
          "the numeric round count and the word 'budget' are not in the same sentence")
    check("plan may override the budget",
          re.search(r"(plan|Plan).{0,80}overrid", gate_fail, re.S) is not None,
          "the budget is not stated as overridable by the plan")
    check("budget is counted and reported",
          re.search(r"count(ed)?\b.{0,60}report|report.{0,60}count", gate_fail, re.I | re.S)
          is not None,
          "the budget is not required to be counted and reported")

    # 2 — the existing three-level severity taxonomy
    for level in ("Critical", "Important", "Suggestion"):
        check(f"severity level named: {level}", level in gate_fail,
              f"'{level}' absent from the gate-failure procedure")
    check("severity classification is a step",
          re.search(r"classif", gate_fail, re.I) is not None,
          "no severity-classification step before repair")

    # 3 — a pass rule that a judgment-based reviewer can actually meet
    # The pass condition itself, not a window: a 400-char window lets "Critical" satisfy
    # the check from an unrelated aside.
    check("exit criterion turns on no Critical remaining",
          re.search(r"passes when\s+\*{0,2}no Critical", exit_block, re.I) is not None,
          "the exit criterion does not state that passing requires no Critical remaining")
    check("Important findings are FIXED, not filed",
          affirms(exit_block, r"Important[\s\S]{0,120}fixed"),
          "Important findings may be silently dropped — no affirmative fix rule")
    # The inverse pin, and the load-bearing half: the criterion must not offer the
    # backlog as a way to pass a gate on an unfixed defect. A pin that only stopped
    # REQUIRING "backlog" next to "Important" would leave the drift free to return in the
    # next rewording.
    check("the pass rule gives an unfixed defect no backlog exit",
          not re.search(r"Important[\s\S]{0,120}recorded to the `?backlog", exit_block, re.I),
          "the exit criterion lets an Important finding leave the gate as a backlog ID, "
          "so a defect can pass the gate unrepaired")
    check("the backlog's two admissible kinds are named at the criterion",
          affirms(exit_block, r"significant improvement")
          and affirms(exit_block, r"decision"),
          "the criterion removes the backlog as a disposition without saying what the "
          "backlog IS for, which is how the rule reads as 'never file anything'")
    check("a defect that cannot be fixed here escalates with its blocker named",
          affirms_predicate(exit_block, r"cannot fix", r"[Ee]scalat")
          or affirms(exit_block, r"naming the blocker"),
          "no escape valve: a defect needing a device, a credential or an upstream "
          "release would be unreportable, which is worse than a deferred one")
    check("'no findings' rejected as the bar",
          re.search(r"not a reachable state|returned silent", exit_block, re.I) is not None,
          "the rationale for not using 'detector returned silent' is missing")

    # 6 — the sibling sites. Every other place in the file that restates what happens to
    # an Important finding is a member of the same defect class, so they are checked as a
    # SET (the class-predicate rule): fixing one site alone leaves a sibling to survive
    # to the next round, which is the exact oscillation the class rule exists to end.
    sibling_sites = [
        ("Tier-2 stage review",
         section(text, r"\*\*Deep code review \(Tier 2\)", r"\*\*Decisions-conformance")),
        ("Light-plan pre-gate review",
         section(text, r"\*\*One review, not per-task",
                 r"\*\*The evaluator follows the tier")),
        ("Integration summary (code-reviewer agent)",
         section(text, r"- \*\*planning:code-reviewer agent\*\*", r"\n- \*\*")),
        # The master-plan clause is a sibling too: a sibling left out of this list is
        # the instance-vs-class gap the class rule exists to close.
        ("master-plan sub-plan gate clause",
         section(text, r"\*\*On a sub-plan's close-out\*\*", r"\n4\. \*\*Version bumps")),
    ]
    for label, block in sibling_sites:
        check(f"site present: {label}", bool(block), f"could not locate the {label} block")
        # A dead END anchor makes section() run to the end of the concatenation, and the
        # checks below then pass on unrelated text while still naming this site (an end
        # anchor that exists nowhere outside this file reads 33,190 chars). Every
        # sibling block is 300-1500 chars, so a bound catches the whole failure mode.
        check(f"slice is bounded, not fallen through: {label}", len(block) < 4000,
              f"the {label} slice is {len(block)} chars — its end anchor no longer "
              f"matches, so these checks are reading the rest of the document")
        # Two conditions rather than one 220-char window. The window had to be greedy to
        # span either order, and a greedy span pulls in any negation further down the
        # paragraph — including, at the master site, the criterion's own "no Critical
        # remains". Cite-the-criterion and say-they-are-fixed are separate claims anyway.
        check(f"Importants bound to the exit criterion at: {label}",
              "exit criterion" in block and affirms(block, r"leaves[\s\S]{0,40}?fixed")
              and not re.search(r"either fixed or recorded|or recorded to the `?backlog",
                                block, re.I),
              f"{label} describes Important findings without binding them to the exit "
              f"criterion and to being fixed — findings can pass this path unrepaired")
        check(f"no backlog escape hatch at: {label}",
              not re.search(r"Important[\s\S]{0,260}recorded to the `?backlog", block, re.I),
              f"{label} lets an Important finding go to the backlog instead of being "
              f"fixed, so this sibling can still defer a defect")

    # 4 — escalation on exhaustion, carrying the residual list
    check("budget-exhaustion escalation",
          re.search(r"exhaust", gate_fail, re.I) is not None,
          "no budget-exhaustion path")
    check("escalation carries a residual list",
          re.search(r"residual", gate_fail, re.I) is not None,
          "escalation does not carry a residual list")
    check("exhaustion is a Stop condition",
          re.search(r"[Ss]top condition", gate_fail) is not None,
          "exhaustion is not tied to a Stop condition")

    # 5 — narrow re-verification plus the class sweep
    check("class sweep re-run alongside narrow re-verification",
          re.search(r"sweep", gate_fail, re.I) is not None,
          "the class sweep is not required at re-verification")

    # 5b — the set has a DERIVATION SOURCE, not just an instruction to name it.
    # "name the set" alone is not enough: naming is not deriving, and a set produced
    # from recollection is how a class arrives one member short.
    check("the set is derived from the task's Scope: field",
          affirms(gate_fail, r"`?Scope:`?[^.]{0,80}field|field'?s? `?Scope:`?"),
          "step 2 does not name the task's Scope: field as the derivation source")
    # Asserted on the RULE, not the gate: the enumeration procedure lives in the trunk
    # section because the rule is not gate-only, and a defect found outside a gate is
    # precisely the case where no `Scope:` was ever declared — so this property matters
    # MORE at the rule than at the gate.
    check("a missing Scope: has a stated fallback",
          affirms_predicate(class_rule, r"(no `?Scope:`?|when no scope)", r"enumerate"),
          "there is no procedure for deriving the set when the task declares no Scope:")
    check("the derived sweep command is recorded in the gate report",
          affirms(gate_fail, r"write the command down|command down in the gate report"),
          "the derivation is not required to be written down, so the next round re-guesses")
    check("every member found is fixed in the SAME round",
          affirms(gate_fail, r"every member[^.]{0,80}this round|fix every member"),
          "repair may still proceed one instance per round, which is oscillation")

    # 6b — evidence-first diagnosis is instructed AT the diagnosis step. A mention
    # elsewhere in the file would pass a plain grep and change nothing, so position is
    # what is asserted: inside the gate-failure block, ahead of the step naming the set. Anchored on the step BODY
    # ("evidence-first before generalizing"): step 2's heading already says
    # "diagnose evidence-first", so a bare anchor would pass on the heading alone.
    check("evidence-first diagnosis is instructed in the gate-failure procedure",
          affirmed_index(gate_fail, r"evidence-first\W*before generalizing") != -1,
          "the gate-failure procedure never instructs evidence-first diagnosis "
          "(or names it only to opt out)")
    # Anchor on the DERIVATION instruction, not on step 2's heading: the heading
    # ("Diagnose evidence-first, then name the set…") already contains "name the set"
    # and states the order itself, so anchoring there compares against the wrong point.
    # The ORDER is asserted on the rule (step 1 before step 2) and its ROUTING on
    # the gate, because the rule is where the ordering is defined and the gate is where
    # it is most fix-prone. Both must hold; neither alone is the contract.
    check("step 2's heading orders diagnosis before naming",
          affirms(gate_fail, r"diagnose evidence-first, then name the set"),
          "step 2 does not state diagnosis-before-generalization in its own heading")
    diag_at = affirmed_index(class_rule, r"evidence-first\W*before generalizing")
    derive_at = class_rule.lower().find("name the set")
    check("evidence-first diagnosis is ordered BEFORE the set is derived",
          diag_at != -1 and derive_at != -1 and diag_at < derive_at,
          "diagnosis is not ordered before generalization, so a wrong root cause "
          "yields a confidently-swept wrong set")
    check("the ordering rationale is stated, not just the order",
          affirms(class_rule + gate_fail,
                  r"wrong root cause[^.]{0,60}wrong set|set derived from a wrong"),
          "nothing explains why diagnosis must precede generalization")

    # 6c — the SECOND site of the same defect. Without this check, deleting the Red-Green
    # diagnose-rule reference leaves this suite green, so the site is unpinned.
    rg = section(text, r"\*\*Diagnose before fixing", r"\*\*Respect the cycle budget")
    check("evidence-first diagnosis is instructed at the Red-Green diagnose step too",
          affirmed_index(rg, r"evidence-first") != -1,
          "the Red-Green loop's diagnose rule does not instruct evidence-first diagnosis")

    # 7 — sweep: no instance-shaped framing survives anywhere under planning/skills/
    offenders = []
    scanned = 0
    # Every file, not just *.md: a gate's `grep -r` reads the whole tree, and a sweep
    # that reads less than that gate can pass where the gate fails.
    # __pycache__ is excluded as generated, not as inconvenient: it is not a source
    # of prose, and its .pyc are rebuilt from the .py files already swept.
    for path in sorted(p for p in SKILLS_ROOT.rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts):
        scanned += 1
        body = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(body.splitlines(), 1):
            if BANNED_PHRASE in line:
                rel = path.relative_to(SKILLS_ROOT.parent.parent)
                offenders.append(f"{rel}:{i}")
    # 8 — the evaluator briefs. Two sites, checked as a set for the same
    # reason as #6: the gate evaluator and the close-out evaluator are siblings, and
    # giving only one of them a severity vocabulary leaves the other unsatisfiable.
    evaluator_sites = [
        # The BRIEF lives in references/stage-gate.md (the evaluator's briefing is
        # branch-taken text); the trunk keeps the rule that it runs and what gates it.
        # Anchored on the reference so the severity vocabulary is pinned where it is
        # actually written, rather than reported missing from a trunk that does not
        # carry it.
        ("gate evaluator (Step 3.5)",
         section((SKILL.parent / "references" / "stage-gate.md")
                 .read_text(encoding="utf-8"),
                 r"## Independent evaluator for non-command checks",
                 r"## Deep code review")),
        # Anchored on the step's NAME, not on a parenthetical after it. Pinning a policy
        # word such as "(default)" inside a *locator* means a legitimate policy change
        # silently unanchors every downstream assertion at once (they report as
        # independent failures, which is how an over-fit anchor disguises itself as a
        # regression). The class: pin the rule, locate by the stable name.
        ("close-out evaluator",
         section(text, r"\*\*Independent evaluator pass", r"\n4\. \*\*Bump")),
    ]
    for label, block in evaluator_sites:
        check(f"site present: {label}", bool(block), f"could not locate the {label} block")
        # The level must be BRIEFED, not merely mentioned. A bare `level in block` is
        # satisfiable by the prose around the brief — "an evaluator FAIL carrying no
        # Blocking finding…", "Blocking maps to Critical…" — so replacing the severity
        # table's own `**Blocking**` row would leave it green. Both legitimate briefing
        # forms are accepted: the gate
        # evaluator states them as an emphasised table, the close-out evaluator as the
        # slash-listed triple, and neither survives deleting the row or the list.
        for level in ("Blocking", "Material", "Minor"):
            briefed = (re.search(rf"\*\*{level}\*\*", block) is not None
                       or re.search(r"Blocking\s*/\s*Material\s*/\s*Minor", block)
                       is not None)
            check(f"severity '{level}' in brief: {label}", briefed,
                  f"{label} does not brief the evaluator to return '{level}' — the word "
                  f"may appear in nearby prose, but the brief itself does not require it")
        check(f"silent-detector rationale at: {label}",
              re.search(r"not a reachable state|essentially (always|never)|"
                        r"almost never", block, re.I) is not None,
              f"{label} does not say why 'no adverse findings' cannot be the bar")

    close_out = evaluator_sites[1][1]
    # One alternative only. A looser second form (`stop condition … Blocking` within
    # 80 chars) would also match "…is the stop condition. Blocking findings especially
    # matter" — prose that does NOT narrow the condition. The precise form is the one
    # that fires against the skill text.
    check("close-out stop condition scoped to Blocking",
          affirms(close_out, r"Blocking finding is the stop condition"),
          "the close-out stop condition is not narrowed to Blocking findings — any FAIL "
          "blocks merge, so no reviewer output can ever let the merge through")
    # Plain search, NOT affirms(): this claim is affirmative in meaning but negative in
    # wording ("is *not* a merge blocker"), so the negation guard would reject a correct
    # sentence. Use affirms() only where a negated copy of a claim reverses the rule;
    # used everywhere, it rejects correct prose and costs upkeep for nothing.
    #
    # The pattern allows emphasis markers, because the skill text emphasises its `not`,
    # and a plain `not a merge blocker` would never match. There is no looser
    # `|residual` alternative: ordinary boilerplate matches it, and the check would go
    # green while pinning nothing.
    check("close-out: a Material-only FAIL leaves the merge open",
          re.search(r"Material[\s\S]{0,120}is \*?not\*? a merge blocker",
                    close_out, re.I) is not None,
          "a Material-only FAIL is not distinguished from a Blocking one")
    check("close-out Material findings are FIXED, not just mentioned",
          affirms(close_out, r"fix each Material finding"),
          "Material findings are reported without an imperative to fix them")
    check("close-out does not route a Material finding to the backlog instead",
          not re.search(r"record each Material finding[\s\S]{0,60}backlog", close_out, re.I),
          "close-out still files Material findings rather than fixing them, so the "
          "deferral path survives at the one gate with the widest view of the diff")

    # 8b — (backlog admission) A SWEEP of every skill, not a check of a few files. The
    # banned contract — fix it OR file it in the backlog — can be written at many sites,
    # and fixing only the one that was spotted leaves the others. Any markdown file under
    # ADMISSION_ROOT that lets an Important or Material finding go to the backlog fails
    # here, by name.
    #
    # Any path under a fixtures/ directory is excluded: a fixture is test input, not
    # guidance an executor follows. A fixture plan carries whatever wording its test
    # needs a checker to read, and a forbidden wording is one of those, so sweeping
    # fixtures would flag test data and push the tests to drop the cases they exist for.
    # Two patterns, because one of them needs no distance parameter at all. The window on
    # the second is 260: an 80-char window is vacuous against a sibling site whose
    # distance measures 186 characters, and the disjunction pattern backstops it
    # regardless.
    DEFERRAL_RE = re.compile(
        r"either fixed or recorded|fixed or recorded to the `?backlog|"
        r"or recorded to the `?backlog|"
        r"(Important|Material)[\s\S]{0,260}?recorded to the `?backlog", re.I)
    # Wider than skills/: the disposition claim can also be stated in a README or a
    # docs/ page beside the skills. A guard narrower than the claim it protects
    # is the instance-vs-class shape the class rule exists to close, recurring inside
    # the guard. Matches check 11d's scope for the same reason.
    ADMISSION_ROOT = SKILLS_ROOT.parent.parent
    offenders = []
    swept = 0
    for md in sorted(ADMISSION_ROOT.rglob("*.md")):
        if "fixtures" in md.parts or ".git" in md.parts:
            continue
        swept += 1
        if DEFERRAL_RE.search(flat(md.read_text(encoding="utf-8"))):
            offenders.append(str(md.relative_to(ADMISSION_ROOT)))
    check(f"no skill files a defect instead of fixing it (swept {swept} files)",
          not offenders,
          "these let a finding go to the backlog instead of being fixed: "
          + ", ".join(offenders))
    check("the admission sweep examined a non-empty set", swept > 20,
          f"only {swept} files swept — the sweep is not reaching the skills tree")

    # 8c — the backlog skill states what it DOES admit. A rule that only forbids leaves
    # an executor with nowhere to put a genuine improvement, and the predictable failure
    # is that it stops recording those too.
    backlog_skill = SKILLS_ROOT / "backlog" / "SKILL.md"
    if backlog_skill.is_file():
        bt = flat(backlog_skill.read_text(encoding="utf-8"))
        for kind in ("significant improvement", "non-urgent decision"):
            check(f"backlog admits: {kind}", affirms(bt, re.escape(kind)),
                  f"the backlog skill does not name '{kind}' as admissible")
        check("backlog refuses a defect found during execution",
              affirms_predicate(bt, r"Refuse", r"defect"),
              "the backlog skill has no refusal path, so `add` still accepts a defect")

    # 11b — (dispatch precedence) A plan's mandated dispatch needs no confirmation turn.
    # One assertion per clause, and the bound gets the same weight as the rule, since the
    # rule can fail two ways: an executor treats the standing caution as absolute and
    # skips every mandated dispatch and review, or an over-correction reverses the rule
    # instead of limiting it. Pinning only the permissive half leaves the second open.
    precedence = section(text, r"## The plan is the authorization",
                         r"## A bug found during execution is a class")
    check("dispatch-precedence rule stated as its own trunk section", bool(precedence),
          "no '## The plan is the authorization' section — a session must then re-derive "
          "the precedence between the standing caution and the plan's execution model")
    check("slice is bounded, not fallen through: precedence", len(precedence) < 4000,
          f"the precedence slice is {len(precedence)} chars — its end anchor no longer "
          f"matches, so the checks below are reading the rest of the document")
    # These four requirements have a NEGATION as their subject — "conditional, not
    # absolute", "no plan in play", "over-corrected", "without asking" — so affirms(),
    # which screens negation tokens inside the match, rejects every one of them on true
    # prose. Closest precedent is check 9b, which drops the screen because there is no single
    # claim clause to anchor; here the reason differs again — the target text itself embeds
    # a negation token, so the screen rejects the requirement's own correct wording. The phrases are specific enough
    # that an inversion cannot match them accidentally, which is what affirms() would
    # otherwise be buying.
    check("the standing caution is named as CONDITIONAL, not absolute",
          re.search(r"conditional, not absolute", precedence, re.I) is not None,
          "the rule does not say the standing caution is conditional, which is the whole "
          "resolution — without it the two rules still contradict and the general one wins")
    check("approving the plan is named as the request",
          affirms(precedence, r"was the request|is the request"),
          "nothing states that the plan's approval IS the request the caution refers to")
    check("the BOUND is stated: no plan in play means you still ask",
          re.search(r"no plan in play[\s\S]{0,160}?ask", precedence, re.I) is not None,
          "the rule is stated without its bound, which is how it gets over-corrected into "
          "its inverse — the rule's second failure direction")
    check("the over-correction is recorded as a failure in its own right",
          re.search(r"over-correct(?:ed|ion)? into its own inverse", precedence, re.I)
          is not None,
          "only the permissive failure is recorded, so a reader has no warning against "
          "inverting the rule rather than scoping it")
    check("what still halts a dispatch is enumerated",
          affirms(precedence, r"requires_enablement") and affirms(precedence, r"probe"),
          "the rule removes the confirmation turn without saying what legitimately still "
          "stops a dispatch, which reads as 'dispatch unconditionally'")

    # 11c — the rule must appear in both files that decide a dispatch, checked as a SET.
    # dispatching-parallel-agents launches a fan-out; dispatch-fidelity holds the
    # reasoning. A rule stated only in the trunk never reaches the dispatch path.
    DISPATCH_SITES = [
        # A sentence pattern, not a bare substring: "without asking" on its own also
        # matches "do not fan out without asking the user", the over-correction the
        # rule forbids.
        ("dispatching-parallel-agents", SKILLS_ROOT / "dispatching-parallel-agents"
         / "SKILL.md", r"[Dd]ispatch on invocation[\s\S]{0,80}?without asking"),
        ("dispatch-fidelity rationale", SKILLS_ROOT / "executing-plans" / "references"
         / "dispatch-fidelity.md", r"conditional"),
    ]
    missing = [name for name, path, pat in DISPATCH_SITES
               if not (path.is_file()
                       and re.search(pat, flat(path.read_text(encoding="utf-8")), re.I))]
    check("dispatch precedence reaches: " + ", ".join(n for n, _, _ in DISPATCH_SITES),
          not missing,
          f"these dispatch-path files do not carry the rule: {', '.join(missing)}")

    # 11d — every skill in the marketplace is read: none may put a confirmation turn
    # back in front of a dispatch the plan requires. Fixtures excluded for the reason given at the admission sweep.
    # Synonyms matter: the rule is about a confirmation turn, not about one phrasing of
    # it, and "check with the user before fanning out" is the same regression. Scope is
    # the whole marketplace, matching the stage gate's own class predicate rather than
    # being quietly narrower than the check it mirrors.
    ASK_RE = re.compile(r"ask (?:the user )?(?:whether|if) to (?:dispatch|fan out)|"
                        r"(?:confirm|check) with the user before (?:dispatch|fan)|"
                        r"confirm before dispatching|permission to dispatch", re.I)
    MARKET_ROOT = SKILLS_ROOT.parent.parent
    askers = [str(md.relative_to(MARKET_ROOT))
              for md in sorted(MARKET_ROOT.rglob("*.md"))
              if "fixtures" not in md.parts and ".git" not in md.parts
              and ASK_RE.search(flat(md.read_text(encoding="utf-8")))]
    check("no skill asks before a mandated dispatch", not askers,
          "these still ask before dispatching: " + ", ".join(askers))

    # 9 — drift guard. The renderer hardcodes the default budget as its denominator when
    # `remediation_budget` is absent, which duplicates the number stated in the skill
    # prose. Without this check, changing the prose default would leave the status line
    # dividing by the old number. Assert the two agree.
    doc_default = re.search(r"[Rr]emediation budget\s*—\s*default\s+(\d+)\s+rounds?",
                            flat(text))
    check("skill text states a default remediation budget", doc_default is not None,
          "could not find 'Remediation budget — default N rounds' in SKILL.md")
    renderer = SKILL.parent / "scripts" / "plan-progress.py"
    check("renderer present", renderer.is_file(), f"{renderer} not found")
    if doc_default and renderer.is_file():
        code = renderer.read_text(encoding="utf-8")
        # Anchored on the assignment line, not a character window: a window such as
        # `remediation_budget[\s\S]{0,300}?else (\d+)` breaks silently ("<not found>")
        # as soon as an explanatory comment pushes the distance past it.
        # Follows the CONSTANT, not a literal after `else`. The renderer's fallback has
        # a second consumer (--budget-check's ceiling), and two literals would let the
        # bar and the stop disagree about when a budget is spent — so the file keeps
        # one definition and this assertion reads it.
        m_fallback = re.search(r"^DEFAULT_REMEDIATION_BUDGET\s*=\s*(\d+)",
                               code, re.M)
        check("renderer default budget matches the documented default",
              m_fallback is not None and m_fallback.group(1) == doc_default.group(1),
              f"SKILL.md documents a default of {doc_default.group(1)} rounds but the "
              f"renderer falls back to "
              f"{m_fallback.group(1) if m_fallback else '<not found>'}")

    # 9b — every agent-dispatching mandate defers to the declared review tier at the
    # site that DISPATCHES it, not only in the summary table.
    #
    # Kept as a set, like the rest of this file. Grepping for unconditional wordings
    # finds only the sites that use them. A mandate listed in review-scope.md but never
    # wired at its own site (a Preflight probe, a design-fidelity check) is the same
    # defect, and that grep cannot see it, since the mandate never used those wordings.
    # A roster of sites can: each new mandate is either on the roster or visibly missing.
    #
    # MEASURED LIMIT, stated rather than implied (honest-gates; the disclosure
    # half): this asserts the site MENTIONS the tier, not that it defers correctly. A site
    # saying "the tier is irrelevant here" would pass. It catches the likely failure — a
    # dispatch mandate written with no tier term at all — and
    # does not pretend to grade the wording. No negation screen is used for the same
    # reason: there is no single claim clause to screen, only a topic that must be present.
    tier_gated_dispatch_sites = [
        ("Tier-1 per-task review",
         section(text, r"6\. \*\*Quick review gate \(Tier 1\)", r"7\. \*\*Commit after each")),
        ("Tier-2 deep review",
         section(text, r"\*\*Deep code review \(Tier 2\)", r"\*\*Decisions-conformance check")),
        ("gate evaluator",
         section(text, r"\*\*Independent evaluator for non-command checks",
                 r"\*\*Deep code review")),
        ("close-out evaluator",
         section(text, r"\*\*Independent evaluator pass", r"\n4\. \*\*Bump")),
        ("Preflight dispatch probe",
         section(text, r"2\. \*\*Probe the capability", r"3\. \*\*Snapshot the")),
        # Lives in references/stage-gate.md — it fires only on a redesign stage, which is
        # the definition of branch-taken. Matched in either form so the anchor survives
        # the heading style rather than the file it lives in.
        ("design-fidelity verify hook",
         section(text, r"(?:\*\*|## )Design-fidelity verify hook",
                 r"(?:\*\*|## )Independent evaluator for non-command checks")),
    ]
    for label, block in tier_gated_dispatch_sites:
        check(f"dispatch site present: {label}", bool(block),
              f"could not locate the {label} block — if it moved, re-anchor it here; a "
              f"site this suite cannot find is a site it is not guarding")
        if block:
            check(f"tier-gated at the dispatch site: {label}",
                  re.search(r"§ Review scope|review scope|\btier\b", block, re.I)
                  is not None,
                  f"{label} dispatches an agent without referring to the declared review "
                  f"tier — the summary table can say the tier gates it while this site "
                  f"runs it unconditionally, which is the untiered-mandate defect class")

    # 9c — the three rules that keep the defaults lean. Check 9b asserts each dispatch
    # site MENTIONS a tier, which is deliberately weak — it catches a mandate nobody
    # tiered. It does NOT catch a rule reverting to the unconditional default while
    # still naming the tier, which is how these three would erode: against 9b alone each
    # one reverts green, so each gets its own claim-level anchor here.
    check("Tier-1 is scoped to high's risk-listed tasks and Review: required",
          affirms_claim(text,
                        r"there is no per-task review|"
                        r"Tier 1\)[^.]{0,80}`high` tier's risk-listed tasks and "
                        r"`Review: required` tasks only"),
          "Step 3.3 rule 6 no longer scopes the per-task review to `high`'s risk-listed "
          "tasks and `Review: required` — per-task review has reverted to a default")
    # The floor escalates the plan for mandates reading an integrated diff, but
    # Tier-1 follows the risk to the individual task. Anchored apart from the check above,
    # which passes even when `high` binds every task: its wording says which *tiers* run
    # Tier-1, not which *tasks*.
    check("Tier-1 at high binds the risk-listed task, not every task in the plan",
          affirms_claim(text, r"this task is one the declaration names"),
          "Step 3.3 rule 6 no longer requires a `high` declaration to name the tasks "
          "Tier-1 binds — one risk-listed task has gone back to buying a per-task review "
          "dispatch for every task in the plan")
    check("required verification uses the active round; separate critique reserves new work",
          affirms_claim(text, ws(r"Required verification belongs to the active round"))
          and affirms_claim(text, ws(r"A separately initiated critique reserves new work")),
          "verification was charged again or separate new critique lost its admission boundary")
    # Negative assertion, so affirms_claim is wrong here (its negation screen would
    # reject the very absence being asserted). A literal-absence sweep is the honest
    # shape: the retired nudge is gone from every .md under planning/, or it is not.
    # Assembled, not written literally — same reason as BANNED_PHRASE above. This file
    # lives under planning/, which a gate may grep for the retired phrase, so a literal
    # here turns that gate permanently red against its own guard.
    retired_nudge = " ".join(
        ("Delegate", "sequential", "tasks", "for", "context", "hygiene"))
    revived = []
    for path in sorted(SKILLS_ROOT.parent.rglob("*.md")):
        if retired_nudge in path.read_text(encoding="utf-8", errors="replace"):
            revived.append(str(path.relative_to(SKILLS_ROOT.parent.parent)))
    check("the discretionary sequential-delegation nudge stays retired",
          not revived,
          "the retired nudge is back: an executor could hand a `Parallel: NO` task to a "
          f"subagent on its own judgment, a third mode the plan never shows: {revived}")

    # 10 — the behavioral-claim rule and its wiring, as a SET of sites.
    hg = SKILLS_ROOT / "honest-gates" / "SKILL.md"
    check("honest-gates present", hg.is_file(), f"{hg} not found")
    if hg.is_file():
        hg_text = flat(hg.read_text(encoding="utf-8"))
        check("honest-gates: behavioral claim is a verification claim",
              affirms(hg_text, r"sentence asserting behavior[\s\S]{0,120}"
                               r"claim that something was verified"),
              "honest-gates does not extend 'a gate is a claim that something was "
              "verified' to sentences asserting behavior")
        check("honest-gates: the citation requirement",
              re.search(r"cite the [`*]*file:line", hg_text, re.I) is not None,
              "no file:line citation requirement for a behavioral assertion")
        check("honest-gates sub-rule: a correction is a new claim",
              re.search(r"correction is a new claim", hg_text, re.I) is not None,
              "honest-gates no longer treats a correction as a fresh claim")
        check("honest-gates sub-rule: unrequested specificity",
              re.search(r"[Uu]nrequested specificity", hg_text) is not None,
              "the 'unrequested specificity' sub-rule is missing")
        # The rule's own honesty clause: it must say it is not a script, because
        # implying a validator exists would be the falsehood the rule forbids.
        check("honest-gates: discloses that no script can enforce this",
              re.search(r"cannot be a script", hg_text, re.I) is not None,
              "the section does not disclose that it is a discipline, not a validator")
        # The hard cases. A citation rule written only for a positive claim at one place
        # gives no help with the claim most often wrong: that something does NOT happen.
        #
        # Plain search, NOT affirms(): this rule is *about* negative claims, so its text
        # quotes negative claims as examples. Screening it for negations would reject the
        # rule for describing its own subject.
        check("honest-gates: absence claims cite the search, not a line",
              re.search(r"absence claim[\s\S]{0,240}(scope|grep)", hg_text, re.I)
              is not None,
              "no guidance for an absence claim ('nothing wires this'), where there is "
              "no single file:line and the claim is only as strong as the search scope")
        check("honest-gates: aggregate claims routed to the sweep rule",
              affirms(hg_text, r"(emergent|aggregate) [\s\S]{0,200}sweep"),
              "no guidance for a claim over a set, which the class-predicate rule "
              "already covers — leaving the two rules unconnected")

    # Tier-1's brief and its docs-only skip live in references/task-execution.md. Both
    # are anchored on that file rather than the concatenation, with end anchors inside
    # it: an end marker that sits in the trunk precedes the reference in the
    # concatenation, so `section()` finds no end after the start and runs to the end of
    # the whole corpus. That fails open — ~30k chars of unrelated text, and assertions
    # that pass on it while naming a site they are not reading. A vacuous pass is worse
    # here than a red, so the anchors are pinned inside the file that owns the text.
    task_exec = (SKILL.parent / "references" / "task-execution.md").read_text(
        encoding="utf-8")
    claim_sites = [
        ("Tier-1 per-task review brief",
         section(task_exec, r"## Tier 1 — the quick per-task review",
                 r"- \*\*Critical → blocking")),
        ("Tier-2 review brief",
         section(text, r"\*\*Deep code review \(Tier 2\)", r"\*\*Decisions-conformance")),
        ("docs-only Tier-1 skip",
         section(task_exec, r"- \*\*Skip for trivial/non-code diffs",
                 r"## The executor trailer")),
    ]
    for label, block in claim_sites:
        check(f"behavioral-claim site present: {label}", bool(block),
              f"could not locate the {label} block")
        check(f"behavioral-claim rule referenced at: {label}",
              affirms(block, r"behavioral claim|claims? about what the code does|"
                             r"behavioral claims"),
              f"{label} does not ask the reviewer to check behavioral claims")
    docs_skip = claim_sites[2][1]
    check("docs-only skip names the executable-behavior exception",
          re.search(r"[Ee]xception[\s\S]{0,120}executable behavior", docs_skip) is not None,
          "the docs-only skip does not carve out docs that assert executable behavior")
    # Every token in the message is actually checked — a failure text that names a kind
    # the tuple omits claims coverage the check does not have.
    claim_kinds = ("commands", "flags", "env vars", "exit codes")
    missing_kinds = [tok for tok in claim_kinds if tok not in docs_skip]
    check("docs-only exception lists the claim kinds it covers",
          not missing_kinds,
          f"the exception does not name these claim kinds, so a docs diff asserting "
          f"them would still auto-skip Tier 1: {', '.join(missing_kinds)}")
    check("docs-only exception turns on asserting, not merely mentioning",
          re.search(r"asserting[\s\S]{0,40}not[\s\S]{0,20}mentioning|"
                    r"asserting a fact about", docs_skip, re.I) is not None,
          "the exception's trigger is not scoped to *asserting* a fact — 'naming' a "
          "flag would make nearly every docs diff in this file non-trivial")

    # ---- 11 — dispatch fidelity. One assertion per rule; see the docstring for why
    # this group is deliberately small. Each names the rule it would lose.
    pp = (SKILLS_ROOT / "planning-projects" / "SKILL.md").read_text(encoding="utf-8")
    dpa = (SKILLS_ROOT / "dispatching-parallel-agents" / "SKILL.md").read_text(
        encoding="utf-8")

    # Anchored past the `YES | NO` field gloss: that `NO` is a FIELD VALUE in a fenced
    # block (not a code span, so it survives the backtick blanking) and reads as a
    # negation. Screening prose means screening prose only.
    check("Parallel: YES is defined as a dispatch obligation",
          affirms_claim(flat(pp), r"YES obligates dispatch"),
          "the authoring skill no longer defines YES as an obligation, so an author and "
          "an executor can read the same field two ways")
    check("no permissive gloss survives in the authoring skill",
          not re.search(r"can a sub-agent run this concurrently|it can be dispatched",
                        pp, re.I),
          "a permissive gloss is back: YES reads as 'a subagent could do this'")
    # `affirms`, not `affirms_claim`: the sentence continues "...and is NEVER a reason to
    # hand the task back to the caller", which reinforces the rule but is a negation token
    # inside the claim's own sentence. This is the absence-subject case, one clause over.
    split = section(text, r"### Step 3\.2 — Split by parallelism",
                    r"### Step 3\.3 — Red-Green loop")
    review_scope = section(text, r"### Review scope — the machinery scales to the change",
                           r"## Phase 3 — Stage execution")
    check("review effort is tiered to the diff, and the tier is declared",
          affirms_claim(review_scope,
                        r"the declaration is what makes the choice reviewable"),
          "the review machinery runs at one weight regardless of what it reviews, and a "
          "downgrade leaves no record — the cost nobody compares to what it protects")
    check("format and tier compose as shape-vs-depth, not lighter-wins",
          affirms_claim(review_scope,
                        r"format decides the review's SHAPE\. The tier decides its DEPTH"),
          "nothing says how format and tier combine, so a Light plan with a heavy tier "
          "is compliant whichever weight it runs at")
    check("a process plan must name what it removes",
          affirms_claim(flat(pp), r"adds an obligation names what it removes"),
          "plans can add mandatory steps without ever retiring one, so the process grows "
          "monotonically and each addition looks individually defensible")

    check("a file conflict serializes the dispatch instead of inlining it",
          affirms_claim(split, r"serialize the dispatches"),
          "a file-conflicting YES task routes to the main session again — the one "
          "documented authorization to inline a task the plan marked for dispatch")

    check("a lone ready task is still dispatched",
          affirms(flat(dpa), r"lone ready task is \*\*still dispatched\*\*"),
          "|S| = 1 can return control to the caller again, which is how a stage with one "
          "ready task inlines it while looking compliant")

    roster = section(text, r"### Dispatch roster and capability probe",
                     r"## Phase 3 — Stage execution")
    closeout_report = section(text, r"9\. Report to the user with:", r"\n10\. ")
    resets = section(text, r"## Context resets at stage boundaries",
                     r"## Progress state file")
    check("the Preflight roster/probe block is present", bool(roster),
          "could not slice the dispatch roster section — the two checks below would "
          "pass vacuously over an empty string")
    # Both patterns tolerate an inserted qualifier and the leading case, and no further:
    # bare literals false-alarm on a meaning-preserving rewrite — naming the probe's
    # agent type ("Dispatch one throwaway `general-purpose` subagent") or widening the
    # sweep's scope ("sweep **every task in the plan, across all stages**") breaks a pin
    # while strengthening the prose.
    # The sweep pattern KEEPS a right boundary ([,*]): without it "sweep **every task in
    # the plan's first stage**" would match, which is the very defect the rule forbids
    # ("A roster covering only the first stage is not a roster") and which no other
    # assertion pins. Deleting either sentence still fails, which is what these assert.
    check("Preflight probes dispatch and declares a roster",
          affirms_claim(roster, r"[Dd]ispatch one throwaway[^.]{0,40}subagent")
          and affirms_claim(roster, r"[Ss]weep \*\*every task in the plan[,*]"),
          "Preflight no longer probes dispatch or sweeps the plan for YES tasks, so an "
          "unavailable dispatch is discovered at close-out instead of before Stage 1")
    check("the probe is conditioned on a non-empty roster",
          affirms_claim(roster, r"only if the roster is non-empty"),
          "the probe runs unconditionally again, so a plan that will never dispatch "
          "still burns a throwaway one to prove a capability nothing uses")
    check("Review: skip annotations are snapshotted at Preflight",
          affirms_claim(roster, r"Snapshot the `Review: skip` annotations"),
          "nothing pins the annotations to the run's base commit, so an executor can "
          "add one mid-run and cite it as a user opt-out")
    check("close-out reconciles dispatch plan-wide against the roster",
          affirms_claim(closeout_report, r"reconciled against Preflight's roster"),
          "the roster is declared plan-wide but answered only per stage, so a skipped "
          "or silent stage gate leaves a hole no per-stage check can see")
    check("the handoff carries the ledgers a reset would discard",
          affirms_claim(resets, r"dispatch and review lines are carried here"),
          "the gate's ledgers stay transcript-only while the skill recommends discarding "
          "that context — and the review ledger cannot be rebuilt from git")

    check("an unavailable dispatch fails Preflight",
          affirms_predicate(roster, r"dispatch is unavailable or disallowed",
                            r"Preflight fails and you stop"),
          "an unavailable dispatch no longer stops the run, so the executor substitutes "
          "inline execution and the user never gets the decision")

    commit_rule = section(text, r"7\. \*\*Commit after each green task", r"### Step 3\.4")
    check("every per-task commit carries an executor trailer",
          affirms_claim(commit_rule, r"ends with an executor trailer"),
          "nothing records WHO ran a task, so an inlined YES task and a dispatched one "
          "are byte-identical again — and the trailer is what makes the rest enforceable")
    check("the trailer is constrained to one physical line",
          affirms_claim(commit_rule, r"trailer to one physical line"),
          "a wrapped trailer silently vanishes from every %(trailers:...) query, so the "
          "convention documents a check that returns nothing")

    # Scoped to the TRUNK and ended on the next top-level heading. An end anchor that is
    # an inline run in one file and a `## ` heading in another can miss where it is
    # expected and hit a case-insensitive bullet 56,637 chars and six files later, and
    # the assertions below would then bite only by the accident of which files sort
    # inside that span. Both properties this needs — the right file, and an end anchor
    # that exists in it — are fixed here rather than left to luck.
    gate_step = section(skill_only, r"### Step 3\.5 — Stage gate",
                        r"## Context resets at stage boundaries")
    check("the gate reports dispatched-vs-inline with a reason",
          affirms_claim(gate_step, r"dispatched-vs-inline counts")
          and affirms_claim(gate_step, r"a reason for every inlined"),
          "the gate stops counting dispatch, so a run can reach close-out with inlined "
          "YES tasks and nobody noticing")
    check("the gate report says who reviewed and which diff",
          affirms_claim(gate_step, r"the agent that ran it")
          and affirms_claim(gate_step, r"the diff it saw"),
          "a gate can report green without saying who reviewed what, so an unrun review "
          "and a passed one leave the same record")

    stops = section(text, r"## Stop conditions", r"## When to revisit")
    check("an unperformable mandated dispatch or review is a Stop condition",
          affirms(stops, r"mandated verification or dispatch cannot be performed"
                         r"|mandated (dispatch|review) cannot be (run|performed)"),
          "an unavailable dispatch or reviewer no longer stops the run")
    check("inline substitution is refused as a resolution",
          re.search(r"[Ss]ubstituting inline execution[^.]{0,80}not a documented "
                    r"resolution", stops) is not None,
          "the Stop entry does not refuse the substitution, so it reads as advice")

    # Bound this to ONE file's opt-out block: reading trunk+references means a \Z end
    # anchor runs past the end of one file and swallows every later one — review-scope.md
    # carries its own "**Review opt-out.**" heading and older wording, so an unbounded
    # slice over the concatenation would let these assertions pass on that copy even if
    # the live block were deleted outright.
    #
    # The block lives in references/integration.md, where `## Review opt-out` is the
    # final section — so \Z is bounded by the file itself. If a later edit appends a
    # section there, re-point the end anchor rather than widening the slice. The trunk
    # keeps the pointer
    # to it (Integration), which the DEAD-PATH half of check-extraction-integrity.py
    # verifies actually resolves.
    integration_md = SKILL.parent / "references" / "integration.md"
    review_optout = section(integration_md.read_text(encoding="utf-8"),
                            r"## Review opt-out", r"\Z") if integration_md.is_file() else ""
    check("the review opt-out block is locatable", bool(review_optout),
          "no '## Review opt-out' section in references/integration.md — the block the "
          "four assertions below pin is deleted or has moved")
    check("review skips are closed to two reasons",
          affirms_claim(review_optout, r"the list is closed at two"),
          "the review opt-out no longer states its reasons as an exhaustive pair, so a "
          "third situation can be read in, such as an uninstalled reviewer")
    check("a reviewer that cannot be dispatched is a Stop condition",
          affirms_claim(review_optout, r"Stop condition for a mandated review"),
          "an unavailable code-reviewer has no stated resolution, so the run proceeds on "
          "whatever checks remain and the user never gets the decision")
    check("only a snapshotted annotation counts as an opt-out",
          affirms_claim(review_optout,
                        r"counts as an opt-out when Preflight's snapshot lists it"),
          "an annotation read at skip time is accepted again, which cannot distinguish "
          "a user's decision from the executor's own")
    check("an opt-out is evidenced by quoting the user",
          affirms_claim(review_optout, r"quoting the user's own\s+words"),
          "an asserted opt-out and an evidenced one leave the same artifact again")
    # The negation is INSIDE the pattern deliberately: the requirement itself is negative,
    # so affirms_claim would screen its own `not` and reject true prose. Dropping the `not`
    # deletes the match and turns this red. A trailing clause that leaves the sentence intact
    # and then takes it back still passes; that gap is stated here, not hidden.
    check("executor judgment is named as not constituting an opt-out",
          re.search(r"\*\*Executor judgment is not an opt-out\.\*\*", review_optout)
          is not None,
          "the file no longer says an executor's own judgment fails to be an opt-out, "
          "which is the only reading that makes the quote requirement bite")
    escape = REVIEW_ESCAPE_RE.search(text)
    check("no review or evaluator excuses itself on availability",
          escape is None,
          f"an availability-based excuse for skipping a review is back: "
          f"{escape.group(0) if escape else ''}")

    # Every slice this suite took must have found its end anchor. Checked last, so it
    # reports on all of them at once. A fall-through does not fail the assertion that
    # used the slice — it makes that assertion read unrelated text while still naming
    # its site, which is how a guard goes quiet without going red.
    check("no slice fell through its end anchor",
          not FELL_THROUGH,
          "these slices ran past their end anchor and are reading unrelated text: "
          + "; ".join(FELL_THROUGH))
    check(f"no slice exceeds {MAX_SLICE} chars",
          not OVERSIZED,
          "these slices are too long to be the section they name — their end anchor "
          "most likely matched in a different file: " + "; ".join(OVERSIZED))

    check("sweep examined a non-empty set", scanned > 0,
          "no markdown files scanned — an empty sweep is not a pass")
    check(f"no {BANNED_PHRASE!r} under planning/skills/", not offenders,
          f"instance-shaped framing survives at: {', '.join(offenders)}")

    # 11. Hardware and remote access count as present only when a probe ran and got an
    #     answer; an environment variable alone proves nothing. Two sites:
    #     the trunk's Preflight bullet, and the procedure in preflight-checks.md.
    _here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(_here, "..", "SKILL.md"), encoding="utf-8") as fh:
        _trunk = fh.read()
    with open(os.path.join(_here, "..", "references", "preflight-checks.md"), encoding="utf-8") as fh:
        _pre = fh.read()
    _ws = lambda pat: re.sub(r" ", r"\\s+", pat)
    _access = re.search(r"^- Access / permissions verified.*$", _trunk, re.M)
    check("Preflight's access line carries more than the bare label",
          _access is not None and re.search(r"^- Access / permissions verified$", _trunk, re.M) is None,
          "the trunk lists 'Access / permissions verified' with no probe")
    check("Preflight's access line names a probe",
          _access is not None and "probe" in _access.group(0),
          "the access bullet does not say access is proven by a probe")
    _probe = section(_pre, r"\n## Access probe", r"\n## ")
    check("preflight-checks.md has an access-probe section", bool(_probe),
          "no '## Access probe' heading in preflight-checks.md")
    check("access probe: the target comes from the repo's own scripts",
          affirms_claim(_probe, _ws(r"from the repo's own deploy, HIL or provisioning scripts")),
          "nothing says to resolve the target from the repo's own scripts")
    check("access probe: run it, write down who replied",
          affirms_claim(_probe, _ws(r"record what answered")),
          "no instruction to run the probe and keep its reply")
    check("access probe: nothing answered -> BLOCKED",
          re.search(_ws(r"nothing answered.{0,200}BLOCKED"), _probe, re.S | re.I) is not None,
          "the 'nothing answered' outcome is not mapped to BLOCKED")
    check("access probe: an unexpected reply -> investigate it",
          re.search(_ws(r"not what was expected.{0,120}investigat"), _probe, re.S) is not None,
          "the wrong-identity outcome is not mapped to investigation")
    check("access probe: an unset env var means absent config, not an absent device",
          re.search(_ws(r"missing configuration"), _probe) is not None
          and re.search(_ws(r"missing hardware"), _probe) is not None,
          "the configuration/hardware distinction is not stated")

    # 12. The amendment protocol lists what can never justify an amendment, and its two
    #     definition sites point at each other.
    _amend = section(_pre, r"\n## Amending authored ceremony", r"\n## ")
    with open(os.path.join(_here, "..", "..", "honest-gates", "SKILL.md"), encoding="utf-8") as fh:
        _hg = fh.read()
    check("amendment protocol: cost, time and disk may shrink the plan's scope, never its evidence",
          re.search(_ws(r"cost, wall-clock and disk"), _amend, re.I) is not None
          and re.search(_ws(r"re-scoping the plan"), _amend) is not None
          and re.search(_ws(r"never (?:for )?(?:re-scoping )?the evidence"), _amend) is not None,
          "the protocol lets cost, time or disk shrink the evidence instead of the plan")
    check("amendment protocol: taking a suite out of a gate command leaves the task [~] BLOCKED on it",
          re.search(_ws(r"dropped from a gate command.{0,120}`\[~\]`.{0,40}BLOCKED on that suite"), _amend, re.S) is not None,
          "the protocol omits the [~] mark for a suite taken out of a gate")
    check("amendment protocol: points at test-scope-tiers.md for which trees a stage owns",
          "test-scope-tiers.md" in _amend and re.search(_ws(r"neither touched nor depend on"), _amend) is not None,
          "the protocol does not name the tiering discriminator (trees the stage neither touched nor depends on)")
    check("cross-citation: preflight-checks § Amending cites honest-gates, and honest-gates' amendment bullet cites § Amending authored ceremony",
          "honest-gates" in _amend and "Amending authored ceremony" in _hg,
          "one of the two definition sites does not point at the other")

    # 13. The host's own footing is a safety
    #     rail; a mid-execution feature request goes back through triage.
    _rails = section(_trunk, r"\n## Safety rails", r"\n## ")
    _revisit = section(_trunk, r"\n## When to revisit earlier steps", r"\n## ")
    check("safety rail: never reconfigure the agent host's own network interfaces, routes or DNS to reach a device under test",
          re.search(_ws(r"own network interfaces, routes or DNS"), _rails) is not None
          and re.search(_ws(r"device under test"), _rails) is not None,
          "no rail names the host's own interfaces/routes/DNS")
    check("safety rail: lists the three other ways to reach the device",
          all(re.search(_ws(w), _rails) for w in (r"second interface", r"spare client", r"subagent on another machine")),
          "the rail does not name the three alternatives")
    check("safety rail: no other way to reach it -> BLOCKED",
          re.search(_ws(r"none is available.{0,60}BLOCKED"), _rails, re.S) is not None,
          "the rail does not map 'no alternative' to BLOCKED")
    check("safety rail: generalized to anything the session depends on to keep running",
          re.search(_ws(r"anything the session depends on to keep running"), _rails) is not None,
          "the rail is not generalized past networking")
    check("revisit: a mid-execution request for new work goes through planning-projects triage before implementation",
          affirms_claim(_revisit, _ws(r"mid-execution request for new work")) and re.search(_ws(r"triage"), _revisit) is not None
          and "planning-projects" in _revisit,
          "no sentence routes a mid-execution feature request through triage")
    # Literal pin with a negation as its subject: catches deletion and rewording, not an
    # outer reversal ("whether it shares the branch is up to you") — the same stated
    # limit as the honest-gates suite's pin_neg, and the reason the clause is kept short.
    check("revisit: such work does not share the plan's branch or its gate (negation-subject, literal)",
          re.search(_ws(r"does not share the plan's branch or its gate"), _revisit) is not None,
          "the branch/gate separation is not stated")

    # 12. A handoff needs a measured reason.
    #     Read from the reference directly: the rule lives there, and the trunk carries its
    #     five names and bounds. Each pin below is a sentence that a rewrite bringing back
    #     a stop by feel would have to delete.
    _ho_path = SKILL.parent / "references" / "session-handoff.md"
    _ho = flat(_ho_path.read_text(encoding="utf-8")) if _ho_path.is_file() else ""
    _rules = section(_ho, r"## The five stop rules", r"## The bounds")
    check("session-handoff: the five stop rules are named",
          all(re.search(_ws(r"\*\*" + n + r"\*\*"), _rules) for n in
              (r"Owner request", r"Sub-plan boundary", r"Context", r"Dead weight",
               r"Dated external wait")),
          "a stop rule is missing from session-handoff.md § The five stop rules")
    # The supervisor's rollover request is the stop rule whose name is the script's
    # reason prefix, so the rule and the verdict line agree.
    check("session-handoff: the owner request is `rule requested`",
          "rule requested" in _rules,
          "the owner-request stop rule is not named by the script's `rule requested` reason")
    check("session-handoff: the context rule is `now > 50`, or now plus last_stage_cost past 50%",
          affirms_claim(_rules, r"handoff when `now > 50`")
          and re.search(_ws(r"`last_stage_cost` would pass 50%"), _rules) is not None,
          "the context threshold is not stated as a handoff rule")
    check("session-handoff: the first stage of a session always runs",
          re.search(_ws(r"first stage of a session always runs"), _rules) is not None,
          "the first-stage bound is gone — a fresh session could hand off before doing work")
    check("session-handoff: dead weight needs disjoint AND the 25% floor",
          re.search(_ws(r"`disjoint`.{0,120}above 25%"), _rules, re.S) is not None,
          "the dead-weight rule lost its disjointness test or its floor")
    check("session-handoff: a sub-plan boundary hands off unless under 25%",
          re.search(_ws(r"handoff, unless the context is under 25%"), _rules) is not None,
          "the sub-plan-boundary floor is not stated")
    _bounds = section(_ho, r"## The bounds", r"## On `continue`")
    # Negation-subject literals: the rule IS a "never"; screening the clause would reject it.
    check("session-handoff: `unknown` never stops (its bound)",
          re.search(_ws(r"`unknown` never stops"), _bounds) is not None,
          "the unknown-never-stops bound is gone")
    check("session-handoff: a stop without the script's reason: line is not a legal stop",
          re.search(_ws(r"stop without the script's `reason:` line is not a legal stop"),
                    _bounds) is not None,
          "a bare stop is no longer called illegal")
    _on_ho = section(_ho, r"## On `handoff`", r"\Z")
    check("session-handoff: the RESUME HERE block carries reason: verbatim",
          "RESUME HERE" in _on_ho
          and re.search(_ws(r"reason: <the script's reason: line, verbatim>"), _on_ho) is not None,
          "the handoff block no longer carries the script's reason verbatim")
    check('session-handoff: a handoff writes phase: "handoff"',
          'phase: "handoff"' in _on_ho, "the state-file phase is not named")
    # The handoff id rides the RESUME HERE block, the state file and the `ready`
    # envelope. Position, not presence: `handoff-envelope.py
    # verify` reads `handoff_id:` from the block, so a copy outside the template does not
    # count. Read from the raw text — the fence is a line structure `flat` erases.
    _on_ho_raw = section(_ho_path.read_text(encoding="utf-8") if _ho_path.is_file() else "",
                         r"## On `handoff`", r"\Z")
    _hdr = _on_ho_raw.find("**RESUME HERE (<YYYY-MM-DD>):**")
    _fence_end = _on_ho_raw.find("```", _hdr) if _hdr >= 0 else -1
    _hid = _on_ho_raw.find("handoff_id: <id>", _hdr) if _hdr >= 0 else -1
    check("session-handoff: `handoff_id: <id>` sits inside the RESUME HERE block template",
          _hdr >= 0 and _fence_end > _hdr and _hdr < _hid < _fence_end,
          "the RESUME HERE template carries no `handoff_id: <id>` line between its heading "
          "and its closing fence — a successor's verify would fail id-mismatch")
    _mint = _on_ho_raw.find("handoff-envelope.py new-id")
    check("session-handoff: step 0 mints the id with `handoff-envelope.py new-id`, before the block",
          0 <= _mint < _hdr,
          f"§ On `handoff` must mint the id before the RESUME HERE template (new-id@{_mint}, "
          f"block@{_hdr})")
    _state = _on_ho_raw.find('`phase: "handoff"`')
    _ready = _on_ho_raw.find("handoff-envelope.py ready")
    check("session-handoff: the `ready` envelope is written after the state-file step",
          0 <= _state < _ready,
          f"§ On `handoff` must write `ready` after phase \"handoff\" (state@{_state}, "
          f"ready@{_ready})")
    # The template parses as `verify` reads it: fill it, dedent it to column 0 as step 1
    # says to write it, and run handoff-envelope.py's own block parser over it.
    _he = None
    try:
        _spec = importlib.util.spec_from_file_location(
            "handoff_envelope", SKILL.parent / "scripts" / "handoff-envelope.py")
        _he = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_he)
    except Exception:  # noqa: BLE001 — reported by the check below
        _he = None
    _tpl = _on_ho_raw[_hdr:_fence_end] if 0 <= _hdr < _fence_end else ""
    _filled = "\n".join(l.strip() for l in _tpl.replace("<YYYY-MM-DD>", "2026-10-05")
                         .replace("<id>", "h-" + "0" * 20).replace("<repo root>", "/r")
                         .replace("<branch>", "feat/x").splitlines())
    _blk = _he.last_block(_filled) if _he else None
    check("session-handoff: the filled template parses as verify reads it",
          _blk is not None and _he.block_field(_blk, "handoff_id") == "h-" + "0" * 20
          and _he.block_field(_blk, "cwd") == "/r" and _he.block_field(_blk, "branch") == "feat/x",
          "handoff-envelope.py's block parser does not read handoff_id/cwd/branch from the "
          "RESUME HERE template — a successor's verify would fail")
    check("session-handoff: from the state-file step on, the session owns nothing",
          "owns nothing" in _on_ho,
          "the ownership-surrender rule is gone from § On `handoff`")
    _psf_path = SKILL.parent / "references" / "progress-state-file.md"
    check("progress-state-file: the schema carries `handoff_id`",
          _psf_path.is_file() and "handoff_id" in _psf_path.read_text(encoding="utf-8"),
          "the state file schema does not name `handoff_id`")
    # Before it owns anything, a session launched with --adopt-handoff checks that the
    # handoff it resumes is the one addressed to it: verify, then accept.
    # The file's last section, so `\Z`: its step 3 names `## Decisions in force` inline,
    # which a `## ` end anchor would cut it at.
    _adopt = section(_ho, r"## Adopting a handoff \(`--adopt-handoff <id>`\)", r"\Z")
    check("session-handoff: the adoption section exists",
          "## Adopting a handoff (`--adopt-handoff <id>`)" in _ho,
          "session-handoff.md has no `## Adopting a handoff (`--adopt-handoff <id>`)` section")
    _vi = _adopt.find("handoff-envelope.py verify")
    _ai = _adopt.find("handoff-envelope.py accept")
    _pi = _adopt.find("handoff-envelope.py plan")
    check("session-handoff: adoption runs `plan`, then `verify`, then `accept`",
          0 <= _pi < _vi < _ai,
          f"plan, verify, accept must come in that order in the adoption section "
          f"(plan@{_pi}, verify@{_vi}, accept@{_ai})")
    check("session-handoff: accept and fail are one-shot per id",
          re.search(_ws(r"one-shot per id"), _adopt) is not None,
          "the adoption section does not say a second accept/fail of an id is refused")
    check("session-handoff: the manual resume path runs no verify",
          re.search(_ws(r"manual path.{0,200}no `verify`"), _adopt, re.S) is not None,
          "the adoption section no longer keeps the manual resume free of a verify step")
    # SKILL.md's Phase 1 itself — the entry path a started session follows. `text` joins
    # the references, where the section already says it.
    _phase1 = section(SKILL.read_text(encoding="utf-8"), r"## Phase 1", r"## Phase 2")
    check("trunk: Phase 1 routes `--adopt-handoff` to the adoption section",
          "--adopt-handoff" in _phase1 and "Adopting a handoff" in _phase1,
          "the trunk carries no pointer to adopting a handoff")
    _resets = section(text, r"## Context resets at stage boundaries", r"## Progress state file")
    check("trunk: the context-reset section points at session-handoff.md and names the rules",
          "session-handoff.md" in _resets and "context-usage.py" in _resets
          and all(n in _resets for n in ("requested", "context", "dead weight", "sub-plan",
                                         "dated wait")),
          "the trunk no longer carries the measured stop rule's names and pointer")
    # Retired advice: an unmeasured reset suggestion. Swept across every markdown file in
    # the plugin, because a copy can sit outside the reference that states the rule (the
    # trunk's master-plans paragraph is one such site).
    _retired = ("prefer the reset", "per session, ideally")
    _ret_off = []
    for _p in sorted((SKILLS_ROOT.parent).rglob("*.md")):
        if "fixtures" in _p.parts:
            continue
        for _i, _line in enumerate(_p.read_text(encoding="utf-8", errors="replace")
                                   .splitlines(), 1):
            if any(r in _line for r in _retired):
                _ret_off.append(f"{_p.relative_to(SKILLS_ROOT.parent.parent)}:{_i}")
    check("retired: no 'prefer the reset' / 'per session, ideally' under planning/**/*.md",
          not _ret_off, "the unmeasured reset advice survives at: " + ", ".join(_ret_off))

    # 13. The task field is spelled `Dispatch:`. `Parallel:` sounds like a statement
    #     about concurrency, which is not what the field decides. Each pin is a site a revert
    #     would have to touch.
    _pp_root = SKILLS_ROOT / "planning-projects"
    _tmpl = (_pp_root / "references" / "plan-document-template.md").read_text(encoding="utf-8")
    check("template: the task field is spelled `- **Dispatch:**`",
          re.search(r"^- \*\*Dispatch:\*\* YES", _tmpl, re.M) is not None
          and re.search(r"^- \*\*Parallel:\*\*", _tmpl, re.M) is None,
          "the plan template writes the retired `Parallel:` spelling (or no field) again")
    check("authoring: `Dispatch: YES` obligates a dispatch",
          affirms_claim(flat(pp), r"YES obligates dispatch")
          and re.search(r"Mark a task `Dispatch: YES`", pp) is not None,
          "the authoring skill no longer defines the renamed field as an obligation")
    check("executing: Step 3.2 reads the `Dispatch` field",
          re.search(r"Dispatch: YES", split) is not None,
          "Step 3.2 no longer names the field it splits on")
    # Assembled with join, not written literally: this file sits under planning/, which
    # the sweep reads — a literal would turn the check red against itself.
    _retired_phr = (" ".join(("own", "context-hygiene", "criteria")),
                    " ".join(("delegate", "by", "signal")))
    _off = []
    for _p in sorted(SKILLS_ROOT.parent.rglob("*.md")):
        if "fixtures" in _p.parts:
            continue
        _body = _p.read_text(encoding="utf-8", errors="replace")
        for _r in _retired_phr:
            if _r in _body:
                _off.append(f"{_p.relative_to(SKILLS_ROOT.parent.parent)} ({_r!r})")
    check("retired: executor discretion over a NO task stays deleted across planning/**/*.md",
          not _off, "a delegate-by-judgment rule is back: " + ", ".join(_off))
    _both = {
        "planning-projects/SKILL.md": pp,
        "executing-plans/SKILL.md": SKILL.read_text(encoding="utf-8"),
    }
    check("validate-dispatch.py is named in both skills",
          all("validate-dispatch.py" in body for body in _both.values()),
          "a skill stopped running the dispatch-field validator: "
          + ", ".join(k for k, v in _both.items() if "validate-dispatch.py" not in v))

    # 14. Runtime enforcement. A roster reconciliation that is only a report line can miss
    #     a task, and a stage-level `Depends on:` that nothing parses lets a later stage
    #     close before an earlier stage's gate. Each is an exit status, and these pins
    #     keep the prose calling it.
    check("close-out step 9 runs --dispatch-check as the reconciliation gate",
          "--dispatch-check" in closeout_report
          and affirms_claim(closeout_report, r"reconciled against Preflight's roster"),
          "close-out reconciles dispatch by reading trailers again, so a rostered task "
          "run inline without a reason reaches merge as a report line nobody acts on")
    # The check opens Step 3.0, the first thing a stage does, ahead of its premise.
    step30 = section(SKILL.read_text(encoding="utf-8"),
                     r"### Step 3\.0 — Test the stage's premise", r"### Step 3\.1")
    check("Step 3.0 runs --stage-order-check before a stage opens",
          "--stage-order-check" in step30
          and affirms_claim(step30, r"fully `\[x\]` gate"),
          "nothing stops a stage from opening ahead of the gate it waits on")

    # 15. Live-evidence remediation. A fix fitted to one capture passes its fake and fails
    #     the live re-run, round after round, when the remediation sweeps code and never
    #     the captures. These pin four things: the capture sweep ahead of any live
    #     re-run, its trailer, a stated property tested on a second capture, and a label
    #     on any fake that encodes the tested behaviour.
    gfp = (SKILL.parent / "references" / "gate-failure-procedure.md").read_text(encoding="utf-8")
    live = section(gfp, r"(?m)^## Remediation that re-runs a live check", r"(?m)^## ")
    check("gate-failure-procedure: § Remediation that re-runs a live check present",
          bool(live), "no live-evidence remediation section")
    check("live remediation: every real capture runs through the fix ahead of the live re-run",
          affirms_claim(live, ws(r"proven against every real capture or fixture of that kind"))
          and affirms_claim(live, ws(r"before a remediation round re-runs a live or device-bound check")),
          "the capture sweep, or its position before the live re-run, is absent or negated")
    check("live remediation: the sweep command is recorded as a `fixture-sweep:` trailer",
          "`fixture-sweep:`" in live
          and affirms_claim(live, ws(r"recorded in the commit as a `fixture-sweep:` trailer")),
          "the `fixture-sweep:` trailer is unnamed or optional")
    check("live remediation: a capture-derived rule states the property it checks",
          affirms_claim(live, ws(r"states the property it checks")),
          "no property statement")
    check("live remediation: the test holds a second real capture with other incidental detail",
          affirms_claim(live, ws(r"one real capture that differs from the source in its incidental parts")),
          "a one-capture test is allowed")
    check("live remediation: a fake encoding the behaviour under test is labelled",
          affirms_claim(live, ws(r'is named in the gate report as "unproven against the real system"')),
          "the fake that encodes the tested behaviour carries no unproven label")

    # 16. Code rewritten late in a gate gets a reader. An Important fix is closed by
    #     re-running its own scope, with no second review, so new code written in the
    #     budget's final round could merge with nobody having read it. These pin both
    #     definitions, the review (or its battery stand-in), its tier bound and the record.
    redesign = section(gfp, r"(?m)^## A redesign the gate closes on", r"(?m)^## ")
    check("gate-failure-procedure: § A redesign the gate closes on present", bool(redesign),
          "no redesign section")
    check("redesign: a repair is defined",
          affirms_claim(redesign, ws(r"A \*\*repair\*\* is a change inside code the review read")),
          "the repair definition is absent")
    check("redesign: a redesign is defined",
          affirms_claim(redesign, ws(r"A \*\*redesign\*\* is a new file or function, or a replacement of logic the review read")),
          "the redesign definition is absent")
    check("redesign: closing on new code nobody read buys one review of that diff, or a battery entry",
          # The subject is an absence ("no review has read"), so it is pinned by presence;
          # the obligation it carries is screened.
          re.search(ws(r"A redesign no review has read when the gate closes"), redesign) is not None
          and affirms_claim(redesign, ws(r"gets one review of the redesign's diff alone"))
          and affirms_claim(redesign, ws(r"or a deterministic substitute")),
          "new code nobody read can still close on its own scope re-run")
    check("redesign: keyed to the gate closing green or on an exhausted budget",
          affirms_claim(redesign, ws(r"whether the gate closes green or on an exhausted budget")),
          "the rule is keyed to the budget-ending round only — a gate closing green in "
          "round 1 ships its redesign unread")
    check("redesign: the review is an explicit exception to the round and re-dispatch rules",
          # Again an absence by design ("is not a round"): presence, beside the exception
          # sentence that frames it, screened.
          re.search(ws(r"it is not a remediation round and does not count against the budget"),
                    redesign) is not None
          and affirms_claim(redesign, ws(r"This review is an exception to two rules")),
          "the review contradicts 'a re-dispatched review is a round' with no stated exception")
    check("redesign: bounded to the tier that funded the original review",
          affirms_claim(redesign, ws(r"at the tier that funded the original review"))
          and re.search(ws(r"Below tier `light`, nothing is added"), redesign) is not None,
          "the tier bound, or the below-light clause, is absent")
    check("redesign: the review-line form is stated",
          "`round K: redesign — reviewed by <subagent_type>`" in redesign
          and "`round K: redesign — battery <name>`" in redesign,
          "the record form is unspecified")

    # 16b. Both exceptions pinned, the one-review rule, the
    #      termination sentence, and the cross-references at the sites that count rounds.
    check("redesign: second exception — owed though nothing Blocking was fixed",
          affirms_claim(redesign, ws(r"it is owed though nothing Blocking was fixed")),
          "the second exception is absent, leaving a false 'two rules'")
    check("redesign: every unread redesign of the gate goes into the one review",
          affirms_claim(redesign, ws(r"Every unread redesign of the gate goes into that one review")),
          "several unread redesigns could each buy a review")
    check("redesign: a redesign answering this review is named unread, so the loop ends on the budget",
          "`round K: redesign — unread`" in redesign
          and re.search(ws(r"the loop ends on the budget"), redesign) is not None,
          "a redesign answering the review could buy another review, without end")
    stagegate_text = (SKILL.parent / "references" / "stage-gate.md").read_text(encoding="utf-8")
    for site, text in (
            ("SKILL.md budget", SKILL.read_text(encoding="utf-8")),
            ("gate-failure-procedure.md budget", gfp),
            ("stage-gate.md", stagegate_text)):
        check(f"cross-reference to the redesign exception at {site}",
              re.search(ws(r"A redesign the gate closes on"), text) is not None
              or re.search(ws(r"unread redesign"), text) is not None,
              f"{site} counts rounds or re-dispatches with no pointer to the redesign exception")
    check("stage-gate.md: active verification, new admission and owed redesign review agree",
          affirms_claim(stagegate_text, ws(r"Required verification belongs to the active round"))
          and affirms_claim(stagegate_text, ws(r"A separately initiated critique starts new work through begin-round"))
          and affirms_claim(stagegate_text, ws(r"A review of an unread redesign is owed verification")),
          "transactional accounting or the owed redesign-review boundary is absent")

    print(f"assertions run ({len(RAN)}), files swept: {scanned}")
    for name in RAN:
        print(f"  - {name}")
    if FAILURES:
        print("\nFAILURES:", file=sys.stderr)
        for f in FAILURES:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    print("\nOK — gate-remediation contract present in skill text (prose contract only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
