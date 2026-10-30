#!/usr/bin/env python3
"""Structure suite for the review-cost rules — run directly (CI convention):

    python3 core/skills/executing-plans/tests/test-review-cost-contract.py

PROSE contracts, not behavior: the suite asserts each rule is stated in every copy an
author or executor reads, using the shared negation screening
(test-gate-remediation-contract.py's affirms_claim). What it pins:

  1. `Review: required` is granted by the risk list's paths, never by a word. task-fields.md
     § `Review:` and review-scope.md (core and the Cursor override) say it goes only on a
     task whose `Scope:` names a risk-listed path; no sentence in either grants it for the
     words identity, permission or protocol unless that sentence is negated.
  2. A re-review after a Critical fix covers the fix diff only, and Tier-1's Important
     findings are carried to the gate as advisory. Stated in task-execution.md § Tier 1 and
     stage-gate.md, every copy. The rest of the class — every place that re-dispatches a
     review after a Critical fix (SKILL.md's Tier-1 rule, close-out.md's Tier-2 step) —
     scopes that re-dispatch to the fix diff, so no copy still orders a fresh full review.
  3. After a repair, only the drifted records are re-proved. § If the gate fails in
     stage-gate.md, every copy, says to re-prove the drifted records only — the tasks whose
     touched or witness files the repair changed, as Sub-plan 1's per-file binding reports
     them — never every task of the stage.
  4. Below `high`, the gate evaluator is skipped when a recorded command decides the goal.
     stage-gate.md, every copy, holds § Skipped when a recorded command decides the goal:
     the rule, the report line (`evaluator: skipped — goal command`) and demo.md's
     `Decided by:` form. The statements of when the gate evaluator runs carry the
     exception, each pinned: stage-gate.md's opening line, closed-at-two list, "tier's
     call" sentence and demo stand-in paragraph (four pointers outside the subsection);
     SKILL.md's evaluator paragraph and its gate-report reasons bullet (four reasons);
     review-scope.md's two tables; light-plans.md item 4; plan-document-template.md's
     evaluator comment; README.md's standard row (core and the Cursor override). Every
     copy of each. A new statement elsewhere is not found by this suite.

The failure it guards against: an author who reads "touches something risky" as "mentions
something risky" marks 8 of 17 tasks `Review: required` in one master, and each buys a
Tier-1 review plus a re-review the stage's Tier-2 pass would have covered anyway.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(os.path.dirname(SKILLS))
TASKFIELDS = os.path.join(SKILLS, "planning-projects", "references", "task-fields.md")
REVIEWSCOPE = "skills/executing-plans/references/review-scope.md"
TASKEXEC = "skills/executing-plans/references/task-execution.md"
STAGEGATE = "skills/executing-plans/references/stage-gate.md"
TRUNK = "skills/executing-plans/SKILL.md"
CLOSEOUT = "skills/executing-plans/references/close-out.md"
HELPER = os.path.join(HERE, "test-gate-remediation-contract.py")

spec = importlib.util.spec_from_file_location("_gate_contract", HELPER)
_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_helper)
affirms_claim = _helper.affirms_claim
NEGATION_RE = _helper.NEGATION_RE


def affirms_phrase(hay, target_pat):
    """affirms_claim, with the matched phrase itself blanked before the screen.

    For a rule whose own words are on the negation list: "Important findings are carried
    to the gate as advisory" names `advisory` as its subject, and affirms_claim reads that
    word as the clause withdrawing itself. Everything else in the clause is still screened.
    """
    for m in re.finditer(target_pat, hay, re.I | re.S):
        starts = [b.end() for b in _helper.CLAUSE_START.finditer(hay[:m.start()])]
        after = _helper.SENTENCE_END.search(hay, m.end())
        lo = starts[-1] if starts else 0
        span = hay[lo:m.start()] + " " + hay[m.end():(after.start() if after else len(hay))]
        if not NEGATION_RE.search(re.sub(r"`[^`]*`", " ", span)):
            return True
    return False

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def ws(pattern):
    """Every space may be any whitespace run: the references are hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(text, start_pat, end_pat):
    m = re.search(start_pat, text, re.M)
    if not m:
        return ""
    rest = text[m.start():]
    e = re.search(end_pat, rest[1:], re.M)
    return rest[: e.start() + 1] if e else rest


def copies(rel):
    """The core file under core/ and every host override of it, as (label, path)."""
    out = [("core/" + rel, os.path.join(REPO, "core", rel))]
    hosts = os.path.join(REPO, "hosts")
    for host in sorted(os.listdir(hosts)):
        p = os.path.join(hosts, host, "overrides", rel)
        if os.path.isfile(p):
            out.append((f"hosts/{host}/overrides/{rel}", p))
    return out


def sentences(text):
    """Sentences, with a table row, list item or heading also ending one."""
    text = re.sub(r"\n(?=[ \t]*(?:[-*+|] |\d+\. |#|```|>))", ".\n", text)
    return re.split(r"(?<=[.;])\s+", text)


FIX_DIFF_ONLY = ws(r"re-review after a Critical fix covers the fix diff only")
IMPORTANT_TO_GATE = ws(r"Important findings are carried to the gate as advisory")
REDISPATCH_SCOPED = r"re-(?:dispatch|spawn)(?: the review)?\s+over\s+the\s+fix\s+diff\s+only"
REPROVE_DRIFTED = ws(r"re-prove the drifted records only")
SKIP_HEAD = r"^### Skipped when a recorded command decides the goal\s*$"
SKIP_RULE = ws(r"the gate evaluator is skipped at a gate whose `\(goal\)` check is a command "
               r"the executor ran green and recorded")
SKIP_EXCEPTION = ws(r"unless a recorded goal command decides it")
LIGHTPLANS = "skills/executing-plans/references/light-plans.md"
GRANT_BY_PATH = ws(r"only on a task whose `Scope:` names a risk-listed path")
KEYWORD = re.compile(r"\b(?:identity|permissions?|protocols?)\b", re.I)


def keyword_grants(text):
    """Sentences naming `Review: required` and a keyword, with no negation in them."""
    bad = []
    for s in sentences(text):
        if "Review: required" in s and KEYWORD.search(s) \
                and not NEGATION_RE.search(re.sub(r"`[^`]*`", " ", s)):
            bad.append(" ".join(s.split())[:120])
    return bad


def main():
    # --- 1. `Review: required` follows the risk list, not keywords ----------------------
    review = section(read(TASKFIELDS), r"^### `Review:`", r"^### ")
    check("task-fields: § `Review:` located", bool(review))
    check("task-fields: `Review: required` only on a task whose Scope names a risk-listed path",
          affirms_claim(review, GRANT_BY_PATH),
          "no non-negated 'only on a task whose `Scope:` names a risk-listed path'")
    bad = keyword_grants(review)
    check("task-fields: no sentence grants `Review: required` by keyword", not bad,
          "; ".join(bad))
    for label, path in copies(REVIEWSCOPE):
        text = read(path)
        check(f"{label}: `Review: required` only on a task whose Scope names a risk-listed path",
              affirms_claim(text, GRANT_BY_PATH),
              "no non-negated 'only on a task whose `Scope:` names a risk-listed path'")
        bad = keyword_grants(text)
        check(f"{label}: no sentence grants `Review: required` by keyword", not bad,
              "; ".join(bad))

    # --- 2. re-review the fix diff only; Important waits for the gate -------------------
    for rel in (TASKEXEC, STAGEGATE):
        for label, path in copies(rel):
            text = read(path)
            check(f"{label}: the re-review after a Critical fix covers the fix diff only",
                  affirms_claim(text, FIX_DIFF_ONLY),
                  "no non-negated 're-review after a Critical fix covers the fix diff only'")
            check(f"{label}: Important findings are carried to the gate as advisory",
                  affirms_phrase(text, IMPORTANT_TO_GATE),
                  "no non-negated 'Important findings are carried to the gate as advisory'")
    tier1 = re.compile(r"\*\*Critical → blocking\.\*\*.*?(?=\n- \*\*)", re.S)
    for label, path in copies(TASKEXEC):
        m = tier1.search(read(path))
        check(f"{label}: the Tier-1 Critical bullet re-dispatches over the fix diff only",
              bool(m) and re.search(REDISPATCH_SCOPED, m.group(0)) is not None,
              "the Critical bullet re-dispatches the review without scoping it to the fix diff")
    for label, path in copies(TRUNK):
        rule6 = section(read(path), r"^6\. \*\*Quick review gate", r"^7\. ")
        check(f"{label}: rule 6 re-dispatches over the fix diff only",
              bool(rule6) and re.search(REDISPATCH_SCOPED, rule6) is not None,
              "rule 6's Critical re-dispatch is not scoped to the fix diff")
    for label, path in copies(CLOSEOUT):
        step = section(read(path), r"^2a\. ", r"\n(?=\S)")
        check(f"{label}: step 2a re-dispatches over the fix diff only",
              bool(step) and re.search(REDISPATCH_SCOPED, step) is not None,
              "step 2a's Critical re-dispatch is not scoped to the fix diff")

    # --- 3. after a repair, re-prove the drifted records only ---------------------------
    for label, path in copies(STAGEGATE):
        fails = section(read(path), r"^## If the gate fails", r"^## ")
        check(f"{label}: § If the gate fails says to re-prove the drifted records only",
              bool(fails) and affirms_claim(fails, REPROVE_DRIFTED),
              "no non-negated 're-prove the drifted records only' in § If the gate fails")

    # --- 4. the gate evaluator is skipped when a recorded command decides the goal -------
    for label, path in copies(STAGEGATE):
        sub = section(read(path), SKIP_HEAD, r"^#{1,3} (?!Skipped when)")
        check(f"{label}: holds § Skipped when a recorded command decides the goal", bool(sub),
              "no '### Skipped when a recorded command decides the goal' heading")
        check(f"{label}: states the skip rule", affirms_claim(sub, SKIP_RULE),
              "no non-negated 'the gate evaluator is skipped at a gate whose `(goal)` check is "
              "a command the executor ran green and recorded'")
        for token in ("evaluator: skipped — goal command", "Decided by:",
                      "an excuse word does not excuse a mandated evaluator"):
            check(f"{label}: the skip subsection names `{token}`", token in " ".join(sub.split()),
                  f"'{token}' missing from the subsection")
    for label, path in copies(STAGEGATE):
        text = read(path)
        sub = section(text, SKIP_HEAD, r"^#{1,3} (?!Skipped when)")
        n = len(re.findall(ws(r"§ Skipped when a recorded command decides the goal"),
                           text.replace(sub, "")))
        check(f"{label}: four statements outside the subsection point to it", n >= 4,
              f"{n} pointer(s) to § Skipped when a recorded command decides the goal")
    for label, path in copies(TRUNK):
        bullet = re.search(r"^- \*\*The gate report names every review that ran.*$", read(path), re.M)
        check(f"{label}: the gate-report bullet lists the skip as a fourth reason",
              bool(bullet) and "**four** reasons" in bullet.group(0)
              and "Skipped when a recorded command decides the goal" in bullet.group(0),
              "the bullet does not name four reasons with the skip pointer")
    for label, path in (copies("skills/planning-projects/references/plan-document-template.md")
                        + [("core/README.md", os.path.join(REPO, "core", "README.md"))]
                        + [(lbl, pth) for lbl, pth in
                           [("hosts/cursor/overrides/README.md",
                             os.path.join(REPO, "hosts", "cursor", "overrides", "README.md"))]
                           if os.path.isfile(pth)]):
        check(f"{label}: its evaluator statement carries the skip exception",
              re.search(SKIP_EXCEPTION, read(path)) is not None,
              "no 'unless a recorded goal command decides it'")
    for label, path in copies(TRUNK):
        para = section(read(path), r"^\*\*Independent evaluator for non-command checks\.\*\*",
                       r"^\*\*(?!Independent)")
        check(f"{label}: the evaluator paragraph carries the skip exception",
              bool(para) and re.search(SKIP_EXCEPTION, para) is not None,
              "no 'unless a recorded goal command decides it' in the evaluator paragraph")
    for label, path in copies(REVIEWSCOPE):
        rows = [ln for ln in read(path).splitlines()
                if re.match(r"^\| (?:\*\*light\*\*|\*\*standard\*\*|`light`|`standard`) \|", ln)]
        check(f"{label}: both tables' light and standard rows carry the skip exception",
              len(rows) == 4 and all(re.search(SKIP_EXCEPTION, r) for r in rows),
              f"{len(rows)} rows, {sum(bool(re.search(SKIP_EXCEPTION, r)) for r in rows)} with it")
    for label, path in copies(LIGHTPLANS):
        item = section(read(path), r"^4\. \*\*The evaluator follows the tier", r"^5\. ")
        check(f"{label}: item 4 carries the skip exception",
              bool(item) and re.search(SKIP_EXCEPTION, item) is not None,
              "no 'unless a recorded goal command decides it' in item 4")

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed:")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
