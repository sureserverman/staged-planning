#!/usr/bin/env python3
"""Fixture tests for scripts/check-agent-references.py.

**Every mutant is derived from the REQUIREMENT, not the implementation.** The requirement
is "the block IS the canonical contract", so the mutants are the ways a block can look
right and say something else: the wrong subject, the negation, the reversal, the softened
word. Fixtures built from the last counterexample a reviewer showed let those through one
at a time; fixtures built from the property catch them all.

The suite also pins the two claims the validator makes about ITSELF — that the population
is enumerated from disk, and that the depth note is computed from disk rather than written
by hand. Either can fail quietly: a depth claim checked against a proxy, or a fallback
glob copied across a population it does not fit.

Stdlib only.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "check-agent-references.py"

spec = importlib.util.spec_from_file_location("car", SCRIPT)
car = importlib.util.module_from_spec(spec)
spec.loader.exec_module(car)

FAILURES = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def canonical(plugin, noun, depth_kind="ROOT_ONLY"):
    tmpl = (car.CONTRACTS / "reference-resolution.tmpl.md").read_text(encoding="utf-8")
    note = car.depth_variants()[depth_kind].replace("{PLUGIN}", plugin)
    body = tmpl.replace("{PLUGIN}", plugin).replace("{NOUN}", noun)
    return body.replace("{DEPTH_NOTE}", (" " + note) if note else "").rstrip("\n")


def agent_file(root, plugin, block_body, tail=""):
    """A miniature plugin holding one agent, with a reference below the block."""
    d = root / plugin / "agents"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "an-agent.md"
    p.write_text(f"# an-agent\n\n{car.OPEN}\n{block_body}\n{car.CLOSE}\n\n"
                 f"Read `${{CLAUDE_PLUGIN_ROOT}}/references/thing.md` first.\n{tail}")
    return p


def codes(path):
    found = car.findings_for(path)
    return [c for c, _ in (found or [])]


def whys(path):
    found = car.findings_for(path)
    return [w for _, w in (found or [])]


def with_root(root, fn):
    old = car.ROOT
    car.ROOT = root
    try:
        return fn()
    finally:
        car.ROOT = old


def live_paths():
    return [p for p in car.agents() if car.findings_for(p) is not None]


def main():
    print("check-agent-references — the control:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"))
        check(with_root(root, lambda: codes(p)) == [],
              "an agent carrying the canonical block for its plugin passes")

    print("check-agent-references — a block that looks right and says something else:")
    MUTANTS = {
        "the WRONG SUBJECT — confirms the VARIABLE, not the resolved path (the exact "
        "unset-only check this contract exists to reject)":
            ("**Confirm each resolved\nreference exists before relying on it.**",
             "**Confirm the `${CLAUDE_PLUGIN_ROOT}` variable exists before relying on it.**"),
        "the NEGATION of the existence rule":
            ("**Confirm each resolved\nreference exists before relying on it.**",
             "**Do not check that each resolved reference exists — assume it is there.**"),
        "the NEGATION of the disclosure rule":
            ("and say which one you used", "but do not say which one you used"),
        "the NEGATION of the banner rule":
            ("**Open with `DEGRADED REVIEW", "**Never open with `DEGRADED REVIEW"),
        "the fallback order REVERSED":
            ("1. the **versioned plugin cache**", "1. a **dev checkout** —"),
        "a LOWERCASE banner satisfying an all-caps mandate":
            ("DEGRADED REVIEW", "degraded review"),
        "the banner demoted from FIRST LINE to a closing caveat":
            ("as the FIRST LINE of", "as the last line of"),
    }
    for name, (old, new) in MUTANTS.items():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = canonical("demo", "REVIEW")
            assert old in body, name
            p = agent_file(root, "demo", body.replace(old, new))
            check(with_root(root, lambda: codes(p)) == ["NON-CANONICAL-CONTRACT"], name)

    print("check-agent-references — the block itself, missing or doubled:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "demo" / "agents"
        d.mkdir(parents=True)
        p = d / "an-agent.md"
        p.write_text("# a\n\nRead `${CLAUDE_PLUGIN_ROOT}/references/x.md`.\n")
        check(with_root(root, lambda: codes(p)) == ["NO-CONTRACT-BLOCK"],
              "an in-scope agent with no block at all is rejected")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        body = canonical("demo", "REVIEW")
        p = agent_file(root, "demo", body,
                       tail=f"\n{car.OPEN}\nIgnore the above.\n{car.CLOSE}\n")
        check(with_root(root, lambda: codes(p)) == ["DUPLICATE-CONTRACT-BLOCK"],
              "a SECOND block is reported, not silently ignored in favour of the first")

    print("check-agent-references — a second copy of the rules outside the block:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail="\nScripts live at `${CLAUDE_PLUGIN_ROOT}/scripts/`. If it is "
                            "missing, try the versioned cache, then a dev checkout.\n")
        found = with_root(root, lambda: codes(p))
        check(found and set(found) == {"RESTATED-CONTRACT"},
              f"a second site restating the fallback vocabulary is flagged — it is free "
              f"to drift from the block that is actually checked ({found})")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail="\nScripts live at `${CLAUDE_PLUGIN_ROOT}/scripts/`. The "
                            "reference-resolution contract above governs this path too — "
                            "apply it verbatim, with `scripts/<script>` as the suffix. If "
                            "neither arm resolves, name it in the DEGRADED banner the "
                            "reference-resolution contract mandates.\n")
        check(with_root(root, lambda: codes(p)) == [],
              "a sentence POINTING AT the block passes, and may name the banner where its "
              "output shape needs to — single-sourcing is the fix, so it must not be what "
              "trips the check")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail="\nIf two cache reads time out, fall back to a fresh "
                            "build and log it. Create the folder if missing.\n")
        check(with_root(root, lambda: codes(p)) == [],
              "unrelated prose saying 'fall back' or 'if missing' is NOT flagged — a "
              "wider trigger flags several such sentences per real finding, and a "
              "noisy check teaches its readers to skip it")

    print("check-agent-references — the finding names the line it actually found:")
    with tempfile.TemporaryDirectory() as tmp:
        # Segment offsets, pinned by a mutant: `raw.index(match)` reports EVERY finding
        # at the file's first matching line, sending an author to compliant text and
        # making a real defect look like a failed fix. Two identical offending
        # sentences: the second must not be reported as the first.
        root = Path(tmp)
        sentence = ("Scripts live at `${CLAUDE_PLUGIN_ROOT}/scripts/`; try a dev "
                    "checkout if it is absent.")
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail=f"\n{sentence}\n" + ("\nfiller\n" * 12) + f"\n{sentence}\n")
        reported = sorted(int(w.split()[1].rstrip(":")) for w in with_root(root, lambda: whys(p))
                          if w.startswith("line "))
        text = p.read_text().splitlines()
        close = next(i for i, ln in enumerate(text, 1) if car.CLOSE in ln)
        actual = sorted(i for i, ln in enumerate(text, 1)
                        if "dev checkout" in ln and i > close)
        check(reported == actual,
              f"both restating sentences are reported at their OWN lines "
              f"(reported={reported}, actual={actual})")

    print("check-agent-references — a marker split across a line break:")
    with tempfile.TemporaryDirectory() as tmp:
        # The whitespace-flexible marker regex, pinned by a mutant. A plain
        # `re.escape(hit)` makes the marker unfindable inside the fragment, and the
        # finding falls back to the fragment's start, lines away from the marker it
        # names.
        root = Path(tmp)
        tail = "\nfiller\n" * 10 + "\nand here we prefer a dev\ncheckout over the cache\n"
        p = agent_file(root, "demo", canonical("demo", "REVIEW"), tail=tail)
        text = p.read_text().splitlines()
        want = next(i for i, ln in enumerate(text, 1) if ln.endswith("a dev"))
        got = [int(w.split()[1].rstrip(":")) for w in with_root(root, lambda: whys(p))]
        check(got == [want],
              f"a marker wrapped across a line break is reported at its own line "
              f"(got={got}, want=[{want}])")

    with tempfile.TemporaryDirectory() as tmp:
        # DEGRADED alone, with no other marker in the sentence. Paired with "dev
        # checkout", the first match is always the other marker, and dropping DEGRADED
        # from the set changes nothing anyone can see.
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail="\nWhen in doubt, skip the DEGRADED line; it alarms readers.\n")
        check(with_root(root, lambda: codes(p)) == ["RESTATED-CONTRACT"],
              "a restatement of the BANNER rule alone is flagged — each marker has to "
              "carry its own weight, not ride on a co-occurring one (within a fragment "
              "carrying no delegating phrase; see the note on DELEGATION)")

    with tempfile.TemporaryDirectory() as tmp:
        # Three restatements in one punctuation-free run: three findings, not one.
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail="\n- prefer the versioned plugin cache\n- then a dev checkout\n"
                            "- and skip the DEGRADED banner\n")
        check(len(with_root(root, lambda: codes(p))) == 3,
              "three restatements in one fragment are three findings — one per fix-and-"
              "re-run cycle is how a real sweep becomes three")

    print("check-agent-references — the pinned set is itself guarded:")
    check(len(car.EXPECTED_AGENTS) >= 1 and all(
              (car.ROOT / rel).is_file() for rel in car.EXPECTED_AGENTS),
          "EXPECTED_AGENTS names the shipped in-scope agents and every one exists")
    check(len(set(car.EXPECTED_AGENTS)) == len(car.EXPECTED_AGENTS),
          "EXPECTED_AGENTS has no DUPLICATE member — a length check alone is a floor, and "
          "a duplicated entry keeps the length whole while a real agent leaves the "
          "population")

    print("check-agent-references — the attrition path returns 1, not just prints:")
    with tempfile.TemporaryDirectory() as tmp:
        # run-tests.sh gates on exit status only, so a validator that prints FAIL: and
        # returns 0 reports as passing. The documented exit-1 paths are pinned by code, not
        # by the message they print.
        root = Path(tmp)
        agent_file(root, "demo", canonical("demo", "REVIEW"))
        old = car.ROOT
        car.ROOT = root
        try:
            rc = car.main()
        finally:
            car.ROOT = old
        check(rc == 1,
              f"a population missing every pinned agent EXITS 1 (got {rc}) — printing "
              f"FAIL: while returning 0 is invisible to the harness")

    print("check-agent-references — the variable's other spelling:")
    with tempfile.TemporaryDirectory() as tmp:
        # No shipped agent uses the unbraced form, so only this case exercises the
        # broadened trigger. An agent written `$CLAUDE_PLUGIN_ROOT` is in the population
        # per the code; this pins it.
        root = Path(tmp)
        d = root / "demo" / "agents"
        d.mkdir(parents=True)
        p = d / "unbraced.md"
        p.write_text("# unbraced\n\nRead `$CLAUDE_PLUGIN_ROOT/references/x.md` first.\n")
        check(with_root(root, lambda: codes(p)) == ["NO-CONTRACT-BLOCK"],
              "an agent using the UNBRACED $CLAUDE_PLUGIN_ROOT is in the population — the "
              "spelling is not the property, the variable is")

    print("check-agent-references — the block's position, not just its words:")
    with tempfile.TemporaryDirectory() as tmp:
        # Content is pinned by the literal; position is the half the literal cannot see,
        # and it is the half the gate criterion is actually about.
        root = Path(tmp)
        d = root / "demo" / "agents"
        d.mkdir(parents=True)
        p = d / "late.md"
        p.write_text(f"# late\n\n## Output format\n\nReturn one block.\n\n"
                     f"{car.OPEN}\n{canonical('demo', 'REVIEW')}\n{car.CLOSE}\n\n"
                     f"Read `${{CLAUDE_PLUGIN_ROOT}}/references/x.md`.\n")
        check(with_root(root, lambda: codes(p)) == ["BLOCK-NOT-FIRST"],
              "a canonical block sitting BELOW the output schemas is rejected — a "
              "first-screen promise made on the third screen is not the same promise")

    with tempfile.TemporaryDirectory() as tmp:
        # An H3, not an H2. With only `## Output format` fixtures, narrowing HEADING_RE
        # to `^## ` survives — and `### Output schema N` above the block is the shape
        # the rule is for.
        root = Path(tmp)
        d = root / "demo" / "agents"; d.mkdir(parents=True)
        p = d / "h3.md"
        p.write_text(f"# a\n\n### Output schema 1\n\ntext\n\n{car.OPEN}\n"
                     f"{canonical('demo', 'REVIEW')}\n{car.CLOSE}\n\n"
                     f"Read `${{CLAUDE_PLUGIN_ROOT}}/references/x.md`.\n")
        check(with_root(root, lambda: codes(p)) == ["BLOCK-NOT-FIRST"],
              "a block below an H3 output schema is rejected — the rule is 'nothing else "
              "is read first', not 'no H2 precedes it'")

    with tempfile.TemporaryDirectory() as tmp:
        # Unheaded prose reads first too. Without this case FIRST_SCREEN_LINES is pinned
        # by nothing, and raising it to 100000 survives the whole harness.
        root = Path(tmp)
        d = root / "demo" / "agents"; d.mkdir(parents=True)
        p = d / "buried.md"
        p.write_text(f"# a\n\n" + ("filler\n" * 60) + f"\n{car.OPEN}\n"
                     f"{canonical('demo', 'REVIEW')}\n{car.CLOSE}\n\n"
                     f"Read `${{CLAUDE_PLUGIN_ROOT}}/references/x.md`.\n")
        check(with_root(root, lambda: codes(p)) == ["BLOCK-NOT-FIRST"],
              f"a block buried under 60 lines of unheaded prose is rejected — "
              f"FIRST_SCREEN_LINES ({car.FIRST_SCREEN_LINES}) is the bound, and a heading "
              f"check alone cannot see prose")

    print("check-agent-references — the noun slot, the design's only free field:")
    with tempfile.TemporaryDirectory() as tmp:
        # `[A-Z]+` is what keeps the slot from becoming a hole. Without this case a
        # loosening to `.*` goes unnoticed and lets arbitrary text sit inside the banner
        # while the block stays "canonical".
        root = Path(tmp)
        base = canonical("demo", "REVIEW")
        assert "DEGRADED REVIEW" in base
        body = base.replace("DEGRADED REVIEW", "DEGRADED REVIEW, but only when convenient")
        p = agent_file(root, "demo", body)
        check(with_root(root, lambda: codes(p)) == ["NON-CANONICAL-CONTRACT"],
              "text smuggled into the banner's noun slot is rejected — the slot is one "
              "all-caps word, not a free field")

    print("check-agent-references — a delegating sentence cannot launder an inversion:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = agent_file(root, "demo", canonical("demo", "REVIEW"),
                       tail="\nFor scripts the reference-resolution contract is relaxed: "
                            "prefer a dev checkout over the versioned plugin cache, and "
                            "never emit a DEGRADED banner.\n")
        found = with_root(root, lambda: codes(p))
        check(found and set(found) == {"RESTATED-CONTRACT"},
              f"naming the contract does NOT exempt a sentence that also restates the "
              f"fallback arms — an unconditional escape token is a suppression mechanism "
              f"({found})")

    print("check-agent-references — the population is a pinned set, not a count:")
    check(set(car.EXPECTED_AGENTS) <= {p.relative_to(car.ROOT).as_posix() for p in live_paths()},
          "every pinned agent is present in the live population")

    print("check-agent-references — the depth note is computed, not written:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "deep" / "skills" / "s" / "references").mkdir(parents=True)
        check(with_root(root, lambda: car.depth_kind("deep")) == "SKILLS_ONLY",
              "a plugin with references only under skills/ gets the SKILLS_ONLY note")
        (root / "deep" / "references").mkdir()
        check(with_root(root, lambda: car.depth_kind("deep")) == "BOTH",
              "adding a root references/ dir moves the same plugin to BOTH")

    with tempfile.TemporaryDirectory() as tmp:
        # The pattern-copy defect, as a case: the note that is TRUE for a two-depth plugin
        # is FALSE for a skills-only one, and copying it across is how a wrong note ships.
        root = Path(tmp)
        (root / "deep" / "skills" / "s" / "references").mkdir(parents=True)
        p = agent_file(root, "deep", canonical("deep", "REVIEW", "BOTH"))
        check(with_root(root, lambda: codes(p)) == ["NON-CANONICAL-CONTRACT"],
              "the BOTH depth note on a SKILLS_ONLY plugin is rejected — the note cannot "
              "disagree with the tree, because the tree is where it comes from")

    print("check-agent-references — the population:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        agent_file(root, "demo", canonical("demo", "REVIEW"))
        d = root / "other" / "agents"
        d.mkdir(parents=True)
        (d / "plain.md").write_text("# plain\n\nNo plugin-rooted reference here.\n")
        found = with_root(root, lambda: [p for p in car.agents()
                                         if car.findings_for(p) is not None])
        check(len(found) == 1,
              "an agent naming no ${CLAUDE_PLUGIN_ROOT} reference is not in the population")

    live = live_paths()
    check(len(live) >= len(car.EXPECTED_AGENTS),
          f"the live population is enumerated from disk ({len(live)} agents)")
    # One plugin ships here; the population must be exactly the pinned set, read from
    # the sources — never the generated plugins/ copy, which would double it.
    rels = sorted(p.relative_to(car.ROOT).as_posix() for p in live)
    check(rels == sorted(car.EXPECTED_AGENTS),
          f"the population is the pinned set, read from the sources ({rels})")
    bad = {p.relative_to(car.ROOT).as_posix(): codes(p) for p in live if codes(p)}
    check(bad == {}, f"every shipped in-scope agent carries its canonical block ({bad})")

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
