#!/usr/bin/env python3
"""A fake `cursor-agent` for test-qualify.py: no network, no model.

It answers the three prompts qualify.py sends, from what is installed under
$HOME/.cursor/plugins/local, and misbehaves on demand through FAKE_MODE:
  ok         list every model-invocable skill and every agent; read the backlog skill and
             answer BL-NNN; log one dispatch line for one Task call
  miss       leave one skill out of the listing
  extra      list a skill path the build never emitted
  noagent    leave the agents out of the listing
  noread     answer BL-NNN without reading the backlog skill
  double     log the one Task call's dispatch line twice
  nolog      log no dispatch line
  owner      also write into $FAKE_OWNER/.cursor/hooks.json
  roots      write each plugin's skill paths as $N/<skill>/SKILL.md, with a root line for
             each $N (Cursor's abbreviated form)
  bareroots  the same, with no root lines: the listing cannot be judged
  notask     log the dispatch line but show no Task call in the transcript
  FAKE_LINGER=<tag>  (any mode) leave a background child behind, as the real host's
             workers do: `sleep` under argv LINGER-<tag>, in the same session
"""
import json
import os
import re
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


def emit(*events):
    for e in events:
        print(json.dumps(e))


def result(text):
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
         {"type": "result", "result": text})


def main():
    args = sys.argv[1:]
    linger()
    if args[:1] == ["--version"]:
        print("2026.01.01-fake")
        return 0
    prompt = args[-1] if args else ""
    local = Path(os.environ["HOME"]) / ".cursor" / "plugins" / "local"
    plugins = sorted(p for p in local.iterdir() if p.is_dir()) if local.is_dir() else []
    if MODE == "owner" and os.environ.get("FAKE_OWNER"):
        hooks = Path(os.environ["FAKE_OWNER"]) / ".cursor" / "hooks.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        hooks.write_text('{"changed": true}\n')
    if "BEGIN-LIST" in prompt:
        lines, agents = [], []
        for p in plugins:
            for s in sorted((p / "skills").iterdir()):
                md = s / "SKILL.md"
                if md.is_file() and "disable-model-invocation: true" not in md.read_text():
                    if MODE in ("roots", "bareroots"):
                        lines.append(f"skill ${plugins.index(p)}/{s.name}/SKILL.md")
                    else:
                        lines.append(f"skill {md}")
            agents += [a.stem for a in sorted((p / "agents").glob("*.md"))]
        if MODE == "roots":
            lines = [f"root ${i} {p}/skills" for i, p in enumerate(plugins)] + lines
        if MODE == "miss":
            lines = lines[1:]
        if MODE == "extra":
            lines.append(f"skill {plugins[0]}/skills/never-built/SKILL.md")
        if MODE != "noagent":
            lines += ["agent generalPurpose"] + [f"agent {a}" for a in agents]
        result("BEGIN-LIST\n" + "\n".join(lines) + "\nEND-LIST")
    elif "backlog skill" in prompt:
        if MODE != "noread":
            path = next(p for p in plugins if (p / "skills" / "backlog").is_dir()) / "skills" / "backlog" / "SKILL.md"
            emit({"type": "tool_call", "subtype": "completed", "call_id": "r1",
                  "tool_call": {"readToolCall": {"args": {"path": str(path)},
                                                 "result": {"success": {"content": "x"}}}}})
        result("BL-NNN")
    elif "Task tool" in prompt:
        if MODE != "notask":
            emit({"type": "tool_call", "subtype": "started", "call_id": "t1",
                  "tool_call": {"taskToolCall": {"args": {"subagentType": "code-reviewer"}}}})
        log = Path.cwd() / ".claude" / "dispatch-log.jsonl"
        row = json.dumps({"event": "dispatch", "subagent_type": "code-reviewer",
                          "tool_use_id": "t1"}) + "\n"
        if MODE != "nolog":
            with open(log, "a") as fh:
                fh.write(row * (2 if MODE == "double" else 1))
        result("REVIEW-OK")
    else:
        result("?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
