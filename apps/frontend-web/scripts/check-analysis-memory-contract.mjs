import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const adapter = readFileSync(new URL("../src/adapters/analysisMemory.ts", import.meta.url), "utf8");
const panel = readFileSync(new URL("../src/components/analysis-memory/AnalysisMemoryPanel.tsx", import.meta.url), "utf8");
const processingPage = readFileSync(new URL("../src/pages/ProcessingMonitorPage.tsx", import.meta.url), "utf8");
const reviewPage = readFileSync(new URL("../src/pages/ReviewCenterPage.tsx", import.meta.url), "utf8");

assert.match(adapter, /Promise\.allSettled/, "independent reads must keep candidates visible without canonical");
assert.match(adapter, /state_kind !== "accepted_canonical" \|\| !canonicalState\.publish_allowed/, "canonical projection must fail closed");
assert.match(adapter, /X-Finance-Analysis-Memory-Token/, "review action must carry the dedicated write token");
assert.match(panel, /正式 accepted canonical/, "panel must label the only official state");
assert.match(panel, /candidate \/ 待复核/, "panel must isolate candidate state");
assert.match(panel, /blocked \/ 不可采用/, "panel must isolate blocked state");
assert.match(panel, /ContextBundle token composition/, "panel must expose bundle token composition");
assert.match(processingPage, /<AnalysisMemoryPanel \/>/, "Processing Monitor must render state observability");
assert.match(reviewPage, /<AnalysisMemoryPanel allowReview \/>/, "Review Center must render permission-gated review controls");

console.log("analysis-memory frontend contract: ok");
