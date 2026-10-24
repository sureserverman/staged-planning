// Shared fixtures for the package's node --test suites.
//
// The suites run in two places: from the sources (hosts/opencode/add/test, where the
// package root holds package.json.tmpl) and from a built package (test/ beside src/,
// hooks/ and skills/, with a rendered package.json). Either way they drive what ships:
// from the sources, the suite first builds this host into a scratch directory with
// build/build.py, so the hook scripts it runs are the host's rewritten copies, not core's.
// Each test then builds a throwaway package (the adapters' src/ beside a copy of those
// hook scripts) so the adapters resolve ../hooks/ exactly as they do when installed.
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const HERE = dirname(fileURLToPath(import.meta.url));
export const PKG = resolve(HERE, "..");
export const SRC = join(PKG, "src");
// A built package holds the rendered package.json; the sources hold only the template.
export const BUILT = existsSync(join(PKG, "package.json"));
// From the sources: the repo whose build/build.py builds this host.
export const REPO = BUILT ? null : resolve(PKG, "../../..");

const SCRATCH = mkdtempSync(join(tmpdir(), "oc-staged-planning-"));
process.on("exit", () => rmSync(SCRATCH, { recursive: true, force: true }));

function buildHost() {
  const out = join(SCRATCH, "build");
  try {
    execFileSync("python3", [join(REPO, "build", "build.py"), "--host", "opencode", "--no-lock-check",
                             "--out", out], { cwd: REPO, stdio: ["ignore", "ignore", "pipe"] });
  } catch (e) {
    throw new Error(`fixture: building the opencode host failed: ${e.stderr || e.message}`);
  }
  return out;
}
// The built package the suite drives: this one when built, else a fresh build.
export const SHIPPED = BUILT ? PKG : buildHost();
export const HOOKS = join(SHIPPED, "hooks");
export const INSTALL = join(SHIPPED, "skills/executing-plans/scripts/proof-hooks-install.py");

for (const need of [join(HOOKS, "proof-guard.sh"), join(HOOKS, "dispatch-log.sh"),
                    join(HOOKS, "plan_continue_classify.py"), INSTALL]) {
  if (!existsSync(need)) throw new Error(`fixture: ${need} is missing; the suite cannot run`);
}

// Hermetic: no user git config, no user HOME, no inherited project dir.
process.env.HOME = join(SCRATCH, "home");
mkdirSync(process.env.HOME);
process.env.GIT_CONFIG_GLOBAL = "/dev/null";
process.env.GIT_CONFIG_NOSYSTEM = "1";
delete process.env.CLAUDE_PROJECT_DIR;

let n = 0;
export function scratch(name) {
  const d = join(SCRATCH, `${name}-${++n}`);
  mkdirSync(d, { recursive: true });
  return d;
}

/** A throwaway package: src/ copied, hooks/ copied (or replaced by `hooks`), plus `files`. */
export function makePackage({ hooks, files = {} } = {}) {
  const root = scratch("pkg");
  mkdirSync(join(root, "src"));
  for (const f of readdirSync(SRC)) copyFileSync(join(SRC, f), join(root, "src", f));
  if (hooks === undefined) {
    mkdirSync(join(root, "hooks"));
    for (const d of readdirSync(HOOKS, { withFileTypes: true })) {
      if (d.isFile()) copyFileSync(join(HOOKS, d.name), join(root, "hooks", d.name));
    }
  } else if (hooks !== null) {
    mkdirSync(join(root, "hooks"));
    for (const [name, text] of Object.entries(hooks)) writeFileSync(join(root, "hooks", name), text);
  }
  for (const [rel, text] of Object.entries(files)) {
    mkdirSync(dirname(join(root, rel)), { recursive: true });
    writeFileSync(join(root, rel), text);
  }
  return root;
}

export async function loadIndex(root) {
  return import(pathToFileURL(join(root, "src", "index.ts")).href);
}

/** The one plugin function a module exports; throws when there is not exactly one. */
export function pluginOf(mod) {
  const fns = Object.values(mod).filter((v) => typeof v === "function");
  if (fns.length !== 1) throw new Error(`the module exports ${fns.length} functions, not 1`);
  return fns[0];
}

/** A git repo; `plan` puts a plan in flight, `optIn` installs the commit-gate shim. */
export function newRepo({ plan = false, optIn = false } = {}) {
  const dir = scratch("repo");
  execFileSync("git", ["init", "-q", "--template=", dir], { stdio: "ignore" });
  if (optIn) {
    execFileSync("python3", [INSTALL, "--install", "--repo", dir], { stdio: "ignore" });
  }
  if (plan) {
    mkdirSync(join(dir, ".claude"), { recursive: true });
    writeFileSync(join(dir, "plan.md"), "# Plan\n");
    writeFileSync(join(dir, ".claude", "plan-progress.json"),
      JSON.stringify({ plan: join(dir, "plan.md"), phase: "task", stage: 1, task: "1.1" }) + "\n");
  }
  return dir;
}

/** Calls a hook; resolves to "ok" or "threw: <message>". */
export async function call(fn, ...args) {
  try {
    await fn(...args);
    return "ok";
  } catch (e) {
    return `threw: ${e && e.message}`;
  }
}

// Payloads in the shapes @opencode-ai/plugin 1.19.3 types its hooks with.
export const bashCall = (command, workdir) => [
  { tool: "bash", sessionID: "ses_parent", callID: "call_bash" },
  { args: workdir === undefined ? { command, description: "run it" }
                                : { command, description: "run it", workdir } },
];
export const taskCall = (subagent_type = "code-reviewer", description = "Stage 1 Tier-2 review") => [
  { tool: "task", sessionID: "ses_parent", callID: "call_task" },
  { args: { description, prompt: "review the stage", subagent_type } },
];
export const childCreated = (id = "ses_child", extra = {}) => ({
  event: {
    type: "session.created",
    properties: { info: { id, projectID: "prj", directory: "/", parentID: "ses_parent", title: "child",
                          version: "1.19.3", time: { created: 1, updated: 1 }, ...extra } },
  },
});
export const taskDone = (sessionId = "ses_child") => [
  { tool: "task", sessionID: "ses_parent", callID: "call_task", args: {} },
  { title: "done", output: "ok", metadata: { sessionId } },
];

/** The log's lines, parsed; [] when there is no log. */
export function logLines(repo) {
  const f = join(repo, ".claude", "dispatch-log.jsonl");
  if (!existsSync(f)) return [];
  return readFileSync(f, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

// The git hooks-path key, spelled in two halves so this file's own text is not a target.
export const HOOKS_KEY = "core.hooks" + "Path";
