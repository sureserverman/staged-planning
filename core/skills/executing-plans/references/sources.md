# Sources and rationale

- **Red-Green loop** — Kent Beck, *Test-Driven Development: By Example* (2002); the "test first, then make it pass" cycle adapted for task-level discipline
- **Stage gates** — Robert Cooper, *Winning at New Products* (1986); phase gates with specific pass/fail criteria
- **Max 3 failure cycles** — heuristic from debugging literature; after three targeted fixes without resolution, the hypothesis (not the implementation) is wrong. See Feynman on "the first principle is that you must not fool yourself"
- **Preflight as hard gate** — aviation checklist tradition; Atul Gawande, *The Checklist Manifesto* (2009)
- **Commit per green task** — frequent, small commits; *The Pragmatic Programmer* Ch. 7; Linus Torvalds on "each commit should be a single logical change"
- **Never skip the test** — Beck (TDD), Fowler ("Continuous Integration"); the test is the only signal that says "done"
- **Independent evaluator, context resets** — Anthropic Engineering, "Harness design for long-running application development" (https://www.anthropic.com/engineering/harness-design-long-running-apps); generators grade their own work too generously, and structured handoffs into fresh context outperform one degrading context
- **Repair the class, not the instance** — W. Edwards Deming, *Out of the Crisis* (1982), on acting at the level of the process rather than the defective unit; Toyota's *jidoka*, where a line stops on a fault so the cause is removed rather than the piece replaced. This is what `../SKILL.md` § *A bug found during execution is a class* applies to a single run: the instance a gate, a review or a RED test happens to surface is a sample, and repairing only the sample is what converts one class into N remediation rounds
