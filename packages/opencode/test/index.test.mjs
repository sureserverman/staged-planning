// index.ts: the one plugin entry. Its config hook registers the package's skills path,
// agents and commands in the shape the OpenCode probe measured (a skills path in the
// config, agents and commands added to cfg.agent / cfg.command); it never throws, and a
// file it cannot read is named and skipped.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, existsSync, readdirSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { call, loadIndex, makePackage, pluginOf, SHIPPED } from "./helpers.mjs";

const AGENT = `---
description: >
  Reviews a finished task against its plan.
  Read-only: it reports findings.

  Cites sources.
mode: subagent
permission:
  edit: deny
  webfetch: allow
  bash:
    "*": ask
    'git diff *': allow
    git log*: allow  # a trailing comment
---

You are the reviewer. Read the diff.
`;
const COMMAND = `---
description: "Deferred-work register: add | list | remove"
subtask: false
---
Load the backlog skill by name and run: $ARGUMENTS
`;
const SKILL = "---\nname: demo\ndescription: Demo skill. Invoke it by name.\n---\n\nDo the demo.\n";

const fixture = () => makePackage({ files: {
  "skills/demo/SKILL.md": SKILL,
  "agents/reviewer.md": AGENT,
  "commands/backlog.md": COMMAND,
} });

async function configured(root, cfg = {}) {
  const h = await pluginOf(await loadIndex(root))({ directory: root, worktree: root });
  assert.equal(await call(h.config, cfg), "ok");
  return cfg;
}

test("an agent's or command's <planning-plugin> registers as the package's own folder, which reads may enter", async () => {
  const root = makePackage({ files: {
    "agents/reader.md": "---\nmode: subagent\n---\n\nRead <planning-plugin>/references/x.md, then <planning-plugin>/skills/a/SKILL.md.\n",
    "commands/run.md": "---\ndescription: run\n---\nRun python3 <planning-plugin>/scripts/x.py\n",
  } });
  const cfg = await configured(root);
  const pkg = realpathSync(root);
  assert.equal(cfg.agent.reader.prompt, `Read ${pkg}/references/x.md, then ${pkg}/skills/a/SKILL.md.`);
  assert.equal(cfg.command.run.template, `Run python3 ${pkg}/scripts/x.py`);
  assert.ok(Object.keys(cfg.permission.external_directory).includes(`${pkg}/**`));
});

test("the module exports exactly one function: OpenCode calls each exported function as a plugin", async () => {
  const mod = await loadIndex(fixture());
  assert.equal(Object.values(mod).filter((v) => typeof v === "function").length, 1);
});

test("config registers the skills path, each agent and each command", async () => {
  const root = fixture();
  const cfg = await configured(root);
  assert.deepEqual(cfg.skills, { paths: [join(root, "skills")] });
  assert.deepEqual(cfg.agent.reviewer, {
    description: "Reviews a finished task against its plan. Read-only: it reports findings.\nCites sources.\n",
    mode: "subagent",
    permission: { edit: "deny", webfetch: "allow", bash: { "*": "ask", "git diff *": "allow", "git log*": "allow" } },
    prompt: "You are the reviewer. Read the diff.",
  });
  assert.deepEqual(cfg.command.backlog, {
    description: "Deferred-work register: add | list | remove",
    subtask: false,
    template: "Load the backlog skill by name and run: $ARGUMENTS",
  });
});

test("the skills path joins whichever form the config holds, once", async () => {
  const root = fixture();
  const dir = join(root, "skills");
  const list = await configured(root, { skills: ["/elsewhere"] });
  assert.deepEqual(list.skills, ["/elsewhere", dir]);
  const map = await configured(root, { skills: { paths: ["/elsewhere"], urls: ["u"] } });
  assert.deepEqual(map.skills, { paths: ["/elsewhere", dir], urls: ["u"] });
  const again = await configured(root, map);
  assert.deepEqual(again.skills.paths, ["/elsewhere", dir]);
});

test("reads across the package folder are allowed: permission.external_directory gains <pkg>/**", async () => {
  const root = fixture();
  const own = `${root}/**`;
  const cfg = await configured(root);
  assert.deepEqual(cfg.permission, { external_directory: { [own]: "allow" } });
});

test("the package's read rule merges into the user's permission, and names only the package", async () => {
  const root = fixture();
  const own = `${root}/**`;
  const cases = [
    // [what the user set, what the config must hold after]
    [{ edit: "deny" }, { edit: "deny", external_directory: { [own]: "allow" } }],
    [{ external_directory: "allow" }, { external_directory: "allow" }],
    [{ external_directory: { "/data/**": "allow", "*": "ask" } },
     { external_directory: { "/data/**": "allow", "*": "ask", [own]: "allow" } }],
    // The user's rule for this exact pattern wins.
    [{ external_directory: { [own]: "deny" } }, { external_directory: { [own]: "deny" } }],
    // A narrower rule of the user's inside the package still decides: it stays after ours.
    [{ external_directory: { "*": "ask", [`${root}/secret/**`]: "deny" } },
     { external_directory: { "*": "ask", [own]: "allow", [`${root}/secret/**`]: "deny" } }],
  ];
  for (const [mine, want] of cases) {
    const cfg = await configured(root, { permission: structuredClone(mine) });
    assert.deepEqual(cfg.permission, want, JSON.stringify(mine));
    const ed = cfg.permission.external_directory;
    if (ed && typeof ed === "object") assert.deepEqual(Object.keys(ed), Object.keys(want.external_directory));
  }
  for (const [mine, want] of [["allow", "allow"], ["ask", { "*": "ask", external_directory: { [own]: "allow" } }]]) {
    const cfg = await configured(root, { permission: mine });
    assert.deepEqual(cfg.permission, want, mine);
  }
  // Never wider than the package: every rule added is the package's own.
  const before = { "/data/**": "allow" };
  const cfg = await configured(root, { permission: { external_directory: { ...before } } });
  const added = Object.keys(cfg.permission.external_directory).filter((k) => !(k in before));
  assert.deepEqual(added, [own]);
  assert.ok(!own.startsWith("/**") && own.length > 3);
});

// A blanket deny of the user's wins: nothing is added, and one stderr line says so.
for (const [label, mine] of [
  ["permission: \"deny\"", "deny"],
  ["external_directory: \"deny\"", { external_directory: "deny" }],
  ["an external_directory map whose * rule is deny", { external_directory: { "/data/**": "allow", "*": "deny" } }],
  ["a permission map whose * rule is deny", { "*": "deny", edit: "ask" }],
]) {
  test(`a blanket deny wins (${label}): no allow is added, and stderr says so`, async () => {
    const root = fixture();
    const errors = [];
    const orig = console.error;
    console.error = (...a) => errors.push(a.join(" "));
    let cfg;
    try {
      cfg = await configured(root, { permission: structuredClone(mine) });
    } finally {
      console.error = orig;
    }
    assert.deepEqual(cfg.permission, mine);
    const said = errors.filter((e) => e.includes(root) && /not allowed/.test(e) && /refused/.test(e));
    assert.equal(said.length, 1, `stderr was ${JSON.stringify(errors)}`);
  });
}

test("a name the user's config already defines is left alone", async () => {
  const root = fixture();
  const mine = { prompt: "mine" };
  const cfg = await configured(root, { agent: { reviewer: mine, build: { mode: "primary" } },
                                       command: { backlog: { template: "mine" } } });
  assert.equal(cfg.agent.reviewer, mine);
  assert.deepEqual(cfg.agent.build, { mode: "primary" });
  assert.deepEqual(cfg.command.backlog, { template: "mine" });
});

test("a file in a shape the reader refuses is named on stderr and skipped; the rest register", async () => {
  const root = makePackage({ files: {
    "agents/listy.md": "---\ndescription: d\ntools:\n  - read\n---\nbody\n",
    "agents/anchor.md": "---\ndescription: &a d\n---\nbody\n",
    "agents/unclosed.md": "---\ndescription: d\nbody\n",
    "agents/empty.md": "---\ndescription: d\n---\n",
    "agents/good.md": "---\ndescription: d\nmode: subagent\n---\nbody\n",
    "commands/tabbed.md": "---\npermission:\n\tedit: deny\n---\nbody\n",
  } });
  const errors = [];
  const orig = console.error;
  console.error = (...a) => errors.push(a.join(" "));
  let cfg;
  try {
    cfg = await configured(root);
  } finally {
    console.error = orig;
  }
  assert.deepEqual(Object.keys(cfg.agent), ["good"]);
  assert.deepEqual(cfg.command ?? {}, {});
  for (const f of ["agents/listy.md", "agents/anchor.md", "agents/unclosed.md", "agents/empty.md", "commands/tabbed.md"]) {
    assert.ok(errors.some((e) => e.includes(f)), `no stderr line names ${f}: ${errors.join(" | ")}`);
  }
});

test("config never throws, whatever it is handed", async () => {
  const h = await pluginOf(await loadIndex(fixture()))({});
  for (const cfg of [undefined, null, 5, "x", { agent: "x", command: [], skills: 3 }, { skills: { paths: "x" } }]) {
    const orig = console.error;
    console.error = () => {};
    try {
      assert.equal(await call(h.config, cfg), "ok", JSON.stringify(cfg));
    } finally {
      console.error = orig;
    }
  }
});

// The agents and commands the built package ships, read by the real module.
test("every agent and command this package ships registers", async () => {
  for (const d of ["agents", "commands"]) assert.ok(existsSync(join(SHIPPED, d)), `the package ships no ${d}/`);
  const root = makePackage();
  for (const d of ["agents", "commands"]) cpSync(join(SHIPPED, d), join(root, d), { recursive: true });
  const cfg = {};
  const errors = [];
  const orig = console.error;
  console.error = (...a) => errors.push(a.join(" "));
  try {
    const h = await pluginOf(await loadIndex(root))({ directory: root, worktree: root });
    assert.equal(await call(h.config, cfg), "ok");
  } finally {
    console.error = orig;
  }
  assert.deepEqual(errors, []);
  for (const [d, key] of [["agents", "agent"], ["commands", "command"]]) {
    const names = readdirSync(join(SHIPPED, d)).filter((n) => n.endsWith(".md")).map((n) => n.slice(0, -3)).sort();
    assert.ok(names.length > 0, `${d}/ holds no .md file`);
    assert.deepEqual(Object.keys(cfg[key]).sort(), names);
  }
});
