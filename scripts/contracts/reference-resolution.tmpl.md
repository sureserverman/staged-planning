## Reference resolution — check the path, not the variable

`${CLAUDE_PLUGIN_ROOT}` being *set* is not the same as a reference being *there*: a
partially-installed or superseded plugin cache resolves to a directory that exists with the
file missing, and an unset-only test reads that as success. **Confirm each resolved
reference exists before relying on it.** If one does not — or the variable is unset — fall
back in this order, and say which one you used:

1. the **versioned plugin cache** — `Glob` with `path` set to the plugin cache root
   (`~/.claude/plugins/cache/`, or `$CLAUDE_CONFIG_DIR/plugins/cache/` when that is set)
   and pattern `**/{PLUGIN}/*/<the reference path that follows ${CLAUDE_PLUGIN_ROOT}/>`
2. a **dev checkout** — `Glob` pattern `**/{PLUGIN}/<that same path>`, searched from the
   working directory

Arm 1 needs its explicit `path` because `Glob` is rooted at the working directory, and you
are dispatched into the repo under review — which is usually not this plugin's checkout, and
never contains the cache. A rootless arm 1 silently matches nothing everywhere it matters,
which is the failure the next paragraph names.

Keep that suffix exactly as the reference is written in this file rather than guessing a
shape.{DEPTH_NOTE}
A fallback that silently matches nothing is worse than none: it reports a healthy reference
as unreadable and sends the run into the banner below for no reason.

The order is not cosmetic — the cache is what the operator is actually running, so a
checkout preferred over it would ground the work in rules that are not in force.

**Open with `DEGRADED {NOUN} — <references that could not be read>` as the FIRST LINE of
your output whenever any named reference went unread.** Not a closing caveat: a degraded run
and a complete one are otherwise identical in shape, so the disclosure has to arrive before
the content, not after it.
