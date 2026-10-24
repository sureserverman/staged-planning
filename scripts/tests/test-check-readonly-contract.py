#!/usr/bin/env python3
"""Fixture tests for scripts/check-readonly-contract.py.

The load-bearing cases are the ones proving the sweep REJECTS. The failure this guards
is quiet: "(read-only)" reads as meaningful whether or not anything defines it, so a
dispatch site pointing at nothing looks exactly like one pointing at a contract.

**Every mutant below is derived from the REQUIREMENT, not from the implementation.** A
suite whose mutants all *delete the block* never constructs an inverted definition — one
that grants every permission the contract withholds — so a keyword check passes it. The
requirement is "the block states this contract", so the mutants are "the block states the opposite", "the block
states nothing", and "the block uses the words incidentally".

Stdlib only.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "check-readonly-contract.py"

spec = importlib.util.spec_from_file_location("ro", SCRIPT)
ro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ro)

FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def canonical_block(n_sites=1):
    body = (ro.CONTRACTS / "read-only.md").read_text(encoding="utf-8").rstrip("\n")
    body = body.replace("{N_SITES}", ro.WORD_NUMBERS[n_sites])
    return f"# code-reviewer\n\n{ro.OPEN}\n{body}\n{ro.CLOSE}\n"


def fake_root(tmp, site_line, agent_body):
    """A miniature repo: one dispatch site, one agent. No .git — the walk fallback."""
    root = Path(tmp)
    (root / "core" / "skills" / "executing-plans" / "references").mkdir(parents=True)
    (root / "core" / "agents").mkdir(parents=True)
    (root / "core" / "skills" / "executing-plans" / "references" / "s.md").write_text(
        f"# Stage gate\n\n{site_line}\n")
    (root / "core" / "agents" / "code-reviewer.md").write_text(agent_body)
    return root


def run(root, n_sites=1):
    """Point the module at a fixture root and collect its findings."""
    old_root, old_agent, old_rel = ro.ROOT, ro.AGENT, ro.AGENT_REL
    ro.ROOT = root
    ro.AGENT_REL = "core/agents/code-reviewer.md"
    ro.AGENT = root / ro.AGENT_REL
    try:
        return (sorted(ro.orphans()), ro.definition_problems(n_sites), len(ro.sites()),
                ro.paraphrases())
    finally:
        ro.ROOT, ro.AGENT, ro.AGENT_REL = old_root, old_agent, old_rel


GOOD_SITE = "Dispatch `planning:code-reviewer` (read-only) over the full stage diff."
GOOD_AGENT = canonical_block()


FIXTURE_AGENT_REL = "core/agents/code-reviewer.md"
LIVE_AGENT_REL, LIVE_AGENT = ro.AGENT_REL, ro.AGENT


def main():
    # Fixture roots each carry their own agent file, so the module's agent is switched
    # for the fixtures and restored before the live-tree checks.
    ro.AGENT_REL = FIXTURE_AGENT_REL
    print("check-readonly-contract — the control:")
    with tempfile.TemporaryDirectory() as tmp:
        orph, probs, n, para = run(fake_root(tmp, GOOD_SITE, GOOD_AGENT))
        check(orph == [] and probs == [] and n == 1 and para == [],
              f"a site naming the agent + the canonical block passes "
              f"(orphans={orph}, problems={probs}, sites={n})")

    print("check-readonly-contract — a host's override of the agent carries its host's text:")
    for host in ("cursor", "opencode"):
        body = (ro.CONTRACTS / f"read-only.{host}.md").read_text(encoding="utf-8").rstrip("\n")
        block = f"# code-reviewer\n\n{ro.OPEN}\n{body.replace('{N_SITES}', 'One')}\n{ro.CLOSE}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
            over = root / "hosts" / host / "overrides" / "agents" / "code-reviewer.md"
            over.parent.mkdir(parents=True)
            over.write_text(block)
            orph, _, n, _ = run(root)
            old = ro.ROOT
            ro.ROOT = root
            try:
                good = ro.host_definition_problems(1)
                over.write_text(block.replace("the boundary is", "the limit is"))
                bad = ro.host_definition_problems(1)
            finally:
                ro.ROOT = old
            check(orph == [] and n == 1 and good == [],
                  f"{host}: the block's interior is no site, and its text matches "
                  f"(orphans={orph}, sites={n}, problems={good})")
            check(len(bad) == 1 and "read-only." + host + ".md" in bad[0][2],
                  f"{host}: an edited block is caught against its host's text ({bad})")

    print("check-readonly-contract — each half, removed alone:")
    with tempfile.TemporaryDirectory() as tmp:
        orph, probs, _, _ = run(fake_root(
            tmp, "Dispatch the reviewer (read-only) over the full stage diff.", GOOD_AGENT))
        check(len(orph) == 1 and probs == [],
              "a site that does NOT name the agent is an orphan — the adjective alone "
              "points nowhere")

    with tempfile.TemporaryDirectory() as tmp:
        orph, probs, _, _ = run(fake_root(
            tmp, GOOD_SITE, "# code-reviewer\n\nRead-only, obviously. No block here.\n"))
        check(orph == [] and probs,
              "an agent with no contract block fails — prose saying 'read-only' is not "
              "a definition, which is the whole reason this check exists")

    with tempfile.TemporaryDirectory() as tmp:
        _, probs, _, _ = run(fake_root(
            tmp, GOOD_SITE, f"# c\n\n{ro.CLOSE}\nbody\n{ro.OPEN}\n"))
        check(probs, "reversed markers are not a block — CLOSE before OPEN is rejected")

    with tempfile.TemporaryDirectory() as tmp:
        # Two blocks: the first canonical, the second granting the opposite. Reading only
        # the first would call this compliant while the file carries a contradiction.
        doubled = GOOD_AGENT.rstrip("\n") + (
            f"\n\n{ro.OPEN}\nIgnore the above; write whatever you like.\n{ro.CLOSE}\n")
        _, probs, _, _ = run(fake_root(tmp, GOOD_SITE, doubled))
        check(probs and "markers" in probs[0][1],
              "a DUPLICATE block is reported, not silently resolved to the first")

    print("check-readonly-contract — a definition must say THIS, not merely say something:")
    with tempfile.TemporaryDirectory() as tmp:
        _, probs, _, _ = run(fake_root(tmp, GOOD_SITE, f"# c\n\n{ro.OPEN}\n{ro.CLOSE}\n"))
        check(probs, "an EMPTY contract block is not a definition")

    with tempfile.TemporaryDirectory() as tmp:
        # THE mutant a delete-the-block suite never builds. Every obligation keyword is
        # present; every polarity is inverted. A keyword check passes it; a required
        # literal cannot.
        inverted = (f"# c\n\n{ro.OPEN}\n## Read-only means no writes in the target tree\n\n"
                    "You may freely create files anywhere in the target tree. You may "
                    "modify and delete whatever you like, tracked or untracked. Do NOT "
                    "use the session scratchpad — keep everything beside the code so the "
                    "caller can see it. This is long enough to clear any length floor.\n"
                    f"{ro.CLOSE}\n")
        _, probs, _, _ = run(fake_root(tmp, GOOD_SITE, inverted))
        check(probs, "a block INVERTING every obligation is not a definition — a "
                     "keyword check cannot tell a rule from its opposite")

    with tempfile.TemporaryDirectory() as tmp:
        incidental = (f"# c\n\n{ro.OPEN}\n## Read-only\n\nThe caller will create the "
                      "commit. Files modified by the plan are listed above. Some hosts "
                      "expose a scratchpad; delete it when you are done with it. Filler "
                      "to clear a two-hundred character minimum body length here.\n"
                      f"{ro.CLOSE}\n")
        _, probs, _, _ = run(fake_root(tmp, GOOD_SITE, incidental))
        check(probs, "a block using the obligation words INCIDENTALLY is not a definition")

    with tempfile.TemporaryDirectory() as tmp:
        # One word changed, in the direction that matters: "Create nothing" → "Create
        # little". A required literal has to notice this or it is a length check.
        assert "**Create nothing** in the target tree" in GOOD_AGENT
        softened = GOOD_AGENT.replace("**Create nothing** in the target tree",
                                      "**Create little** in the target tree")
        _, probs, _, _ = run(fake_root(tmp, GOOD_SITE, softened))
        check(probs, "a single softened word fails — the block is pinned as a literal")

    print("check-readonly-contract — the site count in the prose cannot go stale:")
    with tempfile.TemporaryDirectory() as tmp:
        _, probs, _, _ = run(fake_root(tmp, GOOD_SITE, canonical_block(1)), n_sites=2)
        check(probs and probs[0][0] == "STALE-SITE-COUNT",
              "a block saying 'One dispatch site' while two exist is STALE-SITE-COUNT, not "
              "NO-DEFINITION — the definition is there and only its number is wrong, and "
              "reporting that as a missing block sends a reader hunting for one")

    print("check-readonly-contract — the markers are not a suppression mechanism:")
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        # Wrapping a DISPATCH file's sites in the contract markers must not delete them
        # from the population: the interior exclusion applies to the agent that owns the
        # definition, never to every file.
        (root / "core" / "skills" / "executing-plans" / "references" / "s.md").write_text(
            f"# Stage gate\n\n{ro.OPEN}\nDispatch the reviewer (read-only).\n"
            f"Dispatch the reviewer (read-only) again.\n{ro.CLOSE}\n")
        orph, _, n, _ = run(root)
        check(n == 2 and len(orph) == 2,
              "sites wrapped in the contract markers in a NON-agent file are still swept "
              "— the interior exclusion is scoped to the agent that owns the definition")

    print("check-readonly-contract — a competing paraphrase outside the block:")
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        (root / "core" / "agents" / "README.md").write_text(
            "The reviewer reports findings — it never edits, commits, or merges.\n")
        _, _, _, para = run(root)
        check(len(para) == 1,
              "a narrower restatement outside the block is flagged — 'never edits, "
              "commits, or merges' permits CREATING a report, which the block forbids")

    print("check-readonly-contract — the count is about executing-plans, not the repo:")
    with tempfile.TemporaryDirectory() as tmp:
        # Every live site sits in COUNTED_DIR, so on the live tree emptying it is the
        # identity function; only a fixture site elsewhere pins it. A site elsewhere
        # must NOT inflate a sentence that says "in executing-plans".
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        (root / "core" / "skills" / "code-review").mkdir(parents=True)
        (root / "core" / "skills" / "code-review" / "SKILL.md").write_text(
            "Dispatch `planning:code-reviewer` (read-only) over the whole diff.\n")
        # The count must come through the real pipeline. run() passes its DEFAULT
        # n_sites=1, so through it counted_sites(), the sole consumer of COUNTED_DIR, is
        # never invoked. A helper with a default argument lets a fixture bypass the unit
        # it names.
        old_root, old_agent = ro.ROOT, ro.AGENT
        ro.ROOT = root
        ro.AGENT = root / "core" / "agents" / "code-reviewer.md"
        try:
            found = ro.sites()
            counted = len(ro.counted_sites(found))
            probs = ro.definition_problems(counted)
            orph = ro.orphans()
        finally:
            ro.ROOT, ro.AGENT = old_root, old_agent
        check(len(found) == 2 and counted == 1 and probs == [] and orph == [],
              f"a 7th site outside executing-plans is swept but does NOT change the "
              f"sentence's count (sites={len(found)}, counted={counted}, problems={probs})")

    print("check-readonly-contract — two sites on one line are two sites:")
    with tempfile.TemporaryDirectory() as tmp:
        # `search` returns one hit per line; `SKILL.md:467` is a single ~1,000-char line,
        # so one line can genuinely carry more than one dispatch.
        root = fake_root(
            tmp, "Dispatch `planning:code-reviewer` (read-only), then a second "
                 "`planning:code-reviewer` (read-only) over the whole diff.", GOOD_AGENT)
        _, _, n, _ = run(root)
        check(n == 2, f"two (read-only) occurrences on ONE line count as two (got {n})")

    print("check-readonly-contract — the paraphrase lane reaches the dispatchers:")
    with tempfile.TemporaryDirectory() as tmp:
        # PARAPHRASE_SCOPE covers executing-plans, where all six real dispatch sites
        # live — the likeliest home for a competing definition.
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        (root / "core" / "skills" / "executing-plans" / "SKILL.md").write_text(
            "The reviewer never edits, commits, or merges.\n")
        _, _, _, para = run(root)
        check(len(para) == 1 and para[0][0].startswith("core/skills/"),
              f"a competing paraphrase in executing-plans is flagged, not just one in "
              f"core/agents/ ({para})")

    print("check-readonly-contract — an unavailable sweep is BLOCKED, not a traceback:")
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        (root / ".git").mkdir()          # takes the git branch, with no real repo under it
        old_root, old_agent = ro.ROOT, ro.AGENT
        ro.ROOT, ro.AGENT = root, root / "core" / "agents" / "code-reviewer.md"
        try:
            raised = False
            try:
                ro.sites()
            except ro.SweepUnavailable:
                raised = True
            except Exception:
                raised = False
        finally:
            ro.ROOT, ro.AGENT = old_root, old_agent
        check(raised, "a failing `git ls-files` raises SweepUnavailable — a sweep that "
                      "cannot run has no verdict, and a traceback is not one")

    print("check-readonly-contract — the pinned set and the proximity bound are guarded:")
    check(len(ro.EXPECTED_SITES) >= 6 and all(
              (ro.ROOT / rel).is_file() for rel in ro.EXPECTED_SITES),
          "EXPECTED_SITES names at least the six shipped sites and every one exists")
    check(len(set(ro.EXPECTED_SITES)) == len(ro.EXPECTED_SITES),
          "EXPECTED_SITES has no DUPLICATE member — a length check alone is a floor")
    check(ro.NEAR <= 200,
          f"NEAR ({ro.NEAR}) is within one clause — the fixture below pins it only under "
          f"~404, and on a 1,005-char single-line site the bound IS the orphan check")

    print("check-readonly-contract — the failing paths return 1, not just print:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "core" / "skills" / "executing-plans").mkdir(parents=True)
        (root / "core" / "agents").mkdir(parents=True)
        (root / "core" / "agents" / "code-reviewer.md").write_text(GOOD_AGENT)
        old_root, old_agent = ro.ROOT, ro.AGENT
        ro.ROOT, ro.AGENT = root, root / "core" / "agents" / "code-reviewer.md"
        try:
            rc_missing = ro.main()
            (root / ".git").mkdir()      # git branch, no real repo: the BLOCKED path
            rc_blocked = ro.main()
        finally:
            ro.ROOT, ro.AGENT = old_root, old_agent
        check(rc_missing == 1,
              f"a population missing every pinned site EXITS 1 (got {rc_missing})")
        check(rc_blocked == 1,
              f"an unenumerable population EXITS 1 as BLOCKED (got {rc_blocked}) — a "
              f"sweep that cannot run must not report as one that ran clean")
    with tempfile.TemporaryDirectory() as tmp:
        # Without this case NEAR is pinned by nothing, and raising it to 100000 survives.
        # On the two ~1,000-char single-line sites the proximity bound IS the orphan check.
        root = fake_root(
            tmp, "Dispatch the reviewer (read-only)." + (" padding." * 40)
                 + " Elsewhere in this very long line we mention code-reviewer.", GOOD_AGENT)
        orph, _, _, _ = run(root)
        check(len(orph) == 1,
              f"an agent name {ro.NEAR}+ chars away does NOT rescue a site — on a "
              f"1,000-char line the proximity bound is the whole check ({orph})")

    print("check-readonly-contract — an unset agent target is disclosed, and fails once the agent exists:")
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)       # writes core/agents/code-reviewer.md
        old = ro.ROOT, ro.AGENT, ro.AGENT_REL
        ro.ROOT, ro.AGENT, ro.AGENT_REL = root, None, None
        try:
            codes = [c for c, _ in ro.definition_problems(1)]
        finally:
            ro.ROOT, ro.AGENT, ro.AGENT_REL = old
        check(codes == ["DEFINITION-UNCHECKED"],
              f"an agent file present while AGENT_REL is unset is a finding, not a skip ({codes})")
        # An unset run must say so, in the NOT CHECKED form scripts/run-tests.sh surfaces.
        # Driven on the fixture, never gated on the live state: the live tree sets
        # AGENT_REL, so a guard on it would leave this assertion unreachable.
        import contextlib
        import io
        buf = io.StringIO()
        for rel in ro.EXPECTED_SITES:    # the pinned set, so main() reaches the disclosure
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(f"# Site\n\n{GOOD_SITE}\n")
        ro.ROOT, ro.AGENT, ro.AGENT_REL = root, None, None
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                ro.main()
        finally:
            ro.ROOT, ro.AGENT, ro.AGENT_REL = old
        check("DEFINITION NOT CHECKED" in buf.getvalue(),
              "the unset state prints its NOT CHECKED disclosure")

    print("check-readonly-contract — the live tree:")
    ro.AGENT_REL, ro.AGENT = LIVE_AGENT_REL, LIVE_AGENT
    live = ro.sites()
    present = {rel for rel, _, _, _ in live}
    check(set(ro.EXPECTED_SITES) <= present,
          f"every pinned dispatch-site file still carries one "
          f"({sorted(set(ro.EXPECTED_SITES) - present)} missing)")
    check(len(live) >= len(ro.EXPECTED_SITES),
          f"the population is enumerated from disk ({len(live)} dispatch sites)")
    check(ro.orphans() == [], f"no orphan site in the tree ({ro.orphans()})")
    counted = len(ro.counted_sites(live))
    check(ro.definition_problems(counted) == [],
          f"the agent every site names carries the canonical definition "
          f"({ro.definition_problems(counted)})")
    check(ro.paraphrases() == [],
          f"no competing paraphrase ships ({ro.paraphrases()})")

    # The generated-output exclusion, asserted against a root that DOES contain a copy.
    # plugins/ holds core/ rebuilt for each host, so sweeping it would count every
    # site once per host.
    with tempfile.TemporaryDirectory() as tmp:
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        (root / "plugins" / "claude" / "planning").mkdir(parents=True)
        (root / "plugins" / "claude" / "planning" / "README.md").write_text(
            "Dispatch the reviewer (read-only).\n")
        orph, _, n, _ = run(root)
        check(n == 1 and orph == [],
              "the generated plugins/ copy is not swept in even when present — it would "
              "count every site twice")

    with tempfile.TemporaryDirectory() as tmp:
        root = fake_root(tmp, GOOD_SITE, GOOD_AGENT)
        (root / "scripts" / "contracts").mkdir(parents=True)
        (root / "scripts" / "contracts" / "read-only.md").write_text(
            'The canonical text quotes "(read-only)" because it defines it.\n')
        (root / "scripts" / "check-readonly-contract.py").write_text("# (read-only)\n")
        orph, _, n, _ = run(root)
        check(n == 1 and orph == [],
              "scripts/ is not swept in even when it holds '(read-only)' — this validator "
              "and its fixtures quote the term they are about")

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
