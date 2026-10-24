#!/usr/bin/env python3
"""decisions-relevant — which recorded decisions bind this project?

The project's own register is `<records home>/decisions.md`, where the records home comes
from the plugin's `lib/records_home.py` (the repo's `docs/` when nothing is configured).
A configured records resolver may also list further registers that bind the project,
for example registers shared by every project on one stack (`records_home.py
--decision-registers`). This script digests the project's register first, then each
listed register in order, so planning and execution read one digest instead of
hand-reading files.

Two properties this script exists to guarantee:

  * **Absent is a state, not an error.** A new project has no decisions.md yet; that
    degrades to `project_register: absent`, and the listed registers still return.
  * **Degrade, never drop.** A malformed block comes back flagged, not skipped, and an
    id claimed by two blocks is reported: a decision that fails to parse is exactly the
    one a planner must see.

An unreachable records home (exit 2 from the resolver) is exit 2 here, never an empty
digest: "nothing binds this project" and "the register could not be read" are different
answers.

Run: python3 <plugin>/skills/decisions/scripts/decisions-relevant.py [--project <repo>]
     [--format text|json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[3] / "lib"

# Block boundaries come from a GENERIC `## ` heading match, and the id shape is checked
# per block. Finding boundaries with the strict id pattern instead would make a mistyped
# heading invisible: its body would be swallowed into the block above it.
BLOCK_HEAD_RE = re.compile(r"^## +(.+?)\s*$", re.M)
# Plain (DEC-NNN) and tagged (DEC-XX-NNN) ids, with or without a leading G that some
# shared registers use.
ID_RE = re.compile(r"^((?:G?DEC)-(?:[A-Z]{2,4}-)?\d+)\s+—\s+(.+)$")
RULE_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
FIELD_LINE_RE = re.compile(r"^\s*-\s+\*\*([^:*]+):\*\*\s*(.*)$")
PROJECT_REQUIRED = ("Decided", "Status", "Domains", "Source", "Reason")
EXTRA_REQUIRED = ("Decided", "Status", "Reason")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _LIB / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_decision_file(text, required):
    """`## <ID> — <title>` blocks as dicts; a malformed block is flagged, never dropped."""
    out = []
    marks = list(BLOCK_HEAD_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        heading = m.group(1).strip()
        fields, cur = {}, None
        for line in text[m.end():end].splitlines():
            fm = FIELD_LINE_RE.match(line)
            if fm:
                cur = fm.group(1).strip()
                fields[cur] = fm.group(2).strip()
            elif cur and line.strip() and not RULE_RE.match(line.strip()):
                fields[cur] = (fields[cur] + " " + line.strip()).strip()
        idm = ID_RE.match(heading)
        if not idm:
            out.append({"id": None, "heading": heading, "title": heading, "fields": fields,
                        "missing": list(required), "malformed_heading": True})
            continue
        out.append({"id": idm.group(1), "heading": heading, "title": idm.group(2).strip(),
                    "fields": fields, "malformed_heading": False,
                    "missing": [f for f in required if not fields.get(f)]})
    return out


def duplicate_id_errors(entries):
    """Ids claimed by more than one block in one register: every reference is ambiguous."""
    seen, dupes = set(), []
    for e in entries:
        if e["id"] is None:
            continue
        if e["id"] in seen and e["id"] not in dupes:
            dupes.append(e["id"])
        seen.add(e["id"])
    return [f"`{d}` is defined by more than one block in this file — "
            f"every reference to it is ambiguous" for d in dupes]


def first_sentence(text, limit=240):
    """The Reason's opening sentence: cut at a sentence boundary, else a word boundary."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    for end in (". ", "; "):
        i = t.find(end)
        if 0 < i <= limit:
            return t[:i + 1].strip()
    if len(t) <= limit:
        return t
    return t[:t.rfind(" ", 0, limit)].rstrip(",;: ") + " …"


def digest_entry(entry, register):
    f = entry["fields"]
    status = (f.get("Status") or "").strip()
    return {
        "id": entry["id"],
        "title": entry["title"],
        "status": status or "unknown",
        "superseded": status.lower().startswith("superseded"),
        "register": register,
        "applies_to": " ".join((f.get("Applies to", "") or "").split()).lstrip("- ").replace(" - ", "; "),
        "source": f.get("Source", ""),
        "decided": f.get("Decided", ""),
        "reason": first_sentence(f.get("Reason", "")),
        "malformed": entry["malformed_heading"] or bool(entry["missing"]),
        "missing": entry["missing"],
        "heading": entry["heading"],
    }


def read_register(path, required):
    """{rows, errors} for one register file, or None when the file does not exist."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        text = p.read_text(errors="ignore")
    except OSError as e:
        return {"rows": [], "errors": [f"unreadable: {e}"]}
    entries = parse_decision_file(text, required)
    errors = duplicate_id_errors(entries)
    if not entries:
        errors.append("no decision blocks found")
    return {"rows": [digest_entry(e, str(p)) for e in entries], "errors": errors}


def scan(project):
    """(exit code, result dict or None, message)."""
    rh = _load("staged_planning_records_home", "records_home.py")
    code, home, msg = rh.resolve(project)
    if code == 2:
        return 2, None, msg
    result = {"records_home": home}
    own = read_register(Path(home) / "decisions.md", PROJECT_REQUIRED)
    if own is None:
        result.update(project_register="absent",
                      project_reason=f"{home}/decisions.md does not exist — no decisions recorded yet",
                      project=[], project_errors=[])
    else:
        result.update(project_register="present", project_reason="",
                      project=own["rows"], project_errors=own["errors"])
    rcode, paths, rmsg = rh.decision_registers(project)
    if rcode == 2:
        return 2, None, rmsg
    result["extra"] = []
    for path in paths if rcode == 0 else []:
        reg = read_register(path, EXTRA_REQUIRED)
        if reg is None:
            result["extra"].append({"path": path, "rows": [],
                                    "errors": ["listed by the resolver but does not exist"]})
        else:
            result["extra"].append({"path": path, **reg})
    return 0, result, ""


def _render_row(r):
    marks = []
    if r["superseded"]:
        marks.append("SUPERSEDED")
    if r["malformed"]:
        marks.append("MALFORMED: missing " + ", ".join(r["missing"]) if r["missing"]
                     else "MALFORMED: unparseable heading")
    mark = ("  [" + "; ".join(marks) + "]") if marks else ""
    ident = r["id"] or f"<unparseable heading: {r['heading']}>"
    print(f"{ident} — {r['title']}  ({r['status']}){mark}")
    if r["reason"]:
        print(f"    {r['reason']}")
    if r["applies_to"]:
        print(f"    applies to: {r['applies_to']}")


def render_text(result):
    if result["project_register"] == "present":
        print(f"# Project decisions ({len(result['project'])})")
    else:
        print(f"# Project decisions: absent — {result['project_reason']}")
    for r in result["project"]:
        _render_row(r)
    for e in result["project_errors"]:
        print(f"project register error: {e}", file=sys.stderr)
    for reg in result["extra"]:
        print(f"# Decisions from {reg['path']} ({len(reg['rows'])})")
        for r in reg["rows"]:
            _render_row(r)
        for e in reg["errors"]:
            print(f"register error ({reg['path']}): {e}", file=sys.stderr)


def main(argv=None):
    # Staleness probe (the plugin's lib/staleness.py), loaded by path; diagnostic
    # only, and guarded so it can never stop the command. A stale cached copy would
    # answer "what binds this project" from superseded parsing rules.
    try:
        import importlib.util as _ilu
        _sp = Path(__file__).resolve().parents[3] / "lib" / "staleness.py"
        _spec = _ilu.spec_from_file_location("staleness_probe", _sp)
        _s = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_s)
        _s.warn_if_stale(__file__)
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="decisions-relevant",
                                 description="Digest the decisions that bind a project.")
    ap.add_argument("--project", default="", help="the repo (default: the git top level)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)
    project = args.project or subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    if not project:
        print("decisions-relevant: not in a git repo; pass --project", file=sys.stderr)
        return 2
    code, result, msg = scan(str(Path(project).resolve()))
    if code == 2:
        print(f"decisions-relevant: {msg}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        render_text(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
