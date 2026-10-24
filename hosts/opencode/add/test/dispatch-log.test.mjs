// dispatch-log.ts: a task's dispatch, start and stop reach .claude/dispatch-log.jsonl through
// hooks/dispatch-log.sh, and no hook ever throws — a throw from tool.execute.before would
// block the task.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import {
  call, childCreated, loadIndex, logLines, makePackage, newRepo, pluginOf, taskCall, taskDone, bashCall,
} from "./helpers.mjs";

const pkg = makePackage();
const plugin = pluginOf(await loadIndex(pkg));

test("a task's dispatch, start and stop each write one line, start and stop sharing the agent id", async () => {
  const repo = newRepo({ plan: true });
  const h = await plugin({ directory: repo, worktree: repo });
  assert.equal(await call(h["tool.execute.before"], ...taskCall("code-reviewer", "Stage 1 Tier-2 review")), "ok");
  assert.equal(await call(h.event, childCreated("ses_child", { agent: "code-reviewer" })), "ok");
  assert.equal(await call(h["tool.execute.after"], ...taskDone("ses_child")), "ok");
  const lines = logLines(repo);
  assert.deepEqual(lines.map((l) => l.event), ["dispatch", "start", "stop"]);
  // The host's script logs the agent as agent_name.
  assert.equal(lines[0].agent_name, "code-reviewer");
  assert.equal(lines[0].description, "Stage 1 Tier-2 review");
  assert.equal(lines[1].agent_id, "ses_child");
  assert.equal(lines[1].agent_type, "code-reviewer");
  assert.equal(lines[2].agent_id, "ses_child");
});

test("a bash call, a parent session and a non-task tool write nothing", async () => {
  const repo = newRepo({ plan: true });
  const h = await plugin({ directory: repo, worktree: repo });
  assert.equal(await call(h["tool.execute.before"], ...bashCall("echo hi")), "ok");
  const parent = childCreated("ses_parent");
  delete parent.event.properties.info.parentID;
  assert.equal(await call(h.event, parent), "ok");
  assert.equal(await call(h.event, { event: { type: "session.updated", properties: {} } }), "ok");
  const [, out] = taskDone();
  assert.equal(await call(h["tool.execute.after"], { tool: "read", sessionID: "s", callID: "c", args: {} }, out), "ok");
  assert.deepEqual(logLines(repo), []);
});

test("no plan in flight: no log (the script's own inertness)", async () => {
  const repo = newRepo({ plan: false });
  mkdirSync(join(repo, ".claude"), { recursive: true });
  const h = await plugin({ directory: repo, worktree: repo });
  assert.equal(await call(h["tool.execute.before"], ...taskCall()), "ok");
  assert.equal(existsSync(join(repo, ".claude", "dispatch-log.jsonl")), false);
});

test("the project directory is the worktree, not a directory below it", async () => {
  const repo = newRepo({ plan: true });
  const sub = join(repo, "sub");
  mkdirSync(sub);
  const h = await plugin({ directory: sub, worktree: repo });
  assert.equal(await call(h.event, childCreated("ses_w")), "ok");
  assert.deepEqual(logLines(repo).map((l) => l.event), ["start"]);
  assert.equal(existsSync(join(sub, ".claude")), false);
});

test("a malformed payload never throws, from any hook, and logs nothing", async () => {
  const repo = newRepo({ plan: true });
  const h = await plugin({ directory: repo, worktree: repo });
  const circular = { subagent_type: "x", description: "y" };
  circular.self = circular;
  const before = [
    [undefined, undefined], [null, null], [{}, {}], [{ tool: "task" }, undefined], [{ tool: "task" }, null],
    [{ tool: "task" }, { args: null }], [{ tool: "task" }, { args: "a string" }],
    [{ tool: "task" }, { args: circular }],
  ];
  for (const args of before) {
    assert.equal(await call(h["tool.execute.before"], ...args), "ok", `tool.execute.before ${String(args[1]?.args)}`);
  }
  const events = [undefined, null, {}, { event: null }, { event: { type: "session.created" } },
                  { event: { type: "session.created", properties: null } },
                  { event: { type: "session.created", properties: { info: { parentID: "p" } } } },
                  { event: { type: "session.created", properties: { info: { id: 7, parentID: {} } } } }];
  for (const e of events) assert.equal(await call(h.event, e), "ok", `event ${JSON.stringify(e)}`);
  const after = [[undefined, undefined], [{ tool: "task" }, null], [{ tool: "task" }, { metadata: null }],
                 [{ tool: "task" }, { metadata: { sessionId: 42 } }]];
  for (const args of after) assert.equal(await call(h["tool.execute.after"], ...args), "ok");
  // The circular payload is the one task call with a usable shape; nothing else may log.
  assert.ok(logLines(repo).every((l) => l.event === "dispatch"));
});

test("a plugin context with no directory or worktree never throws", async () => {
  for (const ctx of [undefined, null, {}, { worktree: 5 }]) {
    const h = await plugin(ctx);
    assert.equal(await call(h["tool.execute.before"], ...taskCall()), "ok");
    assert.equal(await call(h.event, childCreated()), "ok");
    assert.equal(await call(h["tool.execute.after"], ...taskDone()), "ok");
  }
});

test("a failing or missing script still lets the task run", async () => {
  const repo = newRepo({ plan: true });
  const failing = pluginOf(await loadIndex(makePackage({ hooks: {
    "dispatch-log.sh": "echo boom >&2\necho garbage\nexit 7\n",
    "proof-guard.sh": "exit 0\n",
  } })));
  const missing = pluginOf(await loadIndex(makePackage({ hooks: null })));
  for (const p of [failing, missing]) {
    const h = await p({ directory: repo, worktree: repo });
    assert.equal(await call(h["tool.execute.before"], ...taskCall()), "ok");
    assert.equal(await call(h.event, childCreated()), "ok");
    assert.equal(await call(h["tool.execute.after"], ...taskDone()), "ok");
  }
});
