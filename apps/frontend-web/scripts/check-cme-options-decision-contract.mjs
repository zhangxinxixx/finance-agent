import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = (relativePath) => readFileSync(join(root, relativePath), "utf8");
const adapter = source("src/adapters/cmeOptions.ts");
const hook = source("src/hooks/useCMEOptionsDecision.ts");
const page = source("src/pages/CMEOptionsPage.tsx");
const workspace = source("src/components/cme-options/CMEOptionsDecisionWorkspace.tsx");

assert.match(adapter, /CME_OPTIONS_DECISION_PATH = "\/api\/options\/decision"/, "decision adapter must use the stable API endpoint");
assert.match(adapter, /schema_version !== "cme_options_decision\.v1"/, "decision adapter must validate the schema version");
assert.match(adapter, /fetchCMEOptionsDecision/, "decision adapter must export a dedicated fetcher");
assert.doesNotMatch(adapter, /loadMockCMEOptions\(\).*decision/s, "decision request must not fall back to snapshot mock data");
assert.match(hook, /fetchCMEOptionsDecision\(date\)/, "decision hook must be date-driven");
assert.match(page, /decisionState\.refetch\(\)/, "page refresh must also refresh decision data");
assert.match(workspace, /oi_by_expiry/, "decision workspace must render OI expiry data");
assert.match(workspace, /key_levels/, "decision workspace must render backend key levels");
assert.match(workspace, /gamma_profile/, "decision workspace must render the backend Gamma Profile");
assert.match(workspace, /intraday_strategy/, "decision workspace must render backend intraday strategy");
assert.match(workspace, /swing_strategy/, "decision workspace must render backend swing strategy");

console.log("CME Options decision frontend contract OK");
