#!/usr/bin/env python3
"""Tests for core/lib/records_home.py — the one entry point that names a records home.

The contract is docs/records-resolver.md. Its exit codes are the interface every caller
branches on, so each row of the mapping is driven end to end through the command with a
stub resolver written into a temp dir: the stub prints what the case needs, exits with the
code the case needs, and logs the argv it was given so the call shape is pinned too.

Every process runs with a throwaway HOME and XDG_CONFIG_HOME, so the machine's own config
can never make a case pass.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / "records_home.py"

FAILURES = []


def check(cond, msg):
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)


CLEARED = ("STAGED_PLANNING_CONFIG", "XDG_CONFIG_HOME")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Box:
    """A throwaway HOME, a repo, and a place for stub resolvers."""

    def __init__(self, root):
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.xdg = self.home / ".config" / "staged-planning"
        self.repo = root / "work" / "proj"
        self.repo.mkdir(parents=True)
        self.stubs = root / "stubs"
        self.stubs.mkdir()
        self.n = 0

    def env(self, drop=(), **extra):
        e = {k: v for k, v in os.environ.items() if k not in CLEARED}
        e["HOME"] = str(self.home)
        e["XDG_CONFIG_HOME"] = str(self.home / ".config")
        e.update({k: str(v) for k, v in extra.items()})
        for k in drop:
            e.pop(k, None)
        return e

    def stub(self, out="", code=0, err="", sleep=0):
        """A resolver that logs its argv, then prints `out`, `err` and exits `code`.

        `out` and `err` given as bytes are written raw, so a case can send bytes that are
        not UTF-8.
        """
        self.n += 1
        log = self.stubs / f"argv-{self.n}.json"
        path = write(self.stubs / f"resolver-{self.n}.py", (
            "import json, sys, time\n"
            f"open({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
            f"time.sleep({sleep})\n"
            f"sys.stdout{'.buffer' if isinstance(out, bytes) else ''}.write({out!r})\n"
            f"sys.stderr{'.buffer' if isinstance(err, bytes) else ''}.write({err!r})\n"
            f"sys.exit({code})\n"))
        return [sys.executable, str(path)], log

    def config(self, argv, where=None):
        """A config whose records_resolver: is `argv` (a JSON list is a YAML flow list)."""
        return write(where or self.xdg / "config.yaml",
                     f"records_resolver: {json.dumps(argv)}\n")


def run(box, *args, env=None, project=None, cwd=None, timeout=60):
    project = box.repo if project is None else project
    argv = [sys.executable, str(MODULE)]
    if project is not False:
        argv += ["--project", str(project)]
    t = time.monotonic()
    r = subprocess.run(argv + list(args), capture_output=True, text=True,
                       env=box.env() if env is None else env, cwd=cwd, timeout=timeout)
    r.elapsed = time.monotonic() - t
    return r


def tail(r):
    return f"exit {r.returncode}, out {r.stdout.strip()[-80:]!r}, err {r.stderr.strip()[-120:]!r}"


def logged(log):
    try:
        return json.loads(log.read_text(encoding="utf-8"))
    except Exception:
        return None


def no_traceback(r):
    return "Traceback" not in r.stderr


def refused(r):
    """Exit 2 from records_home itself: nothing on stdout, its own prefix on stderr.

    The prefix is what keeps these cases from passing against a missing module, where
    the interpreter also exits 2 with nothing on stdout.
    """
    return (r.returncode == 2 and r.stdout == "" and "records_home:" in r.stderr
            and no_traceback(r))


def default_home_cases():
    print("no resolver — the records home is <repo>/docs, exit 3:")
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        docs = str(b.repo / "docs")
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs, f"no config file ({tail(r)})")
        r = run(b, "--for-write")
        check(r.returncode == 3 and r.stdout.strip() == docs, f"no config file, --for-write ({tail(r)})")
        write(b.xdg / "config.yaml", "something_else: 1\n")
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs, f"a config with no records_resolver: key ({tail(r)})")
        write(b.xdg / "config.yaml", "")
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs, f"an empty config file ({tail(r)})")
        (b.xdg / "config.yaml").unlink()
        r = subprocess.run([sys.executable, "-c",
                            "import sys, runpy; sys.modules['yaml'] = None; "
                            f"sys.argv = [{str(MODULE)!r}, '--project', {str(b.repo)!r}]; "
                            f"runpy.run_path({str(MODULE)!r}, run_name='__main__')"],
                           capture_output=True, text=True, env=b.env(), timeout=60)
        check(r.returncode == 3 and r.stdout.strip() == docs,
              f"with no config file, PyYAML is never imported ({tail(r)})")


def mapping_cases():
    print("the resolver's answer, row by row:")
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        docs = str(b.repo / "docs")
        home = b.root / "records" / "proj"
        home.mkdir(parents=True)

        argv, log = b.stub(out=f"{home}\n")
        b.config(argv)
        r = run(b)
        check(r.returncode == 0 and r.stdout == f"{home}\n", f"exit 0 with one absolute line prints it ({tail(r)})")
        check(logged(log) == ["--project", str(b.repo)],
              f"...and the resolver got exactly --project <repo> ({logged(log)})")

        argv, log = b.stub(out=str(home))
        b.config(argv)
        r = run(b)
        check(r.returncode == 0 and r.stdout.strip() == str(home), f"a line with no trailing newline is one line ({tail(r)})")

        argv, log = b.stub(out=f"{home}\n")
        b.config(argv)
        r = run(b, "--for-write")
        check(r.returncode == 0 and r.stdout.strip() == str(home), f"--for-write with an existing directory ({tail(r)})")
        check(logged(log) == ["--project", str(b.repo), "--for-write"],
              f"...and --for-write was passed on ({logged(log)})")

        missing = b.root / "records" / "not-made"
        argv, log = b.stub(out=f"{missing}\n")
        b.config(argv)
        r = run(b, "--for-write")
        check(refused(r) and no_traceback(r),
              f"--for-write with a directory that does not exist is exit 2 ({tail(r)})")
        r = run(b)
        check(r.returncode == 0 and r.stdout.strip() == str(missing),
              f"...while a read accepts it, the resolver being read-only then ({tail(r)})")

        argv, log = b.stub(code=3)
        b.config(argv)
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs, f"resolver exit 3 is <repo>/docs, exit 3 ({tail(r)})")
        argv, log = b.stub(out=f"{home}\n", code=3)
        b.config(argv)
        r = run(b, "--for-write")
        check(r.returncode == 3 and r.stdout.strip() == docs,
              f"resolver exit 3 ignores anything it printed, --for-write too ({tail(r)})")

        argv, log = b.stub(code=2, err="store offline: disk-7 not mounted\n")
        b.config(argv)
        r = run(b)
        check(refused(r) and "store offline: disk-7 not mounted" in r.stderr,
              f"resolver exit 2 is exit 2 with its stderr passed on ({tail(r)})")
        argv, log = b.stub(out=f"{home}\n", code=2, err="half-broken\n")
        b.config(argv)
        r = run(b)
        check(refused(r) and "half-broken" in r.stderr,
              f"resolver exit 2 prints no path even if it wrote one ({tail(r)})")

        for code in (1, 4, 127):
            argv, log = b.stub(out=f"{home}\n", code=code, err=f"odd failure {code}\n")
            b.config(argv)
            r = run(b)
            check(refused(r) and f"odd failure {code}" in r.stderr,
                  f"resolver exit {code} is exit 2 with its stderr ({tail(r)})")

        argv, log = b.stub(out=f"{home}\n{home}\n")
        b.config(argv)
        r = run(b)
        check(refused(r), f"two lines are exit 2 ({tail(r)})")
        argv, log = b.stub(out="records/proj\n")
        b.config(argv)
        r = run(b)
        check(refused(r), f"a relative path is exit 2 ({tail(r)})")
        argv, log = b.stub(out="")
        b.config(argv)
        r = run(b)
        check(refused(r), f"exit 0 with nothing printed is exit 2 ({tail(r)})")
        argv, log = b.stub(out=f"  {home}\n")
        b.config(argv)
        r = run(b)
        check(refused(r), f"a padded line is refused, not trimmed ({tail(r)})")
        for label, out in (("a trailing space", f"{home} \n"), ("a CRLF line end", f"{home}\r\n"),
                           ("a bare CR", f"{home}\r"), ("a NUL", f"{home}\x00x\n"),
                           ("a tab inside", f"{home}\tx\n"), ("a lone newline", "\n")):
            argv, log = b.stub(out=out)
            b.config(argv)
            r = run(b)
            check(refused(r), f"{label} is refused, exit 2 ({tail(r)})")

        argv, log = b.stub(out=f"{home}".encode() + b"\xff\n")
        b.config(argv)
        r = run(b)
        check(refused(r), f"stdout that is not UTF-8 with exit 0 is exit 2 ({tail(r)})")
        argv, log = b.stub(out=b"\xff\xfe garbage\r\n\x00", code=3)
        b.config(argv)
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs and no_traceback(r),
              f"garbage stdout with exit 3 is still exit 3, <repo>/docs ({tail(r)})")
        argv, log = b.stub(out=f"{home}\n", err=b"warn \xff\xfe\n")
        b.config(argv)
        r = run(b)
        check(r.returncode == 0 and r.stdout == f"{home}\n",
              f"stderr that is not UTF-8 does not spoil a good exit 0 ({tail(r)})")
        argv, log = b.stub(code=2, err=b"store \xff gone\n")
        b.config(argv)
        r = run(b)
        check(refused(r) and "store \ufffd gone" in r.stderr,
              f"stderr that is not UTF-8 is passed on with replacement characters ({tail(r)})")

        a_file = write(b.root / "records" / "plain-file", "x\n")
        argv, log = b.stub(out=f"{a_file}\n")
        b.config(argv)
        r = run(b, "--for-write")
        check(refused(r), f"--for-write naming a file, not a directory, is exit 2 ({tail(r)})")

        uni = b.root / "récords-ü"
        uni.mkdir()
        argv, log = b.stub(out=f"{uni}\n".encode("utf-8"))
        b.config(argv)
        r = subprocess.run([sys.executable, str(MODULE), "--project", str(b.repo)],
                           capture_output=True, env=b.env(PYTHONIOENCODING="ascii", LC_ALL="C"),
                           timeout=60)
        check(r.returncode == 0 and r.stdout == f"{uni}\n".encode("utf-8"),
              f"a non-ASCII home prints as UTF-8 bytes even under an ASCII locale "
              f"(exit {r.returncode}, {r.stdout[-60:]!r}, {r.stderr[-120:]!r})")

        b.config([str(b.root / "no-such-resolver")])
        r = run(b)
        check(refused(r) and no_traceback(r),
              f"a resolver that cannot be started is exit 2 ({tail(r)})")

        argv, log = b.stub(out=f"{home}\n", sleep=12)
        b.config(argv)
        r = run(b)
        check(refused(r) and no_traceback(r) and r.elapsed < 11.5,
              f"a resolver that sleeps 12 s is cut off at 10 s, exit 2 "
              f"({tail(r)}, {r.elapsed:.1f} s)")


def registers_cases():
    print("--decision-registers:")
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        r = run(b, "--decision-registers")
        check(r.returncode == 3 and r.stdout == "", f"no config prints nothing, exit 3 ({tail(r)})")
        write(b.xdg / "config.yaml", "other: 1\n")
        r = run(b, "--decision-registers")
        check(r.returncode == 3 and r.stdout == "", f"no key prints nothing, exit 3 ({tail(r)})")

        a, c = b.root / "regs" / "a.md", b.root / "regs" / "c.md"
        argv, log = b.stub(out=f"{a}\n{c}\n")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(r.returncode == 0 and r.stdout.splitlines() == [str(a), str(c)],
              f"two absolute paths print in order, exit 0 ({tail(r)})")
        check(logged(log) == ["--project", str(b.repo), "--decision-registers"],
              f"...and the resolver got --project <repo> --decision-registers ({logged(log)})")

        argv, log = b.stub(out="")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(r.returncode == 0 and r.stdout == "", f"zero paths with exit 0 is exit 0, nothing printed ({tail(r)})")

        argv, log = b.stub(out=f"{a}\nregs/c.md\n")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(refused(r), f"a relative line is exit 2, printing none ({tail(r)})")
        argv, log = b.stub(out=f"{a}\n\n{c}\n")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(refused(r), f"a blank line between paths is exit 2 ({tail(r)})")
        for label, out in (("a CRLF line", f"{a}\r\n{c}\n"), ("a NUL", f"{a}\n{c}\x00\n"),
                           ("a trailing space", f"{a} \n{c}\n")):
            argv, log = b.stub(out=out)
            b.config(argv)
            r = run(b, "--decision-registers")
            check(refused(r), f"{label} among the registers is exit 2 ({tail(r)})")
        argv, log = b.stub(out=f"{a}\n".encode() + b"\xff\n")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(refused(r), f"register stdout that is not UTF-8 is exit 2 ({tail(r)})")
        argv, log = b.stub(out=b"\xff junk", code=3)
        b.config(argv)
        r = run(b, "--decision-registers")
        check(r.returncode == 3 and r.stdout == "", f"garbage with exit 3 is still exit 3, nothing printed ({tail(r)})")

        argv, log = b.stub(code=3)
        b.config(argv)
        r = run(b, "--decision-registers")
        check(r.returncode == 3 and r.stdout == "", f"resolver exit 3 prints nothing, exit 3 ({tail(r)})")
        argv, log = b.stub(code=2, err="register store gone\n")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(refused(r) and "register store gone" in r.stderr,
              f"resolver exit 2 is exit 2 with its stderr ({tail(r)})")
        argv, log = b.stub(out=f"{a}\n", code=5, err="weird\n")
        b.config(argv)
        r = run(b, "--decision-registers")
        check(refused(r) and "weird" in r.stderr,
              f"any other resolver exit is exit 2 ({tail(r)})")

        r = run(b, "--decision-registers", "--for-write")
        check(refused(r), f"--decision-registers with --for-write is a usage error ({tail(r)})")


def load_module():
    spec = importlib.util.spec_from_file_location("records_home_under_test", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Environ:
    """Run a block with os.environ replaced, so the API reads a throwaway config."""

    def __init__(self, env):
        self.env = env

    def __enter__(self):
        self.old = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.old)


def api_cases():
    print("the Python API, imported by file path:")
    probe = subprocess.run([sys.executable, "-c",
                            "import importlib.util\n"
                            f"s = importlib.util.spec_from_file_location('m', {str(MODULE)!r})\n"
                            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"],
                           capture_output=True, text=True, timeout=60)
    check(probe.returncode == 0 and probe.stdout == "" and probe.stderr == "",
          f"importing prints nothing and does nothing ({probe.returncode}, {probe.stderr.strip()[-100:]!r})")
    try:
        mod = load_module()
    except Exception as e:
        check(False, f"records_home.py loads by file path ({e!r})")
        return
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        docs = str(b.repo / "docs")
        with Environ(b.env()):
            got = mod.resolve(str(b.repo))
            check(got[:2] == (3, docs) and len(got) == 3, f"resolve() with no config is (3, <repo>/docs, …) ({got})")
            got = mod.decision_registers(str(b.repo))
            check(got[:2] == (3, []) and len(got) == 3, f"decision_registers() with no config is (3, [], …) ({got})")
            got = mod.resolve("relative/proj")
            check(got[0] == 2 and got[1] is None, f"resolve() refuses a relative project ({got})")

            home = b.root / "records"
            home.mkdir()
            argv, log = b.stub(out=f"{home}\n")
            b.config(argv)
            got = mod.resolve(str(b.repo), for_write=True)
            check(got[:2] == (0, str(home)), f"resolve(for_write=True) returns the home ({got})")
            check(logged(log) == ["--project", str(b.repo), "--for-write"], f"...passing --for-write ({logged(log)})")
            argv, log = b.stub(code=2, err="offline\n")
            b.config(argv)
            got = mod.resolve(str(b.repo))
            check(got[0] == 2 and got[1] is None and "offline" in got[2],
                  f"resolve() on a resolver exit 2 carries its stderr ({got})")
            argv, log = b.stub(out=f"{home}/a.md\n{home}/b.md\n")
            b.config(argv)
            got = mod.decision_registers(str(b.repo))
            check(got[:2] == (0, [f"{home}/a.md", f"{home}/b.md"]), f"decision_registers() lists the paths ({got})")
            argv, log = b.stub(out=f"{home}/a.md\n", sleep=3)
            b.config(argv)
            old = mod.TIMEOUT
            mod.TIMEOUT = 1
            try:
                got = mod.decision_registers(str(b.repo))
            finally:
                mod.TIMEOUT = old
            check(got[0] == 2 and got[1] == [], f"decision_registers() maps a timeout to 2 ({got})")
            check(old == 10, f"the timeout is 10 s ({old})")

            # A resolver that exits at once but leaves a child holding its stdout open:
            # the timeout must still bind, and the child must not outlive the call.
            pidfile = b.root / "child.pid"
            orphaner = write(b.stubs / "orphaner.py", (
                "import subprocess, sys\n"
                "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
                f"print({str(home)!r}, flush=True)\n"))
            b.config([sys.executable, str(orphaner)])
            mod.TIMEOUT = 1
            t = time.monotonic()
            try:
                got = mod.resolve(str(b.repo))
            finally:
                mod.TIMEOUT = old
            took = time.monotonic() - t
            check(got[0] == 2 and got[1] is None and took < 2.5,
                  f"a child holding stdout open cannot stretch the timeout ({got}, {took:.1f} s)")
            child = int(pidfile.read_text()) if pidfile.exists() else None
            gone = False
            for _ in range(40):
                try:
                    state = Path(f"/proc/{child}/stat").read_text().split(")")[-1].split()[0]
                    gone = state == "Z"
                except (OSError, TypeError, IndexError):
                    gone = child is not None
                if gone:
                    break
                time.sleep(0.05)
            check(gone, f"...and that child is killed with the resolver's process group (pid {child})")


def config_cases():
    print("finding the config:")
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        docs = str(b.repo / "docs")
        h_xdg = b.root / "records" / "from-xdg"
        h_named = b.root / "records" / "from-named"
        h_cwd = b.root / "records" / "from-cwd"
        for d in (h_xdg, h_named, h_cwd):
            d.mkdir(parents=True)
        argv_xdg, _ = b.stub(out=f"{h_xdg}\n")
        argv_named, _ = b.stub(out=f"{h_named}\n")
        argv_cwd, _ = b.stub(out=f"{h_cwd}\n")
        b.config(argv_xdg)
        named = b.config(argv_named, where=b.root / "elsewhere" / "mine.yaml")

        r = run(b, env=b.env(STAGED_PLANNING_CONFIG=named))
        check(r.returncode == 0 and r.stdout.strip() == str(h_named),
              f"$STAGED_PLANNING_CONFIG wins over XDG ({tail(r)})")
        typo = b.root / "typo.yaml"
        r = run(b, env=b.env(STAGED_PLANNING_CONFIG=typo))
        check(refused(r) and str(typo) in r.stderr,
              f"$STAGED_PLANNING_CONFIG naming a missing file is exit 2, naming it ({tail(r)})")
        r = run(b, "--decision-registers", env=b.env(STAGED_PLANNING_CONFIG=typo))
        check(refused(r), f"...for --decision-registers too ({tail(r)})")
        r = run(b, env=b.env(STAGED_PLANNING_CONFIG="  "))
        check(r.returncode == 0 and r.stdout.strip() == str(h_xdg),
              f"a blank $STAGED_PLANNING_CONFIG counts as unset ({tail(r)})")
        r = run(b, env=b.env(STAGED_PLANNING_CONFIG=""))
        check(r.returncode == 0 and r.stdout.strip() == str(h_xdg),
              f"an empty $STAGED_PLANNING_CONFIG counts as unset ({tail(r)})")
        r = run(b, env=b.env(drop=("XDG_CONFIG_HOME",)))
        check(r.returncode == 0 and r.stdout.strip() == str(h_xdg),
              f"XDG_CONFIG_HOME unset defaults to ~/.config ({tail(r)})")

        # A relative XDG_CONFIG_HOME that does resolve from the cwd must still be ignored.
        b.config(argv_cwd, where=b.root / "relxdg" / "staged-planning" / "config.yaml")
        r = run(b, env=b.env(XDG_CONFIG_HOME="relxdg"), cwd=b.root)
        check(r.returncode == 0 and r.stdout.strip() == str(h_xdg),
              f"a relative XDG_CONFIG_HOME is ignored, never cwd-relative ({tail(r)})")
        (b.xdg / "config.yaml").unlink()
        r = run(b, env=b.env(XDG_CONFIG_HOME="relxdg"), cwd=b.root)
        check(r.returncode == 3 and r.stdout.strip() == docs,
              f"...so with nothing under ~/.config the answer is exit 3 ({tail(r)})")

        b.config(argv_named, where=b.home / "tilde.yaml")
        r = run(b, env=b.env(STAGED_PLANNING_CONFIG="~/tilde.yaml"))
        check(r.returncode == 0 and r.stdout.strip() == str(h_named),
              f"a ~ in $STAGED_PLANNING_CONFIG expands ({tail(r)})")
        stub_in_home = write(b.home / "bin" / "res.py", f"print({str(h_xdg)!r})\n")
        b.config([sys.executable, "~/" + str(stub_in_home.relative_to(b.home))])
        r = run(b)
        check(r.returncode == 0 and r.stdout.strip() == str(h_xdg),
              f"a ~ in a records_resolver: string expands ({tail(r)})")

        no_pw = ("import pwd\n"
                 "pwd.getpwuid = lambda uid: (_ for _ in ()).throw(KeyError('no passwd entry'))\n"
                 "pwd.getpwnam = lambda name: (_ for _ in ()).throw(KeyError('no passwd entry'))\n")
        for label, extra, want in (
                ("a ~ config path with no HOME and no passwd entry is exit 2, naming it as written",
                 {"STAGED_PLANNING_CONFIG": "~/x.yaml"}, 2),
                ("no HOME, no passwd entry and nothing configured is exit 3", {}, 3)):
            env = {k: v for k, v in b.env().items() if k not in ("HOME", "XDG_CONFIG_HOME")}
            env.update(extra)
            r = subprocess.run([sys.executable, "-c",
                                no_pw + "import sys, runpy\n"
                                f"sys.argv = [{str(MODULE)!r}, '--project', {str(b.repo)!r}]\n"
                                f"runpy.run_path({str(MODULE)!r}, run_name='__main__')\n"],
                               capture_output=True, text=True, env=env, timeout=60)
            ok = r.returncode == want and no_traceback(r)
            if want == 2:
                ok = ok and "~/x.yaml" in r.stderr
            check(ok, f"{label} ({tail(r)})")

        cfg = b.xdg / "config.yaml"
        cfg.unlink()
        cfg.mkdir()
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs and no_traceback(r),
              f"a config.yaml that is a directory is no config, exit 3 ({tail(r)})")
        cfg.rmdir()
        cfg.symlink_to(b.root / "nowhere.yaml")
        r = run(b)
        check(r.returncode == 3 and r.stdout.strip() == docs and no_traceback(r),
              f"a config.yaml that is a dangling symlink is no config, exit 3 ({tail(r)})")
        cfg.unlink()

        odd = b.root / os.fsdecode(b"pr\xffoj")
        odd.mkdir()
        r = subprocess.run([sys.executable, str(MODULE), "--project", os.fsencode(odd)],
                           capture_output=True, env=b.env(), timeout=60)
        check(r.returncode == 3 and r.stdout == os.fsencode(odd) + b"/docs\n",
              f"a repo path that is not UTF-8 prints back byte for byte "
              f"(exit {r.returncode}, {r.stdout[-60:]!r}, {r.stderr[-120:]!r})")

        locked = b.home / ".config"
        if os.geteuid() == 0:
            print("  skip: an unreadable ~/.config (running as root, chmod does not bind)")
        else:
            locked.chmod(0)
            try:
                r = run(b, env=b.env(drop=("XDG_CONFIG_HOME",)))
                check(r.returncode == 3 and r.stdout.strip() == docs and no_traceback(r),
                      f"an unreadable ~/.config is no config, never a raise ({tail(r)})")
            finally:
                locked.chmod(0o755)


def malformed_cases():
    print("a config or call that cannot be honestly read is exit 2:")
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        cfg = b.xdg / "config.yaml"
        for label, text in (
                ("unparseable YAML", "records_resolver: [unclosed\n"),
                ("a top level that is not a mapping", "- a\n- b\n"),
                ("records_resolver: as a string", "records_resolver: python3 res.py\n"),
                ("records_resolver: with a number in it", "records_resolver: [python3, 5]\n"),
                ("records_resolver: as an empty list", "records_resolver: []\n"),
                ("records_resolver: with no value", "records_resolver:\n"),
                ("records_resolver: with an empty string", "records_resolver: ['', x]\n"),
                ("records_resolver: as a mapping", "records_resolver: {a: b}\n")):
            write(cfg, text)
            for flag in ((), ("--decision-registers",)):
                r = run(b, *flag)
                check(refused(r) and no_traceback(r),
                      f"{label}{' (--decision-registers)' if flag else ''} ({tail(r)})")
        write(cfg, "records_resolver: [python3, x]\n")
        r = subprocess.run([sys.executable, "-c",
                            "import sys, runpy; sys.modules['yaml'] = None; "
                            f"sys.argv = [{str(MODULE)!r}, '--project', {str(b.repo)!r}]; "
                            f"runpy.run_path({str(MODULE)!r}, run_name='__main__')"],
                           capture_output=True, text=True, env=b.env(), timeout=60)
        check(refused(r) and no_traceback(r),
              f"a config file with PyYAML missing is exit 2 ({tail(r)})")
        if os.geteuid() != 0:
            cfg.chmod(0)
            try:
                r = run(b)
                check(refused(r) and no_traceback(r),
                      f"a config file that exists but cannot be read is exit 2 ({tail(r)})")
            finally:
                cfg.chmod(0o644)

        cfg.unlink()
        r = run(b, project="work/proj", cwd=b.root)
        check(refused(r) and no_traceback(r),
              f"a relative --project is a usage error, exit 2, even with no config ({tail(r)})")
        r = run(b, "--decision-registers", project="work/proj", cwd=b.root)
        check(refused(r), f"...for --decision-registers too ({tail(r)})")
        r = run(b, project=False)
        check(refused(r), f"no --project is a usage error, exit 2 ({tail(r)})")


def hardening_cases():
    print("nothing resolves against the caller's directory, and a home is a directory:")
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        home = b.root / "records" / "proj"
        home.mkdir(parents=True)

        # A relative $STAGED_PLANNING_CONFIG that does exist under the cwd is refused.
        argv, _ = b.stub(out=f"{home}\n")
        b.config(argv, where=b.root / "rel" / "c.yaml")
        r = run(b, env=b.env(STAGED_PLANNING_CONFIG="rel/c.yaml"), cwd=b.root)
        check(refused(r) and "must be an absolute path" in r.stderr,
              f"a relative $STAGED_PLANNING_CONFIG is exit 2, even when it exists ({tail(r)})")
        r = run(b, "--decision-registers", env=b.env(STAGED_PLANNING_CONFIG="rel/c.yaml"),
                cwd=b.root)
        check(refused(r), f"...for --decision-registers too ({tail(r)})")
        r = run(b, env=b.env(STAGED_PLANNING_CONFIG="c.yaml"), cwd=b.root / "rel")
        check(refused(r) and "must be an absolute path" in r.stderr,
              f"a bare config filename is relative too, exit 2 ({tail(r)})")

        # records_resolver: an element with a / that is not absolute names a script the
        # current project holds; it is refused even when that script exists under the cwd.
        write(b.root / "tools" / "r.sh", f"#!/bin/sh\necho {home}\n").chmod(0o755)
        for label, argv in (("[bash, tools/r.sh]", ["bash", "tools/r.sh"]),
                            ("[./tools/r.sh]", ["./tools/r.sh"]),
                            ("[bash, tools/../tools/r.sh]",["bash", "tools/../tools/r.sh"])):
            b.config(argv)
            r = run(b, cwd=b.root)
            check(refused(r) and "absolute" in r.stderr,
                  f"records_resolver: {label} is exit 2 ({tail(r)})")
            r = run(b, "--decision-registers", cwd=b.root)
            check(refused(r), f"...{label} with --decision-registers too ({tail(r)})")
        good = write(b.stubs / "abs-r.py", f"print({str(home)!r})\n")
        b.config(["python3", str(good)])
        r = run(b, cwd=b.root)
        check(r.returncode == 0 and r.stdout.strip() == str(home),
              f"[python3, /abs/r.py] still works: a bare command name is a PATH lookup ({tail(r)})")
        b.config([sys.executable, "-c", "import os; print(os.getcwd())"])
        r = run(b, cwd=b.root)
        check(r.returncode == 0 and r.stdout.strip() == "/",
              f"the resolver runs with / as its working directory, not the caller's ({tail(r)})")

        # An exit-0 home that exists but is not a directory is refused in read mode too.
        a_file = write(b.root / "records" / "plain-file", "x\n")
        argv, _ = b.stub(out=f"{a_file}\n")
        b.config(argv)
        r = run(b)
        check(refused(r) and "not a directory" in r.stderr,
              f"a read naming a file, not a directory, is exit 2 ({tail(r)})")
        missing = b.root / "records" / "not-made-yet"
        argv, _ = b.stub(out=f"{missing}\n")
        b.config(argv)
        r = run(b)
        check(r.returncode == 0 and r.stdout.strip() == str(missing),
              f"...while a read naming a home that does not exist yet is still exit 0 ({tail(r)})")


def config_value_cases():
    print("config_value(), the other keys of the same config file:")
    try:
        mod = load_module()
    except Exception as e:
        check(False, f"records_home.py loads by file path ({e!r})")
        return
    if not hasattr(mod, "config_value"):
        check(False, "records_home.py has a config_value() helper")
        return
    with tempfile.TemporaryDirectory() as tmp:
        b = Box(Path(tmp))
        with Environ(b.env()):
            got = mod.config_value("some_key")
            check(got == (None, ""), f"no config file is (None, '') ({got!r})")
            write(b.xdg / "config.yaml", "some_key: [a-, b-]\nother: 3\n")
            got = mod.config_value("some_key")
            check(got == (["a-", "b-"], ""), f"the XDG config's value is returned as parsed ({got!r})")
            got = mod.config_value("other")
            check(got == (3, ""), f"...whatever its type: the caller checks the shape ({got!r})")
            got = mod.config_value("absent")
            check(got == (None, ""), f"a missing key is (None, '') ({got!r})")
            write(b.xdg / "config.yaml", "")
            got = mod.config_value("some_key")
            check(got == (None, ""), f"an empty config is (None, '') ({got!r})")
            write(b.xdg / "config.yaml", "some_key: [a-\n")
            got = mod.config_value("some_key")
            check(got[0] is None and "not valid YAML" in got[1],
                  f"YAML that does not parse is None plus a message ({got!r})")
            write(b.xdg / "config.yaml", "- a\n- b\n")
            got = mod.config_value("some_key")
            check(got[0] is None and "mapping" in got[1],
                  f"a top level that is not a mapping is None plus a message ({got!r})")
            log = b.stubs / "ran.txt"
            stub = write(b.stubs / "logs-if-run.py", f"open({str(log)!r}, 'w').write('ran')\n")
            write(b.xdg / "config.yaml",
                  f"records_resolver: [{sys.executable!r}, {str(stub)!r}]\nsome_key: x\n")
            got = mod.config_value("some_key")
            check(got == ("x", "") and not log.exists(),
                  f"reading a key never runs the records resolver ({got!r}, ran={log.exists()})")
        named = write(b.root / "named.yaml", "some_key: from-named\n")
        with Environ(b.env(STAGED_PLANNING_CONFIG=named)):
            got = mod.config_value("some_key")
            check(got == ("from-named", ""), f"$STAGED_PLANNING_CONFIG wins over the XDG file ({got!r})")
        with Environ(b.env(STAGED_PLANNING_CONFIG=b.root / "missing.yaml")):
            got = mod.config_value("some_key")
            check(got[0] is None and "missing.yaml" in got[1],
                  f"a named config that is not a file is None plus a message naming it ({got!r})")
        with Environ(b.env(STAGED_PLANNING_CONFIG="rel/config.yaml")):
            got = mod.config_value("some_key")
            check(got[0] is None and "absolute" in got[1],
                  f"a relative $STAGED_PLANNING_CONFIG is None plus a message ({got!r})")
        with Environ(b.env(STAGED_PLANNING_CONFIG="  ")):
            got = mod.config_value("some_key")
            check(got == ("x", ""), f"a blank $STAGED_PLANNING_CONFIG counts as unset ({got!r})")
        with Environ(b.env()):
            try:
                got = mod.config_value(None)
                check(isinstance(got, tuple) and len(got) == 2 and got[0] is None,
                      f"a key that is not a string is (None, …), never an exception ({got!r})")
            except Exception as e:
                check(False, f"config_value() never raises ({e!r})")


default_home_cases()
hardening_cases()
mapping_cases()
registers_cases()
config_cases()
malformed_cases()
api_cases()
config_value_cases()

print()
if FAILURES:
    print(f"FAIL: {len(FAILURES)} check(s) failed")
    sys.exit(1)
print("OK")
