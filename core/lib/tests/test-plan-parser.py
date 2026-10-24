#!/usr/bin/env python3
"""Fixture tests for core/lib/plan_parser.py, the one plan-format contract.

Every fixture is written inline below and is synthetic: nothing is read from a plans
folder, a project or a register. The cases lock the format invariants the reference describes
(core/skills/planning-projects/references/plan-parser.md):

  (a) a master plan yields ZERO candidates (the parser-safety invariant)
  (b) an in-progress Status-field plan yields one candidate per `Status: [ ]` task;
      its raw body bullets are not candidates
  (c) a completed plan yields zero candidates
  (d) a legacy (pre-Status) plan keeps its heuristic candidates
  (e) gate bullets, Preflight bullets and `Decisions in force` bullets never surface
  (f) a stray `- [ ]` inside a done task is suppressed
  (g) Deferred bullets surface on both paths
  (h) a Light plan is parser-safe by construction
  (i) `[~]` is partial: it counts toward total and never toward done
  (j) abandonment is a structured marker; banner prose is advisory only
  plus the gate-checkbox contract, blocked acceptance and its propagation to a master,
  the out-of-contract warnings, and the module's import-time purity.

No pytest dependency: plain checks, non-zero exit on any failure.

Run:  python3 core/lib/tests/test-plan-parser.py
"""
from __future__ import annotations

import datetime
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "plan_parser.py"

spec = importlib.util.spec_from_file_location("plan_parser", LIB)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
parse_plan = mod.parse_plan

failures = []
TODAY_ = datetime.date(2026, 7, 25)   # fixed 'today' so date assertions never drift


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        failures.append(name)
        print(f"FAIL  {name}  {detail}")


# ---------------------------------------------------------------------------
# Synthetic fixtures. Keyed by the file name they would carry in a plans/ folder,
# because a candidate's Source locator embeds that name.
# ---------------------------------------------------------------------------
F = {}

F["2020-01-01-stale-legacy-plan.md"] = """\
# Project Plan: Stale legacy plan
Date: 2020-01-01

## Stage 1: Only stage

### Task 1.1: First task
- [ ] Update documentation and changelog before the release ships to the stable channel
- [ ] Something clearly distinct

### Task 1.2: Second task
- [ ] Update documentation and changelog before the release ships to the beta channel

### Stage 1 Gate
- [ ] gate bullets must never surface
"""

F["2026-05-01-legacy-single-plan.md"] = """\
# Project Plan: Legacy single plan (pre-Status format)
Date: 2026-05-01

## Preflight

- [ ] PREFLIGHT-MARKER: tools installed

## Stage 1: Old-style work

### Task 1.1: Ship the widget
- [x] build the widget
- [ ] LEGACY-CANDIDATE-A: document the widget

### Stage 1 Gate
- [ ] GATE-MARKER-LEGACY: suite passes

## Deferred

- LEGACY-DEFERRED-A: widget telemetry
- [ ] LEGACY-DEFERRED-B: widget dark mode
"""

F["2026-05-02-decisions-legacy-plan.md"] = """\
# Project Plan: Legacy plan with a decisions section
Date: 2026-05-02

Legacy shape on purpose: NO `- **Status:**` fields anywhere, so this file takes the
heuristic path in parse_plan, where a stray checkbox inside `## Decisions in force`
would otherwise become a false candidate.

## Decisions in force

- DEC-NNN — LEGACYDEC-PROSE-MARKER well-formed non-checkbox bullet (accepted; security)
- [ ] LEGACYDEC-CHECKBOX-MARKER a checkbox smuggled into the decisions section

## Stage 1: Work

- [ ] LEGACY-REAL-MARKER a genuine unchecked item outside any excluded section

### Stage 1 Gate
- [ ] LEGACYGATE-MARKER gate bullets are excluded as always
"""

F["2026-07-04-widget-master-plan.md"] = """\
# Master Plan: Widget rollout
Date: 2026-07-04

## Research Summary

Shared findings for both sub-plans: the API contract is v2, the client pins it.

## Sub-plans

### Sub-plan 1: API service
- **Status:** [x]
- **Plan:** ./2026-07-04-widget-sub-01-api-plan.md
- **Goal:** The v2 API serves the new contract end-to-end.
- **Depends on:** none
- **Blocks:** Sub-plan 2
- **Parallel:** YES

**Gate:**
- [ ] MASTER-GATE-MARKER-A: contract tests pass against the deployed API
- [ ] MASTER-GATE-MARKER-B: no regressions in v1 endpoints

### Sub-plan 2: Client migration
- **Status:** [ ]
- **Plan:** ./2026-07-04-widget-sub-02-client-plan.md
- **Goal:** The client consumes v2 exclusively.
- **Depends on:** Sub-plan 1
- **Blocks:** none
- **Parallel:** NO (blocked by Sub-plan 1)

**Gate:**
- [ ] MASTER-GATE-MARKER-C: end-to-end flow green across API + client
"""

F["2026-07-04-widget-sub-01-api-plan.md"] = """\
# Project Plan: Widget API service
Date: 2026-07-04
Master: ./2026-07-04-widget-master-plan.md

## Research Summary

Scoped to the API sub-plan.

## Preflight

- [ ] PREFLIGHT-MARKER: toolchain installed

---

## Stage 1: Contract

**Goal:** v2 contract implemented.
**Depends on:** none
**Blocks:** none
**Risk:** LOW — prior art.
**Rollback:** revert commits.

### Task 1.1: Implement v2 endpoint
- **Status:** [x]
- **Depends on:** none
- **Blocks:** Task 1.2
- **Parallel:** YES
- **Test:** `pytest tests/test_v2.py`
- **Red-Green max cycles:** 3
- [x] scaffold the handler
- [x] wire the router
- [ ] STRAY-LEFTOVER: forgotten body bullet in a DONE task — Status [x] must suppress it

### Task 1.2: Harden the endpoint
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Blocks:** none
- **Parallel:** NO (blocked by 1.1)
- **Test:** `pytest tests/test_v2_hardening.py`
- **Red-Green max cycles:** 3
- [ ] SUB1-CANDIDATE-A: add retry logic to the upload handler
- [ ] SUB1-CANDIDATE-B: rate-limit the v2 endpoint

### Stage 1 Gate
- [ ] GATE-MARKER-SUB1: full suite passes

## Deferred

- SUB1-DEFERRED-A: telemetry for the retry path
"""

F["2026-07-04-widget-sub-02-client-plan.md"] = """\
# Project Plan: Widget client migration
Date: 2026-07-04
Master: ./2026-07-04-widget-master-plan.md

## Preflight

- [ ] PREFLIGHT-MARKER: client toolchain installed

---

## Stage 1: Migrate calls

### Task 1.1: Swap client to v2
- **Status:** [x]
- **Test:** `npm test`
- [x] point client at v2
- [x] delete v1 shims

### Stage 1 Gate
- [x] GATE-MARKER-SUB2: e2e suite passes

**Completed:** 2026-07-04 — commits: abc1234
"""

F["2026-07-05-status-edge-cases-plan.md"] = """\
# Project Plan: Status-path edge cases
Date: 2026-07-05

A task with no enclosing Stage header (bare `Task N.N` locator) and a malformed task
carrying two Status lines (exactly one candidate).

### Task 0.1: EDGE-NOSTAGE: task before any stage header
- **Status:** [ ]
- **Test:** `true`

## Stage 1: Real stage

### Task 1.1: EDGE-DOUBLE: malformed task with two Status lines
- **Status:** [ ]
- **Status:** [ ]
- **Test:** `true`
"""

F["2026-07-14-light-completed-plan.md"] = """\
# Light Plan: Completed light plan fixture
Date: 2026-07-14

**Context:** every task `[x]` and a close-out line present.

## Stage 1: Light lane

### Task 1.1: Author the reference doc
- **Status:** [x]
- **Test:** `true`

### Task 1.2: Add the parser fixture
- **Status:** [x]
- **Depends on:** Task 1.1
- **Test:** `true`

### Stage 1 Gate
- [ ] LIGHT-DONE-GATE: integration check, excluded by the parser
- [ ] Full existing test suite passes

**Completed:** 2026-07-14 — commits: abc1234, def5678
"""

F["2026-07-14-light-inprogress-plan.md"] = """\
# Light Plan: In-progress light plan fixture
Date: 2026-07-14

**Context:** one candidate per `[ ]` task, gate bullets excluded, a stray bullet in a
done task suppressed, and Deferred bullets still surfacing.

## Stage 1: Light lane

### Task 1.1: Author the reference doc
- **Status:** [x]
- **Test:** `true`
- [ ] LIGHT-STRAY: leftover raw bullet inside a DONE task — must be suppressed

### Task 1.2: Add the parser fixture
- **Status:** [ ]
- **Depends on:** Task 1.1
- **Test:** `true`

### Task 1.3: Bump the version
- **Status:** [ ]
- **Depends on:** Task 1.2
- **Test:** `true`
- **Red-Green max cycles:** 3

### Stage 1 Gate
- [ ] LIGHT-GATE-MARKER: integration check that must never surface as a candidate
- [ ] Full existing test suite passes

## Deferred

- LIGHT-DEFERRED-A: badge for light plans
"""

F["2026-07-24-abandoned-plan.md"] = """\
# Project Plan: Abandoned work
Date: 2026-07-24

**Abandoned:** 2026-07-20 — superseded by the widget rewrite

## Stage 1: Never finished

### Task 1.1: ABANDONED-A: open task inside an abandoned plan
- **Status:** [ ]
- **Test:** `true`
"""

F["2026-07-24-all-partial-plan.md"] = """\
# Project Plan: Every task partial
Date: 2026-07-24

Every task here is `[~]`, so the authoritative-path detection class must contain `~`.

## Stage 1: Only partial tasks

### Task 1.1: ALLPARTIAL-A: in flight
- **Status:** [~]
- **Test:** `true`

### Stage 1 Gate
- [ ] ALLPARTIAL-GATE-MARKER: must never surface as a candidate
"""

F["2026-07-24-banner-only-plan.md"] = """\
# Project Plan: Banner prose, no marker
Date: 2026-07-24

OBSOLETE — DO NOT IMPLEMENT

Prose banner with NO `**Abandoned:**` marker: an advisory only, never suppressed.

## Stage 1: Still live as far as the parser is concerned

### Task 1.1: BANNER-A: open task under a banner
- **Status:** [ ]
- **Test:** `true`
"""

F["2026-07-24-partial-status-plan.md"] = """\
# Project Plan: Partial-status contract
Date: 2026-07-24

All three Status characters in one plan: `[x]` emits nothing, `[ ]` emits
`status-unexecuted`, `[~]` emits `status-partial`.

## Stage 1: Mixed states

### Task 1.1: PARTIAL-DONE: finished task
- **Status:** [x]
- **Test:** `true`

### Task 1.2: PARTIAL-OPEN: never started
- **Status:** [ ]
- **Test:** `true`

### Task 1.3: PARTIAL-INFLIGHT: started but unfinished
- **Status:** [~]
- **Test:** `true`

### Stage 1 Gate
- [ ] PARTIAL-GATE-MARKER: must never surface as a candidate
"""

F["2026-07-25-decisions-light-plan.md"] = """\
# Light Plan: Decisions Context Line Parser Safety
Date: 2026-07-25
Format: Light — single stage, 2 tasks, one session

**Context:** a Light plan carries decisions inline. DEC-NNN binds this —
LIGHTCTX-MARKER constraint stated in half a line.

## Stage 1: Only stage

### Task 1.1: LIGHT-CANDIDATE-MARKER first task
- **Status:** [ ]
- **Test:** `true`

### Task 1.2: LIGHT-DONE-MARKER second task
- **Status:** [x]
- **Test:** `true`

### Stage 1 Gate
- [ ] LIGHTGATE-MARKER goal proven end-to-end
- [ ] Full existing test suite passes (regressions check)
- [ ] No change contradicts a decision in force (DEC-NNN)
"""

F["2026-07-25-decisions-master-plan.md"] = """\
# Master Plan: Decisions Section at Master Level
Date: 2026-07-25

## Decisions in force

- DEC-NNN — MASTERDEC-MARKER entry (accepted; security) — constraint in one line
- DEC-NNN — MASTERDEC-MARKER listed-register entry (accepted; security; from a resolver-listed register) — constraint in one line

## Sub-plans

### Sub-plan 1: First
- **Status:** [ ]
- **Plan:** ./2026-07-25-decisions-standard-plan.md
- **Goal:** fixture entry

**Gate:**
- [ ] MASTERDECGATE-MARKER integration check

### Sub-plan 2: Second
- **Status:** [ ]
- **Plan:** ./2026-07-25-decisions-light-plan.md
- **Goal:** fixture entry

**Gate:**
- [ ] MASTERDECGATE-MARKER cross-plan check
"""

F["2026-07-25-decisions-standard-plan.md"] = """\
# Project Plan: Decisions Section Parser Safety (Standard)
Date: 2026-07-25

## Decisions in force

- DEC-NNN — DECISIONS-SECTION-MARKER project entry (accepted; security) — one line
- DEC-NNN — DECISIONS-SECTION-MARKER listed-register entry (accepted; security; from a resolver-listed register) — one line
- none — no further entry binds this scope

## Preflight

- [ ] PREFLIGHT-MARKER baseline suite passes

---

## Stage 1: Only real task

### Task 1.1: REAL-CANDIDATE-MARKER the one deferred task
- **Status:** [ ]
- **Test:** `true`

### Stage 1 Gate
- [ ] GATE-MARKER integration check
- [ ] No change contradicts a decision in force (DEC-NNN); any Supersedes citation recorded
"""

F["sample-architecture.md"] = """\
# Architecture: Sync CLI
Date: 2026-07-04
Status: Approved 2026-07-04

An architecture document, authored to the architecting-projects Document format.
It exercises the risky shapes (plain-bullet lists, a fenced directory tree,
Risks/Alternatives sections), none of them parseable as deferred work.

## Decision

Hexagonal core with adapter crates. The sync engine lives in a pure `core` crate;
remote and filesystem access are ports implemented by adapter crates.

## Alternatives rejected

- Single-crate layered: cheapest start, but the remote client leaks into engine tests.
- Workspace-per-feature: over-modular for a two-port tool.

## ARCH-01 Directory layout

```
sync-cli/
├── core/                 (domain: diff, plan, apply — no I/O deps)
├── adapters/
│   ├── remote/src/lib.rs
│   └── localfs/src/lib.rs
└── cli/src/main.rs
```

## ARCH-02 Module boundaries

- core: owns `SyncPlan` and the diff algorithm; depends on nothing above std.
- adapters/remote: implements `RemoteStore`; talks to core only via that trait.

## Risks

- The remote client is young: mitigation — it sits behind `RemoteStore`, swappable.
"""

F["unstamped-legacy-plan.md"] = """\
# Project Plan: Unstamped legacy plan

## Stage 1: Only stage

### Task 1.1: A task
- [ ] unstamped unresolved item
"""


def candidates(fname, done_stages=frozenset()):
    return parse_plan(F[fname], f"plans/{fname}", set(done_stages))


def by_signal(cands):
    out = {}
    for c in cands:
        out.setdefault(c["signal"], []).append(c)
    return out


# --- import-time purity ------------------------------------------------------
print("module purity:")
probe = subprocess.run(
    [sys.executable, "-I", "-c",
     "import importlib.util, sys\n"
     f"s = importlib.util.spec_from_file_location('p', {str(LIB)!r})\n"
     "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
     "bad = [n for n in ('yaml', 'subprocess') if n in sys.modules]\n"
     "print('LOADED:' + ','.join(bad))\n"],
    capture_output=True, text=True, timeout=60)
check("importing the lib loads neither PyYAML nor subprocess",
      probe.returncode == 0 and probe.stdout.strip() == "LOADED:",
      f"rc={probe.returncode} out={probe.stdout!r} err={probe.stderr[-300:]!r}")

# --- `## Decisions in force` never manufactures candidates --------------------
print("decisions sections:")
dec_std = candidates("2026-07-25-decisions-standard-plan.md")
check("Standard: decisions section yields no candidates",
      not any("DECISIONS-SECTION-MARKER" in c["title"] for c in dec_std),
      f"got: {[c['title'] for c in dec_std]}")
check("Standard: exactly the one real unchecked task survives",
      [c["title"] for c in dec_std] == ["REAL-CANDIDATE-MARKER the one deferred task"],
      f"got: {[c['title'] for c in dec_std]}")
dec_light = candidates("2026-07-25-decisions-light-plan.md")
check("Light: Context-line decision yields no candidate",
      not any("LIGHTCTX-MARKER" in c["title"] for c in dec_light))
check("Light: only the unchecked task survives",
      [c["title"] for c in dec_light] == ["LIGHT-CANDIDATE-MARKER first task"],
      f"got: {[c['title'] for c in dec_light]}")
# Falsifiable: this one breaks the non-checkbox convention on the legacy path, where
# the exclusion (not the format) is what keeps the checkbox out.
legacy_dec = [c["title"] for c in candidates("2026-05-02-decisions-legacy-plan.md")]
check("legacy path: a checkbox smuggled into `Decisions in force` is EXCLUDED",
      not any("LEGACYDEC-CHECKBOX-MARKER" in x for x in legacy_dec), f"got: {legacy_dec}")
check("legacy path: the prose decision bullet never surfaces either",
      not any("LEGACYDEC-PROSE-MARKER" in x for x in legacy_dec), f"got: {legacy_dec}")
check("legacy path: a genuine unchecked item OUTSIDE the section still surfaces",
      any("LEGACY-REAL-MARKER" in x for x in legacy_dec), f"got: {legacy_dec}")
check("master with a decisions section still yields zero candidates",
      candidates("2026-07-25-decisions-master-plan.md") == [])

# --- (a) + (e) the parser-safety invariant: a master yields zero candidates ---
print("master plans:")
master = candidates("2026-07-04-widget-master-plan.md")
check("master yields zero candidates", master == [], f"got: {master}")
check("master yields zero candidates even with every stage git-confirmed done",
      candidates("2026-07-04-widget-master-plan.md", {1, 2}) == [])
check("master yields zero candidates under the legacy heuristic too "
      "(its Status fields removed)",
      parse_plan(F["2026-07-04-widget-master-plan.md"].replace("- **Status:** [x]\n", "")
                 .replace("- **Status:** [ ]\n", ""), "plans/m.md", set()) == [])
check("master detected by filename suffix",
      mod.is_master_plan("# Plan: x\n", "plans/x-master-plan.md"))
check("master detected by its first heading",
      mod.is_master_plan("# Master Plan: x\n", "plans/x-plan.md"))
check("an ordinary plan is not a master",
      not mod.is_master_plan(F["2026-07-24-partial-status-plan.md"], "plans/p-plan.md"))
regs = [m.groups() for m in map(mod.SUBPLAN_RE.match,
                                F["2026-07-04-widget-master-plan.md"].splitlines()) if m]
check("SUBPLAN_RE reads the register headings",
      regs == [("1", "API service"), ("2", "Client migration")], f"got: {regs}")
check("SUBPLAN_RE reads a zero-padded, em-dash register heading",
      mod.SUBPLAN_RE.match("### Sub-plan 01 — maintenance lane").groups()
      == ("1", "maintenance lane"))
links = mod.SUBPLAN_LINK_RE.findall(F["2026-07-04-widget-master-plan.md"])
check("SUBPLAN_LINK_RE reads both register links",
      [mod.link_target(x) for x in links]
      == ["./2026-07-04-widget-sub-01-api-plan.md", "./2026-07-04-widget-sub-02-client-plan.md"],
      f"got: {links}")
check("link_target reads the markdown-link form",
      mod.link_target("[a-plan.md](./a-plan.md)") == "./a-plan.md")
back = mod.MASTER_BACKLINK_RE.search(F["2026-07-04-widget-sub-01-api-plan.md"])
check("MASTER_BACKLINK_RE reads a sub-plan's backlink",
      back and mod.link_target(back.group(1)) == "./2026-07-04-widget-master-plan.md")
check("link_target returns None for nothing usable",
      mod.link_target("   ") is None and mod.link_target(None) is None)

# --- light detection ----------------------------------------------------------
print("light plans:")
check("light detected by filename suffix",
      mod.is_light_plan("# Project Plan: x\n", "plans/x-light-plan.md"))
check("light detected by its first heading",
      mod.is_light_plan(F["2026-07-14-light-inprogress-plan.md"], "plans/x-plan.md"))
check("a Standard plan is not light",
      not mod.is_light_plan(F["2026-07-24-partial-status-plan.md"], "plans/p-plan.md"))
check("a master is not light",
      not mod.is_light_plan(F["2026-07-04-widget-master-plan.md"],
                            "plans/2026-07-04-widget-master-plan.md"))

# --- (b) + (f) + (g) in-progress Status-field plan ----------------------------
print("Status-authoritative path:")
sub1 = candidates("2026-07-04-widget-sub-01-api-plan.md")
s1 = by_signal(sub1)
check("status plan: one status-unexecuted candidate per undone task",
      [c["title"] for c in s1.get("status-unexecuted", [])] == ["Harden the endpoint"],
      f"got: {sub1}")
check("status-unexecuted source locator is Stage N / Task N.N",
      s1.get("status-unexecuted", [{}])[0].get("source")
      == "plans/2026-07-04-widget-sub-01-api-plan.md — Stage 1 / Task 1.2")
titles = {c["title"] for c in sub1}
check("stray bullet in DONE task suppressed; body bullets not separate candidates",
      not any("STRAY-LEFTOVER" in t or "SUB1-CANDIDATE" in t for t in titles),
      f"got: {sorted(titles)}")
check("preflight/gate bullets excluded",
      not any("PREFLIGHT-MARKER" in t or "GATE-MARKER" in t for t in titles))
check("Deferred bullets still surface from a Status-authoritative plan",
      [c["title"] for c in s1.get("deferred-section", [])]
      == ["SUB1-DEFERRED-A: telemetry for the retry path"])
check("status plan emits nothing beyond status-unexecuted + deferred-section",
      set(s1) == {"status-unexecuted", "deferred-section"}, f"got: {set(s1)}")
check("the Status path ignores git stage evidence",
      candidates("2026-07-04-widget-sub-01-api-plan.md", {1}) == sub1)

# --- (c) completed plan -------------------------------------------------------
check("completed sub-plan yields zero candidates",
      candidates("2026-07-04-widget-sub-02-client-plan.md") == [])

# --- (d) legacy plan ----------------------------------------------------------
print("legacy heuristic path:")
legacy = candidates("2026-05-01-legacy-single-plan.md")
check("legacy plan candidates unchanged",
      {c["title"] for c in legacy} == {"LEGACY-CANDIDATE-A: document the widget",
                                      "LEGACY-DEFERRED-A: widget telemetry",
                                      "LEGACY-DEFERRED-B: widget dark mode"},
      f"got: {sorted(c['title'] for c in legacy)}")
check("legacy plan uses both heuristic signals",
      {c["signal"] for c in legacy} == {"unchecked-open", "deferred-section"})
check("legacy unchecked locator names its stage and a snippet",
      [c["source"] for c in legacy if c["signal"] == "unchecked-open"]
      == ["plans/2026-05-01-legacy-single-plan.md — Stage 1 / unchecked: "
          "LEGACY-CANDIDATE-A: document the widget"])
check("a git-confirmed-done stage suppresses its legacy candidates, not Deferred",
      {c["signal"] for c in candidates("2026-05-01-legacy-single-plan.md", {1})}
      == {"deferred-section"})
stale = candidates("2020-01-01-stale-legacy-plan.md")
check("legacy gate bullets never surface", len(stale) == 3
      and not any("gate bullets" in c["title"] for c in stale), f"got: {stale}")

# --- edge cases on the authoritative path --------------------------------------
edges = candidates("2026-07-05-status-edge-cases-plan.md")
check("no-stage task uses bare Task N.N locator",
      any(c["source"] == "plans/2026-07-05-status-edge-cases-plan.md — Task 0.1"
          for c in edges), f"got: {edges}")
check("double-Status malformed task emits exactly one candidate",
      sum("EDGE-DOUBLE" in c["title"] for c in edges) == 1)
check("edge fixture emits nothing else", len(edges) == 2, f"got: {edges}")
bare = parse_plan("# Project Plan: Bare\n\n- **Status:** Draft\n\n## Stage 1: Work\n\n"
                  "### Task 1.1: Ship it\n- [ ] BARE-CANDIDATE-A: still a candidate\n",
                  "plans/bare.md", set())
check("checkbox-less Status field degrades to the legacy heuristic",
      [(c["title"], c["signal"]) for c in bare]
      == [("BARE-CANDIDATE-A: still a candidate", "unchecked-open")], f"got: {bare}")

# --- (h) Light plans ------------------------------------------------------------
light = candidates("2026-07-14-light-inprogress-plan.md")
lt = by_signal(light)
check("light plan: one status-unexecuted candidate per undone task",
      [c["title"] for c in lt.get("status-unexecuted", [])]
      == ["Add the parser fixture", "Bump the version"])
check("light plan locators are Stage 1 / Task 1.N",
      [c["source"] for c in lt.get("status-unexecuted", [])]
      == ["plans/2026-07-14-light-inprogress-plan.md — Stage 1 / Task 1.2",
          "plans/2026-07-14-light-inprogress-plan.md — Stage 1 / Task 1.3"])
check("light plan: stray bullet in DONE task and gate bullets excluded",
      not any("LIGHT-STRAY" in c["title"] or "LIGHT-GATE-MARKER" in c["title"]
              for c in light))
check("light plan: Deferred bullets still surface",
      [c["title"] for c in lt.get("deferred-section", [])]
      == ["LIGHT-DEFERRED-A: badge for light plans"])
check("completed light plan yields zero candidates",
      candidates("2026-07-14-light-completed-plan.md") == [])

# --- architecture docs ---------------------------------------------------------------
check("architecture doc yields zero candidates", candidates("sample-architecture.md") == [])
mut = parse_plan(F["sample-architecture.md"] + "\n- [ ] ARCH-MUTANT: smuggled work\n",
                 "plans/sample-architecture.md", set())
check("mutated architecture doc (one raw unchecked bullet) DOES emit a candidate",
      [c["title"] for c in mut] == ["ARCH-MUTANT: smuggled work"], f"got: {mut}")
check("is_not_a_plan reads the three non-plan suffixes, hyphen-anchored",
      mod.is_not_a_plan("plans/x-design.md") and mod.is_not_a_plan("plans/x-architecture.md")
      and mod.is_not_a_plan("plans/x-done.md")
      and not mod.is_not_a_plan("plans/x-redesign-plan.md"))

# --- (i) the `[~]` partial state ------------------------------------------------------
print("partial state:")
partial = candidates("2026-07-24-partial-status-plan.md")
pt = by_signal(partial)
check("`[~]` task lands in the status-partial bucket",
      [c["title"] for c in pt.get("status-partial", [])]
      == ["PARTIAL-INFLIGHT: started but unfinished"], f"got: {partial}")
check("`[ ]` task lands in status-unexecuted, not status-partial",
      [c["title"] for c in pt.get("status-unexecuted", [])] == ["PARTIAL-OPEN: never started"])
check("`[x]` task emits nothing, and gate bullets excluded",
      not any("PARTIAL-DONE" in c["title"] or "PARTIAL-GATE-MARKER" in c["title"]
              for c in partial))
check("status_state maps the three contract characters",
      tuple(mod.status_state(c) for c in " xX~") == ("open", "done", "done", "partial"))


def done_total(text):
    """done/total as every consumer counts it: STATUS_RE under a task, classified
    through status_state()."""
    done = total = 0
    for line in text.splitlines():
        m = mod.STATUS_RE.match(line)
        if m:
            total += 1
            done += mod.status_state(m.group(1)) == "done"
    return done, total


check("`[~]` counts to total, never to done",
      done_total(F["2026-07-24-partial-status-plan.md"]) == (1, 3),
      f"got: {done_total(F['2026-07-24-partial-status-plan.md'])}")
allpartial = candidates("2026-07-24-all-partial-plan.md")
check("all-partial plan takes the authoritative path, not the legacy heuristic",
      [(c["title"], c["signal"]) for c in allpartial]
      == [("ALLPARTIAL-A: in flight", "status-partial")], f"got: {allpartial}")

# --- (j) abandonment ----------------------------------------------------------------
print("terminal markers:")
check("**Abandoned:** marker flags the plan abandoned, with its reason and no advisory",
      mod.plan_terminal_state(F["2026-07-24-abandoned-plan.md"])
      == (True, None, "2026-07-20 — superseded by the widget rewrite"))
ab = mod.plan_terminal_state(F["2026-07-24-banner-only-plan.md"])
check("banner prose WITHOUT the marker is never abandoned, only advised",
      ab[0] is False and ab[1] is not None and "not suppressed" in ab[1] and ab[2] is None,
      f"got: {ab}")
check("an ordinary live plan is neither abandoned nor advised",
      mod.plan_terminal_state(F["2026-07-24-partial-status-plan.md"]) == (False, None, None))
check("an abandoned plan still yields its open tasks as candidates",
      [c["title"] for c in candidates("2026-07-24-abandoned-plan.md")]
      == ["ABANDONED-A: open task inside an abandoned plan"])
check("COMPLETED_RE reads the close-out line and its heading form",
      mod.COMPLETED_RE.search(F["2026-07-04-widget-sub-02-client-plan.md"]) is not None
      and mod.COMPLETED_RE.search("## Completed: 2031-01-18 — commits: abc\n") is not None
      and mod.COMPLETED_RE.search("the work Completed: mid-sentence\n") is None)

# --- filename stamps and staleness -----------------------------------------------------
print("filename stamps:")
check("90-day boundary: 91 days is stale",
      mod.stale_age_days("2026-04-25-x-plan.md", TODAY_) > mod.STALE_DAYS)
check("90-day boundary: exactly 90 days is NOT stale",
      not (mod.stale_age_days("2026-04-26-x-plan.md", TODAY_) > mod.STALE_DAYS))
check("unstamped filename -> staleness UNKNOWN, never assumed",
      mod.stale_age_days("unstamped-legacy-plan.md") is None)
check("plan_date's 0000-00-00 sentinel is NOT reused for staleness",
      mod.plan_date("unstamped-legacy-plan.md") == "0000-00-00"
      and mod.plan_date("2026-07-24-x-plan.md") == "2026-07-24")
check("invalid date in a filename -> unknown, not a crash",
      mod.stale_age_days("2026-13-45-x-plan.md") is None)
check("future-dated stamp is not stale",
      mod.stale_age_days("2099-01-01-x-plan.md", TODAY_) < 0)

# --- the gate-checkbox contract -------------------------------------------------------
print("gate-item contract, `[~]` is BLOCKED:")
for mark, want in ((" ", "open"), ("x", "done"), ("X", "done"), ("~", "blocked")):
    m = mod.GATE_ITEM_RE.match(f"- [{mark}] a gate check")
    got = mod.gate_item_state(m.group(1)) if m else None
    check(f"`- [{mark}]` -> {want}", got == want, f"got {got}")
check("an out-of-contract gate marker matches nothing",
      mod.GATE_ITEM_RE.match("- [!] out of contract") is None)
check("a `[~]` INSIDE a Stage N Gate block is blocked",
      mod.plan_has_blocked_gate("# P\n\n### Stage 1 Gate\n\n- [x] ok\n- [~] could not run\n"))
check("a `[~]` under Preflight is NOT gate state",
      not mod.plan_has_blocked_gate("# P\n\n### Preflight\n\n- [~] could not run\n\n"
                                    "### Stage 1 Gate\n\n- [x] ok\n"))
check("a `[~]` after the gate block closes is NOT gate state",
      not mod.plan_has_blocked_gate("# P\n\n### Stage 1 Gate\n\n- [x] ok\n\n"
                                    "### Task 1.1: t\n\n- [~] a bullet\n"))

# --- blocked acceptance and propagation to a master -----------------------------------
print("blocked acceptance + master propagation:")
gate = "### Stage 1 Gate\n\n- [x] host suite\n- [~] device suite\n"
plain = "# P\n\n### Task 1.1: a\n- **Status:** [x]\n\n" + gate
b, why = mod.plan_blocked(plain, None)
check("an unaccepted `[~]` gate is blocked, and the reason names the gate",
      b is True and bool(why) and "gate" in why.lower(), f"got {(b, why)}")
accepted = plain + "\n**Blocked-accepted:** 2031-02-11 — no test device here; shipping anyway\n"
check("an ACCEPTED blocked gate is not blocked", mod.plan_blocked(accepted, None)[0] is False)
check("acceptance carries its reason",
      "no test device" in (mod.blocked_acceptance(accepted) or ""))
with tempfile.TemporaryDirectory(prefix="plan-parser-") as td:
    d = Path(td)
    (d / "x-sub-01-plan.md").write_text(plain)
    (d / "x-sub-02-plan.md").write_text(accepted)
    mtext = ("# Master Plan: x\n\n## Sub-plans\n\n"
             "### Sub-plan 1: one\n- **Status:** [x]\n- **Plan:** ./x-sub-01-plan.md\n\n"
             "### Sub-plan 2: two\n- **Status:** [x]\n- **Plan:** ./x-sub-02-plan.md\n")
    mp = d / "x-master-plan.md"
    mp.write_text(mtext)
    b3, why3 = mod.plan_blocked(mtext, mp)
    check("a master with a blocked sub-plan is blocked, naming the sub-plan",
          b3 is True and "sub-01" in (why3 or ""), f"got {(b3, why3)}")
    (d / "x-sub-01-plan.md").write_text(accepted)
    check("a master whose sub-plans are all accepted is not blocked",
          mod.plan_blocked(mtext, mp)[0] is False)
    (d / "x-sub-01-plan.md").write_text(plain)
    check("an accepted master is not blocked whatever its sub-plans say",
          mod.plan_blocked(mtext + "\n**Blocked-accepted:** 2031-02-11 — known\n", mp)[0]
          is False)
    mp2 = d / "y-master-plan.md"
    mp2.write_text("# Master Plan: y\n\n## Sub-plans\n\n### Sub-plan 1: one\n"
                   "- **Status:** [x]\n- **Plan:** ./nope-plan.md\n")
    try:
        ok = mod.plan_blocked(mp2.read_text(), mp2)[0] is False
    except Exception:
        ok = False
    check("an unresolvable sub-plan link is not blockage, and never raises", ok)

# --- out-of-contract warnings ------------------------------------------------------------
print("contract warnings:")


def codes(t, p=None):
    return sorted({c for c, _l, _e in mod.contract_warnings(t, p)})


check("a well-formed plan warns about nothing",
      codes("# Plan: x\n\n### Task 1.1: a\n- **Status:** [x] done\n") == [])
check("an out-of-contract Status marker warns",
      codes("### Task 1.1: a\n- **Status:** [!] blocked on the owner\n")
      == ["STATUS-OUT-OF-CONTRACT"])
check("a Status line with no brackets at all warns too",
      codes("- **Status:** done\n") == ["STATUS-OUT-OF-CONTRACT"])
check("an indented **Blocked-accepted:** warns",
      codes("  **Blocked-accepted:** 2031-02-11 — why\n") == ["ACCEPTANCE-INDENTED"])
check("the same marker at column 0 does not",
      codes("**Blocked-accepted:** 2031-02-11 — why\n") == [])
check("a qualified **Completed (...):** warns",
      codes("**Completed (through Stage 4):** 2031-01-20\n") == ["CLOSE-OUT-DIALECT"])
check("a dated **Close-out (YYYY-MM-DD):** warns",
      codes("**Close-out (2031-01-22):** Complete.\n") == ["CLOSE-OUT-DIALECT"])
check("the plain **Completed:** form does not",
      codes("**Completed:** 2031-01-25 — commits: abc\n") == [])
check("a **Close-out evaluator:** section label does NOT warn",
      codes("**Close-out evaluator:** PASS, 0 Blocking, 2 Material\n") == [])
check("prose beginning with the bare word does NOT warn",
      codes("close-out notes go under the last gate, one per check\n") == [])
check("a bare-ordinal register heading warns in a master",
      codes("# Master Plan: x\n\n### 01. Widget cache and its loaders\n")
      == ["REGISTER-DIALECT"])
check("the recognised Sub-plan form does not",
      codes("# Master Plan: x\n\n### Sub-plan 1: Widget cache\n") == [])
check("the same ordinal heading in a NON-master is not a register at all",
      codes("# Plan: x\n\n### 01. Research summary\n") == [])
fenced = "# Plan: x\n\n```\n- **Status:** [x] an EXAMPLE, not a real marker\n```\n"
check("a marker inside a fence warns", codes(fenced) == ["MARKER-IN-FENCE"])
check("and the parser still reads it, which is why the warning exists",
      mod.STATUS_RE.match("- **Status:** [x] an EXAMPLE, not a real marker") is not None)
w = mod.contract_warnings("a\nb\n  **Blocked-accepted:** 2026-01-01 — w\n")
check("a warning carries its line number", bool(w) and w[0][1] == 3, str(w))
check("ANY_STATUS_RE sees a bracketed marker STATUS_RE cannot",
      mod.ANY_STATUS_RE.match("- **Status:** [!]") is not None
      and mod.STATUS_RE.match("- **Status:** [!]") is None)

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
# An architecture doc lands in plans/ beside the plans, so it must be parser-safe by
# construction: no candidates, whatever its content.
arch = (HERE / "fixtures" / "plan-parser" / "sample-architecture.md").read_text()
check("an architecture doc yields no backlog candidates",
      mod.parse_plan(arch, "plans/sample-architecture.md", set()) == [])
print("\nOK — all plan-parser checks passed")
