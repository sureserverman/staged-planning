# Decisions format: `decisions.md`

A project records **why its architecture is the way it is** in one register,
`<records home>/decisions.md` (the records home is the repo's `docs/` unless a records
resolver is configured; see `../../../references/records-resolver.md`). A configured
resolver may also list further registers that bind the project, such as registers
shared by every project on one stack; the decisions scan reads those after the project's
own, with the same parser.

## Why a register and not just the architecture doc

An architecture doc (`plans/YYYY-MM-DD-<topic>-architecture.md`) is event-shaped: it
captures one architecture exercise, keyed `ARCH-NN`, and is not revisited once its plan
is executed. Decisions accrete *between* those events: a security review lands a
constraint, a platform deprecation forces a library swap, a packaging limit rules out an
approach. Those have no home in a dated plan file. The register is that home; the
architecture doc stays the place where a decision is first *made*, and cites into the
register when it is.

## Format

`decisions.md` is a flat list of `## DEC-NNN` blocks, newest first, under a short
preamble. IDs are zero-padded 3-digit, monotonic, and **never reused**: the next ID is
`max + 1` even when earlier entries have been superseded.

A register may instead key its entries `DEC-<TAG>-NNN`, where `<TAG>` is a 2–4 letter
uppercase project tag. Both forms parse; a register picks one and holds to it. The tag
earns its cost when the project's decisions are cited from outside the project, where a
bare `DEC-NNN` does not say whose decision it is.

```markdown
# Decisions

Architectural decisions binding this project, newest first. Each entry records
what was decided and why. Superseded entries stay — the history is the point.

---

## DEC-NNN — Keep API tokens in the OS keychain, not in a config file

- **Decided:** YYYY-MM-DD
- **Status:** accepted
- **Domains:** desktop, security
- **Source:** security review report `<file>.md` (local-only)
- **Reason:** A config file is readable by any process running as the user and is
  copied into plain backups. The OS keychain gates access per app and stays out of
  those backups. Cost: each supported OS needs its own keychain adapter.
```

### Field semantics

| Field | Required | Meaning |
|-------|----------|---------|
| `Decided` | yes | `YYYY-MM-DD`, the date the decision was taken (not the date it was written down). |
| `Status` | yes | `accepted`, or `superseded by DEC-NNN`. A superseded entry is never deleted or renumbered. |
| `Domains` | yes | Comma-separated slugs this decision touches (stack, platform, concern). `none` for a decision genuinely specific to this project. |
| `Source` | yes | What produced the decision: a plan file, an architecture doc plus its `ARCH-NN`, a code review, a security review report, or `direct` when taken in conversation. |
| `Reason` | yes | **The point of the register.** The constraint, the evidence, the trade-off accepted, and what was rejected. A `Reason` that only restates the decision is a defect. |

### Recording a security review recommendation

Security review report files are **local-only and never committed**. A decision that
comes from one therefore:

- cites the report **by filename and date only**, suffixed `(local-only)`;
- restates the finding's substance **in the entry's own words** under `Reason`;
- **never** embeds, quotes at length, or copies the report body.

The register must stay useful to a reader who cannot open the report, which is what
`Reason` is for, without becoming a second copy of it.

## Parser rules

The reader in `../scripts/decisions-relevant.py` follows these, and
`../scripts/tests/test-decisions-relevant.py` locks them:

1. **Block boundaries are found with a generic `^## ` match**, and the ID shape is
   validated *afterwards*. A heading that misses the em-dash (a plain hyphen is the
   common slip) would otherwise start no block at all, and its body would be dropped or
   swallowed into the previous block: a binding decision would disappear, which is the
   one outcome this register exists to prevent.
2. A heading that fails `^DEC-(?:[A-Z]{2,4}-)?\d+ — ` yields a **flagged entry**
   carrying the raw heading, never a skipped one.
3. Fields are `- **Name:** value` lines; a field may wrap onto continuation lines,
   joined with a single space. A horizontal rule (`---`, `***`, `___`) never joins into
   a field value.
4. A block missing a required field is **reported, not dropped**.
5. A file that is unreadable or has no recognizable blocks contributes zero entries and
   one error line; it never aborts the scan.
6. Zero-padding to three digits is the authoring convention, not a parser requirement.
7. **An ID claimed by two blocks in the same file is reported**: every reference to it
   is ambiguous. Both blocks are still listed.
8. A `## `-prefixed line inside a field's continuation is read as a block boundary,
   which is inherent to rule 1. It degrades visibly: the quoted line becomes a flagged
   entry and the following decision parses intact. Indent such a line or use inline
   code.
