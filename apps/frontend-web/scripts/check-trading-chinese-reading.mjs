import fs from "node:fs";
import path from "node:path";

const root = path.resolve(new URL("..", import.meta.url).pathname, "src");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function expectIncludes(relativePath, fragment, message) {
  if (!read(relativePath).includes(fragment)) {
    throw new Error(`${relativePath}: ${message}`);
  }
}

function expectAbsent(relativePath, fragment, message) {
  if (read(relativePath).includes(fragment)) {
    throw new Error(`${relativePath}: ${message}`);
  }
}

// The heatmap must keep missing changes nullable. A missing change may be
// rendered as a neutral cell, but it must never become a synthetic zero.
expectIncludes("components/market-monitor/FactorHeatmap.tsx", "function changeToNumber(value: unknown): number | null", "missing change must remain nullable");
expectIncludes("components/market-monitor/FactorHeatmap.tsx", "return null;", "invalid or missing change must not be coerced to zero");
expectIncludes("components/market-monitor/MultiLineChart.tsx", "<TradingViewChart", "market main chart must use the isolated TradingView view");
expectIncludes("components/market-monitor/format.ts", "return MARKET_MONITOR_SOURCE_LABELS[normalized] ?? \"来源待核验\"", "unknown source ids need a Chinese review label");

// These are the user-visible strings that previously exposed implementation
// enums or English-only section names in the reviewed page group.
const uiFiles = [
  "components/market-monitor/MarketMonitorTabSections.tsx",
  "components/market-monitor/AssetTableSections.tsx",
  "components/market-monitor/LiquidityPricePanel.tsx",
  "components/market-monitor/RealRatePanel.tsx",
  "components/market-monitor/FactorPanel.tsx",
  "components/market-monitor/FactorHeatmap.tsx",
  "components/market-monitor/CorrelationMatrix.tsx",
  "components/market-monitor/SourceTracePanel.tsx",
  "components/oil-geopolitics/OilGeoEvidenceTimeline.tsx",
  "components/oil-geopolitics/OilGeoMainlineRows.tsx",
  "components/oil-geopolitics/OilGeoVerificationCard.tsx",
  "components/oil-geopolitics/SafeHavenVsInflationSplit.tsx",
  "components/oil-geopolitics/WarOilRateChainPanel.tsx",
  "pages/RatesDollarPage.tsx",
  "pages/OilGeopoliticsPage.tsx",
];
const forbiddenVisibleFragments = [
  'eyebrow="Rate / Dollar"',
  'eyebrow="Oil / Geopolitics"',
  'eyebrow="Factor Heatmap"',
  'eyebrow="Realtime Chain"',
  'eyebrow="Cross-Asset Matrix"',
  'eyebrow="Event Evidence"',
  'eyebrow="Source Trace"',
  'eyebrow="Verification Rail"',
  'eyebrow="Conflict Split"',
  'eyebrow="Chain Board"',
  "history unavailable",
  ">Symbol<",
  ">Latest<",
  ">Status<",
  " loaded",
];
for (const relativePath of uiFiles) {
  const source = read(relativePath);
  for (const fragment of forbiddenVisibleFragments) {
    if (source.includes(fragment)) {
      throw new Error(`${relativePath}: visible reading fragment remains: ${fragment}`);
    }
  }
}

expectIncludes("pages/RatesDollarPage.tsx", 'if (typeof value !== "number" || !Number.isFinite(value)) return "—";', "missing score needs a dash");
expectIncludes("components/oil-geopolitics/oilGeopoliticsModel.ts", 'if (typeof value !== "number" || !Number.isFinite(value)) return "—";', "missing oil risk score needs a dash");
expectIncludes("pages/MarketOddsPage.tsx", "当前未提供中文影响解释", "missing external odds analysis must be explicit");
expectIncludes("components/cme-options/CMEOptionsDecisionWorkspace.tsx", "PNT / 大宗成交", "PNT needs a business explanation");
expectIncludes("pages/RatesDollarPage.tsx", "readableRateEventLabel", "rate event IDs need a Chinese business label");
expectIncludes("components/oil-geopolitics/OilGeoEvidenceTimeline.tsx", "readableOilEventLabel", "oil event IDs need a Chinese business label");
expectIncludes("pages/CMEOptionsPage.tsx", "formatCMEExpiryLabel(ex)", "expiry filter options need a Chinese label");
expectIncludes("pages/CMEOptionsPage.tsx", "EvidenceRecordActions", "snapshot identity needs a human-readable evidence action");
expectAbsent("pages/RatesDollarPage.tsx", ">{event.event_id}</", "rate event IDs must not be primary visible labels");
expectAbsent("components/oil-geopolitics/OilGeoEvidenceTimeline.tsx", ">{event.event_id}</", "oil event IDs must not be primary visible labels");

console.log("Trading Chinese reading contract OK");
