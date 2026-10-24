# staged-planning

The `planning` plugin for coding agents. It turns a vague idea into executed work:

- **brainstorming** asks one question at a time until the design holds;
- **architecting-projects** compares researched architecture options;
- **planning-projects** writes a staged plan, and every stage ends in a gate of runnable checks;
- **executing-plans** drives each task Red-Green, runs the gates, and dispatches reviews;
- **honest-gates** keeps a "green" claim tied to a command that really ran.

Around those, `backlog`, `decisions`, `workflow-spec` and `project-maturity` keep each
project's records.

It needs nothing set up. Plans and the other records go to `docs/` in the repo. Keeping
them somewhere else is opt-in, through a records resolver: see
[docs/configuration.md](docs/configuration.md).

## Install

### Claude Code

```bash
claude plugin marketplace add sureserverman/staged-planning
claude plugin install planning@staged-planning
```

On Claude Code 2.1.288 or later the plugin also draws plan progress as a band above
the prompt; its tests are pinned to 2.1.303. Elsewhere, `/planning:statusline` puts the
bar in the status line. Claude Code does not auto-update a third-party marketplace: take a new
release with `claude plugin update planning@staged-planning`.

### Codex

```bash
codex plugin marketplace add sureserverman/staged-planning
codex plugin add planning@staged-planning
```

Codex asks you to review a plugin's hooks before they run: open `/hooks` in Codex and trust
the planning ones. A Codex plugin cannot ship agent roles; `plugins/codex/planning/README.md`
gives the command that copies them into your Codex home.

### Cursor

Cursor has no install command for a local plugin. From a clone of this repository, sync
the build into Cursor's local plugins folder (`--delete` drops files a newer build no longer ships), then reload the
window (or start a new `cursor-agent` session):

```bash
rsync -a --delete plugins/cursor/planning/ ~/.cursor/plugins/local/planning/
```

Then run the `hooks` skill (`/hooks`) in each project you plan in: it checks that the hooks
are wired and installs the proof-record git hook. While a plan is in flight the commit
gate denies git in a repo without that hook. Every hook runs from the plugin's own
`hooks/hooks.json`. Invoke skills by their bare names
(`/executing-plans`, `/backlog`); the progress bar's skill is `/plan-statusline`, because
Cursor ships a built-in `statusline`. The Cursor marketplace does not list the plugin.

### OpenCode

Load `packages/opencode` from a clone of this repository by its path, in the `plugin`
array of your `opencode.json`:

```json
{ "plugin": ["/absolute/path/to/staged-planning/packages/opencode/src/index.ts"] }
```

The package is `opencode-staged-planning`; once it is on npm, `{ "plugin":
["opencode-staged-planning"] }` loads it by name.

The package registers its skills, agents and commands itself. OpenCode does not trigger
a skill reliably from prose, so name the one you want ("use the planning-projects
skill"). If your records live outside the repo, `opencode run` refuses to write there,
and still exits 0, until `opencode.json` allows that folder:

```json
{ "permission": { "external_directory": { "/absolute/path/to/records-home/**": "allow" } } }
```

## Use

Start with `/planning:brainstorming` or just ask for a plan ("plan this", "break this
down"). Run a saved plan with `/planning:executing-plans <plan file>`. The skills hand
off to each other; `core/README.md` describes each one in full.

## Repository layout

- `core/` — the host-neutral skills, agents, hooks and scripts;
- `hosts/<host>/` — what one host adds or overrides;
- `build/build.py` — builds one host's package from those two: `plugins/<host>/planning/`
  for Claude Code, Codex and Cursor, `packages/opencode/` for OpenCode. The output is
  committed, and `build.py --host <host> --check` fails if it is stale;
- `scripts/host-install-check.py --host <host> --isolated` — installs a build into a
  throwaway home and checks what the host loaded;
- `scripts/run-tests.sh` — every suite and repo check, run over the sources.

## License

MIT — see [LICENSE](LICENSE).
