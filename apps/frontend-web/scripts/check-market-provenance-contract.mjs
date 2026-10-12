import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, "src", relativePath), "utf8");
}

const marketCards = read("components/market-monitor/MarketPriceCards.tsx");
assert.match(marketCards, /metricStatusLabel/);
assert.match(marketCards, /已观测/);
assert.match(marketCards, /无观测/);
assert.doesNotMatch(marketCards, /impactLabel:\s*"利多"/);
assert.doesNotMatch(marketCards, /impactLabel:\s*"利空"/);

const marketModel = read("components/market-monitor/marketMonitorPageModel.ts");
assert.match(marketModel, /观测可用，驱动待确认/);
assert.doesNotMatch(marketModel, /美元走弱驱动/);

const marketAdapter = read("adapters/marketMonitor.ts");
assert.doesNotMatch(marketAdapter, /MARKET_MONITOR_MOCK_URL/);
assert.match(marketAdapter, /throw apiCause instanceof Error/);
assert.match(marketAdapter, /cause\.status === 404 \|\| cause\.status === 501/);
assert.match(marketAdapter, /市场监控总览数据结构无效/);
assert.match(marketAdapter, /confidence: asNumberOrNull\(realtimeRegime\.confidence\)/);
assert.match(marketAdapter, /confidence: asNumberOrNull\(primaryDriver\.confidence\)/);
assert.match(marketAdapter, /confidence: asNumberOrNull\(raw\.confidence\)/);
assert.match(marketAdapter, /把握程度未量化/);

const marketHook = read("hooks/useMarketMonitor.ts");
assert.match(marketHook, /isRefreshing/);
assert.match(marketHook, /Keep the last successful result visible/);
assert.match(marketHook, /setError\(null\);/);

const goldAdapter = read("adapters/goldMainlines.ts");
assert.match(goldAdapter, /read_time_source_health/);
assert.match(goldAdapter, /read_time_warnings/);

const goldSourceFrame = read("components/gold-mainlines/GoldMainlinePageFrame.tsx");
assert.match(goldSourceFrame, /treasury_2y: "2年期美国国债"/);
assert.match(goldSourceFrame, /fed_macro_events: "美联储与宏观事件"/);
assert.match(goldSourceFrame, /来源检查明细/);
assert.match(goldSourceFrame, /suppressRepeatedSourceReason/);
const sourceHelpersStart = goldSourceFrame.indexOf("const SOURCE_LABELS");
const sourceHelpersEnd = goldSourceFrame.indexOf("\nexport function GoldReadTimeSourceHealthBanner", sourceHelpersStart);
assert.ok(sourceHelpersStart >= 0 && sourceHelpersEnd > sourceHelpersStart, "Gold source helper boundary exists");
const sourceHelpersJavaScript = ts.transpileModule(
  goldSourceFrame.slice(sourceHelpersStart, sourceHelpersEnd).replaceAll("export function", "function"),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None } },
).outputText;
const { sourceLabel, sourceHealthReasonLabel, suppressRepeatedSourceReason } = new Function(
  `${sourceHelpersJavaScript}; return { sourceLabel, sourceHealthReasonLabel, suppressRepeatedSourceReason };`,
)();
assert.equal(suppressRepeatedSourceReason("xauusd_price: unexpected integrity conflict", new Set(["xauusd_price"])), false, "an unknown risk must remain even if it mentions a missing source");
assert.equal(sourceLabel("treasury_10y"), "10年期美国国债");
assert.equal(sourceLabel("eiainventory"), "EIA 库存");
assert.equal(sourceHealthReasonLabel("P1 source missing: cme_options"), "P1 辅助源缺失");
assert.equal(
  suppressRepeatedSourceReason("global P0 source unavailable: xauusd_price", new Set(["xauusd_price"])),
  true,
);
assert.equal(
  suppressRepeatedSourceReason("global P0 source unavailable: xauusd_price", new Set()),
  false,
);
assert.equal(sourceHealthReasonLabel("vendor-specific unknown source state"), null);

const goldPages = [
  read("pages/GoldMainlinesPage.tsx"),
  read("pages/RatesDollarPage.tsx"),
  read("pages/OilGeopoliticsPage.tsx"),
].join("\n");
assert.match(goldPages, /GoldReadTimeSourceHealthBanner/);
assert.match(goldPages, /已登记主线/);

const kpi = read("components/dashboard/CompactKPICard.tsx");
assert.match(kpi, /状态未知/);
assert.match(kpi, /观测 \{dataDate \|\| "时间未知"\}/);
assert.match(kpi, /dot: "var\(--fg-5\)"/);

const helperStart = kpi.indexOf("export function resolveKpiDataStatus");
const helperEnd = kpi.indexOf("\n}\n\nfunction statusDotColor", helperStart) + 2;
assert.ok(helperStart >= 0 && helperEnd > helperStart, "KPI status helper boundary exists");
const helperSource = kpi.slice(helperStart, helperEnd).replace("export function", "function");
const helperJavaScript = ts.transpileModule(helperSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;
const resolveKpiDataStatus = new Function(`${helperJavaScript}; return resolveKpiDataStatus;`)();
assert.equal(resolveKpiDataStatus("UNAVAILABLE").label, "不可用");
assert.notEqual(resolveKpiDataStatus("UNAVAILABLE").dot, "var(--up)");
assert.equal(resolveKpiDataStatus("stale").label, "已过期");
assert.equal(resolveKpiDataStatus("mock").label, "模拟 / 回退");
assert.equal(resolveKpiDataStatus("unknown").label, "状态未知");
assert.equal(resolveKpiDataStatus("0").label, "状态未知");

const sidebar = read("components/AppSidebar.tsx");
assert.match(sidebar, /useDataStatus/);
assert.doesNotMatch(sidebar, /当前会话已连接/);
assert.doesNotMatch(sidebar, />在线</);
assert.doesNotMatch(sidebar, /新闻实时/);

const marketPage = read("pages/MarketMonitorPage.tsx");
assert.match(marketPage, /上次读取：\$\{pageStatusText\}/);
assert.match(marketPage, /当前刷新尚未完成/);
const marketHeader = read("components/market-monitor/MarketMonitorHeaderSections.tsx");
assert.match(marketHeader, /formatGoldDriverLabel/);
assert.match(marketHeader, /primaryDriver\.driver === "data_insufficient" \? null/);

class TestApiError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? null;
    this.url = options.url ?? "";
  }
}

function loadMarketMonitorAdapter(fetchJson) {
  const source = fs.readFileSync(path.join(root, "src", "adapters", "marketMonitor.ts"), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText;
  const module = { exports: {} };
  const sandbox = {
    module,
    exports: module.exports,
    console,
    require(specifier) {
      if (specifier === "@/adapters/apiClient") {
        return { fetchJson, ApiError: TestApiError };
      }
      throw new Error(`Unexpected adapter import: ${specifier}`);
    },
  };
  vm.runInNewContext(output, sandbox, { filename: "marketMonitor.ts" });
  return module.exports;
}

const OVERVIEW_PATH = "/api/market/monitor";
const TICKERS_PATH = "/api/market/tickers";
const MACRO_PATH = "/api/macro/latest";

function validTickerPayload() {
  return {
    generated_at: "2026-10-04T02:00:00Z",
    tickers: {
      xauusd: { price: 2650, change_pct: 0.4, source: "test", time: "2026-10-04T02:00:00Z" },
    },
  };
}

function validMacroPayload() {
  return {
    as_of: "2026-10-03",
    indicators: {
      DXY: { value: 100, weekly_change: -0.2, monthly_change: 0.1, unit: "index" },
    },
  };
}

function validOverviewPayloadWithoutConfidence() {
  return {
    generated_at: "2026-10-04T02:00:00Z",
    latest_date: "2026-10-03",
    has_data: true,
    source: "api",
    metrics: [{
      key: "XAUUSD",
      label: "XAUUSD",
      group: "metals",
      latest_date: "2026-10-03",
      latest_value: 2650,
      unit: "USD/oz",
      one_week_change: null,
      one_month_change: null,
      status: "ok",
      interpretation: "",
    }],
    market_regimes: {},
    environment_filters: {},
    source_trace: [],
    realtime_regime: { regime: "neutral", available: true },
    primary_driver: { driver: "data_insufficient" },
    agent_market_regime: { regime: "neutral", regime_label: "中性", summary: "" },
  };
}

async function assertOverviewFailureDoesNotFallback(name, overviewResult) {
  const calls = [];
  const adapter = loadMarketMonitorAdapter(async (requestPath) => {
    calls.push(requestPath);
    if (requestPath === OVERVIEW_PATH) {
      if (overviewResult instanceof Error) throw overviewResult;
      return overviewResult;
    }
    throw new Error(`${name} unexpectedly requested ${requestPath}`);
  });

  await assert.rejects(() => adapter.fetchMarketMonitorData(), `${name} must reject`);
  assert.deepEqual(calls, [OVERVIEW_PATH], `${name} must not call legacy endpoints`);
}

await assertOverviewFailureDoesNotFallback(
  "overview 503",
  new TestApiError("overview unavailable", { status: 503, url: OVERVIEW_PATH }),
);
await assertOverviewFailureDoesNotFallback("overview network error", new TypeError("network down"));
await assertOverviewFailureDoesNotFallback("overview malformed", { source: "api", metrics: "malformed", source_trace: [] });

for (const status of [404, 501]) {
  const calls = [];
  const adapter = loadMarketMonitorAdapter(async (requestPath) => {
    calls.push(requestPath);
    if (requestPath === OVERVIEW_PATH) {
      throw new TestApiError(`overview ${status}`, { status, url: OVERVIEW_PATH });
    }
    if (requestPath === TICKERS_PATH) return validTickerPayload();
    if (requestPath === MACRO_PATH) return validMacroPayload();
    throw new Error(`unexpected request ${requestPath}`);
  });
  const result = await adapter.fetchMarketMonitorData();
  assert.equal(result.source, "api", `HTTP ${status} fallback retains API provenance`);
  assert.equal(calls.length, 3, `HTTP ${status} fallback makes exactly three reads`);
  assert.ok(calls.includes(TICKERS_PATH), `HTTP ${status} fallback reads tickers`);
  assert.ok(calls.includes(MACRO_PATH), `HTTP ${status} fallback reads macro`);
}

{
  const adapter = loadMarketMonitorAdapter(async (requestPath) => {
    assert.equal(requestPath, OVERVIEW_PATH, "confidence fixture must use overview only");
    return validOverviewPayloadWithoutConfidence();
  });
  const result = await adapter.fetchMarketMonitorData();
  assert.equal(result.realtime_regime?.confidence, null, "missing realtime confidence stays null");
  assert.equal(result.primary_driver?.confidence, null, "missing primary driver confidence stays null");
  assert.equal(result.agent_market_regime?.confidence, null, "missing agent confidence stays null");
}

console.log("Market and gold provenance frontend contract OK");
