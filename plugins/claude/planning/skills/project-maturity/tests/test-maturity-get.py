#!/usr/bin/env python3
"""Fixture tests for `scripts/maturity-get.py`, the script `project-maturity get` runs.

Every expectation below comes from the rules in SKILL.md § `get` and the tick-state
syntax in `references/maturity-axes.md`, never from what the script prints:

  - an item's `state` is auto | claim | na | unticked | stale-detector; `stale` is true
    for a claim more than 90 days old;
  - `ticked` counts auto + claim lines; `total` counts the lines present minus `[N/A]`;
  - `axis_ship_ready` is true iff every counted line is ticked, or the axis is empty or
    N/A-only (ship-ready by vacuity); `stale_count` counts `[STALE-90D]` markers;
  - `ship_ready` is true iff every axis is ship-ready, no `[?] stale-detector` marker
    is anywhere in the file, and `errors` is empty;
  - a missing MATURITY.md exits 2 naming its path;
  - a malformed line (a bare `[N/A]`, an `[x]` without `auto:`/`claim:`, a claim whose
    date is not a date) or a missing axis section is reported under `errors`, never
    classified; its axis is not ship-ready.

The MATURITY.md fixtures are synthetic and written into a temp dir per case. The
staged-planning config is pointed at an empty temp dir, so the records home is always
`<project>/docs`. No pytest dependency — plain assertions, non-zero exit on any failure.

Run locally:  python3 core/skills/project-maturity/tests/test-maturity-get.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "maturity-get.py"
TODAY = "2026-10-29"
RECENT = "2026-09-01"     # 58 days before TODAY
DAY_90 = "2026-07-31"     # exactly 90 days: not stale
DAY_91 = "2026-07-30"     # 91 days: stale
OLD = "2026-01-02"        # 300 days
AXES = ["documentation", "security", "packaging", "ui_ux", "i18n", "testing"]

HEAD = """# Project Maturity: proj

This file tracks publishing-readiness across six axes. Each sub-item
carries one of three tick states:

- `[x] auto:<evidence>`     — auto-detected by `project-maturity audit`
- `[x] claim:<YYYY-MM-DD>`  — manually asserted by the maintainer
- `[N/A] <reason>`          — does not apply to this project

---
"""

NOTES = """
---

## Notes

- [ ] a bullet in Notes is not an axis item
"""

# All six axes, mixed states. Expected values follow the § get rules by hand.
SIX_AXES = HEAD + f"""
## Documentation

- [x] auto:repo:README.md
- [x] auto:repo:LICENSE

## Security

- [x] claim:{RECENT}

## Packaging

<!-- audit will ADD a line per detected packaging target.
- [ ] claim:planned-2026-01-01 inside a comment is not an item -->
- [N/A] not-distributed

## UI/UX

- [ ] App icon present
- [STALE-90D] [x] claim:{OLD}
- [N/A] headless-cli

## i18n

<!-- audit will add a line if a non-default locale is detected. -->

## Testing & CI

- [x] auto:repo:tests/
- [x] auto:repo:.github/workflows/ci.yml
""" + NOTES

SIX_AXES_EXPECTED = {
    "documentation": {"ticked": 2, "total": 2, "axis_ship_ready": True, "stale_count": 0,
                      "states": ["auto", "auto"]},
    "security": {"ticked": 1, "total": 1, "axis_ship_ready": True, "stale_count": 0,
                 "states": ["claim"]},
    "packaging": {"ticked": 0, "total": 0, "axis_ship_ready": True, "stale_count": 0,
                  "states": ["na"]},
    "ui_ux": {"ticked": 1, "total": 2, "axis_ship_ready": False, "stale_count": 1,
              "states": ["unticked", "claim", "na"]},
    "i18n": {"ticked": 0, "total": 0, "axis_ship_ready": True, "stale_count": 0,
             "states": []},
    "testing": {"ticked": 2, "total": 2, "axis_ship_ready": True, "stale_count": 0,
                "states": ["auto", "auto"]},
}

ALL_READY = HEAD + f"""
## Documentation

- [x] auto:repo:README.md
- [x] claim:{DAY_90}

## Security

- [N/A] no-attack-surface

## Packaging

- [x] auto:repo:.claude-plugin/plugin.json

## UI/UX

- [N/A] ai-tool

## i18n

- [N/A] ai-tool

## Testing & CI

- [x] auto:repo:tests/
- [x] claim:{DAY_91}
""" + NOTES

# The same file with a stale-detector line in one axis.
STALE_DETECTOR_IN_AXIS = ALL_READY.replace(
    "- [x] auto:repo:.claude-plugin/plugin.json",
    "- [x] auto:repo:.claude-plugin/plugin.json\n"
    "- [?] stale-detector — chrome/manifest.json: invalid JSON")

# Every axis ready, but a stale-detector marker sits outside the axes.
STALE_DETECTOR_IN_NOTES = ALL_READY + "\n[?] stale-detector previously had: repo:icon.png\n"

MALFORMED = HEAD + """
## Documentation

- [x] auto:repo:README.md
- [x] auto:repo:LICENSE

## Security

- [x] security audit clean

## Packaging

- [N/A]

## UI/UX

- [x] claim:2026-13-45

## Testing & CI

- [x] auto:repo:tests/
- [x] auto:repo:.github/workflows/ci.yml
""" + NOTES


def isolated_env(tmp: str) -> dict:
    """The environment with the staged-planning config pointed at an empty place,
    so the records home is always <project>/docs."""
    env = {k: v for k, v in os.environ.items() if k != "STAGED_PLANNING_CONFIG"}
    env["XDG_CONFIG_HOME"] = str(Path(tmp) / "xdg")
    return env


def run(maturity: str | None, *extra: str):
    """Write `maturity` (None = no file) to <tmp>/proj/docs/MATURITY.md, run the script,
    and return (exit code, stdout, stderr, the MATURITY.md path)."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "proj"
        (proj / "docs").mkdir(parents=True)
        md = proj / "docs" / "MATURITY.md"
        if maturity is not None:
            md.write_text(maturity, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(proj), "--today", TODAY, *extra],
            capture_output=True, text=True, env=isolated_env(tmp))
        return proc.returncode, proc.stdout, proc.stderr, str(md.resolve())


def run_json(label: str, maturity: str, failures: list):
    code, out, err, _ = run(maturity)
    if code != 0:
        failures.append(f"{label}: exited {code}, expected 0\n{err}")
        return None
    try:
        return json.loads(out)
    except ValueError as e:
        failures.append(f"{label}: stdout is not JSON ({e}): {out[:300]!r}")
        return None


def check_six_axes(failures: list) -> None:
    label = "six axes"
    out = run_json(label, SIX_AXES, failures)
    if out is None:
        return
    if out.get("project") != "proj":
        failures.append(f"{label}: project {out.get('project')!r}, expected 'proj'")
    if sorted(out.get("axes", {})) != sorted(AXES):
        failures.append(f"{label}: axes {sorted(out.get('axes', {}))}, expected {sorted(AXES)}")
        return
    for axis, want in SIX_AXES_EXPECTED.items():
        got = out["axes"][axis]
        for key in ("ticked", "total", "axis_ship_ready", "stale_count"):
            if got.get(key) != want[key]:
                failures.append(f"{label}: {axis}.{key} = {got.get(key)!r}, expected {want[key]!r}")
        states = [i.get("state") for i in got.get("items", [])]
        if states != want["states"]:
            failures.append(f"{label}: {axis} states {states}, expected {want['states']}")
    if out.get("ship_ready") is not False:
        failures.append(f"{label}: ship_ready {out.get('ship_ready')!r}, expected False")
    if out.get("errors"):
        failures.append(f"{label}: errors {out['errors']}, expected none")

    # Item fields: label, evidence, stale.
    ui = out["axes"]["ui_ux"]["items"]
    want_items = [
        {"label": "App icon present", "state": "unticked", "evidence": None, "stale": False},
        {"state": "claim", "evidence": OLD, "stale": True},
        {"state": "na", "evidence": "headless-cli", "stale": False},
    ]
    for got, want in zip(ui, want_items):
        for key, val in want.items():
            if got.get(key) != val:
                failures.append(f"{label}: ui_ux item {got} has {key}={got.get(key)!r}, expected {val!r}")
    doc = out["axes"]["documentation"]["items"]
    if [i.get("evidence") for i in doc] != ["repo:README.md", "repo:LICENSE"]:
        failures.append(f"{label}: documentation evidence {[i.get('evidence') for i in doc]}")
    sec = out["axes"]["security"]["items"]
    if sec and (sec[0].get("evidence") != RECENT or sec[0].get("stale") is not False):
        failures.append(f"{label}: security claim {sec[0]}, expected evidence {RECENT}, stale False")


def check_ready_and_stale_detector(failures: list) -> None:
    out = run_json("all ready", ALL_READY, failures)
    if out is not None:
        if out.get("ship_ready") is not True:
            failures.append(f"all ready: ship_ready {out.get('ship_ready')!r}, expected True")
        for axis in AXES:
            if out["axes"][axis].get("axis_ship_ready") is not True:
                failures.append(f"all ready: {axis} not ship-ready: {out['axes'][axis]}")
        doc = out["axes"]["documentation"]["items"]
        if [i.get("stale") for i in doc] != [False, False]:
            failures.append(f"all ready: a claim exactly 90 days old is stale: {doc}")
        tst = out["axes"]["testing"]["items"]
        if [i.get("stale") for i in tst] != [False, True]:
            failures.append(f"all ready: a claim 91 days old is not stale: {tst}")
        if out["axes"]["testing"].get("stale_count") != 0:
            failures.append("all ready: stale_count counts [STALE-90D] markers, and there are none")

    out = run_json("stale-detector in an axis", STALE_DETECTOR_IN_AXIS, failures)
    if out is not None:
        pk = out["axes"]["packaging"]
        if [i.get("state") for i in pk["items"]] != ["auto", "stale-detector"]:
            failures.append(f"stale-detector in an axis: packaging states {pk['items']}")
        if (pk.get("ticked"), pk.get("total"), pk.get("axis_ship_ready")) != (1, 2, False):
            failures.append(f"stale-detector in an axis: packaging {pk}")
        if out.get("ship_ready") is not False:
            failures.append("stale-detector in an axis: ship_ready is not False")

    out = run_json("stale-detector in Notes", STALE_DETECTOR_IN_NOTES, failures)
    if out is not None:
        if not all(out["axes"][a].get("axis_ship_ready") for a in AXES):
            failures.append("stale-detector in Notes: an axis changed; the marker is outside them")
        if out.get("ship_ready") is not False:
            failures.append("stale-detector in Notes: a marker anywhere in the file must block ship_ready")


def check_missing(failures: list) -> None:
    label = "missing MATURITY.md"
    code, out, err, md = run(None)
    if code != 2:
        failures.append(f"{label}: exited {code}, expected 2")
    if md not in out and md not in err:
        failures.append(f"{label}: the path {md} is not named\nstdout: {out}\nstderr: {err}")
    try:
        body = json.loads(out)
    except ValueError:
        failures.append(f"{label}: stdout is not JSON: {out!r}")
        return
    if body != {"error": "no-maturity-md", "path": md}:
        failures.append(f"{label}: stdout {body}, expected the no-maturity-md object")


def check_malformed(failures: list) -> None:
    label = "malformed"
    out = run_json(label, MALFORMED, failures)
    if out is None:
        return
    errs = out.get("errors") or []
    by_axis: dict = {}
    for e in errs:
        by_axis.setdefault(e.get("axis"), []).append(e)
    # One reported error per malformed axis: [x] without a prefix, a bare [N/A], a claim
    # date that is not a date, and the missing i18n section.
    for axis in ("security", "packaging", "ui_ux", "i18n"):
        if len(by_axis.get(axis, [])) != 1:
            failures.append(f"{label}: {axis} errors {by_axis.get(axis)}, expected exactly 1")
        if out["axes"].get(axis, {}).get("axis_ship_ready") is not False:
            failures.append(f"{label}: {axis} is ship-ready, but it was not readable")
        # A malformed line is reported, not classified into an item.
        if out["axes"].get(axis, {}).get("items"):
            failures.append(f"{label}: {axis} classified a malformed line: {out['axes'][axis]['items']}")
    for e in by_axis.get("security", []) + by_axis.get("packaging", []) + by_axis.get("ui_ux", []):
        if not isinstance(e.get("line"), int) or not e.get("error"):
            failures.append(f"{label}: error {e} lacks a line number or a reason")
    want_text = {"security": "[x] security audit clean", "packaging": "[N/A]",
                 "ui_ux": "[x] claim:2026-13-45"}
    for axis, text in want_text.items():
        if not any(text in (e.get("text") or "") for e in by_axis.get(axis, [])):
            failures.append(f"{label}: no {axis} error quoting {text!r}: {by_axis.get(axis)}")
    if set(by_axis) - {"security", "packaging", "ui_ux", "i18n"}:
        failures.append(f"{label}: errors on readable axes: {errs}")
    for axis in ("documentation", "testing"):
        if out["axes"][axis].get("axis_ship_ready") is not True:
            failures.append(f"{label}: well-formed {axis} lost its ship-readiness")
    if out.get("ship_ready") is not False:
        failures.append(f"{label}: ship_ready {out.get('ship_ready')!r}, expected False")


def check_yaml(failures: list) -> None:
    code, out, err, _ = run(ALL_READY, "--format", "yaml")
    if code != 0:
        failures.append(f"yaml: exited {code}\n{err}")
    elif "ship_ready: true" not in out or out.lstrip().startswith("{"):
        failures.append(f"yaml: not block YAML with ship_ready: true:\n{out[:400]}")


def main() -> int:
    if not SCRIPT.exists():
        print(f"FAIL: script not found at {SCRIPT}", file=sys.stderr)
        return 2
    failures: list = []
    checks = [check_six_axes, check_ready_and_stale_detector, check_missing,
              check_malformed, check_yaml]
    for check in checks:
        check(failures)
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK — {len(checks)} checks passed (six axes, ready + stale-detector, "
          f"missing file, malformed, yaml)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
