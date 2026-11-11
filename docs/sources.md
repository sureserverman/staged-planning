# Sources

The works the shipped skills draw on, grouped by the skill or reference that drew on them.
This is a maintainer document: it is not installed with any skill. The skills state their
rules; the reasons a rule exists are recorded here.

## brainstorming

- **One question at a time / multiple choice** — Socratic dialogue tradition; easier to reason about a constrained choice than generate an open-ended answer
- **YAGNI / KISS / DRY** — *The Pragmatic Programmer* (Hunt & Thomas); Kent Beck's *Extreme Programming Explained*
- **Explicit alternatives with tradeoffs** — ADR (Architecture Decision Record) practice; Michael Nygard, "Documenting Architecture Decisions"
- **Pre-mortem technique** — Gary Klein, *Performing a Project Premortem* (Harvard Business Review, 2007)
- **Planning fallacy** — Daniel Kahneman, *Thinking, Fast and Slow*, Ch. 23
- **Christopher Alexander pattern forces** — *A Pattern Language* (1977) via *Design Patterns* (GoF)
- **5W1H clarification** — journalism/business-analysis standard; see Kipling's "six honest serving men"
- **Section-by-section validation** — stage-gate process (Robert Cooper, *Winning at New Products*)

## executing-plans

- **Red-Green loop** — Kent Beck, *Test-Driven Development: By Example* (2002); the "test first, then make it pass" cycle adapted for task-level discipline
- **Stage gates** — Robert Cooper, *Winning at New Products* (1986); phase gates with specific pass/fail criteria
- **Max 3 failure cycles** — heuristic from debugging literature; after three targeted fixes without resolution, the hypothesis (not the implementation) is wrong. See Feynman on "the first principle is that you must not fool yourself"
- **Preflight as hard gate** — aviation checklist tradition; Atul Gawande, *The Checklist Manifesto* (2009)
- **Commit per green task** — frequent, small commits; *The Pragmatic Programmer* Ch. 7; Linus Torvalds on "each commit should be a single logical change"
- **Never skip the test** — Beck (TDD), Fowler ("Continuous Integration"); the test is the only signal that says "done"
- **Independent evaluator, context resets** — Anthropic Engineering, "Harness design for long-running application development" (https://www.anthropic.com/engineering/harness-design-long-running-apps); generators grade their own work too generously, and structured handoffs into fresh context outperform one degrading context
- **Repair the class, not the instance** — W. Edwards Deming, *Out of the Crisis* (1982), on acting at the level of the process rather than the defective unit; Toyota's *jidoka*, where a line stops on a fault so the cause is removed rather than the piece replaced. This is what executing-plans § *A bug found during execution is a class* applies to a single run: the instance a gate, a review or a RED test happens to surface is a sample, and repairing only the sample is what converts one class into N remediation rounds

## executing-plans: dispatch (`references/dispatch.md`)

- **Dependency graph execution** — classic topological sort from graph theory; *Introduction to Algorithms* (CLRS) section 22.4
- **Fan-out / fan-in pattern** — Communicating Sequential Processes (Hoare, 1978); Go's `sync.WaitGroup` and Erlang supervision trees
- **Self-contained agent prompts** — Anthropic multi-agent orchestration guidance; sub-agents have no conversation context and must be briefed completely
- **Trust-but-verify** — Reagan / Gorbachev; applied to sub-agent reports. On incident postmortems: *Google SRE Book* Ch. 15
- **Merge check after parallel work** — continuous integration practice; Fowler, "Continuous Integration" (2006)
- **Failure propagation through dependents** — Erlang "let it crash" + supervisor trees; don't build on broken foundations

### references/stack-routing.md

- Anthropic — "Create custom subagents" (code.claude.com/docs/en/sub-agents): isolated
  context windows; subagents for context preservation; choose main conversation for
  coupled/iterative/quick/latency-sensitive work.
- Anthropic — "Effective context engineering for AI agents"
  (anthropic.com/engineering/effective-context-engineering-for-ai-agents): subagents
  return condensed summaries; specialized agents with clean context windows.
- Codex `[agents]` configuration (Codex fork of this file): `max_threads` (concurrency cap,
  default 6) and `max_depth` 1 (a spawned agent cannot spawn).

## workflow-spec

- **Behavior-as-contract** — Bertrand Meyer, *Object-Oriented Software Construction* (1997); preconditions/postconditions/invariants as the unit of specification, lifted from code to docs.
- **Stable IDs over prose** — same logic as test-case IDs in regulated industries (IEC 62304, ISO 26262): a triage that says "WF-AUTH-003 removed" is mechanically actionable; "the login flow changed" is not.
- **Capture is a draft, audit is the gate** — Karl Wiegers, *Software Requirements* (3rd ed.); spec docs that aren't reviewed by a human are decoration. The skill explicitly stops at draft and hands off.
- **`Last verified` stamps** — borrowed from runbooks / SOC2 evidence practice; a doc with no recency stamp is assumed stale.

## applying-design-handoff

- Claude Design handoff = spec bundle (tokens + components + layout + assets) for direct
  consumption, not a PNG/Figma URL — claudefa.st "Claude Design to Claude Code";
  Anthropic Claude Design overhaul coverage (VentureBeat).
- Separate-evaluator visual verification + weighted rubric + capped iterate loop —
  a generator–evaluator loop (four weighted dimensions, a pass threshold, a capped
  iterate loop) in which the generator never grades itself.
- Independent evaluator (generators grade their own work too generously) — Anthropic
  Engineering, "Harness design for long-running application development".

## references/review-catalogs.md (the code-reviewer agent's catalogs)

- Google — *Code Review Developer's Guide* (google.github.io/eng-practices/review/)
- Martin Fowler — *Refactoring* 2e (2018); refactoring.com/catalog/
- Robert C. Martin — *Clean Code* (2008); SOLID
- Brian Kernighan & P.J. Plauger — *The Elements of Programming Style* (1978)
- Karl E. Wiegers — *Peer Reviews in Software* (2002)
- Michael Fagan — "Design and code inspections to reduce errors in program development" (IBM Systems Journal, 1976)
- OWASP — ASVS v4, WSTG v4.2, Top 10 (2021)
- MITRE — CWE Top 25 Most Dangerous Software Weaknesses
- CERT Secure Coding Standards (C, C++, Java)
- NASA / JPL — "The Power of 10: Rules for Developing Safety-Critical Code" (Holzmann, 2006)
- Gerard Meszaros — *xUnit Test Patterns* (test-smell vocabulary)
- Donald Knuth — "Literate Programming" (1984)
