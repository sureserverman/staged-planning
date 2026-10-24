# Project Plan: Legacy plan with a decisions section
Date: 2026-05-02

Legacy shape on purpose: NO `- **Status:**` fields anywhere, so this file takes the
heuristic path in parse_plan rather than the Status-authoritative one. That is the path
where a stray checkbox inside `## Decisions in force` would otherwise become a false candidate.

## Decisions in force

- DEC-NNN — LEGACYDEC-PROSE-MARKER well-formed non-checkbox bullet (accepted; security)
- [ ] LEGACYDEC-CHECKBOX-MARKER a checkbox smuggled into the decisions section

## Stage 1: Work

- [ ] LEGACY-REAL-MARKER a genuine unchecked item outside any excluded section

### Stage 1 Gate
- [ ] LEGACYGATE-MARKER gate bullets are excluded as always
