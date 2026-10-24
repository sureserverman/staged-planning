#!/usr/bin/env python3
"""Every agent that names a `CLAUDE_PLUGIN_ROOT` reference can survive it being absent.

The reference rule has two halves: an agent's reference paths are plugin-rooted, and **a reference
it cannot read is disclosed**. Left to each agent's own prose, the second half drifts — one
agent says "say so in your return", another says nothing, and neither distinguishes the
variable being UNSET from the resolved file being MISSING. That distinction is the whole
defect: `${CLAUDE_PLUGIN_ROOT}` points at a real directory in a partially-installed or
superseded plugin cache, so an unset-only check reports success and the agent proceeds
ungrounded, producing output shaped exactly like the grounded kind.

WHAT THIS DECIDES, AND WHY IT IS DECIDABLE
------------------------------------------
**The block must be the canonical contract, byte for byte after whitespace flattening.**
Not "a block containing the words confirm and exists" — the canonical text itself, held in
`contracts/reference-resolution.tmpl.md`, with exactly three substitution points:

  {PLUGIN}      the plugin directory the agent lives in, taken from its own path
  {NOUN}        the agent's output noun in the banner (REVIEW, VERIFICATION, REPRODUCTION …),
                constrained to one all-caps word
  {DEPTH_NOTE}  which of three fixed sentences applies, **computed from disk** — whether
                the plugin has `references/` at its root, under `skills/<name>/`, or both

Inferring the contract from prose — from an agent's ordinary text, or from tokens inside a
delimited block — cannot work, so this file does not try: `confirm the VARIABLE exists`
satisfies a check whose stated purpose is rejecting exactly that; `do not check that each
resolved reference exists` satisfies it too, because presence of a token cannot distinguish
an instruction from its own prohibition; a reversed fallback list passes by seeding decoy
`1.`/`2.` digits in ordinary prose. `honest-gates` § *A test does not
exist until its mutant dies* names the two ways out and only two — make the property
structural, or leave it to review and say so. A **required literal** is the structural one,
and it is available here precisely because these blocks are generated boilerplate rather
than authored prose.

So polarity, subject, order and wording are all decided, because none of them can vary:
an inverted clause is not the canonical text, and neither is a reworded one.

  NON-CANONICAL-CONTRACT  the block is not the canonical text for this plugin. The report
                          names the first differing run of words in both directions.
  NO-CONTRACT-BLOCK       no `<!-- reference-resolution-contract -->` block at all.
  DUPLICATE-CONTRACT-BLOCK  more than one pair; only one would ever be read.
  BLOCK-NOT-FIRST         the contract is not the first thing in the file: some other
                          heading of any level precedes it, or more than
                          `FIRST_SCREEN_LINES` lines of anything do. The
                          banner is a PRESENTATION rule, so the block's position is part of
                          the property, not a formatting preference: a contract that sits
                          below the output schemas is read after them.
  RESTATED-CONTRACT       a sentence outside the block uses the contract's own vocabulary
                          without pointing at the block, so it is a second copy of the
                          rules, free to drift from the one that is checked.

The population is every `*/agents/*.md` naming `CLAUDE_PLUGIN_ROOT` in ANY spelling —
`${...}` or bare — enumerated here rather than hardcoded, so a new agent joins the check by
existing. Keying it to the braced form alone would let an agent join the repo and miss the
sweep while this paragraph claimed otherwise. `EXPECTED_AGENTS` guards the other direction,
and it is a **named set rather than a floor**: any three agents satisfy a floor of three, so
removing one agent's block while adding a compliant agent keeps the count whole and the sweep
silent. Naming the members makes attrition and substitution both visible.

WHAT THIS STILL CANNOT SCREEN, disclosed
----------------------------------------
**Whether a dispatched agent follows the block.** Only its live output shows that, and no
static check ever reaches it. Saying so is the rule — claiming more would be the overreach
the banner itself exists to prevent.

**The out-of-block lane decides RESTATEMENT, not compliance, and it is incomplete in one
direction.** Both halves of that matter. It is decidable — "does this sentence contain one
of these fixed strings without also naming the contract" is a substring test, not a reading
of what the sentence means — so it never has to judge whether prose is compliant, which is
the judgment this file may not make. But a second copy of the rules written in entirely
different words carries none of the markers and is not caught. That gap is real and is the
accepted cost of not being noisy: a wider trigger flags about four unrelated sentences
for every genuine site (measured over one owner's agent files, undated), and a check
whose findings are mostly noise is one whose readers learn to skip it.

**AN INVERSION OF THE CANONICAL SOURCE ITSELF.** This is a required-literal check, so what
it decides is that every block MATCHES `contracts/reference-resolution.tmpl.md` — not that
the template says the right thing. An author who inverts the template and re-renders every
copy is green, and so is the suite, because every fixture is built from the template
too. That is inherent to the mechanism and not a bug in it: pinning a literal moves the
question from "what does this prose mean" to "is this the agreed text", and *what the agreed
text should say* is a review question by construction. It is visible in any diff that touches
`contracts/`, which is the compensating control, and it is written here so nobody concludes
from a green run that the contract was read.

**REVOCATION and REFRAMING are not caught at all, and they are a different thing from
paraphrase.** The lane asks whether a sentence restates the contract. It does not ask
whether some other sentence tells the agent to disregard the block ("the boxed rules below
are obsolete"), or wraps it in a frame that neutralises it ("kept only so you can recognise
and ignore it"). Those defeat the contract without restating one word of it, and no
substring test decides them — this is the residue that belongs to review, and it is written
down rather than left for the next reviewer to rediscover.

Read-only. Exit 0 when every in-scope agent carries the canonical block in the first
section, and no sentence outside it restates the contract's vocabulary without pointing at
the block. Exit 1 otherwise — including before any of that, when a member of
`EXPECTED_AGENTS` has left the population, which is the sweep failing rather than the tree
passing.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract_block import extract, first_difference, flat, pinned_population  # noqa: E402
import _layout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "scripts" / "contracts"

# An agent is in scope when it tells the model to read a plugin-rooted reference. Matched
# on the NAME, not on one spelling of it: `$CLAUDE_PLUGIN_ROOT` without braces reads the
# same variable, and keying the population to `${...}` would let an agent join the repo
# and miss the sweep entirely while the docstring claims it joins "by existing".
TRIGGER = "CLAUDE_PLUGIN_ROOT"

OPEN = "<!-- reference-resolution-contract -->"
CLOSE = "<!-- /reference-resolution-contract -->"

# A pinned SET, not a count. A floor of 3 is satisfied by any 3, so removing one agent's
# block and adding one compliant agent keeps the number whole and the sweep silent. Naming
# the members makes attrition and substitution both visible, and adding an agent is a
# deliberate one-line edit a reviewer sees.
# Members are checked for UNIQUENESS by the suite: a duplicated entry keeps the length
# whole while a real agent drops out, which is the floor failure one level in.
EXPECTED_AGENTS = (
    "core/agents/claim-verifier.md",
    "core/agents/code-reviewer.md",
    "core/agents/design-handoff-reproducer.md",
)

# --- the out-of-block lane -------------------------------------------------------------
# What a second resolution site actually does wrong is RESTATE the contract instead of
# pointing at it — an agent carrying its own copy of the fallback rules, free to drift
# from the block screens above it. Restatement is decidable as a
# substring test, so that is what this lane tests.
#
# The markers are the contract's distinctive vocabulary, chosen because they do not occur
# in ordinary agent prose. Two other triggers are the wrong mechanism: `if … unset`
# misses "is not set" and "is empty" entirely, and the whole negation family flags about
# four unrelated sentences (an "if a required field is missing" check, an "installs it if
# missing" step) for every real site (one owner's agent files, undated). A check that
# noisy teaches its readers to skip it, which is worse than the gap it closes. `fall back` is deliberately NOT a marker: an agent may fall back to
# a cached result after a rate-limit, which is nothing to do with reference resolution.
RESTATEMENT_MARKERS = ("dev checkout", "versioned plugin cache", "versioned cache",
                       "DEGRADED")
# Known and accepted: the escape is evaluated per FRAGMENT, and a punctuation-free run
# (a bullet list, say) is one fragment — so a delegating bullet launders a DEGRADED
# restatement three bullets down. Narrowing it would break an agent whose output-shape
# section legitimately needs both in one breath. Recorded rather than left for a reader to
# discover from the fixture's more confident wording.
#
# The escape, and the form the contract wants: a sentence may name the banner when it
# POINTS AT the block. Single-sourcing is the fix, so it must not be what trips the check.
#
# But the escape is NOT unconditional: a sentence reading "for scripts the
# reference-resolution contract is relaxed — prefer a dev checkout over the versioned plugin
# cache, and never emit a DEGRADED banner" carries the pointer and three inversions, and an
# unconditional escape passes it. A delegating sentence has no reason to restate the fallback
# ARMS — that is the part it is delegating — so naming them revokes the exemption. `DEGRADED`
# is exempt-able because an output-shape section legitimately needs to say where the banner
# goes.
DELEGATION = "reference-resolution contract"
UNLAUNDERABLE = ("dev checkout", "versioned plugin cache", "versioned cache")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def noun_slot():
    return r"(?P<noun>[A-Z]+)"


def depth_variants():
    """{name: sentence} from the canonical depth file, so the three live in one place."""
    out = {}
    for line in (CONTRACTS / "reference-resolution.depth.md").read_text(
            encoding="utf-8").splitlines():
        if ":" in line:
            name, _, text = line.partition(":")
            out[name.strip()] = text.strip()
    return out


def depth_kind(plugin_dir):
    """Which depth sentence is TRUE for this plugin, computed from disk.

    Hand-written, this sentence gets pattern-copied onto a plugin whose premise is false
    (told it keeps references "at more than one depth" when it has no root `references/`
    at all). Deriving it removes the whole class: the note cannot disagree
    with the tree, because the tree is where it comes from.
    """
    root_refs = (ROOT / plugin_dir / "references").is_dir()
    skill_refs = any((ROOT / plugin_dir / "skills").glob("*/references"))
    if root_refs and skill_refs:
        return "BOTH"
    if skill_refs:
        return "SKILLS_ONLY"
    return "ROOT_ONLY"


def expected_pattern(plugin, plugin_dir=None):
    """The canonical block for this plugin, as a regex with the noun as the only slot.

    `plugin_dir` is the directory the depth note is computed from; it defaults to
    `plugin`, which is the same thing in a tree laid out like a marketplace."""
    tmpl = (CONTRACTS / "reference-resolution.tmpl.md").read_text(encoding="utf-8")
    note = depth_variants()[depth_kind(plugin_dir or plugin)].replace("{PLUGIN}", plugin)
    body = tmpl.replace("{PLUGIN}", plugin)
    body = body.replace("{DEPTH_NOTE}", (" " + note) if note else "")
    parts = flat(body).split("{NOUN}")
    return re.compile(noun_slot().join(re.escape(p) for p in parts)), flat(body)


def agents():
    """Every shipped agent markdown, in sorted order — in core/ and every host's add/
    layer (host overrides are not swept), never in the generated plugins/ copy
    (`_layout.glob_components`)."""
    return sorted(Path(p) for p in _layout.glob_components(str(ROOT), "*/agents/*.md")
                  if Path(p).is_file())


# Any heading level, not just `##`: the property is "nothing else is read first",
# and five `### Output schema N` sections above the block would satisfy a `^## ` test
# while plainly violating what the codes table promises.
HEADING_RE = re.compile(r"^#{2,6} ", re.M)
# And a heading is not the only thing that can precede it: 120 lines of unheaded
# prose read first too. The block sits within the opening screens or it is not a
# first-screen promise.
FIRST_SCREEN_LINES = 40


def block_is_first_section(raw):
    """The contract's heading is the first `##` in the file.

    Content is pinned by the required literal; this pins position, which the literal cannot
    see. The banner exists so a degraded run cannot be mistaken for a full one by someone
    reading the first screen — so where the block sits IS part of what is being promised,
    and a check that verified the words while ignoring the placement would be measuring the
    easier half of its own subject.
    """
    before = raw[:raw.index(OPEN)]
    if before.count("\n") + 1 > FIRST_SCREEN_LINES:
        return False
    m = HEADING_RE.search(raw)
    return m is None or raw.index(OPEN) < m.start()


def out_of_block_sites(raw):
    """(line_no, marker) for each sentence outside the block that restates the contract."""
    out = []
    body, err = extract(raw, OPEN, CLOSE)
    if err is not None:
        return out
    segments = [(0, raw[:raw.index(OPEN)]),
                (raw.index(CLOSE) + len(CLOSE), raw[raw.index(CLOSE) + len(CLOSE):])]
    # Scanned SEPARATELY, and each carries its own offset into `raw`. Concatenating them
    # would put text from before the block next to text from after it; and sharing one
    # offset would report every finding at the file's FIRST matching line, sending an
    # author to compliant text and making a real defect look like a failed fix.
    for base, seg in segments:
        pos = 0
        for sentence in SENTENCE_SPLIT.split(seg):
            start = seg.index(sentence, pos)
            pos = start + len(sentence)
            one = flat(sentence)
            launderable = not any(m in one for m in UNLAUNDERABLE)
            if DELEGATION in one and launderable:
                continue                 # points at the block: the form the contract wants
            for hit in [m for m in RESTATEMENT_MARKERS if m in one]:
                # Every marker in the fragment, not the first: a punctuation-free run can
                # carry three distinct restatements, and reporting one sends the author
                # through three fix-and-re-run cycles for one edit.
                #
                # The marker's OWN offset, not the fragment's. A run of lines with no
                # sentence-ending punctuation between them is one fragment, so reporting
                # its start would point a reader at the first filler line above the real
                # site — the same "wrong line" defect as a shared offset, one level in.
                # Matched whitespace-flexibly because the fragment is raw text while the
                # marker was found in the flattened copy.
                rx = re.compile(r"\s+".join(re.escape(w) for w in hit.split()))
                found = list(rx.finditer(sentence))
                for m in (found or [None]):
                    at = start + (m.start() if m else 0)
                    out.append((raw.count("\n", 0, base + at) + 1, hit))
    return out


def findings_for(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    if TRIGGER not in raw:
        return None                      # not in the population
    out = []
    body, err = extract(raw, OPEN, CLOSE)
    if err is not None:
        return [err]

    rel = path.relative_to(ROOT).as_posix()
    # The block names the PLUGIN (`planning`); its depth note is a fact about the
    # source root the agent sits in (`core`), so the two are looked up separately.
    plugin, plugin_dir = _layout.plugin_name(rel), _layout.source_root(rel)
    pattern, canonical = expected_pattern(plugin, plugin_dir)
    actual = flat(body)
    if not pattern.fullmatch(actual):
        out.append(("NON-CANONICAL-CONTRACT",
                    f"the block is not `contracts/reference-resolution.tmpl.md` rendered "
                    f"for `{plugin}` ({depth_kind(plugin_dir)}) — "
                    f"{first_difference(actual, canonical)}"))

    if not block_is_first_section(raw):
        out.append(("BLOCK-NOT-FIRST",
                    "the contract block does not precede the file's first `##` section; "
                    "the banner is a first-screen promise, so the block's position is part "
                    "of the property"))

    for line, marker in out_of_block_sites(raw):
        out.append(("RESTATED-CONTRACT",
                    f"line {line}: `{marker}` outside the contract block restates it and "
                    f"is free to drift from it; point at the block by naming the "
                    f"`{DELEGATION}` in the same sentence instead"))
    return out


def main():
    in_scope, problems = [], []
    for path in agents():
        found = findings_for(path)
        if found is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        in_scope.append(rel)
        for code, why in found:
            problems.append(f"  {rel}: {code} — {why}")

    attrition = pinned_population(EXPECTED_AGENTS, in_scope, "agent")
    if attrition:
        for why in attrition:
            print(f"FAIL: {why}", file=sys.stderr)
        return 1

    print(f"{len(in_scope)} agent(s) name a plugin-rooted reference; "
          f"{len(problems)} problem(s).")
    print("  (decides the block IS the canonical contract text, and that no sentence "
          "outside it carries the contract's vocabulary without naming it)")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
