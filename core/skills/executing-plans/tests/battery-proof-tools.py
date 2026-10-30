#!/usr/bin/env python3
"""Mutation battery for the proof tools: plan-flip-audit.py and prove-claim.py,
and the opt-in commit gate: hooks/git-ref-gate.sh, hooks/proof-guard.sh and
proof-hooks-install.py.

    python3 core/skills/executing-plans/tests/battery-proof-tools.py [-j N] [--anchors-only]

Run it at a stage gate after ANY change to one of them — never inside a task.
Deliberately not named `test-*`, so `scripts/run-tests.sh` does not discover it.

EXIT CODES. A caller that branches on $? needs these to mean different things,
because the required response to each differs:

    0   every guard independently pinned — nothing survived, nothing skipped
    1   a mutation SURVIVED: that guard is not reachable from any named test
    2   the control suites were already red before mutating, or an entry is
        malformed (not 5 fields, or an empty killer); nothing was run
    4   a mutation was SKIPPED because its anchor text is gone. Coverage
        silently shrank; the guard it pinned is now unpinned. Re-anchor it.
    5   a trial ERRORED: it could not run, timed out, the mutation left the
        script unparseable, or the suite went red without reporting a failing
        check. None of those is a kill — a red that measured nothing is the
        failure this battery exists to catch. Fix the entry or the environment.

    6   a mutation was MISNAMED: a check other than the one its entry names
        killed it. The guard is pinned, but not by the check the entry says —
        the name is wrong, or the named check stopped covering it. Fix the
        name after reading which check it was. (Precedence: 1, then 5, then 6.)
        A MISNAMED trial is re-run once, alone; one its named check kills on the
        re-run is UNSTABLE — printed, with the stray failure's detail, and
        counted apart: it changes no exit code.

--anchors-only checks the anchors (exit 0 or 4) and runs nothing — cheap enough
for CI, which runs the suites but not the battery.

WHY IT EXISTS. Both tools are fraud detectors, so their failure mode is silence
— a weakened guard changes no output anyone looks at, and the suite stays green.
A suite can pass with a whole clause deleted, with the severity of several
findings unpinned, or with two guards masking each other.

A green suite is not evidence in any of those cases. This is.

Each entry weakens ONE guard. A guard is PINNED if the suite goes red; a
SURVIVOR means the suite would stay green with that protection deleted.

EACH MUTATION RUNS IN ITS OWN COPY of the plugin's executing-plans skill and
hooks directory (the layout the scripts find each other by), never in the
repo. Mutating the tracked scripts in place forces the runs to go serially, and
a killed run leaves a weakened fraud detector in the working tree. A copy per
mutation makes the runs independent: they go out in parallel (-j, default every
CPU) and an interrupted battery leaves nothing behind but temporary directories.

EACH SUITE RUNS FAIL-FAST (SUITE_FAIL_FAST=1): a kill needs only the first failing
check, and that first check must be the one the entry names.

COST, measured so a change to it is visible (16 CPUs, -j 16). Every suite run to its
end: 173 mutations, 6m33s wall, 43m16s user. Fail-fast with named killers: 176
mutations, 4m06s wall, 24m27s user — 176 killed, 0 misnamed.
"""
import argparse
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PLUGIN = next(p for p in Path(__file__).resolve().parents if p.name == "skills").parent   # the plugin root: the dir holding skills/
EP = "skills/executing-plans"
PY_S, PY_T = f"{EP}/scripts/plan-flip-audit.py", f"{EP}/tests/test-plan-flip-audit.py"
PC_S, PC_T = f"{EP}/scripts/prove-claim.py", f"{EP}/tests/test-prove-claim.py"
PI_S = f"{EP}/scripts/proof-hooks-install.py"
GR_S, GR_T = "hooks/git-ref-gate.sh", "hooks/tests/test-git-ref-gate.sh"
PG_S, PG_T = "hooks/proof-guard.sh", "hooks/tests/test-proof-guard.sh"
PCC_S = "hooks/plan_continue_classify.py"   # the lock rule both commit gates share
SUITES = [PY_T, PC_T, GR_T, PG_T]

M = [
 # (label, target, old, new, killer) — `killer` is a substring of the `  FAIL` label of the
 # check meant to kill the mutation; ` | ` separates alternatives, for a guard two checks cover
 # whose first failure varies with machine load (measured: three entries under -j 16). Each killer is the mutation's first
 # FAIL under SUITE_FAIL_FAST=1, cut before run-specific tails such as `(rc=0)`; a different
 # check killing it later is reported MISNAMED, so the name is reviewed, not silently moved.
 ('strong tier voids alone -> demoted to advisory', PY_S,
  'return m.group(0), "blocking"',
  'return m.group(0), "advisory"',
  'expected exit 1'),
 ('checkbox line -> the next indented line is read as part of the box', PY_S,
  'LAZY_STOP = re.compile(r"^(?:\\s|$|',
  'LAZY_STOP = re.compile(r"^(?:$|',
  'a quote on the line after a ticked box voided it'),
 ('lazy continuation dropped -> an unindented line run into the box goes unscanned', PY_S,
  'return "".join(" " + ln for ln in tail)',
  'return ""',
  'an unindented continuation of a ticked box went unscanned'),
 ('two-signal rule -> one signal is enough', PY_S,
  'if len({h.lower() for h in hits}) >= 2:',
  'if len({h.lower() for h in hits}) >= 1:',
  "'amended' fired from prose — the main false-positive source is back"),
 ('two-signal rule -> three signals required', PY_S,
  'if len({h.lower() for h in hits}) >= 2:',
  'if len({h.lower() for h in hits}) >= 3:',
  'the >=2 threshold is unpinned — it is masked by the parenthetical rule'),
 ('distinct-word rule -> the same word twice counts', PY_S,
  'if len({h.lower() for h in hits}) >= 2:',
  'if len(hits) >= 2:',
  'M3 SURVIVES: duplicate words counted as independent signals'),
 ('lone undisclosed amendment -> silent again', PY_S,
  'return hits[0] + " (undisclosed amendment)", "advisory"',
  'pass',
  "--vocab-file extension wrong: lines [5, 6] sev {5: 'blocking', 6: 'blocking'}"),
 ('DISCLOSED escape -> a was-value no longer exempts', PY_S,
  'and not DISCLOSED.search(tail.group(0))',
  'and True',
  'the amendment protocol itself fires — the main false-positive source'),
 ('exit 2|78 promoted to strong -> back to weak', PY_S,
  'r"\\bexit\\s+(code\\s+)?(2|78)\\b",',
  'r"\\bZZNOMATCHZZ\\b",',
  "'amended, exit 2 on rerun' should be blocking — a strong term voids the tick outright"),
 ('finding 4 severity inheritance -> always advisory', PY_S,
  'sev = "blocking" if any(d.get("severity") == "blocking" for d in dirty) else "advisory"',
  'sev = "advisory"',
  'M7 SURVIVES: **Completed:** over a blocking gate line is not blocking'),
 ('finding 4 severity inheritance -> always blocking', PY_S,
  'sev = "blocking" if any(d.get("severity") == "blocking" for d in dirty) else "advisory"',
  'sev = "blocking"',
  "M8 SURVIVES: finding 4 ignores its evidence's severity"),
 ('finding 1 severity -> advisory', PY_S,
  '"finding": 1, "severity": "blocking",',
  '"finding": 1, "severity": "advisory",',
  'expected exit 1'),
 ('finding 3 severity -> advisory', PY_S,
  '"finding": 3, "severity": "blocking",',
  '"finding": 3, "severity": "advisory",',
  'M10 SURVIVES: finding 3 severity unpinned'),
 ('finding 5 severity -> advisory', PY_S,
  '"finding": 5, "severity": "blocking",',
  '"finding": 5, "severity": "advisory",',
  'M11 SURVIVES: finding 5 severity unpinned'),
 ('exit 4 for advisory-only -> collapses back into 1', PY_S,
  '        return 4',
  '        return 1',
  'advisory-only exited 1, expected 4'),
 ('blocking exit 1 -> collapses into 4', PY_S,
  '    if any(f.get("severity") == "blocking" for f in findings):\n        return 1',
  '    if False:\n        return 1',
  'expected exit 1'),
 ('NEGATED filter deleted', PY_S,
  'if NEGATED.search(pre) or NEGATED_HYPHEN.search(pre):',
  'if False:',
  'M14 SURVIVES: the NEGATED guard is unreachable from its fixture'),
 ('COUNTED filter deleted', PY_S,
  'return not COUNTED.search(pre)',
  'return True',
  'M15 SURVIVES: the COUNTED guard is unreachable from its fixture'),
 ('QUOTED_SPAN masking deleted', PY_S,
  'masked = QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), raw)',
  'masked = raw',
  'REGRESSION: 1 false positive(s) on honest prose'),
 ('--vocab-replace guard deleted', PY_S,
  'if args.vocab_replace and not args.vocab_file:',
  'if False:',
  '--vocab-replace alone exited 0, expected 2'),
 ('finding 6 severity -> advisory', PY_S,
  '"finding": 6, "severity": "blocking",',
  '"finding": 6, "severity": "advisory",',
  'unquoted owner decision must be a blocking finding 6'),
 ('finding 6 ATTESTED escape deleted (a quote no longer clears it)', PY_S,
  'if not m or ATTESTED.search(raw):',
  'if not m:',
  'a quoted owner attestation must clear finding 6'),
 ('finding 6 start-of-box anchor dropped (prose fires again)', PY_S,
  'r"^(?:\\*\\*\\(judgment\\)\\*\\*\\s*|\\(judgment\\)\\s*|the\\s+)?"',
  'r"(?:\\*\\*\\(judgment\\)\\*\\*\\s*|\\(judgment\\)\\s*|the\\s+)?"',
  'finding 6 must anchor to the start of the box'),
 ('finding 6 vocabulary widened to action verbs', PY_S,
  '|sign(?:s|ed)?[\\s-]+off|authori[sz](?:es|ed|ation))\\b",',
  '|sign(?:s|ed)?[\\s-]+off|authori[sz](?:es|ed|ation)|runs|creates)\\b",',
  'owner ACTIONS must not need a quote'),
 ('finding 6 ticked-only guard deleted', PY_S,
  '        if not ticked:\n            continue\n        # A decision phrase inside backticks',
  '        # A decision phrase inside backticks',
  'an unticked box must not be finding 6'),
 ('finding 7 severity -> blocking', PY_S,
  '"finding": 7, "severity": "advisory",',
  '"finding": 7, "severity": "blocking",',
  'finding 7 must be advisory with exit 4'),
 ('finding 7 historical/amended exemption deleted', PY_S,
  'if v in line and not STALE_EXEMPT.search(line):',
  'if v in line and "was:" not in line:',
  'a historical mention must clear finding 7'),
 ('finding 7 identifier filter deleted (words get swept)', PY_S,
  'if len(v) >= 6 and DISTINCTIVE.search(v):',
  'if len(v) >= 6:',
  'only identifier-like was-values may be swept'),
 ('baseline: second --snapshot no longer refused', PY_S,
  '    if bp.exists():',
  '    if False:',
  'second --snapshot must exit 2'),
 ('baseline: hash check deleted (edited baseline trusted)', PY_S,
  'if hashlib.sha256(text.encode()).hexdigest() != recorded:',
  'if False:',
  'tampered baseline must exit 2'),
 ('baseline: plan-identity check deleted', PY_S,
  'if doc.get("plan") != str(path.resolve()):',
  'if False:',
  'foreign baseline must exit 2'),
 ('baseline: compares the plan with itself (no flips ever)', PY_S,
  'flips = tick_delta(base["text"], text)',
  'flips = tick_delta(text, text)',
  'expected findings 1, 3, 5 and exit 1; got [8]'),
 # The rule is emitted at two sites (the plan-wide count and the per-commit scan); the
 # shared condition is the anchor, so both are mutated.
 ('baseline: bulk-flip rule deleted', PY_S,
  'if len(counted) > threshold and task_commits < threshold:',
  'if False:',
  'expected findings 1, 3, 5 and exit 1; got [3, 5, 8]'),
 ('baseline: probe rule deleted', PY_S,
  '    if not probed:',
  '    if False:',
  'finding 3 NOT flagged'),
 ('baseline: probe evidence never recognised', PY_S,
  '            probed = True',
  '            probed = False',
  'honest run must be clean'),
 ('baseline: review rule deleted', PY_S,
  '    if not reviewed:',
  '    if False:',
  'expected findings 1, 3, 5 and exit 1; got [1, 3, 8]'),
 ('baseline: not wired for a plan outside any repo', PY_S,
  'not_run = from_baseline(f"{path.parent}: {err}")',
  'not_run = skip(f"{path.parent}: {err}")',
  'checks_not_run was [1, 3, 5, 8, 9, 10], expected [1, 3, 5, 8, 9, 10, 11]'),
 ('GATE_HEAD -> "gate" anywhere on a Stage heading', PY_S,
  r'(\d+)(?:[-\s][A-Za-z]+)?\s*[:.\-—–]?\s*Gate\b", re.I)',
  r'(\d+)\b[^\n]*\bGate\b", re.I)',
  "a stage title containing 'gate' was read as a gate block"),
 ('structure: fenced blocks counted', PY_S,
  '            fence = not fence\n',
  '            fence = False\n',
  'a fenced example was counted as structure'),
 ('baseline: a non-object snapshot exits 2 again', PY_S,
  '    if not isinstance(doc, dict):\n        raise Unreadable(',
  '    if False:\n        raise Unreadable(',
  'a non-object snapshot must read as unreadable'),
 ('baseline: structural check not wired (a deleted task goes unreported)', PY_S,
  '        findings.extend(structure_findings(path, text, base))\n',
  '',
  'a deleted task must be one advisory STRUCTURE-SHRANK finding naming Task 2.3'),
 ('finding 11 severity -> blocking', PY_S,
  '"finding": 11, "severity": "advisory",',
  '"finding": 11, "severity": "blocking",',
  'a deleted task must be one advisory STRUCTURE-SHRANK finding naming Task 2.3'),
 ('baseline: an unparseable baseline exits 2 again (every other check lost)', PY_S,
  'raise Unreadable(f"baseline {bp} is unreadable: {e}")',
  'die(f"baseline {bp} is unreadable: {e}")',
  'an unreadable snapshot must skip only 1/3/5/11 and say so once'),
 ('finding 8 unproven claims -> advisory', PY_S,
  '            out.append({**base, "severity": "blocking",\n                        "rule": f"Task {tid}: {len(unproven)} of {n} required claim(s)',
  '            out.append({**base, "severity": "advisory",\n                        "rule": f"Task {tid}: {len(unproven)} of {n} required claim(s)',
  'a stale local record must be blocking (red if disk records are trusted unbound)'),
 ('finding 8 records ignored', PY_S,
  'unproven = [k for k in required if got.get(("claim", k), ["no record"])]',
  'unproven = list(required)',
  'valid committed records must satisfy 8 and 9 (red if records are not read)'),
 ('finding 8 legacy branch deleted (lines alone go blocking)', PY_S,
  '        elif not got and muts:',
  '        elif False:',
  'honest run must be clean'),
 ('finding 8 no-commit branch deleted', PY_S,
  '        if commits == 0 and not got:',
  '        if False:',
  'no-commit must be one advisory, from finding 8'),
 ('finding 8 claim counting collapsed to one', PY_S,
  '    claims = claim_clauses(test)\n    return [k for k, c in enumerate(claims, 1)',
  '    claims = claim_clauses(test)[:1]\n    return [k for k, c in enumerate(claims, 1)',
  'a task earns credit only with all its claims proven (red when a single record is enough)'),
 ('finding 8 ticked-only filter dropped', PY_S,
  'return [(t["id"], t["line"], t["test"]) for t in out if t["line"]]',
  'return [(t["id"], t["line"] or 0, t["test"]) for t in out]',
  'a deleted task must be one advisory STRUCTURE-SHRANK finding naming Task 2.3'),
 ('finding 8 runs on an implicit repo', PY_S,
  '    if args.repo:',
  '    if True:',
  'a quote on the line after a ticked box voided it'),
 ('finding 9 unmet requirements -> blocking (the rule: advisory, never blocking)', PY_S,
  '            why = "; ".join(f"requirement {k}: {p}" for k, p in open_[:4])\n            out.append({**base, "severity": "advisory",',
  '            why = "; ".join(f"requirement {k}: {p}" for k, p in open_[:4])\n            out.append({**base, "severity": "blocking",',
  "a local schema-1 record must not claim an add date (red if it says 'added after the cutover')"),
 ('finding 9 deviations not reported', PY_S,
  '        elif devs:',
  '        elif False:',
  'a deviation must be advisory'),
 ('finding 9 legacy branch deleted', PY_S,
  '        if open_ and not got and reqs:',
  '        if False:',
  'self-reported lines with no record stay legacy advisories (red when a line passes as proof)'),
 ('finding 9 clause counting collapsed to one', PY_S,
  'return len(requirement_clauses(desc))',
  'return 1',
  'honest run must be clean'),
 ('finding 9 code spans no longer masked', PY_S,
  'return QUOTED_SPAN.sub(lambda m: " " * len(m.group(0)), text)',
  'return text',
  'code spans must not be stripped as notes'),
 ('finding 9 deviation: no longer counts', PY_S,
  'REQ_LINE = re.compile(r"^\\s*(req|deviation)\\s*:\\s*\\S", re.I | re.M)',
  'REQ_LINE = re.compile(r"^\\s*(req)\\s*:\\s*\\S", re.I | re.M)',
  'deviation lines must count as legacy evidence'),
 ('finding 9 duplicates finding 8 on a task with no commit', PY_S,
  '        if n == 0 or (commits == 0 and not got):',
  '        if n == 0:',
  'no-commit must be one advisory, from finding 8'),
 ('finding 9 not wired to --repo', PY_S,
  'f9 = scan_task_requirements(path, text, Path(top8.strip())) if has_head else None',
  'f9 = []',
  'no baseline must leave 1/3/5 not run, pointing at --snapshot'),
 ('prove: green under the break is recorded', PC_S,
  '    if red_rc == 0:\n        raise Refused("the test still PASSES',
  '    if False:\n        raise Refused("the test still PASSES',
  'a green-under-break run must be refused'),
 ('prove: baseline run no longer required to pass', PC_S,
  '    if base_rc != 0:',
  '    if False:',
  'a failing baseline must be refused'),
 ('prove: a break may touch a test file', PC_S,
  '        if TEST_PATH.search(p):\n            raise Refused',
  '        if False:\n            raise Refused',
  'breaking the test must be refused'),
 ('prove: a break that stops the build is accepted', PC_S,
  '                if b_rc != 0:\n                    raise Refused(f"the code does not build with',
  '                if False:\n                    raise Refused(f"the code does not build with',
  'a non-building break must be refused'),
 ('prove: no build step and no reason is accepted', PC_S,
  '    if not build and not no_build:',
  '    if False:',
  'missing build step must exit 2'),
 ('prove: restore not verified', PC_S,
  '        if bad:\n            raise RestoreFailed("could not restore',
  '        if False:\n            raise RestoreFailed("could not restore',
  'journal recovery must restore and stop'),
 ('prove: restored file no newer than the broken write (stale builds)', PC_S,
  '        t = max(time.time_ns(), broke + 10**9)',
  '        t = broke',
  'the restore must leave the source newer than the broken build, exits 0/1'),
 ('prove: test runs write .pyc again', PC_S,
  'env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}',
  'env = dict(os.environ)',
  'a real proof must be recorded | test runs must not write .pyc'),
 ('prove: unstaged change outside proof/ accepted', PC_S,
  '    if diff:\n        raise Refused',
  '    if False:\n        raise Refused',
  'a dirty tree must be refused'),
 ('prove: untracked file outside proof/ accepted', PC_S,
  '    if untracked:\n        raise Refused',
  '    if False:\n        raise Refused',
  'untracked files must be refused'),
 ('prove: claim/requirement number not range-checked', PC_S,
  '    if index < 1 or index > len(items):',
  '    if False:',
  'out-of-range claim must exit 2'),
 ("prove: --test not bound to the plan's Test field", PC_S,
  '    require_planned_test(test, block["test"], task)',
  '    pass',
  'a free-form --test must be refused'),
 ('prove: a trivial --build accepted', PC_S,
  '    if build is not None and build.strip() in TRIVIAL_BUILD:',
  '    if False:',
  'a trivial build must be refused'),
 ('prove: rename / new file / mode-change breaks accepted', PC_S,
  '        if line.startswith(("rename", "copy", "create", "delete", "mode change")):',
  '        if False:',
  'a rename must be refused'),
 ('prove: patch paths read C-quoted (no -z)', PC_S,
  '"apply", "--numstat", "-z",',
  '"apply", "--numstat",',
  'a real proof must be recorded'),
 ('prove: assume-unchanged / skip-worktree accepted', PC_S,
  '    if flags:\n        raise Refused',
  '    if False:\n        raise Refused',
  'index flags must be refused'),
 ('prove: non-record files allowed under proof/', PC_S,
  '    if stray:\n        raise Refused',
  '    if False:\n        raise Refused',
  'proof/ must hold records only'),
 ('prove: no cleanliness check after the run', PC_S,
  '        require_clean(repo, before)\n        after = index_fingerprint(repo)',
  '        after = index_fingerprint(repo)',
  'a changed tree after the proof must exit 3'),
 ("prove: interrupted run's journal not recovered", PC_S,
  '    recover_if_needed(repo)',
  '    pass',
  'journal recovery must restore and stop'),
 ('prove: the elapsed time is not recorded', PC_S,
  '"baseline": {"exit": base[0], "tail": base[1], "elapsed_s": base[2]},',
  '"baseline": {"exit": base[0], "tail": base[1]},',
  'a record must carry elapsed_s for both runs'),
 ('prove: the break run elapsed time is not recorded', PC_S,
  '"red": {"exit": red[0], "tail": red[1], "elapsed_s": red[2]}}',
  '"red": {"exit": red[0], "tail": red[1]}}',
  'a record must carry elapsed_s for both runs'),
 ('prove: a test over --timeout before the break is not a budget stop', PC_S,
  '    if base_rc is None:\n        raise OverBudget(',
  '    if False:\n        raise OverBudget(',
  'a test over --timeout must exit 4 with no record'),
 ('prove: timeout kills only the shell', PC_S,
  '        os.killpg(p.pid, signal.SIGKILL)',
  '        p.kill()',
  'timeout must kill the process group'),
 ('req: a trivial --check accepted', PC_S,
  '        if not check or check.strip() in TRIVIAL_BUILD:',
  '        if False:',
  'a trivial check must be refused'),
 ('req: covered-by-claim not validated', PC_S,
  '        if problems:\n            raise Refused(f"claim {covered_by}',
  '        if False:\n            raise Refused(f"claim {covered_by}',
  'dangling claim reference must be refused'),
 ('deviation: no reason required', PC_S,
  '    if not why or len(why.strip()) < 10:',
  '    if False:',
  'empty deviation reason must exit 2'),
 ('replay: only re-reads the JSON', PC_S,
  '        if not problems:\n            fd, tmp = tempfile.mkstemp',
  '        if False:\n            fd, tmp = tempfile.mkstemp',
  'replay must re-run, not re-read'),
 ('validate: fingerprint not compared', PC_S,
  '    elif fingerprint and fpr != fingerprint:',
  '    elif False:',
  'fingerprint mismatch must be rejected'),
 # ---- a record binds its touched files' blobs (touched_blobs)
 ('record: blob maps not written (the record binds the whole index only)', PC_S,
  '"touched": paths, **maps, "fingerprint": fp,',
  '"touched": paths, "fingerprint": fp,',
  'a record must carry touched_blobs {path: blob} for its touched files'),
 ('req covered by a claim: the claim\'s blobs not carried', PC_S,
  '                rec[key] = crec[key]',
  '                pass',
  "a covered req must carry its claim's touched_blobs"),
 # The first check a weakened comparison fails is the test file edited after the proof: the
 # suite judges it before the changed touched file.
 ('validate: touched blobs not compared to the tree judged', PC_S,
  '        moved = blob_drift(rec, blobs)\n        if moved:',
  '        moved = blob_drift(rec, blobs)\n        if False:',
  'a weakened test must stale the record (red if the test the record was watched under goes unbound)'),
 # Judged by blobs, a record that binds none is compared to nothing: the half-bound record
 # (no witness_blobs) is the first such record the suite judges.
 ('validate: a record without touched_blobs judged by blobs (accepted unbound)', PC_S,
  '    elif bound and blobs is not None:',
  '    elif blobs is not None:',
  'a record without witness_blobs must keep the fingerprint rule (red if its test goes unbound)'),
 ('validate: touched_blobs shape not checked', PC_S,
  '    if kind in ("claim", "req") and any(k in rec for k in BLOB_MAPS):\n        p.extend(touched_blobs_problems(rec))',
  '    if False:\n        p.extend(touched_blobs_problems(rec))',
  'a malformed touched_blobs must be rejected'),
 ('record: witness_blobs not written (the test the proof ran goes unbound)', PC_S,
  '"witness_blobs": {w: staged[w] for w in witness}} if witness else {})',
  '"witness_blobs": {}} if witness else {})',
  'a record must carry witness_blobs {path: blob} for the files its test runs'),
 ('validate: witness_blobs not compared to the tree judged', PC_S,
  'return sorted({str(p) for m in maps for p, b in m.items() if blobs.get(p) != b})',
  'return sorted({str(p) for m in maps[:1] for p, b in m.items() if blobs.get(p) != b})',
  'a weakened test must stale the record'),
 ('validate: a record without witness_blobs judged by blobs (its test unbound)', PC_S,
  '            and all(isinstance(rec.get(k), dict) for k in BLOB_MAPS)\n            and bool(rec["witness_blobs"]))',
  '            and isinstance(rec.get("touched_blobs"), dict)\n            and bool(rec.get("witness_blobs", {"_": ""})))',
  'a record without witness_blobs must keep the fingerprint rule'),
 ('validate: an empty witness_blobs judged by blobs (no test bound)', PC_S,
  '            and bool(rec["witness_blobs"]))',
  '            and True)',
  'an empty witness_blobs must not count as bound'),
 ('binds_by_blobs: a deviation carrying maps judged by them (the kind guard)', PC_S,
  '    return (isinstance(rec, dict) and rec.get("kind") in ("claim", "req")',
  '    return (isinstance(rec, dict)',
  'only a claim or req record binds by blobs'),
 ('touched_blobs: the exact-touched-set check dropped', PC_S,
  'set(tb) != {t for t in touched if isinstance(t, str)}',
  'False',
  'a malformed touched_blobs must be rejected'),
 ('OBJECT_ID: any word read as a blob id', PC_S,
  'OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")',
  'OBJECT_ID = re.compile(r"^\\S+$")',
  'a malformed touched_blobs must be rejected'),
 # ---- the witness binds every test file a runner is given, or no blob map at all
 ('witness: an empty or incomplete witness still binds by blobs', PC_S,
  '    return out if out and complete else None',
  '    return out',
  '`pytest` must bind None'),
 ('witness: a runner path naming nothing tracked leaves the witness complete', PC_S,
  '            elif not hit and runner and PATH_LIKE.search(w.split("::", 1)[0]):\n                complete = False',
  '            elif not hit and runner and PATH_LIKE.search(w.split("::", 1)[0]):\n                pass',
  '`pytest tests/test_a.py tests/test_gone.py` must bind None'),
 ('witness: a dotted -m module naming nothing tracked leaves it complete', PC_S,
  '                complete &= bool(hit)',
  '                pass',
  '`python3 -m unittest tests.test_a tests.test_gone` must bind None'),
 ('witness: a directory argument binds nothing under it', PC_S,
  '    return set(tracked) if n == "." else {t for t in tracked if t.startswith(n + "/")}',
  '    return set()',
  '`pytest tests/` must bind'),
 ("witness: a pytest node's `::name` kept on the path", PC_S,
  '            n = os.path.normpath(os.path.join(where, w.split("::", 1)[0]))',
  '            n = os.path.normpath(os.path.join(where, w))',
  '`pytest tests/test_a.py::test_add` must bind'),
 ('witness: the record writes blob maps for a command naming no test file', PC_S,
  '"witness_blobs": {w: staged[w] for w in witness}} if witness else {})',
  '"witness_blobs": {w: staged[w] for w in witness or []}})',
  'a command that resolves nothing must write neither blob map'),
 # ---- a renumbered req or deviation record is moved to its clause's number, never lost
 ('prove: a renumbered record at the number being proven is overwritten', PC_S,
  '    make_room(repo, plan, task, index, PFA.requirement_clauses(block["desc"]))\n    require_clean(repo)',
  '    require_clean(repo)',
  'a renumbered req record must be moved to its clause'),
 ('prove: a deviation deletes a renumbered req record at its number', PC_S,
  '    if target != "claim":\n        make_room(',
  '    if False:\n        make_room(',
  'a deviation must not delete a renumbered req record at its number'),
 ('prove: a renumbered record moved over the record already at its number', PC_S,
  '        if there.exists():\n            raise Refused(',
  '        if False:\n            raise Refused(',
  'a renumbered record whose clause already has a record must refuse, naming both files'),
 ('ref gate: a covered req binding other files than its claim', GR_S,
  '                    key in req_rec and req_rec.get(key) != proven[cites].get(key)',
  '                    False',
  'a covered req must carry its claim'),
 ('audit: proof drift at HEAD not reported', PY_S,
  '        if moved:\n            # Valid where it was proven, but HEAD holds another blob',
  '        if False:\n            # Valid where it was proven, but HEAD holds another blob',
  'drift must be reported, blocking, with the file and the record'),
 ('audit: proof drift advisory (a drifted proof passes the gate)', PY_S,
  '                out.append({**base, "severity": "blocking", "rule": drift})',
  '                out.append({**base, "severity": "advisory", "rule": drift})',
  'drift must be reported, blocking, with the file and the record'),
 ('audit: drift on a closed stage still blocking', PY_S,
  '            if tid.split(".")[0] in closed and held:',
  '            if False:',
  'drift on a task whose stage gate is fully ticked must be advisory'),
 ('audit: drift on an open stage advisory', PY_S,
  '            if tid.split(".")[0] in closed and held:',
  '            if True:',
  'drift must be reported, blocking, with the file and the record'),
 ('audit: ticked gate boxes alone make drift advisory', PY_S,
  '            if tid.split(".")[0] in closed and held:',
  '            if tid.split(".")[0] in closed:',
  'a stage closed on a drifted proof must keep its drift blocking'),
 ('audit: a green commit that held other blobs read as the close', PY_S,
  '        return any(tr is not None and not pc.blob_drift(rec, tr[1])',
  '        return any(tr is not None',
  'a stage closed on a drifted proof must keep its drift blocking'),
 ('audit: a stage gate with one box ticked read as closed', PY_S,
  '    return {stage for stage, got in ticks.items() if got and all(got)}',
  '    return {stage for stage, got in ticks.items() if got and any(got)}',
  'drift on a task whose stage gate is not fully ticked must be blocking'),
 ("audit: a covered req repeats its claim's drift", PY_S,
  "                continue  # a covered req binds its claim's maps: that claim's line reports it",
  "                pass",
  "a covered req must not repeat its claim's drift line"),
 ('ref gate: Stage N green lands over a drifted record', GR_S,
  '                        if moved:\n                            missing.append(f"{short} Stage {stage}: proof drift',
  '                        if False:\n                            missing.append(f"{short} Stage {stage}: proof drift',
  'drift must refuse Stage N green, naming the file and the record'),
 ('validate: record path (task/index) not compared', PC_S,
  '        if rec.get("task") != etask or rec.get("index") != eindex:',
  '        if False:',
  'a record at the wrong path must be rejected'),
 ('validate: plan wording not compared', PC_S,
  '        if etext is not None and rec.get("text") != etext:',
  '        if False:',
  'reworded claim must be rejected'),
 ('validate: kind not compared to the path', PC_S,
  '        if kind != ekind:',
  '        if False:',
  'kind/path mismatch must be rejected'),
 ('validate: booleans pass as exit codes', PC_S,
  '    return type(x) is int',
  '    return isinstance(x, int)',
  'booleans must not pass as exit codes'),
 ('notes stripped without a history mark', PY_S,
  '        if HISTORY_MARK.search(m.group(0)):',
  '        if True:',
  'a history-free note must still count'),
 ('notes matched on unmasked text (code spans stripped)', PY_S,
  '    for m in ANNOTATION.finditer(masked):',
  '    for m in ANNOTATION.finditer(text):',
  'code spans must not be stripped as notes'),
 ('records: commit binding not checked', PY_S,
  'problems = pc.validate(rec, fp, (kind, task, k, text), allow_legacy=True,\n                                   blobs=blobs)',
  'problems = pc.validate(rec, None, (kind, task, k, text), allow_legacy=True,\n                                   blobs=None)',
  'a stale local record must be blocking (red if disk records are trusted unbound)'),
 ('records: path and wording not checked', PY_S,
  'problems = pc.validate(rec, fp, (kind, task, k, text), allow_legacy=True,',
  'problems = pc.validate(rec, fp, allow_legacy=True,',
  'a reworded claim must be blocking (red if wording is not compared)'),
 ('finding 9 req records ignored', PY_S,
  '            if req == []:\n                if got.get(("legacy", k)):',
  '            if False:\n                if got.get(("legacy", k)):',
  'valid committed records must satisfy 8 and 9 (red if records are not read)'),
 ('finding 1: no task credited for its records', PY_S,
  '    return {t for t, got in recs.items() if t in blocks',
  '    return set() and {t for t, got in recs.items() if t in blocks',
  'each proven task earns its own credit (red when a commit is credited once whatever it holds)'),
 ('finding 1: naming tasks buys credit', PY_S,
  '    task_commits = max(task_commits, len(task_numbers(task_ids) & proven_tasks(repo, path)))\n',
  '    task_commits = max(task_commits, len(task_numbers(task_ids)))\n',
  'partial records leave subject stuffing caught (red when a task id alone earns credit)'),
 ('audit: legacy req checks blocking', PY_S,
  'problems = pc.validate(rec, fp, (kind, task, k, text), allow_legacy=True,',
  'problems = pc.validate(rec, fp, (kind, task, k, text),',
  "a local schema-1 record must not claim an add date (red if it says 'added after the cutover')"),
 ('audit: legacy req checks not reported', PY_S,
  '        if not open_ and legacy:',
  '        if False:',
  "schema-1 bare req check (added before the cutover) must be advisory 'legacy schema-1' (red"),
 ('audit: covered-by citation not followed', PY_S,
  '            if req == [] and cites is not None and (',
  '            if False and cites is not None and (',
  'the covered-by pointer must be followed (red when the cited claim goes unchecked)'),
 ('audit: stray files under proof/ allowed', PY_S,
  '    if stray:\n        out.append(',
  '    if False:\n        out.append(',
  'a non-record file under proof/ must block (red when proof/ accepts any file)'),
 ('prove: exit 126/127 counted as red', PC_S,
  '    if red_rc in (126, 127) or killed_by_signal(red_rc):',
  '    if killed_by_signal(red_rc):',
  'exit 127 must not be red'),
 ('prove: killed (128+n) counted as red', PC_S,
  '    if red_rc in (126, 127) or killed_by_signal(red_rc):',
  '    if red_rc in (126, 127):',
  'exit 137 must not be red'),
 ('validate: red exit 0 accepted', PC_S,
  '    if not _is_int(red) or red == 0 or red in (126, 127) or killed_by_signal(red):',
  '    if False:',
  'red exit 0 must be rejected'),
 ('validate: a bare schema-2 req check accepted', PC_S,
  '            _check_run(rec, p, "check")\n',
  '            pass\n',
  'a bare schema-2 req check must be rejected'),
 ('validate: legacy accepted at commit', PC_S,
  '    legacy = allow_legacy and is_legacy(rec)',
  '    legacy = is_legacy(rec)',
  'legacy req checks: rejected by default, accepted only with allow_legacy'),
 ('req: --check without --break accepted', PC_S,
  '        if not brk:\n            raise Usage',
  '        if False:\n            raise Usage',
  '--check without --break must be refused'),
 ('req: the check is never run', PC_S,
  '        seen = observe(repo, brk, check, build, no_build, timeout, text)\n',
  '        seen = {"baseline": {"exit": 0, "tail": ""}, "red": {"exit": 1, "tail": ""}}\n',
  'failing req check must be refused'),
 ('prove: recovery overwrites a moved repo', PC_S,
  '    if now_head != head or now_blobs != blobs:',
  '    if False:',
  'recovery must refuse a moved repo, exits -9/3'),
 ('prove: runs not exclusive', PC_S,
  '    held = lock(repo)  # noqa: F841',
  '    held = None  # noqa: F841',
  'runs must be exclusive'),
 ('prove: unparseable break counted (no build step)', PC_S,
  '            broken = unparseable(repo, paths)\n',
  '            broken = []\n',
  'a non-parsing break must be refused'),
 ('prove: the test runner may be broken', PC_S,
  '        if os.path.normpath(p) in runs or any(fnmatch.fnmatchcase(p, r) for r in patterns):',
  '        if False:',
  'the test runner must not be breakable'),
 ('prove: wider test trees not recognised', PC_S,
  '    r"|(^|/)[A-Za-z]*Test/"',
  '    r""',
  'TEST_PATH must cover the wider test trees'),
 ('subject_tasks: 1.10 read as 1.1', PY_S,
  '            out.add(cur.group(0))',
  '            out.add(cur.group(0)[:3])',
  'subject_tasks must read every subject form'),
 ('subject_tasks: case-sensitive again', PY_S,
  '    r"(?:tasks?\\b\\s*[:#-]?\\s*)?\\d+\\.\\d+)*)", re.I)',
  '    r"(?:tasks?\\b\\s*[:#-]?\\s*)?\\d+\\.\\d+)*)")',
  'finding 1 fired on an honest per-task history'),
 ('subject_tasks: ranges not expanded', PY_S,
  '                out.update(f"{a_major}.{n}" for n in range(a_minor + 1, b_minor))',
  '                pass',
  'subject_tasks must read every subject form'),
 ('subject_tasks: lists read as their first task', PY_S,
  '        for i, cur in enumerate(ids):',
  '        for i, cur in enumerate(ids[:1]):',
  'every record must be ignored for local mode (red if records[0] alone decides)'),
 ('validate: a non-dict run field crashes it', PC_S,
  '    return v.get("exit") if isinstance(v, dict) else None',
  '    return v.get("exit")',
  'validate() raised AttributeError on a malformed record'),
 ('audit: legacy has no cutoff', PY_S,
  '            if added is None or added >= datetime.datetime.fromisoformat(LEGACY_CUTOFF):',
  '            if False:',
  "schema-1 bare req check (added after the cutover) must be advisory 'not shown met' (red if"),
 ('finding 1: one proven claim credits a task', PY_S,
  '            and all(got.get(("claim", k)) == [] for k in required_claims(blocks[t]["test"]))}',
  '            and any(got.get(("claim", k)) == [] for k in required_claims(blocks[t]["test"]))}',
  'a task earns credit only with all its claims proven (red when a single record is enough)'),
 ('required claims: the first claim not required', PY_S,
  'if k == 1 or NAMED_BREAK.search(_masked(c))]',
  'if NAMED_BREAK.search(_masked(c))]',
  'honest run must be clean'),
 ('required claims: named breaks not required', PY_S,
  'if k == 1 or NAMED_BREAK.search(_masked(c))]',
  'if k == 1]',
  'a task earns credit only with all its claims proven (red when a single record is enough)'),
 ('required claims: every claim required', PY_S,
  'if k == 1 or NAMED_BREAK.search(_masked(c))]',
  'if k == 1 or True]',
  'records are owed for claim 1 and break-naming claims only (red when all claims are demanded)'),
 ('claim deviation counted as proof', PY_S,
  '                problems = ["recorded as a claim deviation"]',
  '                problems = []',
  'a claim deviation must earn no credit (red if a deviation counts as proof)'),
 ('claim deviation not reported', PY_S,
  '        if devs:\n',
  '        if False:\n',
  'an older commit matching a valid claim deviation must bind it (red if the fallback treats a valid deviation as a failure)'),
 ('claim deviation: reason not required (audit)', PY_S,
  'len(rec["why"].strip()) < 10:\n        p.append("a claim deviation without a reason")',
  'len(rec["why"].strip()) < 0:\n        p.append("a claim deviation without a reason")',
  'a reasonless claim deviation must be blocking (red if it is waived silently)'),
 ('claim deviation: task/index not compared', PY_S,
  '    if rec.get("task") != task or rec.get("index") != k:',
  '    if False:',
  'a claim deviation must match its path (red if task/index are not compared)'),
 ('claim deviation: wording not compared', PY_S,
  '        p.append("recorded against different wording than the plan now has")',
  '        pass',
  "a claim deviation must match the plan's wording (red if wording is not compared)"),
 ('claim deviation: fingerprint not compared', PY_S,
  '        p.append("recorded on a different tree than this one")',
  '        pass',
  'a deviation on a claim is tied to the tree of its commit (red when fingerprints go uncompared)'),
 ('deviation --claim records requirement wording', PC_S,
  '        text = pick(PFA.claim_clauses(block["test"]), index, "claim")',
  '        text = pick(PFA.requirement_clauses(block["desc"]), index, "claim")',
  'a claim deviation must record'),
 ('validate(): claim deviation not delegated to the audit', PC_S,
  '    if kind == "claim-deviation" and (not expect or expect[0] == "claim"):',
  '    if False:',
  'a claim deviation must not cover a requirement'),
 ('req: covered-by accepts a claim deviation as proof', PC_S,
  '        if not problems and crec.get("kind") != "claim":',
  '        if False:',
  'a claim deviation must not cover a requirement'),
 # unbacked() builds `out` before its Preflight step, so the filter itself is the anchor.
 ('finding 1: gate boxes always counted (a gate ticked with its green commit is a bulk flip)', PY_S,
  '    out = [e for e in entries if gates.get(e[2]) not in green]',
  '    out = list(entries)',
  "a stage's gate boxes are backed only by its green commit (red if gate boxes count, or coun"),
 ('finding 1: gate boxes backed without a Stage N green commit', PY_S,
  '    out = [e for e in entries if gates.get(e[2]) not in green]',
  '    out = [e for e in entries if gates.get(e[2]) is None]',
  "a stage's gate boxes are backed only by its green commit (red if gate boxes count, or coun"),
 ('finding 10: a live-check remediation with no fixture sweep goes silent', PY_S,
  '        if not hit or date < since or hit.group(1) not in stages:',
  '        if True:',
  'remediating a live-checked gate without a sweep is finding 10, advisory (red when nothing is reported)'),
 ('replay: a claim deviation counted as a failed replay', PC_S,
  '        if isinstance(rec, dict) and rec.get("kind") == "claim-deviation":',
  '        if False:',
  'replay must skip claim deviations'),
 # ---- hooks/git-ref-gate.sh: the opt-in commit gate
 ('ref gate: acts in the committed phase, where a refusal aborts nothing', GR_S,
  '[[ "${1:-}" == "prepared" ]] || exit 0',
  '[[ "${1:-}" == "committed" ]] || exit 0',
  'unproven task commit must be refused'),
 ('ref gate: the state file read naively, following symlinks', GR_S,
  'state = pcc.read_state(repo)',
  'p_ = repo / ".claude" / "plan-progress.json"; state = json.load(open(p_)) if p_.exists() else None',
  'symlinked state must not gate'),
 ('ref gate: HEAD updates ignored (a detached HEAD commit lands)', GR_S,
  'not (ref == "HEAD" or ref.startswith("refs/heads/"))',
  'not ref.startswith("refs/heads/")',
  'HEAD updates must be checked'),
 ('ref gate: commits already on a branch re-checked (old history blocks new work)', GR_S,
  'tip, "--not", "--branches", "--remotes")',
  'tip)',
  'history already on a branch must not block a proven commit'),
 ('ref gate: records read from the index, not the commit', GR_S,
  'r = git("show", f"{sha}:{rel}")',
  'r = git("show", f":{rel}")',
  'records must be read from the commit'),
 ('ref gate: the task read from the whole message, not the subject', GR_S,
  'git("log", "-1", "--format=%s", sha)',
  'git("log", "-1", "--format=%B", sha)',
  'the body must not be gated'),
 ('ref gate: stray files under proof/ allowed', GR_S,
  'if p and not pc.RECORD_PATH.match(p):',
  'if False:',
  'stray proof/ files must be refused'),
 ('ref gate: named-break claims not required (first claim only)', GR_S,
  '                if k in required:',
  '                if k == 1:',
  'a named-break claim without a record must be refused'),
 ('ref gate: every claim required (stricter than the rule)', GR_S,
  '                if k in required:',
  '                if True:',
  'a proven task commit must land'),
 ('ref gate: a present record validated only when required', GR_S,
  '            if probs:\n                missing.append(f"{short} Task {t} claim {k}: {probs[0]}")',
  '            if probs and k in required:\n                missing.append(f"{short} Task {t} claim {k}: {probs[0]}")',
  'a present invalid record must be refused'),
 ('ref gate: a record not bound to the commit tree', GR_S,
  'problems_of(rec, fp, ("claim", t, k, c), blobs)',
  'problems_of(rec, None, ("claim", t, k, c), None)',
  '-a must be checked against the tree git commits'),
 ('ref gate: a record not bound to the plan wording', GR_S,
  '("claim", t, k, c), blobs)',
  '("claim", t, k, None), blobs)',
  'reworded claim must be refused'),
 ('ref gate: a claim deviation counted as proof', GR_S,
  '            elif rec.get("kind") == "claim-deviation":',
  '            elif False:',
  'a claim deviation must be allowed and named'),
 ('ref gate: covered-by not followed to a valid proof', GR_S,
  'if probs.get("req") == [] and cites is not None and not proven.get(cites):',
  'if False:',
  'covered-by must accept only kind claim'),
 ('ref gate: deviations not named at commit time', GR_S,
  '    if deviations:\n        sys.stderr.write',
  '    if False:\n        sys.stderr.write',
  'a claim deviation must be allowed and named'),
 ('ref gate: unaccounted requirements not named (finding 9 silent)', GR_S,
  '    if advisory:',
  '    if False:',
  'an unaccounted requirement must be named, not silently passed'),
 ('ref gate: a refusal exits 0', GR_S,
  '    sys.stderr.write(text.rstrip() + "\\n")\n    sys.exit(1)',
  '    sys.stderr.write(text.rstrip() + "\\n")\n    sys.exit(0)',
  'unproven task commit must be refused'),
 # ---- proof-hooks-install.py
 ('installer: a foreign reference-transaction hook replaced', PI_S,
  '        if not shim_is_ours(hook):\n            die(',
  '        if False:\n            die(',
  'a foreign hook must not be overwritten'),
 ('installer: --remove deletes a foreign hook', PI_S,
  '    if not shim_is_ours(hook):\n        print(f"nothing to remove',
  '    if False:\n        print(f"nothing to remove',
  '--remove must remove only its own shim'),
 ('installer: a shim without its exec bit counts as installed', PI_S,
  'return os.access(hook, os.X_OK) and hook.read_text(errors="replace") == shim_text()',
  'return hook.read_text(errors="replace") == shim_text()',
  'a non-executable shim must not count as installed'),
 ('installer: an edited shim counts as installed', PI_S,
  'return os.access(hook, os.X_OK) and hook.read_text(errors="replace") == shim_text()',
  'return os.access(hook, os.X_OK)',
  'an edited shim must not count as installed'),
 ('installer: core.hooksPath ignored', PI_S,
  'hd = Path(hooks) if os.path.isabs(hooks) else r / hooks',
  'hd = r / ".git" / "hooks"',
  'a shared hooks directory must be refused'),
 ('installer: the shim is written without its exec bit', PI_S,
  'os.chmod(tmp, 0o755)',
  'os.chmod(tmp, 0o644)',
  'unproven task commit must be refused'),
 ('installer: a dangling shim fails open in silence', PI_S,
  'is missing — the commit gate is OFF;',
  'is missing;',
  'a dangling shim must fail open loudly'),
 ('installer: re-install rewrites a current shim', PI_S,
  '        if shim_is_current(hook):\n            print(f"already installed',
  '        if False:\n            print(f"already installed',
  're-install must leave the shim unchanged'),
 ('installer: a non-repo accepted', PI_S,
  '    if top.returncode != 0:\n        die(f"{r} is not a git work tree")',
  '    if False:\n        die(f"{r} is not a git work tree")',
  'a non-repo must be refused'),
 ('installer: --status reports a missing shim as installed', PI_S,
  '        print(f"not installed — no {HOOK_NAME} hook in {top}")\n    return 1',
  '        print(f"not installed — no {HOOK_NAME} hook in {top}")\n    return 0',
  '--status must report not installed after --remove'),
 # ---- plan-flip-audit.py: proof listings take any path; orphaned proof directories
 ('audit: committed records split on whitespace', PY_S,
  '                   for rel in listing.split("\\0") if rel]',
  '                   for rel in listing.split() if rel]',
  'each proven task earns its own credit'),
 ('audit: the orphan step printed with its operands unquoted', PY_S,
  '            move = (f"`git mv {shlex.quote(src)} {shlex.quote(dst)}` (plain `mv` when proof/ "',
  '            move = (f"`git mv {src} {dst}` (plain `mv` when proof/ "',
  'the git mv operands must be shell-quoted'),
 ('audit: the orphan step offers a nesting git mv onto an existing directory', PY_S,
  '        if (Path(repo) / dst).is_dir():',
  '        if False:',
  'an existing proof/<new>/ must get a merge step'),
 ('audit: a renumbered record replaces the own-number record of its clause', PY_S,
  '        if at != k and (task, kind, at) in own:\n            continue',
  '        if False:\n            continue',
  'the own-number record must decide its clause'),
 ('audit: a stem-derived record path read as a glob pathspec (committed)', PY_S,
  'gout(repo, "--literal-pathspecs", "log", "-1", "--format=%H", "--", rel)',
  'gout(repo, "log", "-1", "--format=%H", "--", rel)',
  'a stem with `[`, `*` must be a literal pathspec (committed)'),
 ('audit: a local record checked for ignore against the index', PY_S,
  'gout(repo, "check-ignore", "-q", "--no-index", "--",',
  'gout(repo, "check-ignore", "-q", "--",',
  'a stem with `[`, `*` must be a literal pathspec (local)'),
 ('audit: an orphaned proof directory not reported', PY_S,
  '    for old in orphan_proof_dirs(repo, path):',
  '    for old in []:',
  'proof/<old>/ with no plan must be named'),
 ('audit: a local orphaned proof directory not seen', PY_S,
  '        stems |= {d.name for d in base.iterdir() if d.is_dir()}',
  '        stems |= set()',
  'a local proof/<old>/ with no plan must be named'),
 ('clauses: the sentence start read on the masked text', PY_S,
  '            if end == m.start() + 1 or not SENTENCE_START.match(desc, end):',
  '            if end == m.start() + 1 or not SENTENCE_START.match(masked, end):',
  '"`a` holds. `b` holds." must be two clauses'),
 ('audit: a renumbered record not matched by its text', PY_S,
  '            j = renumbered(rec, requirement_clauses(blocks[task]["desc"]))',
  '            j = None',
  'a record whose clause number shifted must match by text'),
 ('ref gate: a renumbered req record not looked up', GR_S,
  '                    if isinstance(rj, dict) and pfa.renumbered(rj, clauses) == k:',
  '                    if False:',
  'a renumbered req record must be looked up and judged for its clause'),
 ("ref gate: another clause's record judged under its old number", GR_S,
  "                    recs[kind] = r = None  # another clause's record, under its old number",
  "                    pass",
  'a renumbered req record must match its clause by text'),
 # ---- plan-flip-audit.py: an abbreviation before a code span ends no sentence
 ('clauses: an abbreviation before a code span ends a sentence', PY_S,
  '            if desc.startswith("`", end) and (word in ABBREVIATIONS or (',
  '            if False and (word in ABBREVIATIONS or (',
  '"e.g. `x`" must stay one clause'),
 ('clauses: a single letter before a code span ends a sentence', PY_S,
  '                    len(word) == 1 and word.isalpha())):',
  '                    False)):',
  '"a. `x`" must stay one clause'),
 ('clauses: the abbreviation read case-sensitively', PY_S,
  '*_").lower()',
  '*_")',
  '"No. `x`" must stay one clause'),
 # ---- prove-claim.py: the runner behind shell syntax, the shell, restore edge cases
 ('prove: killed_by_signal reads every exit >= 128 as a signal', PC_S,
  '    return rc < 0 or 128 < rc <= 128 + 64',
  '    return rc < 0 or rc >= 128',
  'exit 255 is a legitimate red'),
 ('prove: shell syntax taken as the program', PC_S,
  '        if w in SHELL_OPENERS or _is_paren(w):\n            i += 1',
  '        if _is_paren(w):\n            i += 1',
  'the runner behind `{ python3 t.py; }` must not be breakable'),
 ('prove: wrappers taken as the program', PC_S,
  '        elif Path(w).name in WRAPPERS:',
  '        elif False:',
  'the runner behind `timeout 60 python3 t.py` must not be breakable | the runner behind `env A=1 python3 t.py` must not be breakable'),
 ('prove: a break of the runner recipe accepted', PC_S,
  '        if os.path.normpath(p) in recipes:',
  '        if False:',
  'the Makefile behind `make test` must not be breakable'),
 ('prove: a cd not followed', PC_S,
  '            base = (os.path.normpath(os.path.join(base, dest))',
  '            base = ("."',
  'the programs `cd scripts && python3 v2.py` runs must be'),
 ('prove: substitutions not read', PC_S,
  '    for sub in inner:\n        yield from located_commands(sub, base, _depth + 1)',
  '    for sub in ():\n        yield from located_commands(sub, base, _depth + 1)',
  'the programs `x=$(python3 t.py)'),
 ("prove: a shell's -c string not read", PC_S,
  '        elif prog and Path(prog[0]).name in C_SHELLS and "-c" in prog[1:-1]:',
  '        elif False:',
  'the programs `bash -c'),
 ('prove: segments split inside quotes', PC_S,
  '        if quote:\n            quote = None if c == quote else quote\n        elif c in',
  '        if False:\n            quote = None if c == quote else quote\n        elif c in',
  'the programs `bash -c'),
 ('prove: attached option values ignored', PC_S,
  '        vals += [a[len(nm):] for nm in names',
  '        vals += [a[len(nm):] for nm in ()',
  'runner_files must name exactly the file each runner reads'),
 ('prove: bash never chosen', PC_S,
  '    if wanted in (None, "bash"):',
  '    if wanted in ("bash",):',
  'a bash-syntax Test must run under bash'),
 ('prove: a relative bash path kept', PC_S,
  '            return "bash", os.path.abspath(bash)',
  '            return "bash", bash',
  "the repo's own ./bash must not run the test"),
 ('replay: the recorded shell ignored', PC_S,
  '                      shell=rec.get("shell", "sh"))',
  '                      shell=None)',
  'a record without `shell` must replay under sh'),
 ('validate: any shell accepted', PC_S,
  '    if "shell" in rec and rec["shell"] not in ("bash", "sh"):',
  '    if False:',
  'a record with shell zsh must fail validation'),
 ("prove: the build's own untracked output fails the restore", PC_S,
  '        require_clean(repo, before)',
  '        require_clean(repo)',
  "a build's own untracked output must not fail the restore"),
 ('prove: no rebuild after a refusal under the break', PC_S,
  '        refused = e\n',
  '        raise\n',
  'a build-stopping break must be refused and rebuilt after'),
 ('prove: a non-UTF-8 break stored lossily', PC_S,
  '                  "break_patch_b64": base64.b64encode(patch_bytes).decode()}',
  '                  }',
  'a non-UTF-8 break must be stored byte-exact'),
 ('validate: break_patch_b64 not checked as base64', PC_S,
  '            p.append("break_patch_b64 is not base64")',
  '            pass',
  'an undecodable break_patch_b64 must fail validation'),
 ('validate: break_patch_b64 may be another break', PC_S,
  '            if not raw or raw.decode("utf-8", errors="replace") != rec.get("break_patch"):',
  '            if False:',
  'break_patch_b64 and break_patch must be one break'),
 ('restore: a read-only file not made writable', PC_S,
  '                os.chmod(f, stat.S_IMODE(f.stat().st_mode) | stat.S_IWUSR)',
  '                pass',
  'a read-only file must be restored with its mode'),
 ('prove: the killed refusal does not name the signal', PC_S,
  '               or f"killed by signal {-red_rc if red_rc < 0 else red_rc - 128}")',
  '               or "killed by a signal")',
  'exit 137 must not be red'),
 ("prove: a for loop's variable not expanded", PC_S,
  '            for each in _loop_expand(prog, loops):\n                yield base, each',
  '            for each in [prog]:\n                yield base, each',
  'the programs `for f in {t,u}.py; do python3 "$f" || exit 1; done` runs must include'),
 ('prove: a brace list not expanded', PC_S,
  '    m = re.search(r"\\{([^{}]*,[^{}]*)\\}", word)\n    if not m:',
  '    m = None\n    if not m:',
  'the programs `for f in {t,u}.py; do python3 "$f" || exit 1; done` runs must include'),
 ('prove: a glob runner not matched', PC_S,
  ' or any(fnmatch.fnmatchcase(p, r) for r in patterns):',
  ':',
  'the runner behind `for f in t*.py; do python3 "$f" || exit 1; done` must not be breakable'),
 ("prove: a make or npm recipe's runner not read", PC_S,
  '    runs = (command_programs(test) | recipe_programs(repo, test)) if test else set()',
  '    runs = command_programs(test) if test else set()',
  "the script `make test`'s recipe runs must not be breakable"),
 # ---- the lock rule: proof-guard.sh, git-ref-gate.sh and their shared helper
 ('guard: the lock rule off', PG_S,
  '        if live:\n            deny(f"Denied: this command commits in {r}, and {live}")',
  '        if False:\n            deny(f"Denied: this command commits in {r}, and {live}")',
  'a commit while prove-claim holds its lock must be denied naming it (repo)'),
 ('lock rule: a held lock not reported', PCC_S,
  '    if held:\n        return (f"a prove-claim.py run is in progress',
  '    if False:\n        return (f"a prove-claim.py run is in progress',
  'a commit while prove-claim holds its lock must be denied naming it (repo) | a commit during a live proof must be refused'),
 ('lock rule: the journal not read', PCC_S,
  '    if journal is not None and journal.is_file():',
  '    if False:',
  'a commit with a prove-claim journal present must be denied | a commit over an interrupted proof must be refused'),
 ('lock rule: any word "commit" counts', PCC_S,
  '    return bool(re.search(r"\\bgit\\b", command) and re.search(r"\\bcommit\\b", command))',
  '    return bool(re.search(r"\\bcommit\\b", command))',
  'a non-commit command must get no decision while the lock is held'),
 ('ref gate: the lock rule off', GR_S,
  'if live:\n    refuse(f"commit gate: refused — {live}")',
  'if False:\n    refuse(f"commit gate: refused — {live}")',
  'a commit during a live proof must be refused'),
 # ---- hooks/proof-guard.sh: the PreToolUse guard
 ('guard: the hooksPath rule off', PG_S,
  'if re.search(r"hookspath", command, re.I):',
  'if False:',
  "a planted json.py must not switch the guard off"),
 ('guard: hooksPath matched case-sensitively', PG_S,
  'command, re.I):',
  'command):',
  "a planted json.py must not switch the guard off"),
 ('guard: the hook-file rule off', PG_S,
  'if re.search(rf"{HOOK_NAME}|\\.git/hooks", command):',
  'if False:',
  "must deny 'rm .git/hooks/reference-transaction'"),
 ('guard: the installer --remove rule off', PG_S,
  'if inst in command and re.search(r"--remove\\b", command):',
  'if False:',
  "must deny 'python3 "),
 ('guard: acts without opt-in', PG_S,
  'gated = [r for r in repos if opted_in(r) and in_flight(r)]',
  'gated = [r for r in repos if in_flight(r)]',
  'a repo that did not opt in must see no decision'),
 ('guard: acts with no plan in flight', PG_S,
  'gated = [r for r in repos if opted_in(r) and in_flight(r)]',
  'gated = [r for r in repos if opted_in(r)]',
  'no plan in flight must see no decision'),
 ('guard: any reference-transaction hook counts as our opt-in', PG_S,
  '        return len(lines) > 1 and lines[1].startswith(f"# {MARK} — installed by")',
  '        return True',
  "someone else's hook must not opt the repo in"),
 ('guard: the state file read naively, following symlinks', PG_S,
  '    state = pcc.read_state(repo)',
  '    p_ = repo / ".claude" / "plan-progress.json"; state = json.load(open(p_)) if p_.exists() else None',
  'symlinked state must not count'),
 ('guard: a repo reached by cd not considered', PG_S,
  're.findall(r"\\bcd\\s+(',
  're.findall(r"\\bcdXX\\s+(',
  "/repo && git -c core.hookspath=/x commit -m x'"),
 ('guard: a repo reached by git -C not considered', PG_S,
  're.findall(r"\\bgit\\s+-C\\s+(',
  're.findall(r"\\bgitXX\\s+-C\\s+(',
  "/repo -c core.hooksPath=/x commit -m x'"),
 ('guard: the pre-filter drops hooksPath', PG_S,
  "[[ $PAYLOAD =~ hookspath|reference-transaction|",
  "[[ $PAYLOAD =~ reference-transaction|",
  "must deny 'git config core.HOOKSPATH /tmp/none'"),
 ('guard: the pre-filter drops the hook file', PG_S,
  "[[ $PAYLOAD =~ hookspath|reference-transaction|",
  "[[ $PAYLOAD =~ hookspath|",
  "must deny 'cd .git && rm hooks/reference-transaction'"),
 ('guard: an unreadable payload denied (fails closed)', PG_S,
  '    none("payload is not JSON")',
  '    deny("payload is not JSON")',
  'a garbage payload must produce no decision'),
 ('guard: the decision is "ask", not "deny"', PG_S,
  '"permissionDecision": "deny"',
  '"permissionDecision": "ask"',
  "a planted json.py must not switch the guard off"),
 # ---- fail-open, fetched commits, option abbreviation and shared hooks directories
 ('ref gate: no python3 aborts every update', GR_S,
  'command -v python3 >/dev/null 2>&1 || {',
  'false && {',
  'a missing python3 must fail open with a note'),
 ('ref gate: an uncaught exception refuses the update', GR_S,
  'sys.excepthook = _fail_open',
  'pass',
  'an uncaught error must fail open'),
 ('ref gate: fetched commits gated as if added here', GR_S,
  '"--not", "--branches", "--remotes")',
  '"--not", "--branches")',
  'a fetched commit must be checkable-out'),
 ('installer: --rem abbreviates --remove past the guard', PI_S,
  '        allow_abbrev=False,',
  '        allow_abbrev=True,',
  '--rem must not act as --remove'),
 ('installer: a shared hooks directory accepted', PI_S,
  '    if not any(within(hd, base) for base in (top, common)):',
  '    if False:',
  'a shared hooks directory must be refused'),
 ('installer: the marker anywhere identifies our shim', PI_S,
  '    return len(lines) > 1 and lines[1].startswith(SHIM_LINE2)',
  '    return any(SHIM_MARK in l for l in lines)',
  'the marker must identify only our shim'),
 ('guard: a shim in a shared hooks directory counts as opt-in', PG_S,
  '        if not any(hd.resolve().is_relative_to(b.resolve()) for b in (repo, common)):',
  '        if False:',
  'a shared hooks directory must not opt a repo in'),
]


def suites_for(target):
    # The installer's suite is the git hook's: one fixture installs the shim the
    # hook runs from.
    return {PY_S: [PY_T], PC_S: [PC_T], GR_S: [GR_T], PI_S: [GR_T], PG_S: [PG_T],
            PCC_S: [PG_T, GR_T]}[target]


SUITE_TIMEOUT = 900   # seconds; the slowest suite takes ~20 s alone


def run(root, suite):
    """(exit code, stdout) of one suite run; exit None on a timeout."""
    cmd = ["bash"] if suite.endswith(".sh") else [sys.executable]
    try:
        r = subprocess.run(cmd + [str(root / suite)], capture_output=True,
                           text=True, timeout=SUITE_TIMEOUT,
                           env=dict(os.environ, SUITE_FAIL_FAST="1"))
    except subprocess.TimeoutExpired:
        return None, ""
    return r.returncode, r.stdout


def copy_skill():
    """A private copy of the plugin's executing-plans skill and hooks directory,
    at d/planning: the suites find the scripts and hooks where the plugin has them."""
    d = Path(tempfile.mkdtemp(prefix="battery-proof-tools-"))
    ignore = shutil.ignore_patterns("__pycache__", "mod", "node_modules")
    shutil.copytree(PLUGIN / EP, d / "planning" / EP, ignore=ignore)
    shutil.copytree(PLUGIN / "hooks", d / "planning" / "hooks", ignore=ignore)
    # The Claude Code registration is a host file: in this repo's source tree it lives
    # in hosts/claude/add/hooks/, and the built plugin puts it beside the hooks.
    claude_hooks = PLUGIN.parent / "hosts" / "claude" / "add" / "hooks" / "hooks.json"
    if not (d / "planning" / "hooks" / "hooks.json").exists() and claude_hooks.exists():
        shutil.copy(claude_hooks, d / "planning" / "hooks" / "hooks.json")
    return d


HEREDOC_PY = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.S)


def unparseable(f):
    """Why the mutated file would not even run, or None. A shell hook is checked
    with `bash -n` AND its embedded Python compiled: a hook that crashes fails
    open, so its suite would go red having measured nothing about the guard."""
    if f.suffix == ".py":
        try:
            py_compile.compile(str(f), cfile=str(f.parent / ".check.pyc"), doraise=True)
        except py_compile.PyCompileError:
            return "the mutation leaves the script unparseable"
        return None
    if subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode != 0:
        return "the mutation leaves the hook's shell unparseable"
    for body in HEREDOC_PY.findall(f.read_text()):
        try:
            compile(body, str(f), "exec")
        except SyntaxError:
            return "the mutation leaves the hook's Python unparseable"
    return None


def trial(entry):
    """(label, verdict) for one mutation, run in its own copy.

    killed: the suite's first failing check (`  FAIL` on stdout, every suite's
    marker; the suite runs fail-fast) is the one the entry names. MISNAMED: another
    check killed it. SURVIVED: every suite passed. ERROR: anything else — never counted
    as a kill. Exceptions are caught here, so a worker's crash cannot escape as
    Python's exit 1, which this file defines as "survived".
    """
    label = entry[0] if entry else "?"
    d = None
    try:
        label, target, old, new, killer = entry
        d = copy_skill()
        f = d / "planning" / target
        f.write_text(f.read_text().replace(old, new))
        why = unparseable(f)
        if why:
            return label, "ERROR", why
        for s in suites_for(target):
            rc, out = run(d / "planning", s)
            if rc is None:
                return label, "ERROR", f"{s} timed out after {SUITE_TIMEOUT}s"
            if rc != 0:
                fails = [ln[8:] for ln in out.splitlines() if ln.startswith("  FAIL")]
                if not fails:
                    return label, "ERROR", f"{s} exited {rc} without reporting a failing check"
                if any(k.strip() in fails[0] for k in killer.split(" | ")):
                    return label, "killed", ""
                lines = out.splitlines()
                at = next(i for i, ln in enumerate(lines) if ln.startswith("  FAIL"))
                detail = " / ".join(ln.strip() for ln in lines[at + 1: at + 4]
                                    if ln.startswith("        |"))
                return label, "MISNAMED", (f"killed by `{fails[0][:90]}`, named `{killer}`"
                                           + (f" — {detail[:300]}" if detail else ""))
        return label, "SURVIVED", ""
    except Exception as e:  # noqa: BLE001
        return label, "ERROR", f"{e.__class__.__name__}: {e}"
    finally:
        if d is not None:
            shutil.rmtree(d, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--anchors-only", action="store_true",
                    help="check every anchor still matches, run nothing")
    args = ap.parse_args()
    jobs = max(1, args.jobs)

    # Every anchor is checked BEFORE anything runs. A missing one is the exit-4
    # outcome anyway; finding it first costs a second rather than a battery.
    # An anchor at several sites is mutated at ALL of them: a guard emitted in
    # two places is only pinned if BOTH are covered.
    # A killer that is empty, or has an empty ` | ` alternative, matches every FAIL line and
    # would read any kill as the named one; a short entry would crash a worker. Both are
    # refused before anything runs.
    malformed = [e[0] for e in M if len(e) != 5
                 or not all(k.strip() for k in str(e[4]).split(" | "))]
    if malformed:
        for label in malformed:
            print(f"  MALFORMED {label}  (needs 5 fields and a non-empty killer)")
        return 2
    gone = [label for label, target, old, *_ in M if (PLUGIN / target).read_text().count(old) == 0]
    if gone:
        for label in gone:
            print(f"  SKIP     {label}  (anchor missing)")
        sys.stderr.write(f"\n{len(gone)} mutation(s) SKIPPED — anchors gone, those guards are "
                         "no longer pinned. Re-anchor them. Nothing was mutated.\n")
        return 4
    if args.anchors_only:
        print(f"anchors: all {len(M)} present")
        return 0

    print("control: suites must be green before mutating")
    d = copy_skill()
    try:
        red = [s for s in SUITES if run(d / "planning", s)[0] != 0]
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if red:
        print(f"  ABORT — {', '.join(red)} already red")
        return 2
    print(f"  ok\n\nrunning {len(M)} mutations, {jobs} at a time")

    counts = {"killed": 0, "SURVIVED": 0, "ERROR": 0, "MISNAMED": 0, "UNSTABLE": 0}
    misnamed = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for entry, (label, verdict, why) in zip(M, pool.map(trial, M)):
            if verdict == "MISNAMED":
                misnamed.append((entry, why))
                continue
            print(f"  {verdict:<8} {label}" + (f"  ({why})" if why else ""), flush=True)
            counts[verdict] += 1
    # A MISNAMED trial is re-run once, alone, after the pool: under -j N a check that
    # also covers the guard sometimes fails first (measured: an rc=128 from
    # `git commit` in test-git-ref-gate.sh, 1-2 times in ~5 full runs, never in 36
    # targeted ones). A wrong name is deterministic and stays MISNAMED; a first killer
    # that changed between runs is UNSTABLE — printed with the stray failure's detail
    # so it can be diagnosed, and never counted as a kill or a misname.
    for entry, why in misnamed:
        label, verdict, why2 = trial(entry)
        if verdict == "killed":
            verdict, why2 = "UNSTABLE", f"first run {why}; re-run alone: killed by its named check"
        print(f"  {verdict:<8} {label}" + (f"  ({why2})" if why2 else ""), flush=True)
        counts[verdict] += 1
    print(f"\nkilled {counts['killed']}  survived {counts['SURVIVED']}  "
          f"errors {counts['ERROR']}  misnamed {counts['MISNAMED']}  "
          f"unstable {counts['UNSTABLE']}  skipped 0")
    if counts["SURVIVED"]:
        return 1
    if counts["ERROR"]:
        return 5
    return 6 if counts["MISNAMED"] else 0


if __name__ == "__main__":
    sys.exit(main())
