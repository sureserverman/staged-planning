#!/usr/bin/env python3
"""Validate references/stack-routing.md against what this plugin ships.

Every cell of every table in the file is scanned, header rows included. In a
column whose header names an agent or a skill, each backticked name must resolve
to one of:
  - a built-in subagent (general, explore),
  - an agent this plugin ships (<plugin root>/agents/<name>.md), dispatched by its
    bare <name>,
  - a skill this plugin ships (<plugin root>/skills/*/SKILL.md).

Every other `<plugin>:<name>` id, in any cell and backticked or not, must be in this
plugin's namespace and name an agent or skill shipped here.

Anything else is drift: a renamed/removed agent, a typo, or a name from another
plugin. The table names no other plugin's agent or skill: a stack row says to
prefer an installed agent whose description matches the stack, otherwise
general, so the route works for a user who installs only this plugin.

OPENCODE FORK. OpenCode names an agent by its file name (agents/<name>.md carries no
name field), has no plugin namespacing, and its built-in subagents are `general` and
`explore`. So this fork reads the shipped agents from their file names, accepts the bare
name as the dispatched form and refuses a `planning:<name>` agent id, and checks the
OpenCode built-ins. Everything else is the core's.

The plugin root is this script's own plugin (`../../..`): the built plugin directory.
This fork's source folder holds only the agents and skills OpenCode overrides, not the whole package, so it is checked in the build output. A wider root (a marketplace of
several plugins) would make every neighbour "shipped here" and so hide exactly the
outside names this check exists to find.

Exit 0 = clean, 1 = drift found. No third-party deps; stdlib only.
"""

import os
import re
import sys

BUILTINS = {"general", "explore"}

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, "..", "references", "stack-routing.md")
# scripts/ -> dispatching-parallel-agents/ -> skills/ -> plugin root
PLUGIN_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PLUGIN = "planning"

TOKEN = re.compile(r"`([^`]+)`")
# A `<plugin>:<name>` id, backticked or not. Every table cell is searched for these.
ID = re.compile(r"(?<![\w.:/<-])([A-Za-z0-9][\w-]*):([A-Za-z0-9][\w-]*)(?![\w:>-])")


def collect_shipped(root=None):
    """Return (agents: name->plugin, skills: set[name]) this plugin ships."""
    root = root or PLUGIN_ROOT
    agents, skills = {}, set()
    agents_dir = os.path.join(root, "agents")
    for fn in sorted(os.listdir(agents_dir)) if os.path.isdir(agents_dir) else []:
        # OpenCode registers an agent under its file name.
        if not fn.endswith(".md") or fn == "README.md":
            continue
        agents[fn[:-len(".md")]] = PLUGIN
    skills_dir = os.path.join(root, "skills")
    for name in sorted(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else []:
        if os.path.isfile(os.path.join(skills_dir, name, "SKILL.md")):
            skills.add(name)
    return agents, skills


def is_separator(cells):
    return bool(cells) and set("".join(cells)) <= set("-: ") and "-" in "".join(cells)


def column_kind(header):
    h = header.lower()
    if "skill" in h:
        return "skill"
    if "agent" in h:
        return "agent"
    return None


def table_cells(text):
    """Yield (kind, cell, is_header) for every cell of every row of every table.

    `kind` is "agent" or "skill" when the column's header names one, else None.
    A table's header is its first row when the second row is a separator; a
    table without one has no typed columns, and all its rows are data.
    """
    blocks, block = [], []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif block:
            blocks.append(block)
            block = []
    for block in blocks:
        kinds = []
        if len(block) > 1 and is_separator(block[1]):
            kinds = [column_kind(h) for h in block[0]]
            for cell in block[0]:
                yield None, cell, True
            rows = block[2:]
        else:
            rows = block
        for cells in rows:
            if is_separator(cells):
                continue
            for i, cell in enumerate(cells):
                yield (kinds[i] if i < len(kinds) else None), cell, False


def classify_any(name, agents, skills):
    """An id in a cell whose column names neither an agent nor a skill."""
    plugin, _, bare = name.partition(":")
    if plugin != PLUGIN:
        return "FAIL", (f"'{name}' names another plugin; route the stack to an installed "
                        "agent whose description matches it, otherwise general")
    if agents.get(bare) == PLUGIN or bare in skills:
        return "OK", "agent or skill shipped by this plugin"
    return "FAIL", f"'{name}' is in this plugin's namespace and no such agent or skill ships here"


def classify(name, agents, skills, want_skill):
    if name in BUILTINS:
        return "OK", "built-in subagent"
    if ":" in name:  # namespaced plugin:name — the form Claude Code dispatches
        plugin, _, bare = name.partition(":")
        if plugin != PLUGIN:
            return "FAIL", (f"'{name}' names another plugin; route the stack to an installed "
                            "agent whose description matches it, otherwise general")
        if want_skill:
            return ("OK", "skill shipped by this plugin") if bare in skills else \
                ("FAIL", f"'{name}' is in this plugin's namespace and no such skill ships here")
        if agents.get(bare) == PLUGIN:
            return "FAIL", (f"'{name}': OpenCode has no plugin namespacing; dispatch the "
                            f"agent by its bare name '{bare}'")
        return "FAIL", f"'{name}' is in this plugin's namespace and no such agent ships here"
    if want_skill:
        if name in skills:
            return "OK", "skill shipped by this plugin"
        return "FAIL", "skill not shipped by this plugin"
    if name in agents:
        return "OK", "plugin agent (bare, as OpenCode dispatches it)"
    return "FAIL", "bare agent name that is neither built in nor shipped here"


def main():
    with open(TABLE, encoding="utf-8") as fh:
        text = fh.read()
    agents, skills = collect_shipped()
    if not agents or not skills:
        print(f"FAIL: found {len(agents)} agent(s) and {len(skills)} skill(s) under "
              f"{PLUGIN_ROOT} — not this plugin's tree, so nothing can be validated")
        return 1

    results = []
    for kind, cell, is_header in table_cells(text):
        loose = cell
        if kind and not is_header:
            for tok in TOKEN.findall(cell):
                sev, why = classify(tok, agents, skills, want_skill=(kind == "skill"))
                results.append((sev, kind, tok, why))
            loose = TOKEN.sub(" ", cell)
        # Any other cell, and any id outside backticks: every `<plugin>:<name>` must be ours.
        for m in ID.finditer(loose):
            tok = m.group(0)
            sev, why = classify_any(tok, agents, skills)
            results.append((sev, "id", tok, why))

    # de-dup, keep worst severity per (kind, token)
    rank = {"FAIL": 0, "WARN": 1, "OK": 2}
    best = {}
    for sev, kind, tok, why in results:
        key = (kind, tok)
        if key not in best or rank[sev] < rank[best[key][0]]:
            best[key] = (sev, why)

    fails = warns = 0
    for (kind, tok), (sev, why) in sorted(best.items()):
        if sev == "OK":
            continue
        if sev == "FAIL":
            fails += 1
        else:
            warns += 1
        print(f"  [{sev}] {kind:5} {tok:32} {why}")

    total = len(best)
    if total == 0:
        print(f"FAIL: no agent or skill names parsed from the routing table in {TABLE} — "
              "an empty sweep validates nothing")
        return 1
    print(f"\n{total} unique references checked — {fails} FAIL, {warns} WARN")
    if fails:
        print("\nFix each FAIL by naming an agent or skill this plugin ships, a built-in,")
        print("or the rule: an installed agent whose description matches the stack.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
