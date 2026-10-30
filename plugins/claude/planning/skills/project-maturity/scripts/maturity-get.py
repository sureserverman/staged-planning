#!/usr/bin/env python3
"""Read a project's MATURITY.md and print its ship-readiness for `project-maturity get`.

This is the deterministic lane for `get`. It finds `<records home>/MATURITY.md` through
`lib/records_home.py`, classifies every line of the six axis sections, and computes the
per-axis and overall ship-readiness by the rules in SKILL.md § `get`. There is **no
LLM judgement here** — a line either matches one of the tick-state syntaxes in
`../references/maturity-axes.md` or it is reported under `errors`, never guessed at.

Output shape (stdout, JSON; `--format yaml` prints the same shape as YAML):

    {
      "project": "<final path segment>",
      "path":    "<absolute project path>",
      "file":    "<absolute path of MATURITY.md>",
      "audited": "<YYYY-MM-DD the file was last written>",
      "axes": {
        "documentation": {"ticked": 2, "total": 2, "axis_ship_ready": true,
                          "stale_count": 0, "items": [
          {"label": "auto:repo:README.md", "state": "auto",
           "evidence": "repo:README.md", "stale": false}, ...]},
        "security": {...}, "packaging": {...}, "ui_ux": {...}, "i18n": {...},
        "testing": {...}
      },
      "ship_ready": false,
      "errors": [ {"axis": "packaging", "line": 31, "text": "- [N/A]",
                   "error": "bare [N/A]: a reason is required"} ]
    }

Exit codes: 0 — the object above, even when `errors` is non-empty (the errors travel
in the JSON). 2 — no MATURITY.md (stdout `{"error": "no-maturity-md", "path": ...}`),
the records resolver failed, or the project path is not a directory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

_LIB = Path(__file__).resolve().parents[3] / "lib"

# `## <heading>` (case-insensitive) -> axis key. "Testing" is the reference's name for
# the template's "Testing & CI".
AXIS_HEADINGS = {
    "documentation": "documentation",
    "security": "security",
    "packaging": "packaging",
    "ui/ux": "ui_ux",
    "i18n": "i18n",
    "testing & ci": "testing",
    "testing": "testing",
}
AXES = ["documentation", "security", "packaging", "ui_ux", "i18n", "testing"]
STALE_DAYS = 90

HEADING_RE = re.compile(r"^(#{1,2})\s+(.*?)\s*#*\s*$")
BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
CHECKBOX_RE = re.compile(r"^\[( |x|X|N/A|n/a|\?)\]\s*(.*)$")
STALE90_RE = re.compile(r"\[STALE-90D\]\s*")
STALE_DETECTOR_RE = re.compile(r"\[\?\]\s*stale-detector\b(.*)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_records_home():
    spec = importlib.util.spec_from_file_location(
        "staged_planning_records_home", _LIB / "records_home.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def strip_comments(lines):
    """Yield (line number, text) with HTML comments and fenced code blocks removed."""
    in_comment = in_fence = False
    for n, raw in enumerate(lines, 1):
        line = raw
        if not in_comment and line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out = ""
        while line:
            if in_comment:
                end = line.find("-->")
                if end == -1:
                    line = ""
                else:
                    line = line[end + 3:]
                    in_comment = False
            else:
                start = line.find("<!--")
                if start == -1:
                    out += line
                    line = ""
                else:
                    out += line[:start]
                    line = line[start + 4:]
                    in_comment = True
        yield n, out.rstrip()


def classify(text: str, today: date):
    """(item, stale markers, error) for one line's text after its bullet."""
    markers = len(STALE90_RE.findall(text))
    text = STALE90_RE.sub("", text).strip()
    m = CHECKBOX_RE.match(text)
    if not m:
        return None, markers, "no checkbox: expected [ ], [x], [N/A] or [?]"
    box, rest = m.group(1).lower(), m.group(2).strip()
    item = {"label": rest, "state": None, "evidence": None, "stale": False}

    sd = STALE_DETECTOR_RE.search(text)
    if sd:
        item["label"] = rest
        item["state"] = "stale-detector"
        item["evidence"] = sd.group(1).strip(" \t:—-") or None
        return item, markers, None
    if box == "?":
        return None, markers, "[?] without stale-detector"
    if box == " ":
        if not rest:
            return None, markers, "[ ] with no label"
        item["state"] = "unticked"
        return item, markers, None
    if box == "n/a":
        if not rest:
            return None, markers, "bare [N/A]: a reason is required"
        item["state"] = "na"
        item["evidence"] = rest
        return item, markers, None
    # [x]
    for prefix in ("auto", "claim"):
        if rest.startswith(prefix + ":"):
            value = rest[len(prefix) + 1:].split()
            if not value:
                return None, markers, f"[x] {prefix}: with no {'evidence' if prefix == 'auto' else 'date'}"
            item["state"] = prefix
            item["evidence"] = value[0]
            if prefix == "claim":
                try:
                    if not DATE_RE.match(value[0]):
                        raise ValueError
                    claimed = date.fromisoformat(value[0])
                except ValueError:
                    return None, markers, f"claim date {value[0]!r} is not YYYY-MM-DD"
                item["stale"] = (today - claimed).days > STALE_DAYS
            return item, markers, None
    return None, markers, "[x] without auto:<evidence> or claim:<YYYY-MM-DD>"


def parse(text: str, today: date):
    """(axes, errors, stale-detector anywhere) for a MATURITY.md body."""
    axes = {a: {"items": [], "stale_count": 0, "errors": 0, "seen": False} for a in AXES}
    errors = []
    stale_detector_anywhere = False
    axis = None
    for n, line in strip_comments(text.splitlines()):
        if STALE_DETECTOR_RE.search(line):
            stale_detector_anywhere = True
        h = HEADING_RE.match(line)
        if h:
            axis = AXIS_HEADINGS.get(h.group(2).strip().lower())
            if axis is not None:
                if axes[axis]["seen"]:
                    errors.append({"axis": axis, "line": n, "text": line,
                                   "error": "axis section repeated"})
                    axes[axis]["errors"] += 1
                axes[axis]["seen"] = True
            continue
        if axis is None or not line.strip() or line.strip() == "---":
            continue
        b = BULLET_RE.match(line)
        if b:
            indent, body = b.group(1), b.group(2)
            if not body.startswith("[") and len(indent) >= 2:
                continue  # an indented note under an item, not an item
        elif line.lstrip().startswith("["):
            body = line.strip()
        else:
            continue  # prose inside the section
        item, markers, err = classify(body, today)
        axes[axis]["stale_count"] += markers
        if err:
            errors.append({"axis": axis, "line": n, "text": line.strip(), "error": err})
            axes[axis]["errors"] += 1
        else:
            axes[axis]["items"].append(item)

    for a in AXES:
        if not axes[a]["seen"]:
            errors.append({"axis": a, "line": None, "text": None,
                           "error": "axis section missing"})
            axes[a]["errors"] += 1
    return axes, errors, stale_detector_anywhere


def aggregate(axes):
    out = {}
    for a in AXES:
        items = axes[a]["items"]
        ticked = sum(1 for i in items if i["state"] in ("auto", "claim"))
        total = sum(1 for i in items if i["state"] != "na")
        out[a] = {
            "ticked": ticked,
            "total": total,
            "axis_ship_ready": ticked == total and axes[a]["errors"] == 0,
            "stale_count": axes[a]["stale_count"],
            "items": items,
        }
    return out


def to_yaml(value, indent=0) -> str:
    """Block YAML for dicts, lists and JSON scalars (strings double-quoted)."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        s = ""
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                s += f"{pad}{k}:\n" + to_yaml(v, indent + 1)
            else:
                s += f"{pad}{k}: {scalar(v)}\n"
        return s
    if isinstance(value, list):
        if not value:
            return pad + "[]\n"
        s = ""
        for v in value:
            if isinstance(v, (dict, list)) and v:
                # the nested block's first line, re-indented behind the dash
                s += f"{pad}- " + to_yaml(v, indent + 1)[len(pad) + 2:]
            else:
                s += f"{pad}- {scalar(v)}\n"
        return s
    return pad + scalar(value) + "\n"


def scalar(v) -> str:
    if isinstance(v, (dict, list)):
        return "{}" if isinstance(v, dict) else "[]"
    return json.dumps(v, ensure_ascii=False)


def emit(obj, fmt: str) -> None:
    print(to_yaml(obj), end="") if fmt == "yaml" else print(json.dumps(obj, indent=2))


def main(argv=None) -> int:
    # Staleness probe (the plugin's lib/staleness.py), loaded by path; diagnostic
    # only, and guarded so it can never stop the command. A stale cached copy would
    # judge ship-readiness by superseded rules.
    try:
        _sp = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"
        _spec = importlib.util.spec_from_file_location("staleness_probe", _sp)
        _s = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_s)
        _s.warn_if_stale(__file__)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Ship-readiness of a project's MATURITY.md.")
    ap.add_argument("project_path", nargs="?", default=".",
                    help="project working tree (default: cwd)")
    ap.add_argument("--format", choices=["json", "yaml"], default="json")
    ap.add_argument("--today", help="YYYY-MM-DD to age claims against (default: today)")
    args = ap.parse_args(argv)

    root = Path(args.project_path).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        print(f"error: --today {args.today!r} is not YYYY-MM-DD", file=sys.stderr)
        return 2

    code, home, message = load_records_home().resolve(str(root))
    if code == 2:
        print(f"error: records home: {message}", file=sys.stderr)
        return 2
    if code == 3 and message:
        print(f"note: {message}", file=sys.stderr)
    md = Path(home) / "MATURITY.md"
    if not md.is_file():
        print(f"error: no MATURITY.md at {md}", file=sys.stderr)
        emit({"error": "no-maturity-md", "path": str(md)}, args.format)
        return 2

    text = md.read_text(encoding="utf-8", errors="replace")
    axes, errors, stale_detector = parse(text, today)
    agg = aggregate(axes)
    out = {
        "project": root.name,
        "path": str(root),
        "file": str(md),
        "audited": date.fromtimestamp(os.path.getmtime(md)).isoformat(),
        "axes": agg,
        "ship_ready": (all(agg[a]["axis_ship_ready"] for a in AXES)
                       and not stale_detector and not errors),
        "errors": errors,
    }
    emit(out, args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
