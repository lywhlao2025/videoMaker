import fs from "node:fs";
import path from "node:path";

const marker = "lywhlao-http-failover-policy-v1";
const managedNodeRoot = process.env.OPENCLAW_MANAGED_NODE_ROOT || "/root/.openclaw/tools/node";
const openClawRoot = process.env.OPENCLAW_INSTALL_ROOT || path.join(fs.realpathSync(managedNodeRoot), "lib/node_modules/openclaw");
const distDir = path.join(openClawRoot, "dist");
const policyPath = process.env.OPENCLAW_FAILOVER_POLICY_PATH || "/root/.openclaw/failover-policy.json";
const forbiddenStatuses = new Set([401, 402, 403, 429]);
const allowedReasons = new Set(["timeout", "server_error", "overloaded"]);

function validatePolicy() {
  const raw = fs.readFileSync(policyPath, "utf8");
  const policy = JSON.parse(raw);
  if (policy.version !== 1) throw new Error("policy.version must be 1");
  if (policy.mode !== "http_status_allowlist") throw new Error("policy.mode must be http_status_allowlist");
  if (typeof policy.enabled !== "boolean") throw new Error("policy.enabled must be boolean");
  if (!Array.isArray(policy.switchHttpStatuses)) throw new Error("switchHttpStatuses must be an array");
  if (!allowedReasons.has(policy.failoverReason)) throw new Error("failoverReason must be timeout, server_error, or overloaded");

  const seen = new Set();
  for (const status of policy.switchHttpStatuses) {
    if (!Number.isInteger(status) || status < 400 || status > 599) {
      throw new Error(`invalid switch HTTP status: ${status}`);
    }
    if (forbiddenStatuses.has(status)) {
      throw new Error(`HTTP ${status} cannot be configured for automatic account switching`);
    }
    if (seen.has(status)) throw new Error(`duplicate switch HTTP status: ${status}`);
    seen.add(status);
  }
  return policy;
}

function findTarget() {
  const matches = fs.readdirSync(distDir)
    .filter((name) => /^errors-.*\.js$/.test(name))
    .map((name) => path.join(distDir, name))
    .filter((file) => {
      const source = fs.readFileSync(file, "utf8");
      return source.includes("function classifyFailoverSignal(signal) {") && source.includes("classifyFailoverSignal as a");
    });
  if (matches.length !== 1) throw new Error(`expected one OpenClaw error classifier, found ${matches.length}`);
  return matches[0];
}

function patchTarget(target) {
  const source = fs.readFileSync(target, "utf8");
  if (source.includes(marker)) {
    if (!source.includes("classifyConfiguredHttpFailoverStatus(inferSignalStatus(signal))")) {
      throw new Error("policy marker exists but classifier hook is missing");
    }
    return "already-patched";
  }

  const needle = "function classifyFailoverSignal(signal) {\n";
  const index = source.indexOf(needle);
  if (index < 0) throw new Error("OpenClaw classifier signature changed; refusing unsafe patch");

  const helper = `// ${marker}\nfunction classifyConfiguredHttpFailoverStatus(status) {\n\tif (typeof status !== "number" || !Number.isFinite(status)) return null;\n\tconst configuredPath = process.env.OPENCLAW_FAILOVER_POLICY_PATH;\n\tif (!configuredPath) return null;\n\ttry {\n\t\tconst fsBuiltin = process.getBuiltinModule("fs");\n\t\tconst policy = JSON.parse(fsBuiltin.readFileSync(configuredPath, "utf8"));\n\t\tif (policy.enabled !== true || policy.mode !== "http_status_allowlist") return { handled: true, classification: null };\n\t\tif (!Array.isArray(policy.switchHttpStatuses) || !policy.switchHttpStatuses.includes(status)) return { handled: true, classification: null };\n\t\treturn { handled: true, classification: toReasonClassification(policy.failoverReason || "timeout") };\n\t} catch {\n\t\treturn { handled: true, classification: null };\n\t}\n}\n`;
  const hook = `${needle}\tconst configuredHttpDecision = classifyConfiguredHttpFailoverStatus(inferSignalStatus(signal));\n\tif (configuredHttpDecision?.handled) return configuredHttpDecision.classification;\n`;
  const patched = source.slice(0, index) + helper + source.slice(index).replace(needle, hook);
  const backup = `${target}.failover-policy.original`;
  if (!fs.existsSync(backup)) fs.copyFileSync(target, backup);
  const temp = `${target}.failover-policy.tmp`;
  fs.writeFileSync(temp, patched, { mode: fs.statSync(target).mode });
  fs.renameSync(temp, target);
  return "patched";
}

const policy = validatePolicy();
const target = findTarget();
const result = patchTarget(target);
console.log(JSON.stringify({ ok: true, result, target, switchHttpStatuses: policy.switchHttpStatuses }));
