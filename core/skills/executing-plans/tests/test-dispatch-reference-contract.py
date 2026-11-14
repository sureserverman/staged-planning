#!/usr/bin/env python3
"""Structure suite for the dispatch reference — run directly (CI convention):

    python3 core/skills/executing-plans/tests/test-dispatch-reference-contract.py

PROSE contract, not behavior. The dispatch procedure is a reference of executing-plans,
not a skill of its own. What it pins:

  1. Kept in `references/dispatch.md`: the five preconditions; the lone-task rule (a set
     of one is still dispatched); the file and shared-resource guard; the brief template
     with its decisions block, its prove-claim step and its dispatched trailer line; the
     main-session re-run of each green task's test; the trailer check; the merge check.
  2. Gone from it: the common-mistakes table, the when-not-to-use list and any Sources
     heading. The file is at most 12000 bytes.
  3. The trunk's reference map names the file, the trunk is no larger than 57587 bytes,
     and the old skill folder does not exist.

(The old skill's name and the Sources heading are split in the code below: the plan's
gates grep the whole tree for them, tests included.)

Why: a dispatched agent reads only its brief, so a rule cut from the template is a rule
no agent follows; and two owners for one procedure drift apart.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
TRUNK = os.path.join(SKILL_DIR, "SKILL.md")
REF = os.path.join(SKILL_DIR, "references", "dispatch.md")
OLD_SKILL = os.path.join(os.path.dirname(SKILL_DIR), "dispatching-" + "parallel-agents")
MAX_REF_BYTES = 12000
# The ceiling scripts/trunk-budget.txt holds for this trunk, which names what each rise
# pays for: 2.3.0 raised it for the literal prove-claim and plan-state calls.
MAX_TRUNK_BYTES = 57587
# Three hosts ship a whole-file fork of the reference; the host-neutral part of the
# contract binds each. Host facts (how the host spawns, its trailer wording, its notes)
# cost up to 1500 B more. Absent from a built copy of this test.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
FORKS = [os.path.join(REPO, "hosts", h, "overrides", "skills", "executing-plans",
                      "references", "dispatch.md") for h in ("codex", "cursor", "opencode")]
MAX_FORK_BYTES = MAX_REF_BYTES + 1500

FAILED = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f" — {detail}"))
    if not ok:
        FAILED.append(name)


def ws(pattern):
    """Every space may be any whitespace run: the file may be hard-wrapped."""
    return re.sub(r" ", r"\\s+", pattern)


def has(text, pattern):
    return re.search(ws(pattern), text, re.S) is not None


def read(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw, raw.decode("utf-8")


def section(text, heading):
    """The text under a `## ` heading, up to the next `## ` heading outside a code fence."""
    out, inside, fenced = [], False, False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().startswith(heading)
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def check_reference(path=REF, max_bytes=MAX_REF_BYTES, fork=""):
    global check
    plain = check
    if fork:
        def check(name, ok, detail=""):
            plain(f"[{fork}] {name}", ok, detail)
    try:
        _check_reference(path, max_bytes, fork)
    finally:
        check = plain


def _check_reference(path, max_bytes, fork):
    if not os.path.isfile(path):
        check("references/dispatch.md exists", False, f"missing: {path}")
        return
    raw, text = read(path)
    check("references/dispatch.md exists", True)

    pre = section(text, "Preconditions")
    numbered = re.findall(r"(?m)^([1-5])\. \*\*", pre)
    check("five numbered preconditions", numbered == list("12345"),
          f"found items {numbered}")
    for name, pat in [
        ("precondition: a plan exists", r"A plan exists"),
        ("precondition: every task is Dispatch: YES", r"`Dispatch: YES`"),
        ("precondition: Depends on is fully green", r"`Depends on` list is fully green"),
        ("precondition: no two tasks modify the same file", r"No two tasks in scope modify the same file"),
        ("precondition: the stage gate has not run", r"The stage gate has not yet run"),
        ("a failed precondition stops, never relaxed", r"do not relax them"),
        ("the preconditions are the whole check", r"These five preconditions are the whole check"),
    ]:
        check(name, has(pre, pat), "not in § Preconditions")

    check("lone-task rule: |S| = 1 is still dispatched",
          has(text, r"\|S\| = 1") and has(text, r"still dispatched"),
          "the `|S| = 1` rule or its `still dispatched` wording is gone")
    check("file guard: an overlapping task is dispatched on its own afterwards",
          has(text, r"paths overlap") and has(text, r"dispatched on its own after"),
          "the overlap rule is gone")
    check("shared-resource guard", has(text, r"shared resources"),
          "no `shared resources` guard")

    m = re.search(r"```\n(You are a sub-agent executing Task.*?)\n```", text, re.S)
    check("brief template is one fenced block", m is not None, "no template fence found")
    tpl = m.group(1) if m else ""
    # Every fork names its own agent in the trailer line; Cursor alone proves at the gate,
    # not in the task, so its brief has no proof step.
    host_worded = ("trailer line",) + (("prove-claim step", "git add proof/")
                                       if fork == "cursor" else ())
    check("template: an Executor: dispatched trailer line",
          has(tpl, r"`Executor: dispatched — "), "no dispatched trailer in the template")
    for name, pat in [
        ("template: ## What this is for", r"## What this is for"),
        ("template: ## Decisions in force block", r"## Decisions in force"),
        ("template: an Honors entry must appear", r"`Honors DEC-NNN`, that entry MUST appear"),
        ("template: test first, RED for the named reason", r"Write the test FIRST"),
        ("template: nothing wider than the Test", r"Run NOTHING WIDER than the Test"),
        ("template: prove-claim step", r"scripts/prove-claim\.py claim"),
        ("template: git add proof/", r"git add proof/"),
        ("template: Executor: dispatched trailer line", r"`Executor: dispatched — <your subagent_type>`"),
        ("template: wait on background work by its own completion", r"by its own completion"),
        ("template: return only after background work finished or stopped",
         r"returns only after its own background work has finished or been stopped"),
        ("template: STATUS: GREEN | ESCALATE", r"STATUS: GREEN \| ESCALATE"),
    ]:
        if fork and any(w in name for w in host_worded):
            continue
        check(name, has(tpl, pat), "not in the brief template")

    check("main-session re-run of each green task's test",
          has(text, r"Run the task's test \*\*in the main session\*\*"),
          "the main-session re-run rule is gone")
    check("trailer check on every returned commit",
          has(text, r"%\(trailers:key=Executor,valueonly\)") and has(text, r"amend it"),
          "the trailer verification or its amend step is gone")
    merge = section(text, "Merge check")
    check("merge check: the round's own tests together, not the full suite",
          has(merge, r"the round's own tests together") and has(merge, r"Not the full suite"),
          "§ Merge check is missing or lost its bound")
    check("the whole ready set is launched before waiting on any of it",
          has(text, r"single message") or has(text, r"before waiting on any"),
          "the concurrency rule (one message, or all issued before waiting) is gone")
    check("every dispatched agent is collected before integrating",
          has(text, r"Wait for every (dispatched|spawned) agent"), "the collect rule is gone")
    if fork:
        # host.yaml rewrites do not run over an override, so a fork must already speak
        # its host's terms: none of Claude Code's may come back.
        claude_only = ("subagent" + "_type", "Agent tool", "`Agent`", "general-" + "purpose",
                       "capability-index.json", "requires_" + "enablement", "TodoWrite")
        back = [w for w in claude_only if w in text]
        check("no Claude Code term in the fork", not back, f"found: {back}")
    check("an escalated task freezes its dependents",
          has(text, r"Do not dispatch its dependents"), "the escalation rule is gone")

    for gone in ("Common mistakes", "When NOT to use", "Sour" + "ces"):
        check(f"no `{gone}` heading",
              re.search(r"(?m)^#{1,6} +" + re.escape(gone), text) is None,
              "the heading is back")
    check("no frontmatter (a reference, not a skill)", not text.startswith("---"),
          "the file opens with a frontmatter fence")
    check(f"at most {max_bytes} bytes", len(raw) <= max_bytes, f"{len(raw)} bytes")


def check_trunk():
    raw, text = read(TRUNK)
    rmap = section(text, "Reference map")
    check("the trunk's reference map names references/dispatch.md",
          re.search(r"(?m)^\| `references/dispatch\.md` \|", rmap) is not None,
          "no row for `references/dispatch.md` in § Reference map")
    check("the trunk's reference map names references/stack-routing.md",
          "`references/stack-routing.md`" in text,
          "the trunk does not cite the routing table at its new path")
    check(f"the trunk is at most {MAX_TRUNK_BYTES} bytes", len(raw) <= MAX_TRUNK_BYTES,
          f"{len(raw)} bytes")
    check("the old skill folder does not exist", not os.path.exists(OLD_SKILL),
          f"still present: {OLD_SKILL}")
    for rel in ("references/stack-routing.md", "scripts/validate-stack-routing.py"):
        check(f"{rel} sits under this skill", os.path.isfile(os.path.join(SKILL_DIR, rel)),
              "missing")


check_reference()
check_trunk()
for _fork in FORKS:
    if os.path.isdir(os.path.join(REPO, "hosts")):
        check_reference(_fork, MAX_FORK_BYTES, _fork.split(os.sep)[-6])
print()
if FAILED:
    print(f"{len(FAILED)} FAILED: " + "; ".join(FAILED))
    sys.exit(1)
print("all passed")
