import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = (relativePath) => readFileSync(join(root, relativePath), "utf8");
const adapter = source("src/adapters/shadowEvaluation.ts");
const hook = source("src/hooks/useShadowEvaluation.ts");
const page = source("src/pages/StrategyPage.tsx");
const panel = source("src/components/strategy/ShadowEvaluationPanel.tsx");
const types = source("src/types/shadow-evaluation.ts");

assert.match(types, /schema_version: "shadow_evaluation_metrics_api\.v1"/, "frontend API type must pin the response schema");
assert.match(types, /accuracy: number \| null/, "accuracy must retain the backend null state");
assert.match(adapter, /SHADOW_EVALUATION_LATEST_PATH = "\/api\/shadow-evaluation\/metrics\/latest"/, "adapter must use the stable latest endpoint");
assert.match(adapter, /raw\.schema_version !== "shadow_evaluation_metrics_api\.v1"/, "adapter must reject incompatible API schemas");
assert.match(adapter, /raw\.schema_version !== "shadow_evaluation_metrics\.v1"/, "adapter must reject incompatible metrics schemas");
assert.match(hook, /fetchLatestShadowEvaluationMetrics\(\)/, "latest hook must request the backend-selected partition");
assert.match(hook, /cause instanceof ApiError && cause\.status === 404/, "404 must map to an unavailable state");
assert.match(page, /<ShadowEvaluationPanel/, "Strategy page must mount the shadow evaluation panel");
assert.match(page, /shadowEvaluation\.refetch\(\)/, "Strategy page refresh must refresh evaluation data");
assert.match(panel, /暂无可评分样本/, "null accuracy must have an explicit no-sample label");
assert.match(panel, /metrics\.directional_count/, "panel must display the backend accuracy denominator");
assert.match(panel, /metrics\.blocked_count/, "panel must display blocked outcomes separately");
assert.match(panel, /metrics\.unscorable_count/, "panel must display unscorable outcomes separately");
assert.match(panel, /metrics\.by_horizon\[horizon\]/, "panel must render backend per-horizon summaries");
assert.doesNotMatch(panel, /accuracy\s*\?\?\s*0/, "null accuracy must never fall back to zero");
assert.doesNotMatch(panel, /correct_count\s*\/|\/\s*metrics\.directional_count/, "frontend must not recalculate accuracy");

console.log("Shadow evaluation frontend contract OK");
