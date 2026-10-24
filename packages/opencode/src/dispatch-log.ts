/**
 * dispatch-log — the OpenCode adapter for hooks/dispatch-log.sh.
 *
 * The line writer has one copy: ../hooks/dispatch-log.sh, shipped from core with one key
 * renamed by this host's build (the agent is `agent_name`, an untyped call `general`), so
 * its properties hold here: it never blocks, it is inert unless
 * .claude/plan-progress.json exists, and it writes .claude/dispatch-log.jsonl with
 * O_NOFOLLOW, mode 0600. This adapter reshapes each OpenCode event into the payload the
 * script reads, with CLAUDE_PROJECT_DIR set to the plugin context's worktree (else its
 * directory):
 *   dispatch  `tool.execute.before`, tool `task` ->
 *             {"hook_event_name":"PreToolUse","tool_name":"Task",
 *              "tool_input":{"agent_name":args.subagent_type,"description":args.description}}
 *             (OpenCode's task tool names the agent in its `subagent_type` argument)
 *   start     `event`, `session.created` whose info has a parentID ->
 *             {"hook_event_name":"SubagentStart","agent_id":info.id,"agent_type":info.agent}
 *   stop      `tool.execute.after`, tool `task` ->
 *             {"hook_event_name":"SubagentStop","agent_id":metadata.sessionId}
 * A child session's info.id and its task's metadata.sessionId are the same id, so
 * review-ledger-check.py --unstopped pairs a start with its stop.
 *
 * IT ALLOWS EXPLICITLY AND NEVER THROWS. A throw from `tool.execute.before` blocks the
 * tool, and a dispatch must never fail because logging did. So every hook returns
 * normally (OpenCode's allow) on every path: a malformed payload, a missing or failing
 * script, a value JSON cannot encode. The hook waits for the script, so lines keep
 * their order, but nothing the script does reaches the caller.
 *
 * Erasable TypeScript only, as proof-guard.ts.
 */
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runScript } from "./proof-guard.ts";

export type Ctx = { directory?: string; worktree?: string };
export type Options = { hooksDir?: string; timeoutMs?: number };

const DEFAULT_HOOKS = fileURLToPath(new URL("../hooks/", import.meta.url));

function str(v: unknown): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}

export function createDispatchLog(opts: Options = {}) {
  const hooksDir = opts.hooksDir ?? DEFAULT_HOOKS;
  const timeoutMs = opts.timeoutMs ?? 10000;
  return async (ctx: Ctx) => {
    let project = "";
    try {
      project = str(ctx?.worktree) ?? str(ctx?.directory) ?? "";
    } catch {
      project = "";
    }
    const feed = async (payload: object): Promise<void> => {
      try {
        await runScript(resolve(hooksDir, "dispatch-log.sh"), JSON.stringify(payload),
          { ...process.env, CLAUDE_PROJECT_DIR: project }, timeoutMs);
      } catch {
        // never surfaces: see the header
      }
    };
    return {
      "tool.execute.before": async (input: { tool?: string }, output: { args?: any }): Promise<void> => {
        try {
          if (input?.tool !== "task") return;
          const a = output?.args ?? {};
          await feed({ hook_event_name: "PreToolUse", tool_name: "Task",
                       tool_input: { agent_name: a.subagent_type, description: a.description } });
        } catch {
          // never surfaces
        }
      },
      event: async (input: { event?: any }): Promise<void> => {
        try {
          const ev = input?.event;
          if (ev?.type !== "session.created") return;
          const info = ev.properties?.info;
          if (!str(info?.parentID) || !str(info?.id)) return;
          await feed({ hook_event_name: "SubagentStart", agent_id: info.id, agent_type: info.agent });
        } catch {
          // never surfaces
        }
      },
      "tool.execute.after": async (input: { tool?: string }, output: { metadata?: any }): Promise<void> => {
        try {
          if (input?.tool !== "task") return;
          const id = str(output?.metadata?.sessionId);
          if (!id) return;
          await feed({ hook_event_name: "SubagentStop", agent_id: id });
        } catch {
          // never surfaces
        }
      },
    };
  };
}
