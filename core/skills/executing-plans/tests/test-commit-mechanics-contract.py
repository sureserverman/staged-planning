#!/usr/bin/env python3
"""Structure suite for the commit-mechanics contract — run directly (CI convention):
    python3 core/skills/executing-plans/tests/test-commit-mechanics-contract.py

A PROSE contract, not behavior. The suite asserts that the skill text states a set
of execution-discipline rules — the commit mechanics for a plan that lives outside
the repo, the turn discipline that keeps an announcement from standing in for the
work, and the single form a report uses to ask the user for something. It cannot
verify that an executor obeys any of them — stated plainly, because a structure
suite that implies behavioral coverage is the falsehood class `honest-gates` exists
to catch.

What it pins (commit mechanics):
  1. The trunk NAMES the plan-outside-the-repo case — that a plan can live outside
     the repo it plans, wherever the records home is elsewhere, not an edge case.
  2. It mandates editing the plan at an ABSOLUTE PATH and forbids `cd`-ing to the
     plan's directory to do it.
  3. It mandates running the commit FROM THE REPO ROOT.
  4. It names the failure the rule prevents (`fatal: not a git repository`), so
     the rule reads as a guard against a concrete error rather than as a style note.
  5. `references/task-execution.md` carries the elaboration, so the reference the
     trunk points at is not a dead end.

Why the rule needs to exist at all: rule 7 mandates committing "the flipped
`Status: [x]`" in the same commit as the work, which silently assumes the plan
file is inside the repo. With a plan outside the repo it is not, and the natural
executor move is to chain a directory change into the plan's directory before the
git command, which fails the commit.

What it pins (turn discipline):
  6. § Run to completion forbids ending a turn on a stage or task announcement,
     and requires the tool call that opens the next stage/task in the SAME turn
     as the sentence announcing it, or instead of it.
  7. It names the shape it forbids — a turn whose last words are "Starting Stage
     N." with no tool call — so the rule is concrete rather than stylistic.

What it pins (the ACTION NEEDED callout):
  8. Both report-owning references — stage-gate.md and close-out.md — define an
     `ACTION NEEDED:` block with NUMBERED options.
  9. Both forbid a report that carries one from also announcing that it is
     proceeding.
 10. Both state that a report carries at most ONE such block.
     Checked as a SET across the two files, because a gate report and a close-out
     report are two instances of one defect class and a check naming only one of
     them cannot fail on the other.

     **Coverage limit, stated because overstating it is the defect this suite
     exists to catch.** The rule calls for "a single isolated" form. What is
     checked is that each reference *states* the one-block rule —
     a prose contract has no report to count blocks in. A report that violates
     the rule at runtime is not something any assertion here can see.

What it pins (the honest-gates capsule):
 11. The four load-bearing honest-gates rules, plus the BLOCKED antecedent, appear
     verbatim BOTH in honest-gates/SKILL.md and in the trunk's Step 3.5. Pinning
     both directions is the point: a one-way check would let the restatement rot
     the moment honest-gates was reworded.
 12. The capsule keeps RED as its own state, routed to the gate-failure procedure.
     Entry 11's fifth phrase and this assertion pin the connective glue too: a
     bridge such as "Otherwise BLOCKED, never green" negates the conjunction "ran
     AND passed" and so swallows RED — and because glue is original prose rather
     than a quoted rule, nothing else pins it. The general rule: four faithful
     quotes can still be joined by an unfaithful sentence.

What it pins (the dispatched-vs-inline review ledger):
 13. Both the trunk's gate-report review line and stage-gate.md's ledger name an
     inline-run mandated review a SUBSTITUTION, require a recorded reason, and
     state that an unrecorded one FAILS THE GATE — a consequence, not a request.
 14. The trunk states the review bound in proximity to its label, not as two
     unrelated mentions. The bound must not let a DISPATCH FAILURE authorise the
     substitution: integration.md § Review opt-out closes the excuses at two and
     says an undispatchable reviewer is neither — it is a Stop condition, and the
     choice is the user's. A bound that let it through would invert the source it
     cites.

The five rules share one suite because they share one failure mode: a rule the
executor reads and then does not apply at the moment of pressure. Rule text is
the only artifact any of them can be checked against.

Read-only. Exit 0 when every promise holds, 1 otherwise.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "SKILL.md"
TASK_EXECUTION = HERE.parent / "references" / "task-execution.md"

FAILURES = []
RAN = []


def check(name, ok, detail=""):
    RAN.append(name)
    if not ok:
        FAILURES.append(f"{name}: {detail}" if detail else name)


def flat(s):
    """Collapse whitespace so a matcher is not defeated by a line wrap.

    The trunk is hard-wrapped at ~95 columns, so any phrase this suite looks for
    may carry a newline plus indentation — or a blockquote marker — in the middle
    of it. Matching the raw text makes every assertion depend on where the
    paragraph happened to wrap — it reports "the rule is missing" for a rule that
    is present, which is the one failure mode a prose contract must not have. The sibling suite
    test-gate-remediation-contract.py normalizes for the same reason.
    """
    # Blockquote markers go too. A rule the trunk QUOTES rather than states is
    # still the rule, but `\s+` collapsing turns "> " into an interleaved token
    # that splits every phrase spanning a line — a present rule reads as absent.
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s*>\s?", "", s))


def slice_between(text, start, end, label):
    """Return the span between two anchors, or the whole text if either is absent.

    Falling back to the whole text is deliberate: a missing anchor is reported by
    its own assertion, and a slice that silently became empty would make every
    assertion using it fail for the wrong stated reason.
    """
    i = text.find(start)
    if i < 0:
        return text, False
    j = text.find(end, i + len(start))
    if j < 0:
        return text[i:], False
    return text[i:j], True


def main():
    text = flat(SKILL.read_text(encoding="utf-8"))

    # The rules must land where the executor is when it needs them: inside the
    # Red-Green loop, at the commit rule. A correct rule stated in a section the
    # executor has already passed is the "buried decision point" failure wearing a
    # different hat.
    loop, loop_anchored = slice_between(
        text, "### Step 3.3 — Red-Green loop", "### Step 3.4", "Step 3.3")
    check("Step 3.3's anchors both resolve", loop_anchored,
          "the Red-Green loop section could not be sliced — its heading or "
          "Step 3.4's heading moved, and every assertion below read the whole file")

    # (1) The plan-outside-the-repo case is NAMED, not left to be inferred from "the repo".
    check("Step 3.3 names the plan-outside-the-repo case",
          re.search(r"outside the repo it plans", loop) is not None,
          "rule 7 still assumes the plan file is inside the repo being committed to; "
          "the plan-outside-the-repo case is not named")
    check("Step 3.3 names the records home as where that happens",
          "records home" in loop.lower(),
          "the case is described abstractly but the records home — the place it actually "
          "happens — is not named")

    # (2) Absolute-path edit, and no directory change to perform it.
    check("Step 3.3 mandates editing the plan at an absolute path",
          re.search(r"absolute path", loop) is not None,
          "no rule tells the executor to address the plan file by absolute path")
    nocd = re.search(r"[Nn]ever `cd`|do not `cd`|without `cd`", loop)
    check("Step 3.3 forbids cd-ing to the plan's directory",
          nocd is not None,
          "nothing forbids changing directory into the plan's own directory, which "
          "is the shape that fails the commit")

    # (3) The commit runs from the repo root.
    check("Step 3.3 mandates committing from the repo root",
          re.search(r"from the repo root", loop) is not None,
          "no rule says where the git command runs; 'commit after each green task' "
          "does not say from where, which is the whole defect")

    # (4) The failure is named, so the rule is concrete rather than stylistic.
    check("Step 3.3 names the failure it prevents",
          "not a git repository" in loop,
          "the error the rule prevents (`fatal: not a git repository`) is not named, "
          "so a future editor cannot tell what the rule is protecting")

    # (5) The reference the trunk points at actually carries the elaboration.
    ref = flat(TASK_EXECUTION.read_text(encoding="utf-8"))
    check("task-execution.md elaborates the commit mechanics",
          "outside the repo it plans" in ref,
          f"{TASK_EXECUTION.name} does not discuss the plan-outside-the-repo case, so "
          "the trunk's pointer leads nowhere")
    check("task-execution.md states what happens to the Status flip",
          re.search(r"Status: \[x\]|`Status:` flip|Status flip", ref) is not None,
          f"{TASK_EXECUTION.name} does not say what becomes of the Status flip when "
          "the plan file is not in the repo — the question rule 7 raises and does not answer")

    # ---- turn discipline --------------------------------------------------
    # Scoped to § Run to completion rather than to the whole trunk: the rule
    # belongs with the other rules about not handing the turn back, and a
    # trunk-wide match would pass on a sentence buried anywhere at all.
    rtc, rtc_anchored = slice_between(
        text, "## Run to completion", "## The plan is the authorization", "Run to completion")
    check("§ Run to completion's anchors both resolve", rtc_anchored,
          "the section could not be sliced — its heading or the next section's heading "
          "moved, and the turn-discipline assertions read the whole file instead")

    check("§ Run to completion forbids ending a turn on an announcement",
          re.search(r"end a turn on an announcement|end a turn on a (stage|task)", rtc)
          is not None,
          "nothing forbids a turn whose last words announce work it never started")
    check("§ Run to completion requires the opening tool call in the same turn",
          re.search(r"same turn", rtc) is not None,
          "the rule does not say WHEN the announced work must start, so 'Starting "
          "Stage 3.' followed by nothing still satisfies it")
    check("§ Run to completion allows the announcement to be dropped entirely",
          re.search(r"instead of it|or instead", rtc) is not None,
          "the rule mandates an announcement-plus-call pairing without saying the "
          "announcement is optional, which reads as requiring the announcement")
    check("§ Run to completion names the shape it forbids",
          re.search(r"Starting Stage", rtc) is not None,
          "the literal shape the rule prevents is not quoted, so a future editor "
          "cannot tell what the rule is protecting against")

    # ---- the ACTION NEEDED callout -----------------------------------------
    # Checked as a SET over both report-owning references rather than one at a
    # time: the defect is that a report buries what it wants from the user, and
    # a gate report and a close-out report are two instances of one class. A
    # check naming only one of them cannot fail on the other.
    report_sites = {
        "stage-gate.md": HERE.parent / "references" / "stage-gate.md",
        "close-out.md": HERE.parent / "references" / "close-out.md",
    }
    missing_form, missing_numbered, missing_exclusive = [], [], []
    missing_single = []
    for label, path in report_sites.items():
        body = flat(path.read_text(encoding="utf-8"))
        if "ACTION NEEDED" not in body:
            # Recorded against all three lists, not skipped with `continue`: a
            # site with no callout at all has no numbered options and no
            # exclusivity rule either, and letting those two assertions go quiet
            # would report two passes for a site that carries nothing.
            missing_form.append(label)
            missing_numbered.append(label)
            missing_exclusive.append(label)
            missing_single.append(label)
            continue
        # The options are numbered, so the user answers with a number rather
        # than by reconstructing the choice from prose.
        if re.search(r"ACTION NEEDED.{0,600}?1\.\s", body) is None:
            missing_numbered.append(label)
        # And the report may not both ask and proceed. The phrasing is pinned
        # loosely (any of the proceeding/next-stage forms) because what must not
        # happen is the PAIRING, not one particular sentence.
        if re.search(
                r"(does not also|never also|not).{0,80}(proceed|proceeding)"
                r"|(proceed|proceeding).{0,120}(and|while).{0,60}ACTION NEEDED",
                body) is None:
            missing_exclusive.append(label)
        # "Single isolated" is the rule's wording. What a PROSE contract can
        # check is that the rule is stated — a report is not an artifact this suite
        # can count blocks in. Stated here rather than left implied, because a
        # docstring claiming more coverage than the assertions carry is the exact
        # honest-gates falsehood this suite exists to catch.
        if re.search(r"[Oo]ne block per report|[Oo]ne block, last", body) is None:
            missing_single.append(label)

    check("both report references define the ACTION NEEDED form",
          not missing_form,
          "no ACTION NEEDED callout at: " + ", ".join(missing_form))
    check("the ACTION NEEDED form carries numbered options",
          not missing_numbered,
          "no numbered options under the callout at: "
          + ", ".join(missing_numbered))
    check("a report may not both ask and announce it is proceeding",
          not missing_exclusive,
          "nothing forbids pairing an unresolved decision with 'proceeding to the "
          "next stage' in one report at: " + ", ".join(missing_exclusive))
    check("both references mandate ONE such block per report",
          not missing_single,
          "the form is defined but nothing says a report carries at most one of them, "
          "so three asks in three paragraphs still satisfies it at: "
          + ", ".join(missing_single))

    # ---- honest-gates restated inline at the gate --------------------------
    # Pinned in BOTH directions. Each phrase must still be in honest-gates
    # (the source of the rule) AND in the trunk's Step 3.5 (where the executor
    # is standing when it binds). A one-way check would let the restatement rot
    # silently the moment honest-gates was reworded — which is the failure this
    # capsule exists to end, arriving from the other side.
    #
    # A pointer is not enough: an executor reads this trunk many times for each
    # time it opens honest-gates. A rule reachable only by opening a second file
    # is a rule that does not fire at the moment of pressure.
    HONEST_GATES = HERE.parent.parent / "honest-gates" / "SKILL.md"
    LOAD_BEARING = {
        "the one rule":
            "A gate is green only when its real command ran in the current environment "
            "and actually passed. Nothing else counts as green.",
        "letter vs spirit":
            "Violating the letter of a gate is violating its spirit.",
        "a behavioral claim is a gate too":
            "a sentence asserting behavior is itself a claim that something was verified",
        "BLOCKED never collapses into GREEN":
            "Never collapse BLOCKED into GREEN.",
        # The bridge between the first two rules is pinned too. An invented
        # "Otherwise BLOCKED, never green" negates the conjunction "ran AND
        # passed" and so swallows "ran and failed" — a state honest-gates calls
        # RED and routes to the gate-failure procedure, not to a blocker
        # escalation. Glue is original prose and so pinned by nothing else,
        # which is why its drift is invisible to the four assertions above.
        "BLOCKED is the check that could not run":
            "If you cannot make the real check run here, the gate is BLOCKED, not green",
        # Four parsers read `[~]`, so the trunk must say how to write the BLOCKED state
        # it mandates — not leave the instruction in honest-gates alone, a file opened
        # far less often than this trunk is read. An executor reaching for the default
        # writes `[x]` plus a note, which is verbatim the anti-pattern this rule exists
        # to stop.
        "how a BLOCKED check is written":
            "the checklist item as `- [~]`, never `- [x]` with a note explaining "
            "it away",
        # Pinned verbatim because a PARAPHRASE of honest-gates drifts, in a capsule
        # whose entire purpose is faithful restatement.
        "a dirty tree proves nothing":
            "uncommitted edits proves nothing about what the branch records",
    }
    hg = flat(HONEST_GATES.read_text(encoding="utf-8"))
    gate, gate_anchored = slice_between(
        text, "### Step 3.5 — Stage gate", "## Context resets", "Step 3.5")
    check("Step 3.5's anchors both resolve", gate_anchored,
          "the stage-gate section could not be sliced — its heading or the next "
          "section's heading moved, and the honest-gates assertions read the whole file")

    drifted, absent = [], []
    for label, phrase in LOAD_BEARING.items():
        # Strip the emphasis markers the trunk and honest-gates may each apply
        # differently; the RULE is the words, not the bolding.
        needle = phrase.replace("**", "")
        if needle not in hg.replace("**", ""):
            drifted.append(label)
        if needle not in gate.replace("**", ""):
            absent.append(label)

    check("the load-bearing rules are still worded this way in honest-gates",
          not drifted,
          "honest-gates no longer carries these verbatim, so the trunk's restatement "
          "is now a paraphrase of something that changed: " + ", ".join(drifted))
    # RED must survive as its own state in the capsule, and must still be routed
    # to the gate-failure procedure rather than to the blocker escalation.
    # Adjacency, not token presence: the defect being guarded is not "the word
    # RED disappeared" but "RED was folded back into BLOCKED", and a rewording
    # can do the second while keeping the first.
    #
    # WHAT THIS CANNOT SCREEN. It pins the routing clause as
    # written. Prose that keeps this clause and adds a contradicting one further
    # off ("...though a failed check escalates the same way") passes. The guard
    # is strongest against DELETION and against the specific collapse of RED
    # into BLOCKED; an inversion worded away from the anchor survives it,
    # the same limitation check-trunk-retention.py discloses for its markers.
    check("the capsule keeps RED distinct and routes it to the gate-failure procedure",
          re.search(r"\bRED\b,?\s+and takes the gate-failure procedure", gate) is not None,
          "the Step 3.5 capsule no longer names RED as its own state routed to the "
          "gate-failure procedure, so a check that ran and failed reads as BLOCKED "
          "and takes the blocker escalation instead of the remediation loop")
    check("the load-bearing rules are restated verbatim at Step 3.5",
          not absent,
          "the gate still reaches these only by opening honest-gates, which happens "
          "far less often than this trunk is read: " + ", ".join(absent))

    # ---- an inline-run mandated review is a recorded substitution ----------
    # Checked at BOTH sites as a set — the trunk states the rule, stage-gate.md
    # carries the ledger it is recorded in. A rule at one site and a ledger at
    # the other that do not agree is how the substitution stays invisible: every
    # mandated review can run as "Executor: inline" with zero dispatches, and no
    # artifact says so.
    STAGE_GATE = HERE.parent / "references" / "stage-gate.md"
    sg = flat(STAGE_GATE.read_text(encoding="utf-8"))
    sites = {"trunk Step 3.5": gate, "stage-gate.md": sg}

    # WHAT THESE CANNOT SCREEN, per the convention this file already
    # applies to the RED guard: all four are proximity matches with no polarity
    # awareness. "This substitution never fails the gate even with no recorded
    # reason" matches the same window as the rule it inverts. Strongest against
    # DELETION, which is how a rule decays; an in-place inversion
    # survives them, exactly as check-trunk-retention.py discloses for markers.
    no_subst, no_reason, no_failure, no_bound = [], [], [], []
    for label, body in sites.items():
        if re.search(r"substitution", body) is None:
            no_subst.append(label)
        if re.search(r"substitution.{0,400}?reason|reason.{0,400}?substitution",
                     body) is None:
            no_reason.append(label)
        # The consequence must be stated. Without it the rule is a request.
        if re.search(r"(no recorded reason|without a recorded reason|unrecorded)"
                     r".{0,160}?(fails the gate|gate fails|is a gate failure)"
                     r"|(fails the gate|is a gate failure).{0,160}?(no recorded reason"
                     r"|without a recorded reason)", body) is None:
            no_failure.append(label)

    # The bound carries equal weight. A rule stated without it gets
    # over-corrected into its own inverse — "I won't dispatch unless you
    # explicitly ask" strips the same reviews for the opposite reason.
    # Proximity, not two unanchored existence checks. The unanchored form passes
    # against a section whose bound sentence is deleted, with a stray "Bound"
    # footnote elsewhere and unrelated "the declared tier" prose carrying the
    # second half — a guard measuring nothing while reporting green.
    # Anchored on the bound sentence's own phrase, so neither a stray "Bound"
    # nor unrelated "the declared tier" prose can stand in for it.
    ceiling = re.search(r"\bBound\b[^.]{0,40}?only\s+reviews\s+the\s+declared\s+tier\s+"
                        r"mandates,?\s+never\s+a\s+dispatch\s+beyond", gate)
    # BOTH halves, not just the ceiling. The floor is the half that matters most,
    # and a check that verifies only the ceiling would pass green through the
    # deletion of exactly that sentence — measuring nothing about the thing it
    # names in its own failure message.
    floor = re.search(r"mandate\s+IS\s+the\s+authorization", gate)
    if ceiling is None or floor is None:
        no_bound.append("trunk Step 3.5")

    check("both sites name an inline-run mandated review a substitution",
          not no_subst, "not named a substitution at: " + ", ".join(no_subst))
    check("both sites require the substitution to carry a recorded reason",
          not no_reason, "no reason is required at: " + ", ".join(no_reason))
    check("both sites state that an unrecorded substitution fails the gate",
          not no_failure,
          "the rule has no stated consequence, so it is a request rather than a "
          "gate criterion, at: " + ", ".join(no_failure))
    check("the trunk states BOTH halves of the review bound, by its label",
          not no_bound,
          "the rule is missing its ceiling (only the reviews the declared tier mandates) "
          "or its floor (within the tier, the mandate IS the authorization). Without the "
          "ceiling it licenses dispatches the tier never funded; without the floor it "
          "inverts into 'never dispatch unless explicitly asked' — the "
          "over-correction the bound exists to block")

    print(f"assertions run ({len(RAN)}):")
    for name in RAN:
        print(f"  - {name}")
    if FAILURES:
        print("\nFAILURES:", file=sys.stderr)
        for f in FAILURES:
            print(f"  ✗ {f}", file=sys.stderr)
        return 1
    print("\nOK — commit-mechanics contract present in skill text (prose contract only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
