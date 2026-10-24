// The suite's entry. Node 22 runs `node --test <dir>` by loading <dir> as a module, which
// resolves to this file; it imports every *.test.mjs beside it, so a suite added here is
// run without editing this file. Finding none fails: an empty sweep is not a pass.
import { readdirSync } from "node:fs";

const here = new URL("./", import.meta.url);
const suites = readdirSync(here).filter((n) => n.endsWith(".test.mjs")).sort();
if (suites.length === 0) throw new Error("no *.test.mjs suites found beside test/index.js");
for (const f of suites) await import(new URL(f, here).href);
