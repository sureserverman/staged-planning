/**
 * proof-guard — the OpenCode adapter for hooks/proof-guard.sh.
 *
 * The text rules have one copy: ../hooks/proof-guard.sh, shipped from core unchanged.
 * This adapter only reshapes. On `tool.execute.before` for the `bash` tool it pipes
 * {"tool_input":{"command":…},"cwd":…} to the script, and when the script prints a
 * `deny` decision it throws with the script's reason: a throw from
 * `tool.execute.before` is how an OpenCode plugin blocks a tool call. `cwd` is the
 * call's own `workdir` (resolved against the session's directory) when it names one,
 * else the session's directory.
 *
 * It FAILS OPEN, as the script does on its own errors: a script that cannot run, exits
 * non-zero, times out, or prints anything but a deny decides nothing, and the tool runs.
 *
 * Erasable TypeScript only (no enum, no value namespace, no parameter properties): the
 * package's suite runs this file under Node's type stripping, OpenCode under Bun.
 */
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type Ctx = { directory?: string; worktree?: string };
export type Options = { hooksDir?: string; timeoutMs?: number };

const DEFAULT_HOOKS = fileURLToPath(new URL("../hooks/", import.meta.url));
const FALLBACK_REASON = "Denied by the planning commit gate.";

/** Runs `bash <script>` with `input` on stdin. Resolves to {status, stdout}; never rejects. */
export function runScript(
  script: string,
  input: string,
  env: Record<string, string | undefined>,
  timeoutMs: number,
): Promise<{ status: number | null; stdout: string }> {
  return new Promise((done) => {
    let stdout = "";
    let settled = false;
    const finish = (status: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      done({ status, stdout });
    };
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn("bash", [script], { env, stdio: ["pipe", "pipe", "ignore"] });
    } catch {
      done({ status: null, stdout: "" });
      return;
    }
    const timer = setTimeout(() => {
      try { child.kill("SIGKILL"); } catch { /* already gone */ }
      finish(null);
    }, timeoutMs);
    child.on("error", () => finish(null));
    child.stdout?.on("data", (b: Buffer) => { stdout += b.toString("utf8"); });
    child.on("close", (code: number | null) => finish(code));
    child.stdin?.on("error", () => { /* the script may exit before reading it all */ });
    try {
      child.stdin?.end(input);
    } catch {
      /* the close handler still settles */
    }
  });
}

/** The deny reason the script printed, or "" when it decided nothing. */
export async function guardDecision(
  command: string,
  cwd: string,
  hooksDir: string = DEFAULT_HOOKS,
  timeoutMs = 15000,
): Promise<string> {
  try {
    const r = await runScript(resolve(hooksDir, "proof-guard.sh"),
      JSON.stringify({ tool_input: { command }, cwd }), process.env, timeoutMs);
    const out = r.stdout.trim();
    if (r.status !== 0 || !out) return "";
    const d = JSON.parse(out)?.hookSpecificOutput;
    if (d?.permissionDecision !== "deny") return "";
    return String(d.permissionDecisionReason || FALLBACK_REASON);
  } catch {
    return "";
  }
}

export function createProofGuard(opts: Options = {}) {
  const hooksDir = opts.hooksDir ?? DEFAULT_HOOKS;
  const timeoutMs = opts.timeoutMs ?? 15000;
  return async (ctx: Ctx) => ({
    "tool.execute.before": async (input: { tool?: string }, output: { args?: any }) => {
      let reason = "";
      try {
        if (input?.tool !== "bash") return;
        const args = output?.args ?? {};
        if (typeof args.command !== "string") return;
        const base = typeof ctx?.directory === "string" && ctx.directory ? ctx.directory : process.cwd();
        const cwd = typeof args.workdir === "string" && args.workdir ? resolve(base, args.workdir) : base;
        reason = await guardDecision(args.command, cwd, hooksDir, timeoutMs);
      } catch {
        return;
      }
      if (reason) throw new Error(reason);
    },
  });
}
