#!/usr/bin/env python3
"""A script running from a superseded plugin cache says so, once, on stderr.

A host can keep every installed plugin version side by side under
`.../plugins/cache/<marketplace>/<plugin>/<version>/`, and nothing pins which one an
invocation resolves to. A stale copy passes its own tests, so the staleness is invisible
unless something compares it with the checkout. core/lib/staleness.py is that
comparison; the checkout is named by $STAGED_PLANNING_CHECKOUT.

Properties tested:
  1. `warn_if_stale()` warns when, and only when, the checkout is genuinely ahead.
  2. Every degraded input is silent: no checkout configured, a missing checkout, no or
     a broken manifest, an unparseable version, a different marketplace, not cached.
  3. The opt-out silences it, and a warning sets the opt-out so children stay quiet,
     tested across a real process boundary.
  Each silence block ends with a teeth case: the same inputs, opt-out cleared, warn.

Every fixture is a synthetic tree under a temp directory. HOME is redirected for the
whole run so nothing on the host can be read by accident.

Stdlib only, no pytest. Run:  python3 core/lib/tests/test-staleness.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "staleness.py"
MARKET = "example-market"
OPT_OUT = "STAGED_PLANNING_NO_STALE_WARNING"
CHECKOUT_VAR = "STAGED_PLANNING_CHECKOUT"

FAILURES: list[str] = []


def check(ok, msg):
    print(f"  {'ok' if ok else 'FAIL'}: {msg}")
    if not ok:
        FAILURES.append(msg)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = load(LIB, "staleness")


def make_checkout(root: Path, plugin: str, version, market=MARKET):
    """A checkout whose marketplace.json advertises `version` for `plugin`."""
    root.mkdir(parents=True, exist_ok=True)
    man = root / ".claude-plugin"
    man.mkdir(exist_ok=True)
    (man / "marketplace.json").write_text(json.dumps({
        "name": market,
        "metadata": {"version": "1.0.0"},
        "plugins": [{"name": "other-plugin", "version": "9.9.9"},
                    {"name": plugin, "version": version}],
    }))
    return root


def cached_script(root: Path, plugin: str, version: str, market=MARKET, name="tool.py"):
    """A path shaped like an installed plugin cache. The file need not exist for the
    coordinate parse; cases that RUN it create it themselves."""
    return (root / "plugins" / "cache" / market / plugin / version
            / "skills" / "some-skill" / "scripts" / name)


def capture(fn, *a, checkout=None, **kw):
    """(result, stderr-text) with the checkout variable set (or unset when None).

    Clears the opt-out first: a successful warn SETS it to silence children, so
    without this every case after the first would pass by being suppressed rather
    than by the property it claims to test.
    """
    os.environ.pop(OPT_OUT, None)
    if checkout is None:
        os.environ.pop(CHECKOUT_VAR, None)
    else:
        os.environ[CHECKOUT_VAR] = str(checkout)
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            res = fn(*a, **kw)
    finally:
        os.environ.pop(CHECKOUT_VAR, None)
    return res, err.getvalue()


def helper_cases(rootp: Path):
    print("warn_if_stale — warns exactly when the checkout is ahead:")
    checkout = make_checkout(rootp / "checkout", "planning", "0.44.0")
    script = cached_script(rootp, "planning", "0.43.1")

    msg, err = capture(ss.warn_if_stale, script, checkout=checkout)
    check(msg is not None and "0.43.1" in msg and "0.44.0" in msg,
          f"a newer checkout warns, naming both versions ({msg!r})")
    check(msg is not None and msg in err and err.count("\n") == 1,
          "...exactly one line, on stderr")
    check(str(checkout) in (msg or ""), "...and names the checkout")
    check(OPT_OUT in (msg or ""), "...and names the opt-out variable")

    out = io.StringIO()
    os.environ.pop(OPT_OUT, None)
    os.environ[CHECKOUT_VAR] = str(checkout)
    try:
        from contextlib import redirect_stdout
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            ss.warn_if_stale(script)
    finally:
        os.environ.pop(CHECKOUT_VAR, None)
    check(out.getvalue() == "", "nothing is ever written to stdout")

    msg, err = capture(ss.warn_if_stale, cached_script(rootp, "planning", "0.44.0"),
                       checkout=checkout)
    check(msg is None and err == "", "an up-to-date cache says nothing at all")
    msg, err = capture(ss.warn_if_stale, cached_script(rootp, "planning", "0.99.0"),
                       checkout=checkout)
    check(msg is None and err == "", "a checkout BEHIND the cache is silent")
    msg, _ = capture(ss.warn_if_stale, cached_script(rootp, "not-a-plugin", "0.1.0"),
                     checkout=checkout)
    check(msg is None, "a plugin absent from the manifest is silent")

    print("warn_if_stale — equal versions written at different widths:")
    short = make_checkout(rootp / "short", "planning", "0.44")
    check(ss._version_tuple("0.44") == ss._version_tuple("0.44.0")
          == ss._version_tuple("0.44.0.0"),
          "0.44, 0.44.0 and 0.44.0.0 parse to ONE tuple")
    msg, _ = capture(ss.warn_if_stale, cached_script(rootp, "planning", "0.44.0"),
                     checkout=short)
    check(msg is None, "checkout '0.44' vs cache '0.44.0' is silent (a pin, not teeth)")
    msg, _ = capture(ss.warn_if_stale, cached_script(rootp, "planning", "0.44"),
                     checkout=checkout)
    check(msg is None, "...and the mirror image is silent too")
    msg, _ = capture(ss.warn_if_stale, cached_script(rootp, "planning", "0.43"),
                     checkout=checkout)
    check(msg is not None, "...while 0.43 vs 0.44.0 still warns")

    print("warn_if_stale — every degraded input is silent, never fatal:")
    msg, err = capture(ss.warn_if_stale, script, checkout=None)
    check(msg is None and err == "", "no $STAGED_PLANNING_CHECKOUT: silent")
    msg, err = capture(ss.warn_if_stale, script, checkout="")
    check(msg is None and err == "", "a blank $STAGED_PLANNING_CHECKOUT: silent")
    msg, _ = capture(ss.warn_if_stale, script, checkout=rootp / "absent")
    check(msg is None, "a checkout that does not exist: silent")
    (rootp / "empty").mkdir()
    msg, _ = capture(ss.warn_if_stale, script, checkout=rootp / "empty")
    check(msg is None, "a checkout with no marketplace.json: silent")
    broken = rootp / "broken"
    (broken / ".claude-plugin").mkdir(parents=True)
    (broken / ".claude-plugin" / "marketplace.json").write_text("{{{ not json")
    msg, _ = capture(ss.warn_if_stale, script, checkout=broken)
    check(msg is None, "an unparseable marketplace.json: silent")
    listy = rootp / "listy"
    (listy / ".claude-plugin").mkdir(parents=True)
    (listy / ".claude-plugin" / "marketplace.json").write_text("[1, 2]")
    msg, _ = capture(ss.warn_if_stale, script, checkout=listy)
    check(msg is None, "a manifest that is not an object: silent")
    weird = make_checkout(rootp / "weird", "planning", "not-a-version")
    msg, _ = capture(ss.warn_if_stale, script, checkout=weird)
    check(msg is None, "an unparseable manifest version: silent, never a guess")
    nonstr = make_checkout(rootp / "nonstr", "planning", None)
    msg, _ = capture(ss.warn_if_stale, script, checkout=nonstr)
    check(msg is None, "a missing manifest version: silent")
    other = make_checkout(rootp / "other-market", "planning", "0.44.0", market="elsewhere")
    msg, _ = capture(ss.warn_if_stale, script, checkout=other)
    check(msg is None, "a checkout of a DIFFERENT marketplace: silent")
    msg, _ = capture(ss.warn_if_stale, rootp / "checkout" / "skills" / "x" / "tool.py",
                     checkout=checkout)
    check(msg is None, "a script running from a checkout, not a cache: silent")
    msg, _ = capture(ss.warn_if_stale, cached_script(rootp, "planning", "v-next"),
                     checkout=checkout)
    check(msg is None, "an unparseable cache version: silent")
    msg, _ = capture(ss.warn_if_stale, object(), checkout=checkout)
    check(msg is None, "a nonsense argument: silent, never raises")

    os.environ[OPT_OUT] = "1"
    os.environ[CHECKOUT_VAR] = str(checkout)
    try:
        err = io.StringIO()          # not capture(): that clears the variable
        with redirect_stderr(err):
            msg = ss.warn_if_stale(script)
        check(msg is None and err.getvalue() == "",
              "STAGED_PLANNING_NO_STALE_WARNING silences a genuine warning")
    finally:
        os.environ.pop(OPT_OUT, None)
        os.environ.pop(CHECKOUT_VAR, None)

    msg, _ = capture(ss.warn_if_stale, script, checkout=checkout)
    check(msg is not None, "...and with it unset the same call warns — the silences are "
                           "guards, not a dead probe")


def dedupe_cases(rootp: Path):
    """One user invocation, one warning, across process boundaries."""
    print("dedupe — one invocation warns once, children stay quiet:")
    checkout = make_checkout(rootp / "dd-checkout", "planning", "0.44.0")
    script = cached_script(rootp, "planning", "0.43.1")

    first, _ = capture(ss.warn_if_stale, script, checkout=checkout)
    os.environ[CHECKOUT_VAR] = str(checkout)
    err2 = io.StringIO()
    try:
        with redirect_stderr(err2):      # deliberately NOT capture(): keep the state
            second = ss.warn_if_stale(script)
    finally:
        os.environ.pop(CHECKOUT_VAR, None)
    check(first is not None and second is None and err2.getvalue() == "",
          "a second call in the same process is silent — having warned sets the flag")
    check(os.environ.get(OPT_OUT) == "1", "...via the env var children inherit")
    os.environ.pop(OPT_OUT, None)

    # Across a real process boundary: a parent in a cache-shaped tree warns, then
    # spawns a child that runs the same probe.
    cache = rootp / "plugins" / "cache" / MARKET / "planning" / "0.43.1"
    (cache / "lib").mkdir(parents=True)
    (cache / "lib" / "staleness.py").write_bytes(LIB.read_bytes())
    scripts = cache / "skills" / "some-skill" / "scripts"
    scripts.mkdir(parents=True)
    probe = ("import importlib.util, sys\n"
             "from pathlib import Path\n"
             "lib = Path(__file__).resolve().parents[3] / 'lib' / 'staleness.py'\n"
             "spec = importlib.util.spec_from_file_location('_s', lib)\n"
             "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
             "got = m.warn_if_stale(__file__)\n")
    (scripts / "child.py").write_text(probe)
    (scripts / "parent.py").write_text(
        probe + "print('PARENT-WARNED' if got else 'PARENT-SILENT', file=sys.stderr)\n"
        "import subprocess\n"
        "subprocess.run([sys.executable, str(Path(__file__).with_name('child.py'))],\n"
        "               stdin=subprocess.DEVNULL)\n")
    env = dict(os.environ, **{CHECKOUT_VAR: str(checkout)})
    env.pop(OPT_OUT, None)
    r = subprocess.run([sys.executable, str(scripts / "parent.py")], env=env,
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    check("PARENT-WARNED" in r.stderr and r.stderr.count("warning: running") == 1,
          f"a parent that warned silences the child it spawns (stderr={r.stderr!r})")
    check(r.stdout == "", "...and neither process wrote to stdout")

    r = subprocess.run([sys.executable, str(scripts / "child.py")], env=env,
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    check(r.stderr.count("warning: running") == 1,
          "...and an unsuppressed child warns by itself — the probe is live in it")

    env_off = dict(env)
    env_off.pop(CHECKOUT_VAR, None)
    r = subprocess.run([sys.executable, str(scripts / "child.py")], env=env_off,
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    check(r.returncode == 0 and r.stderr == "",
          "...and with no checkout configured the same child is silent and exits 0")


def main():
    old_home = os.environ.get("HOME")
    with tempfile.TemporaryDirectory(prefix="staleness-") as root:
        rootp = Path(root)
        os.environ["HOME"] = str(rootp / "no-such-home")
        try:
            helper_cases(rootp)
            dedupe_cases(rootp)
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
