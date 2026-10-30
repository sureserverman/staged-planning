---
name: project-maturity
description: >
  Use to scaffold, audit, and read a per-project docs/MATURITY.md checklist tracking ship-readiness across six axes (Documentation, Security, Packaging, UI/UX, i18n, Testing). Triggers: "scaffold maturity", "audit project maturity", "is this ready to publish", "check ship-readiness".
  On OpenCode, invoke this skill by name.
---

> On OpenCode, `<planning-plugin>` is this package's folder: the folder that holds `skills/`, `../..` from the base directory OpenCode prints with this skill. In a shell command use its absolute path, quoted.

# Project Maturity

`MATURITY.md` is a per-project checklist tracking publishing readiness across six axes. Each axis has sub-items; each sub-item carries one of three tick states:

- `[x] auto:<evidence-path>` — auto-detected by a deterministic rule (file exists, regex matches, count above threshold)
- `[x] claim:<YYYY-MM-DD>` — manually claimed by the user on this date (stale once >90 days old; `get` reports it)
- `[N/A] <reason>` — not applicable to this project

## Where the file lives + what gets scanned

The checklist lives in the project's records home, `<records home>/MATURITY.md`. Find the
records home with `python3 <planning-plugin>/lib/records_home.py --project <repo>`
(add `--for-write` before writing):

- **Exit 0 or 3:** use the printed directory. On 3 the records home is the repo's
  `docs/`, so the file is `<repo>/docs/MATURITY.md`; warn once and carry on.
- **Exit 2:** stop and show the message. Create nothing.

The **detectors scan the repo**: README, packaging recipes, locale dirs, CI workflows all
live in `<project-path>` (the repo working tree). So:

- The checklist is read from / written to `<records home>/MATURITY.md`.
- Detector inputs are globbed from `<project-path>`.
- Every auto-tick's evidence path carries the scope prefix `repo:` (e.g.
  `[x] auto:repo:deb/package/DEBIAN/control`), so a checklist kept outside the repo still
  says which tree its evidence lives in. The script returns a `scope` field on each fired
  item; render `auto:<scope>:<evidence>` from it.

Every `docs/MATURITY.md` reference below means `<records home>/MATURITY.md`; detector
paths are `repo:`-relative to `<project-path>`.

**Announce at start:** "Using the project-maturity skill — `<init|audit|get>` on `<records home>/MATURITY.md` (detectors scan `<project-path>`)."

The six axes, the per-axis auto-detect rules, and the ship-ready thresholds are defined in `references/maturity-axes.md`. Read that file before invoking `audit`.

---

## Subcommands

### `init` — scaffold `docs/MATURITY.md` from the template

Inputs: `<project-path>` (absolute, defaults to current working directory).

Refuses to overwrite an existing `docs/MATURITY.md` — caller must delete it or use a different mode.

Writes the following template, with the project name interpolated from the path's final segment:

```markdown
# Project Maturity: <project-name>

This file tracks publishing-readiness across six axes. Each sub-item
carries one of three tick states:

- `[x] auto:<evidence>`     — auto-detected by `project-maturity audit`
- `[x] claim:<YYYY-MM-DD>`  — manually asserted by the maintainer
- `[N/A] <reason>`          — does not apply to this project (rare — preferred is to omit the line entirely)

Per-project MATURITY.md is **sparse**: it only lists items that are auto-detected, manually claimed, or universally applicable basics. Packaging targets you don't ship to (and i18n if you're english-only) are omitted entirely — not listed as `[ ]` or `[N/A]`. Re-run `project-maturity audit` after any change; the audit will ADD newly-detected items as lines and re-evaluate existing ones.

The full catalog of detectable items lives in `references/maturity-axes.md`.

---

## Documentation

- [ ] README at project root
- [ ] LICENSE file

## Security

- [ ] security audit clean (latest stamped security report has 0 CRITICAL + 0 HIGH)

## Packaging

<!-- audit will ADD a line per detected packaging target. To mark a target as PLANNED, add the line manually with `[ ] claim:planned-<date>`. To opt out of a detected target, replace with `[N/A] <reason>`. Android maintainers: Google Play is OPTIONAL — F-Droid, GitHub Releases (signed APK), IzzyOnDroid, Obtainium, and Accrescent are peer channels. Any one satisfies the axis. Use `[N/A] fdroid-only` / `[N/A] sideload-only` / `[N/A] not-distributing-to-play` / `[N/A] private-distribution` if you want to make the Play choice explicit. -->

## UI/UX

- [ ] App icon present

## i18n

<!-- audit will add a line if a non-default locale is detected (Android values-*, browser ext _locales, gettext po/, Flutter .arb). Omit this whole axis with `[N/A] english-only-tool` if you don't intend to translate. -->

## Testing & CI

- [ ] Test suite present
- [ ] CI configured (`.github/workflows/`)

---

## Notes

Free-form context that doesn't fit a checkbox (waivers, planned packaging targets, links to publishing-target tracking issues, why an axis is N/A, etc.).
```

After write, report: `Scaffolded docs/MATURITY.md for <project-name>. Run 'project-maturity audit' to populate auto-ticks and add detected packaging/i18n items.`

### `audit` — re-run auto-detectors and refresh the file

Inputs: `<project-path>` (absolute), optional `--write` (off by default — dry-run shows the diff but doesn't persist).

Operation:

1. Read `docs/MATURITY.md`. If missing, abort with `No MATURITY.md found. Run 'project-maturity init' first.` (Never auto-scaffold during audit — that's the orchestrator's separate concern.)
2. Run the deterministic detector lane and consume its JSON — do **not** re-run
   the detectors by hand:

   ```
   python3 "<planning-plugin>/skills/project-maturity/scripts/audit-detectors.py" \
     <project-path>
   ```

   The script implements every auto-detect rule defined in
   `references/maturity-axes.md` (file-existence, glob, JSON-field,
   and regex checks only — no LLM, no remote calls). It prints one JSON object:

   - **`is_ai_tool`** — the AI-agent-tooling fingerprint (any of
     `.claude-plugin/plugin.json` · `.claude-plugin/marketplace.json`,
     `.mcp.json` at any depth, `.cursorrules` / `.cursor/rules/*.mdc`,
     `AGENTS.md` at any depth / `.codex/config.toml` / `.codex/agents/*.md`,
     `opencode.json` / `.opencode/`, or an `agents/*.md` · `skills/**/SKILL.md` ·
     `commands/*.md` frontmatter bundle with `name:` + `description:`). When
     true, the UI/UX and i18n axes are waived — apply step 3's auto-`[N/A]
     ai-tool` rule.
   - **`detectors`** — per axis (`documentation`, `security`, `packaging`,
     `ui_ux`, `i18n`, `testing`), the list of fired items, each with an evidence
     path. Each fired item becomes an `[x] auto:repo:<evidence>` line in step 3.
   - **`notes`** — informational lines for a detector whose input exists but does
     not satisfy the tick (e.g. a security report with open
     CRITICAL/HIGH). Surface these in the step-5 terminal summary; do not tick.
   - **`errors`** — malformed inputs (unparseable `chrome/manifest.json`, a
     report header that doesn't match the `**Findings:**` regex). Each maps to
     a `[?] stale-detector` annotation in step 3 on the affected item.

   Manual-claim-only items (Google Play, IzzyOnDroid, Obtainium, Accrescent;
   theming / accessibility; CI-green / coverage) are intentionally NOT emitted by
   the script — they have no local file signal. See
   `references/maturity-axes.md` for the full per-item rationale and
   the sanctioned Android `[N/A]` reasons (`fdroid-only`, `sideload-only`,
   `not-distributing-to-play`, `private-distribution`).

3. Compute the diff between existing state and detector results. The audit can:
   - **Tick an existing `[ ]` line** → flip to `[x] auto:<evidence>`.
   - **ADD a new line** for a detector that fired but has no matching line in the file yet (this is the primary behavior for the Packaging and i18n axes — those start empty and grow). Add the new line at the bottom of its axis section, preserving the section's existing lines.
   - **Update an existing `[x] auto:<old>`** to a different evidence path → apply (file moved/renamed).
   - **Mark `[?] stale-detector`** if a previously-`[x] auto:` line's evidence has disappeared. Never silently un-tick.
   - **Append `[?] stale-detector: <error>`** inline if the detector errored (malformed JSON, unreadable file). Never silently fail.
   - **NEVER overwrite `[x] claim:<date>` lines.** If a manual claim is >90 days old, prepend an inline `[STALE-90D]` marker; `get` counts it in `stale_count`.
   - **NEVER add a line for a detector that didn't fire.** Items that don't apply stay out of the file (no `[N/A]` line written by audit). The user adds `[N/A]` manually only if they want to be explicit about an opt-out (e.g. `[N/A] english-only-tool` for the i18n axis).
   - **AI-agent tooling waiver — the one exception to the step-3 rule.** When the step-2 `is_ai_tool` flag is true, the audit DOES write `[N/A] ai-tool` for the **UI/UX** and **i18n** axes, but only when the axis is not already satisfied by a real signal: i.e. the icon detector did not fire / no locale fired AND the maintainer has not set their own `[x]` or `[N/A]` on that axis. Concretely: convert a bare `[ ] App icon present` to `[N/A] ai-tool`; if the UI/UX or i18n axis is empty, add an `[N/A] ai-tool` line. NEVER overwrite a real `[x] auto:`/`[x] claim:` icon tick or a user's existing `[N/A] <reason>` — a maintainer who ships a GUI keeps their icon tick and the waiver does not apply. (Packaging is NOT waived: AI-agent projects tick it via the Claude-plugin / marketplace / MCP / Cursor / Codex / OpenCode detectors for that axis.)

4. If `--write`, persist the new file (preserving every comment, blank line, and the `## Notes` section byte-for-byte). Otherwise, print a unified-diff-style preview including the new lines that would be added.

5. Report a one-line summary per axis showing `<ticked>/<total-in-file>` (the denominator is the number of lines actually present in that axis section, not a hypothetical max): `Documentation: 2/2 ✓ | Security: 1/1 ✓ | Packaging: 1/1 ✓ | UI/UX: 1/1 ✓ | i18n: 1/1 ✓ | Testing: 2/2 ✓`.

### `get` — emit machine-readable state for a caller

Inputs: `<project-path>` (absolute), optional `--format json|yaml` (default `json`).

Run the script and reply with its stdout verbatim in a fenced block: the caller reads that output, so no table or summary takes its place. Never parse the file by hand:

```
python3 "<planning-plugin>/skills/project-maturity/scripts/maturity-get.py" \
  <project-path> [--format yaml]
```

It reads `<records home>/MATURITY.md`, resolved through `lib/records_home.py`. Exit 0 prints JSON in the output shape. Exit 2: no `MATURITY.md` (stdout `{"error": "no-maturity-md", "path": "<records home>/MATURITY.md"}`; a caller treats it as "not tracked yet"), the records resolver failed, or a bad path or `--today` (stderr; create nothing).

Its contract:

- Item: `label` (text after the checkbox), `state` (`auto` | `claim` | `na` | `unticked` | `stale-detector`), `evidence` (path/date/reason after the prefix, or `null`), `stale` (a claim >90 days old).
- Axis: `ticked` = `auto` + `claim` lines; `total` = lines present minus `[N/A]`; `axis_ship_ready` iff every counted line is ticked or the axis is empty/N/A-only; `stale_count` = `[STALE-90D]` markers.
- `ship_ready` iff every axis is ship-ready, no `[?] stale-detector` is anywhere in the file, and `errors` is empty.
- `errors` lists each malformed line (bare `[N/A]`, `[x]` without `auto:`/`claim:`, a bad claim date) and each missing or repeated axis heading, with axis, line and reason. Such a line is never classified; its axis is not ship-ready. Report it; do not guess.
- The per-axis minimums in `references/maturity-axes.md` are not checked.

Output shape (`axes` holds `documentation`, `security`, `packaging`, `ui_ux`, `i18n`, `testing`):

```json
{
  "project": "<final path segment>", "path": "<absolute project path>",
  "file": "<absolute MATURITY.md path>", "audited": "<YYYY-MM-DD the file was last written>",
  "axes": {
    "ui_ux": { "ticked": 1, "total": 3, "axis_ship_ready": false, "stale_count": 0, "items": [...] },
    ...
  },
  "ship_ready": false,
  "errors": []
}
```

YAML output uses the same shape.

---

## Hard rules

- `init` never overwrites an existing MATURITY.md.
- `audit` never overwrites a `[x] claim:` line — only `[ ]`, `[x] auto:`, and `[?] stale-detector` lines are subject to detector updates.
- `audit` never silently un-ticks. Disappeared evidence becomes `[?] stale-detector previously had: <old>`.
- Detectors are pure file-system / regex checks executed by `scripts/audit-detectors.py` — no LLM in the detection loop, no remote calls, no package-index queries. The skill's own judgement is confined to the diff/merge, the AI-tool waiver and stale-detector marking; ship-ready aggregation runs in `scripts/maturity-get.py`.
- The file is human-edited. Preserve formatting (blank lines, comments, the `## Notes` free-form section) byte-for-byte when writing.

## Integration

- **A cross-project plugin, if one is installed**, may call `get` across projects to roll the checklists up, and `init` when a project is opted in.
- **Ad-hoc** — invoke directly on a single project to scaffold or refresh.
- Detector rules and per-axis definitions live in `references/maturity-axes.md` — that is the source of truth; `scripts/audit-detectors.py` implements them and this skill consumes its JSON.

## Remember

- `init` scaffolds, `audit` refreshes, `get` reports.
- Three tick states: `auto`, `claim`, `na`. `audit` writes `auto` — and, only for AI-agent tooling projects (`is_ai_tool`), `[N/A] ai-tool` on the waived UI/UX + i18n axes.
- Detectors fail loudly (`[?] stale-detector`), never silently.
- Manual claims go stale after 90 days; `get` reports them (`stale`, `stale_count`).
