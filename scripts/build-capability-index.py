#!/usr/bin/env python3
"""Generate `capability-index.json`: a machine-independent map of every
skill/agent/command in the marketplace, so plan-execution routing can resolve a
capability *from disk* without the owning plugin being enabled.

Enablement only controls what Claude Code injects and registers at session start
(descriptions, Skill-tool entries, agent types, hooks, MCP servers). The files
themselves are always on disk. A consumer that wants a capability whose plugin is
disabled reads this index, then either Reads-and-follows a skill's SKILL.md or
injects an agent's body into a generic subagent (carrying its `model` pin). The
two capabilities that genuinely can't be lazy-loaded — native hooks and MCP
servers — are flagged `requires_enablement` so the router bounces to the user
instead of silently degrading.

Scans `*/skills/*/SKILL.md`, `*/agents/*.md`, `*/commands/*.md` from the repo
root, excluding `tests/` and `fixtures/` (same rule as check-frontmatter-budget).

Reproducibility contract (the freshness check `check-capability-index.py` depends
on it): output is byte-stable across machines. Component `path`s are
repo-relative with forward slashes; there is NO absolute path and NO timestamp in
the output. Consumers resolve each `path` against the directory containing this
index file (the marketplace root by construction). Components are sorted by
(plugin, kind, name); JSON is emitted with sorted keys and a trailing newline.

Read-only by default: prints JSON to stdout. With --write, writes
`capability-index.json` at the repo root.
"""
import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(REPO_ROOT, "capability-index.json")
SCHEMA_VERSION = 1

# Shared scan primitives live in _frontmatter_common so this generator and
# check-frontmatter-budget.py can't drift on what counts as a component or on the
# dispatch-only rule. Bootstrap this script's own dir onto sys.path so the import
# resolves both when run directly and when loaded via importlib in the tests.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _frontmatter_common import (  # noqa: E402
    PATTERNS,
    is_excluded,
    frontmatter_block,
    disable_model_invocation,
)
from _layout import glob_components, plugin_name, source_root  # noqa: E402

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None


def _require_yaml():
    """PyYAML is a hard dependency of the generator, not an optional accelerator.

    The committed index is checked for freshness by check-capability-index.py, so its bytes must be a pure
    function of the source tree — never of whether the writer's machine happened
    to have PyYAML. A single YAML code path (correct unquoting/unescaping of
    scalars) guarantees that; a stdlib regex fallback would serialize quoted
    descriptions differently and make the freshness check flap. Fail loudly so
    exactly one code path ever produces the file.
    """
    if _yaml is None:
        sys.stderr.write(
            "error: build-capability-index requires PyYAML (pip install pyyaml).\n"
        )
        raise SystemExit(2)


def _collapse(value):
    return re.sub(r"\s+", " ", value.strip())


def parse_frontmatter(text, path="<frontmatter>"):
    """Return a dict of the YAML-parsed frontmatter fields we index: name,
    description, model. Missing fields are None; returns None when there is no
    frontmatter block. The dispatch-only flag is NOT parsed here — build()
    derives it from the shared `disable_model_invocation` predicate so it agrees
    byte-for-byte with the budget script.

    Single YAML code path (see _require_yaml) so emitted content is a pure
    function of the source, independent of environment. A component whose
    frontmatter is not valid YAML raises loudly, naming the file — the
    check-frontmatter-budget lane guards against that on shipped components, so
    it never fires on a clean tree."""
    _require_yaml()
    fm = frontmatter_block(text)
    if fm is None:
        return None
    try:
        data = _yaml.safe_load(fm)
    except Exception as exc:
        raise SystemExit(
            f"error: invalid YAML frontmatter in {path}: "
            f"{str(exc).splitlines()[0][:120]}"
        )
    if not isinstance(data, dict):
        return {"name": None, "description": None, "model": None}
    name = data.get("name")
    desc = data.get("description")
    model = data.get("model")
    return {
        "name": name if isinstance(name, str) else None,
        "description": _collapse(desc) if isinstance(desc, str) else None,
        "model": model if isinstance(model, str) else None,
    }


def plugin_requires_enablement(root, plugin):
    """A plugin's components can't be lazy-loaded from disk when the plugin
    ships machinery that only activates on enablement: native hooks, a native
    MCP config, or a bundled (containerized) MCP server. Detected deterministically
    from files under the plugin dir."""
    pdir = os.path.join(root, plugin)
    # Native hooks: hooks/hooks.json or a `hooks` key in plugin.json.
    if os.path.exists(os.path.join(pdir, "hooks", "hooks.json")):
        return True
    # Native MCP config anywhere in the plugin, excluding test data (a fixture
    # .mcp.json is not the plugin's own MCP config).
    for hit in glob.glob(os.path.join(pdir, "**", ".mcp.json"), recursive=True):
        if not is_excluded(os.path.relpath(hit, root)):
            return True
    # Bundled container MCP (e.g. <plugin>/infrastructure/mcp-server/).
    if os.path.isdir(os.path.join(pdir, "infrastructure", "mcp-server")):
        return True
    manifest = os.path.join(pdir, ".claude-plugin", "plugin.json")
    if os.path.exists(manifest):
        try:
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("hooks") or data.get("mcpServers"):
                return True
        except (ValueError, OSError) as exc:
            sys.stderr.write(f"warning: could not parse {manifest}: {exc}\n")
    return False


def derive_name(kind, rel, frontmatter_name):
    if frontmatter_name:
        return frontmatter_name
    parts = rel.replace(os.sep, "/").split("/")
    if kind == "skill":
        # */skills/<name>/SKILL.md
        return parts[-2]
    # */agents/<name>.md or */commands/<name>.md
    return os.path.splitext(parts[-1])[0]


def build(root):
    components = []
    enablement_cache = {}
    for kind, pattern in PATTERNS:
        for path in glob_components(root, pattern):
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if is_excluded(rel):
                continue
            plugin = plugin_name(rel)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            fields = parse_frontmatter(text, rel)
            if fields is None:
                # No frontmatter: still index the file so it's resolvable, with a
                # derived name and null description.
                fields = {"name": None, "description": None, "model": None}
            if plugin not in enablement_cache:
                enablement_cache[plugin] = any(
                    plugin_requires_enablement(root, src)
                    for src in sorted({source_root(os.path.relpath(p, root))
                                       for _, pat in PATTERNS
                                       for p in glob_components(root, pat)
                                       if plugin_name(os.path.relpath(p, root)) == plugin}))
            components.append({
                "plugin": plugin,
                "kind": kind,
                "name": derive_name(kind, rel, fields["name"]),
                "path": rel,
                "description": fields["description"],
                "model": fields["model"],
                "disable_model_invocation": disable_model_invocation(text),
                "requires_enablement": enablement_cache[plugin],
            })
    components.sort(key=lambda c: (c["plugin"], c["kind"], c["name"]))
    return {"schema": SCHEMA_VERSION, "components": components}


def render(index):
    return json.dumps(index, indent=2, sort_keys=True) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=REPO_ROOT, help="repo root to scan")
    ap.add_argument("--write", action="store_true",
                    help="write capability-index.json at the repo root (default: stdout)")
    ap.add_argument("--out", default=INDEX_PATH, help="output path for --write")
    args = ap.parse_args(argv)

    index = build(args.root)
    text = render(index)
    if args.write:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {len(index['components'])} components -> "
              f"{os.path.relpath(args.out, args.root)}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
