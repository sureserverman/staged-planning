#!/usr/bin/env python3
"""One-line warning when a script runs from a plugin cache the checkout has moved past.

A host can install plugins into `.../plugins/cache/<marketplace>/<plugin>/<version>/` and
keep every installed version side by side. Nothing pins which one an invocation resolves
to, so a script can be running from a version whose bug the checkout fixed long ago. The
failure is silent and self-concealing: the stale copy behaves exactly as its own tests
said it should, and the operator reads a correct-looking result from superseded code.

The checkout to compare against is named by `$STAGED_PLANNING_CHECKOUT` (a directory
holding `.claude-plugin/marketplace.json`). Unset or blank, the probe is silent: it has
nothing to compare with, and it never goes looking.

So this is a **diagnostic, never a control**. It writes one line to stderr and returns;
it never exits and never changes what the caller computes. Its one side effect concerns
the warning, not the work: having warned, it sets `STAGED_PLANNING_NO_STALE_WARNING` in
its own environment so child processes carrying the same probe stay quiet. Every failure
mode (no checkout, unreadable manifest, unparseable version, a different marketplace,
not running from a cache at all) degrades to silence, because a broken staleness probe
must not be able to take down the command it advises on. A missed warning costs one
confusing session; a probe that raises costs the command.

**stderr, not stdout, is load-bearing.** Some callers emit one JSON document on stdout
that other tools parse; a warning there would be a syntax error in someone else's input.

The version comparison reads the checkout's own `.claude-plugin/marketplace.json`, the
manifest the repo's version-mirror check already treats as a mirror site, so this never
invents a second opinion about what version a plugin is.

Stdlib only, no I/O on import.
"""
import json
import os
import sys
from pathlib import Path

CHECKOUT_ENV = "STAGED_PLANNING_CHECKOUT"
OPT_OUT_ENV = "STAGED_PLANNING_NO_STALE_WARNING"


def _cache_coords(path):
    """(marketplace, plugin, version) if `path` sits inside a plugin cache, else None.

    Matched structurally, `.../plugins/cache/<marketplace>/<plugin>/<version>/...`, rather
    than by a fixed home directory, because the host's config root is relocatable and a
    probe keyed to one home would report "not cached" on exactly the machines that moved
    it: a silent false negative.
    """
    parts = path.parts
    for i in range(len(parts) - 4):
        if parts[i] == "plugins" and parts[i + 1] == "cache":
            return parts[i + 2], parts[i + 3], parts[i + 4]
    return None


def _version_tuple(s):
    """(1, 2, 3, 0) from "1.2.3", or None if it is not a plain dotted-numeric version.

    None means "cannot compare", and every caller treats that as silence. Guessing an
    ordering for a version this does not understand would produce a warning whose
    direction is unknown, which is worse than none because the operator would act on it.
    """
    parts = str(s).split(".")
    if not (1 <= len(parts) <= 4):
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    # Padded to a fixed width: Python compares tuples lexicographically, so (0, 44) <
    # (0, 44, 0), and "0.44" and "0.44.0", the same version, would compare unequal in
    # the direction that invents a warning.
    return tuple(nums + [0] * (4 - len(nums)))


def _checkout():
    """The configured checkout directory, or None when unset or blank."""
    raw = os.environ.get(CHECKOUT_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def _manifest(checkout):
    """The checkout's marketplace.json as a dict, or None."""
    try:
        doc = json.loads((checkout / ".claude-plugin" / "marketplace.json")
                         .read_text(encoding="utf-8"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _manifest_version(doc, plugin):
    """`plugin`'s version in a marketplace manifest, or None."""
    for entry in doc.get("plugins") or []:
        if isinstance(entry, dict) and entry.get("name") == plugin:
            return entry.get("version")
    return None


def warn_if_stale(script, stream=None):
    """Print one stderr line if `script` runs from a cache the checkout has moved past.

    Returns the message it printed, or None. The return value exists for tests;
    callers ignore it, and nothing about this function's result may change what a
    caller does.
    """
    stream = stream or sys.stderr
    if os.environ.get(OPT_OUT_ENV):
        # An operator deliberately running an old cache (bisecting a regression, or
        # reproducing a report against the version that produced it) should not be
        # nagged on every invocation.
        return None
    try:
        coords = _cache_coords(Path(script).resolve())
        if coords is None:
            return None                      # running from a checkout: nothing to compare
        marketplace, plugin, running = coords
        running_v = _version_tuple(running)
        if running_v is None:
            return None
        checkout = _checkout()
        if checkout is None or not checkout.is_dir():
            return None                      # not configured or absent: stay silent
        doc = _manifest(checkout)
        if doc is None or doc.get("name") != marketplace:
            # A checkout of some other marketplace says nothing about this cache.
            return None
        latest = _manifest_version(doc, plugin)
        latest_v = _version_tuple(latest)
        if latest_v is None or latest_v <= running_v:
            # `<=`, so a checkout BEHIND the cache stays silent. That is a real state
            # (a branch reverted, a rebase in progress), and it is not staleness.
            return None
        msg = (f"warning: running {plugin} {running} from the plugin cache, but "
               f"{checkout} has {latest}. Re-add the marketplace to pick it up, or set "
               f"{OPT_OUT_ENV}=1 to silence this.")
        print(msg, file=stream)
        # Silence descendants. A command that forks children carrying this same probe
        # would otherwise repeat the identical line once per process. Children inherit
        # os.environ, so setting the opt-out here makes the warning per USER INVOCATION
        # rather than per process. A deliberate mutation in an otherwise side-effect-free
        # probe: the alternative is every caller remembering to pass a suppressed
        # environment to every subprocess, which is correct the day it is written and
        # wrong the day someone adds one more subprocess.
        os.environ[OPT_OUT_ENV] = "1"
        return msg
    except Exception:
        # Over and above the per-step guards: this probe is never worth a traceback in a
        # command that was otherwise going to succeed.
        return None
