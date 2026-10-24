#!/usr/bin/env python3
"""Every "(read-only)" dispatch site points at one definition, and that definition is real.

Every site in `executing-plans` that dispatches `planning:code-reviewer (read-only)`
points at one definition, and that definition is real. (The count is deliberately not
written here: it is computed below and rendered into the contract via `{N_SITES}`, and
hardcoding it in this header would introduce, in the mechanism, the staleness the
mechanism exists to prevent.) Without one
definition the word means whatever each reader assumes — and the readings differ in the
way that matters: "does not edit the files under review" and
"creates nothing in the tree under review" are not the same rule, and only the second one
keeps a reviewer's scratch file out of the caller's `git status` mid-gate.

This binds the two halves that a convention leaves unbound:

  ORPHAN-READONLY   a site says "(read-only)" without naming the agent whose block defines
                    it, so the pointer resolves to nothing.
  NO-DEFINITION     the agent carries no canonical definition for the pointer to reach.
  RESTATED-CONTRACT a narrower paraphrase of the contract lives outside the block, free to
                    drift from it: "never edits, commits, or merges" (which permits
                    *creating* a report, the one thing the definition singles out), or
                    "no write tools by design" in an agent whose own frontmatter grants
                    an unrestricted `Bash`.

WHAT THIS DECIDES, AND WHY IT IS DECIDABLE
------------------------------------------
**The block must be the canonical text**, held in `contracts/read-only.md`, with one
substitution point — `{N_SITES}`, rendered from the count this script computes, so the
sentence "Six dispatch sites …" cannot go stale while the validator that knows better
prints the true number and says nothing.

Checking that the block exists and names three obligation keywords is a meaning test
wearing a keyword's clothes, and it fails the way meaning tests fail: a block saying *"You
may freely create files anywhere in the target tree… You may modify and delete whatever you
like… Do NOT use the session scratchpad"* contains `create`, `modify`, `scratchpad`, is over
the length floor, and passes — the definition inverted, the check green. `honest-gates`
§ *A test does not exist until its mutant dies* allows exactly two ways out; the required
literal is the structural one, and it is available because this block is one canonical
text rather than one authored per site.

**The population is swept from the whole repo**, not from a hardcoded directory list. A
directory list misses a dispatch site added in a directory it does not name — a file that
really does dispatch this agent — while the printed count stays unchanged.
`EXPECTED_SITES` guards the opposite direction: a population that shrinks is a sweep
that stopped looking.

**Scope, and what is deliberately outside it.** `scripts/` is excluded because this file
and its tests quote the term they are about, and `plugins/` and `packages/` because they are
generated copies that would count every site twice. Sweeping in text that uses the same two
words for an unrelated property would produce findings nobody can act on, which is how a
check teaches its readers to skip it. Each exclusion is named here rather than left as a
silent glob boundary, and the suite asserts each against a fixture root that actually
contains the collision: a paragraph claiming a fixture for an exclusion that has none is the
same overclaim this file exists to catch, made about itself.

WHAT THIS CANNOT SCREEN, disclosed
----------------------------------
**Whether a dispatched agent obeys the block.** Only its live output shows that.

**Whether an occurrence is a dispatch or a mention.** The pointer test is "the agent's name
within one clause", which a sentence merely *discussing* the agent also satisfies. The
consequence is bounded and in the safe direction: a mention gets held to the same pointer
rule a dispatch is, which costs a few words and misleads nobody.

**A paraphrase written in words this file does not list.** `RESTATED_PARAPHRASES` is a
literal set — decidable, and incomplete by construction. It catches the listed literals
and the shapes they belong to, not every sentence someone could write.

**An inversion of `contracts/read-only.md` itself.** The block is pinned to that file, so
this decides they MATCH — not that the canonical text is right. Editing the source and the
copy together is green, and the suite is too, since its fixtures render from the same source.
Inherent to a required literal: it moves the question from "what does this prose mean" to "is
this the agreed text", and whether the agreed text is correct stays a review question. The
compensating control is that it is visible in any diff touching `contracts/`.

**A paraphrase outside `PARAPHRASE_SCOPE`.** That lane reads `core/agents/` and
`core/skills/executing-plans/` — the agent and the dispatchers. A competing definition
written in a third plugin is not seen. Named because a scope left unstated reads as "no
paraphrase ships" rather than "none ships here".

**An untracked dispatch site.** The population is `git ls-files`, so a new site in a file
nobody has staged yet is invisible until it is added. The sibling validator walks the tree
instead, so the two disagree about untracked files by design: this one describes what
ships, and a `(read-only)` claim only binds once it is in the tree.

Read-only. Exit 0 when every site points, the definition is canonical, and no paraphrase
competes with it. Exit 1 otherwise — and also, before any problem is computed, when a member
of `EXPECTED_SITES` has stopped carrying one, or when the population cannot be enumerated at
all (BLOCKED: a sweep that cannot run has no verdict to give).
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract_block import (extract, first_difference, flat,  # noqa: E402
                             pinned_population, span)

class SweepUnavailable(RuntimeError):
    """The population could not be enumerated — a BLOCKED sweep, not a clean tree."""


ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "scripts" / "contracts"

# The bundled reviewer: the one definition every dispatch site points at. Set to None
# only while no reviewer ships; the sites are still swept then, each naming the agent.
AGENT_REL = "core/agents/code-reviewer.md"
AGENT = ROOT / AGENT_REL if AGENT_REL else None
# The reviewer's path, kept so that unsetting AGENT_REL while the file exists fails: the
# definition check would be off over a definition that is RIGHT THERE — a fail, not a note.
PENDING_AGENT_REL = "core/agents/code-reviewer.md"

READONLY_RE = re.compile(r"\(read-only\)", re.I)
OPEN, CLOSE = "<!-- read-only-contract -->", "<!-- /read-only-contract -->"
# A host's whole-file version of the reviewer. Its block states that host's facts (what the
# host enforces differs), so it is pinned to `contracts/read-only.<host>.md` when one exists,
# else to the shared text; its interior is the definition, not a site.
HOST_AGENT_RE = re.compile(r"^hosts/([^/]+)/overrides/agents/code-reviewer\.md$")

# Documented above. Kept as path prefixes so the exclusion is checkable by reading it.
# plugins/ and packages/ are generated copies of core/ + hosts/ — sweeping them would
# count every site twice (`_layout.GENERATED`).
EXCLUDED_PREFIXES = ("scripts/", "plugins/", "packages/")

ANCHOR = "code-reviewer"
NEAR = 120

# {N_SITES} renders a sentence that says "dispatch sites in `executing-plans`", so it is
# counted over THAT directory alone. The orphan sweep stays repo-wide: those are different
# questions, and conflating them would make a site added elsewhere either inflate a
# sentence about executing-plans or force an author to write a false number to go green.
COUNTED_DIR = "core/skills/executing-plans/"

# A pinned SET, not a floor: any six satisfies a floor of six, so a site deleted here and
# one added there keeps the number whole and the sweep silent.
EXPECTED_SITES = (
    "core/skills/executing-plans/SKILL.md",
    "core/skills/executing-plans/references/close-out.md",
    "core/skills/executing-plans/references/integration.md",
    "core/skills/executing-plans/references/light-plans.md",
    "core/skills/executing-plans/references/stage-gate.md",
    "core/skills/executing-plans/references/task-execution.md",
)

# Narrower restatements of the contract. Each is a known paraphrase literal, or the
# shape of one. Matched outside the canonical block only — the block is allowed to
# define the thing it defines.
RESTATED_PARAPHRASES = (
    "never edits, commits, or merges",
    "no write tools",
    "no Edit/Write tools",
)
PARAPHRASE_SCOPE = ("core/agents/", "core/skills/executing-plans/")

WORD_NUMBERS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
                7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven",
                12: "Twelve"}


def markdown_files():
    """Every shipped markdown file, as (path, repo-relative posix path).

    TRACKED files only, when the root is a git repo. A local, gitignored artifact is not
    part of the shipped contract: an untracked local report that says "(read-only)"
    about something else entirely — a finding nobody can act on, in a file that is not in
    the tree this validator describes. Falls back to a plain walk when there is no git
    directory, which is how the fixture roots in the test suite are read.
    """
    if (ROOT / ".git").exists():
        try:
            out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "*.md"],
                                 capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            # A traceback is not a verdict. The sweep cannot run, so say that and let the
            # caller fail loudly rather than crashing mid-enumeration.
            raise SweepUnavailable(f"`git ls-files` failed: {exc}") from exc
        rels = sorted(r for r in out.stdout.split("\0") if r)
        paths = ((ROOT / r, r) for r in rels)
    else:
        paths = ((p, p.relative_to(ROOT).as_posix()) for p in sorted(ROOT.rglob("*.md")))
    for p, rel in paths:
        if rel.startswith(EXCLUDED_PREFIXES) or "/.git/" in rel:
            continue
        if p.is_file():
            yield p, rel


def sites():
    """(rel, line_no, line) for every (read-only) occurrence in the swept population.

    The canonical block's interior is excluded **for the agent file only**. The definition
    quotes the term it defines, and without the exclusion the definition would be a
    finding against itself. Scoping it to the agent matters: applied to every file, the
    marker pair would become a suppression mechanism — wrapping real dispatch sites in
    `<!-- read-only-contract -->` would delete them from the population silently.
    """
    out = []
    for p, rel in markdown_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        skip = set()
        if rel == AGENT_REL or HOST_AGENT_RE.match(rel):
            got = span(text, OPEN, CLOSE)
            if got:
                skip = set(range(got[0], got[1] + 1))
        for n, line in enumerate(text.splitlines(), 1):
            if n in skip:
                continue
            # Every occurrence, not the first: two dispatch sites on one line would be
            # two sites. The population has ~1,000-char single lines, where a second
            # dispatch on one line is entirely plausible.
            for m in READONLY_RE.finditer(line):
                out.append((rel, n, line, m.start()))
    return out


def orphans():
    bad = []
    for rel, n, line, at in sites():
        lo, hi = max(0, at - NEAR), min(len(line), at + len("(read-only)") + NEAR)
        if not re.search(r"\b" + re.escape(ANCHOR) + r"\b", line[lo:hi]):
            bad.append((rel, n))
    return bad


def definition_problems(n_sites):
    """[] if the agent carries the canonical definition, else (code, why) for each reason.

    NO-DEFINITION and STALE-SITE-COUNT are separated because they call for opposite
    actions: one says the pointer resolves to nothing, the other says it resolves to a
    correct definition whose opening sentence names the wrong number. Reporting the second
    as the first would send a reader looking for a missing block that is there all along.
    """
    if AGENT is None:
        if (ROOT / PENDING_AGENT_REL).exists():
            return [("DEFINITION-UNCHECKED", f"{PENDING_AGENT_REL} exists but AGENT_REL is "
                                             "unset, so its contract block is never compared "
                                             "— set AGENT_REL to it")]
        return []
    if not AGENT.exists():
        return [("NO-DEFINITION", "the agent file does not exist; every site points here "
                                  "and would resolve to nothing")]
    text = AGENT.read_text(encoding="utf-8", errors="replace")
    body, err = extract(text, OPEN, CLOSE)
    if err is not None:
        return [("NO-DEFINITION", f"{err[1]}; every site points here and would resolve to "
                                  f"nothing")]
    expected = CONTRACTS / "read-only.md"
    want = flat(expected.read_text(encoding="utf-8").replace(
        "{N_SITES}", WORD_NUMBERS.get(n_sites, str(n_sites))))
    got = flat(body)
    if got == want:
        return []
    a, b = got.split(" "), want.split(" ")
    only_count = (len(a) == len(b)
                  and sum(1 for x, y in zip(a, b) if x != y) == 1
                  and any(x in WORD_NUMBERS.values() for x, y in zip(a, b) if x != y))
    code = "STALE-SITE-COUNT" if only_count else "NO-DEFINITION"
    tail = "" if only_count else "; every site points here and would resolve to nothing"
    return [(code, f"the block is not `contracts/read-only.md` rendered for {n_sites} "
                   f"executing-plans site(s) — {first_difference(got, want)}{tail}")]


def host_definition_problems(n_sites):
    """(rel, code, why) for each host override of the reviewer whose block is not its
    host's canonical text rendered for n_sites."""
    out = []
    for p in sorted(ROOT.glob("hosts/*/overrides/agents/code-reviewer.md")):
        rel = p.relative_to(ROOT).as_posix()
        host = HOST_AGENT_RE.match(rel).group(1)
        name = f"read-only.{host}.md" if (CONTRACTS / f"read-only.{host}.md").exists() \
            else "read-only.md"
        body, err = extract(p.read_text(encoding="utf-8", errors="replace"), OPEN, CLOSE)
        if err is not None:
            out.append((rel, "NO-DEFINITION", err[1]))
            continue
        want = flat((CONTRACTS / name).read_text(encoding="utf-8").replace(
            "{N_SITES}", WORD_NUMBERS.get(n_sites, str(n_sites))))
        got = flat(body)
        if got != want:
            out.append((rel, "NO-DEFINITION", f"the block is not `contracts/{name}` rendered "
                        f"for {n_sites} executing-plans site(s) — {first_difference(got, want)}"))
    return out


def paraphrases():
    out = []
    for p, rel in markdown_files():
        if not rel.startswith(PARAPHRASE_SCOPE):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        skip = set()
        if rel == AGENT_REL:
            got = span(text, OPEN, CLOSE)
            if got:
                skip = set(range(got[0], got[1] + 1))
        for n, line in enumerate(text.splitlines(), 1):
            if n in skip:
                continue
            for phrase in RESTATED_PARAPHRASES:
                if phrase in line:
                    out.append((rel, n, phrase))
    return out


def counted_sites(found):
    """The sites the canonical sentence is ABOUT — executing-plans only (see COUNTED_DIR)."""
    return [s for s in found if s[0].startswith(COUNTED_DIR)]


def main():
    try:
        found = sites()
    except SweepUnavailable as exc:
        print(f"BLOCKED: {exc} — the population could not be enumerated, so this "
              f"validator has no verdict to give.", file=sys.stderr)
        return 1
    problems = []

    present = {rel for rel, _, _, _ in found}
    attrition = pinned_population(EXPECTED_SITES, present, "(read-only) site")
    if attrition:
        for why in attrition:
            print(f"FAIL: {why}", file=sys.stderr)
        return 1

    problems += [f"  {rel}:{n}: ORPHAN-READONLY — '(read-only)' with no `{ANCHOR}` within "
                 f"{NEAR} chars on the same line; the agent name is the pointer to the "
                 f"definition" for rel, n in orphans()]
    problems += [f"  {AGENT_REL or PENDING_AGENT_REL}: {code} — {why}"
                 for code, why in definition_problems(len(counted_sites(found)))]
    problems += [f"  {rel}: {code} — {why}"
                 for rel, code, why in host_definition_problems(len(counted_sites(found)))]
    problems += [f"  {rel}:{n}: RESTATED-CONTRACT — \"{phrase}\" is a narrower second "
                 f"definition, free to drift from the canonical block; point at the block "
                 f"instead" for rel, n, phrase in paraphrases()]

    print(f"{len(found)} (read-only) site(s), {len(counted_sites(found))} of them in "
          f"executing-plans; {len(problems)} problem(s).")
    print("  (decides the block IS `contracts/read-only.md` — not that a dispatched agent "
          "obeyed it; scripts/ and the generated plugins/ and packages/ are excluded)")
    if AGENT is None:
        print("  DEFINITION NOT CHECKED: AGENT_REL is unset, so the reviewer's block is not "
              "compared")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
