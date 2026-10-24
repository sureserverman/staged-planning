"""Codex's own interfaces, driven without a model turn.

Two surfaces: the `codex plugin ... --json` commands, and `codex app-server --stdio`,
whose JSON-RPC `skills/list` and `hooks/list` report what a session would load. Neither
writes authentication or hook trust. Every call takes the environment it is given, so a
caller that sets HOME and CODEX_HOME to a scratch dir keeps the user's profile out of it.
"""
import json
import os
import select
import subprocess
import time


class NativeError(RuntimeError):
    """A Codex command failed or answered in a shape this harness does not read."""


def cli(codex, env, cwd, *args, timeout=60):
    """Run `codex plugin <args> --json` and return its parsed stdout."""
    done = subprocess.run([codex, "plugin", *args, "--json"], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise NativeError(f"codex plugin {' '.join(args)} exited {done.returncode}: "
                          f"{done.stderr.strip()[-400:]}")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise NativeError(f"codex plugin {' '.join(args)} printed no JSON: {exc}") from exc


def version(codex, env, cwd):
    try:
        done = subprocess.run([codex, "--version"], env=env, cwd=cwd, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


class AppServer:
    """One `codex app-server --stdio` process, closed by the caller."""

    def __init__(self, codex, env, cwd, log_path):
        self.log = open(log_path, "ab")
        self.proc = subprocess.Popen([codex, "app-server", "--stdio"], env=env, cwd=cwd,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.log, bufsize=0)
        self.serial = 0
        self.buffer = b""
        try:
            self.rpc("initialize", {"clientInfo": {"name": "staged_planning_qualify",
                                                   "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def send(self, message):
        self.proc.stdin.write((json.dumps(message) + "\n").encode())
        self.proc.stdin.flush()

    def rpc(self, method, params, timeout=30):
        self.serial += 1
        wanted = self.serial
        self.send({"id": wanted, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b"\n" not in self.buffer:
                ready = select.select([self.proc.stdout], [], [],
                                      max(0, deadline - time.monotonic()))[0]
                if not ready:
                    break
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                self.buffer += chunk
                continue
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == wanted and "method" not in message:
                if "error" in message:
                    raise NativeError(f"{method}: {message['error']}")
                return message.get("result", {})
        raise NativeError(f"app-server {method} gave no answer in {timeout}s")

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self.proc.stdout.close()
        self.log.close()


def discovery(codex, env, cwd, log_path):
    """What a fresh session in `cwd` would load: (skills, hooks), each a flat list."""
    server = AppServer(codex, env, cwd, log_path)
    try:
        skills = server.rpc("skills/list", {"cwds": [str(cwd)], "forceReload": True})
        hooks = server.rpc("hooks/list", {"cwds": [str(cwd)]})
    finally:
        server.close()
    try:
        return ([s for row in skills["data"] for s in row["skills"]],
                [h for row in hooks["data"] for h in row["hooks"]])
    except (KeyError, TypeError) as exc:
        raise NativeError(f"skills/list or hooks/list answered an unread shape: {exc!r}") from exc
