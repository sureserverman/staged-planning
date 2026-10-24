"""Where the planning plugin's sources live in this repo.

The checks in scripts/ also read a marketplace layout, where every top-level
directory is one plugin and its name is the directory's name. Here one plugin
is split into layers:

  core/                    host-neutral source, runnable as Claude Code source
  hosts/<host>/add/        files only that host ships
  hosts/<host>/overrides/  that host's whole-file versions of core files, at their
                           core-relative paths

and plugins/ + packages/ hold generated copies. A generated copy is proven
against its sources by `build/build.py --check`; a check that read it as a
source would check the same bytes twice and the sources not at all.

So for every check here: a "plugin directory" is one of the source roots, every
source root belongs to the plugin `planning`, and a recursive scan skips
GENERATED. A tree with neither core/ nor hosts/ (a test fixture laid out like
a marketplace) keeps the marketplace meaning, because the first path segment
of its files is still their plugin.
"""
import glob
import os
import re

PLUGIN = "planning"
CORE = "core"
GENERATED = ("plugins", "packages")
HOST_LAYERS = "hosts/*/add"
_HOST_LAYER = re.compile(r"^(hosts/[^/]+/(?:add|overrides))(?:/|$)")
_HOST_FILE = re.compile(r"^hosts/([^/]+)/(?:add|overrides)/(.*)$")
# A marketplace entry pointing at generated output: ./plugins/<host>/<plugin>.
_GENERATED_SOURCE = re.compile(r"^plugins/([^/]+)/[^/]+$")


def _posix(rel):
    return rel.replace(os.sep, "/")


def source_root(rel):
    """The source root a repo-relative path belongs to: `core`, a host layer
    `hosts/<host>/add` or `hosts/<host>/overrides`, or — outside both — its first
    path segment."""
    rel = _posix(rel)
    m = _HOST_LAYER.match(rel)
    if m:
        return m.group(1)
    return rel.split("/", 1)[0]


def plugin_name(rel):
    """The plugin a repo-relative path ships in."""
    root = source_root(rel)
    return PLUGIN if root == CORE or _HOST_LAYER.match(root) else root


def built_twins(root, rel):
    """For a host layer file, the directory it sits in within each layer that host's
    build unites (its overrides/, core/, its add/), absolute; [] for any other file.

    A host file is read from the built plugin, so a relative path in it resolves there:
    an override of a SKILL.md links to references/ that only core holds.
    """
    m = _HOST_FILE.match(_posix(rel))
    if not m:
        return []
    host, sub = m.group(1), os.path.dirname(m.group(2))
    return [os.path.join(root, d, sub)
            for d in (f"hosts/{host}/overrides", CORE, f"hosts/{host}/add")]


def is_generated(rel):
    return _posix(rel).split("/", 1)[0] in GENERATED


def component_globs(pattern):
    """A `*/<sub>` component glob, widened to the host layers.

    `*/skills/*/SKILL.md` matches core/ the way it matched a marketplace's
    plugin directories; host layers sit two levels deeper, so they need their
    own glob. In a tree with no hosts/ the second glob matches nothing.
    """
    assert pattern.startswith("*/"), pattern
    return [pattern, f"{HOST_LAYERS}/{pattern[2:]}"]


def glob_components(root, pattern):
    """Absolute paths matching a `*/<sub>` component glob in any source root,
    generated output excluded, sorted."""
    hits = set()
    for pat in component_globs(pattern):
        for path in glob.glob(os.path.join(root, pat)):
            if not is_generated(os.path.relpath(path, root)):
                hits.add(path)
    return sorted(hits)


def source_dirs(root, marketplace_source):
    """The directories a marketplace entry's plugin is built from.

    An entry naming generated output (`./plugins/<host>/<plugin>`) is built from
    core/ plus that host's layer; anything else is its own source.
    """
    src = _posix(marketplace_source).removeprefix("./").rstrip("/")
    m = _GENERATED_SOURCE.match(src)
    if not m:
        return [os.path.join(root, src)]
    dirs = [os.path.join(root, CORE)]
    layer = os.path.join(root, "hosts", m.group(1), "add")
    if os.path.isdir(layer):
        dirs.append(layer)
    return dirs


def find_in(dirs, rel):
    """The first of `dirs` holding `rel`, joined; None when none does."""
    for d in dirs:
        path = os.path.join(d, rel)
        if os.path.exists(path):
            return path
    return None
