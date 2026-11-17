# Dry run — what a planner runs before a plan is presented

A Standard plan and a sub-plan are tried before the owner sees them. Each carries a
`## Preflight` section; a Light plan and a master plan carry none and owe no dry run.

## What is run

- **Each Preflight check that only reads** — a version, a tag, a file, a probe that changes
  nothing.
- **Each `Test:` and gate command, probed without running a suite.** A pytest selector:
  `pytest --collect-only -q <selector>`. Any other command: its program resolves
  (`command -v <program>`, or the script's path exists), and each path it names exists or
  is created by a named task.
- **Each stage premise** — for a stage whose Risk is HIGH, or whose Goal or Outcomes rely on
  something the code does not control: that premise, on the real environment, with one or
  two commands.

## What is never run

- A command that changes state outside a scratch folder: a branch switch, a push, an
  install, a migration, a deploy.
- A suite that takes over about 5 minutes.

Each is recorded as not run, with the reason.

## What a result changes

A check that fails, a command that cannot start, and a premise that is false each become a
change to the plan, or a question in the owner's batched round (`owner-decisions.md`).

## The record

In `## Preflight`, after the test-scope commands:

```
**Dry run** (<date>, at <short sha> on `<branch>`):
- Preflight: <n> of <m> checks run now; what came back. Not run: <check> (<why>).
- Commands: what each Test: and gate command's probe returned; a command that could not start, and what changed.
- Premises: Stage <N> — <the assumption> — `<command>` returned <what> — holds | false | not checkable here — <why>.
```

`python3 scripts/validate-gate-checks.py --authoring <plan>` reads it and reports
`DRY-RUN-MISSING` when the block is not in `## Preflight`, when one of its `Preflight:`,
`Commands:` or `Premises:` lines is missing, or when a stage whose `**Risk:**` starts with
HIGH is not named by `Premises:`. Execution never passes the flag, so a plan written before
2.4.0 needs no block.
