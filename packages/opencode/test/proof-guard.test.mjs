// proof-guard.ts: in a repo that opted into the commit gate with a plan in flight, a bash
// command that would switch the gate off throws (a throw from tool.execute.before blocks
// the call); everywhere else, and on any error of its own, the call runs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { bashCall, call, HOOKS_KEY, loadIndex, makePackage, newRepo, pluginOf, taskCall } from "./helpers.mjs";

const plugin = pluginOf(await loadIndex(makePackage()));
const denied = `git config ${HOOKS_KEY} /dev/null`;

test("opted in, plan in flight: a command naming the hooks-path key throws the guard's reason", async () => {
  const repo = newRepo({ plan: true, optIn: true });
  const h = await plugin({ directory: repo, worktree: repo });
  const r = await call(h["tool.execute.before"], ...bashCall(denied, repo));
  assert.match(r, /^threw: Denied:/);
});

test("a command naming the git reference-transaction hook throws too", async () => {
  const repo = newRepo({ plan: true, optIn: true });
  const h = await plugin({ directory: repo, worktree: repo });
  const r = await call(h["tool.execute.before"], ...bashCall("rm .git/hooks/reference-transaction"));
  assert.match(r, /^threw: Denied:/);
});

test("no workdir: the cwd is the session's directory; a relative workdir resolves against it", async () => {
  const repo = newRepo({ plan: true, optIn: true });
  mkdirSync(join(repo, "sub"));
  const h = await plugin({ directory: repo, worktree: repo });
  assert.match(await call(h["tool.execute.before"], ...bashCall(denied)), /^threw: Denied:/);
  assert.match(await call(h["tool.execute.before"], ...bashCall(denied, "sub")), /^threw: Denied:/);
  const elsewhere = newRepo({ plan: false });
  const h2 = await plugin({ directory: elsewhere, worktree: elsewhere });
  assert.equal(await call(h2["tool.execute.before"], ...bashCall(denied)), "ok");
});

test("an ordinary command in the gated repo runs", async () => {
  const repo = newRepo({ plan: true, optIn: true });
  const h = await plugin({ directory: repo, worktree: repo });
  assert.equal(await call(h["tool.execute.before"], ...bashCall("git status", repo)), "ok");
});

test("not opted in, or no plan in flight: the command runs", async () => {
  for (const opts of [{ plan: true, optIn: false }, { plan: false, optIn: true }]) {
    const repo = newRepo(opts);
    const h = await plugin({ directory: repo, worktree: repo });
    assert.equal(await call(h["tool.execute.before"], ...bashCall(denied, repo)), "ok", JSON.stringify(opts));
  }
});

test("a non-bash tool carrying the same text is not examined", async () => {
  const repo = newRepo({ plan: true, optIn: true });
  const h = await plugin({ directory: repo, worktree: repo });
  const [input, output] = taskCall();
  output.args.command = denied;
  assert.equal(await call(h["tool.execute.before"], input, output), "ok");
});

test("it fails open: a script printing garbage, a missing script, a malformed payload", async () => {
  const repo = newRepo({ plan: true, optIn: true });
  const garbage = pluginOf(await loadIndex(makePackage({ hooks: {
    "proof-guard.sh": 'echo "{not json"\nexit 0\n', "dispatch-log.sh": "exit 0\n",
  } })));
  const missing = pluginOf(await loadIndex(makePackage({ hooks: null })));
  for (const p of [garbage, missing]) {
    const h = await p({ directory: repo, worktree: repo });
    assert.equal(await call(h["tool.execute.before"], ...bashCall(denied, repo)), "ok");
  }
  const h = await plugin({ directory: repo, worktree: repo });
  for (const out of [undefined, null, {}, { args: null }, { args: { command: 7 } }]) {
    assert.equal(await call(h["tool.execute.before"], { tool: "bash" }, out), "ok");
  }
});
