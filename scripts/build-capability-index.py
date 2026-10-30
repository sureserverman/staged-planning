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

A slash command a host's mod registers at session start (`$.command.register`)
has no file under `commands/`, so that scan can't see it. Each mod declares its
commands in `hosts/<host>/add/hooks/mod/registered-commands.json`; they are
listed under `registered_commands`, not `components`, because there is no body
to Read-and-follow — only a name a person types. check-capability-index.py holds
the declared list to the registrations in the mod's sources
(`registration_drift`).

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


# A mod directory, and the file in it declaring the commands the mod registers.
MOD_DIRS = "hosts/*/add/hooks/mod"
DECLARED_COMMANDS = "registered-commands.json"
# The registration call. Every way to reach `command.register` is a hit — a call, a
# generic or optional call, a chained or computed member, an alias — read on the raw
# text and then placed by _lex. A hit in live code must be a call passed exactly one
# object literal, or it fails: an unread registration never passes.
_REGISTER = re.compile(r"\bcommand\s*(?:\?\s*\.|\.)\s*register\b"
                       r"|\bcommand\s*\[\s*(['\"`])register\1\s*\]")
# `$.command` reached for anything but register (`const { register } = $.command`).
_COMMAND_OTHER = re.compile(r"\$\s*\.\s*command\b(?!\s*(?:\?\s*)?\.\s*register\b"
                            r"|\s*\[\s*['\"`]register)")
# Every source a mod can register from, at any depth. A `.test.`/`.spec.` source, a
# `__tests__/` directory and `node_modules/` hold doubles and dependencies, not the
# mod's commands. Build output is read like a source; keep it out of the mod tree.
MOD_SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
_DOUBLE = re.compile(r"\.(?:test|spec)\.[^.]+$")
_SKIP_DIRS = {"node_modules", "__tests__"}
# After one of these, a `/` starts a regex literal; after anything else it divides.
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
                   "throw", "case", "do", "else", "yield", "await"}


def _lex(text):
    """(kinds, comment_start): per character of `text`, "c" for code, "m" for a
    comment, "s" for a string, template or regex literal; and, for a comment
    character, the index its comment starts at.

    Enough of JS/TS to place a registration, not a parser. Regex literals are told
    from division by the code before the `/`; `'` and `"` strings end at a newline,
    as they must in JS, so a quote that opens none (JSX text, `Don't`) misreads one
    line at most; template `${...}` nests. What it still misreads — a regex after
    `)`, as in `if (x) /re/.test(s)` — is why registration_drift fails a hit it
    cannot place rather than skipping it.
    """
    n = len(text)
    kinds, cstart = ["c"] * n, [None] * n
    tmpl = []          # brace depth of each open `${`, innermost last
    i, prev = 0, ""    # prev: last significant code character, or a keyword marker
    word = re.compile(r"[A-Za-z_$][\w$]*")

    def mark(a, b, kind, start=None):
        for k in range(a, b):
            if text[k] != "\n":
                kinds[k] = kind
                cstart[k] = start

    def string_end(i, q):
        j = i + 1
        while j < n and text[j] != q:
            if text[j] == "\\":
                j += 2
            elif text[j] == "\n":
                return j
            else:
                j += 1
        return min(j + 1, n)

    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            mark(i, j, "m", i)
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            mark(i, j, "m", i)
            i = j
            continue
        if c in "'\"":
            j = string_end(i, c)
            mark(i, j, "s")
            i, prev = j, "x"
            continue
        if c == "`" or (c == "}" and tmpl and tmpl[-1] == 0):
            if c == "}":
                tmpl.pop()
            j = i + 1
            while j < n and text[j] != "`" and not text.startswith("${", j):
                j += 2 if text[j] == "\\" else 1
            if text.startswith("${", j):
                mark(i if c == "`" else i + 1, j + 1, "s")
                tmpl.append(0)
                i, prev = j + 2, "{"
                continue
            mark(i if c == "`" else i + 1, min(j + 1, n), "s")
            i, prev = min(j + 1, n), "x"
            continue
        if c == "/" and (prev == "" or prev in _REGEX_AFTER or prev == "kw"):
            j, in_class = i + 1, False
            while j < n and text[j] != "\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                elif text[j] == "/" and not in_class:
                    break
                j += 1
            j = min(j + 1, n) if j < n and text[j] == "/" else j
            mark(i, j, "s")
            i, prev = j, "x"
            continue
        m = word.match(text, i)
        if m:
            i, prev = m.end(), ("kw" if m.group() in _REGEX_KEYWORDS else "x")
            continue
        if tmpl and c == "{":
            tmpl[-1] += 1
        elif tmpl and c == "}":
            tmpl[-1] -= 1
        prev = c if c in _REGEX_AFTER else "x"
        i += 1
    return kinds, cstart


def _mod_sources(mod_dir):
    """(sources, links): every JS/TS source under `mod_dir` that is the mod's, at
    any depth, sorted; and every symlink met on the way, which is not followed."""
    found, links = [], []
    for dirpath, dirnames, files in os.walk(mod_dir):
        keep = []
        for d in sorted(dirnames):
            if d in _SKIP_DIRS:
                continue
            path = os.path.join(dirpath, d)
            (links if os.path.islink(path) else keep).append(path)
        dirnames[:] = [os.path.basename(d) for d in keep]
        for f in files:
            path = os.path.join(dirpath, f)
            source = f.endswith(MOD_SOURCE_EXTS) and not _DOUBLE.search(f)
            # A dangling link to a directory is listed here, among the files.
            if os.path.islink(path) and (source or not os.path.isfile(path)):
                links.append(path)
            elif source:
                found.append(path)
    return sorted(found), sorted(links)


def _closing(code, i, open_ch, close_ch):
    """Index of the `close_ch` matching the `open_ch` at `i` in `code`, or None."""
    depth = 0
    for k in range(i, len(code)):
        if code[k] == open_ch:
            depth += 1
        elif code[k] == close_ch:
            depth -= 1
            if depth == 0:
                return k
    return None


def _object_argument(code, i):
    """(open, close) of the one object literal the call after `register` at `i` is
    passed — through an optional `?.` and a generic `<...>` — or None."""
    m = re.compile(r"\s*(?:\?\s*\.\s*)?").match(code, i)
    i = m.end()
    if code.startswith("<", i):
        end = _closing(code, i, "<", ">")
        if end is None:
            return None
        i = end + 1
    m = re.compile(r"\s*\(\s*\{").match(code, i)
    if not m:
        return None
    close = _closing(code, m.end() - 1, "{", "}")
    if close is None or not re.compile(r"\s*\)").match(code, close + 1):
        return None
    return m.end() - 1, close


def _literal(body, code, key):
    """The string literal the top-level `key:` of an object literal holds,
    unescaped; None when the key is absent or its value is not a literal. `code`
    is `body` with comments and literals blanked, so nesting is counted on code
    only and a nested object's `key:` is not this one's."""
    for m in re.finditer(rf"\b{key}\s*:", code):
        before = code[:m.start()]
        if sum(before.count(o) - before.count(c) for o, c in ("{}", "[]", "()")):
            continue
        v = re.compile(r"\s*(['\"])((?:\\.|(?!\1)[^\\\n])*)\1"
                       r"|\s*`((?:\\.|[^`\\$]|\$(?!\{))*)`", re.S).match(body, m.end())
        if not v:
            return None
        raw = v.group(2) if v.group(1) else v.group(3)
        return re.sub(r"\\(.)", r"\1", raw)
    return None


def declared_commands(path, rel):
    """{name: description} from a mod's registered-commands.json. A malformed
    file raises loudly, naming it, like invalid frontmatter does."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        cmds = {c["name"]: _collapse(c["description"]) for c in data["commands"]}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SystemExit(f"error: {rel} is not a {{\"commands\": [{{name, description}}]}} "
                         f"list: {exc}")
    return cmds


def registered_commands(root):
    """The commands every mod declares, as index entries sorted by (plugin, name)."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, MOD_DIRS, DECLARED_COMMANDS))):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for name, desc in declared_commands(path, rel).items():
            out.append({"plugin": plugin_name(rel), "name": name,
                        "description": desc, "path": rel})
    out.sort(key=lambda c: (c["plugin"], c["name"]))
    return out


def registration_drift(root):
    """Each way a mod's registrations and its declared list disagree, one line
    each, naming the command and its file:line: registered but not declared,
    declared but not registered, a description that differs. A hit the check cannot
    read fails rather than passes: a registration not passed exactly one object
    literal, one whose name is not a string literal, one inside a string, template
    or regex literal, one in a comment that starts on an earlier line of code, any
    other use of `$.command`, and a symlink in the mod tree."""
    problems = []
    for mod_dir in sorted(glob.glob(os.path.join(root, MOD_DIRS))):
        decl = os.path.join(mod_dir, DECLARED_COMMANDS)
        decl_rel = os.path.relpath(decl, root).replace(os.sep, "/")
        declared = declared_commands(decl, decl_rel) if os.path.exists(decl) else {}
        unread = f"can't be checked against {decl_rel}"
        registered = {}
        sources, links = _mod_sources(mod_dir)
        for link in links:
            problems.append(f"{os.path.relpath(link, root).replace(os.sep, '/')}: a symlink "
                            f"in the mod tree is not followed, so its registrations {unread}")
        for src in sources:
            rel = os.path.relpath(src, root).replace(os.sep, "/")
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
            kinds, cstart = _lex(text)
            code = "".join(ch if k == "c" else (ch if ch == "\n" else " ")
                           for ch, k in zip(text, kinds))

            def line(pos):
                return text.count("\n", 0, pos) + 1

            hits = [(m, True) for m in _REGISTER.finditer(text)]
            hits += [(m, False) for m in _COMMAND_OTHER.finditer(text)]
            for m, is_register in sorted(hits, key=lambda h: h[0].start()):
                pos, where = m.start(), f"{rel}:{line(m.start())}"
                kind = kinds[pos]
                if kind == "m":
                    own_line = text[text.rfind("\n", 0, pos) + 1:pos].lstrip()
                    if line(cstart[pos]) == line(pos) or own_line.startswith(("*", "//")):
                        continue
                    problems.append(f"{where}: a command registration in a comment opened on "
                                    f"an earlier line of code {unread}")
                    continue
                if kind == "s":
                    problems.append(f"{where}: `command.register` inside a string, template "
                                    f"or regex literal {unread}")
                    continue
                arg = _object_argument(code, m.end()) if is_register else None
                if arg is None:
                    what = ("a command registration not passed exactly one object literal"
                            if is_register else "a use of $.command other than a call to register")
                    problems.append(f"{where}: {what} {unread}")
                    continue
                body, body_code = text[arg[0] + 1:arg[1]], code[arg[0] + 1:arg[1]]
                name = _literal(body, body_code, "name")
                if name is None:
                    problems.append(f"{where}: a command registration whose name is not a "
                                    f"string literal {unread}")
                    continue
                registered[name] = (where, _literal(body, body_code, "description"))
        for name, (where, desc) in sorted(registered.items()):
            if name not in declared:
                problems.append(f"{where}: registers /{name}, absent from {decl_rel}")
            elif desc is None or _collapse(desc) != declared[name]:
                problems.append(f"{where}: /{name} description differs from {decl_rel} "
                                f"(mod: {desc!r}, declared: {declared[name]!r})")
        for name in sorted(set(declared) - set(registered)):
            problems.append(f"{decl_rel}: declares /{name}, which no mod source registers")
    return problems


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
    return {"schema": SCHEMA_VERSION, "components": components,
            "registered_commands": registered_commands(root)}


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
