/**
 * opencode-staged-planning — the package's one OpenCode plugin entry.
 *
 * Load it by its local path in the config's `plugin` array, or by the package name.
 * It does two things.
 *
 * 1. REGISTERS the package's skills, agents and commands from its `config` hook, the
 *    route hosts/opencode/host.yaml `install_shape` records:
 *      skills    <package>/skills is added to the config's skills paths
 *                (`skills: [...]` or `skills: {paths: [...]}`, whichever the config holds);
 *      agents    each agents/<name>.md becomes cfg.agent[<name>]: its frontmatter is the
 *                agent's config, its body the agent's prompt, with `<planning-plugin>`
 *                written as the package's folder (commands get the same);
 *      commands  each commands/<name>.md becomes cfg.command[<name>]: its frontmatter is
 *                the command's config, its body the command's template.
 *      reads     `permission.external_directory` gains `<package>/**: allow`. The skills and
 *                agents read files across the package (hooks/, references/, lib/), and
 *                OpenCode otherwise allows only each skill's own folder outside the
 *                workspace: `opencode run` auto-rejects the rest. The rule is merged into
 *                what the user set and names only the package's folder (see allowPackage).
 *    A name the user's own config already defines is left alone: the user's copy wins.
 *    The hook never throws, because a throw there could stop OpenCode starting. A file it
 *    cannot read is reported on stderr by name and not registered; the package's suite
 *    checks that every shipped file registers.
 *
 * 2. GUARDS AND LOGS through the two adapters: proof-guard.ts (a `bash` call the commit
 *    gate denies throws, which blocks it) and dispatch-log.ts (a `task` dispatch, start and
 *    stop are logged, and the logger never throws).
 *
 * This module exports exactly one function, because OpenCode calls every function a plugin
 * module exports as a plugin.
 *
 * Frontmatter is read by a small YAML subset, enough for the files this package ships:
 * `key: value` lines, nested maps by indentation, quoted keys and values, and `>`/`|`
 * block scalars. A list, a flow collection, an anchor, an alias, a tag or a tab indent is
 * refused rather than guessed at.
 *
 * Erasable TypeScript only, as proof-guard.ts.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createDispatchLog } from "./dispatch-log.ts";
import { createProofGuard } from "./proof-guard.ts";

type Ctx = { directory?: string; worktree?: string };
type YamlMap = Record<string, unknown>;

// The package's folder, with no trailing separator.
const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url)).replace(/\/+$/, "");
const LABEL = "opencode-staged-planning";

// ---- the YAML subset ---------------------------------------------------------------

const KEY_RE = /^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s"'#\-?:[\]{},&*!|>%@`][^:]*?)\s*:(?:\s+(.*))?$/;

function fail(n: number, why: string): never {
  throw new Error(`frontmatter line ${n}: ${why}`);
}

function unquote(s: string, n: number): string {
  if (s.startsWith('"')) {
    try {
      return JSON.parse(s);
    } catch {
      fail(n, `unsupported escape in ${s}`);
    }
  }
  if (s.startsWith("'")) return s.slice(1, -1).replace(/''/g, "'");
  return s;
}

function scalar(raw: string, n: number): unknown {
  const s = raw.trim();
  const dq = s.match(/^("(?:[^"\\]|\\.)*")\s*(?:#.*)?$/);
  if (dq) return unquote(dq[1], n);
  const sq = s.match(/^('(?:[^']|'')*')\s*(?:#.*)?$/);
  if (sq) return unquote(sq[1], n);
  if (/^["']/.test(s)) fail(n, "unterminated quoted value");
  const cut = s.search(/\s#/);
  const v = cut >= 0 ? s.slice(0, cut).trimEnd() : s;
  if (/^[[\]{}&*!%@`|>]/.test(v) || /^-(\s|$)/.test(v)) {
    fail(n, `unsupported value ${JSON.stringify(v)} (a list, flow collection, anchor, alias or tag)`);
  }
  if (v === "true") return true;
  if (v === "false") return false;
  if (v === "null" || v === "~") return null;
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  return v;
}

function parseYaml(src: string, firstLine: number): YamlMap {
  const lines = src.split("\n");
  let i = 0;
  const indentOf = (l: string) => (l.match(/^ */) as RegExpMatchArray)[0].length;
  const blank = (l: string) => /^\s*(#.*)?$/.test(l);

  function blockScalar(style: string, chomp: string, parent: number): string {
    const body: string[] = [];
    let bi = -1;
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "") { body.push(""); i++; continue; }
      const ind = indentOf(l);
      if (ind <= parent) break;
      if (/^ *\t/.test(l)) fail(firstLine + i, "tab indentation");
      if (bi < 0) bi = ind;
      if (ind < bi) fail(firstLine + i, "block scalar line indented less than its first line");
      body.push(l.slice(bi));
      i++;
    }
    let trail = 0;
    while (body.length && body[body.length - 1] === "") { body.pop(); trail++; }
    let text = "";
    if (style === "|") {
      text = body.join("\n");
    } else {
      let blanks = 0;
      let first = true;
      for (const l of body) {
        if (l === "") { blanks++; continue; }
        text += first ? l : blanks ? "\n".repeat(blanks) + l : " " + l;
        first = false;
        blanks = 0;
      }
    }
    if (!body.length) return "";
    if (chomp === "-") return text;
    if (chomp === "+") return text + "\n".repeat(trail + 1);
    return text + "\n";
  }

  function block(indent: number): YamlMap {
    const out: YamlMap = {};
    while (i < lines.length) {
      const l = lines[i];
      if (blank(l)) { i++; continue; }
      if (/^ *\t/.test(l)) fail(firstLine + i, "tab indentation");
      const ind = indentOf(l);
      if (ind < indent) return out;
      if (ind > indent) fail(firstLine + i, "unexpected indentation");
      const m = l.slice(ind).match(KEY_RE);
      if (!m) fail(firstLine + i, `not a "key: value" line: ${l.trim()}`);
      const key = unquote(m[1], firstLine + i);
      if (Object.prototype.hasOwnProperty.call(out, key)) fail(firstLine + i, `duplicate key ${key}`);
      const rest = (m[2] ?? "").trim();
      const at = firstLine + i;
      i++;
      if (rest === "" || rest.startsWith("#")) {
        let j = i;
        while (j < lines.length && blank(lines[j])) j++;
        if (j < lines.length && indentOf(lines[j]) > indent) {
          i = j;
          out[key] = block(indentOf(lines[j]));
        } else {
          out[key] = null;
        }
      } else {
        const bs = rest.match(/^([|>])([-+]?)\s*(?:#.*)?$/);
        out[key] = bs ? blockScalar(bs[1], bs[2], indent) : scalar(rest, at);
      }
    }
    return out;
  }

  return block(0);
}

/** {data, body} of a Markdown file with optional `---` frontmatter; throws on an unsupported shape. */
function readMarkdown(text: string): { data: YamlMap; body: string } {
  const t = text.replace(/^﻿/, "").replace(/\r\n/g, "\n");
  if (!/^---[ \t]*\n/.test(t)) return { data: {}, body: t.trim() };
  const m = t.match(/^---[ \t]*\n(?:([\s\S]*?)\n)?---[ \t]*(?:\n|$)/);
  if (!m) throw new Error("frontmatter has no closing ---");
  return { data: parseYaml(m[1] ?? "", 2), body: t.slice(m[0].length).trim() };
}

// ---- registration ------------------------------------------------------------------

function entries(dir: string): Array<{ name: string; file: string }> {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isFile() && d.name.endsWith(".md"))
    .map((d) => ({ name: d.name.slice(0, -3), file: join(dir, d.name) }))
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

function report(what: string, why: unknown): void {
  try {
    console.error(`${LABEL}: not registered: ${what}: ${why instanceof Error ? why.message : String(why)}`);
  } catch {
    // stderr gone: nothing else to tell
  }
}

// An agent runs apart from the package's files, and a headless read outside the folders the
// config allows is refused: for an agent that refusal ends it. So `<planning-plugin>` in an
// agent's prompt or a command's template is written as the package's own folder, the one
// folder allowPackage lets reads enter.
const PLACEHOLDER = "<planning-plugin>";

function registerKind(cfg: any, key: "agent" | "command", dir: string, field: "prompt" | "template",
                      root: string): void {
  const list = entries(dir);
  if (!list.length) return;
  if (cfg[key] === undefined || cfg[key] === null) cfg[key] = {};
  if (typeof cfg[key] !== "object" || Array.isArray(cfg[key])) {
    report(`${key} entries`, `the config's ${key} is not a map`);
    return;
  }
  for (const { name, file } of list) {
    try {
      const { data, body } = readMarkdown(readFileSync(file, "utf8"));
      if (!body) throw new Error(`empty ${field}`);
      if (Object.prototype.hasOwnProperty.call(cfg[key], name)) continue;
      cfg[key][name] = { ...data, [field]: body.split(PLACEHOLDER).join(root) };
    } catch (e) {
      report(`${key === "agent" ? "agents" : "commands"}/${name}.md`, e);
    }
  }
}

function registerSkills(cfg: any, dir: string): void {
  if (!existsSync(dir)) return;
  const s = cfg.skills;
  if (s === undefined || s === null) {
    cfg.skills = { paths: [dir] };
  } else if (Array.isArray(s)) {
    if (!s.includes(dir)) s.push(dir);
  } else if (typeof s === "object") {
    if (s.paths === undefined || s.paths === null) s.paths = [];
    if (!Array.isArray(s.paths)) return report("skills", "the config's skills.paths is not a list");
    if (!s.paths.includes(dir)) s.paths.push(dir);
  } else {
    report("skills", "the config's skills is neither a list nor a map");
  }
}

const ACTIONS = new Set(["allow", "ask", "deny"]);
const isMap = (v: unknown) => typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * Adds `<root>/**: allow` to permission.external_directory, merged into what the user set.
 * OpenCode applies the last rule that matches, so the order of the rules is kept:
 *   - no permission, or no external_directory: the one rule is added;
 *   - a blanket deny wins: `"deny"` for the whole config or for external_directory, or a
 *     `*: deny` rule in either map, and nothing is added. One stderr line says the package
 *     folder is not allowed, so skills that read package files will be refused;
 *   - a whole-config or whole-key `"ask"` is kept as the `*` rule, and the package's rule
 *     follows it; `"allow"` already allows the folder, so nothing changes;
 *   - a map: a rule the user wrote for this exact pattern wins, untouched. Otherwise the
 *     package's rule goes before the user's first rule inside the package folder, so a
 *     narrower rule of the user's there still decides, else at the end.
 * It never adds a rule for any path but the package's folder.
 */
function deniedByUser(root: string): void {
  report("permission", `the config denies external_directory, so ${root} is not allowed: `
    + "skills that read package files (hooks/, references/, lib/) will be refused");
}

function allowPackage(cfg: any, root: string): void {
  const pattern = `${root}/**`;
  const p = cfg.permission;
  if (p === undefined || p === null) {
    cfg.permission = { external_directory: { [pattern]: "allow" } };
    return;
  }
  if (typeof p === "string") {
    if (!ACTIONS.has(p)) return report("permission", "the config's permission is not an action");
    if (p === "deny") return deniedByUser(root);
    if (p !== "allow") cfg.permission = { "*": p, external_directory: { [pattern]: "allow" } };
    return;
  }
  if (!isMap(p)) return report("permission", "the config's permission is neither an action nor a map");
  const ed = p.external_directory;
  if (ed === undefined || ed === null) {
    if (p["*"] === "deny") return deniedByUser(root);
    p.external_directory = { [pattern]: "allow" };
    return;
  }
  if (typeof ed === "string") {
    if (!ACTIONS.has(ed)) return report("permission", "permission.external_directory is not an action");
    if (ed === "deny") return deniedByUser(root);
    if (ed !== "allow") p.external_directory = { "*": ed, [pattern]: "allow" };
    return;
  }
  if (!isMap(ed)) return report("permission", "permission.external_directory is neither an action nor a map");
  if (Object.prototype.hasOwnProperty.call(ed, pattern)) return;
  if (ed["*"] === "deny") return deniedByUser(root);
  const rules = Object.entries(ed);
  const at = rules.findIndex(([k]) => k.startsWith(`${root}/`));
  rules.splice(at < 0 ? rules.length : at, 0, [pattern, "allow"]);
  p.external_directory = Object.fromEntries(rules);
}

function register(cfg: any, root: string): void {
  if (!cfg || typeof cfg !== "object") return;
  for (const step of [
    () => allowPackage(cfg, root),
    () => registerSkills(cfg, join(root, "skills")),
    () => registerKind(cfg, "agent", join(root, "agents"), "prompt", root),
    () => registerKind(cfg, "command", join(root, "commands"), "template", root),
  ]) {
    try {
      step();
    } catch (e) {
      report("package", e);
    }
  }
}

// ---- the plugin --------------------------------------------------------------------

export const StagedPlanning = async (ctx: Ctx) => {
  const guard = await createProofGuard()(ctx);
  const log = await createDispatchLog()(ctx);
  return {
    config: async (cfg: any): Promise<void> => {
      try {
        register(cfg, PACKAGE_ROOT);
      } catch (e) {
        report("package", e);
      }
    },
    event: log.event,
    "tool.execute.before": async (input: { tool?: string }, output: { args?: any }): Promise<void> => {
      await log["tool.execute.before"](input, output);
      await guard["tool.execute.before"](input, output);
    },
    "tool.execute.after": log["tool.execute.after"],
  };
};
