# Architecture: WebDAV Sync CLI
Date: 2026-07-04
Design: ./2026-07-04-webdav-sync-design.md
Status: Approved 2026-07-04

Fixture for the architecture-doc parser-safety invariant (see
plan-parser.md § "Architecture docs"): authored per the architecting-projects
skill's Document format, this file MUST yield zero parser candidates.
It deliberately exercises the risky shapes — plain-bullet lists, a fenced
directory tree, Risks/Alternatives sections — none parseable as deferred work.

## Decision

Hexagonal core with adapter crates. The domain sync engine lives in a pure
`core` crate; WebDAV and filesystem access are ports implemented by adapter
crates; the binary wires them. Consequence: the engine is testable without
network fixtures, at the cost of one extra crate boundary.

## Alternatives rejected

- Single-crate layered: cheapest start, but the WebDAV client leaks into engine
  tests (evidence: reqwest-dependent unit tests in comparable projects).
- Workspace-per-feature: over-modular for a two-port tool; violates KISS.

## ARCH-01 Directory layout

```
webdav-sync/
├── Cargo.toml            (workspace)
├── core/                 (domain: diff, plan, apply — no I/O deps)
│   └── src/lib.rs
├── adapters/
│   ├── webdav/src/lib.rs (port impl over reqwest-dav)
│   └── localfs/src/lib.rs
└── cli/src/main.rs       (clap entry, wires adapters into core)
```

## ARCH-02 Module boundaries

- core: owns `SyncPlan`, `Entry`, diff algorithm; depends on nothing above std.
- adapters/webdav: implements `RemoteStore`; talks to core only via that trait.
- adapters/localfs: implements `LocalStore`; same rule.
- cli: the only crate allowed to depend on all three.

## ARCH-03 Key interfaces

- `trait RemoteStore { fn list(&self, path: &Path) -> Result<Vec<Entry>>; ... }`
  — the WebDAV boundary; mockable in core tests.
- `trait LocalStore` — mirror of the above for the filesystem side.

## ARCH-04 Data flow

cli parses args → core builds `SyncPlan` from `LocalStore::list` +
`RemoteStore::list` → core emits actions → adapters execute → cli reports.

## ARCH-05 Library choices

- clap 4: CLI surface (https://docs.rs/clap/4)
- reqwest-dav 0.2: WebDAV client (https://docs.rs/reqwest_dav)

## Risks

- reqwest-dav is young: mitigation — it sits behind `RemoteStore`, swappable.
- Large trees: diff is O(n) memory; accepted for v1, noted for evolution.

## Evidence

- rust-analyzer workspace layout (github.com/rust-lang/rust-analyzer): crates/
  split by responsibility, binary wires them.
- Hexagonal-in-Rust write-up (web, fetched 2026-07-04): trait-port pattern.
