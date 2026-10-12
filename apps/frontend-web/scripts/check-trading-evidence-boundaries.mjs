import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import ts from "typescript";
import * as jsxRuntime from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";

const source = (relativePath) => readFileSync(join(process.cwd(), relativePath), "utf8");
const cme = source("src/adapters/cmeOptions.ts");
const cmePage = source("src/pages/CMEOptionsPage.tsx");
const cmeIdentity = source("src/components/cme-options/cmeDecisionIdentity.ts");
const cmeSections = source("src/components/cme-options/CMEOptionsPageSections.tsx");
const event = source("src/adapters/eventFlow.ts");
const detail = source("src/pages/EventFlowDetailPage.tsx");
const chain = source("src/components/event-flow/EventChainAnalysis.tsx");
const evidenceHook = source("src/hooks/useEventFlowEventEvidence.ts");
const format = source("src/components/event-flow/eventFlowFormat.ts");

assert.doesNotMatch(cme, /loadMockCMEOptions|CME_OPTIONS_MOCK_URL/, "CME failures must not load a bundled snapshot mock");
assert.match(cme, /return createUnavailableResponse\(apiError\)/, "CME 500/503 must become an unavailable read model");
assert.match(cmePage, /const alignedDecision = dateIdentityMismatch \|\| dateIdentityUnverified \|\| decisionRevisionMismatch \|\| decisionRevisionUnverified/, "CME decision must pass both date and revision identity gates");
assert.match(cmePage, /resolveCMETradeDateIdentity\(selectedDate, snapshotTradeDate, decisionTradeDate\)/, "CME page must compare selected, snapshot and decision trade dates");
assert.match(cmePage, /resolveCMEDecisionIdentity\(snapshotIdentityIds, decisionIdentityIds\)/, "CME page must compare snapshot and decision revision identities");
assert.match(cmeIdentity, /everyDecisionRevisionIsPresent/, "CME revision identity must reject a decision carrying an unaligned known snapshot");
assert.match(cmePage, /CMEOptionsKpiStrip snapshot=\{snapshot\} decision=\{alignedDecision\}/, "CME KPI strip must not mix an unaligned decision snapshot");
assert.doesNotMatch(cmePage, /snapshotReportDate\s*&&\s*snapshotReportDate\s*!==\s*selectedDate/, "CME report publication date must not be treated as the trade date");
assert.match(cmePage, /aria-label=\"选择期权交易日\"/, "CME empty/error state must retain a date selector");
assert.match(cmePage, /dateIdentityUnverified/, "CME missing date identity must be visible as unverified");
assert.match(cmePage, /判断主快照：后端未单独提供判断主快照身份/, "CME must disclose that decision primary snapshot identity is not available");
assert.match(cmePage, /当前仅核对来源记录，不能证明完整版本一致/, "CME must avoid presenting source matching as full revision verification");
assert.doesNotMatch(cmeSections, /snapshot\.intent\.confidence\s*\?\?\s*snapshot\.intent\.score/, "CME intent confidence must not borrow the score field");
assert.match(cmeSections, /评分，非概率/, "CME score must be labeled as a non-probability score");
assert.match(event, /fetchJson<Record<string, unknown>>\("\/api\/events\/flow\/overview"\)/, "event overview must use the read-only API client");
assert.doesNotMatch(event, /API 不可用，fallback 到 mock/, "event 500/503 must not fall back to a curated mock");
assert.doesNotMatch(event, /updated_at:\s*\(raw\.updated_at as string\) \?\? new Date\(\)/, "missing source timestamps must not become the browser refresh time");
assert.match(event, /fetchEventFlowEventImpact/, "event detail must expose the impact read model");
assert.match(event, /fetchEventFlowMarketReaction/, "event detail must expose the market-reaction read model");
assert.doesNotMatch(event, /desc:\s*buildChineseSummary\(asString\(e\.title\)/, "English facts must not become inferred causal summaries");
assert.match(event, /desc:\s*toChineseContent\(/, "event descriptions must come from a supplied source field");
assert.match(format, /raw: headline\.raw/, "foreign source headlines retain their original text for evidence");
assert.doesNotMatch(evidenceHook, /Promise\.allSettled/, "a delayed reaction must not hide the completed impact evidence");
assert.match(detail, /isLoading=\{eventEvidence\.impactLoading\}/, "impact loading is independent");
assert.match(detail, /isLoading=\{eventEvidence\.marketReactionLoading\}/, "reaction loading is independent");
assert.doesNotMatch(chain, /45%|strokeDasharray|circumference/, "event chain must not display a fabricated pricing percentage");
assert.match(detail, /尚无窗口样本/, "empty/partial reaction data must be explicitly marked");
assert.match(detail, /当前定价标签：未核验/, "no windows must not be labeled as priced");
assert.match(detail, /displayObservedCount/, "missing confirmation counts must not be rendered as zero");
assert.match(detail, /eventEvidence\.refetch\(\)/, "event refresh must reload the evidence read models with the overview");
assert.match(evidenceHook, /fetchEventFlowMarketReaction/, "detail flow must consume the market-reaction read model");

function loadTranspiledModule(relativePath, dependencies) {
  const output = ts.transpileModule(source(relativePath), {
    fileName: relativePath,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, {
    module,
    exports: module.exports,
    require: (name) => {
      if (dependencies[name]) return dependencies[name];
      throw new Error(`Unexpected runtime dependency in ${relativePath}: ${name}`);
    },
    console,
    Error,
    Promise,
    URL,
    encodeURIComponent,
    setTimeout,
    clearTimeout,
  }, { filename: relativePath });
  return module.exports;
}

function mockResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return payload;
    },
  };
}

let nextResponse = async () => mockResponse({});
const injectedFetchJson = async (path) => {
  const response = await nextResponse(path);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
};
class InjectedApiError extends Error {}
const adapterDependencies = {
  "@/adapters/apiClient": { ApiError: InjectedApiError, fetchJson: injectedFetchJson },
  "@/components/shared/goldMainlineFormat": {
    formatGoldDriverLabel: (value) => value,
    formatGoldMainlineLabel: (value) => value,
    formatGoldNetBiasLabel: (value) => value,
    formatTransmissionPathLabel: (value) => value,
    normalizeGoldMainlineId: (value) => value,
  },
};
const cmeAdapter = loadTranspiledModule("src/adapters/cmeOptions.ts", adapterDependencies);
const eventAdapter = loadTranspiledModule("src/adapters/eventFlow.ts", adapterDependencies);

nextResponse = async () => mockResponse({
  trade_date: "2026-10-02",
  data_source: { product: "OG", status: "FINAL", expiries: [], row_count: 1, report_date: "2026-10-03" },
  gex: { netgex_aggregate: { net_gex: null, net_gex_direction: null, gamma_zero: { method: "" } } },
  wall_scores: [],
  intent: { type: "neutral", score: 0.72, evidence: [] },
  has_data: false,
});
const nullableCme = await cmeAdapter.fetchCMEOptionsData("2026-10-02");
assert.equal(nullableCme.intent.confidence, null, "missing CME confidence must remain null");
assert.equal(nullableCme.intent.score, 0.72, "CME score must remain a score when supplied");
assert.equal(nullableCme.gex.netgex_aggregate.gamma_zero.price, null, "missing gamma zero must remain null");

nextResponse = async () => mockResponse({ trade_date: "2026-10-02", data_source: {}, wall_scores: [], has_data: true });
const unknownCount = await cmeAdapter.fetchCMEOptionsData("2026-10-02");
assert.equal(unknownCount.data_source.row_count, null, "missing sample size is not a measured zero");
nextResponse = async () => mockResponse({ trade_date: "2026-10-02", data_source: { row_count: 0 }, wall_scores: [], has_data: true });
assert.equal((await cmeAdapter.fetchCMEOptionsData()).data_source.row_count, 0, "a supplied zero must remain zero");
const formatModule = loadTranspiledModule("src/components/cme-options/cmeOptionsFormat.ts", {
  "@/lib/researchReading": { readableWarning: (value) => value },
});
const kpiModule = loadTranspiledModule("src/components/cme-options/CMEOptionsKpiStrip.tsx", {
  "react/jsx-runtime": jsxRuntime,
  "./cmeOptionsFormat": formatModule,
});
unknownCount.gex.netgex_aggregate.gamma_zero.price = 4321;
const kpiMarkup = renderToStaticMarkup(kpiModule.CMEOptionsKpiStrip({ snapshot: unknownCount }));
assert.match(kpiMarkup, /伽马零点<\/span><span[^>]*>4,321\.0 点/);
assert.match(kpiMarkup, /远期价<\/span><span[^>]*>— 点/, "gamma zero must not masquerade as forward price");
assert.match(kpiMarkup, /样本<\/span><span[^>]*>— 行/);

nextResponse = async () => mockResponse({ error: "upstream unavailable" }, 500);
const cmeUnavailable = await cmeAdapter.fetchCMEOptionsData("2026-10-02");
assert.equal(cmeUnavailable.source, "unavailable", "CME 500 must return an unavailable read model");
assert.equal(cmeUnavailable.has_data, false, "CME 500 must not claim data");
assert.match(cmeUnavailable.error_reason, /HTTP 500/, "CME 500 reason must remain visible");

nextResponse = async () => mockResponse({ error: "service unavailable" }, 503);
const event503 = eventAdapter.fetchEventFlowOverviewView();
await assert.rejects(event503, /HTTP 503/, "event 503 must remain an API error");

nextResponse = async () => mockResponse({
  status: "partial",
  source: "api",
  updated_at: "2026-10-04T01:02:03Z",
  events: [{
    id: "evt-en",
    title: "Federal Reserve keeps rates unchanged",
    summary: "",
    source: "Reuters",
    affected_assets: ["XAUUSD"],
  }],
});
const englishFacts = await eventAdapter.fetchEventFlowOverviewView();
assert.equal(englishFacts.timeline.length, 1, "English fact should remain in the API timeline");
assert.equal(englishFacts.timeline[0].title, "Federal Reserve keeps rates unchanged", "English source title must remain intact");
assert.equal(englishFacts.timeline[0].desc, "", "missing English analysis must remain empty");
assert.equal(englishFacts.timeline[0].impact, "未评估", "missing impact must not be inferred");
assert.equal(englishFacts.timeline[0].pricing, "未核验", "missing pricing must not be inferred");
assert.equal(englishFacts.timeline[0].source, "路透", "source labels may be localized without changing the fact");

nextResponse = async () => mockResponse({ status: "partial", source: "api", events: [] });
const emptyOverview = await eventAdapter.fetchEventFlowOverviewView();
assert.equal(emptyOverview.status, "partial", "empty overview status must remain partial");
assert.equal(emptyOverview.source, "api", "empty overview must retain the API source identity");
assert.equal(emptyOverview.timeline.length, 0, "empty overview must not re-enter the legacy timeline fixture");
assert.equal(emptyOverview.has_data, false, "empty overview must be explicitly marked without data");

nextResponse = async () => mockResponse({
  status: "partial",
  source: "api",
  market_validation: {},
  market_snapshot: {},
  pricing_status: "已定价",
  warnings: ["no observed window"],
});
const partialReaction = await eventAdapter.fetchEventFlowMarketReaction("evt-en");
assert.equal(partialReaction.status, "partial", "partial market reaction status must remain visible");
assert.deepEqual(partialReaction.market_validation, {}, "partial market reaction must not receive fabricated validation");
assert.deepEqual(partialReaction.market_snapshot, {}, "no-window market reaction must not receive fabricated snapshots");
assert.equal(partialReaction.pricing_status, "已定价", "adapter must preserve the backend pricing field for the UI to gate on windows");

nextResponse = async () => mockResponse({ error: "impact unavailable" }, 500);
await assert.rejects(
  eventAdapter.fetchEventFlowEventImpact("evt-en"),
  /HTTP 500/,
  "impact 500 must remain an explicit read-model error",
);

console.log("Trading evidence behavior contract OK: injected 500/503, English facts and partial/no-window read models remain fail-closed.");

console.log("Trading evidence boundary static contract OK: 500/503, empty/partial, English facts and no-window samples are fail-closed.");
