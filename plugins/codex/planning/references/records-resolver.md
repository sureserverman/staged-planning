# The records-resolver hook

planning keeps each project's records (plans, design and architecture docs, the
backlog, the decision register and the maturity checklist) in one folder per project,
called the **records home**. By default that folder is `<repo>/docs/`. A records
resolver is an optional external command that moves it somewhere else: a notes folder,
a shared drive, a folder per client. planning never knows what the other place is.

Every skill and script asks one entry point, and only that one:

```bash
python3 <plugin>/lib/records_home.py --project <abs repo> [--for-write]
python3 <plugin>/lib/records_home.py --project <abs repo> --decision-registers
```

## Configuration

The config file is found in this order; the first that is set wins:

1. `$STAGED_PLANNING_CONFIG`. A blank value counts as unset. A value naming a file that
   does not exist is exit 2: a named config is a configured one, so it never falls back.
2. `$XDG_CONFIG_HOME/staged-planning/config.yaml`. `XDG_CONFIG_HOME` defaults to
   `~/.config`, and a relative value is ignored, as the XDG spec requires.

Its resolver key is `records_resolver:`, a YAML list of argv strings. Each string has
`~` expanded. No shell is involved.

```yaml
records_resolver: [python3, ~/tools/my-resolver.py]
```

With no config file, or no `records_resolver:` key, there is no resolver.

### Other keys

The same file holds settings other skills read through `config_value(key)` in
`records_home.py`. It returns `(value, message)`: the key's parsed YAML value, or `None`
with an empty message when there is no config or no such key. A config that cannot be
read (the cases under **Edge cases**) gives `None` and a message saying why; the caller
notes it and goes on without the setting. It never runs the resolver, never raises, and
leaves the shape of the value to the caller. Reading another key never changes how the
records home is resolved.

- `security_report_prefixes:` a list of file-name prefixes, each coming straight before
  `<YYYYMMDD>-<HHMM>.md`, that the project-maturity audit also reads as security reports,
  for a tool that does not write `<prefix>security-audit-report-<stamp>.md` or
  `<prefix>security-report-<stamp>.md`. Example: `security_report_prefixes: [acme-scan-]`.

## The call

`records_home.py` runs `<argv…> --project <abs repo>`, adding `--for-write` when the caller
is about to write, with a 10 second timeout. It then maps the result.

### Exit 0

The resolver printed exactly one line, an absolute directory: that is the records home.
`records_home.py` prints it and exits 0. With `--for-write`, the directory must exist when
the resolver returns; if it does not, the result is exit 2.

### Exit 3

The project is not managed. This is what happens with no resolver configured, and what a
resolver returns for a project it does not handle. `records_home.py` prints `<repo>/docs`
and exits 3. The caller uses that folder and warns once that records go to the repo.

### Exit 2

The resolver is configured but cannot reach its storage, for example an unmounted disk.
`records_home.py` exits 2 and passes on the resolver's message. The caller stops, shows the
message and creates nothing. A missing store is not an empty one, and creating folders
there would build a tree in the wrong place.

### Anything else

Any other exit code, a run longer than 10 seconds, or stdout that is not exactly one
absolute path is treated as exit 2, with the resolver's stderr passed on. A resolver that
answers in a shape `records_home.py` does not parse is refused, never guessed at.

### Edge cases

A config that exists but cannot be read honestly is a configured one, so it is exit 2,
never the `<repo>/docs` fallback. The same holds for `--decision-registers`.

- **Malformed config file:** YAML that does not parse, a top level that is not a
  mapping, a file that exists but cannot be read, or PyYAML missing while a config file
  exists. Each is exit 2, naming the file.
- **`records_resolver:` that is not a list of strings:** a string, a mapping, a null
  value, an empty list, or a list holding a non-string or an empty string. Each is
  exit 2. An empty config file, or one without the key, is still no resolver (exit 3).
- **Relative `--project`:** a usage error, exit 2, checked before any config is read.
  A missing `--project`, or `--for-write` together with `--decision-registers`, is
  also a usage error, exit 2.
- **A resolver that cannot be started** (no such program, not executable) is exit 2.
- **A line padded with spaces** is not trimmed. It counts as bad stdout, exit 2.
- **Control characters:** a line holding any of `\x00`–`\x1f` or `\x7f` is bad stdout,
  exit 2. Only the single newline that ends each line is allowed, so a CR (CRLF line
  ends), a tab or a NUL is refused.
- **Encoding:** after an exit 0 the resolver's stdout must be valid UTF-8, or the result
  is exit 2. After an exit 3 its stdout is ignored, whatever it holds, and the result is
  still exit 3. Its stderr is passed on with bytes that are not UTF-8 replaced, and never
  changes the exit code. `records_home.py` writes its answer as UTF-8 bytes whatever the
  locale, and a repo path that is not UTF-8 comes back byte for byte.
- **A records home that exists but is not a directory** (a file, say) is exit 2, on a
  read as well as with `--for-write`. A home that does not exist yet is allowed on a
  read, because the resolver creates it when `--for-write` is passed.
- **A relative `$STAGED_PLANNING_CONFIG`** is exit 2 ("must be an absolute path"),
  checked after the blank-counts-as-unset rule and after `~` expansion, so
  `~/my.yaml` is allowed. A relative value would name a config held by whatever
  project the caller happens to stand in.
- **A relative path in `records_resolver:`**: any element that, after `~` expansion,
  holds a `/` but is not absolute is exit 2, for the same reason: `tools/r.sh` would
  run a script the current project holds. A bare command name with no `/`, such as
  `python3`, is allowed and found on `PATH`. The resolver always runs with `/` as its
  working directory, so nothing it does resolves against the caller's.
- **A `config.yaml` that is a directory or a dangling symlink** counts as no config
  file (exit 3).
- **`~` is expanded in every argv element** of `records_resolver:`, not only the first.
- **An unreadable `~/.config`** hides whether a config is there, so it counts as no
  config file (exit 3). A config file that is visible but unreadable is exit 2.

## Layout of a records home

The same names are used wherever the home is, including the default `<repo>/docs/`:

| Path | What |
|---|---|
| `plans/` | plans, design docs and architecture docs |
| `backlog.md` | the deferred-work register |
| `decisions.md` | the decision register |
| `MATURITY.md` | the ship-readiness checklist |

## `--for-write`

Without the flag the resolver must be read-only. With it, the resolver may create the
home, register the project in whatever it keeps, and refresh anything it maintains
alongside. planning passes it only just before it writes a record.

## `--decision-registers`

```bash
python3 <plugin>/lib/records_home.py --project <abs repo> --decision-registers
```

This asks the resolver for further decision registers that bind the project, beyond the
project's own `decisions.md`, for example registers shared by every project on one stack.
`records_home.py` runs `<argv…> --project <abs repo> --decision-registers`.

- The resolver prints zero or more absolute file paths, one per line, and exits 0.
- It exits 3 when there are none. With no resolver configured, `records_home.py` prints
  nothing and exits 3.
- A relative path or any other line makes the result exit 2. A resolver exit 2, a
  timeout or any other exit code maps to 2, as in the main call.

The decisions scan reads the project's own register first, then each listed register in
order.

## Writing a resolver

A resolver is any program that honours the arguments and exit codes in **The call**:

- `--project <abs repo>` is always passed; `--for-write` and `--decision-registers` are
  optional and never passed together.
- Print the records home as one absolute path on stdout and exit 0, or exit 3 for a
  project you do not manage, or exit 2 with a message on stderr when your storage is
  unreachable.
- Stay read-only unless `--for-write` is given.
- Answer within 10 seconds.
