"""The schemas build.py reads: a host's host.yaml and its overrides.lock.

host.yaml, at <root>/hosts/<host>/host.yaml:
  host: <host>                 must be the directory's name
  out: <path>                  the output, relative to the root's git toplevel
  exclude: [<glob>, ...]       core paths this host does not ship
  rewrites:                    applied in order to the core files a glob matches
    - {glob: <glob>, pattern: <regex>, replace: <re.sub replacement>}
  features:                    what the host matrix reports
    - {id: <id>, status: native|equivalent|inline|absent, note: <text>}
  moves:                       output paths renamed after overrides (a file or a directory)
    - {from: <path>, to: <path>}

  The record keys below are carried, never read by the build: a host probe's measured
  facts (probe_date, probe_script and what it measured) and the owner's rulings on them.
  Their shape is the probe's and the plan's, so only the key names are checked here.

overrides.lock, at <root>/hosts/<host>/overrides.lock:
  <core-relpath>:
    base_sha256: <sha256 of core/<core-relpath> when the override was last reread>
    host_fact: <the host fact that forces the fork>   required for a script

Globs match a path relative to core/ (the output path): `*` and `?` stay inside one
path segment, `**` crosses segments, and `**/` also matches no directory at all.
A rewrite's pattern is compiled with re.MULTILINE, so `^` and `$` match at each line.

A shape this module does not know is refused, never read as something close.
"""
import re

import yaml

HOST_KEYS = {"host", "out", "exclude", "rewrites", "features", "moves"}
MOVE_KEYS = {"from", "to"}
RECORD_KEYS = {"probe_date", "probe_script", "probe_events", "probe_double_fire",
               "claude_hooks_run", "shadow", "install_shape", "co_visible_roots",
               "external_directory", "rulings"}
REWRITE_KEYS = {"glob", "pattern", "replace"}
FEATURE_KEYS = {"id", "status", "note"}
STATUSES = ("native", "equivalent", "inline", "absent")
LOCK_KEYS = {"base_sha256", "host_fact", "depends_on"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SchemaError(Exception):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    """A SafeLoader that refuses a repeated mapping key: last-wins would let a second
    `exclude:` silently replace the first."""


def _unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"repeated key {key!r}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def glob_re(glob):
    """A compiled regex matching the whole of a relative path against `glob`."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def load_yaml(path):
    """A YAML file, refusing a repeated key; a parse error is a SchemaError."""
    with open(path, encoding="utf-8") as fh:
        try:
            return yaml.load(fh, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader)
        except yaml.YAMLError as e:
            raise SchemaError(f"{path}: not YAML: {e}") from None


def _str(value, where):
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{where} must be a non-empty string, not {value!r}")
    return value


def _glob(value, where):
    _str(value, where)
    if value.startswith("/") or ".." in value.split("/"):
        raise SchemaError(f"{where} must be a path glob relative to core/, not {value!r}")
    return value


def load_host(path, host):
    """host.yaml as a dict with every key present, compiled where it compiles."""
    doc = load_yaml(path)
    if not isinstance(doc, dict):
        raise SchemaError(f"{path} must be a mapping")
    unknown = sorted(set(doc) - HOST_KEYS - RECORD_KEYS)
    if unknown:
        raise SchemaError(f"{path}: unknown key(s) {', '.join(map(str, unknown))}")
    for key in ("host", "out"):
        if key not in doc:
            raise SchemaError(f"{path}: missing {key!r}")
    if _str(doc["host"], f"{path}: host") != host:
        raise SchemaError(f"{path}: host is {doc['host']!r}, but the file is under hosts/{host}/")
    out = _str(doc["out"], f"{path}: out")
    lists = {}
    for key in ("exclude", "rewrites", "features", "moves"):
        value = doc.get(key)
        if value is None:
            value = []
        if not isinstance(value, list):
            raise SchemaError(f"{path}: {key} must be a list")
        lists[key] = value
    exclude = [_glob(g, f"{path}: exclude[{i}]") for i, g in enumerate(lists["exclude"])]
    rewrites = []
    for i, rw in enumerate(lists["rewrites"]):
        where = f"{path}: rewrites[{i}]"
        if not isinstance(rw, dict) or set(rw) != REWRITE_KEYS:
            raise SchemaError(f"{where} must have exactly the keys glob, pattern, replace")
        _glob(rw["glob"], f"{where}.glob")
        _str(rw["pattern"], f"{where}.pattern")
        if not isinstance(rw["replace"], str):
            raise SchemaError(f"{where}.replace must be a string")
        try:
            pattern = re.compile(rw["pattern"], re.M)
        except re.error as e:
            raise SchemaError(f"{where}.pattern {rw['pattern']!r} does not compile: {e}") from None
        rewrites.append({"glob": rw["glob"], "match": glob_re(rw["glob"]),
                         "pattern": pattern, "replace": rw["replace"]})
    features, seen = [], set()
    for i, ft in enumerate(lists["features"]):
        where = f"{path}: features[{i}]"
        if not isinstance(ft, dict) or not {"id", "status"} <= set(ft) \
                or set(ft) - FEATURE_KEYS:
            raise SchemaError(f"{where} must have id and status, and may have note")
        fid = _str(ft["id"], f"{where}.id")
        if fid in seen:
            raise SchemaError(f"{where}: feature {fid!r} is listed twice")
        seen.add(fid)
        if ft["status"] not in STATUSES:
            raise SchemaError(f"{where}.status {ft['status']!r} is not one of "
                              + "|".join(STATUSES))
        note = ft.get("note")
        if note is not None:
            _str(note, f"{where}.note")
        features.append({"id": fid, "status": ft["status"], "note": note})
    moves, seen = [], set()
    for i, mv in enumerate(lists["moves"]):
        where = f"{path}: moves[{i}]"
        if not isinstance(mv, dict) or set(mv) != MOVE_KEYS:
            raise SchemaError(f"{where} must have exactly the keys from, to")
        for key in ("from", "to"):
            v = _str(mv[key], f"{where}.{key}")
            if v.startswith("/") or v.endswith("/") or "" in v.split("/") \
                    or ".." in v.split("/") or "*" in v or "?" in v:
                raise SchemaError(f"{where}.{key} must be a plain relative path, not {v!r}")
        if mv["from"] == mv["to"]:
            raise SchemaError(f"{where} moves {mv['from']!r} onto itself")
        if mv["from"] in seen:
            raise SchemaError(f"{where}: {mv['from']!r} is moved twice")
        seen.add(mv["from"])
        moves.append({"from": mv["from"], "to": mv["to"]})
    return {"host": host, "out": out, "exclude": exclude, "rewrites": rewrites,
            "features": features, "moves": moves}


def load_lock(path):
    """overrides.lock as {relpath: {base_sha256, host_fact or None, depends_on}}; {} when
    empty. depends_on maps each other core file the override loads to its sha256."""
    doc = load_yaml(path)
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise SchemaError(f"{path} must be a mapping of core paths")
    lock = {}
    for rel, entry in doc.items():
        where = f"{path}: {rel}"
        _glob(rel, where)
        if not isinstance(entry, dict) or "base_sha256" not in entry \
                or set(entry) - LOCK_KEYS:
            raise SchemaError(f"{where} must have base_sha256, and may have host_fact and "
                              "depends_on")
        if not isinstance(entry["base_sha256"], str) or not SHA256_RE.match(entry["base_sha256"]):
            raise SchemaError(f"{where}.base_sha256 is not a sha256 hex digest")
        fact = entry.get("host_fact")
        if fact is not None:
            _str(fact, f"{where}.host_fact")
        deps = entry.get("depends_on") or {}
        if not isinstance(deps, dict):
            raise SchemaError(f"{where}.depends_on must map core paths to sha256 digests")
        for dep, digest in deps.items():
            _glob(dep, f"{where}.depends_on")
            if not isinstance(digest, str) or not SHA256_RE.match(digest):
                raise SchemaError(f"{where}.depends_on.{dep} is not a sha256 hex digest")
        lock[rel] = {"base_sha256": entry["base_sha256"], "host_fact": fact,
                     "depends_on": dict(deps)}
    return lock


def dump_lock(lock):
    """The lock file's text: sorted, host_fact written only where there is one."""
    doc = {}
    for rel in sorted(lock):
        entry = {"base_sha256": lock[rel]["base_sha256"]}
        if lock[rel].get("host_fact"):
            entry["host_fact"] = lock[rel]["host_fact"]
        if lock[rel].get("depends_on"):
            entry["depends_on"] = dict(sorted(lock[rel]["depends_on"].items()))
        doc[rel] = entry
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000) if doc else "{}\n"
