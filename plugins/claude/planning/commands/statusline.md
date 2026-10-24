---
description: Wire, check, or remove the plan-execution progress bar in the Claude Code status line. Triggers on "install the progress bar", "wire the plan statusline", "is the progress bar set up", "remove the statusline bar".
argument-hint: "[install|status|remove] [--force]"
allowed-tools: ["Bash(python3:*)"]
model: inherit
---

# /planning:statusline

Manages the one line of wiring the plan-execution progress bar needs in
`~/.claude/settings.json`.

The bar itself ships with this plugin — `skills/executing-plans/scripts/plan-progress.py`
renders it, and `statusline-chain.sh` chains it after your own status line. What it can
chain is a plain `bash <script>` invocation: that shape is preserved as the base, and
anything else (a `node`/`deno` command, a pipeline, a `bash` call with its own arguments)
is refused without `--force` and replaced with `--force`, with the old command echoed to
stderr and kept in the backup. What cannot ship with the plugin is the pointer:
`statusLine` is not a plugin
contribution point (a plugin's `settings.json` supports only `agent` and
`subagentStatusLine`), so exactly one entry must live in your global settings. This
command is what writes it, so you never hand-edit that file.

Wiring is **global and one-time** — it applies in every project, not per repo. The bar
prints nothing when no plan is executing.

**On Claude Code 2.1.288 or later this command is optional.** The planning plugin's mod
draws the same plans, counts and phase text as a band above the prompt (and `/plan-view` opens the full plan in a
pane), with no settings entry at all. The status-line bar remains for older builds and
other hosts. When both are present the bars show twice; if your user settings run
`statusline-chain.sh`, the mod says so once per session, and `remove` takes the
status-line copy out.

## Run

The user invoked this with: `$ARGUMENTS`

Map the argument to a subcommand and run it, from the plugin root:

| Argument | Command |
|---|---|
| `install` (or empty) | `python3 "${CLAUDE_PLUGIN_ROOT}/skills/executing-plans/scripts/statusline-install.py" --install` |
| `status` | `python3 "${CLAUDE_PLUGIN_ROOT}/skills/executing-plans/scripts/statusline-install.py" --status` |
| `remove` | `python3 "${CLAUDE_PLUGIN_ROOT}/skills/executing-plans/scripts/statusline-install.py" --remove` |

Append `--force` when the user passed it.

Report the script's own output. These cases need a word of explanation rather than
a bare paste:

- **A non-zero exit naming an existing `statusLine`** means something else is already
  wired there. Show what it points at and ask before re-running with `--force` — do not
  pass `--force` on your own initiative.
- **A refusal on malformed JSON** means the settings file could not be parsed. Do not
  offer to repair it by rewriting; say which file failed and let the user look.
- **`Preserved your previous statusline as the base`** means the displaced command was a
  plain `bash <script>`, so it now runs first and the bar is appended under it. A later
  `remove` restores that base rather than clearing the key.
- **`your previous statusline was NOT chained in`** means the displaced script runs
  `plan-progress.py` itself, so chaining it would print the bar twice. The install is
  correct; the old script is in the backup and can be deleted once the new line renders.
- **After a successful install**, tell the user the bar appears on the next status line
  redraw and only while a plan is executing — an empty status line is the expected
  result when nothing is running, not a failed install.

## Replacing a hand-written wrapper

A bar wired by hand is a wrapper script that calls `plan-progress.py` on a hard-coded path.
Do **not** replace it with `--install --force`: that wrapper is a `bash <script>`
invocation, so it would be chained in as the base and the bar would render twice.

The installer detects this specific case and refuses to chain it, so `--force` is safe —
but the clean sequence, which needs the user's approval because it passes `--force`, is:

1. `--remove --force` — clears the old entry (it is not this tool's, hence `--force`)
2. `--install` — writes the pointer with no base prefix
3. delete the wrapper once the status line renders correctly

Verify afterwards that the written command contains no `PLAN_STATUSLINE_BASE` pointing at
the old wrapper.
