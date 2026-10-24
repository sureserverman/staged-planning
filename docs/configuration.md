# Configuration

planning works with no configuration at all. Plans, design and architecture docs, the
backlog, the decision register and the maturity checklist then live in the repo, under
`docs/`. Everything on this page is opt-in.

## The default: records in the repo

With no config file, or a config without `records_resolver:`, a project's **records home**
is `<repo>/docs/`. The skills warn once that records go to the repo and carry on.

## Moving records elsewhere: a records resolver

A **records resolver** is an external command that tells planning where a project's
records home is: a notes folder, a shared drive, a folder per client. planning never
knows what the other place is. The full contract (arguments, exit codes, timeout,
`--for-write`, `--decision-registers`, edge cases) is
[records-resolver.md](records-resolver.md).

Set it in the config file:

```yaml
records_resolver: [python3, ~/tools/my-resolver.py]
```

The value is a non-empty list of argv strings; anything else stops the skills (exit 2).
`~` is expanded in each element. An element that contains `/` must then be an absolute
path (exit 2 otherwise); an element without `/` is passed as written, and the first one,
the command, is looked up on `PATH`. Reading a config file needs PyYAML; without it the
skills stop (exit 2) rather than guess.

## Where the config file is found

The first that is set wins:

1. `$STAGED_PLANNING_CONFIG` — surrounding whitespace is stripped, and a blank value counts
   as unset. It must be an absolute path (`~` allowed); a relative one stops the skills
   (exit 2). A value naming a file that does not exist stops the
   skills (exit 2): a named config is a configured one, so it never falls back to the repo.
2. `$XDG_CONFIG_HOME/staged-planning/config.yaml` — `XDG_CONFIG_HOME` defaults to
   `~/.config`, and a relative value is ignored, as the XDG spec requires.

To see where a project's records go:

```bash
python3 <plugin>/lib/records_home.py --project <repo>
# prints the records home; exit 0 = a resolver's home, 3 = the repo's docs/, 2 = unreachable
```

## Environment variables

| Variable | Effect |
|---|---|
| `STAGED_PLANNING_CONFIG` | The config file to read (level 1 above). |
| `XDG_CONFIG_HOME` | Base of the default config location (default `~/.config`). |
| `STAGED_PLANNING_CHECKOUT` | A checkout of this plugin's repository. When set, a script running from an older cached copy of the plugin prints one warning line. |
| `STAGED_PLANNING_NO_STALE_WARNING` | Set to `1` to silence that warning. |
