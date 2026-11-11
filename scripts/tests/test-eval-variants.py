#!/usr/bin/env python3
"""eval-variants.py builds the with/without plugin copies and fails loudly when a strip misses.

The behaviour-rule measurement compares a plugin with a rule against the same plugin
without it. That comparison measures nothing if the `without` build still holds the rule
(a heading that was not found, so nothing was stripped) or if it lost more than the rule
(a strip that ran into the neighbouring section). This suite builds from a synthetic
fixture plugin and from the real Claude package, and checks both ways a build can lie.

  build          with/ plus one without-<rule>/ per rule, each with the cases in evals/
  exact strip    the listed text is gone and every other file is byte-identical to with/
  neighbours     a stripped section takes its subsections but not the next section
  manifest       a removed array entry leaves valid JSON with only that entry gone
  no match       a heading, paragraph, folder or array entry that matches nothing exits
                 non-zero naming it, and leaves the output folder empty
  refusal        a non-empty output folder is refused
  real package   the committed strip list applies to the committed Claude package
"""
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scripts", "eval-variants.py")
REAL_SOURCE = os.path.join(REPO, "plugins", "claude", "planning")
REAL_VARIANTS = os.path.join(REPO, "evals", "behaviour-rules", "variants.json")
FAILS = []


def check(ok, msg, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        FAILS.append(msg)
        if detail:
            print("     | " + str(detail)[-900:].replace("\n", "\n     | "))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run(*args):
    return subprocess.run([sys.executable, "-B", SCRIPT, *args],
                          capture_output=True, text=True)


def files_under(root, skip_top=()):
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            if rel.split(os.sep)[0] in skip_top:
                continue
            out.add(rel)
    return out


# ---------------------------------------------------------------- fixture plugin

MANIFEST = """{
  "name": "fixture",
  "version": "0.0.1",
  "skills": [
    "./skills/alpha",
    "./skills/gatekeeper",
    "./skills/runner"
  ],
  "license": "MIT"
}
"""

RUNNER = """# Runner

Intro line.

## Before

Before body stays.

## Keep going

Keep going body goes.

```
## Fake heading inside a fence
```

Still inside keep going.

### Keep going detail

Subsection goes with its parent.

## After

After body stays.

### After detail

After detail stays.
"""

RUNNER_STRIPPED = """# Runner

Intro line.

## Before

Before body stays.

## After

After body stays.

### After detail

After detail stays.
"""

NOTES = """# Notes

## Checks

Refuse unless all are true.

**These are the whole check.** Satisfying them means go,
not a pause to ask first.

Next paragraph stays.

## Go

Cleared tasks are already authorized. Go **without asking**
whether to proceed.

Launch every task at once.

## Collect

Collect results.
"""

NOTES_STRIPPED = """# Notes

## Checks

Refuse unless all are true.

Next paragraph stays.

## Go

Launch every task at once.

## Collect

Collect results.
"""

FIXTURE_VARIANTS = {
    "rules": [
        {"id": "R1", "name": "gatekeeper", "mentions": ["gatekeeper"],
         "strip": [
             {"path": "skills/gatekeeper", "remove": "folder"},
             {"path": ".claude-plugin/plugin.json",
              "json_array_item": {"key": "skills", "value": "./skills/gatekeeper"}},
         ]},
        {"id": "R2", "name": "keep-going", "mentions": ["keep going"],
         "strip": [
             {"path": "skills/runner/SKILL.md", "section": "## Keep going"},
         ]},
        {"id": "R3", "name": "go-without-asking", "mentions": ["without asking"],
         "strip": [
             {"path": "references/notes.md", "paragraph": "**These are the whole check.**"},
             {"path": "references/notes.md",
              "paragraph": "Cleared tasks are already authorized.", "in_section": "## Go"},
         ]},
        {"id": "R4", "name": "last-entry", "mentions": ["runner"],
         "strip": [
             {"path": ".claude-plugin/plugin.json",
              "json_array_item": {"key": "skills", "value": "./skills/runner"}},
         ]},
    ]
}


def make_fixture(root):
    src = os.path.join(root, "plugin")
    write(os.path.join(src, ".claude-plugin", "plugin.json"), MANIFEST)
    write(os.path.join(src, "skills", "alpha", "SKILL.md"), "# Alpha\n\nMentions keep going once.\n")
    write(os.path.join(src, "skills", "gatekeeper", "SKILL.md"), "# Gatekeeper\n\nRules.\n")
    write(os.path.join(src, "skills", "gatekeeper", "references", "more.md"), "More.\n")
    write(os.path.join(src, "skills", "runner", "SKILL.md"), RUNNER)
    write(os.path.join(src, "references", "notes.md"), NOTES)
    write(os.path.join(src, "README.md"), "Fixture. See gatekeeper.\n")
    cases = os.path.join(root, "cases")
    write(os.path.join(cases, "case-a", "case.yaml"), "schema_version: \"1.1\"\nprompt: a\n")
    write(os.path.join(cases, "case-a", "graders", "g.md"), "---\ntype: regex\n---\n")
    write(os.path.join(cases, "case-a-control", "case.yaml"), "schema_version: \"1.1\"\nprompt: b\n")
    variants = os.path.join(root, "variants.json")
    write(variants, json.dumps(FIXTURE_VARIANTS, indent=2) + "\n")
    return src, cases, variants


def variant_files_ok(out, src, cases, rule_strips, label):
    """Every non-listed file in each without build is byte-identical to with/."""
    with_dir = os.path.join(out, "with")
    for case in ("case-a", "case-a-control"):
        check(filecmp.cmp(os.path.join(cases, case, "case.yaml"),
                          os.path.join(with_dir, "evals", case, "case.yaml"), shallow=False),
              f"{label}: with/evals/{case}/case.yaml is a copy of the case")
    src_files = files_under(src)
    with_files = files_under(with_dir, skip_top=("evals",))
    check(src_files == with_files, f"{label}: with/ holds exactly the source's files",
          sorted(src_files ^ with_files))
    diff = [f for f in src_files if not filecmp.cmp(os.path.join(src, f),
                                                     os.path.join(with_dir, f), shallow=False)]
    check(not diff, f"{label}: with/ is byte-identical to the source", diff)
    for rid, (listed_files, removed_dirs) in rule_strips.items():
        vdir = os.path.join(out, f"without-{rid}")
        check(os.path.isdir(vdir), f"{label}: without-{rid}/ exists")
        if not os.path.isdir(vdir):
            continue
        vfiles = files_under(vdir)
        wfiles = files_under(with_dir)
        expected = {f for f in wfiles
                    if not any(f == d or f.startswith(d + os.sep) for d in removed_dirs)}
        check(vfiles == expected, f"{label}: without-{rid}/ holds with/'s files minus the removed folders",
              sorted(vfiles ^ expected))
        for d in removed_dirs:
            check(not os.path.exists(os.path.join(vdir, d)), f"{label}: without-{rid}/{d} is gone")
        for f in sorted(vfiles & wfiles):
            same = filecmp.cmp(os.path.join(vdir, f), os.path.join(with_dir, f), shallow=False)
            if f in listed_files:
                check(not same, f"{label}: without-{rid}/{f} differs from with/ (listed strip)")
            elif not same:
                check(False, f"{label}: without-{rid}/{f} is byte-identical to with/ (not listed)")


tmp = tempfile.mkdtemp(prefix="eval-variants-test-")
try:
    src, cases, variants = make_fixture(tmp)
    common = ["--source", src, "--cases", cases, "--variants", variants]

    # ---- build succeeds and strips exactly the listed text
    out = os.path.join(tmp, "out")
    r = run("build", out, *common)
    check(r.returncode == 0, "fixture: build exits 0", r.stdout + r.stderr)
    if r.returncode == 0:
        variant_files_ok(out, src, cases, {
            "R1": ({".claude-plugin/plugin.json"}, ["skills/gatekeeper"]),
            "R2": ({"skills/runner/SKILL.md"}, []),
            "R3": ({"references/notes.md"}, []),
            "R4": ({".claude-plugin/plugin.json"}, []),
        }, "fixture")
        got = read(os.path.join(out, "without-R2", "skills", "runner", "SKILL.md"))
        check(got == RUNNER_STRIPPED,
              "fixture: the section strip removes the section and its subsection, nothing more",
              got)
        got = read(os.path.join(out, "without-R3", "references", "notes.md"))
        check(got == NOTES_STRIPPED,
              "fixture: each paragraph strip removes only its paragraph", got)
        for rid, gone in (("R1", "./skills/gatekeeper"), ("R4", "./skills/runner")):
            text = read(os.path.join(out, f"without-{rid}", ".claude-plugin", "plugin.json"))
            try:
                data = json.loads(text)
                expected = json.loads(MANIFEST)
                expected["skills"].remove(gone)
                check(data == expected, f"fixture: without-{rid} manifest drops only {gone}", text)
            except ValueError as exc:
                check(False, f"fixture: without-{rid} manifest is valid JSON", f"{exc}\n{text}")
            check(text.count("\n") == MANIFEST.count("\n") - 1,
                  f"fixture: without-{rid} manifest loses exactly one line", text)
        check("R1" in r.stdout and "README.md:1" in r.stdout,
              "fixture: build lists the rule's remaining mentions (R1 in README.md)", r.stdout)
        m = run("mentions", out, "--variants", variants)
        check(m.returncode == 0 and "README.md:1" in m.stdout and "grep" in m.stdout,
              "fixture: mentions lists remaining mentions with the grep behind them",
              m.stdout + m.stderr)
        check("evals" not in "".join(l for l in m.stdout.splitlines() if ":" in l and l.startswith("R")),
              "fixture: mentions does not count the copied cases", m.stdout)

    # ---- a non-empty output folder is refused
    r = run("build", out, *common)
    check(r.returncode != 0 and "not empty" in (r.stdout + r.stderr),
          "fixture: a non-empty output folder is refused", r.stdout + r.stderr)

    # ---- every strip kind that matches nothing exits non-zero naming it
    misses = [
        ("section", {"path": "skills/runner/SKILL.md", "section": "## Keep Going"}, "## Keep Going"),
        ("paragraph", {"path": "references/notes.md", "paragraph": "These are the whole check."},
         "These are the whole check."),
        ("paragraph in section", {"path": "references/notes.md",
                                  "paragraph": "Next paragraph stays.", "in_section": "## Go"},
         "Next paragraph stays."),
        ("folder", {"path": "skills/missing", "remove": "folder"}, "skills/missing"),
        ("array entry", {"path": ".claude-plugin/plugin.json",
                         "json_array_item": {"key": "skills", "value": "./skills/missing"}},
         "./skills/missing"),
        ("file", {"path": "skills/nope/SKILL.md", "section": "## X"}, "skills/nope/SKILL.md"),
        ("ambiguous heading", {"path": "skills/runner/SKILL.md", "section": "## Before"}, None),
    ]
    for label, entry, named in misses:
        v = json.loads(json.dumps(FIXTURE_VARIANTS))
        if label == "ambiguous heading":
            with open(os.path.join(src, "skills", "runner", "SKILL.md"), "a", encoding="utf-8") as fh:
                fh.write("\n## Before\n\nA second one.\n")
            named = "## Before"
        v["rules"][1]["strip"] = [entry]
        vpath = os.path.join(tmp, "v-miss.json")
        write(vpath, json.dumps(v, indent=2))
        mout = os.path.join(tmp, "out-miss")
        r = run("build", mout, "--source", src, "--cases", cases, "--variants", vpath)
        both = r.stdout + r.stderr
        check(r.returncode != 0 and named in r.stderr and "R2" in r.stderr,
              f"fixture: a {label} that matches nothing exits non-zero, its error naming it and its rule",
              both)
        check(not os.path.exists(mout) or not os.listdir(mout),
              f"fixture: a failed build ({label}) leaves no output", os.listdir(mout) if os.path.exists(mout) else "")
        if os.path.exists(mout):
            shutil.rmtree(mout)
    write(os.path.join(src, "skills", "runner", "SKILL.md"), RUNNER)

    # ---- a rule with no mention terms is refused: its remaining-mentions listing would be empty
    for label, value in (("empty", []), ("blank", [""]), ("absent", None)):
        v = json.loads(json.dumps(FIXTURE_VARIANTS))
        if value is None:
            v["rules"][0].pop("mentions", None)
        else:
            v["rules"][0]["mentions"] = value
        vpath = os.path.join(tmp, "v-nomention.json")
        write(vpath, json.dumps(v, indent=2))
        r = run("build", os.path.join(tmp, "out-nomention"), "--source", src, "--cases", cases,
                "--variants", vpath)
        check(r.returncode != 0 and "R1" in r.stderr and "mentions" in r.stderr,
              f"fixture: a rule whose mentions are {label} exits non-zero naming it", r.stdout + r.stderr)

    # ---- a cases folder holding no case is an error, not an empty suite
    empty_cases = os.path.join(tmp, "empty-cases")
    os.makedirs(empty_cases)
    r = run("build", os.path.join(tmp, "out-nocase"), "--source", src, "--cases", empty_cases,
            "--variants", variants)
    check(r.returncode != 0 and "case" in (r.stdout + r.stderr),
          "fixture: a cases folder with no case.yaml exits non-zero", r.stdout + r.stderr)

    # ---- the committed strip list applies to the committed Claude package
    rout = os.path.join(tmp, "real")
    r = run("build", rout, "--cases", cases)
    check(r.returncode == 0, "real: build from plugins/claude/planning with variants.json exits 0",
          r.stdout + r.stderr)
    if r.returncode == 0:
        real = json.loads(read(REAL_VARIANTS))
        strips = {}
        for rule in real["rules"]:
            listed = {e["path"] for e in rule["strip"] if "remove" not in e}
            removed = [e["path"] for e in rule["strip"] if e.get("remove") == "folder"]
            strips[rule["id"]] = (listed, removed)
        check(sorted(strips) == ["R1", "R2", "R3"], "real: variants.json lists R1, R2 and R3",
              sorted(strips))
        variant_files_ok(rout, REAL_SOURCE, cases, strips, "real")
        # The listing is the record's stated limit, so it must reach the text that still
        # carries each rule: R2's Stop hook, R1's spaced name, R3's cross-references.
        listing = r.stdout
        for rid, rel in (("R2", "hooks/plan-continue.sh:"), ("R2", "hooks/mod/stop.ts:"),
                         ("R1", "README.md:"), ("R3", "skills/executing-plans/SKILL.md:")):
            check(any(line.startswith(f"{rid} {rel}") for line in listing.splitlines()),
                  f"real: the {rid} mentions listing reaches {rel.rstrip(':')}", listing[-1500:])
        trunk = "skills/executing-plans/SKILL.md"
        disp = "skills/executing-plans/references/dispatch.md"
        absent = {
            "R1": [],
            "R2": [(trunk, "## Run to completion — don't stop until you have to\n")],
            "R3": [(trunk, "## The plan is the authorization — dispatch without a confirmation turn\n"),
                   (disp, "**These five preconditions are the whole check.**"),
                   (disp, "Tasks that cleared the preconditions are already authorized.")],
        }
        for rid, pairs in absent.items():
            for rel, text in pairs:
                with_text = read(os.path.join(rout, "with", rel))
                got = read(os.path.join(rout, f"without-{rid}", rel))
                check(text in with_text and text not in got,
                      f"real: without-{rid}/{rel} no longer holds {text.strip()[:50]!r}")
        for rel, heading in ((trunk, "## Checklist\n"), (trunk, "## A bug found during execution is a class"),
                             (disp, "## Select\n"), (disp, "Launch every task in S in a **single message**")):
            for rid in ("R2", "R3"):
                check(heading in read(os.path.join(rout, f"without-{rid}", rel)),
                      f"real: without-{rid}/{rel} keeps its neighbour {heading.strip()[:40]!r}")
        manifest = os.path.join(rout, "without-R1", ".claude-plugin", "plugin.json")
        try:
            data = json.loads(read(manifest))
            check("./skills/honest-gates" not in data["skills"] and len(data["skills"]) ==
                  len(json.loads(read(os.path.join(REAL_SOURCE, ".claude-plugin", "plugin.json")))["skills"]) - 1,
                  "real: without-R1 manifest drops only ./skills/honest-gates", data["skills"])
        except ValueError as exc:
            check(False, "real: without-R1 manifest is valid JSON", exc)
        check(not os.path.exists(os.path.join(rout, "without-R1", "skills", "honest-gates")),
              "real: without-R1 has no skills/honest-gates/")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s) failed")
    sys.exit(1)
print("PASS: eval-variants builds exact with/without copies and fails on a strip that misses")
