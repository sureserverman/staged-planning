#!/usr/bin/env python3
"""Qualify a built Codex plugin by installing it into a Codex home and asking Codex what loaded.

Every case is tagged `needs_model`. The `needs_model: false` cases run here, with no model
turn: install from a local marketplace checkout, compare the installed cache and what
Codex discovers against the build's own output, install the agent roles, then disable,
remove and unregister. The `needs_model: true` cases are the clean-machine run's
(`scripts/clean-machine-run.sh --host codex`); this harness lists them and records them as
not run, never as passed.

The plugin under test comes in by identity (`--plugin-id <plugin>@<marketplace>`, default
planning@staged-planning) with its marketplace checkout. A second plugin comes in the same
way, by argument, so this code names no other plugin or repo.

Usage:
  qualify.py --list
  qualify.py --run --codex-home H --workdir D --marketplace M [--plugin-id ID]
             [--extra-marketplace M2 --extra-plugin ID2]... [--evidence E] [--codex BIN]
             [--owner-codex-home O]
  qualify.py --compare-evidence E

--run exits 0 only when every `needs_model: false` case passed for every plugin. It runs
against the --codex-home it is given, and refuses the invoking user's own ($CODEX_HOME, or
~/.codex, or --owner-codex-home); scripts/host-install-check.py --isolated is the caller
that makes it a scratch dir. Every codex call and installer gets HOME set to the parent of
--codex-home, CODEX_HOME, and from the caller's environment only PATH, the locale, TERM
and TMPDIR. --evidence writes E/results.json (paths recorded as given), and refuses a dir
inside this repo or a plugin's marketplace checkout. --compare-evidence re-reads that file and
exits 1 when the build's current output no longer matches what Codex discovered: a skill
added to or removed from the output, or a hook definition changed. Exit 2 is an input this
harness cannot judge.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native  # noqa: E402

DEFAULT_ID = "planning@staged-planning"
SCHEMA = "codex-qualify.v1"
CLEAN_RUN = "scripts/clean-machine-run.sh --host codex"

# (id, needs_model, what passing means). Order is run order within a plugin.
CASES = [
    ("package-static", False, "the built plugin's hook targets, relative Markdown links, "
     "plugin-root references and Python imports resolve inside it"),
    ("marketplace-add", False, "`codex plugin marketplace add` registers the checkout under "
     "the identity's marketplace name"),
    ("plugin-add", False, "`codex plugin add` returns the identity, with an installedPath "
     "inside the Codex home's plugin cache"),
    ("installed-integrity", False, "the installed cache holds the build's output byte for byte"),
    ("plugin-listed", False, "`codex plugin list` reports the identity installed and enabled"),
    ("skill-discovery", False, "app-server skills/list shows exactly the build's emitted "
     "skills, enabled, each under the installed cache"),
    ("hook-discovery", False, "app-server hooks/list shows exactly the hooks.json definitions "
     "(none for a plugin that ships no hooks.json)"),
    ("hook-untrusted", False, "every discovered hook starts untrusted; this harness trusts none"),
    ("hook-rendering", False, "each discovered hook's command, matcher, timeout and source "
     "path match its hooks.json definition, rooted at the cache"),
    ("agent-install", False, "scripts/install-agents.py --codex-home <home> --install exits 0 "
     "(not applicable to a plugin that ships no agents/*.toml)"),
    ("agent-report", False, "install-agents.py --json reports every shipped role present"),
    ("plugin-disable", False, "with the plugin disabled in the home's config, none of its "
     "skills or hooks stays enabled, and every other plugin's still is"),
    ("plugin-remove", False, "`codex plugin remove` deletes the cache, and discovery no "
     "longer shows the plugin"),
    ("marketplace-remove", False, "`codex plugin marketplace remove` unregisters the marketplace"),
    ("owner-home-untouched", False, "the invoking user's Codex config, agent roles and plugin "
     "cache hash the same before and after"),
    ("model-records-land", True, "a brainstorm -> plan -> execute -> gate flow puts its "
     "records where the resolver says (" + CLEAN_RUN + ")"),
    ("model-skills-seen", True, "the plugin's skills named in the prompt as "
     "$<plugin>:<skill> resolve from the installed cache; Codex injects every mentioned "
     "skill, so the flow itself is shown by model-records-land (" + CLEAN_RUN + ")"),
    ("model-outside-changes", True, "the flow writes nothing outside its throwaway home and "
     "toy repo (" + CLEAN_RUN + ")"),
]
NON_MODEL = [c[0] for c in CASES if not c[1]]
REPO = Path(__file__).resolve().parents[3]
KEEP_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR")
EVENT_NAMES = {"Stop": "stop", "PreToolUse": "preToolUse", "SubagentStart": "subagentStart",
               "SubagentStop": "subagentStop", "SessionStart": "sessionStart",
               "UserPromptSubmit": "userPromptSubmit", "PostToolUse": "postToolUse"}
HOOK_COMMAND = re.compile(r'^bash "\$\{PLUGIN_ROOT\}/([^"]+)"$')
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
# A link shown as an example sits in code: a fenced block or an inline span.
MD_CODE = re.compile(r"^(```|~~~).*?^\1[^\n]*$|`[^`\n]*`", re.S | re.M)


class Unjudgeable(Exception):
    """Input this harness cannot honestly judge: exit 2."""


def parse_identity(ident):
    name, sep, market = ident.partition("@")
    if not sep or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name or "") \
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", market or ""):
        raise Unjudgeable(f"--plugin-id wants <plugin>@<marketplace>, got {ident!r}")
    return name, market


def built_dir(marketplace, ident):
    """The plugin's output dir, read from the checkout's Codex marketplace manifest."""
    name, market = parse_identity(ident)
    manifest = Path(marketplace) / ".agents/plugins/marketplace.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Unjudgeable(f"cannot read {manifest}: {exc}") from exc
    if data.get("name") != market:
        raise Unjudgeable(f"{manifest} is named {data.get('name')!r}, not {market!r}")
    entries = [p for p in data.get("plugins", []) if p.get("name") == name]
    if len(entries) != 1:
        raise Unjudgeable(f"{manifest} lists {len(entries)} entries named {name!r}")
    source = entries[0].get("source", {})
    rel = source.get("path") if isinstance(source, dict) else source
    if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise Unjudgeable(f"{manifest}: {name!r} has no local relative source path")
    out = (Path(marketplace) / rel).resolve()
    if not out.is_dir():
        raise Unjudgeable(f"{name!r}'s output {out} is not a directory; build it first")
    return out


def emitted_skills(out, name):
    return sorted(f"{name}:{p.parent.name}" for p in (out / "skills").glob("*/SKILL.md"))


def hook_definitions(out):
    """[(event, matcher, command, timeout)] from the plugin's hooks.json, or [] with none."""
    path = out / "hooks/hooks.json"
    if not path.exists():
        return []
    try:
        hooks = json.loads(path.read_text())["hooks"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Unjudgeable(f"cannot read {path}: {exc!r}") from exc
    rows = []
    for event, groups in hooks.items():
        for group in groups:
            for handler in group.get("hooks", []):
                rows.append((EVENT_NAMES.get(event, event), group.get("matcher"),
                             handler.get("command"), handler.get("timeout")))
    return rows


def tree_hashes(root):
    root = Path(root)
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def owner_fingerprint(home):
    """A digest of the owner's Codex home: config.toml, agents/ and plugins/, so a run
    that changes any of them is caught."""
    home = Path(home)
    paths = [home / "config.toml"]
    for sub in ("agents", "plugins"):
        if (home / sub).is_dir():
            paths += [p for p in (home / sub).rglob("*") if p.is_file()]
    h = hashlib.sha256()
    try:
        for p in sorted(paths):
            if p.is_file():
                h.update(str(p).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    except OSError as exc:
        raise Unjudgeable(f"cannot fingerprint {home}: {exc}") from exc
    return h.hexdigest()


def package_static(out, name):
    """Problems with references inside the built plugin, as a list of strings."""
    problems = []
    for event, _, command, _ in hook_definitions(out):
        m = HOOK_COMMAND.match(command or "")
        if not m:
            problems.append(f"hook {event}: command {command!r} is not bash \"${{PLUGIN_ROOT}}/<path>\"")
        elif not (out / m.group(1)).is_file():
            problems.append(f"hook {event}: target {m.group(1)} is missing")
    root_ref = re.compile(r"<" + re.escape(name) + r"-plugin>/([A-Za-z0-9_./-]+)")
    for path in sorted(out.rglob("*.md")):
        text = path.read_text(errors="replace")
        rel = path.relative_to(out)
        for target in MD_LINK.findall(MD_CODE.sub("", text)):
            target = target.split("#")[0]
            if not target or ":" in target or "<" in target or target.startswith("/"):
                continue
            if not (path.parent / target).exists():
                problems.append(f"{rel}: Markdown link {target} does not resolve")
        for target in root_ref.findall(text):
            if not (out / target.rstrip(".")).exists():
                problems.append(f"{rel}: <{name}-plugin>/{target} does not resolve")
    lib_dirs = [d for d in (out / "lib", out / "vendor") if d.is_dir()]
    for path in sorted(out.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:
            problems.append(f"{path.relative_to(out)}: does not parse: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top in sys.stdlib_module_names or top == "yaml":
                    continue
                homes = [path.parent, *path.parents[:len(path.relative_to(out).parts) - 1],
                         *lib_dirs]
                if any((d / (top + ".py")).is_file() or (d / top / "__init__.py").is_file()
                       or (d / top).is_dir() for d in homes):
                    continue
                problems.append(f"{path.relative_to(out)}: import {module} resolves to "
                                f"nothing in the plugin")
    return problems


class Run:
    def __init__(self, args, plugins):
        self.codex = args.codex
        self.home = Path(args.codex_home).absolute()
        self.workdir = Path(args.workdir).absolute()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
        self.env.update(HOME=str(self.home.parent), CODEX_HOME=str(self.home))
        self.log = self.workdir / "app-server.stderr"
        self.plugins = plugins      # [{id, name, market, marketplace, out}]
        self.results = []

    def record(self, plugin, case, ok, detail=""):
        status = "passed" if ok is True else ("not-applicable" if ok is None else "failed")
        self.results.append({"id": case, "plugin": plugin["id"], "needs_model": False,
                             "status": status, "detail": detail})
        mark = {"passed": "ok  ", "failed": "FAIL", "not-applicable": "n/a "}[status]
        print(f"{mark} {plugin['id']} {case}" + (f": {detail}" if detail else ""))

    def attempt(self, plugin, case, fn):
        try:
            ok, detail = fn()
        except (native.NativeError, OSError, subprocess.SubprocessError, ValueError,
                KeyError, TypeError) as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self.record(plugin, case, ok, detail)
        return ok

    def cli(self, *args):
        return native.cli(self.codex, self.env, self.workdir, *args)

    def discover(self):
        return native.discovery(self.codex, self.env, self.workdir, self.log)

    def config_enabled(self, ident, enabled):
        config = self.home / "config.toml"
        text = config.read_text()
        key = f'[plugins."{ident}"]'
        if key not in text:
            raise ValueError(f"{config} has no {key} table")
        head, tail = text.split(key, 1)
        want, have = ("enabled = true", "enabled = false") if enabled else \
            ("enabled = false", "enabled = true")
        if have not in tail.split("\n[", 1)[0]:
            raise ValueError(f"{key} has no `{have}` line")
        config.write_text(head + key + tail.replace(have, want, 1))

    def run(self, owner_home):
        before = owner_fingerprint(owner_home) if owner_home else None
        version = native.version(self.codex, self.env, self.workdir)
        if not version:
            raise Unjudgeable(f"`{self.codex} --version` did not answer; is codex installed?")
        evidence = {"schema": SCHEMA, "host_version": version,
                    "codex_home": str(self.home), "workdir": str(self.workdir),
                    "plugins": [], "cases": self.results,
                    "not_run": [{"id": c[0], "needs_model": True, "run_by": CLEAN_RUN}
                                for c in CASES if c[1]]}
        for p in self.plugins:
            p["skills_expected"] = emitted_skills(p["out"], p["name"])
            p["hooks_expected"] = hook_definitions(p["out"])
            problems = package_static(p["out"], p["name"])
            self.record(p, "package-static", not problems, "; ".join(problems[:5]))
        for p in self.plugins:
            self.attempt(p, "marketplace-add", lambda p=p: self.add_marketplace(p))
            self.attempt(p, "plugin-add", lambda p=p: self.add_plugin(p))
            self.attempt(p, "installed-integrity", lambda p=p: self.integrity(p))
            self.attempt(p, "plugin-listed", lambda p=p: self.listed(p))
        try:
            skills, hooks = self.discover()
        except native.NativeError as exc:
            skills = hooks = None
            for p in self.plugins:
                for case in ("skill-discovery", "hook-discovery", "hook-untrusted",
                             "hook-rendering"):
                    self.record(p, case, False, f"discovery failed: {exc}")
        for p in self.plugins:
            if skills is not None:
                self.attempt(p, "skill-discovery", lambda p=p: self.skill_case(p, skills))
                mine = [h for h in hooks if h.get("pluginId") == p["id"]]
                p["hooks_seen"] = [{k: h.get(k) for k in ("eventName", "matcher", "command",
                                                          "timeoutSec", "trustStatus",
                                                          "enabled", "sourcePath")}
                                   for h in mine]
                self.attempt(p, "hook-discovery", lambda p=p, m=mine: self.hook_case(p, m))
                self.attempt(p, "hook-untrusted", lambda m=mine: (
                    all(h.get("trustStatus") == "untrusted" for h in m),
                    ", ".join(f"{h.get('eventName')}={h.get('trustStatus')}" for h in m
                              if h.get("trustStatus") != "untrusted")))
                self.attempt(p, "hook-rendering", lambda p=p, m=mine: self.render_case(p, m))
            self.agent_cases(p)
        for p in self.plugins:
            self.attempt(p, "plugin-disable", lambda p=p: self.disable_case(p))
        for p in self.plugins:
            self.attempt(p, "plugin-remove", lambda p=p: self.remove_case(p))
        for p in self.plugins:
            self.attempt(p, "marketplace-remove", lambda p=p: self.unregister_case(p))
        for p in self.plugins:
            if before is None:
                self.record(p, "owner-home-untouched", False, "no --owner-codex-home given")
            else:
                try:
                    after = owner_fingerprint(owner_home)
                except Unjudgeable as exc:
                    self.record(p, "owner-home-untouched", False, str(exc))
                    continue
                self.record(p, "owner-home-untouched", after == before,
                            "" if after == before else f"{owner_home} changed during the run")
        for p in self.plugins:
            evidence["plugins"].append({
                "id": p["id"], "marketplace": str(p["marketplace"]), "built": str(p["out"]),
                "installed_path": p.get("installed"), "skills_expected": p["skills_expected"],
                "skills_seen": p.get("skills_seen"),
                "hooks_expected": [list(h) for h in p["hooks_expected"]],
                "hooks_seen": p.get("hooks_seen"), "roles": p.get("roles")})
        want = {(p["id"], c) for p in self.plugins for c in NON_MODEL}
        have = {(r["plugin"], r["id"]) for r in self.results
                if r["status"] in ("passed", "not-applicable")}
        evidence["status"] = "passed" if want <= have else "failed"
        return evidence

    def add_marketplace(self, p):
        got = self.cli("marketplace", "add", str(p["marketplace"]))
        ok = got.get("marketplaceName") == p["market"]
        return ok, "" if ok else f"registered as {got.get('marketplaceName')!r}"

    def add_plugin(self, p):
        got = self.cli("add", p["id"])
        if got.get("pluginId") != p["id"]:
            return False, f"codex returned identity {got.get('pluginId')!r}"
        path = Path(got.get("installedPath", "")).absolute()
        if not path.is_relative_to(self.home / "plugins/cache"):
            return False, f"installedPath {path} is outside {self.home / 'plugins/cache'}"
        p["installed"] = str(path)
        return True, ""

    def integrity(self, p):
        if not p.get("installed"):
            return False, "not installed"
        built, inst = tree_hashes(p["out"]), tree_hashes(p["installed"])
        diff = sorted(set(built) ^ set(inst)) + sorted(k for k in set(built) & set(inst)
                                                        if built[k] != inst[k])
        return not diff, ", ".join(diff[:8])

    def listed(self, p):
        got = self.cli("list")
        rows = [r for r in got.get("installed", []) if r.get("pluginId") == p["id"]]
        ok = len(rows) == 1 and rows[0].get("installed") is True and rows[0].get("enabled") is True
        return ok, "" if ok else f"plugin list rows for {p['id']}: {rows}"

    def skill_case(self, p, skills):
        if not p["skills_expected"]:
            return False, "the output emits no skills"
        mine = [s for s in skills if s.get("pluginId") == p["id"]]
        p["skills_seen"] = sorted(s.get("name") for s in mine if s.get("enabled"))
        if p["skills_seen"] != p["skills_expected"]:
            extra = sorted(set(p["skills_seen"]) - set(p["skills_expected"]))
            missing = sorted(set(p["skills_expected"]) - set(p["skills_seen"]))
            return False, f"extra {extra}, missing {missing}"
        root = Path(p.get("installed") or "/nonexistent")
        outside = [s.get("name") for s in mine if not Path(s.get("path", "")).is_relative_to(root)]
        return not outside, f"outside the cache: {outside}" if outside else ""

    def hook_case(self, p, mine):
        seen = sorted((h.get("eventName"), h.get("matcher")) for h in mine)
        want = sorted((e, m) for e, m, _, _ in p["hooks_expected"])
        return seen == want, "" if seen == want else f"saw {seen}, hooks.json defines {want}"

    def render_case(self, p, mine):
        if not p["hooks_expected"]:
            return (None, "ships no hooks.json") if not mine else (False, f"{len(mine)} hooks seen")
        root = p.get("installed") or ""
        want = sorted((e, m, (c or "").replace("${PLUGIN_ROOT}", root), t,
                       str(Path(root) / "hooks/hooks.json"))
                      for e, m, c, t in p["hooks_expected"])
        seen = sorted((h.get("eventName"), h.get("matcher"), h.get("command"),
                       h.get("timeoutSec"), h.get("sourcePath")) for h in mine)
        return seen == want, "" if seen == want else "rendered hooks differ from hooks.json"

    def agent_cases(self, p):
        shipped = sorted((p["out"] / "agents").glob("*.toml"))
        if not shipped:
            self.record(p, "agent-install", None, "ships no agents/*.toml")
            self.record(p, "agent-report", None, "ships no agents/*.toml")
            return
        if not p.get("installed"):
            for case in ("agent-install", "agent-report"):
                self.record(p, case, False, "the plugin is not installed")
            return
        installer = Path(p["installed"]) / "scripts/install-agents.py"
        if not installer.is_file():
            for case in ("agent-install", "agent-report"):
                self.record(p, case, False, f"{len(shipped)} roles ship with no installer")
            return
        base = [sys.executable, "-B", str(installer), "--codex-home", str(self.home)]

        def install():
            done = subprocess.run(base + ["--install"], env=self.env, cwd=self.workdir,
                                  capture_output=True, text=True, timeout=60)
            return done.returncode == 0, ("" if done.returncode == 0 else
                                          f"exit {done.returncode}: {done.stderr[-300:]}")
        self.attempt(p, "agent-install", install)

        def report():
            got = subprocess.run(base + ["--json"], env=self.env, cwd=self.workdir,
                                 capture_output=True, text=True, timeout=60)
            roles = json.loads(got.stdout)["roles"]
            p["roles"] = [{k: r.get(k) for k in ("name", "file", "status", "model")} for r in roles]
            files = sorted(r.get("file") for r in roles)
            bad = [r.get("file") for r in roles if r.get("status") != "present"]
            ok = files == [s.name for s in shipped] and not bad
            return ok, "" if ok else f"reported {files}, not present: {bad}"
        self.attempt(p, "agent-report", report)

    def disable_case(self, p):
        self.config_enabled(p["id"], False)
        try:
            skills, hooks = self.discover()
        finally:
            self.config_enabled(p["id"], True)
        on = [s.get("name") for s in skills if s.get("pluginId") == p["id"] and s.get("enabled")]
        on += [h.get("eventName") for h in hooks if h.get("pluginId") == p["id"] and h.get("enabled")]
        others = [q for q in self.plugins if q is not p and q.get("skills_expected")]
        dark = [q["id"] for q in others
                if not any(s.get("pluginId") == q["id"] and s.get("enabled") for s in skills)]
        if on or dark:
            return False, f"still enabled: {on}; other plugins dark: {dark}"
        return True, ""

    def remove_case(self, p):
        self.cli("remove", p["id"])
        if p.get("installed") and Path(p["installed"]).exists():
            return False, f"{p['installed']} survived the remove"
        skills, hooks = self.discover()
        left = [s.get("name") for s in skills if s.get("pluginId") == p["id"]]
        left += [h.get("eventName") for h in hooks if h.get("pluginId") == p["id"]]
        return not left, f"still discovered: {left}" if left else ""

    def unregister_case(self, p):
        self.cli("marketplace", "remove", p["market"])
        got = self.cli("marketplace", "list")
        left = [m for m in got.get("marketplaces", []) if m.get("name") == p["market"]]
        return not left, f"{p['market']} is still registered" if left else ""


def compare(evidence_dir):
    path = Path(evidence_dir) / "results.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Unjudgeable(f"cannot read {path}: {exc}") from exc
    if data.get("schema") != SCHEMA:
        raise Unjudgeable(f"{path}: schema {data.get('schema')!r}, want {SCHEMA}")
    problems = []
    if data.get("status") != "passed":
        problems.append(f"the recorded run did not pass (status {data.get('status')!r})")
    for p in data.get("plugins", []):
        name, _ = parse_identity(p["id"])
        out = Path(p["built"])
        now = emitted_skills(out, name)
        if p.get("skills_seen") != now:
            problems.append(f"{p['id']}: the output now emits {now}, Codex discovered "
                            f"{p.get('skills_seen')}")
        hooks_now = [list(h) for h in hook_definitions(out)]
        if sorted(map(tuple, hooks_now)) != sorted(map(tuple, p.get("hooks_expected", []))):
            problems.append(f"{p['id']}: hooks.json changed since the recorded run")
        if len(p.get("hooks_seen") or []) != len(hooks_now):
            problems.append(f"{p['id']}: Codex discovered {len(p.get('hooks_seen') or [])} "
                            f"hooks, hooks.json defines {len(hooks_now)}")
    if not data.get("plugins"):
        problems.append("the evidence records no plugin")
    for line in problems:
        print(f"FAIL {line}")
    if not problems:
        print(f"ok   {path}: every plugin's output matches what Codex discovered")
    return 1 if problems else 0


def plugin_specs(args):
    pairs = [(args.marketplace, args.plugin_id)]
    if len(args.extra_marketplace) != len(args.extra_plugin):
        raise Unjudgeable("each --extra-marketplace needs one --extra-plugin")
    pairs += list(zip(args.extra_marketplace, args.extra_plugin))
    specs = []
    for market_dir, ident in pairs:
        name, market = parse_identity(ident)
        specs.append({"id": ident, "name": name, "market": market,
                      "marketplace": Path(market_dir).resolve(),
                      "out": built_dir(market_dir, ident)})
    if len({s["id"] for s in specs}) != len(specs):
        raise Unjudgeable("a plugin identity is given twice")
    return specs


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="print every case, one per line")
    mode.add_argument("--run", action="store_true", help="run the needs_model: false cases")
    mode.add_argument("--compare-evidence", metavar="DIR")
    ap.add_argument("--codex-home")
    ap.add_argument("--workdir")
    ap.add_argument("--marketplace", help="the plugin's marketplace checkout")
    ap.add_argument("--plugin-id", default=DEFAULT_ID)
    ap.add_argument("--extra-marketplace", action="append", default=[])
    ap.add_argument("--extra-plugin", action="append", default=[])
    ap.add_argument("--evidence", metavar="DIR")
    ap.add_argument("--codex", default="codex", help="the codex binary (default: codex)")
    ap.add_argument("--owner-codex-home", help="the invoking user's Codex home, fingerprinted "
                    "before and after (owner-home-untouched)")
    args = ap.parse_args(argv)
    if args.run and not (args.codex_home and args.workdir and args.marketplace):
        ap.error("--run needs --codex-home, --workdir and --marketplace")
    return args


def main(argv=None):
    args = parse(argv)
    try:
        if args.list:
            for case, needs_model, what in CASES:
                print(f"{case}\tneeds_model={'true' if needs_model else 'false'}\t{what}")
            return 0
        if args.compare_evidence:
            return compare(args.compare_evidence)
        specs = plugin_specs(args)
        home = Path(args.codex_home).resolve()
        owners = [Path.home() / ".codex", os.environ.get("CODEX_HOME"), args.owner_codex_home]
        if any(o and Path(o).resolve() == home for o in owners):
            raise Unjudgeable("--codex-home is the invoking user's Codex home; give a scratch dir")
        if args.evidence:
            ev = Path(args.evidence).resolve()
            for root in [REPO] + [s["marketplace"] for s in specs]:
                if ev.is_relative_to(root):
                    raise Unjudgeable(f"--evidence {ev} is inside {root}; evidence records "
                                      f"machine paths, so it goes outside every repo")
        evidence = Run(args, specs).run(args.owner_codex_home)
    except Unjudgeable as exc:
        print(f"qualify: {exc}", file=sys.stderr)
        return 2
    if args.evidence:
        out = Path(args.evidence)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"qualify: {evidence['status']} — "
          f"{sum(r['status'] == 'passed' for r in evidence['cases'])} passed, "
          f"{sum(r['status'] == 'failed' for r in evidence['cases'])} failed, "
          f"{len(evidence['not_run'])} model cases not run here")
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
