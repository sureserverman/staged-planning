#!/usr/bin/env python3
"""Where a project's records live: the one entry point every skill and script asks.

The contract is the plugin's references/records-resolver.md; this file implements it.
A records resolver is an optional external command named in the config file. Without
one, the records home is <repo>/docs. With one, its answer is mapped to three exit
codes, and anything it says in a shape not listed there is refused, never guessed at:

  0  the resolver named one absolute directory: that is the records home
  3  no resolver, or the resolver does not manage this project: <repo>/docs
  2  the resolver is configured but failed, or its answer could not be read; the
     caller stops and creates nothing

Config file order: $STAGED_PLANNING_CONFIG (a blank value counts as unset; a value
that is not an absolute path after `~` expansion, or names a missing file, is exit 2,
never a fallback), then
$XDG_CONFIG_HOME/staged-planning/config.yaml (XDG_CONFIG_HOME defaults to ~/.config,
and a relative value is ignored, as the XDG spec requires).

Usage:
  records_home.py --project <abs repo> [--for-write | --decision-registers]

Python API, for scripts that load this file by path:
  resolve(project, for_write=False) -> (code, path, message)
  decision_registers(project)       -> (code, paths, message)
  config_value(key)                 -> (value, message), for the config's other keys

Nothing is printed or run on import, and the API never raises.
"""
import argparse
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

CONFIG_ENV = "STAGED_PLANNING_CONFIG"
APP_DIR = "staged-planning"
KEY = "records_resolver"
TIMEOUT = 10
PROG = "records_home"
# Control characters a path line may not hold: a CR, NUL or tab is refused, never trimmed.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _home():
    """A home directory, never an exception (no HOME and no passwd entry raises)."""
    try:
        return Path.home()
    except Exception:
        return Path(os.environ.get("HOME") or "/nonexistent")


def _expand(value):
    """`~` expanded where a home exists; otherwise the string as written."""
    try:
        return os.path.expanduser(value)
    except Exception:
        return value


def _is_file(path):
    """False for any OSError: an unreadable parent directory raises from is_file()."""
    try:
        return Path(path).is_file()
    except OSError:
        return False


def _config_file():
    """(path, named): the config file to read, or (None, False) when there is none.

    `named` is True when $STAGED_PLANNING_CONFIG chose the path; such a path is returned
    even when it does not exist, so the caller can refuse it by name.
    """
    value = (os.environ.get(CONFIG_ENV) or "").strip()
    if value:
        return _expand(value), True
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base and os.path.isabs(base) else _home() / ".config"
    path = root / APP_DIR / "config.yaml"
    return (str(path), False) if _is_file(path) else (None, False)


class _Refused(Exception):
    """A configured setup that cannot be honestly used: exit 2 with this message."""


def _read_config():
    """(path, data): the parsed config mapping, or (None, None) when there is no config
    or it is empty. Raises _Refused for a config that cannot be honestly read."""
    path, named = _config_file()
    if path is None:
        return None, None
    if named and not os.path.isabs(path):
        # A relative value would name a config the current project holds.
        raise _Refused(f"{CONFIG_ENV} must be an absolute path (got {path!r})")
    if named and not _is_file(path):
        raise _Refused(f"{CONFIG_ENV} names {path}, which is not a file")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise _Refused(f"cannot read config {path}: {e}")
    try:
        import yaml
    except Exception as e:
        raise _Refused(f"config {path} exists but PyYAML cannot be imported: {e}")
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise _Refused(f"config {path} is not valid YAML: {e}")
    if data is None:
        return path, None
    if not isinstance(data, dict):
        raise _Refused(f"config {path} must be a YAML mapping")
    return path, data


def _resolver_argv():
    """The resolver's argv, or None when none is configured. Raises _Refused."""
    path, data = _read_config()
    if data is None or KEY not in data:
        return None
    argv = data[KEY]
    if (not isinstance(argv, list) or not argv
            or not all(isinstance(a, str) and a for a in argv)):
        raise _Refused(f"config {path}: {KEY}: must be a non-empty list of non-empty strings")
    argv = [_expand(a) for a in argv]
    for a in argv:
        # A bare name (python3) is a PATH lookup; a relative path would run a script
        # named by whatever project the caller stands in.
        if "/" in a and not os.path.isabs(a):
            raise _Refused(f"config {path}: {KEY}: {a!r} is a relative path; every element "
                           f"holding a / must be an absolute path")
    return argv


def _run(argv, project, flag):
    """Run the resolver. Returns (exit code, stdout). Raises _Refused on a failed run."""
    cmd = argv + ["--project", project] + ([flag] if flag else [])
    try:
        # Its own session, so a timeout can kill everything it started: a child left
        # holding stdout open would otherwise outlive the call.
        # cwd "/": nothing the resolver does may resolve against the caller's directory.
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, cwd="/")
    except Exception as e:
        raise _Refused(f"records resolver could not be run ({cmd[0]}): {e}")
    try:
        out, err = proc.communicate(timeout=TIMEOUT)
    except BaseException as e:
        err = _kill_group(proc)
        if isinstance(e, subprocess.TimeoutExpired):
            raise _Refused(_with_stderr(f"records resolver ran longer than {TIMEOUT} s", err))
        raise
    if proc.returncode == 3:
        return 3, ""
    if proc.returncode != 0:
        raise _Refused(_with_stderr(f"records resolver exited {proc.returncode}", err))
    try:
        return 0, out.decode("utf-8")
    except UnicodeDecodeError as e:
        raise _Refused(f"records resolver exited 0 but its stdout is not UTF-8 ({e})")


def _path_lines(out):
    """The lines of a resolver's stdout, each an absolute path. Raises _Refused.

    One trailing newline ends the output; every other control character, a blank line
    and surrounding whitespace are refused, never trimmed.
    """
    if out == "":
        return []
    body = out[:-1] if out.endswith("\n") else out
    lines = body.split("\n")
    for line in lines:
        if CONTROL_RE.search(line) or line != line.strip() or not os.path.isabs(line):
            raise _Refused(f"records resolver printed a line that is not an absolute path "
                           f"({line[:200]!r})")
    return lines


def _kill_group(proc):
    """SIGKILL the resolver's whole process group, reap it, and return its stderr."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        _, err = proc.communicate(timeout=1)
        return err
    except Exception:
        proc.kill()
        proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except Exception:
                pass
        return ""


def _with_stderr(what, stderr):
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    stderr = (stderr or "").strip()
    return f"{what}:\n{stderr}" if stderr else what


def _check_project(project):
    if not isinstance(project, str) or not os.path.isabs(project):
        raise _Refused(f"usage: --project must be an absolute path (got {project!r})")


def config_value(key):
    """(value, message) for one top-level key of the config file.

    value is the key's parsed YAML value, or None when there is no config, no such key,
    or the config cannot be read; message is "" except in that last case, where it says
    why. The caller checks the value's shape. Never runs the resolver, never raises.
    """
    try:
        _, data = _read_config()
        if data is None or not isinstance(key, str):
            return None, ""
        return data.get(key), ""
    except _Refused as e:
        return None, str(e)
    except Exception as e:
        return None, f"unexpected failure: {e!r}"


def resolve(project, for_write=False):
    """(code, path, message) for the project's records home; see the module docstring.

    code 0 and 3 carry a path; code 2 carries None and a message for the caller to show.
    """
    default = os.path.join(project, "docs") if isinstance(project, str) else None
    try:
        _check_project(project)
        argv = _resolver_argv()
        if argv is None:
            return 3, default, "no records resolver configured; records go to the repo"
        code, out = _run(argv, project, "--for-write" if for_write else None)
        if code == 3:
            return 3, default, "the records resolver does not manage this project"
        lines = _path_lines(out)
        if len(lines) != 1:
            raise _Refused(f"records resolver exited 0 but did not print exactly one "
                           f"absolute path (stdout {out[:200]!r})")
        home = lines[0]
        if os.path.exists(home) and not os.path.isdir(home):
            # A missing home is allowed on a read (--for-write creates it); one that is
            # there but is not a directory is never a records home.
            raise _Refused(f"records resolver named {home}, which exists but is not a directory")
        if for_write and not os.path.isdir(home):
            raise _Refused(f"records resolver named {home} for writing, which is not a directory")
        return 0, home, ""
    except _Refused as e:
        return 2, None, str(e)
    except Exception as e:
        return 2, None, f"unexpected failure: {e!r}"


def decision_registers(project):
    """(code, paths, message) for the further decision registers that bind the project.

    code 0 lists zero or more absolute paths; 3 and 2 carry an empty list.
    """
    try:
        _check_project(project)
        argv = _resolver_argv()
        if argv is None:
            return 3, [], "no records resolver configured"
        code, out = _run(argv, project, "--decision-registers")
        if code == 3:
            return 3, [], "the records resolver lists no further decision registers"
        return 0, _path_lines(out), ""
    except _Refused as e:
        return 2, [], str(e)
    except Exception as e:
        return 2, [], f"unexpected failure: {e!r}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog=PROG, description="Print a project's records home.")
    ap.add_argument("--project", required=True, help="the repo, as an absolute path")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--for-write", action="store_true",
                      help="the caller is about to write a record")
    mode.add_argument("--decision-registers", action="store_true",
                      help="list further decision registers that bind the project")
    args = ap.parse_args(argv)
    if args.decision_registers:
        code, paths, message = decision_registers(args.project)
        out = "".join(p + "\n" for p in paths)
    else:
        code, path, message = resolve(args.project, for_write=args.for_write)
        out = path + "\n" if path is not None else ""
    if code == 2:
        out = ""
    try:
        if message:
            print(f"{PROG}: {message}", file=sys.stderr)
        # Bytes, not the locale's text encoding: a path is printed exactly as it was
        # read, even under an ASCII locale or for a repo path that is not UTF-8.
        sys.stdout.buffer.write(out.encode("utf-8", errors="surrogateescape"))
        sys.stdout.flush()
    except Exception as e:
        try:
            print(f"{PROG}: could not write the result: {e!r}", file=sys.stderr)
        except Exception:
            pass
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
