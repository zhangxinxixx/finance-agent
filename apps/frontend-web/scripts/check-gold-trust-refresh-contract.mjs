import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, "src", relativePath), "utf8");
}

function transpile(source, filename) {
  return ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
    fileName: filename,
  }).outputText;
}

const frame = read("components/gold-mainlines/GoldMainlinePageFrame.tsx");
const helperStart = frame.indexOf("const SOURCE_LABELS");
const helperEnd = frame.indexOf("\nexport function GoldReadTimeSourceHealthBanner", helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, "gold trust helper boundary exists");
const helperJavaScript = transpile(
  frame.slice(helperStart, helperEnd).replaceAll("export function", "function"),
  "goldMainlineTrust.ts",
);
const helpers = new Function(
  `${helperJavaScript}; return { sourceHealthStatusLabel, isGoldDecisionBlocked, goldDecisionTrustLabel, goldDecisionTrustNote, shouldShowGoldSourceHealthBanner, suppressRepeatedSourceReason };`,
)();

assert.equal(helpers.sourceHealthStatusLabel("ready"), "可用");
assert.equal(helpers.sourceHealthStatusLabel("degraded"), "降级");
assert.equal(helpers.sourceHealthStatusLabel("blocked"), "阻断");
assert.equal(
  helpers.shouldShowGoldSourceHealthBanner({ overall_status: "ready", can_emit_strong_conclusion: true }, []),
  false,
  "healthy ready source health is not a warning",
);
assert.equal(
  helpers.shouldShowGoldSourceHealthBanner({ overall_status: "degraded", can_emit_strong_conclusion: true }, []),
  true,
  "degraded source health remains visible",
);
assert.equal(
  helpers.shouldShowGoldSourceHealthBanner({ overall_status: "blocked", can_emit_strong_conclusion: false }, []),
  true,
  "blocked source health remains visible",
);
assert.equal(helpers.shouldShowGoldSourceHealthBanner(null, []), false, "absent source health has no fabricated warning");

const blockedHealth = {
  overall_status: "ready",
  can_emit_strong_conclusion: false,
};
assert.equal(helpers.isGoldDecisionBlocked(blockedHealth), true);
assert.equal(helpers.goldDecisionTrustLabel(blockedHealth), "历史复核结果");
assert.match(helpers.goldDecisionTrustNote(blockedHealth), /历史复核/);

assert.equal(
  helpers.goldDecisionTrustLabel({ overall_status: "ready", can_emit_strong_conclusion: true }),
  "当前可用结果",
);
assert.equal(
  helpers.goldDecisionTrustLabel({ overall_status: "ready" }),
  "可信度未确认",
  "missing can_emit must not become current result",
);
assert.equal(
  helpers.goldDecisionTrustLabel({ overall_status: "error", can_emit_strong_conclusion: true }),
  "可信度未确认",
  "unknown health status must not become current result",
);
assert.equal(
  helpers.goldDecisionTrustLabel({ overall_status: "degraded", can_emit_strong_conclusion: true }),
  "降级复核结果",
);
assert.equal(
  helpers.goldDecisionTrustLabel({ overall_status: "ready", can_emit_strong_conclusion: true }, { isRefreshing: true }),
  "上次读取结果·仅供复核",
);
assert.match(
  helpers.goldDecisionTrustNote({ overall_status: "ready", can_emit_strong_conclusion: true }, { refreshError: "HTTP 500" }),
  /上次成功读取结果/,
);
assert.equal(helpers.goldDecisionTrustLabel(null), "可信度未确认");
assert.match(helpers.goldDecisionTrustNote(null), /未完整确认/);
assert.equal(
  helpers.suppressRepeatedSourceReason("xauusd_price: integrity conflict", new Set(["xauusd_price"])),
  false,
  "an unknown risk must remain visible",
);

const hook = read("hooks/useGoldMainlines.ts");
const failureStart = hook.indexOf("export function resolveGoldRefreshFailure");
const failureEnd = hook.indexOf("\n\nexport function useGoldMainlines", failureStart);
assert.ok(failureStart >= 0 && failureEnd > failureStart, "refresh failure helper boundary exists");
const failureJavaScript = transpile(
  hook.slice(failureStart, failureEnd).replace("export function", "function"),
  "useGoldMainlines.ts",
);
const resolveGoldRefreshFailure = new Function(
  `${failureJavaScript}; return resolveGoldRefreshFailure;`,
)();
const previousDto = { status: "available", run_id: "previous-run" };
const refresh500 = new Error("HTTP 500");
const retained = resolveGoldRefreshFailure(previousDto, refresh500);
assert.strictEqual(retained.data, previousDto, "HTTP 500 keeps the exact last successful DTO");
assert.strictEqual(retained.error, refresh500, "refresh error remains observable");
assert.equal(resolveGoldRefreshFailure(null, refresh500).data, null, "initial failure has no stale DTO");

for (const page of ["pages/GoldMainlinesPage.tsx", "pages/RatesDollarPage.tsx", "pages/OilGeopoliticsPage.tsx"]) {
  const source = read(page);
  assert.match(source, /if \(isLoading && !data\)/, `${page} preserves body while refreshing`);
  assert.match(source, /if \(isError && !data\)/, `${page} only replaces the page on initial failure`);
  assert.match(source, /sourceHealth=\{data\.read_time_source_health\}/, `${page} passes source health to the gate`);
  assert.match(source, /refreshError=\{refreshError\}/, `${page} exposes refresh failure`);
  assert.match(source, /lastSuccessfulAt=\{lastSuccessfulAt\}/, `${page} exposes review time`);
}

assert.match(read("pages/RatesDollarPage.tsx"), /formatGoldVerificationStatusLabel\(item\.status\)/);
assert.match(read("components/oil-geopolitics/OilGeoVerificationCard.tsx"), /formatGoldVerificationStatusLabel\(item\.status\)/);
assert.match(read("components/oil-geopolitics/SafeHavenVsInflationSplit.tsx"), /formatGoldConflictStatusLabel\(conflict\?\.status\)/);
assert.match(read("components/oil-geopolitics/WarOilRateChainPanel.tsx"), /getStatusLabel\(step\.status \?\? chain\.status, "data"\)/);
assert.match(read("components/gold-mainlines/GoldMainlinePageFrame.tsx"), /页面上次成功读取于：/);
assert.doesNotMatch(read("components/gold-mainlines/GoldMainlinePageFrame.tsx"), /复核时间：/);
for (const page of ["pages/GoldMainlinesPage.tsx", "pages/RatesDollarPage.tsx", "pages/OilGeopoliticsPage.tsx"]) {
  const source = read(page);
  assert.match(source, /decisionTrustLabel=\{decisionTrustLabel\}/, `${page} marks the hero trust state`);
  assert.match(source, /decisionTrustNote=\{decisionTrustNote\}/, `${page} explains the hero trust state`);
}

const marketHeader = read("components/market-monitor/MarketMonitorHeaderSections.tsx");
assert.match(marketHeader, /realtimeRegime\.available === true/);
assert.match(marketHeader, /: "待确认"/);
assert.match(marketHeader, /实时阶段数据不可用/);

const calendarBrief = read("components/market-monitor/MarketMonitorOverviewBlocks.tsx");
assert.match(calendarBrief, /realtimeRegime\?\.available !== true/);
assert.match(calendarBrief, /实时阶段/);
assert.match(calendarBrief, /formatRealtimeRegimeLabel/);

console.log("Gold trust, refresh retention, and regime availability contract OK");
