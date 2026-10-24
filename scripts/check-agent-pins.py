#!/usr/bin/env python3
"""Every shipped agent carries a deliberate `model:` and `effort:` pin.

An invariant that exists only as a one-shot gate command in a plan decays the
moment one more agent is added, with no signal, so it is a validator here, as
this repo's other invariants are.

What it checks, and why each one:

  MISSING-EFFORT  an agent with no `effort:`. It then inherits the session level,
                  so a dispatch's cost is whatever the operator happened to be
                  running at — the unpredictability a pin removes.
  MISSING-MODEL   an agent with no `model:`. Same argument, the other knob.
  BAD-VALUE       a value outside the documented vocabulary. The field takes
                  `low | medium | high | xhigh | max`; a typo silently falls back
                  to inherited rather than erroring, so this cannot be left to the
                  loader.
  HIGH-PIN        `high`, `xhigh` or `max`. NOT a syntax error — a POLICY finding,
                  and the distinction is the point. The rule is that
                  dispatch-heavy verification is already tier-gated by the review
                  tier and "an agent that needs more than `medium` is a signal to revisit
                  its scope". A future author who genuinely needs `xhigh` should
                  reach a check that says so and can be argued with, rather than a
                  regex that cannot express the value at all — a sweep such as
                  `^effort: *\\(low\\|medium\\|high\\)$` fails a correct `xhigh`
                  pin as though it were malformed.

  HOST-PIN        a `model:` or `effort:` in an agent of a host whose agent files take
                  neither field (Cursor: name, description, readonly; OpenCode: the
                  session's model, by agent file). There the rule is the inverse: no
                  pin, because a pin is either ignored or names a model the host lacks.

Read-only. Exit 0 when every agent is pinned within policy, 1 otherwise.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _layout import GENERATED  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The documented vocabulary (code.claude.com/docs/en/sub-agents.md § Supported
# frontmatter fields). Kept whole rather than trimmed to what policy allows, so
# BAD-VALUE and HIGH-PIN stay distinguishable.
VALID_EFFORT = ("low", "medium", "high", "xhigh", "max")
POLICY_MAX = ("low", "medium")
VALID_MODEL = ("haiku", "sonnet", "opus", "fable", "inherit")

EFFORT_RE = re.compile(r"^effort:[ \t]*(\S+)[ \t]*$", re.M)
MODEL_RE = re.compile(r"^model:[ \t]*(\S+)[ \t]*$", re.M)


def agent_files(root):
    """Every shipped agent: `*/agents/*.md`, excluding READMEs and test data.

    The same population a gate sweep over `*/agents/*.md` reads, so the
    validator and such a gate cannot disagree about what "all of them" means.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", "tests", "fixtures",
                                    "test-fixtures", "__pycache__")
                       # Generated copies: their agents are swept at the source.
                       and not (dirpath == root and d in GENERATED)]
        if os.path.basename(dirpath) != "agents":
            continue
        for name in sorted(filenames):
            if name.endswith(".md") and name != "README.md":
                out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


def frontmatter(text):
    """The YAML frontmatter block, or "" when the file has none."""
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else ""


# Hosts whose agent files take no model or effort field.
UNPINNED_HOSTS = ("cursor", "opencode")


def check_file(root, rel):
    problems = []
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        fm = frontmatter(fh.read())
    if not fm:
        return [f"{rel}: NO-FRONTMATTER — cannot carry a pin"]
    parts = rel.split(os.sep)
    if len(parts) > 2 and parts[0] == "hosts" and parts[1] in UNPINNED_HOSTS:
        if MODEL_RE.search(fm) or EFFORT_RE.search(fm):
            problems.append(f"{rel}: HOST-PIN — {parts[1]} agent files take no `model:` or "
                            "`effort:`; remove the pin")
        return problems

    m = MODEL_RE.search(fm)
    if not m:
        problems.append(f"{rel}: MISSING-MODEL — no `model:` pin, so the model is "
                        "whatever the session inherits")
    elif m.group(1) not in VALID_MODEL and not m.group(1).startswith("claude-"):
        problems.append(f"{rel}: BAD-VALUE — model {m.group(1)!r} is not one of "
                        f"{VALID_MODEL} or a full model id")

    e = EFFORT_RE.search(fm)
    if not e:
        problems.append(f"{rel}: MISSING-EFFORT — no `effort:` pin, so the dispatch "
                        "costs whatever the session happens to be set to")
    elif e.group(1) not in VALID_EFFORT:
        problems.append(f"{rel}: BAD-VALUE — effort {e.group(1)!r} is not one of "
                        f"{VALID_EFFORT}; a typo falls back to inherited silently")
    elif e.group(1) not in POLICY_MAX:
        problems.append(
            f"{rel}: HIGH-PIN — effort {e.group(1)!r} exceeds the marketplace policy "
            f"ceiling {POLICY_MAX}. Dispatch-heavy verification is tier-gated by "
            "the review tier, and an agent needing more than `medium` is a signal to revisit "
            "its scope. If the pin is right, raise POLICY_MAX here with the reason.")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check-agent-pins")
    ap.add_argument("--root", default=REPO_ROOT)
    args = ap.parse_args(argv)

    files = agent_files(args.root)
    problems = []
    for rel in files:
        problems += check_file(args.root, rel)

    # honest-gates: name the population swept, so a run that found no agents at all
    # cannot read as a pass over all of them.
    print(f"{len(files)} agent(s) swept; {len(problems)} problem(s).")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
