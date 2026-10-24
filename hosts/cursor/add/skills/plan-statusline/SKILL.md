---
name: plan-statusline
description: Wire, check, or remove the plan-execution progress bar in the Cursor CLI status line. Triggers on "install the progress bar", "wire the plan statusline", "is the progress bar set up", "remove the statusline bar".
disable-model-invocation: true
---

# /plan-statusline

Manages the one entry the plan-execution progress bar needs in
`~/.cursor/cli-config.json`.

The bar itself ships with this plugin — `skills/executing-plans/scripts/plan-progress.py`
renders it, and `statusline-chain.sh` chains it after your own status line command. What
it can chain is a plain `bash <script>` invocation: that shape is preserved as the base,
and anything else (a `node` command, a pipeline, a `bash` call with its own arguments) is
refused without `--force` and replaced with `--force`, with the old command echoed to
stderr and kept in the backup. What cannot ship with the plugin is the pointer:
`statusLine` lives in your own CLI config, not in anything a plugin contributes, so
exactly one entry must live there. This skill writes it, so you never hand-edit that
file.

Wiring is **global and one-time** — it applies in every project, not per repo. The bar
prints nothing when no plan is executing.

## Installing costs you the native footer — say so before you run it

A configured `statusLine` **replaces both native Cursor CLI footer rows rather than
adding one**. While the bar is wired, these disappear:

- the model and context readout
- the auto-review state indicator
- the working directory
- the git branch
- the PR indicator

There is no append mode, and the footer cannot be rebuilt from what the CLI hands a
status line command. `remove` restores the native footer.

So **tell the user what installing costs and get their go-ahead before running
`install`** for the first time. A user who asked for a progress bar did not ask to lose
their branch indicator.

## Run

Map the user's request to a subcommand and run it from the plugin root:

| Request | Command |
|---|---|
| install (or none named) | `python3 "skills/executing-plans/scripts/statusline-install.py" --install` |
| status | `python3 "skills/executing-plans/scripts/statusline-install.py" --status` |
| remove | `python3 "skills/executing-plans/scripts/statusline-install.py" --remove` |

Append `--force` only when the user asked for it.

Report the script's own output. These cases need a word of explanation rather than a
bare paste:

- **A non-zero exit naming an existing `statusLine`** means something else is already
  wired there. Show what it points at and ask before re-running with `--force` — do not
  pass `--force` on your own initiative.
- **A refusal on malformed JSON** means the config file could not be parsed. Do not
  offer to repair it by rewriting; say which file failed and let the user look.
- **`Preserved your previous statusline as the base`** means the displaced command was a
  plain `bash <script>`, so it now runs first and the bar is appended under it. A later
  `remove` restores that base rather than clearing the key. The native footer is not a
  command, so nothing can chain it.
- **`your previous statusline was NOT chained in`** means the displaced script runs
  `plan-progress.py` itself, so chaining it would print the bar twice. The install is
  correct; the old script is in the backup and can be deleted once the new line renders.
- **After a successful install**, tell the user the bar appears on the next status line
  redraw and only while a plan is executing — an empty status line is the expected result
  when nothing is running, not a failed install.

## What the bar does not depend on

The Cursor CLI runs the configured command on every conversation update and pipes it a
JSON payload whose field names are not documented. Nothing here reads a field of that
payload by name: the renderer works from the status line process's own working
directory.
