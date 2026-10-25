#!/usr/bin/env bash
# git-ref-gate.sh — git `reference-transaction` hook: a `Stage N green` commit needs proof
# records for every task of stage N. The Cursor fork of the plugin's git-ref-gate.sh.
#
# WHAT DIFFERS ON CURSOR, AND WHY. Proof is checked once per stage, at its gate, and it
# is on by default while a plan is in flight:
#   * Once per stage. Task commits carry code only. The `Stage N green` commit carries the
#     proof records for every claim of every task of stage N, proven after the gate's
#     fixes, so the records prove the code that ships and a review fix does not leave
#     earlier records stale.
#   * Every claim. A task proves each claim of its Test, not only its first claim and the
#     ones that name their break.
#   * On by default. The shim that runs this hook is installed per repo by
#     `python3 <planning>/scripts/hooks-install.py --install --repo R`; while a plan is in
#     flight, Cursor's commit gate (hooks/commit-gate.sh, on beforeShellExecution) denies
#     every git command in a repo without the shim, naming that command, and denies any
#     command that would point git at another hooks directory.
#
# WHY A REF HOOK. A gate that reads the index before the shell command runs misses
# `git commit -a`, and one that parses shell commands is beaten by a quoted `;` before
# `--no-verify`. Git runs `reference-transaction` whenever a ref moves, and a non-zero
# exit in the `prepared` phase aborts the update. Measured on git 2.43: it refuses
# `commit --no-verify`, `commit -n --amend`, `commit-tree` + `update-ref`,
# `merge --no-verify`, cherry-pick and a detached HEAD; only a `core.hooksPath` override
# bypasses it, and that is what the commit gate denies. So this hook parses no commands:
# it reads the finished COMMIT.
#
# WHAT IT DOES. In the `prepared` phase, for each commit that an update of HEAD or
# refs/heads/* adds (reachable from the new tip and from no local branch or
# remote-tracking ref yet — a teammate's fetched commit is history to read, not work
# being committed here), when the commit's SUBJECT is `Stage N green` for the plan in
# flight (.claude/plan-progress.json, read by plan_continue_classify.read_state), it
# reads that commit's own proof records for every task of stage N (from disk when the
# repo gitignores proof/) and validates each against that commit's tree fingerprint, the
# record's path and the plan's current wording. Every claim needs a record. A claim
# deviation is a valid record, named on stderr — never proof: a requirement "covered by"
# it is refused. A requirement with no record is advisory: named on stderr, never
# refused. A file under proof/ that is not a record is refused. A stage with Outcomes is
# also judged on its premise worksheet and demo report, as on every host.
#
# WHAT IT DOES NOT GATE. A commit whose subject is not `Stage N green` (task commits carry
# code only); a commit already reachable from a remote-tracking ref, so one written there
# by hand (`update-ref refs/remotes/…`) is exempt. The gate holds an agent to the plan's
# own commit convention; it is a rail, not a sandbox.
#
# WITH NO PLAN IN FLIGHT (no execution state, an untrusted one, no plan named, or the
# named plan gone) a commit whose subject starts `Stage N green` is refused, because a stage closed with no
# state could never be checked; the message names `plan-state.py init`. Every other
# commit is allowed.
# A snapshot the gate cannot read or that names another branch (`state_error`, which a
# detached HEAD gives in a worktree whose run started on a branch) and a finished run
# are not "no plan": the gate allows them, so a new plan started after a finished one
# is ungated until `plan-state.py init` records it.
#
# IT FAILS OPEN on its own errors (no python3, unreadable state, git or import
# failures, any uncaught exception) and says why on stderr. A record it cannot read is a
# problem with the record, not an error of the hook: it refuses. There is deliberately NO
# environment escape — the committing command's environment is the agent's. Rebasing or
# cherry-picking a stage-green commit onto a new tree is refused until it is re-proven:
# its records were bound to the old tree.
set -uo pipefail
[[ "${1:-}" == "prepared" ]] || exit 0
command -v python3 >/dev/null 2>&1 || {
    echo "commit gate: python3 not found — not checked; allowing" >&2; exit 0; }
HOOK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" 2>/dev/null && pwd)"
# -I (isolated): `python3 -` otherwise puts the cwd — the worktree git runs the hook in —
# first on sys.path, so a repo file named like a stdlib module would replace it.
# The updates reach the checker on fd 3 (git's stdin, passed through), not in the
# environment: one environment string is capped at 128 KiB, and a large transaction would
# fail the exec instead of being checked.
COMMIT_GATE_SCRIPTS="${HOOK_DIR:-}/../skills/executing-plans/scripts" \
COMMIT_GATE_HOOKS="${HOOK_DIR:-}" \
python3 -I - 3<&0 <<'PY'
import importlib.util, json, os, stat, subprocess, sys
from pathlib import Path

ZERO = "0" * 40


def allow(note=None):
    if note:
        sys.stderr.write(f"commit gate: {note}\n")
    sys.exit(0)


def _fail_open(kind, exc, _tb):
    # An uncaught exception would exit 1, which git reads as a refusal.
    sys.stderr.write(f"commit gate: internal error ({kind.__name__}: {exc}); allowing\n")
    sys.stderr.flush()
    os._exit(0)


sys.excepthook = _fail_open


def refuse(text):
    sys.stderr.write(text.rstrip() + "\n")
    sys.exit(1)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace",
                          timeout=20)


try:
    top = git("rev-parse", "--show-toplevel")
except Exception as e:
    allow(f"cannot run git ({e}); allowing")
if top.returncode != 0:
    allow()  # a bare repo, or not a work tree: no plan can be in flight here
repo = Path(top.stdout.strip())

# ---- the commits this transaction adds to a branch or HEAD, read once, when needed
_ADDED = None


def added_commits():
    global _ADDED
    if _ADDED is not None:
        return _ADDED
    tips = set()
    with os.fdopen(3, encoding="utf-8", errors="replace") as _fh:
        _updates = _fh.read()
    for line in _updates.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        _old, new, ref = parts
        if new == ZERO or not (ref == "HEAD" or ref.startswith("refs/heads/")):
            continue
        if git("cat-file", "-t", new).stdout.strip() == "commit":
            tips.add(new)
    if not tips:
        _ADDED = []
        return _ADDED
    added = []
    for tip in sorted(tips):
        r = git("rev-list", "--max-count=200", tip, "--not", "--branches", "--remotes")
        if len(r.stdout.split()) >= 200:
            sys.stderr.write("commit gate: over 200 commits added; only the newest 200 checked\n")
        for sha in r.stdout.split():
            if sha not in added:
                added.append(sha)
    _ADDED = added
    return added


scripts = Path(os.environ.get("COMMIT_GATE_SCRIPTS", ""))


def unstated(note=None):
    """No execution state names a plan here. A `Stage N green` commit closes a stage of
    the plan convention, and a stage closed with no state could never be checked: a
    session that skipped the state would pass ungated. So it is refused. Every other
    commit is not this gate's to judge without a plan. The pattern is the audit's own
    (plan-flip-audit.py STAGE_GREEN); if that cannot load, the gate fails open."""
    try:
        spec = importlib.util.spec_from_file_location("plan_flip_audit",
                                                      scripts / "plan-flip-audit.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
    except Exception as e:
        allow(f"cannot load plan-flip-audit.py ({e}); allowing")
    for sha in added_commits():
        subject = git("log", "-1", "--format=%s", sha).stdout.strip()
        if audit.STAGE_GREEN.match(subject):
            refuse(f"commit gate: refused — {sha[:7]} \"{subject}\" closes a stage, but no "
                   "execution state names a plan in flight in this repo"
                   f"{f' ({note})' if note else ''}. Record the run first — "
                   "`python3 <planning>/skills/executing-plans/scripts/plan-state.py init` "
                   "(executing-plans § Progress state file) — and commit again; if this "
                   "commit closes no plan's stage, reword its subject.")
    allow(note)


# ---- the plan in flight: read by the Stop hook's own reader, plan_continue_classify's
# read_state (one component at a time, no symlink below the repo root followed, a
# regular file we own). Any phase counts — wider than the Stop check's ACTIVE_PHASES
# on purpose: a plan handed off or blocked still owns its task numbers.
try:
    spec = importlib.util.spec_from_file_location(
        "plan_continue_classify",
        Path(os.environ.get("COMMIT_GATE_HOOKS", "")) / "plan_continue_classify.py")
    pcc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pcc)
except Exception as e:
    allow(f"cannot load plan_continue_classify.py ({e}); allowing")
state = pcc.read_state(repo)
if isinstance(state, dict) and state.get("state_status") == "state_error":
    allow("state_error; execution snapshot cannot establish a plan; allowing")
if pcc.finished(state, repo):
    allow()  # retained terminal evidence over a plan with no open task owns no new commits
if state is None:
    unstated()  # no plan in flight, or a state file we do not trust
plan = state.get("plan") if isinstance(state, dict) else None
if not isinstance(plan, str) or not plan:
    unstated("no plan named in plan-progress.json")
plan_path = Path(plan) if os.path.isabs(plan) else repo / plan
if not plan_path.is_file():
    unstated(f"plan {plan_path} not found")

added = added_commits()
if not added:
    allow()

# ---- the tools
try:
    spec = importlib.util.spec_from_file_location("prove_claim", scripts / "prove-claim.py")
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)
    pfa = pc.PFA
    plan_text = plan_path.read_text(errors="replace")
    blocks = {b["id"]: b for b in pfa.task_blocks(plan_text)}
except Exception as e:
    allow(f"cannot load prove-claim.py or read the plan ({e}); allowing")
stem = plan_path.stem


# A repo that gitignores proof/ keeps its records local: each is read from disk instead
# of from the commit's tree, and validate() still binds it to THIS commit's fingerprint,
# so a record written for an earlier tree proves nothing here (plan-flip-audit reads
# local records the same way).
local = git("-C", str(repo), "check-ignore", "-q", "--no-index",
            f"{pc.PROOF_DIR}/{stem}/x").returncode == 0


class Unreadable(Exception):
    """Evidence that is present but cannot be read. It refuses the commit: let through to
    the fail-open excepthook, an unreadable record or report would ALLOW it."""


def read_evidence(sha, rel):
    """A proof file's text from the commit's own tree (or, with proof/ local, from disk):
    None when absent; raises Unreadable when present but unreadable."""
    try:
        if local:
            path = repo / rel
            if path.is_symlink() or not path.is_file():
                return None
            return path.read_text(errors="replace")
        r = git("show", f"{sha}:{rel}")
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError) as e:
        raise Unreadable(e.__class__.__name__) from None


def record(sha, rel):
    """A record from the commit's own tree (or, with proof/ local, from disk): None when
    absent, a dict — or the value it holds, which validate() then rejects — when present."""
    try:
        text = read_evidence(sha, rel)
    except Unreadable as e:
        return {"_unreadable": str(e)}
    if text is None:
        return None
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        # RecursionError: deep nesting. Uncaught, the fail-open excepthook would
        # read a hostile record as the hook's own error and allow the commit.
        return {"_unreadable": "not JSON"}


def first_copy(sha, rel):
    """The report as the commit that first added it holds it, in `sha`'s history — the
    baseline a later edit cannot move. None when proof/ is local (it has no history) or
    the history cannot say."""
    if local:
        return None
    try:
        r = git("log", "--diff-filter=A", "--format=%H", sha, "--", rel)
        first = r.stdout.split()[-1] if r.returncode == 0 and r.stdout.split() else None
        if first is None:
            return None
        r = git("show", f"{first}:{rel}")
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError) as e:
        raise Unreadable(e.__class__.__name__) from None


def problems_of(rec, fp, expect):
    try:
        return pc.validate(rec, fp, expect)
    except Exception as e:  # noqa: BLE001 — a record that crashes the validator is not valid
        return [f"malformed record ({e.__class__.__name__})"]


def why_of(rec):
    return str(rec.get("why", "") if isinstance(rec, dict) else "")[:200]


missing, deviations, advisory = [], [], []
for sha in added:
    subject = git("log", "-1", "--format=%s", sha).stdout.strip()
    green = pfa.STAGE_GREEN.match(subject)
    if not green:
        continue
    # Every task of stage N, by its id's stage number.
    tasks = sorted((t for t in blocks if t.split(".")[0] == str(int(green.group(1)))),
                   key=lambda t: [int(x) if x.isdigit() else x for x in t.split(".")])
    short = sha[:10]
    try:
        fp = pc.commit_fingerprint(repo, sha)
    except Exception as e:
        allow(f"cannot fingerprint {short} ({e}); allowing")
    # proof/ is outside every fingerprint: anything but a record there rides along unbound.
    ls = git("ls-tree", "-r", "-z", "--name-only", sha, "--", pc.PROOF_DIR).stdout
    for p in ls.split("\0"):
        if p and not pc.RECORD_PATH.match(p):
            missing.append(f"{short}: {p}: not a proof record — proof/ may hold records only")
    # A stage with Outcomes is judged on two reports: the premise worksheet (Step 3.0)
    # and the demo evaluator's report, whose sections must quote every Outcome word for
    # word, hold, and carry evidence. The word-for-word quote is what stops a report
    # from paraphrasing an Outcome away. The hook cannot tell who wrote a report, and a
    # report is not bound to the tree the way a proof record is.
    if green:
        n = green.group(1)[:12]
        # Every failure in here refuses: it is evidence that could not be judged, and
        # the excepthook would read it as the hook's own error and allow the commit.
        try:
            n = str(int(green.group(1)))
            base = f"{pc.PROOF_DIR}/{stem}/stage-{n}"
            outcomes = pfa.stage_outcomes(plan_text, n)
            texts = {}
            for kind in ("premise", "demo"):
                try:
                    texts[kind] = read_evidence(sha, f"{base}/{kind}.md")
                except Unreadable as e:
                    texts[kind] = Unreadable(str(e))
            prem = texts["premise"] if isinstance(texts["premise"], str) else None
            # The worksheet as first committed: deleting it, or its Outcomes, in a later
            # commit does not take the stage out of judgment.
            first = first_copy(sha, f"{base}/premise.md")
            # A worksheet that recorded Outcomes keeps the stage judged even when the
            # plan no longer lists any: the drift check below is what catches the drop.
            recorded = pfa.premise_outcomes(prem) + pfa.premise_outcomes(first)
            stray = pfa.outcomes_stray(plan_text, n)
            if stray:
                missing.append(f"{short} Stage {n} outcomes: a line under **Outcomes:** is not a "
                               f"bullet ({stray[:60]!r}) — indent a wrapped line, or make it a bullet")
            elif pfa.has_outcomes_field(plan_text, n) and not outcomes:
                missing.append(f"{short} Stage {n} outcomes: the **Outcomes:** field has no "
                               "bullet the gate can read — write one `- ` line per Outcome")
            elif outcomes or recorded:
                # The demo is the gate evaluator, so it follows the tier: none at a plan
                # declaring `review-scope: none`, and an owner's evidenced opt-out stands in.
                kinds = [("premise", pfa.premise_problems)]
                demo_text = texts["demo"]
                if pfa.declared_tier(plan_text) != "none" and not (
                        isinstance(demo_text, str) and pfa.demo_opted_out(demo_text)):
                    kinds.append(("demo", lambda r: pfa.demo_problems(r, outcomes)))
                for kind, check in kinds:
                    text = texts[kind]
                    if isinstance(text, Unreadable):
                        missing.append(f"{short} Stage {n} {kind}: unreadable ({text})")
                        continue
                    if text is None:
                        missing.append(f"{short} Stage {n} {kind}: no {base}/{kind}.md — "
                                       f"python3 <scripts>/stage-brief.py {kind} --stage {n}")
                        continue
                    missing.extend(f"{short} Stage {n} {kind}: {p}" for p in check(text))
                # The worksheet holds the Outcomes as they stood at Step 3.0, as it was
                # first committed; changing them since is the owner's call.
                for text in dict.fromkeys(t for t in (first, prem) if t):
                    missing.extend(f"{short} Stage {n} outcomes: {p}"
                                   for p in pfa.outcome_drift_problems(text, plan_text, n))
        except Exception as e:  # noqa: BLE001 — evidence that crashes the check is not valid
            missing.append(f"{short} Stage {n} reports: unreadable ({e.__class__.__name__})")
    for t in tasks:
        b = blocks[t]
        proven = {}  # claim k -> True only for a valid kind "claim" record
        for k, c in enumerate(pfa.claim_clauses(b["test"]), 1):
            rec = record(sha, f"{pc.PROOF_DIR}/{stem}/{t}/claim-{k}.json")
            if rec is None:
                missing.append(f"{short} Task {t} claim {k}: no record")
                continue
            probs = problems_of(rec, fp, ("claim", t, k, c))
            if probs:
                missing.append(f"{short} Task {t} claim {k}: {probs[0]}")
            elif rec.get("kind") == "claim-deviation":
                deviations.append(f"Task {t} claim {k}: {why_of(rec)}")
            else:
                proven[k] = True
        for k, c in enumerate(pfa.requirement_clauses(b["desc"]), 1):
            recs = {kind: record(sha, f"{pc.PROOF_DIR}/{stem}/{t}/{kind}-{k}.json")
                    for kind in ("req", "deviation")}
            probs = {kind: problems_of(r, fp, (kind, t, k, c))
                     for kind, r in recs.items() if r is not None}
            req_rec = recs.get("req")
            cites = req_rec.get("covered_by_claim") if isinstance(req_rec, dict) else None
            if probs.get("req") == [] and cites is not None and not proven.get(cites):
                # A req "covered by claim J" is only as good as claim J's PROOF; a
                # claim deviation discloses, it proves nothing.
                probs["req"] = [f"cites claim {cites}, which is missing or not a valid proof"]
            if not probs:
                advisory.append(f"Task {t} requirement {k}: no req or deviation record")
            elif probs.get("req") == []:
                continue
            elif probs.get("deviation") == []:
                deviations.append(f"Task {t} requirement {k}: {why_of(recs['deviation'])}")
            else:
                missing.append(f"{short} Task {t} requirement {k}: {next(iter(probs.values()))[0]}")

if not missing:
    if deviations:
        sys.stderr.write("commit gate: recorded as deviations — name each in the gate "
                         "report:\n" + "".join(f"  - {d}\n" for d in deviations))
    if advisory:
        sys.stderr.write("commit gate: advisory — requirements with no record (finding 9, "
                         "not blocking):\n" + "".join(f"  - {a}\n" for a in advisory))
    allow()

shown = "\n".join(f"  - {m}" for m in missing[:20])
more = f"\n  (+{len(missing) - 20} more)" if len(missing) > 20 else ""
refuse(
    f"commit gate: refused — {len(missing)} proof record(s) missing or stale in the commit(s) "
    f"being added:\n{shown}{more}\n\n"
    "A `Stage N green` commit must carry a record for every claim of every task of stage N. "
    "Stage the stage's final code, run prove-claim.py claim for each (a claim no repo patch "
    "can break: prove-claim.py deviation --claim K --why …), `git add proof/`, then commit "
    "again. A record proven before the last code change is stale: re-prove after staging "
    "the final code. A stage-green commit rebased or cherry-picked onto another tree needs "
    "re-proving too."
)
PY
