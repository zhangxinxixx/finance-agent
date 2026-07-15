import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = (relativePath) => readFileSync(join(root, relativePath), "utf8");
const types = source("src/types/shadow-evaluation-history.ts");
const adapter = source("src/adapters/shadowEvaluationHistory.ts");
const hook = source("src/hooks/useShadowEvaluationHistory.ts");
const panel = source("src/components/strategy/ShadowEvaluationHistoryPanel.tsx");
const page = source("src/pages/StrategyPage.tsx");

assert.match(types, /schema_version: "shadow_evaluation_history\.v1"/);
assert.match(types, /accuracy: number \| null/);
assert.match(adapter, /\/api\/shadow-evaluation\/history/);
assert.match(adapter, /raw\.schema_version !== "shadow_evaluation_history\.v1"/);
assert.match(adapter, /account_id/);
assert.match(adapter, /limit/);
assert.match(hook, /cause instanceof ApiError && cause\.status === 404/);
assert.match(hook, /fetchShadowEvaluationHistory\(\)/);
assert.match(page, /<ShadowEvaluationHistoryPanel/);
assert.match(page, /shadowEvaluationHistory\.refetch\(\)/);
assert.match(panel, /暂无可评分样本/);
assert.match(panel, /blocked_count/);
assert.match(panel, /unscorable_count/);
assert.match(panel, /artifact_refs/);
assert.doesNotMatch(panel, /accuracy\s*\?\?\s*0/);
assert.doesNotMatch(panel, /correct_count\s*\/|\/\s*directional_count/);

console.log("Shadow evaluation history frontend contract OK");
