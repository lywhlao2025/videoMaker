import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const managedNodeRoot = process.env.OPENCLAW_MANAGED_NODE_ROOT || "/root/.openclaw/tools/node";
const distDir = path.join(fs.realpathSync(managedNodeRoot), "lib/node_modules/openclaw/dist");
const target = fs.readdirSync(distDir)
  .filter((name) => /^errors-.*\.js$/.test(name))
  .map((name) => path.join(distDir, name))
  .find((file) => fs.readFileSync(file, "utf8").includes("lywhlao-http-failover-policy-v1"));

if (!target) throw new Error("patched classifier not found");
const module = await import(`${pathToFileURL(target).href}?policy-test=${Date.now()}`);
const classify = module.a;
const cases = [
  { status: 408, expected: "timeout" },
  { status: 502, expected: "timeout" },
  { status: 503, expected: "timeout" },
  { status: 504, expected: "timeout" },
  { status: 401, expected: null },
  { status: 403, expected: null },
  { status: 429, expected: null },
  { status: 418, expected: null }
];

for (const item of cases) {
  const result = classify({ status: item.status, message: `HTTP ${item.status}` });
  const actual = result?.kind === "reason" ? result.reason : null;
  if (actual !== item.expected) {
    throw new Error(`HTTP ${item.status}: expected ${item.expected}, got ${actual}`);
  }
}

console.log(JSON.stringify({ ok: true, cases }));
