#!/usr/bin/env python3
"""Fixture suite for owner-decision.py — run directly:

    python3 core/skills/executing-plans/tests/test-owner-decision.py

WHAT THIS SUITE IS REALLY GUARDING. An executor that reads `applies to:` itself stretches
an entry to the case in front of it: an entry for "the Stage 2 close-out" was applied to a
one-stage plan's merge in 3 of 3 runs, twice after the prose said not to. The script is
the only reader now, and its first version kept the words it knew and skipped the rest, so
"anything except close-out", "close-out *(Stage 2 only)*" and a one-word command all
passed. So the reader denies by default, and the last part of this suite asserts that as a
property over a battery of entries: whatever `check` passes, `match` lists at its own
place; whatever `check` flags, `match` refuses at every case. Each case runs the CLI the
way the executor does and reads its exit code and output.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "owner-decision.py"

passed = failed = 0


def ok(msg):
    global passed
    passed += 1
    print(f"  ok    {msg}")


def bad(msg, detail=""):
    global failed
    failed += 1
    print(f"  FAIL  {msg}")
    if detail:
        print("        | " + str(detail)[:600].replace("\n", "\n        | "))


def expect(cond, msg, detail=""):
    (ok if cond else (lambda m: bad(m, detail)))(msg)


TMP = Path(tempfile.mkdtemp(prefix="owner-decision-test-"))


def plan(name, stages, entries, head="# Light Plan: calc", extra=""):
    """A synthetic plan: `stages` is {stage number: [task ids]}; `entries` are the
    lines of `## Owner decisions`, or None for a plan without the section."""
    lines = [head, "Date: 2026-10-26", extra, ""]
    if entries is not None:
        lines += ["## Owner decisions", ""] + entries + [""]
    for s, tasks in stages.items():
        lines += [f"## Stage {s}: s{s}", "", "**Goal:** g", ""]
        for t in tasks:
            lines += [f"### Task {t}: t", "- **Status:** [ ]", "- **Test:** `true`", ""]
        lines += [f"### Stage {s} Gate", "- [ ] `true`", ""]
    p = TMP / name
    p.write_text("\n".join(lines))
    return p


def run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def listed(out):
    return [l.split()[1] for l in out.splitlines() if l.startswith("applies ")]


Q = 'owner, 2026-10-26: "yes"'
MERGE = "merge feat/x into main, then delete it"

try:
    # --- match: places ------------------------------------------------------------

    # Catches: the B1 case — a stage the plan does not have, read as "this plan's close-out".
    one = plan("one-light-plan.md", {1: ["1.1", "1.2"]}, [
        f"- **OD-1** — {MERGE} — {Q} — applies to: the Stage 2 close-out merge offer only",
        f"- **OD-2** — {MERGE} — {Q} — applies to: close-out",
    ])
    rc, out = run("match", "--plan", one, "--at", "closeout")
    expect(rc == 0 and listed(out) == ["OD-2"], "a close-out entry is listed at close-out; the B1 one is not", out)
    expect("OD-1" in out and "no Stage 2" in out, "the B1 refusal names the missing stage", out)

    rc, out = run("match", "--plan", one, "--at", "closeout", "--json")
    try:
        j = json.loads(out)
        expect([e["id"] for e in j["applies"]] == ["OD-2"]
               and [e["id"] for e in j["refused"]] == ["OD-1"], "--json carries the same verdict", j)
    except ValueError:
        bad("--json prints JSON", out)

    two = plan("two-plan.md", {1: ["1.1", "1.2"], 2: ["2.1"]}, [
        f"- **OD-1** — run the migration — {Q} — applies to: Stage 2 (`./migrate up`)",
        f"- **OD-2** — skip the review — {Q} — applies to: Task 1.3",
        f"- **OD-3** — use branch feat/x — {Q} — applies to: Preflight",
        f"- **OD-4** — run it — {Q} — applies to: Stage 02",
    ])
    rc, out = run("match", "--plan", two, "--at", "stage", "--stage", "1")
    expect(rc == 1 and listed(out) == [], "at Stage 1, entries naming Stage 2 do not apply", out)
    rc, out = run("match", "--plan", two, "--at", "stage", "--stage", "2", "--command", "./migrate up")
    expect(rc == 0 and listed(out) == ["OD-1"], "at Stage 2 with its command, only the entry naming it applies", out)
    rc, out = run("match", "--plan", two, "--at", "stage", "--stage", "2")
    expect(rc == 0 and listed(out) == ["OD-4"], "at Stage 2 with no command, the stage entry applies (Stage 02 is 2)", out)
    rc, out = run("match", "--plan", two, "--at", "closeout")
    expect(rc == 1, "a stage entry does not apply at close-out", out)
    rc, out = run("match", "--plan", two, "--at", "stage", "--stage", "1", "--task", "1.2")
    expect("OD-2" not in listed(out) and "Task 1.3" in out, "an entry naming Task 1.3 does not apply at Task 1.2", out)
    rc, out = run("match", "--plan", two, "--at", "preflight")
    expect(rc == 0 and listed(out) == ["OD-3"], "a Preflight entry applies at Preflight only", out)
    rc, out = run("match", "--plan", two, "--at", "stage", "--stage", "2")
    expect("OD-1" not in listed(out) and "--command" in out, "an entry naming a command needs --command", out)

    # --- match: commands ------------------------------------------------------------

    cmd = plan("cmd-plan.md", {1: ["1.1"]}, [
        f"- **OD-1** — force-push — {Q} — applies to: close-out (`git push --force origin x`)",
        f"- **OD-2** — merge — {Q} — applies to: close-out",
        f"- **OD-3** — deploy — {Q} — applies to: close-out (`./deploy`)",
        f"- **OD-4** — merge and delete — {Q} — applies to: close-out (`git merge x`, `git branch -d x`)",
    ])
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "git branch -D x")
    expect("OD-1" not in listed(out), "an entry naming another command does not apply", out)
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "git branch -D x", "--require-command")
    expect(rc == 1 and listed(out) == [], "--require-command refuses an entry naming no command", out)
    # Catches close-out demo Material 1: a destructive command checked without the flag
    # applied an entry naming no command.
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "git branch -D x")
    expect(rc == 1 and listed(out) == [] and "names no command" in out,
           "--command alone refuses an entry naming no command", out)
    rc, out = run("match", "--plan", cmd, "--at", "closeout")
    expect(listed(out) == ["OD-2"], "with no --command, an entry naming no command still applies", out)
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", " git push --force origin x ", "--require-command")
    expect(rc == 0 and listed(out) == ["OD-1"], "the exact command (outer spaces aside) applies", out)
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "git  push --force origin x", "--require-command")
    expect(listed(out) == [], "commands match as exact text: an inner double space is another command", out)
    # Catches C1: a one-word code span read as no command, so any command passed.
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "rm -rf /")
    expect("OD-3" not in listed(out), "a one-word command span is a command: another command does not match it", out)
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "./deploy", "--require-command")
    expect(listed(out) == ["OD-3"], "a one-word command matches itself", out)
    rc, out = run("match", "--plan", cmd, "--at", "closeout", "--command", "git branch -d x", "--require-command")
    expect(listed(out) == ["OD-4"], "an entry naming several commands covers each of them", out)

    # --- match: deny by default -----------------------------------------------------

    deny = plan("deny-plan.md", {1: ["1.1"], 2: ["2.1"]}, [
        f"- **OD-1** — merge — {Q} — applies to: anything except close-out",
        f"- **OD-2** — merge — {Q} — applies to: never at close-out",
        f"- **OD-3** — run — {Q} — applies to: not Stage 2",
        f"- **OD-4** — merge — {Q} — applies to: close-out *(Stage 2 only)*",
        f"- **OD-5** — merge — {Q} — applies to: close-out",
        "only if Stage 2 is the last stage",
        f"- **OD-6** — merge — {Q} — applies to: Preflight or close-out",
        f"- **OD-7** — merge — {Q} — applies to: the Stage 2 close-out",
        f"- **OD-8** — the author thinks so *(owner, 2026-10-26: \"x\")* — applies to: close-out",
    ])
    for at, extra in (("closeout", []), ("preflight", []), ("stage", ["--stage", "2"]), ("stage", ["--stage", "1"])):
        rc, out = run("match", "--plan", deny, "--at", at, *extra)
        expect(rc == 1 and listed(out) == [], f"negation, a note, a lazy continuation, 'or', two positions and a quote in a note all refuse (at {at} {' '.join(extra)})", out)
    rc, out = run("match", "--plan", deny, "--at", "closeout")
    expect("cannot place: 'anything', 'except'" in out, "C4: the refusal names the unread words", out)
    expect("OD-5" in out and "section holds a line that is not an entry" in out.split("OD-5")[1].split("\n")[0],
           "C2: a line under an entry is not part of it; it voids the section", out)
    expect("more than one position" in out, "I3: Stage N and close-out never combine", out)
    expect("outside a note" in out, "I5: owner's words inside a note do not count", out)

    # Catches round 2's repeat of C2: text Markdown attaches to an entry, after it,
    # that the reader never read — so the entry must be refused, never listed.
    after = plan("after-plan.md", {1: ["1.1"], 2: ["2.1"]}, [
        f"- **OD-1** — merge — {Q} — applies to: close-out",
        "  - only when Stage 2 was skipped",
        f"- **OD-2** — merge — {Q} — applies to: close-out",
        "1. except Stage 2",
        f"- **OD-3** — merge — {Q} — applies to: close-out",
        "",
        "  Only if the plan has two stages.",
        f"- **OD-4** — merge — {Q} — applies to: close-out",
        "  ```",
        "  only Stage 2",
        "  ```",
        f"- **OD-5** — merge — {Q} — applies to: Stage 2 only — applies to: Stage 1",
        f"- **OD-6** — merge *(ask at execution)* — {Q} — applies to: close-out",
        f"- **OD-7** — merge — owner, 2026-10-26 (agent inferred): \"yes\" — applies to: close-out",
        f"- **OD-8** — merge *(unterminated {Q} — applies to: close-out",
        f"- **OD-9** — merge — {Q} — applies to: Stage 2 *(applies to: close-out)*",
    ])
    for at, extra in (("closeout", []), ("stage", ["--stage", "1"]), ("stage", ["--stage", "2"])):
        rc, out = run("match", "--plan", after, "--at", at, *extra)
        expect(rc == 1 and listed(out) == [], f"text after an entry, two markers, a declined note, a loose owner line and an unterminated note all refuse (at {at} {' '.join(extra)})", out)
    rc, out = run("match", "--plan", after, "--at", "closeout")
    expect(out.count("section holds a line that is not an entry") >= 4, "every entry in a section with a stray line says so", out)
    expect("more than one `applies to:`" in out, "two markers refuse", out)
    rc, out = run("check", after)
    flagged = {l.split(": ")[1] for l in out.splitlines() if ": OD-" in l}
    expect(rc == 1 and {f"OD-{k}" for k in (1, 2, 3, 4, 5, 7, 8, 9)} <= flagged,
           "check flags every one of them", out)

    quoted = plan("quoted-plan.md", {1: ["1.1"]}, [
        f"- **OD-1** — remove it — {Q} — applies to: close-out (`rm -rf \"my  dir\"`)",
    ])
    rc, out = run("match", "--plan", quoted, "--at", "closeout", "--command", 'rm -rf "my dir"', "--require-command")
    expect(listed(out) == [], "spaces inside a quoted argument count: another directory does not match", out)
    rc, out = run("match", "--plan", quoted, "--at", "closeout", "--command", 'rm -rf "my  dir"', "--require-command")
    expect(listed(out) == ["OD-1"], "the same text matches", out)
    rc, out = run("match", "--plan", quoted, "--at", "closeout", "--command", 'rm  -rf "my  dir"', "--require-command")
    expect(listed(out) == [], "other spacing is other text", out)

    # Catches round 3's findings: what the shell does is the command, quoting included;
    # and nothing in the section but entry lines, blank lines and the `none` line is read.
    exact = plan("exact-plan.md", {1: ["1.1"]}, [
        f"- **OD-1** — remove the file named star — {Q} — applies to: close-out (`rm -rf '*'`)",
        f"- **OD-2** — merge — {Q} — applies to: close-out (`git merge feat/x`)",
    ])
    rc, out = run("match", "--plan", exact, "--at", "closeout", "--command", "rm -rf *", "--require-command")
    expect(listed(out) == [], "C1: a quoted glob is not an unquoted one", out)
    rc, out = run("match", "--plan", exact, "--at", "closeout", "--command", "git merge --no-edit feat/x", "--require-command")
    expect(listed(out) == [], "M1: a command with another flag is another command", out)
    for name, lines in (
        ("i1", [f"- **OD-1** — merge — {Q} — applies to: close-out", "- none of the above apply after Stage 2"]),
        ("i2a", [f"- **OD-1** — run — {Q} — applies to: Preflight", "### Withdrawn", f"- **OD-2** — merge — {Q} — applies to: close-out"]),
        ("i2b", ["Entries below apply only to Stage 2.", "", f"- **OD-1** — merge — {Q} — applies to: close-out"]),
        ("i3a", ["<!-- withdrawn: -->", f"- **OD-1** — merge — {Q} — applies to: close-out"]),
        ("i3b", [f"- **OD-1** — merge <!-- {Q} --> — applies to: close-out"]),
        ("s2", [f"    - **OD-1** — merge — {Q} — applies to: close-out"]),
        ("twosec", [f"- **OD-1** — merge — {Q} — applies to: close-out", "", "## Owner decisions", "", f"- **OD-2** — merge — {Q} — applies to: close-out"]),
    ):
        pl = plan(f"{name}-plan.md", {1: ["1.1"], 2: ["2.1"]}, lines)
        rc, out = run("match", "--plan", pl, "--at", "closeout")
        expect(rc == 1 and listed(out) == [], f"nothing applies when the section holds more than entries ({name})", out)
        rc, out = run("check", pl)
        expect(rc == 1, f"check reports it ({name})", out)
    nested = TMP / "nested-plan.md"
    nested.write_text("\n".join(["# Light Plan: n", "", "````", "```", "## Owner decisions", "",
        f"- **OD-1** — merge — {Q} — applies to: close-out", "```", "````", "", "## Stage 1: s", ""]))
    rc, out = run("match", "--plan", nested, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "S1: a section inside a nested fence is not a section", out)

    # Catches round 4's findings: what the script reads must be what a reader sees, so
    # entry lines are plain printable text, lines split only where Markdown splits them,
    # and raw HTML or a comment anywhere up to the section's end voids it.
    E = f"- **OD-1** — merge — {Q} — applies to: close-out (`git merge x`)"
    raw = {
        "n1": f"## Owner decisions\n\n{E}\n##\u00a0but only when CI is green\n",
        "n2": f"## Owner decisions\n\n{E}\u2028## except never on main\n",
        "n2ff": f"## Owner decisions\n\n{E}\x0c## except never on main\n",
        "n3": f"## Owner decisions\n\n- **OD-1** — push — {Q} — applies to: close-out (`git merge x``--force`)\n",
        "n4s": f"## Owner decisions\n\n- **OD-1** — ~~merge~~ ~~{Q}~~ — applies to: close-out (`git merge x`)\n",
        "n4h": f"## Owner decisions\n\n- **OD-1** — merge <s>{Q}</s> — applies to: close-out (`git merge x`)\n",
        "n4o": f"## Owner decisions\n\n- **OD-1** — merge %%{Q}%% — applies to: close-out (`git merge x`)\n",
        "n5": f"## Owner decisions\n\n- **OD-1** — merge — {Q} — applies to: close-out (`git merge x\u202e`)\n",
        "n5z": f"## Owner decisions\n\n- **OD-1** — merge — {Q} — applies to: close-out (`git\u200b merge x`)\n",
        "n6": f"<!--\n## Owner decisions\n\n{E}\n\n## Stage 0: hidden\n-->\n",
        "n6pre": f"<pre>\n## Owner decisions\n\n{E}\n",
        "n6obs": f"%%\n## Owner decisions\n\n{E}\n\n## Stage 0: hidden\n%%\n",
        "nonemix": f"## Owner decisions\n\n- none — the catalog triggered no question (swept 2026-10-26)\n{E}\n",
        "askws": f"## Owner decisions\n\n- **OD-1** — merge — ask  at execution — applies to: close-out (`git merge x`)\n",
    }
    for name, sec in raw.items():
        pl = TMP / f"{name}-plan.md"
        pl.write_text(f"# Light Plan: x\n\n{sec}\n## Stage 1: s\n\n### Task 1.1: t\n- **Status:** [ ]\n")
        rc, out = run("match", "--plan", pl, "--at", "closeout", "--command", "git merge x", "--require-command")
        expect(rc == 1 and listed(out) == [], f"what renders differently from what is read refuses ({name})", out)
        if name not in ("n6", "n6pre", "n6obs", "askws"):  # askws is a valid declined entry
            rc, out = run("check", pl)
            expect(rc == 1, f"check reports it ({name})", out)
    sub_np = plan("subnp-plan.md", {1: ["1.1"]}, [f"- **OD-1** — merge — {Q} — applies to: Sub-plan 3 close-out"])
    rc, out = run("match", "--plan", sub_np, "--at", "closeout")
    expect("outside a master's section" in out, "a Sub-plan entry outside a master says so, not 'names no place'", out)

    # Catches round 4's review Importants: the fence scanner must agree with a renderer,
    # or a section a reader sees as code is read as live.
    P1 = '- **OD-1** — d — owner, 2026-10-26: "go" — applies to: Preflight'
    fences = {
        "fence-nbsp": f"# Light Plan: x\n\n## Stage 1: s\n\n```\nx\n```\u00a0\n## Owner decisions\n\n{P1}\n",
        "fence-inline": f"# Light Plan: x\n\n```x``` inline at line start\n\n## Stage 1: s\n\n```\n## Owner decisions\n\n{P1}\n\n## Stage 9: example\n```\n",
        "math": f"# Light Plan: x\n\n$$\n## Owner decisions\n\n{P1}\n\n## Stage 1: s\n",
    }
    for name, body in fences.items():
        pl = TMP / f"{name}-plan.md"
        pl.write_text(body)
        rc, out = run("match", "--plan", pl, "--at", "preflight")
        expect(rc == 1 and listed(out) == [], f"a section a reader sees as code or math is not read ({name})", out)
    real = TMP / "real-fence-plan.md"
    real.write_text(f"# Light Plan: x\n\n```bash\necho hi\n```  \n\n## Owner decisions\n\n{P1}\n\n## Stage 1: s\n")
    rc, out = run("match", "--plan", real, "--at", "preflight")
    expect(rc == 0 and listed(out) == ["OD-1"], "a real fence closed with trailing spaces still closes", out)
    empty = TMP / "empty-plan.md"
    empty.write_text("# Light Plan: x\n\n## Owner decisions\n\n\n## Stage 1: s\n")
    rc, out = run("check", empty)
    expect(rc == 1 and "empty" in out, "S4: check reports an empty section", out)

    # Catches round 4's Important: check on a sub-plan reads the section match inherits.
    vmaster = TMP / "2026-10-26-v-master-plan.md"
    vmaster.write_text("\n".join([
        "# Master Plan: v", "", "## Owner decisions", "",
        f"- **OD-1** — merge — {Q} — applies to: Sub-plan 1 close-out", "a stray line", "",
        "## Sub-plans", "", "### Sub-plan 1: a", "- **Status:** [ ]", "- **Plan:** ./2026-10-26-v-sub-01-a-plan.md", ""]))
    vsub = plan("2026-10-26-v-sub-01-a-plan.md", {1: ["1.1"]}, ["- none — the catalog triggered no question (swept 2026-10-26)"],
                head="# Project Plan: a", extra="Master: ./2026-10-26-v-master-plan.md")
    rc, out = run("match", "--plan", vsub, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "a voided master section gives a sub-plan nothing", out)
    rc, out = run("check", vsub)
    expect(rc == 1 and "2026-10-26-v-master-plan.md" in out, "check on the sub-plan reports its master's voided section", out)

    # S1: a Master: link a comment hides is not followed.
    hmaster = TMP / "2026-10-26-h-master-plan.md"
    hmaster.write_text("\n".join([
        "# Master Plan: h", "", "## Owner decisions", "",
        f"- **OD-1** — merge — {Q} — applies to: Sub-plan 1 close-out", "",
        "## Sub-plans", "", "### Sub-plan 1: a", "- **Status:** [ ]", "- **Plan:** ./2026-10-26-h-sub-01-a-plan.md", ""]))
    hsub = TMP / "2026-10-26-h-sub-01-a-plan.md"
    hsub.write_text("# Project Plan: a\n<!--\nMaster: ./2026-10-26-h-master-plan.md\n-->\n\n## Stage 1: s\n")
    rc, out = run("match", "--plan", hsub, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "S1: a hidden Master: link inherits nothing", out)

    # --- match: what is not an answer ---------------------------------------------

    na = plan("na-plan.md", {1: ["1.1"]}, [
        "- **OD-1** — the merge — ask at execution — applies to: close-out",
        "- **OD-2** — the merge — the author thinks so — applies to: close-out",
        f"- **OD-3** — the merge — {Q} — applies to: the merge",
        f"- **OD-4** — the merge — {Q}",
    ])
    rc, out = run("match", "--plan", na, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "ask-at-execution, unquoted, unplaceable and applies-less entries are refused", out)
    expect("ask at execution" in out and "owner's words" in out and "cannot place: 'merge'" in out
           and "no `applies to:`" in out, "each refusal says why", out)

    none = plan("none-plan.md", {1: ["1.1"]}, None)
    rc, out = run("match", "--plan", none, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "a plan with no section lists nothing and exits 1", out)

    rc, out = run("match", "--plan", TMP / "missing-plan.md", "--at", "closeout")
    expect(rc == 2 and "cannot read" in out, "an unreadable plan exits 2 with the reason", out)
    rc, out = run("match", "--plan", one, "--at", "somewhere")
    expect(rc == 2, "an unknown --at exits 2", out)
    rc, out = run("match", "--plan", one, "--at", "stage")
    expect(rc == 2, "--at stage without --stage is a usage error (exit 2), not an ask", out)

    fenced = plan("fence-plan.md", {1: ["1.1"]}, [
        "```", f"- **OD-1** — merge — {Q} — applies to: close-out", "```",
    ], extra="```\n## Stage 2: in a fence\n```")
    rc, out = run("match", "--plan", fenced, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "an entry inside a code fence is not an entry", out)

    # --- match: a sub-plan reads its master ---------------------------------------

    master = TMP / "2026-10-26-m-master-plan.md"
    master.write_text("\n".join([
        "# Master Plan: m", "Date: 2026-10-26", "",
        "## Owner decisions", "",
        f"- **OD-1** — merge at the end — {Q} — applies to: Sub-plan 3 close-out",
        f"- **OD-2** — branch feat/m — {Q} — applies to: Sub-plan 2 Preflight",
        f"- **OD-3** — bump the version — {Q} — applies to: close-out",
        f"- **OD-4** — run it — {Q} — applies to: Sub-plan 9 Preflight",
        "", "## Sub-plans", "",
        "### Sub-plan 1: a", "- **Status:** [x]", "- **Plan:** ./2026-10-26-m-sub-01-a-plan.md", "",
        "### Sub-plan 2: b", "- **Status:** [ ]", "- **Plan:** ./2026-10-26-m-sub-02-b-plan.md", "",
        "### Sub-plan 3: c", "- **Status:** [ ]", "- **Plan:** ./2026-10-26-m-sub-03-c-plan.md", "",
    ]))
    sub2 = plan("2026-10-26-m-sub-02-b-plan.md", {1: ["1.1"]}, [
        f"- **OD-1** — merge — {Q} — applies to: Sub-plan 2 close-out",
    ], head="# Project Plan: b", extra="Master: ./2026-10-26-m-master-plan.md")
    rc, out = run("match", "--plan", sub2, "--at", "closeout")
    expect(rc == 1 and "Sub-plan 3" in out, "a master entry for Sub-plan 3 does not apply to sub-plan 2", out)
    expect("a master entry that names no Sub-plan" in out, "a master entry naming no Sub-plan does not apply to a sub-plan", out)
    expect("outside a master's section" in out, "a sub-plan's own entry naming a Sub-plan is refused", out)
    rc, out = run("match", "--plan", sub2, "--at", "preflight")
    expect(rc == 0 and listed(out) == ["OD-2"], "a master entry for Sub-plan 2 Preflight applies to it", out)
    rc, out = run("match", "--plan", master, "--at", "closeout")
    expect(rc == 1 and listed(out) == [], "run on the master itself, its entries bind sub-plans, not the master", out)

    # --- check ----------------------------------------------------------------------

    rc, out = run("check", two)
    expect(rc == 1 and "two-plan.md:" in out and "Task 1.3" in out, "check reports a task the plan lacks, with its line", out)
    rc, out = run("check", one)
    expect(rc == 1 and "Stage 2" in out, "check reports the B1 entry", out)
    rc, out = run("check", master)
    expect(rc == 1 and "no Sub-plan 9" in out and "names no Sub-plan" in out,
           "check on a master reports a sub-plan its register lacks and an entry naming none", out)
    stray = plan("stray-plan.md", {1: ["1.1"]}, [
        "- OD-1 — merge — " + Q + " — applies to: close-out",
        "- none — the catalog triggered no question (swept 2026-10-26)",
    ])
    rc, out = run("check", stray)
    expect(rc == 1 and out.count("not an entry line") == 1 and "stray-plan.md:7:" in out,
           "check reports a line that is not an entry; the `none` line is fine", out)
    good = plan("good-plan.md", {1: ["1.1", "1.2"]}, [
        f"- **OD-1** — {MERGE} — {Q} — applies to: close-out (`git merge feat/x`)",
        "- **OD-2** — the remote — ask at execution — applies to: Preflight",
        f"- **OD-3** — run it *(note: Stage 9 mentioned only here)* — {Q} — applies to: Task 1.2",
        f"- **OD-4** — run it — {Q} — applies to: Stage 1 and Task 1.1",
    ])
    rc, out = run("check", good)
    expect(rc == 0, "check passes valid entries; a note before `applies to:` is fine", out)
    rc, out = run("check", none)
    expect(rc == 1 and "no `## Owner decisions` section" in out,
           "check reports a plan with no section: nobody-looked reads differently from nothing-to-ask", out)
    nonep = plan("nonep-plan.md", {1: ["1.1"]}, ["- none — the catalog triggered no question (swept 2026-10-26)"])
    rc, out = run("check", nonep)
    expect(rc == 0, "check passes the `none` line", out)

    # --- the property: check and match agree ----------------------------------------

    # Catches I4 and every false accept the battery holds: an entry check calls clean
    # must be listed at its own place, and one check flags must refuse everywhere.
    battery = [deny, na, cmd, two, good, one, after, quoted, exact]
    cases = [["--at", "preflight"], ["--at", "closeout"]] + [["--at", "stage", "--stage", s] for s in "12"] \
        + [["--at", "stage", "--stage", t.split(".")[0], "--task", t] for t in ("1.1", "1.2", "1.3", "2.1")]
    cmds = [[], ["--command", "git merge feat/x"], ["--command", "./migrate up"], ["--command", "./deploy"],
            ["--command", "git push --force origin x"], ["--command", "git branch -d x"],
            ["--command", 'rm -rf "my  dir"'], ["--command", "rm -rf '*'"], ["--command", "git merge feat/x"]]
    disagree = []
    for p in battery:
        _, cout = run("check", p)
        flagged = {l.split(": ")[1] for l in cout.splitlines() if l.startswith(p.name + ":") and ": OD-" in l}
        ids = {l.split("**")[1] for l in p.read_text().splitlines() if l.startswith("- **OD-")}
        declined = {i for i in ids if f"**{i}** — " in p.read_text() and
                    "ask at execution" in [l for l in p.read_text().splitlines() if f"**{i}**" in l][0]}
        hits = {}
        for c in cases:
            for k in cmds:
                _, out = run("match", "--plan", p, *c, *k)
                for i in listed(out):
                    hits.setdefault(i, []).append(" ".join(c + k))
        for i in sorted(ids):
            if i in flagged and i in hits:
                disagree.append(f"{p.name} {i}: check flags it but match lists it at {hits[i][0]}")
            if i not in flagged and i not in declined and i not in hits:
                disagree.append(f"{p.name} {i}: check passes it but match lists it nowhere")
    expect(not disagree, "check and match agree on every entry of the battery", "\n".join(disagree))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\npassed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
