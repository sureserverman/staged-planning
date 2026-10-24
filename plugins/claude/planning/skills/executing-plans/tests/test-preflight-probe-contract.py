#!/usr/bin/env python3
"""Structure suite for the Preflight gate-selector probe — run directly:

    python3 core/skills/executing-plans/tests/test-preflight-probe-contract.py

PROSE contract, not behavior, with the shared negation screening. The
authoring half (validate-gate-checks.py SELECTOR-UNMATCHED) reads pytest, Gradle and
cargo selectors; the runtime half — preflight-checks.md § Gate-selector probe — must
settle all three, or a flagged Gradle or cargo selector has nowhere to be settled. It pins:

  1. cargo: a gate's `cargo test <filter>` is probed with `-- --list` and must list a test.
  2. Gradle: `--tests '<pattern>'` must match a test class or method name under the
     project's test source sets, by a source search (Gradle has no cheap listing).
  3. A zero result is a Preflight plan defect for every runner — never advisory.
  4. pytest is probed with `pytest --collect-only -q <the check's selector>`.
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PREFLIGHT = os.path.join(os.path.dirname(HERE), "references", "preflight-checks.md")
HELPER = os.path.join(HERE, "test-gate-remediation-contract.py")

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


def main():
    with open(PREFLIGHT, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^## Gate-selector probe", text, re.M)
    sec = ""
    if m:
        nxt = re.search(r"^## ", text[m.end():], re.M)
        sec = text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]
    check("preflight: § Gate-selector probe located", bool(sec))

    check("probe: pytest is probed with `--collect-only -q`",
          "pytest --collect-only -q <the check's selector>" in sec,
          "the pytest probe command is missing")
    check("probe: cargo is probed with `-- --list` and must list a test",
          "`cargo test <filter> -- --list`" in sec
          and affirms_claim(sec, ws(r"must list at least one test")),
          "cargo is absent, or its probe is not `-- --list`")
    check("probe: Gradle is probed by a source-set match",
          "`--tests '<pattern>'`" in sec
          and affirms_claim(sec, ws(r"must match a test class or method name under the project's test source sets")),
          "Gradle is absent, or its probe is not a source-set match")
    check("probe: a zero result is a Preflight plan defect for every runner",
          affirms_claim(sec, ws(r"A zero result is a plan defect at Preflight for every runner")),
          "a non-pytest runner's zero result could be advisory")

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
