import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const adapter = readFileSync(new URL("../src/adapters/analysisMemory.ts", import.meta.url), "utf8");
const hook = readFileSync(new URL("../src/hooks/useAnalysisMemory.ts", import.meta.url), "utf8");
const panel = readFileSync(new URL("../src/components/analysis-memory/AnalysisMemoryPanel.tsx", import.meta.url), "utf8");
const processingPage = readFileSync(new URL("../src/pages/ProcessingMonitorPage.tsx", import.meta.url), "utf8");
const reviewPage = readFileSync(new URL("../src/pages/ReviewCenterPage.tsx", import.meta.url), "utf8");

assert.match(adapter, /Promise\.allSettled/, "independent reads must keep candidates visible without canonical");
assert.match(adapter, /state_kind !== "accepted_canonical" \|\| !canonicalState\.publish_allowed/, "canonical projection must fail closed");
assert.match(adapter, /X-Finance-Analysis-Memory-Token/, "review action must carry the dedicated write token");
assert.match(adapter, /stateScope=/, "all asset reads must send an explicit state scope");
assert.match(adapter, /state_scope: params\.stateScope/, "candidate acceptance must bind the selected scope");
assert.match(adapter, /state_scope 不匹配/, "frontend adapter must fail closed on cross-scope payloads");
assert.match(hook, /const requestGenerationRef = useRef\(0\)/, "reads must use a monotonic request generation");
assert.match(hook, /requestGenerationRef\.current === requestGeneration/, "stale reads must fail the generation guard");
assert.match(hook, /currentScopeRef\.current === requestedScope/, "read completion must still match the requested scope");
assert.ok((hook.match(/if \(!isCurrentRequest\(\)\) return;/g) ?? []).length >= 2, "stale read success and failure must not update state");
assert.match(hook, /if \(isCurrentRequest\(\)\) setIsLoading\(false\)/, "stale reads must not clear the active loading state");
assert.match(hook, /currentScopeRef\.current !== stateScope \|\| currentAssetRef\.current !== asset/, "a stale review callback must not start an old-scope write");
assert.match(hook, /currentScopeRef\.current === acceptScope && currentAssetRef\.current === acceptAsset/, "candidate acceptance must re-check scope before refetch");
assert.match(panel, /正式 accepted canonical/, "panel must label the only official state");
assert.match(panel, /candidate \/ 待复核/, "panel must isolate candidate state");
assert.match(panel, /blocked \/ 不可采用/, "panel must isolate blocked state");
assert.match(panel, /ContextBundle token composition/, "panel must expose bundle token composition");
assert.match(panel, /Analysis Memory state scope/, "panel must expose a scope selector");
assert.match(panel, /weekly_fundamental/, "panel must expose all persisted state scopes");
assert.match(processingPage, /<AnalysisMemoryPanel \/>/, "Processing Monitor must render state observability");
assert.match(reviewPage, /<AnalysisMemoryPanel allowReview \/>/, "Review Center must render permission-gated review controls");

console.log("analysis-memory frontend contract: ok");
