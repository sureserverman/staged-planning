// The npm manifest: name opencode-staged-planning, MIT, the plugin entry, a version the
// build fills from VERSION, and `files` naming exactly the built output (never the suite
// or the template). Checked on the built package (a fresh build when run from the
// sources), and from the sources on the template too.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { BUILT, PKG, REPO, SHIPPED } from "./helpers.mjs";

const manifest = JSON.parse(readFileSync(join(SHIPPED, "package.json"), "utf8"));
const norm = (f) => f.replace(/\/+$/, "");

test("name, licence, module type and entry", () => {
  assert.equal(manifest.name, "opencode-staged-planning");
  assert.equal(manifest.license, "MIT");
  assert.equal(manifest.type, "module");
  assert.equal(manifest.main, "./src/index.ts");
  assert.deepEqual(manifest.exports, { ".": "./src/index.ts" });
  assert.ok(existsSync(join(SHIPPED, "src", "index.ts")));
});

test("the version is the build's to fill, from VERSION", () => {
  assert.match(manifest.version, /^\d+\.\d+\.\d+$/);
  if (!BUILT) {
    assert.equal(JSON.parse(readFileSync(join(PKG, "package.json.tmpl"), "utf8")).version, "{{VERSION}}");
    assert.equal(manifest.version, readFileSync(join(REPO, "VERSION"), "utf8").trim());
  }
});

test("files never ships the suite or the template", () => {
  assert.ok(Array.isArray(manifest.files) && manifest.files.length > 0);
  for (const f of manifest.files.map(norm)) {
    assert.ok(!["test", "package.json.tmpl"].includes(f), `files ships ${f}`);
    assert.ok(!f.includes("*") && !f.startsWith("."), `files entry ${f} is a glob or hidden path`);
  }
  assert.equal(existsSync(join(SHIPPED, "package.json.tmpl")), false, "the template was shipped");
});

test("files names exactly the package's own top-level entries", () => {
  const files = new Set(manifest.files.map(norm));
  const tops = readdirSync(SHIPPED).filter((n) => n !== "test" && n !== "package.json");
  for (const n of tops) assert.ok(files.has(n), `${n} is built but not in files`);
  for (const f of files) assert.ok(existsSync(join(SHIPPED, f)), `files names ${f}, which the build did not produce`);
});
