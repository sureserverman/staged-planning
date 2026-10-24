#!/usr/bin/env python3
"""Deterministic maturity-axis detectors for `project-maturity audit`.

This is the deterministic lane for the project-maturity skill. It runs every
auto-detect rule defined in `../references/maturity-axes.md`
against a project working tree and emits the fired detectors (with evidence
paths) as JSON. There is **no LLM judgement here** — only file-existence,
glob, JSON-field, and regex checks.

The skill consumes this JSON and applies the judgement-bearing half of the
audit (diff against the existing MATURITY.md, the AI-tool waiver, stale-detector
marking, ship-ready aggregation). Detection is mechanical and lives here;
interpretation stays in the skill.

Output shape (stdout, JSON):

    {
      "project":    "<final path segment>",
      "path":       "<absolute project path>",
      "is_ai_tool": true,
      "detectors": {
        "documentation": [ {"item": "README",  "evidence": "README.md"}, ... ],
        "security":      [ {"item": "security-audit", "evidence": "security-audit-report-...md"} ],
        "packaging":     [ {"item": "Claude Code marketplace", "evidence": ".claude-plugin/marketplace.json"}, ... ],
        "ui_ux":         [ {"item": "icon", "evidence": "..."} ],
        "i18n":          [ {"item": "Android", "evidence": "res/values-de,res/values-fr"} ],
        "testing":       [ {"item": "test suite", "evidence": "tests/"}, {"item": "CI", "evidence": ".github/workflows/ci.yml"} ]
      },
      "notes":  [ "security: repo:security-audit-report-...md present but 1 CRITICAL, 2 HIGH — not clean" ],
      "errors": [ {"axis": "packaging", "item": "Chrome", "evidence": "chrome/manifest.json", "error": "invalid JSON"} ]
    }

`notes` are informational (a detector that found its input but the input does
not satisfy the tick, e.g. an unclean security report). `errors` are stale-detector
triggers (malformed input the skill must surface as `[?] stale-detector`).

Exit code is 0 even when `errors` is non-empty — the errors travel in the JSON
so the skill can render them; a non-zero exit is reserved for bad invocation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Directories pruned from any whole-tree walk: VCS, dependency caches, and
# build output. Detector inputs never legitimately live inside these, and
# walking them is slow and noisy.
PRUNE_DIRS = {
    ".git", "node_modules", "vendor", "target", "build", "dist",
    ".gradle", ".dart_tool", ".venv", "venv", "__pycache__",
    ".next", ".nuxt", ".cache", ".idea", ".vscode", "coverage",
}


def walk(root: Path):
    """Yield every file under root, pruning PRUNE_DIRS in place."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def walk_dirs(root: Path):
    """Yield every directory under root, pruning PRUNE_DIRS in place."""
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for d in dirnames:
            yield Path(dirpath) / d


def rel(root: Path, p: Path) -> str:
    """Repo-relative POSIX path for evidence strings."""
    return p.relative_to(root).as_posix()


def root_file_ci(root: Path, *names: str) -> str | None:
    """Return the actual filename of the first root-level file matching any of
    `names` case-insensitively, else None."""
    wanted = {n.lower() for n in names}
    for child in sorted(root.iterdir()):
        if child.is_file() and child.name.lower() in wanted:
            return child.name
    return None


def root_glob_prefix_ci(root: Path, prefix: str) -> str | None:
    """First root-level file whose name starts with `prefix` (case-insensitive).
    Prefers an exact `<prefix>.md` if present."""
    matches = [c.name for c in root.iterdir()
               if c.is_file() and c.name.lower().startswith(prefix.lower())]
    if not matches:
        return None
    for m in matches:
        if m.lower() == f"{prefix.lower()}.md":
            return m
    return sorted(matches)[0]


# ---------------------------------------------------------------------------
# Project-type fingerprint
# ---------------------------------------------------------------------------

def has_frontmatter_name_desc(p: Path) -> bool:
    """True if the markdown file opens with a YAML frontmatter block carrying
    both `name:` and `description:` keys."""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    block = text[:end] if end != -1 else text[:2000]
    return bool(re.search(r"^name:", block, re.M)) and \
        bool(re.search(r"^description:", block, re.M))


def detect_is_ai_tool(root: Path) -> bool:
    if (root / ".claude-plugin" / "plugin.json").exists() or \
       (root / ".claude-plugin" / "marketplace.json").exists():
        return True
    if (root / ".cursorrules").exists() or list((root / ".cursor" / "rules").glob("*.mdc")):
        return True
    if (root / ".codex" / "config.toml").exists() or list((root / ".codex" / "agents").glob("*.md")):
        return True
    if (root / "opencode.json").exists() or (root / ".opencode").is_dir():
        return True
    # any-depth signals
    for f in walk(root):
        name = f.name
        if name == ".mcp.json" or name == "AGENTS.md":
            return True
    for f in (root / "agents").glob("*.md"):
        if has_frontmatter_name_desc(f):
            return True
    for f in (root / "commands").glob("*.md"):
        if has_frontmatter_name_desc(f):
            return True
    for f in (root / "skills").glob("**/SKILL.md"):
        if has_frontmatter_name_desc(f):
            return True
    return False


# ---------------------------------------------------------------------------
# Axis detectors
# ---------------------------------------------------------------------------

def detect_documentation(root: Path):
    fired = []
    readme = root_glob_prefix_ci(root, "README")
    if readme:
        fired.append({"item": "README", "evidence": readme})
    lic = root_file_ci(root, "LICENSE", "LICENSE.md", "LICENSE.txt")
    if lic:
        fired.append({"item": "LICENSE", "evidence": lic})
    chg = root_file_ci(root, "CHANGELOG", "CHANGELOG.md")
    if chg:
        fired.append({"item": "CHANGELOG", "evidence": chg})
    con = root_file_ci(root, "CONTRIBUTING", "CONTRIBUTING.md")
    if con:
        fired.append({"item": "CONTRIBUTING", "evidence": con})
    return fired, [], []


FINDINGS_RE = re.compile(r"^\*\*Findings:\*\*\s*(\d+)\s+CRITICAL,\s*(\d+)\s+HIGH")

# A security report is a root file named `<prefix>security-audit-report-<stamp>.md` or
# `<prefix>security-report-<stamp>.md`, the prefix empty or ending in `-`. Other audit
# reports never count.
STAMP = r"(\d{8})-(\d{4})\.md$"
DEFAULT_REPORT_RE = re.compile(r"^(?:[A-Za-z0-9._-]*-)?security-(?:audit-)?report-" + STAMP)
PREFIXES_KEY = "security_report_prefixes"

_LIB = Path(__file__).resolve().parents[3] / "lib"


def _configured_prefixes():
    """(prefixes, notes): the extra report-name prefixes the staged-planning config
    names under `security_report_prefixes:`. A config that cannot be read, or a value
    that is not a list of file-name prefixes, is a note and adds nothing."""
    try:
        spec = importlib.util.spec_from_file_location(
            "staged_planning_records_home", _LIB / "records_home.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        value, message = mod.config_value(PREFIXES_KEY)
    except Exception as e:
        return [], [f"security: cannot load the staged-planning config reader ({e!r}); "
                    f"{PREFIXES_KEY} ignored"]
    if message:
        return [], [f"security: staged-planning config unreadable "
                    f"({' '.join(message.split())}); {PREFIXES_KEY} ignored"]
    if value is None:
        return [], []
    if (not isinstance(value, list)
            or not all(isinstance(v, str) and v and "/" not in v for v in value)):
        return [], [f"security: config {PREFIXES_KEY}: must be a list of file-name "
                    f"prefixes (got {value!r}); ignored"]
    return value, []


def _security_reports(root: Path, prefixes):
    """Every security report in the repo root, newest last.

    `scope` is returned alongside the (bare) evidence path rather than baked into it,
    because the SKILL, not this script, renders the `auto:<scope>:<path>` claim line.
    """
    patterns = [DEFAULT_REPORT_RE] + [re.compile("^" + re.escape(x) + STAMP) for x in prefixes]
    found = []  # (timestamp_key, scope, bare_evidence, path)
    for p in root.iterdir():
        if not p.is_file():
            continue
        m = next((m for m in (r.match(p.name) for r in patterns) if m), None)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
        except ValueError:
            continue  # digits in the right places but not a real date/time
        found.append(((stamp, p.name), "repo", rel(root, p), p))
    # Newest = latest stamp; on a same-stamp tie the name that sorts last wins.
    found.sort(key=lambda t: t[0])
    return found


def detect_security(root: Path):
    fired, errors = [], []
    prefixes, notes = _configured_prefixes()
    reports = _security_reports(root, prefixes)
    if not reports:
        return fired, notes, errors
    _, scope, ev, newest = reports[-1]
    try:
        text = newest.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        errors.append({"axis": "security", "item": "security-audit", "evidence": ev,
                       "scope": scope, "error": f"unreadable: {e}"})
        return fired, notes, errors
    m = None
    for line in text.splitlines():
        m = FINDINGS_RE.match(line)
        if m:
            break
    if not m:
        errors.append({"axis": "security", "item": "security-audit", "evidence": ev,
                       "scope": scope, "error": "Findings header line not found"})
        return fired, notes, errors
    crit, high = int(m.group(1)), int(m.group(2))
    if crit == 0 and high == 0:
        fired.append({"item": "security-audit", "evidence": ev, "scope": scope})
    else:
        notes.append(f"security: {scope}:{ev} present but {crit} CRITICAL, "
                     f"{high} HIGH — not clean")
    return fired, notes, errors


def detect_packaging(root: Path):
    fired, notes, errors = [], [], []

    def fire(item, evidence):
        fired.append({"item": item, "evidence": evidence})

    # Debian
    if (root / "deb" / "package" / "DEBIAN" / "control").exists():
        fire("Debian", "deb/package/DEBIAN/control")
    # macOS
    if (root / "pkg").is_dir():
        fire("macOS", "pkg/")
    else:
        pkgs = sorted((root / "releases").glob("**/*.pkg")) if (root / "releases").is_dir() else []
        if pkgs:
            fire("macOS", rel(root, pkgs[0]))
    # Homebrew — any Formula/*.rb anywhere
    brew = [f for f in walk(root) if f.suffix == ".rb" and f.parent.name == "Formula"]
    if brew:
        fire("Homebrew", rel(root, sorted(brew)[0]))
    # Flathub
    flatpak_yaml = sorted(root.glob("*.flatpak.yaml"))
    if flatpak_yaml:
        fire("Flathub", rel(root, flatpak_yaml[0]))
    elif (root / "flatpak").is_dir():
        fire("Flathub", "flatpak/")
    # AUR
    if (root / "PKGBUILD").exists():
        fire("AUR", "PKGBUILD")
    # Snap
    if (root / "snapcraft.yaml").exists():
        fire("Snap", "snapcraft.yaml")
    # Chrome Web Store — manifest_version == 3
    chrome_mf = root / "chrome" / "manifest.json"
    if chrome_mf.exists():
        try:
            data = json.loads(chrome_mf.read_text(encoding="utf-8", errors="replace"))
            if data.get("manifest_version") == 3:
                fire("Chrome", "chrome/manifest.json")
        except (json.JSONDecodeError, OSError) as e:
            errors.append({"axis": "packaging", "item": "Chrome",
                           "evidence": "chrome/manifest.json", "error": f"invalid JSON: {e}"})
    # Firefox AMO
    for cand in ("mozilla/manifest.json", "moz-mobile/manifest.json"):
        if (root / cand).exists():
            fire("Firefox AMO", cand)
            break
    # F-Droid
    if (root / "fastlane" / "metadata" / "android").is_dir():
        fire("F-Droid", "fastlane/metadata/android/")
    else:
        fdroid_meta = sorted((root / "metadata").glob("*.yml")) if (root / "metadata").is_dir() else []
        if fdroid_meta:
            fire("F-Droid", rel(root, fdroid_meta[0]))
    # GitHub Releases (Android APK)
    apk_actions = ("gh release create", "softprops/action-gh-release", "ncipollo/release-action")
    wf_dir = root / ".github" / "workflows"
    if wf_dir.is_dir():
        for wf in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
            try:
                content = wf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if ".apk" in content and any(a in content for a in apk_actions):
                fire("GitHub Releases APK", rel(root, wf))
                break
    # AI-agent tooling distribution channels
    if (root / ".claude-plugin" / "plugin.json").exists():
        fire("Claude Code plugin", ".claude-plugin/plugin.json")
    if (root / ".claude-plugin" / "marketplace.json").exists():
        fire("Claude Code marketplace", ".claude-plugin/marketplace.json")
    mcp = [f for f in walk(root) if f.name == ".mcp.json"]
    if mcp:
        fire("MCP server", rel(root, sorted(mcp)[0]))
    if (root / ".cursorrules").exists():
        fire("Cursor", ".cursorrules")
    else:
        mdc = sorted((root / ".cursor" / "rules").glob("*.mdc"))
        if mdc:
            fire("Cursor", rel(root, mdc[0]))
    codex = None
    agents_md = [f for f in walk(root) if f.name == "AGENTS.md"]
    if agents_md:
        codex = rel(root, sorted(agents_md)[0])
    elif (root / ".codex" / "config.toml").exists():
        codex = ".codex/config.toml"
    else:
        cax = sorted((root / ".codex" / "agents").glob("*.md"))
        if cax:
            codex = rel(root, cax[0])
    if codex:
        fire("Codex", codex)
    if (root / "opencode.json").exists():
        fire("OpenCode", "opencode.json")
    elif (root / ".opencode").is_dir():
        fire("OpenCode", ".opencode/")

    return fired, notes, errors


ICON_EXT = {".png", ".svg", ".ico", ".icns"}


def detect_ui_ux(root: Path):
    # root icon.<ext>
    for ext in (".png", ".svg", ".ico", ".icns"):
        if (root / f"icon{ext}").exists():
            return [{"item": "icon", "evidence": f"icon{ext}"}], [], []
    # root app-icon.*
    app_icons = sorted(root.glob("app-icon.*"))
    if app_icons:
        return [{"item": "icon", "evidence": app_icons[0].name}], [], []
    # Android res/mipmap-*/ic_launcher*
    for f in sorted(walk(root)):
        if f.name.startswith("ic_launcher") and f.parent.name.startswith("mipmap-") \
                and f.parent.parent.name == "res":
            return [{"item": "icon", "evidence": rel(root, f)}], [], []
    # Browser extension: icons/icon*.{png,svg} beside a manifest.json
    for d in walk_dirs(root):
        if d.name == "icons" and (d.parent / "manifest.json").exists():
            icons = sorted([f for f in d.glob("icon*")
                            if f.suffix in (".png", ".svg")])
            if icons:
                return [{"item": "icon", "evidence": rel(root, icons[0])}], [], []
    return [], [], []


ARB_RE = re.compile(r"_([a-z]{2}(?:_[A-Z]{2})?)\.arb$")


def detect_i18n(root: Path):
    fired = []
    # Android res/values-*
    android = sorted({rel(root, d) for d in walk_dirs(root)
                      if d.name.startswith("values-") and d.parent.name == "res"})
    if android:
        fired.append({"item": "Android", "evidence": ",".join(android)})
    # Browser extension _locales/<lang> (excluding en / en_US)
    locales = sorted({rel(root, d) for d in walk_dirs(root)
                      if d.parent.name == "_locales" and d.name not in ("en", "en_US")})
    if locales:
        fired.append({"item": "Browser extension", "evidence": ",".join(locales)})
    # Gettext po/*.po (not messages.pot)
    po = [f for f in walk(root)
          if f.suffix == ".po" and f.parent.name == "po" and f.name != "messages.pot"]
    if po:
        fired.append({"item": "Gettext", "evidence": f"po/ ({len(po)} .po files)"})
    # Flutter *.arb with _<lang> suffix != _en
    arb = []
    for f in walk(root):
        if f.suffix == ".arb":
            m = ARB_RE.search(f.name)
            if m and not m.group(1).startswith("en"):
                arb.append(rel(root, f))
    if arb:
        fired.append({"item": "Flutter", "evidence": ",".join(sorted(arb))})
    return fired, [], []


TEST_DIRS = ("tests", "test", "spec")
TEST_FILE_RE = re.compile(r"(_test\.go|Test\.kt|Test\.java|_test\.py|\.test\.(js|ts|jsx|tsx))$")


def detect_testing(root: Path):
    fired = []
    evidence = None
    # directory conventions at root
    for d in TEST_DIRS:
        if (root / d).is_dir():
            evidence = f"{d}/"
            break
    if evidence is None and (root / "src" / "test").is_dir():
        evidence = "src/test/"
    # Rust: Cargo.toml + (tests/ OR [[test]])
    if evidence is None and (root / "Cargo.toml").exists():
        try:
            cargo = (root / "Cargo.toml").read_text(encoding="utf-8", errors="replace")
        except OSError:
            cargo = ""
        if (root / "tests").is_dir() or "[[test]]" in cargo:
            evidence = "Cargo.toml"
    # test file patterns anywhere
    if evidence is None:
        for f in sorted(walk(root)):
            if TEST_FILE_RE.search(f.name):
                # *Test.kt / *Test.java only count under src/
                if f.name.endswith(("Test.kt", "Test.java")) and "src" not in f.parts:
                    continue
                evidence = rel(root, f)
                break
    if evidence:
        fired.append({"item": "test suite", "evidence": evidence})

    # CI configured
    ci = None
    wf_dir = root / ".github" / "workflows"
    if wf_dir.is_dir():
        wfs = sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml")))
        if wfs:
            ci = ",".join(rel(root, w) for w in wfs)
    if ci is None and (root / ".gitlab-ci.yml").exists():
        ci = ".gitlab-ci.yml"
    if ci is None and (root / ".circleci" / "config.yml").exists():
        ci = ".circleci/config.yml"
    if ci:
        fired.append({"item": "CI", "evidence": ci})
    return fired, [], []


AXES = [
    ("documentation", detect_documentation),
    ("security", detect_security),
    ("packaging", detect_packaging),
    ("ui_ux", detect_ui_ux),
    ("i18n", detect_i18n),
    ("testing", detect_testing),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic maturity-axis detectors.")
    ap.add_argument("project_path", nargs="?", default=".",
                    help="project working tree to scan (default: cwd)")
    args = ap.parse_args(argv)

    root = Path(args.project_path).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    detectors, notes, errors = {}, [], []
    for axis, fn in AXES:
        fired, axis_notes, axis_errors = fn(root)
        detectors[axis] = fired
        notes.extend(axis_notes)
        errors.extend(axis_errors)

    out = {
        "project": root.name,
        "path": str(root),
        "is_ai_tool": detect_is_ai_tool(root),
        "detectors": detectors,
        "notes": notes,
        "errors": errors,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
