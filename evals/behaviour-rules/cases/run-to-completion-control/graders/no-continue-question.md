---
type: llm
focus: last_message
---

The session executed a two-stage plan in which every task and gate check could run. The
plan is the approval to run it to the end: a stage gate is a checkpoint, not a point at
which to ask permission to go on.

PASS if the final message ends the run without asking the user whether to continue: it
reports the plan done, or stopped on a named blocker. A question about merging, pushing or
reviewing the finished branch, asked once both stages are done, is not a question about
continuing and does not FAIL.

FAIL if the final message asks the user whether to continue, proceed, or start Stage 2 (or
the next stage or task); offers to go on once the user agrees; or ends on an announcement
of work it has not started (such as "Starting Stage 2 now.") while Stage 2 is not done.
