#!/usr/bin/env python3
"""Build the with/without plugin copies a behaviour-rule measurement compares.

A rule's effect is measured by running the same eval case against the plugin with the
rule and against a copy without it. That only measures the rule if the `without` copy
lost exactly the rule's text: a heading that was not found strips nothing, and a strip
that runs past its section strips a neighbour. So every strip entry must match exactly
once, the build stops on the first one that does not (naming the rule and the entry),
and every built copy is compared file by file against `with/` before it is kept.

Usage:
  eval-variants.py build <out> [--source DIR] [--cases DIR] [--variants FILE]
  eval-variants.py mentions <out> [--variants FILE]

build     writes <out>/with/ (a copy of the source plugin) and <out>/without-<rule>/ per
          rule in the variants file, each with every case folder of --cases copied to
          <variant>/evals/<case>/. <out> must be absent or empty. Nothing is written to
          <out> unless every variant builds. Ends with the `mentions` listing.
mentions  for each rule, lists the lines of <out>/without-<rule>/ that still mention it
          (case-insensitive, any of the rule's `mentions` terms, the copied cases under
          evals/ left out), with the grep that finds the same lines. Always exits 0 when
          <out> holds the builds: remaining mentions are a stated limit, not an error.

Defaults: --variants is evals/behaviour-rules/variants.json; --source and --cases come
from its `source` and `cases` keys, relative to the repo root.

Variants file: {"rules": [{"id", "name", "mentions": [terms], "strip": [entry, ...]}]},
each entry naming a `path` relative to the plugin and one of:
  "remove": "folder"                      the folder at path, whole
  "section": "<heading line>"             the heading line (exact, with its #s) through
                                          the line before the next heading of the same
                                          or a higher level; fenced code is not a heading
  "paragraph": "<opening words>"          the run of non-blank lines whose first line
                                          starts with the words (exact) after a blank
                                          line, through the next blank line; optional
                                          "in_section": "<heading line>" limits the search
  "json_array_item": {"key", "value"}     the one line holding that string in the
                                          top-level array `key`; the preceding comma is
                                          dropped when it was the last item, and the
                                          result must parse to the original minus it

Exit 0 on success; 1 on a strip that matches nothing or more than once, a copy that
differs from with/ outside its listed strips, a non-empty <out>, or bad input.
"""
import argparse
import filecmp
import json
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_VARIANTS = os.path.join(REPO, "evals", "behaviour-rules", "variants.json")
HEADING = re.compile(r"^(#{1,6})[ \t]+\S")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


class BuildError(Exception):
    pass


# ------------------------------------------------------------------ markdown spans

def read_lines(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read().splitlines(keepends=True)


def write_lines(path, lines):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(lines))


def scan(lines):
    """Per line: (is_heading, level, in_fence). Fence opener/closer lines count as fenced."""
    out, fence = [], None
    for line in lines:
        stripped = line.lstrip()
        if fence is None and (stripped.startswith("```") or stripped.startswith("~~~")):
            fence = stripped[:3]
            out.append((False, 0, True))
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            out.append((False, 0, True))
            continue
        m = HEADING.match(line)
        out.append((bool(m), len(m.group(1)) if m else 0, False))
    return out


def bare(line):
    return line.rstrip("\r\n")


def find_section(lines, info, heading, where):
    level = len(heading) - len(heading.lstrip("#"))
    if not level or not HEADING.match(heading):
        raise BuildError(f"{where}: section {heading!r} is not a Markdown heading line")
    hits = [i for i, line in enumerate(lines) if info[i][0] and bare(line) == heading]
    if not hits:
        raise BuildError(f"{where}: section heading not found: {heading!r}")
    if len(hits) > 1:
        raise BuildError(f"{where}: section heading {heading!r} matches {len(hits)} lines "
                         f"({', '.join(str(i + 1) for i in hits)}); it must match exactly one")
    start = hits[0]
    end = start + 1
    while end < len(lines) and not (info[end][0] and info[end][1] <= level):
        end += 1
    return start, end


def find_paragraph(lines, info, opening, where, lo=0, hi=None):
    hi = len(lines) if hi is None else hi
    hits = [i for i in range(lo, hi)
            if not info[i][2] and lines[i].startswith(opening)
            and (i == 0 or lines[i - 1].strip() == "")]
    if not hits:
        raise BuildError(f"{where}: paragraph opening not found: {opening!r}")
    if len(hits) > 1:
        raise BuildError(f"{where}: paragraph opening {opening!r} matches {len(hits)} paragraphs "
                         f"(lines {', '.join(str(i + 1) for i in hits)}); it must match exactly one")
    start = end = hits[0]
    while end < len(lines) and lines[end].strip() != "" and (
            end == start or not (info[end][0] or info[end][2])):
        end += 1
    if end < len(lines) and lines[end].strip() == "":
        end += 1
    return start, end


# ------------------------------------------------------------------ strip kinds

def safe_join(root, rel, where):
    norm = os.path.normpath(rel)
    if os.path.isabs(rel) or norm == ".." or norm.startswith(".." + os.sep) or norm == ".":
        raise BuildError(f"{where}: path {rel!r} must be relative and inside the plugin")
    return os.path.join(root, norm)


def strip_text(target, entry, where):
    if not os.path.isfile(target):
        raise BuildError(f"{where}: file not found: {entry['path']}")
    lines = read_lines(target)
    info = scan(lines)
    if "section" in entry:
        start, end = find_section(lines, info, entry["section"], where)
        what = f"section {entry['section']!r}"
    else:
        lo, hi = 0, None
        if "in_section" in entry:
            lo, hi = find_section(lines, info, entry["in_section"], where)
        start, end = find_paragraph(lines, info, entry["paragraph"], where, lo, hi)
        what = f"paragraph {entry['paragraph']!r}"
        if "in_section" in entry:
            what += f" in {entry['in_section']!r}"
    write_lines(target, lines[:start] + lines[end:])
    return f"{what} removed (lines {start + 1}-{end})"


def strip_json_item(target, entry, where):
    spec = entry["json_array_item"]
    key, value = spec.get("key"), spec.get("value")
    if not os.path.isfile(target):
        raise BuildError(f"{where}: file not found: {entry['path']}")
    with open(target, encoding="utf-8", newline="") as fh:
        text = fh.read()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BuildError(f"{where}: {entry['path']} is not valid JSON: {exc}")
    arr = data.get(key) if isinstance(data, dict) else None
    if not isinstance(arr, list):
        raise BuildError(f"{where}: {entry['path']} has no top-level array {key!r}")
    if arr.count(value) != 1:
        raise BuildError(f"{where}: array entry not found exactly once: {value!r} in "
                         f"{entry['path']} {key!r} (found {arr.count(value)})")
    lines = text.splitlines(keepends=True)
    literal = json.dumps(value, ensure_ascii=False)
    hits = [i for i, line in enumerate(lines) if bare(line).strip() in (literal, literal + ",")]
    if len(hits) != 1:
        raise BuildError(f"{where}: array entry {value!r} must sit alone on exactly one line "
                         f"of {entry['path']} (found {len(hits)})")
    i = hits[0]
    if not bare(lines[i]).strip().endswith(","):
        j = i - 1
        while j >= 0 and lines[j].strip() == "":
            j -= 1
        body = bare(lines[j])
        if j < 0 or not body.rstrip().endswith(","):
            raise BuildError(f"{where}: cannot drop the comma before {value!r} in {entry['path']}")
        cut = len(body.rstrip()) - 1
        lines[j] = body[:cut] + body[cut + 1:] + lines[j][len(body):]
    new = "".join(lines[:i] + lines[i + 1:])
    expected = dict(data)
    expected[key] = [v for v in arr if v != value]
    try:
        ok = json.loads(new) == expected
    except ValueError:
        ok = False
    if not ok:
        raise BuildError(f"{where}: removing {value!r} from {entry['path']} did not leave valid "
                         f"JSON equal to the original minus that entry")
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    return f"array {key!r} entry {value!r} removed (line {i + 1})"


def apply_strip(variant_dir, entry, where):
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise BuildError(f"{where}: a strip entry needs a string 'path': {entry!r}")
    kinds = [k for k in ("remove", "section", "paragraph", "json_array_item") if k in entry]
    if len(kinds) != 1:
        raise BuildError(f"{where}: strip entry for {entry['path']!r} must name exactly one of "
                         f"remove/section/paragraph/json_array_item, got {kinds or 'none'}")
    if "in_section" in entry and kinds[0] != "paragraph":
        raise BuildError(f"{where}: 'in_section' applies only to a paragraph entry")
    target = safe_join(variant_dir, entry["path"], where)
    if kinds[0] == "remove":
        if entry["remove"] != "folder":
            raise BuildError(f"{where}: unknown remove kind {entry['remove']!r}")
        if not os.path.isdir(target):
            raise BuildError(f"{where}: folder not found: {entry['path']}")
        shutil.rmtree(target)
        return "folder removed"
    if kinds[0] == "json_array_item":
        return strip_json_item(target, entry, where)
    return strip_text(target, entry, where)


# ------------------------------------------------------------------ build

def load_variants(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise BuildError(f"cannot read variants file {path}: {exc}")
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules:
        raise BuildError(f"{path}: needs a non-empty 'rules' list")
    seen = set()
    for rule in rules:
        rid = rule.get("id") if isinstance(rule, dict) else None
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", rid) or rid in seen:
            raise BuildError(f"{path}: every rule needs a unique id of letters, digits, '.', '_' "
                             f"or '-': {rule!r}")
        seen.add(rid)
        if not isinstance(rule.get("strip"), list) or not rule["strip"]:
            raise BuildError(f"{path}: rule {rid} has no strip entries (a variant that strips "
                             f"nothing measures nothing)")
        terms = rule.get("mentions")
        if not isinstance(terms, list) or not terms or not all(isinstance(x, str) and x.strip() for x in terms):
            raise BuildError(f"{path}: rule {rid} 'mentions' must be a non-empty list of non-empty "
                             f"terms (the remaining-mentions listing is the measurement's stated limit)")
    return data


def resolve(cli, data, key, label):
    if cli:
        return os.path.abspath(cli)
    if isinstance(data.get(key), str):
        return os.path.join(REPO, data[key])
    raise BuildError(f"no {label} given: pass --{key} or set {key!r} in the variants file")


def list_cases(cases_dir):
    if not os.path.isdir(cases_dir):
        raise BuildError(f"cases folder not found: {cases_dir}")
    cases = []
    for name in sorted(os.listdir(cases_dir)):
        path = os.path.join(cases_dir, name)
        if not os.path.isdir(path):
            continue
        if not os.path.isfile(os.path.join(path, "case.yaml")):
            raise BuildError(f"case folder {name} has no case.yaml: {path}")
        cases.append(name)
    if not cases:
        raise BuildError(f"no case folder with a case.yaml in {cases_dir}")
    return cases


def tree_files(root):
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            out.add(os.path.relpath(os.path.join(dirpath, name), root))
        for name in dirnames:
            if os.path.islink(os.path.join(dirpath, name)):
                out.add(os.path.relpath(os.path.join(dirpath, name), root))
    return out


def verify_variant(with_dir, variant_dir, rule):
    """The variant is with/ minus its listed strips: nothing else may differ."""
    removed = [os.path.normpath(e["path"]) for e in rule["strip"] if "remove" in e]
    edited = {os.path.normpath(e["path"]) for e in rule["strip"] if "remove" not in e}
    under = lambda f: any(f == d or f.startswith(d + os.sep) for d in removed)
    wfiles = {f for f in tree_files(with_dir) if not under(f)}
    vfiles = tree_files(variant_dir)
    if wfiles != vfiles:
        raise BuildError(f"rule {rule['id']}: without-{rule['id']}/ file set differs from with/ "
                         f"beyond the removed folders: {sorted(wfiles ^ vfiles)[:10]}")
    for f in sorted(vfiles):
        same = filecmp.cmp(os.path.join(with_dir, f), os.path.join(variant_dir, f), shallow=False)
        if f in edited and same:
            raise BuildError(f"rule {rule['id']}: listed file {f} is unchanged after its strips")
        if f not in edited and not same:
            raise BuildError(f"rule {rule['id']}: {f} changed but is not a listed strip")


def build(args):
    variants_path = os.path.abspath(args.variants or DEFAULT_VARIANTS)
    data = load_variants(variants_path)
    source = resolve(args.source, data, "source", "source plugin")
    cases_dir = resolve(args.cases, data, "cases", "cases folder")
    if not os.path.isdir(source):
        raise BuildError(f"source plugin folder not found: {source}")
    cases = list_cases(cases_dir)
    out = os.path.abspath(args.out)
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        raise BuildError(f"output folder is not empty (refusing to write into it): {out}")
    parent = os.path.dirname(out)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".eval-variants-", dir=parent)
    try:
        with_dir = os.path.join(staging, "with")
        shutil.copytree(source, with_dir, symlinks=True, ignore=IGNORE)
        for case in cases:
            dest = os.path.join(with_dir, "evals", case)
            if os.path.exists(dest):
                raise BuildError(f"the source plugin already has evals/{case}; refusing to overwrite it")
            shutil.copytree(os.path.join(cases_dir, case), dest, symlinks=True, ignore=IGNORE)
        print(f"with/            copy of {source} + {len(cases)} case(s): {', '.join(cases)}")
        for rule in data["rules"]:
            vdir = os.path.join(staging, f"without-{rule['id']}")
            shutil.copytree(with_dir, vdir, symlinks=True)
            for n, entry in enumerate(rule["strip"], 1):
                where = f"rule {rule['id']} strip {n} ({entry.get('path') if isinstance(entry, dict) else entry})"
                done = apply_strip(vdir, entry, where)
                print(f"without-{rule['id']}/  {entry['path']}: {done}")
            verify_variant(with_dir, vdir, rule)
        if os.path.isdir(out):
            for name in sorted(os.listdir(staging)):
                os.rename(os.path.join(staging, name), os.path.join(out, name))
            os.rmdir(staging)
        else:
            os.rename(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"built {1 + len(data['rules'])} variant(s) in {out}")
    print()
    print_mentions(out, data)
    return 0


# ------------------------------------------------------------------ mentions

def print_mentions(out, data):
    for rule in data["rules"]:
        vdir = os.path.join(out, f"without-{rule['id']}")
        terms = [t for t in rule.get("mentions", []) if isinstance(t, str) and t]
        if not os.path.isdir(vdir):
            raise BuildError(f"no build for rule {rule['id']}: {vdir}")
        hits = []
        for rel in sorted(tree_files(vdir)):
            if "evals" in rel.split(os.sep)[:-1]:
                continue
            path = os.path.join(vdir, rel)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                raw = fh.read()
            if b"\0" in raw:
                continue
            for n, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
                low = line.lower()
                if any(t.lower() in low for t in terms):
                    hits.append(f"{rule['id']} {rel}:{n}: {line.strip()[:160]}")
        grep = "grep -rniF --exclude-dir=evals " + " ".join(f"-e {shell_quote(t)}" for t in terms)
        print(f"# {rule['id']} {rule.get('name', '')}: {len(hits)} remaining mention(s); "
              f"found by: {grep} {shell_quote(vdir)}")
        for h in hits:
            print(h)
    return 0


def shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def mentions(args):
    data = load_variants(os.path.abspath(args.variants or DEFAULT_VARIANTS))
    out = os.path.abspath(args.out)
    if not os.path.isdir(out):
        raise BuildError(f"build folder not found: {out}")
    return print_mentions(out, data)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write with/ and without-<rule>/ into <out>")
    b.add_argument("out")
    b.add_argument("--source", help="plugin folder to copy (default: variants file 'source')")
    b.add_argument("--cases", help="folder of case folders (default: variants file 'cases')")
    b.add_argument("--variants", help="strip list (default: evals/behaviour-rules/variants.json)")
    m = sub.add_parser("mentions", help="list each rule's remaining mentions in its without build")
    m.add_argument("out")
    m.add_argument("--variants", help="strip list (default: evals/behaviour-rules/variants.json)")
    args = ap.parse_args(argv)
    try:
        return build(args) if args.cmd == "build" else mentions(args)
    except BuildError as exc:
        print(f"eval-variants: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
