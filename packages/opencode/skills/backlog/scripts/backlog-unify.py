#!/usr/bin/env python3
"""backlog-unify — `backlog unify`: plan candidates into the project's backlog.md.

Reads the project's plans from `<records home>/plans/`, applies the plan-parser rules
(`lib/plan_parser.py`, documented in planning-projects `references/plan-parser.md`),
dedups against `<records home>/backlog.md` by exact `**Source:**` string, and with
`--write` appends BL-NNN entries tagged `auto-unified`. Dry-run by default.

The records home comes from `lib/records_home.py`: the repo's `docs/` when nothing is
configured, or whatever a configured records resolver says. A resolver that is
configured but cannot reach its storage stops the command (exit 2) and nothing is
written: a missing store is not an empty one.

Candidate signals (accept-all policy):
  - Status-authoritative tasks: `- **Status:** [ ]` -> one candidate per task
    (signal status-unexecuted); `[~]` -> status-partial; `[x]` -> done, nothing.
  - Legacy plans without Status fields: every unchecked `- [ ]` outside Preflight,
    Decisions-in-force and gate blocks, in a stage not shown executed.
  - Deferred-section bullets (`## Deferred` / `### Deferred`), in both modes.
Excluded: Preflight bullets, stage-gate bullets, `*-done.md` summaries, and items in
plans older than the stale threshold unless `--include-stale` (staleness comes from the
filename's YYYY-MM-DD stamp, because a records home need not be a git repo).

Usage: backlog-unify.py [--project <repo>] [--write] [--include-stale]
Exit: 0 done, 2 the records home is unreachable or the arguments are unusable.
"""
import argparse
import datetime
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[3] / "lib"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _LIB / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pp = _load("staged_planning_plan_parser", "plan_parser.py")
TODAY = datetime.date.today().isoformat()

HEADER = ("# Backlog\n\nDeferred items from plan execution, code review, or ad-hoc "
          "capture. Entries are removed when implemented; git history is the audit trail.\n\n---\n")


def git_stage_evidence(repo_path):
    """(date, stage_number) pairs from the repo's git log.

    A plan's stage counts as executed when a commit dated on or after the plan's date
    names that stage number. Best-effort: commit messages do not name the plan.
    """
    repo = Path(repo_path)
    if subprocess.run(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                      capture_output=True, text=True).returncode != 0:
        return []
    out = subprocess.run(["git", "-C", str(repo), "log", "--format=%ad|%s", "--date=short"],
                         capture_output=True, text=True).stdout
    pairs = []
    for ln in out.splitlines():
        if "|" not in ln:
            continue
        date, msg = ln.split("|", 1)
        for m in re.finditer(r"[Ss]tage\s+(\d+)", msg):
            pairs.append((date, int(m.group(1))))
    return pairs


def existing_sources(backlog_text):
    return set(re.findall(r"^\s*-\s*\*\*Source:\*\*\s*(.+?)\s*$", backlog_text, re.M))


def max_bl(backlog_text):
    ids = [int(m) for m in re.findall(r"^##\s+BL-(\d+)\b", backlog_text, re.M)]
    return max(ids) if ids else 0


def render_entry(bid, c):
    # The plan's filename stamp rides along as a tag, so an entry stays greppable back to
    # the plan that produced it. An unstamped filename gives no tag: a fake date in a tag
    # is worse than none.
    stamp = c.get("plan_date")
    tags = "auto-unified" + (f", {stamp}" if stamp and stamp != "0000-00-00" else "")
    return (f"## BL-{bid:03d} — {c['title'][:80]}\n\n"
            f"- **Opened:** {TODAY}\n"
            f"- **Source:** {c['source']}\n"
            f"- **Reason:** Auto-unified from plan ({c['signal']}).\n"
            f"- **Next step:** TBD — opened by unify on {TODAY}; review and refine.\n"
            f"- **Tags:** {tags}\n\n---\n")


def unify(home, write, repo_path, include_stale=False):
    """(new, duplicates, candidates) for one records home."""
    plans_dir = home / "plans"
    if not plans_dir.is_dir():
        return (0, 0, 0)
    gpairs = git_stage_evidence(repo_path)
    cands = []
    for pf in sorted(plans_dir.rglob("*.md")):
        if pf.name.endswith("-done.md") or pf.name == "backlog.md":
            continue
        rel = "plans/" + pf.relative_to(plans_dir).as_posix()
        pdate = pp.plan_date(pf.name)
        done_stages = {sn for (cdate, sn) in gpairs if cdate >= pdate}
        text = pf.read_text(errors="ignore")
        normal = pp.parse_plan(text, rel, done_stages)
        for c in normal:
            c["plan_date"] = pdate
        cands.extend(normal)
        if not include_stale:
            continue
        age = pp.stale_age_days(pf.name)
        if age is None or age <= pp.STALE_DAYS:
            continue
        # An old plan is re-parsed with the git-stage suppression lifted, keeping only
        # what the normal pass did not already emit. Keyed on (source, title): a legacy
        # locator names the stage, not the task, so two tasks can share a source, and
        # dropping one would hide real forgotten work.
        seen = {(c["source"], c["title"]) for c in normal}
        for c in pp.parse_plan(text, rel, set()):
            if (c["source"], c["title"]) not in seen:
                cands.append(dict(c, signal="stale-plan-unchecked", plan_date=pdate))
    backlog = home / "backlog.md"
    btext = backlog.read_text() if backlog.exists() else HEADER
    have = existing_sources(btext)
    new = [c for c in cands if c["source"] not in have]
    dups = len(cands) - len(new)
    # An append to a hand-curated register, never a regenerate-in-place: `btext` is the
    # file's bytes carried through untouched, and `new` holds only candidates whose
    # Source is absent from them, so a fully registered set never opens the file.
    if write and new:
        nid = max_bl(btext)
        if not btext.endswith("\n"):
            btext += "\n"
        add = ""
        for c in new:
            nid += 1
            add += render_entry(nid, c)
        backlog.write_text(btext + add)
    return (len(new), dups, len(cands))


def main(argv=None):
    try:
        _load("staleness_probe", "staleness.py").warn_if_stale(__file__)
    except Exception:
        pass        # a probe that cannot load must never stop the command it advises on
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--project", help="the repo (default: the git top level)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--include-stale", action="store_true",
                    help="also surface unresolved items in plans older than the stale "
                         "threshold by filename stamp (off by default)")
    args = ap.parse_args(argv)
    project = args.project or subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    if not project:
        print("backlog-unify: not in a git repo; pass --project", file=sys.stderr)
        return 2
    project = str(Path(project).resolve())
    code, home, msg = _load("staged_planning_records_home", "records_home.py").resolve(
        project, for_write=args.write)
    if code == 2:
        print(f"backlog-unify: {msg}", file=sys.stderr)
        return 2
    if code == 3:
        print("backlog-unify: records go to the repo's docs/", file=sys.stderr)
    n, d, c = unify(Path(home), args.write, project, args.include_stale)
    print(f"{'WRITE' if args.write else 'DRY-RUN'}: {n} new entries, {d} duplicates "
          f"skipped, {c} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
