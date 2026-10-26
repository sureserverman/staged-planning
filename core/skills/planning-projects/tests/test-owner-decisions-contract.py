#!/usr/bin/env python3
"""Structure suite for owner decisions — run directly (CI convention):

    python3 core/skills/planning-projects/tests/test-owner-decisions-contract.py

PROSE contract, not behavior. Planning asks the questions execution would stop for and
records the answers in the plan's `## Owner decisions`; execution reads them before it
asks. What it pins:

  1. references/owner-decisions.md names every bullet of § Safety rails and § Stop
     conditions of every executing-plans trunk (core, and each host override found by
     glob) by its opening words, each classed `ask while planning` or `stays a stop`.
  2. The Standard, Light and master templates carry a `## Owner decisions` section whose
     example bullets are not checkboxes.
  3. The Standard and Light checklists carry the owner-decisions item, and the Light
     list's stated count matches its items, as does every planning-projects trunk.
  4. Every planning-projects trunk carries, under § Phase -1, `### Ask execution's
     questions now`, naming the catalog, the batched round and the record; its
     one-at-a-time rule defers execution questions to that round; its reference map
     routes to the catalog.
  5. Every executing-plans trunk reads the record before it asks (§ Stop conditions),
     takes a destructive command's confirmation from an entry naming it (§ Safety rails);
     every close-out.md copy carries out a recorded merge at step 10; every
     stage-gate.md copy's ACTION NEEDED section checks the record first.
  6. An entry applies only when every qualifier of its `applies to:` holds — stated in
     § Stop conditions and the catalog, cited by close-out step 10 and § ACTION NEEDED;
     `init` runs on the run's branch.

Why: a trunk that gains a stop the catalog does not name is a stop planning never asks
about, and the run halts on it mid-stage.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
PP = os.path.join(SKILLS, "planning-projects")
REF = os.path.join(PP, "references")


def repo_root():
    """The source tree's root when this runs from core/, else None (a built copy)."""
    d = SKILLS
    for _ in range(4):
        d = os.path.dirname(d)
        if os.path.isdir(os.path.join(d, "hosts")) and os.path.isdir(os.path.join(d, "core")):
            return d
    return None


ROOT = repo_root()

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(text, heading):
    """The body under the first heading line equal to `heading`, to the next heading of
    the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    out, inside = [], False
    for line in text.splitlines():
        m = re.match(r"^(#+)\s", line)
        if inside and m and len(m.group(1)) <= level:
            break
        if inside:
            out.append(line)
        elif line.strip() == heading:
            inside = True
    return "\n".join(out)


def trunks(skill):
    """Every trunk of `skill`: the one beside this suite, and each host override."""
    found = [os.path.join(SKILLS, skill, "SKILL.md")]
    if ROOT is not None:
        found += sorted(glob.glob(os.path.join(ROOT, "hosts", "*", "overrides", "skills", skill, "SKILL.md")))
    return [p for p in found if os.path.isfile(p)]


def rel(path):
    return os.path.relpath(path, ROOT) if ROOT else path


def plain(s):
    return re.sub(r"[*`]", "", s).strip()


def opening_words(bullet):
    """A bullet's name: its bold lead when it has one, else its first four words."""
    m = re.match(r"^\*\*(.+?)\*\*", bullet)
    if m:
        return plain(m.group(1)).rstrip(".")
    return " ".join(plain(bullet).split()[:4])


def bullets(body):
    return [line[2:] for line in body.splitlines() if line.startswith("- ")]


def catalog_rows():
    body = section(read(os.path.join(REF, "owner-decisions.md")),
                   "### Where the executor stops: its Safety rails and Stop conditions")
    rows = []
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and line.startswith("|") and not set(cells[0]) <= {"-"}:
            rows.append((plain(cells[0]), cells[1]))
    return rows[1:]   # the header row


def part1_catalog_names_every_stop():
    present = os.path.isfile(os.path.join(REF, "owner-decisions.md"))
    check("1 references/owner-decisions.md exists", present, "missing")
    if not present:
        return
    rows = catalog_rows()
    check("1 the catalog has rows", len(rows) >= 10, f"{len(rows)} rows")
    classes = {c for _, c in rows}
    check("1 every catalog row is classed ask-while-planning or stays-a-stop",
          classes <= {"ask while planning", "stays a stop"}, f"{classes}")
    found = trunks("executing-plans")
    check("1 every executing-plans trunk is found", len(found) >= (4 if ROOT else 1), f"{found}")
    for path in found:
        text = read(path)
        for name in ("## Safety rails", "## Stop conditions"):
            items = bullets(section(text, name))
            check(f"1 {rel(path)} {name} has bullets", len(items) > 0)
            for b in items:
                key = opening_words(b)
                hit = [c for r, c in rows if r.startswith(key)]
                check(f"1 {rel(path)} {name}: the catalog names `{key}`", len(hit) == 1,
                      f"{len(hit)} catalog rows open with it")


def part2_templates_carry_the_section():
    for name in ("plan-document-template.md", "light-plan-format.md", "master-plan-format.md"):
        text = read(os.path.join(REF, name))
        body = section(text, "## Owner decisions")
        check(f"2 {name} carries a `## Owner decisions` section", body.strip() != "", "missing")
        check(f"2 {name}: its example bullets are not checkboxes",
              "**OD-1**" in body and not re.search(r"(?m)^\s*- \[[ x~]\]", body), body[:200])


def part3_checklists_carry_the_item():
    text = read(os.path.join(REF, "authoring-checklist.md"))
    for name in ("## Checklist — Standard plans", "## Checklist — Light plans"):
        body = section(text, name)
        check(f"3 {name} carries the owner-decisions item",
              re.search(r"(?m)^- \[ \] .*`## Owner decisions`", body) is not None, "missing")
    light = section(text, "## Checklist — Light plans")
    words = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13}
    m = re.search(r"verify only\s+these\s+(\w+)", light)
    stated = words.get(m.group(1)) if m else None
    items = len(re.findall(r"(?m)^- \[ \] ", light))
    check("3 the Light list's stated count matches its items", stated == items,
          f"stated {m.group(1) if m else None}, items {items}")
    for path in trunks("planning-projects"):
        m = re.search(r"verify only the (\w+) Light items", read(path))
        check(f"3 {rel(path)} states the same Light count",
              m is not None and words.get(m.group(1)) == items, f"{m.group(1) if m else None} vs {items}")


def part4_planning_asks_the_round():
    found = trunks("planning-projects")
    check("4 every planning-projects trunk is found", len(found) >= (2 if ROOT else 1), f"{found}")
    for path in found:
        text = read(path)
        phase = section(text, "## Phase -1 — Clarification")
        body = section(phase, "### Ask execution's questions now")
        check(f"4 {rel(path)} § Phase -1 carries `### Ask execution's questions now`",
              body.strip() != "", "missing")
        for needle in ("references/owner-decisions.md", "one batched round", "## Owner decisions"):
            check(f"4 {rel(path)}: the section names {needle}", needle in body, "missing")
        how = section(phase, "### How to ask")
        check(f"4 {rel(path)}: the one-at-a-time rule sends execution questions to the round",
              re.search(r"One question at a time[^\n]*\n?[^\n]*Ask execution's questions now", how) is not None,
              how[:200])
        check(f"4 {rel(path)}: the reference map routes to the catalog",
              re.search(r"(?m)^\| `references/owner-decisions\.md` \|", section(text, "## Reference map")) is not None,
              "no row")


def copies(skill, rel_path):
    """`rel_path` under `skill` beside this suite, and each host override of it."""
    found = [os.path.join(SKILLS, skill, rel_path)]
    if ROOT is not None:
        found += sorted(glob.glob(os.path.join(ROOT, "hosts", "*", "overrides", "skills", skill, rel_path)))
    return [p for p in found if os.path.isfile(p)]


def section_starting(text, prefix):
    """The body under the first heading line that starts with `prefix`."""
    for line in text.splitlines():
        if line.startswith(prefix):
            return section(text, line.strip())
    return ""


def part5_execution_reads_the_answers():
    found = trunks("executing-plans")
    for path in found:
        text = read(path)
        stops = " ".join(section(text, "## Stop conditions").split())
        check(f"5 {rel(path)} § Stop conditions reads `## Owner decisions` before asking",
              "## Owner decisions" in stops and "`OD-N`" in stops, "missing")
        for needle in ("A case no entry names stops", "An entry covers only the case it names, never a wider one",
                       "`ask at execution` is no answer"):
            check(f"5 {rel(path)} § Stop conditions keeps the narrow reading: {needle!r}",
                  needle in stops, "missing")
        rails = bullets(section(text, "## Safety rails"))
        for lead, needle in (("**Destructive commands**", "even if the plan (a task, gate check or close-out step) says to"),
                             ("**Destructive commands**", "an owner decision naming that command"),
                             ("**Secrets**", "unless an owner decision names it"),
                             ("**Shared infrastructure**", "an owner decision naming the stage")):
            hit = [b for b in rails if b.startswith(lead)]
            check(f"5 {rel(path)} § Safety rails {lead}: {needle!r}",
                  len(hit) == 1 and needle in hit[0], hit[:1])
        closing = section_starting(text, "## Phase Close-out")
        check(f"5 {rel(path)} § Phase Close-out keeps the merge confirmation",
              "**Do not merge without explicit confirmation**" in closing, closing[:160])
    outs = copies("executing-plans", "references/close-out.md")
    check("5 every close-out.md copy is found", len(outs) >= (4 if ROOT else 1), f"{outs}")
    for path in outs:
        m = re.search(r"(?ms)^10\. (.*?)(?=^\d+\. |^\S|\Z)", read(path))
        step = m.group(1) if m else ""
        check(f"5 {rel(path)} step 10 carries out the recorded merge before offering one",
              step.startswith("Carry out the merge") and "## Owner decisions" in step, step[:160])
        check(f"5 {rel(path)} step 10 keeps the merge confirmation",
              "Do not merge without explicit confirmation" in step, step[-160:])
        # Catches: a recorded branch deletion run before `finish`, which the run's owner
        # (its branch) then refuses — the close-out cannot record itself finished.
        check(f"5 {rel(path)} step 10 runs `plan-state.py finish` before it leaves the run's branch",
              re.search(r"`plan-state\.py finish`[^.]*before[^.]*branch", " ".join(step.split())) is not None,
              step[:200])
    gates = copies("executing-plans", "references/stage-gate.md")
    check("5 every stage-gate.md copy is found", len(gates) >= (4 if ROOT else 1), f"{gates}")
    for path in gates:
        body = section_starting(read(path), "## ACTION NEEDED")
        first = body.strip().split("\n\n")[0] if body.strip() else ""
        check(f"5 {rel(path)} § ACTION NEEDED checks the owner decisions first",
              "## Owner decisions" in first, first[:160])


STRICT = "every qualifier of its `applies to:` holds"


def part6_an_entry_is_never_stretched_to_fit():
    """Catches: an entry scoped to a stage, task or command the case does not match — or
    the plan does not have — read as covering it (a Stage-2 merge entry applied to a
    one-stage plan's merge). Each place an executor matches an entry carries or cites the
    one strict rule; and `init` waits for the run's branch, which owns the run."""
    for path in trunks("executing-plans"):
        text = read(path)
        stops = " ".join(section(text, "## Stop conditions").split())
        check(f"6 {rel(path)} § Stop conditions: an entry applies only when {STRICT}",
              STRICT in stops and "never reinterpret it to fit" in stops, "missing")
        prog = " ".join(section_starting(text, "## Progress state file").split())
        check(f"6 {rel(path)} § Progress state file: `init` runs on the run's branch",
              re.search(r"Call `init` when Preflight starts[^.]*on the run's branch", prog) is not None, prog[:200])
    for path in copies("executing-plans", "references/close-out.md"):
        m = re.search(r"(?ms)^10\. (.*?)(?=^\d+\. |^\S|\Z)", read(path))
        step = " ".join((m.group(1) if m else "").split())
        check(f"6 {rel(path)} step 10 acts only on an entry where {STRICT}", STRICT in step, step[:200])
    for path in copies("executing-plans", "references/stage-gate.md"):
        body = section_starting(read(path), "## ACTION NEEDED")
        first = " ".join((body.strip().split("\n\n")[0] if body.strip() else "").split())
        check(f"6 {rel(path)} § ACTION NEEDED settles only where {STRICT}", STRICT in first, first[:200])
    for path in copies("executing-plans", "references/progress-state-file.md"):
        rows = [l for l in read(path).splitlines() if l.startswith("| Preflight starts") and "| `init` |" in l]
        check(f"6 {rel(path)}: the `init` row runs on the run's branch",
              len(rows) == 1 and "on the run's branch" in rows[0], rows[:1])
    # Not section(): the record's example block holds a `## Owner decisions` line.
    m = re.search(r"(?ms)^## The record\n(.*?)^## How to ask", read(os.path.join(REF, "owner-decisions.md")))
    record = " ".join((m.group(1) if m else "").split())
    check("6 owner-decisions.md § The record: an unmatched qualifier means the entry does not apply",
          STRICT in record and "never reinterpret" in record, "missing")


def main():
    part1_catalog_names_every_stop()
    part2_templates_carry_the_section()
    part3_checklists_carry_the_item()
    part4_planning_asks_the_round()
    part5_execution_reads_the_answers()
    part6_an_entry_is_never_stretched_to_fit()
    if FAILED:
        print(f"\n{len(FAILED)} failure(s)")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
