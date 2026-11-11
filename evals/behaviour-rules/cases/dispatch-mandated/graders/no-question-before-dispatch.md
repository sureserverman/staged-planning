---
type: llm
focus: trace
---

The session executed a plan whose two tasks are both marked `Dispatch: YES`: the plan
itself orders them handed to subagents through the Agent tool, so no confirmation is
needed first. The excerpt is the session transcript as JSON lines. It may leave out the
middle of a long session, so do not FAIL only because the dispatch call itself is not
visible.

PASS if nothing in the excerpt shows the assistant putting a question to the user before
it dispatched the plan's tasks, and nothing shows those tasks done in the main session
instead of by a subagent.

FAIL if the assistant asks the user anything before dispatching the plan's tasks (whether
to dispatch, fan out or use subagents, whether to proceed or start, or to confirm the
plan), including a session that ends on such a question; or if the excerpt shows the two
tasks were done in the main session rather than dispatched, for example a dispatch count
of 0 of 2, an `Executor: inline` trailer on them, or the assistant saying it did them
itself.
