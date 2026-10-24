#!/usr/bin/env python3
"""Fixture tests for the project-maturity deterministic detector lane.

Runs `scripts/audit-detectors.py` end-to-end against the fixture trees under
`tests/fixtures/` and asserts the fired detectors, the AI-tool flag, and the
notes/errors channels. No pytest dependency — plain assertions, non-zero exit
on any failure. CI runs it through `scripts/run-tests.sh`, which discovers it.

Run locally:  python3 core/skills/project-maturity/tests/test-audit-detectors.py

Coverage note: the `is_ai_tool` frontmatter-bundle branch (agents/·skills/·
commands/ with name:+description:) has no fixture here. The fixtures raise the
flag through manifest signals (`.claude-plugin/*`, `.mcp.json`) instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "audit-detectors.py"
FIXTURES = HERE / "fixtures"
# An XDG config home that holds no config, for runs that must not read one.
NO_CONFIG_HOME = "/nonexistent/staged-planning-test-xdg"

# Expected fired items per axis (as sets — order-independent), the AI-tool flag,
# and invariants on the notes/errors channels.
EXPECTED = {
    "ai-tool-plugin": {
        "is_ai_tool": True,
        "detectors": {
            "documentation": {"README", "LICENSE"},
            "security": {"security-audit"},
            "packaging": {"Claude Code marketplace", "MCP server"},
            "ui_ux": set(),
            "i18n": set(),
            "testing": {"test suite", "CI"},
        },
        "notes": 0,
        "errors": 0,
    },
    "android-app": {
        "is_ai_tool": False,
        "detectors": {
            "documentation": {"README"},
            "security": set(),
            "packaging": {"F-Droid", "GitHub Releases APK"},
            "ui_ux": {"icon"},
            "i18n": {"Android"},
            "testing": {"test suite", "CI"},
        },
        "notes": 0,
        "errors": 0,
        # spot-check evidence where the value carries meaning
        "evidence": {
            ("i18n", "Android"): "res/values-de,res/values-fr",
            ("ui_ux", "icon"): "res/mipmap-hdpi/ic_launcher.png",
        },
    },
    "edge-cases": {
        "is_ai_tool": False,
        "detectors": {
            "documentation": {"README"},
            "security": set(),
            "packaging": set(),
            "ui_ux": set(),
            "i18n": set(),
            "testing": set(),
        },
        "notes": 1,          # unclean security report -> informational note, not a tick
        "errors": 1,         # malformed chrome/manifest.json -> stale-detector
        "note_contains": "not clean",
        "error_item": "Chrome",
    },
}


def run(fixture: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURES / fixture)],
        capture_output=True, text=True, env=isolated_env(NO_CONFIG_HOME),
    )
    if proc.returncode != 0:
        raise AssertionError(f"{fixture}: script exited {proc.returncode}\n{proc.stderr}")
    return json.loads(proc.stdout)


def check(fixture: str, exp: dict, failures: list) -> None:
    out = run(fixture)

    def fail(msg):
        failures.append(f"{fixture}: {msg}")

    if out["is_ai_tool"] != exp["is_ai_tool"]:
        fail(f"is_ai_tool = {out['is_ai_tool']}, expected {exp['is_ai_tool']}")

    for axis, want in exp["detectors"].items():
        got = {i["item"] for i in out["detectors"].get(axis, [])}
        if got != want:
            fail(f"axis {axis}: fired {sorted(got)}, expected {sorted(want)}")

    for (axis, item), want_ev in exp.get("evidence", {}).items():
        got_ev = next((i["evidence"] for i in out["detectors"].get(axis, [])
                       if i["item"] == item), None)
        if got_ev != want_ev:
            fail(f"axis {axis} item {item}: evidence {got_ev!r}, expected {want_ev!r}")

    if len(out["notes"]) != exp["notes"]:
        fail(f"{len(out['notes'])} notes, expected {exp['notes']}: {out['notes']}")
    if "note_contains" in exp and not any(exp["note_contains"] in n for n in out["notes"]):
        fail(f"no note containing {exp['note_contains']!r}: {out['notes']}")

    if len(out["errors"]) != exp["errors"]:
        fail(f"{len(out['errors'])} errors, expected {exp['errors']}: {out['errors']}")
    if "error_item" in exp and not any(e["item"] == exp["error_item"] for e in out["errors"]):
        fail(f"no error on item {exp['error_item']!r}: {out['errors']}")


# --- security reports in the repo ---------------------------------------------
# The detector reads security review reports from the repo only. Each case pins one
# behaviour: a clean newest report ticks the item, the newest of several wins, CRITICALs
# make a note rather than a tick, and a report the detector cannot parse is an error.
REPORT_CASES = [
    # (label, project fixture, expected fired items, notes, errors)
    ("a clean report fires with scope=repo", "records-audited", {"security-audit"}, 0, 0),
    ("the newest of two reports wins", "records-both", {"security-audit"}, 0, 0),
    ("a report with CRITICALs -> note, not a tick", "records-dirty", set(), 1, 0),
    ("a report missing its Findings line -> stale-detector error", "records-stale", set(), 0, 1),
]


def run_fixture(fixture: str) -> dict:
    proc = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURES / fixture)],
                          capture_output=True, text=True, env=isolated_env(NO_CONFIG_HOME))
    if proc.returncode != 0:
        raise AssertionError(f"{fixture}: exited {proc.returncode}\n{proc.stderr}")
    return json.loads(proc.stdout)


def check_reports(failures: list) -> None:
    for label, fixture, want_items, n_notes, n_errors in REPORT_CASES:
        out = run_fixture(fixture)
        sec = out["detectors"]["security"]
        got = {i["item"] for i in sec}
        if got != want_items:
            failures.append(f"{label}: fired {sorted(got)}, expected {sorted(want_items)}")
        if want_items and any(i.get("scope") != "repo" for i in sec):
            failures.append(f"{label}: scope must be repo: {sec}")
        sec_notes = [n for n in out["notes"] if n.startswith("security:")]
        sec_errors = [e for e in out["errors"] if e.get("axis") == "security"]
        if len(sec_notes) != n_notes:
            failures.append(f"{label}: {len(sec_notes)} security notes, expected {n_notes}: {sec_notes}")
        if len(sec_errors) != n_errors:
            failures.append(f"{label}: {len(sec_errors)} security errors, expected {n_errors}: {sec_errors}")


# --- report naming contract ---------------------------------------------------
# A security report is a root file named `<prefix>security-audit-report-<stamp>.md` or
# `<prefix>security-report-<stamp>.md`, where <prefix> is empty or ends in `-` and
# <stamp> is <YYYYMMDD>-<HHMM>. Other audit reports (a license audit, a gate audit)
# never count. The newest is the security report with the latest stamp; on a same-stamp
# tie the name that sorts last wins.
CLEAN = "# Security review\n\n**Findings:** 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW\n"
DIRTY = "# Security review\n\n**Findings:** 2 CRITICAL, 1 HIGH, 0 MEDIUM, 0 LOW\n"
NO_HEADER = "# Gate audit\n\nNo findings table here.\n"
NAMING_CASES = [
    # (label, {filename: body}, expected fired items, expected evidence, notes, errors)
    ("a security-audit-report is detected",
     {"security-audit-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "security-audit-report-20260101-1200.md", 0, 0),
    ("a security-report is detected",
     {"security-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "security-report-20260101-1200.md", 0, 0),
    ("a prefix ending in - is allowed",
     {"x.y_z-security-audit-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "x.y_z-security-audit-report-20260101-1200.md", 0, 0),
    ("a bare audit-report is not a security report",
     {"audit-report-20260101-1200.md": DIRTY},
     set(), None, 0, 0),
    ("a prefix not ending in - is not a security report",
     {"xsecurity-audit-report-20260101-1200.md": DIRTY},
     set(), None, 0, 0),
    ("a name without a valid stamp is ignored",
     {"security-audit-report-draft.md": DIRTY,
      "security-report-draft.md": DIRTY,
      "security-audit-report-20261399-1200.md": DIRTY,
      "security-audit-report-20260101-1200-old.md": DIRTY},
     set(), None, 0, 0),
    ("an unstamped name does not shadow a stamped one",
     {"security-audit-report-latest.md": DIRTY,
      "security-audit-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "security-audit-report-20260101-1200.md", 0, 0),
    ("newest by stamp wins across prefixes (newer is clean)",
     {"zzz-security-audit-report-20260101-0900.md": DIRTY,
      "security-report-20260724-1830.md": CLEAN},
     {"security-audit"}, "security-report-20260724-1830.md", 0, 0),
    ("newest by stamp wins across prefixes (newer is dirty)",
     {"security-report-20260101-0900.md": CLEAN,
      "aaa-security-audit-report-20260724-1830.md": DIRTY},
     set(), None, 1, 0),
    ("a same-stamp tie goes to the name that sorts last",
     {"a-security-audit-report-20260101-1200.md": DIRTY,
      "b-security-audit-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "b-security-audit-report-20260101-1200.md", 0, 0),
    # A newer clean license audit must not hide a dirty security report.
    ("a newer clean license audit does not hide a dirty security report",
     {"x-security-audit-report-20261001-1000.md": DIRTY,
      "spare-audit-report-20261015-0900.md": CLEAN},
     set(), None, 1, 0),
    # A newer gate audit with no Findings header is ignored, not an error.
    ("a newer gate audit with no Findings header is ignored",
     {"security-audit-report-20261001-1000.md": CLEAN,
      "misc-audit-report-20261015-0900.md": NO_HEADER},
     {"security-audit"}, "security-audit-report-20261001-1000.md", 0, 0),
]

# --- configured prefixes --------------------------------------------------------
# `security_report_prefixes:` in the staged-planning config adds filename prefixes that
# precede `<YYYYMMDD>-<HHMM>.md`. The prefix here is invented; it names no real tool.
# A config that cannot be read, or a key that is not a list of names, is a note and the
# default names still work.
CONFIG_CASES = [
    # (label, config text or None, {filename: body}, fired, evidence, notes, errors, note_contains)
    ("without a config, an invented prefix is not a security report", None,
     {"acme-scan-20260101-1200.md": CLEAN},
     set(), None, 0, 0, None),
    ("a configured prefix is a security report",
     "security_report_prefixes: [acme-scan-]\n",
     {"acme-scan-20260101-1200.md": CLEAN},
     {"security-audit"}, "acme-scan-20260101-1200.md", 0, 0, None),
    ("a configured prefix competes by stamp with the default names",
     "security_report_prefixes: [acme-scan-]\n",
     {"security-audit-report-20260101-1200.md": CLEAN,
      "acme-scan-20260724-1830.md": DIRTY},
     set(), None, 1, 0, "not clean"),
    ("a configured prefix needs a valid stamp",
     "security_report_prefixes: [acme-scan-]\n",
     {"acme-scan-latest.md": DIRTY, "acme-scan-20261399-1200.md": DIRTY},
     set(), None, 0, 0, None),
    ("a config without the key changes nothing",
     "records_resolver: [python3, /nonexistent/r.py]\n",
     {"acme-scan-20260101-1200.md": CLEAN,
      "security-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "security-report-20260101-1200.md", 0, 0, None),
    ("an invalid config is a note; the default names still work",
     "security_report_prefixes: [acme-scan-\n",
     {"security-report-20260101-1200.md": CLEAN, "acme-scan-20260724-1830.md": DIRTY},
     {"security-audit"}, "security-report-20260101-1200.md", 1, 0, "config"),
    ("a key that is not a list is a note",
     "security_report_prefixes: acme-scan-\n",
     {"acme-scan-20260101-1200.md": CLEAN},
     set(), None, 1, 0, "security_report_prefixes"),
    ("a prefix holding a / is a note",
     "security_report_prefixes: [sub/acme-scan-]\n",
     {"security-report-20260101-1200.md": CLEAN},
     {"security-audit"}, "security-report-20260101-1200.md", 1, 0, "security_report_prefixes"),
]


def isolated_env(config_home: str, config_file: str | None = None) -> dict:
    """The environment with the staged-planning config pointed at a throwaway place,
    so the machine's own config can never decide a case."""
    env = {k: v for k, v in os.environ.items() if k != "STAGED_PLANNING_CONFIG"}
    env["XDG_CONFIG_HOME"] = config_home
    if config_file is not None:
        env["STAGED_PLANNING_CONFIG"] = config_file
    return env


def run_tree(files: dict, config: str | None = None):
    """Write `files` into a temp project, run the detector with `config` as the
    staged-planning config (None = no config), and return (exit code, stderr, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "proj"
        proj.mkdir()
        for name, body in files.items():
            (proj / name).write_text(body, encoding="utf-8")
        cfg = None
        if config is not None:
            cfg = Path(tmp) / "config.yaml"
            cfg.write_text(config, encoding="utf-8")
        proc = subprocess.run([sys.executable, str(SCRIPT), str(proj)],
                              capture_output=True, text=True,
                              env=isolated_env(str(Path(tmp) / "xdg"),
                                               None if cfg is None else str(cfg)))
        out = json.loads(proc.stdout) if proc.returncode == 0 else None
        return proc.returncode, proc.stderr, out


def check_security_out(label, out, want_items, want_ev, n_notes, n_errors, failures,
                       note_contains=None) -> None:
    sec = out["detectors"]["security"]
    got = {i["item"] for i in sec}
    if got != want_items:
        failures.append(f"{label}: fired {sorted(got)}, expected {sorted(want_items)}")
    if want_ev is not None and [i.get("evidence") for i in sec] != [want_ev]:
        failures.append(f"{label}: evidence {[i.get('evidence') for i in sec]}, "
                        f"expected [{want_ev!r}]")
    sec_notes = [n for n in out["notes"] if n.startswith("security:")]
    sec_errors = [e for e in out["errors"] if e.get("axis") == "security"]
    if len(sec_notes) != n_notes:
        failures.append(f"{label}: {len(sec_notes)} security notes, expected {n_notes}: {sec_notes}")
    if note_contains and not any(note_contains in n for n in sec_notes):
        failures.append(f"{label}: no security note containing {note_contains!r}: {sec_notes}")
    if len(sec_errors) != n_errors:
        failures.append(f"{label}: {len(sec_errors)} security errors, expected {n_errors}: {sec_errors}")


def check_naming(failures: list) -> None:
    for label, files, want_items, want_ev, n_notes, n_errors in NAMING_CASES:
        code, err, out = run_tree(files)
        if out is None:
            failures.append(f"{label}: exited {code}\n{err}")
            continue
        note = "not clean" if n_notes else None
        check_security_out(label, out, want_items, want_ev, n_notes, n_errors, failures, note)


def check_config(failures: list) -> None:
    for label, config, files, want_items, want_ev, n_notes, n_errors, note in CONFIG_CASES:
        code, err, out = run_tree(files, config)
        if out is None:
            failures.append(f"{label}: exited {code}\n{err}")
            continue
        check_security_out(label, out, want_items, want_ev, n_notes, n_errors, failures, note)


def main() -> int:
    if not SCRIPT.exists():
        print(f"FAIL: detector script not found at {SCRIPT}", file=sys.stderr)
        return 2
    failures: list = []
    for fixture, exp in EXPECTED.items():
        check(fixture, exp, failures)
    check_reports(failures)
    check_naming(failures)
    check_config(failures)
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK — {len(EXPECTED)} fixtures passed "
          f"({', '.join(EXPECTED)}) "
          f"+ {len(REPORT_CASES)} security-report cases "
          f"+ {len(NAMING_CASES)} report-naming cases "
          f"+ {len(CONFIG_CASES)} configured-prefix cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
