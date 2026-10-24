#!/usr/bin/env python3
"""A stand-in `codex` for test-qualify.py: the plugin commands and app-server discovery.

State lives in $CODEX_HOME (fake-state.json plus config.toml), so a run is as isolated as
the home it is given. FAKE_CODEX_MUTATE names one misbehaviour, to prove the case that
should catch it does:
  extra-skill    discovery shows a skill the plugin does not ship
  trusted-hook   discovery reports a hook already trusted
  drop-hook      discovery omits one hook
  wrong-id       `plugin add` answers with another identity
  keep-cache     `plugin remove` leaves the cache in place
  corrupt-cache  `plugin add` installs one file changed
  touch-owner    `plugin add` also writes into $FAKE_OWNER (a directory)
  ignore-disable discovery ignores `enabled = false`
  bad-render     discovery roots each hook command somewhere other than the cache
  drop-role      `plugin add` installs one agents/*.toml fewer
FAKE_CODEX_SEEN, when set, gets one line per call: the HOME and CODEX_HOME the call ran
with, and LEAK when OPENAI_API_KEY reached it. qualify passes the caller's environment
through only in part, so the tests set these in the file the `codex` wrapper sources.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

HOME = Path(os.environ["CODEX_HOME"])
STATE = HOME / "fake-state.json"
CONFIG = HOME / "config.toml"
MUTATE = os.environ.get("FAKE_CODEX_MUTATE", "")
EVENTS = {"Stop": "stop", "PreToolUse": "preToolUse", "SubagentStart": "subagentStart",
          "SubagentStop": "subagentStop"}


def load():
    return json.loads(STATE.read_text()) if STATE.exists() else {"markets": {}, "plugins": {}}


def save(state):
    HOME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


def enabled(ident):
    text = CONFIG.read_text() if CONFIG.exists() else ""
    m = re.search(r'\[plugins\."' + re.escape(ident) + r'"\]\nenabled = (true|false)', text)
    return MUTATE == "ignore-disable" or (m is not None and m.group(1) == "true")


def out(obj):
    print(json.dumps(obj))
    return 0


def plugin(args):
    state = load()
    if args[:2] == ["marketplace", "add"]:
        root = Path(args[2]).resolve()
        data = json.loads((root / ".agents/plugins/marketplace.json").read_text())
        state["markets"][data["name"]] = {"root": str(root), "plugins": data["plugins"]}
        save(state)
        return out({"marketplaceName": data["name"], "installedRoot": str(root),
                    "alreadyAdded": False})
    if args[:2] == ["marketplace", "list"]:
        return out({"marketplaces": [{"name": n, "root": m["root"]}
                                     for n, m in state["markets"].items()]})
    if args[:2] == ["marketplace", "remove"]:
        state["markets"].pop(args[2], None)
        save(state)
        return out({"marketplaceName": args[2], "installedRoot": None})
    if args[0] == "add":
        name, market = args[1].split("@")
        m = state["markets"][market]
        entry = next(p for p in m["plugins"] if p["name"] == name)
        src = Path(m["root"]) / entry["source"]["path"]
        version = json.loads((src / ".codex-plugin/plugin.json").read_text())["version"]
        dest = HOME / "plugins/cache" / market / name / version
        shutil.copytree(src, dest)
        if MUTATE == "corrupt-cache":
            next(p for p in sorted(dest.rglob("SKILL.md"))).write_text("changed\n")
        if MUTATE == "drop-role":
            next(iter(sorted(dest.glob("agents/*.toml")))).unlink()
        if MUTATE == "touch-owner":
            (Path(os.environ["FAKE_OWNER"]) / "config.toml").write_text("touched\n")
        state["plugins"][args[1]] = str(dest)
        save(state)
        with CONFIG.open("a") as fh:
            fh.write(f'\n[plugins."{args[1]}"]\nenabled = true\n')
        ident = "someone-else@" + market if MUTATE == "wrong-id" else args[1]
        return out({"pluginId": ident, "name": name, "marketplaceName": market,
                    "version": version, "installedPath": str(dest)})
    if args[0] == "list":
        return out({"installed": [{"pluginId": i, "installed": True, "enabled": enabled(i)}
                                  for i in state["plugins"]], "available": []})
    if args[0] == "remove":
        path = state["plugins"].pop(args[1], None)
        if path and MUTATE != "keep-cache":
            shutil.rmtree(path)
        save(state)
        text = CONFIG.read_text().replace(f'\n[plugins."{args[1]}"]\nenabled = true\n', "")
        CONFIG.write_text(text)
        return out({"pluginId": args[1]})
    print(f"fake codex: unknown plugin command {args}", file=sys.stderr)
    return 2


def skills():
    rows = [{"name": "builtin-skill", "path": "/x/SKILL.md", "enabled": True}]
    for ident, path in load()["plugins"].items():
        name = ident.split("@")[0]
        on = enabled(ident)
        for s in sorted(Path(path).glob("skills/*/SKILL.md")):
            rows.append({"name": f"{name}:{s.parent.name}", "path": str(s), "enabled": on,
                         "pluginId": ident})
        if MUTATE == "extra-skill":
            rows.append({"name": f"{name}:stray", "path": f"{path}/skills/stray/SKILL.md",
                         "enabled": on, "pluginId": ident})
    return rows


def hooks():
    rows = []
    for ident, path in load()["plugins"].items():
        source = Path(path) / "hooks/hooks.json"
        if not source.exists():
            continue
        on = enabled(ident)
        for event, groups in json.loads(source.read_text())["hooks"].items():
            for group in groups:
                for h in group["hooks"]:
                    rows.append({"eventName": EVENTS[event], "matcher": group.get("matcher"),
                                 "command": h["command"].replace(
                                     "${PLUGIN_ROOT}",
                                     "/elsewhere" if MUTATE == "bad-render" else path),
                                 "timeoutSec": h.get("timeout"), "sourcePath": str(source),
                                 "source": "plugin", "pluginId": ident, "enabled": on,
                                 "trustStatus": "trusted" if MUTATE == "trusted-hook"
                                 else "untrusted"})
    return rows[1:] if MUTATE == "drop-hook" else rows


def app_server():
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method = msg["method"]
        if method == "initialize":
            result = {"userAgent": "fake"}
        elif method == "skills/list":
            result = {"data": [{"cwd": msg["params"]["cwds"][0], "skills": skills()}]}
        elif method == "hooks/list":
            result = {"data": [{"cwd": msg["params"]["cwds"][0], "hooks": hooks()}]}
        else:
            print(json.dumps({"id": msg["id"], "error": {"message": "unknown"}}), flush=True)
            continue
        print(json.dumps({"id": msg["id"], "result": result}), flush=True)
    return 0


def main(argv):
    if os.environ.get("FAKE_CODEX_SEEN"):
        with open(os.environ["FAKE_CODEX_SEEN"], "a") as fh:
            fh.write(f"{os.environ.get('HOME')} {HOME}"
                     + (" LEAK" if "OPENAI_API_KEY" in os.environ else "") + "\n")
    if argv == ["--version"]:
        print("codex-cli 0.0.0-fake")
        return 0
    if argv[:1] == ["plugin"] and argv[-1] == "--json":
        return plugin(argv[1:-1])
    if argv[:2] == ["app-server", "--stdio"]:
        return app_server()
    print(f"fake codex: unknown command {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
