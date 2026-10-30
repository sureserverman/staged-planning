#!/usr/bin/env python3
"""Structure suite for the background-work rules — run directly (CI convention):

    python3 core/skills/executing-plans/tests/test-background-work-contract.py

PROSE contracts, not behavior: the suite asserts the rules are stated where the
executor and a dispatched agent read them, using the shared negation screening
(test-gate-remediation-contract.py's affirms_claim). What it pins:

  1. task-execution.md waits on a background job by its own completion (the harness
     notification, `wait <pid>`, or a sentinel file the job writes last), and says why
     a process-name search is not that: `pgrep -f` matches the shell whose command line
     holds the pattern.
  2. close-out.md and session-handoff.md § On `handoff` both carry the reap step: list
     what this run started — by the id each launch result and completion notification
     carried, not by a listing tool (Claude Code ships `TaskStop` and no
     `TaskList`) — stop each whose result was used (`TaskStop`), and name any still
     running in the report.
  3. The return-clean clause — an agent returns only after its own background work has
     finished or been stopped, and says which — stands in all three places a dispatched
     agent is briefed: the dispatch template's `## Return` block, and stage-gate.md's
     evaluator and Tier-2 sections.

  4. Every file that dispatches an agent carries both rules — wait on a background job
     by its own completion, and the return-clean clause — in the brief it gives that
     agent (an agent definition: told to the agent itself). The set is computed here,
     not listed: `git grep -l -E 'subagent_type|Agent tool|dispatch' -- core/agents
     'core/skills/*/SKILL.md'`, plus brainstorming, plus every host override of those
     names. A file the grep catches that only names dispatch is exempted in EXEMPT, by
     name, with its reason; an exemption the grep no longer catches fails, so the list
     cannot outlive its reason.

The failures it guards against: a gate that waits on `until ! pgrep -f run-tests.sh`
matches its own shell and waits for ever, and a background reviewer left running after
its verdict is used keeps writing into the tree.
"""
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
REFS = os.path.join(SKILLS, "executing-plans", "references")
TASKEXEC = os.path.join(REFS, "task-execution.md")
CLOSEOUT = os.path.join(REFS, "close-out.md")
HANDOFF = os.path.join(REFS, "session-handoff.md")
STAGEGATE = os.path.join(REFS, "stage-gate.md")
DISPATCH = os.path.join(SKILLS, "dispatching-parallel-agents", "SKILL.md")
HELPER = os.path.join(HERE, "test-gate-remediation-contract.py")
REPO = os.path.dirname(os.path.dirname(SKILLS))

# Section 4's population: the grep below, plus files it misses that dispatch anyway.
DISPATCH_GREP = ["git", "grep", "-l", "-E", "subagent_type|Agent tool|dispatch", "--",
                 "core/agents", "core/skills/*/SKILL.md"]
DISPATCH_EXTRA = (
    # Phase 1 grounding is often handed to a research agent; the grep does not see it.
    "core/skills/brainstorming/SKILL.md",
)
# Caught by the grep, yet dispatches no agent. Keyed by the path below core/, so a host
# override of the same name is exempt for the same reason.
EXEMPT = {
    "skills/honest-gates/SKILL.md":
        "names dispatch only to say its rules cost a command and no agent dispatch",
    "skills/planning-projects/SKILL.md":
        "writes the plan's Dispatch fields and its Preflight probe line; executing-plans and "
        "dispatching-parallel-agents dispatch and brief the agents",
}

spec = importlib.util.spec_from_file_location("_gate_contract", HELPER)
_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_helper)
affirms_claim = _helper.affirms_claim

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def ws(pattern):
    """Every space may be any whitespace run: the references are hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def section(text, start_pat, end_pat):
    m = re.search(start_pat, text, re.M)
    if not m:
        return ""
    rest = text[m.start():]
    e = re.search(end_pat, rest[1:], re.M)
    return rest[: e.start() + 1] if e else rest


RETURN_CLEAN = ws(r"returns only after its own background work has finished or been stopped")
WAIT_BY_COMPLETION = ws(r"background job") + r"[^.]{0,60}?" + ws(r"by its own completion")


def blocks_end_sentences(text):
    """A list item, heading, quote or code fence starts a new sentence.

    Section 4 screens whole files, where a bullet carries no full stop: read raw, the
    template's `- An agent returns only after …` bullet runs on into the next paragraph's
    "(no refactoring creep)" and screens as negated.
    """
    return re.sub(r"\n(?=[ \t]*(?:[-*+] |\d+\. |#|```|>))", ".\n", text)


def dispatching_files():
    """(core set, overrides, error): section 4's population, computed from the tree.

    `overrides` also holds every agent definition a host adds under `add/agents/`
    (Codex ships its roles that way, beside no core counterpart for some): an agent
    definition is what a dispatched agent reads, whatever its name or format."""
    try:
        out = subprocess.run(DISPATCH_GREP, cwd=REPO, capture_output=True, text=True,
                             check=True).stdout
        tracked = subprocess.run(
            ["git", "ls-files", "hosts/*/overrides/agents/*",
             "hosts/*/overrides/skills/*/SKILL.md", "hosts/*/add/agents/*"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        return [], [], str(exc)
    core = sorted(set(out.split()) | set(DISPATCH_EXTRA))
    names = {p[len("core/"):] for p in core}
    overrides = sorted(p for p in tracked.split()
                       if "/add/agents/" in p or p.split("/overrides/", 1)[1] in names)
    return core, overrides, ""


def main():
    # --- 1. the wait rule -------------------------------------------------------------
    wait = section(read(TASKEXEC), r"^## Waiting on background work", r"^## ")
    check("task-execution: § Waiting on background work located", bool(wait))
    check("task-execution: wait on a background job by its own completion",
          affirms_claim(wait, ws(r"wait on a background job by its own completion")),
          "no non-negated 'wait on a background job by its own completion'")
    check("task-execution: names the three completion signals",
          all(re.search(p, wait) for p in (ws(r"harness"), r"`wait <pid>`", ws(r"sentinel file"))),
          "one of: harness notification / `wait <pid>` / sentinel file is absent")
    check("task-execution: names the `pgrep -f` self-match",
          "`pgrep -f`" in wait
          and affirms_claim(wait, ws(r"matches the shell whose command line holds the pattern")),
          "`pgrep -f` … 'matches the shell whose command line holds the pattern' absent or negated")

    check("task-execution: the self-excluding name search is given",
          "`pgrep -f '[r]un-tests.sh'`" in wait,
          "the `[r]un-tests.sh` remedy is gone, leaving only the broken loop")
    check("task-execution: ids are kept from what the launches returned",
          affirms_claim(wait, ws(r"The list is kept from the ids the launches returned"))
          and "`TaskStop`" in wait,
          "the definition close-out and handoff point at is gone")
    check("task-execution: ids are noted at launch, where a successor can read them",
          affirms_claim(wait, ws(r"note each id when it is launched")),
          "ids are left to a transcript a successor session does not have")
    check("task-execution: --unstopped is named for agents",
          "review-ledger-check.py --unstopped" in wait, "the agent lister is unnamed")

    # --- 2. the reap step at close-out and handoff --------------------------------------
    closeout = read(CLOSEOUT)
    handoff = section(read(HANDOFF), r"^## On `handoff`", r"^## ")
    for name, text in (("close-out", closeout), ("handoff", handoff)):
        check(f"{name}: lists what the run started, by the ids its launches returned",
              affirms_claim(text, ws(r"list the background tasks and agents this run started"))
              and affirms_claim(text, ws(r"by the id each launch result")),
              "'list the background tasks and agents this run started … by the id each launch "
              "result' absent")
        check(f"{name}: does not send the executor to a TaskList tool the host lacks",
              "TaskList" not in text, "TaskList named as the listing tool")
        check(f"{name}: stops each whose result was used with `TaskStop`",
              "`TaskStop`" in text and affirms_claim(text, ws(r"stop each whose result was used")),
              "'stop each whose result was used' + `TaskStop` absent")
        check(f"{name}: names any still running in the report",
              affirms_claim(text, ws(r"name each one still running")),
              "'name each one still running' absent or negated")

    # --- 3. return-clean in the three briefs --------------------------------------------
    ret = section(read(DISPATCH), r"^## Return", r"^```")
    stagegate = read(STAGEGATE)
    evaluator = section(stagegate, r"^## Independent evaluator for non-command checks", r"^## ")
    tier2 = section(stagegate, r"^## Deep code review \(Tier 2\)", r"^## ")
    for name, text in (("dispatch template ## Return", ret),
                       ("stage-gate evaluator brief", evaluator),
                       ("stage-gate Tier-2 brief", tier2)):
        check(f"{name}: an agent returns only after its own background work finished or stopped",
              bool(text) and affirms_claim(text, RETURN_CLEAN),
              "return-clean clause absent or negated")
        check(f"{name}: ...and says which",
              bool(text) and re.search(RETURN_CLEAN + r"[^.]{0,40}" + ws(r"and says which"),
                                       text) is not None,
              "'and says which' absent")

    # --- 4. every dispatching file carries both rules ------------------------------------
    core, overrides, err = dispatching_files()
    check("dispatching files: the set is computed from the tree", bool(core) and not err,
          err or "the grep found no file")
    caught = {p[len("core/"):] for p in core}
    for name, reason in sorted(EXEMPT.items()):
        check(f"exemption {name}: the grep still catches it", name in caught,
              f"stale exemption ({reason}) — drop it")
    for path in core + overrides:
        name = (path.split("/overrides/", 1)[1] if "/overrides/" in path
                else path if "/add/" in path else path[len("core/"):])
        if name in EXEMPT:
            continue
        text = blocks_end_sentences(read(os.path.join(REPO, path)))
        check(f"{path}: wait on a background job by its own completion",
              affirms_claim(text, WAIT_BY_COMPLETION),
              "no non-negated 'background job … by its own completion'")
        check(f"{path}: returns only after its own background work finished or stopped, "
              f"and says which",
              affirms_claim(text, RETURN_CLEAN)
              and re.search(RETURN_CLEAN + r"[^.]{0,40}" + ws(r"and says which"), text)
              is not None,
              "return-clean clause absent, negated, or without 'and says which'")
    print(f"dispatching files checked: {len(core)} core + {len(overrides)} overrides, "
          f"{len(EXEMPT)} name(s) exempt")

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed:")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
