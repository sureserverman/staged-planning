# Maturity Axes Reference

This document is the authoritative definition for the six maturity axes used by
the `project-maturity` skill. It specifies exactly how each axis is
auto-detected, when a manual claim is appropriate, when N/A is valid, and what
the minimum state is for a reader to count that axis as green (`project-maturity get`
does not check it; see § ship_ready aggregation). Every auto-detect rule in this file runs in `../scripts/audit-detectors.py`, with no LLM
judgement; the skill itself applies the AI-tool waiver and stale-detector marking,
and `../scripts/maturity-get.py` computes the ship-ready aggregation.

## Sparse-file principle

Per-project `docs/MATURITY.md` is **sparse**. It lists only items that are
either auto-detected, manually claimed, or universal-basic-applicable
(README, LICENSE, app icon, test suite, CI). The full catalog of detectable
items lives in this reference doc — but a per-project file never contains
the full catalog. A packaging target that doesn't apply (e.g. AUR for a
browser extension) is simply absent from the file — not listed as `[ ]`
or `[N/A]`. This prevents the per-axis denominator from being a fictitious
"could ship to 10 stores".

`audit` ADDS lines for newly-detected items; it never adds a line for a
detector that didn't fire. The user adds `[N/A]` lines manually only when
they want to be explicit about an opt-out (e.g. `[N/A] english-only-tool`
on the i18n axis).

## Tick-state syntax

Every sub-item in a `docs/MATURITY.md` checklist uses exactly one of three
syntaxes. No other forms are valid.

**Auto-detected (deterministic):**

```
[x] auto:<evidence-path>
```

The tool found the required file or pattern. `<evidence-path>` is the
relative path from the project root (or a comma-separated list of paths) that
satisfied the rule. Written by `project-maturity audit`; never written by
hand. Because the evidence is embedded, reviewers can verify the tick without
re-running the tool.

The evidence path carries a **scope prefix** naming the tree it resolves against:

```
[x] auto:repo:<path>         relative to the project working tree
```

The detectors scan the repo only, so `repo` is the one scope this plugin writes. The
prefix is kept so a checklist kept outside the repo still says which tree its evidence
lives in.

**Manual claim:**

```
[x] claim:<YYYY-MM-DD>
```

The user has verified a condition that cannot be auto-detected. The date is
when the claim was made. Claims older than 90 days are reported as stale by `project-maturity get`, to
prompt a re-check.
The user is responsible for updating the date when they re-verify.

**Not applicable:**

```
[N/A] <reason>
```

This axis or sub-item does not apply to this project. A reason string is
mandatory — a bare `[N/A]` is treated as a parse error by `project-maturity
audit`. The reason should be terse but unambiguous, e.g.
`no-attack-surface`, `english-only-tool`, `not-distributed`.

## ship_ready aggregation

`project-maturity get` (`../scripts/maturity-get.py`) reports `ship_ready: true` if and
only if **every counted line in the file is ticked** (`[x] auto:` or `[x] claim:`; an
empty or `[N/A]`-only axis is ready by vacuity), no `[?] stale-detector` marker is
anywhere in the file, and no line is malformed. It does **not** check the per-axis
minimums below: they are what a reader of the file holds each axis to, and a file
that falls short of one can still read `ship_ready: true`.

Per-axis minimums in the sparse model:

- **Documentation** — must contain a `[x]` for README AND for LICENSE. The
  other two basics (CHANGELOG, CONTRIBUTING) are optional; the audit doesn't
  add lines for them unless detected, and the user can manually omit them.
- **Security** — must contain a `[x]` for security-audit clean (auto or manual
  claim acceptable). If the project has no attack surface, the user can
  explicitly add `[N/A] no-attack-surface` and that satisfies the axis.
- **Packaging** — must contain at least one `[x]` line OR an explicit
  `[N/A] not-distributed`. An entirely empty Packaging section satisfies
  the axis IFF the `[N/A] not-distributed` line is present in the section.
- **UI/UX** — must contain a `[x]` for icon (or `[N/A] headless-cli`).
  Theming and accessibility lines are optional (user adds via manual claim
  when verified). **Waived for AI-agent tooling projects** — see the
  project-type section below; the axis is auto-`[N/A] ai-tool`.
- **i18n** — must contain at least one `[x]` line (a detected locale set)
  OR `[N/A] english-only-tool`. **Waived for AI-agent tooling projects** —
  auto-`[N/A] ai-tool`.
- **Testing & CI** — must contain `[x]` for both "test suite present" AND
  "CI configured" (auto-detected; user can `[N/A] research-throwaway` if
  this isn't applicable).

No axis may be in the `[?] stale-detector` state (see "Auto-detector failure
handling" at the bottom of this document). Stale detectors block ship-ready
regardless of all other state.

## Project-type detection: AI-agent tooling

Some repos are not apps, services, or libraries — they are **AI-agent
tooling**: a Claude Code plugin, a subagent/skill/command bundle, an MCP
server, a Cursor ruleset, a Codex agent, an OpenCode config. For these, two
of the six axes do not apply: there is no GUI surface (UI/UX) and no
user-facing localized strings (i18n). The maturity model adapts the axis set
for them rather than forcing perpetual red.

**Deterministic fingerprint** (any one match ⇒ the repo is an AI-agent
tooling project; a security review that runs extra checks for AI-agent
tooling should key on this same list, so keep the two in lockstep):

- `.claude-plugin/plugin.json` or `.claude-plugin/marketplace.json`
- `.mcp.json` (any depth)
- `.cursorrules` at root, or any `.cursor/rules/*.mdc`
- `AGENTS.md` (any depth), `.codex/config.toml`, or any `.codex/agents/*.md`
- `opencode.json` at root, or a `.opencode/` directory
- `agents/*.md` whose frontmatter has both `name:` and `description:`;
  `skills/**/SKILL.md` with the same; or `commands/*.md` with the same

**Consequences** when the fingerprint matches:

1. **Packaging** is satisfied by the AI-agent distribution channels (the last
   six rows of the Packaging table) — the plugin/skill/MCP manifest *is* the
   package. No distro/store packaging is expected.
2. **UI/UX** and **i18n** are **not applicable**. `audit` auto-writes
   `[N/A] ai-tool` for each (converting a bare `[ ]` icon line, or adding the
   line to an empty axis). This is the one sanctioned case where `audit`
   writes an `[N/A]` line itself — everywhere else N/A is user-only. An
   `[N/A]`-only axis is ship-ready by the standard aggregation rule, so the
   two axes render N/A (⚪) in the dashboard instead of red.
3. The other four axes (Documentation, Security, Packaging, Testing & CI)
   are evaluated exactly as for any other project.

A repo that is *both* an app and ships agent tooling (e.g. a desktop app that
also vendors a Cursor ruleset) is still an app: the fingerprint is a
sufficient condition for the waiver only when the repo has no other UI
surface. If the project genuinely has a GUI, the maintainer overrides the
auto-`[N/A] ai-tool` with a real icon `[x]` or a different `[N/A]` reason and
the audit preserves that manual decision.

---

## Documentation

### Definition

Tracks the presence of the standard root-level documentation files that
downstream users and contributors expect to find. These files are
project-agnostic and apply to virtually every codebase, including libraries,
CLI tools, desktop apps, and browser extensions.

### Auto-detect rules

All path checks are relative to the project root. Each Documentation file name is
matched case-insensitively.

- Any root-level file whose name starts with `README` (`README.md` preferred
  when present) → auto-tick "README" with `auto:<whichever file matched>`
- `CHANGELOG` or `CHANGELOG.md` exists at project root → auto-tick
  "CHANGELOG" with `auto:<whichever file matched>`
- Any of `LICENSE`, `LICENSE.md`, or `LICENSE.txt` exists at project root →
  auto-tick "LICENSE" with `auto:<whichever file matched>`
- `CONTRIBUTING` or `CONTRIBUTING.md` exists at project root → auto-tick
  "CONTRIBUTING" with `auto:<whichever file matched>`

### Manual claim conditions

None of the documentation sub-items require a manual claim under normal
circumstances — they are fully auto-detectable. A manual claim is only
appropriate if the file lives at a non-standard path (e.g. inside `docs/`) and
the project maintainer intentionally keeps it there. In that case, use
`[x] claim:<date>` and add a comment noting the actual path.

### N/A guidance

- **CONTRIBUTING**: reasonable to mark `[N/A] solo-project` or
  `[N/A] not-accepting-prs` for personal tools, archived projects, or
  projects where external contribution is explicitly out of scope.
- **CHANGELOG**: may be marked `[N/A] pre-release` for projects that have
  never shipped a tagged release, but remove the N/A once the first release
  lands.
- **README** and **LICENSE**: N/A is almost never appropriate. Every
  distributed project needs both. Flag it rather than marking N/A.

### Ship-ready threshold

README and LICENSE must both be auto-ticked (or, in the manual-path edge case,
manually claimed). CHANGELOG and CONTRIBUTING may be auto-ticked, manually
claimed, or marked N/A. If either is simply absent (no tick of any kind), the
axis is not green.

---

## Security

### Definition

Tracks whether the project has undergone a security audit and whether any
findings that represent active risk (CRITICAL or HIGH severity) remain open.
The audit report is a structured markdown file produced by a security review
tool. The auto-detector reads the report header to extract finding counts.

### Auto-detect rules

1. List the security reports at the project root. A security report is a file
   named `<prefix>security-audit-report-<YYYYMMDD>-<HHMM>.md` or
   `<prefix>security-report-<YYYYMMDD>-<HHMM>.md`, where `<prefix>` is empty or
   any run of `[A-Za-z0-9._-]` ending in `-`, and the stamp is a real date and
   time. Other audit reports never count: a report from any other audit
   (`other-audit-report-…`) is not read, so a newer one
   can neither hide a dirty security report nor raise a stale-detector error. A
   name without a valid stamp is ignored. If nothing is left, there is no
   auto-tick.

   A security tool that writes another name is named in the staged-planning
   config (`$STAGED_PLANNING_CONFIG`, else
   `$XDG_CONFIG_HOME/staged-planning/config.yaml`; see the plugin's
   `references/records-resolver.md`):

   ```yaml
   security_report_prefixes: [acme-scan-]
   ```

   Each entry is a file-name prefix that comes straight before
   `<YYYYMMDD>-<HHMM>.md`, so `acme-scan-` admits `acme-scan-20261001-1000.md`.
   The entries add to the default names; they never replace them. A config that
   cannot be read, or a value that is not a list of prefixes without a `/`, is a
   note in the audit output, and only the default names are used.
2. Take the security report with the latest stamp, whatever its prefix: that
   is the newest report. When two share the latest stamp, the one whose file
   name sorts last wins.
3. Parse the header line of that file using the regex (the MEDIUM and LOW counts that
   follow are not read):

   ```
   ^\*\*Findings:\*\*\s*(\d+)\s+CRITICAL,\s*(\d+)\s+HIGH
   ```

4. If both captured groups 1 (CRITICAL) and 2 (HIGH) are `0` → auto-tick
   "security audit clean" (item key `security-audit`) with `auto:repo:<path>` (the detector returns the scope as a
   `scope` field alongside the bare path).
5. If the file exists but CRITICAL > 0 or HIGH > 0 → no auto-tick. The
   finding counts are recorded as an annotation so the user sees the block
   reason without opening the file.

### The checklist line

The checklist line is `[ ] security audit clean (latest stamped security report
has 0 CRITICAL + 0 HIGH)`. A checklist line whose label names the security audit
in an older wording is this item's line: rewrite its label to the current one;
never add a second line.

### Manual claim conditions

A manual claim (`[x] claim:<date>`) is appropriate when:

- The security report exists but has open HIGH/CRITICAL findings that the
  user has reviewed and accepted as out-of-scope with documented rationale.
- The audit was performed by an external tool that does not produce a
  security report the detector reads (see § Auto-detect rules); the user has
  reviewed the external output.

In either case the user must be able to point to a specific artifact. A manual
claim with no linked evidence is considered aspirational and will be challenged
at the next review.

### N/A guidance

Mark `[N/A] no-attack-surface` only for projects that genuinely have no
externally reachable I/O: pure data-transformation CLI utilities that read
from stdin and write to stdout, with no network access, no file-system writes
outside a controlled temp dir, and no privilege escalation. This is rare. When
in doubt, run the audit.

### Ship-ready threshold

The "security audit clean" sub-item must be auto-ticked, OR the axis must be marked
`[N/A] no-attack-surface`. A manual claim on the overall axis is accepted only
when backed by an artifact reference, as § Manual claim conditions requires. An absent audit file
with no N/A blocks ship-ready.

---

## Packaging

### Definition

Tracks whether the project is packaged for each distribution channel that
applies to its type. This axis has a per-target sub-checklist; only the
targets relevant to the project are checked — the rest are marked N/A. The
goal is to confirm that users on each supported platform have a working install
path, not to force packaging for every possible channel.

### Auto-detect rules

Each target below is independent. Check only those that apply; mark the rest
`[N/A] <reason>`.

| Target | Detection rule | Auto-tick evidence |
|---|---|---|
| Debian (.deb) | `deb/package/DEBIAN/control` exists | `auto:deb/package/DEBIAN/control` |
| macOS pkg/dmg | `pkg/` directory exists OR a `*.pkg` artifact is present under `releases/` (any depth) | `auto:pkg/` or `auto:releases/<file>.pkg` |
| Homebrew tap | Any `Formula/*.rb` file anywhere under the project tree | `auto:Formula/<file>.rb` |
| Flathub | `*.flatpak.yaml` at root OR a `flatpak/` directory exists | `auto:<file>.flatpak.yaml` or `auto:flatpak/` |
| AUR | `PKGBUILD` exists at project root | `auto:PKGBUILD` |
| Snap | `snapcraft.yaml` exists at project root | `auto:snapcraft.yaml` |
| Chrome extension | `chrome/manifest.json` exists AND contains `"manifest_version": 3` | `auto:chrome/manifest.json` |
| Firefox/AMO extension | `mozilla/manifest.json` OR `moz-mobile/manifest.json` exists | `auto:mozilla/manifest.json` or `auto:moz-mobile/manifest.json` |
| F-Droid | `metadata/<applicationId>.yml` in an fdroiddata fork directory OR a `fastlane/metadata/android/` directory exists | `auto:metadata/<id>.yml` or `auto:fastlane/metadata/android/` |
| GitHub Releases (Android APK) | Any `.github/workflows/*.yml` or `*.yaml` file whose content contains the literal `.apk` AND one of: `gh release create`, `softprops/action-gh-release`, `ncipollo/release-action` | `auto:<workflow-path>` |
| Google Play (Android) | Cannot be auto-detected. Play submission cannot be verified from local files alone. | Manual claim — **optional**. See "Android distribution channels are peers" below. |
| IzzyOnDroid (Android) | Cannot be auto-detected reliably (the project's `fastlane/metadata/android/` layout is shared with F-Droid). | Manual claim once the app is listed at `apt.izzysoft.de/fdroid`. |
| Obtainium (Android) | Cannot be auto-detected from local files (Obtainium pulls from arbitrary release sources). | Manual claim once the app appears in the Obtainium known-app list, or a maintainer-published Obtainium config URL is documented in the repo's README. |
| Accrescent (Android) | Cannot be auto-detected from local files (Accrescent acceptance is a service-side state). | Manual claim once the app is live on Accrescent. |
| Claude Code plugin | `.claude-plugin/plugin.json` exists | `auto:.claude-plugin/plugin.json` |
| Claude Code marketplace | `.claude-plugin/marketplace.json` exists | `auto:.claude-plugin/marketplace.json` |
| MCP server | `.mcp.json` exists (any depth) | `auto:<path>/.mcp.json` |
| Cursor rules pack | `.cursorrules` at root OR any `.cursor/rules/*.mdc` | `auto:.cursorrules` or `auto:.cursor/rules/<file>.mdc` |
| Codex agents | `AGENTS.md` (any depth) OR `.codex/config.toml` OR any `.codex/agents/*.md` | `auto:<path>` |
| OpenCode | `opencode.json` at root OR a `.opencode/` directory | `auto:opencode.json` or `auto:.opencode/` |

The last six rows are **AI-agent tooling distribution channels**: an agent
plugin / skill / ruleset / MCP server ships *as* the repo (installed by a
marketplace or copied into a tool's config dir), so the presence of its
manifest IS its packaging. They fire independently and universally — a non-AI
project simply won't have these files, so they need no project-type gate. Any
one ticking satisfies the Packaging minimum. These same files are the
fingerprint for the "Project-type detection: AI-agent tooling" rules above,
which additionally waive the UI/UX and i18n axes for such repos.

#### Android distribution channels are peers

Google Play, F-Droid, IzzyOnDroid, GitHub Releases (signed APK), Obtainium, and
Accrescent are **peer** channels for Android apps. No single one is canonical;
the maturity model treats any one ticking as satisfying the Android-packaging
minimum. An Android project that deliberately does not ship to Google Play (an
F-Droid-only release, a privacy-focused app refusing Play, an internal/sideload
build) is fully legitimate — it has the same ship-ready status as a Play-only
release, provided at least one of its actual channels is ticked.

Maintainers may use these explicit `[N/A]` reasons on individual Android-channel
sub-items to make the choice visible to reviewers (in addition to the generic
`[N/A] not-applicable`):

- `[N/A] not-distributing-to-play` — neutral opt-out from Google Play.
- `[N/A] fdroid-only` — F-Droid is the only consumer channel.
- `[N/A] sideload-only` — distribution is signed APK on GitHub Releases (or
  similar direct-from-source channel) only.
- `[N/A] private-distribution` — internal MDM, internal Play track, or
  enterprise sideload only; not a public-consumer release.

These reasons are documentary — they do not change tick semantics. Any one
peer channel auto-ticked or manually claimed still satisfies the axis minimum.

For the Chrome extension check, the detector reads `chrome/manifest.json` and
asserts the JSON field `manifest_version` equals `3`. If the file is malformed
JSON, this triggers a stale-detector error (see "Auto-detector failure
handling").

### Manual claim conditions

- **Google Play**: claim `[x] claim:<date>` once the app has been accepted
  and is live on the Play Store. The user should note the Play Store URL or
  package name in a comment. Detection would require a Play Developer API
  call, which is out of scope here. Optional — see "Android distribution
  channels are peers" above; an Android project may legitimately skip Play.
- **IzzyOnDroid**: claim once the app is listed at `apt.izzysoft.de/fdroid`.
  Note the IzzyOnDroid app URL in a comment.
- **Obtainium**: claim once the app appears in the Obtainium known-app list
  OR the repo documents an Obtainium configuration URL that users can paste.
- **Accrescent**: claim once the app is live on Accrescent. Note the
  Accrescent app URL.
- **Any other target**: use a manual claim if the packaging artifact lives at
  a non-standard path not covered by § Auto-detect rules. Note the actual path.

### N/A guidance

- Mark individual targets `[N/A] not-applicable` for any channel the project
  does not target (e.g. `[N/A] not-applicable` on AUR for a project that only
  targets Android).
- Mark the entire axis `[N/A] not-distributed` only if the project is an
  internal library or tool that is never published to any external channel.
  This is unusual — even CLI utilities typically have at least one packaging
  target.

### Ship-ready threshold

At least one applicable packaging target must be auto-ticked OR manually
claimed. If the entire axis is marked `[N/A] not-distributed`, that counts as
green. An axis with no ticks and no N/A blocks ship-ready.

For **Android** projects: any one peer channel suffices (Play, F-Droid,
IzzyOnDroid, GitHub Releases APK, Obtainium, Accrescent). Google Play is not
required — a project shipping only via F-Droid or only via signed APK on
GitHub Releases is ship-ready on the Packaging axis. Maintainers who want to
make the Play choice visible can add the explicit `[N/A]` reason from "Android
distribution channels are peers" above, but it is not required.

For **AI-agent tooling** projects: an auto-ticked AI-agent distribution channel
(Claude plugin / marketplace / MCP / Cursor / Codex / OpenCode) satisfies this
minimum — those repos need no distro or app-store packaging.

---

## UI/UX

### Definition

Tracks the baseline visual and accessibility quality of projects that have a
user-facing interface. For headless CLI tools and pure libraries this axis is
largely N/A, but the icon sub-item still applies to anything that appears in
an application launcher, app store, or browser extension store.

### Auto-detect rules

- **Icon present**: any of the following exists →
  auto-tick "icon" with evidence = the matched path:
  - `icon.png`, `icon.svg`, `icon.ico` or `icon.icns` at project root
  - `app-icon.*` (any extension) at project root
  - For Android projects: any `res/mipmap-*/ic_launcher*` file under the
    project tree (glob; use the first match as evidence)
  - For browser extensions: an `icons/` directory holding at least one
    `icon*.{png,svg}` located beside a `manifest.json` (e.g.
    `mozilla/icons/`, `chrome/icons/`, or a root-level `icons/`) → use the
    first matched icon file as evidence. Store-listed extensions always ship
    icons, so this path catches the common WebExtension layout where icons
    live under the manifest dir rather than at project root.

All other UI/UX sub-items (theming, accessibility audit) cannot be reliably
auto-detected across platforms and require manual claims.

### Manual claim conditions

- **Theming**: claim when a consistent color palette, typography, and spacing
  system has been applied across all screens or surfaces. The user should
  reference a design token file, a Figma link, or a style guide document.
- **Accessibility audit**: claim when an audit has been completed using a
  platform-appropriate tool or methodology:
  - Web / browser extension: WCAG 2.1 AA audit (tool + manual check)
  - Android: TalkBack navigation pass on a physical or emulated device
  - Linux desktop: Orca screen reader pass
  - macOS/iOS: VoiceOver pass
  The claim should reference the audit date and tool used in a comment.

### N/A guidance

- Mark theming and accessibility `[N/A] headless-cli` or
  `[N/A] library-no-ui` for projects with no visual interface.
- Mark the icon sub-item `[N/A] no-launcher-presence` only if the project
  genuinely never appears in any app launcher, extension store listing, or
  home screen (e.g. a pure server-side daemon with no desktop presence). This
  is uncommon — extension stores and app stores all require icons.
- N/A on the full axis is appropriate only for projects that have zero user
  interface of any kind.
- **AI-agent tooling projects** (Claude plugin / skill / MCP / Cursor / Codex
  / OpenCode — see the project-type section) have no GUI surface; `audit`
  auto-marks the axis `[N/A] ai-tool`. The maintainer overrides this with a
  real icon `[x]` or a different `[N/A]` reason if the repo does ship a GUI.

### Ship-ready threshold

The icon sub-item must be auto-ticked (or `[N/A] no-launcher-presence` with
documented rationale). Theming and accessibility must each be manually claimed
or marked N/A — they may not be left with no tick of any kind. A bare unchecked
`[ ]` on any sub-item blocks ship-ready. For AI-agent tooling projects the
axis is auto-`[N/A] ai-tool` and does not block.

---

## i18n

### Definition

Tracks whether the project externalizes its user-visible strings and ships at
least one locale beyond the default (typically English). A project that
targets only English-speaking users is a legitimate N/A; everything else
should demonstrate active i18n support before shipping.

### Auto-detect rules

The detector checks every applicable pattern in this subsection. If more than one applies,
each is ticked independently with its own evidence.

- **Android**: `res/values-*/` directories exist in the project tree (other
  than the bare `res/values/` default) → auto-tick with evidence =
  comma-separated list of the matched directory paths, e.g.
  `auto:app/src/main/res/values-de,app/src/main/res/values-fr`
- **Browser extensions**: `_locales/<lang>/` directories exist (other than
  `_locales/en/` or `_locales/en_US/`) → auto-tick
  with evidence = comma-separated list of matched locale directories
- **Gettext**: `po/*.po` files exist, at least one of which is not
  `messages.pot` → auto-tick with evidence = `auto:po/` and the count of
  `.po` files
- **Flutter**: `*.arb` files exist with a `_<lang>` suffix whose language does not start
  with `en` (so `_en_US` is excluded too)
  (e.g. `app_de.arb`, `app_ja.arb`) → auto-tick with evidence =
  comma-separated list of matched `.arb` file paths

In all cases, the detection confirms structure only — it does not validate
translation completeness or string coverage.

### Manual claim conditions

A manual claim is appropriate when:

- The i18n mechanism uses a framework not covered by § Auto-detect rules (e.g. Rails i18n
  YAML, iOS `.strings` / `.xcstrings`, GNU gettext in a non-standard
  directory layout). The user should note the framework and evidence path.
- Translation exists but is loaded dynamically from a remote source (e.g. a
  translation management platform) and no locale files live in the repo.

### N/A guidance

- Mark `[N/A] english-only-tool` for CLI tools, system daemons, or developer
  utilities whose output is log lines and structured data — places where
  i18n has no meaningful effect on usability.
- Mark `[N/A] english-only-by-design` for projects where the maintainer has
  made a deliberate, documented decision not to support additional locales.
- Do not mark N/A simply because no translations have been done yet — that is
  an open task, not an N/A.
- **AI-agent tooling projects** have no user-facing localized strings (their
  surface is prompts and config consumed by the agent); `audit` auto-marks the
  axis `[N/A] ai-tool`. See the project-type section.

### Ship-ready threshold

At least one non-default locale must be auto-ticked using any of the patterns
above, OR the axis must be marked `[N/A] english-only-tool` or
`[N/A] english-only-by-design`. A project with internationalized UI that has
not yet shipped any locale files does not meet the threshold. For AI-agent
tooling projects the axis is auto-`[N/A] ai-tool` and does not block.

---

## Testing

### Definition

Tracks the presence and health of automated tests and continuous integration.
A project without a test suite and CI is not ship-ready — even a small suite
that runs on every push is sufficient. CI green on main and coverage thresholds
are monitored via manual claims because auto-detecting those states would
require live API calls, which are out of scope here.

### Auto-detect rules

- **Test suite present**: any of the following exists →
  auto-tick "tests present" with evidence = the matched path(s):
  - `tests/` directory at project root
  - `test/` directory at project root
  - `spec/` directory at project root
  - Any `*_test.go`, `*_test.py` or `*.test.{js,ts,jsx,tsx}` file anywhere in
    the project tree
  - Any `*Test.kt` or `*Test.java` file anywhere under `src/`
  - `src/test/` directory (Maven/Gradle conventional test source root)
  - Rust: `Cargo.toml` exists AND (`tests/` directory exists OR `Cargo.toml`
    contains a `[[test]]` section)

  If several patterns match, the evidence is the first one found (a root
  directory before a test file). The presence of any one is sufficient for the
  sub-item to tick.

- **CI configured**: at least one `.yml` or `.yaml` file exists under
  `.github/workflows/` → auto-tick "CI configured" with evidence =
  comma-separated list of matched workflow file paths. With no workflow, a
  root `.gitlab-ci.yml` or a `.circleci/config.yml` ticks it instead, with
  that file as evidence.

### Manual claim conditions

- **CI green on main**: claim `[x] claim:<date>` when CI is currently passing
  on the default branch. Auto-detection would require a GitHub Actions API
  call, which is out of scope here. The user
  should note the last verified date and, optionally, the badge URL in a
  comment.
- **Coverage threshold**: claim when the project's coverage report meets the
  agreed threshold (e.g. 70% line coverage). Note the measured percentage and
  the tool used (e.g. `pytest-cov 84%`, `JaCoCo 76%`) in a comment alongside
  the claim date.

### N/A guidance

- Mark "CI configured" `[N/A] no-remote-repo` only if the project has no
  remote repository where CI can run (e.g. a purely local experiment that has
  never been pushed anywhere). Once the project is pushed, CI should be
  configured.
- Mark "CI green on main" `[N/A] no-ci` only when CI configured is also N/A.
  If CI is configured, its status must be claimed — it cannot be skipped.
- Mark "coverage threshold" `[N/A] no-threshold-set` if the project
  deliberately does not enforce a coverage floor (acceptable for scripts and
  glue code; document the rationale).
- The "tests present" sub-item has no valid N/A for ship-ready projects. Every
  project that ships to users should have at least a minimal smoke test.

### Ship-ready threshold

"Tests present" and "CI configured" must both be auto-ticked. "CI green on
main" and "coverage threshold" must each be manually claimed or marked N/A —
they may not be left as bare unchecked items. A project without a test suite
or without CI configured does not meet the threshold, regardless of the state
of the other five axes.

---

## Auto-detector failure handling

If any auto-detector encounters an error during `project-maturity audit` — for
example, a security report whose header line does not match the expected
regex, a `chrome/manifest.json` that is not
valid JSON, or a filesystem permission error reading a matched file — the
following behavior applies:

1. The axis sub-item retains whatever value it held before the audit run. No
   tick is added or removed.
2. The sub-item is annotated with `[?] stale-detector` and an inline note
   describing the error, e.g.:

   ```
   [?] stale-detector — security-audit-report-20260501-1430.md: Findings header line not found
   ```

3. The error is surfaced in the terminal output of `project-maturity audit` so
   the user is aware. There are no silent failures.
4. A `[?] stale-detector` state blocks `ship_ready: true` for the whole
   project, because the axis state is unknown.
5. The user must resolve the underlying issue (fix the malformed file, or
   update the detection rule if the format has legitimately changed) and
   re-run `project-maturity audit` to clear the flag.

The `[?] stale-detector` marker is never written by hand — it is exclusively
an output of the audit tool. If a user sees it in a `MATURITY.md` and the
audit has not been run recently, that is itself a signal to re-run the audit.
