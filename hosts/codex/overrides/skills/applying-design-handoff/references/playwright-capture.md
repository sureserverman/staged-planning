# Playwright render & capture — browser-renderable stacks

The fidelity loop is only as honest as its capture. For any stack that renders in a
browser, **render the running app with Playwright and screenshot it** — never grade a
web redesign from source alone. This is the concrete capture mechanism Phase 7 (and the
reproducer's per-slice self-check) uses; it is also how you *follow the mocks precisely*
while implementing, not just after.

## When this applies

- **Yes:** web (React/Vue/Svelte/Angular/plain HTML+CSS), and anything else served over
  HTTP or exportable to a static HTML page.
- **No — keep the existing capture path:** Android (emulator screenshots), macOS
  (SwiftUI/AppKit), Windows (WinUI/WPF), GTK/GNOME — each has its own render/capture; use
  it. If a native stack can be previewed in a webview, Playwright is a fallback, not the
  default.

## Driver — MCP first, headless script fallback

- **In the skill session (Codex):** prefer a **Playwright MCP** server, if one is
  configured for Codex — navigate, set viewport, and screenshot through its tools. If
  none is configured, tell the user one can be added to Codex's MCP servers, then fall
  back to the headless script.
- **In a spawned `planning:design-handoff-reproducer` agent:** always use the headless-script
  path via `npx playwright` (see below). It runs shell commands, so it can serve, render,
  and screenshot without an MCP server, and its captures don't depend on which servers
  its session has.

## Recipe

1. **Serve the app.** Start the project's dev/preview server (`npm run dev`, `npm run
   preview`, `vite preview`, framework equivalent) in the background; wait for the ready
   line / poll the port; capture the base URL. Tear it down when done.
2. **Enumerate render targets.** One target per screen in the pack's `layout`, **times**
   each breakpoint the pack declares. If the pack carries no breakpoints, use a small
   default set (e.g. 375 / 768 / 1440 px wide) and record that you defaulted. Add the
   component's own route/story for any component slice being graded.
3. **Render each target deterministically** (see *Determinism* below): set the exact
   viewport width, navigate, wait for settle, and take a **full-page** screenshot;
   **clip** to the component's bounding box for component-level slices. Repeat per themed
   state the pack carries (light/dark, hover/focus/disabled where reachable).
4. **Render the mock alongside — when the pack carries a reference render.** A Claude
   Design pack may ship **preview HTML** (Design System cards marked
   `<!-- @dsCard group="…" -->`) or exported PNG/SVG. When it does, open that reference in
   Playwright at the *same* viewport and screenshot it too, so the evaluator (and you,
   while implementing) compare implementation ↔ mock **at matching size**. When the pack
   carries **only structured spec** (tokens/anatomy/layout, no rendered preview), there is
   no mock image to diff — the spec values are the reference; grade the render against
   them directly.
5. **Name deterministically** and save under a captures dir (e.g.
   `.design-captures/`, gitignored): `<screenId>@<width>[.state].png` for the app and
   `<screenId>@<width>[.state].mock.png` for the reference. Hand these paths to the
   fidelity evaluator (Phase 7) — never the transcript.

## Determinism — a flaky capture fails a good redesign

- **Fixed viewport**, no device-scale surprises: set width explicitly per breakpoint.
- **Freeze motion:** inject CSS to disable animations/transitions
  (`*{animation:none!important;transition:none!important;}`) and set
  `prefers-reduced-motion`. A mid-animation frame is not the design.
- **Wait for settle:** `networkidle` **and** `document.fonts.ready` before shooting — web
  fonts loading late is the most common false type-fidelity miss.
- **Mask dynamic content** (timestamps, live counters, random avatars) so diffs reflect
  design, not data.
- **Do not** rely on wall-clock or randomness in capture scripts; seed or stub anything
  that varies so re-captures are byte-comparable across iterations.

## Following the mocks while you build (not only after)

Rendering is cheapest as a *tight loop*, not a final gate. While reproducing a
slice, render it and put it beside the mock/spec **before** declaring the slice done —
eyeball spacing, radius, type scale, and state coverage against the reference, fix the
largest deviation, re-render. This is what following the mocks means
operationally: the reproducer self-checks against a real render, and the Phase 7
evaluator then re-grades the gate's captures without having seen the implementation.
