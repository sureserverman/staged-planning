#!/usr/bin/env python3
"""A fake `opencode` for test-qualify.py: no network, no model.

It answers from $HOME/.config/opencode/opencode.json the way OpenCode did when measured: a
`plugin` entry's package adds its skills/, agents/ and commands/; a `skills.paths` entry
adds its skills. It misbehaves on demand through FAKE_MODE:
  ok        list everything; the backlog run loads the skill and answers BL-NNN
  miss      leave one skill out of `debug skill`
  noagent   leave the agents out of `debug config`
  xcmd      add a command no package ships
  noskill   answer BL-NNN without loading the skill
  owner     also write into $FAKE_OWNER/.config/opencode/opencode.json
  FAKE_LINGER=<tag>  (any mode) leave a background child behind, as the real host's
             workers do: `sleep` under argv LINGER-<tag>, in the same session
"""
import json
import os
import sys
from pathlib import Path

MODE = os.environ.get("FAKE_MODE", "ok")


def linger():
    tag = os.environ.get("FAKE_LINGER")
    if tag:
        import subprocess
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", f"LINGER-{tag}"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def sources():
    conf = json.loads((Path(os.environ["HOME"]) / ".config/opencode/opencode.json").read_text())
    packages = [Path(p).parent.parent for p in conf.get("plugin") or []]
    roots = [p / "skills" for p in packages] + [Path(p) for p in (conf.get("skills") or {}).get("paths") or []]
    return packages, roots


def main():
    args = sys.argv[1:]
    linger()
    if args[:1] == ["--version"]:
        print("1.19.3-fake")
        return 0
    if MODE == "owner" and os.environ.get("FAKE_OWNER"):
        f = Path(os.environ["FAKE_OWNER"]) / ".config/opencode/opencode.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{"changed": true}\n')
    packages, roots = sources()
    if args[:2] == ["debug", "skill"]:
        skills = [{"name": "customize-opencode", "location": "<built-in>"}]
        for r in roots:
            for s in sorted(r.iterdir()):
                if (s / "SKILL.md").is_file():
                    skills.append({"name": s.name, "location": str(s / "SKILL.md")})
        if MODE == "miss":
            skills = skills[:1] + skills[2:]
        print(json.dumps(skills, indent=2))
    elif args[:2] == ["debug", "config"]:
        agents = {a.stem: {} for p in packages for a in sorted((p / "agents").glob("*.md"))}
        commands = {c.stem: {} for p in packages for c in sorted((p / "commands").glob("*.md"))}
        if MODE == "noagent":
            agents = {}
        if MODE == "xcmd":
            commands["stray"] = {}
        print(json.dumps({"agent": agents, "command": commands}))
    elif args[:1] == ["run"]:
        if MODE != "noskill":
            print(json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "skill", "state": {
                "status": "completed", "input": {"name": "backlog"}}}}))
        print(json.dumps({"type": "text", "part": {"type": "text", "text": "BL-NNN"}}))
    else:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
