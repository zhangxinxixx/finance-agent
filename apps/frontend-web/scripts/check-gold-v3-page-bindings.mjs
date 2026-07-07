import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function source(relativePath) {
  return readFileSync(join(__dirname, "..", relativePath), "utf8");
}

function exists(relativePath) {
  return existsSync(join(__dirname, "..", relativePath));
}

function assertIncludes(text, needle, message) {
  assert.ok(text.includes(needle), message);
}

function assertNotIncludes(text, needle, message) {
  assert.ok(!text.includes(needle), message);
}

const dashboardRightPanel = source("src/components/dashboard/DashboardRightPanel.tsx");
const goldOverviewPanel = source("src/components/dashboard/GoldMacroOverviewPanel.tsx");
const goldMainlinesPage = source("src/pages/GoldMainlinesPage.tsx");
const oilGeopoliticsPage = source("src/pages/OilGeopoliticsPage.tsx");
const strategyPage = source("src/pages/StrategyPage.tsx");
const reportsPage = source("src/pages/ReportsPage.tsx");
const eventTrace = source("src/components/event-flow/EventGoldMainlineTrace.tsx");

for (const componentPath of [
  "src/components/gold/GoldMacroSummaryCard.tsx",
  "src/components/gold/TopMainlinesStrip.tsx",
  "src/components/gold/DriverConflictCard.tsx",
  "src/components/gold/WarOilRateMiniCard.tsx",
  "src/components/gold/VerificationMatrixPreview.tsx",
  "src/components/gold-mainlines/MainlineRankingTable.tsx",
  "src/components/gold-mainlines/MainlineDetailDrawer.tsx",
  "src/components/gold-mainlines/MainlineEvidenceList.tsx",
  "src/components/oil-geopolitics/WarOilRateChainPanel.tsx",
  "src/components/oil-geopolitics/SafeHavenVsInflationSplit.tsx",
  "src/components/oil-geopolitics/OilGeoEvidenceTimeline.tsx",
  "src/components/oil-geopolitics/OilGeoVerificationCard.tsx",
  "src/components/event-flow/MainlineTagGroup.tsx",
  "src/components/event-flow/TransmissionChainTagGroup.tsx",
  "src/components/event-flow/MixedDriverSplitCard.tsx",
  "src/components/event-flow/ProcessingTraceLink.tsx",
]) {
  assert.ok(exists(componentPath), `missing Gold v3 page component ${componentPath}`);
}

assertIncludes(
  dashboardRightPanel,
  "<GoldMacroOverviewPanel overview={summary.gold_macro_overview} />",
  "Dashboard must pass only DashboardSummary.gold_macro_overview into the GoldMacroOverviewPanel",
);
for (const forbidden of ["useGoldMainlines", "fetchGoldMainlines", "mainlineCoverageRows(", "topicRankings("]) {
  assertNotIncludes(goldOverviewPanel, forbidden, `Dashboard Gold overview panel must not recalculate or refetch mainline data: ${forbidden}`);
}

for (const required of [
  "useGoldMainlines",
  "mainlineCoverageRows(overview)",
  "<MainlineRankingTable rows={coverageRows} />",
  "<MainlineDetailDrawer overview={overview} rows={coverageRows} />",
  "<MainlineEvidenceList overview={overview} rows={coverageRows} />",
]) {
  assertIncludes(goldMainlinesPage, required, `GoldMainlinesPage missing required binding ${required}`);
}

for (const required of [
  "topicRankings(overview)",
  "topicRows(overview)",
  "topicVerification(overview)",
  "topicEvents(data.gold_mainlines.event_links ?? [])",
  "<WarOilRateChainPanel chain={chain} rows={rows} events={events} />",
  "<SafeHavenVsInflationSplit conflict={overview.driver_conflict} />",
  "<OilGeoVerificationCard overview={overview} items={verification} />",
  "<OilGeoEvidenceTimeline events={events} sourceRefs={sources} />",
]) {
  assertIncludes(oilGeopoliticsPage, required, `OilGeopoliticsPage missing required binding ${required}`);
}

for (const forbidden of ["useGoldMainlines", "theme_rankings", "war_oil_rate_chain", "driver_conflict"]) {
  assertNotIncludes(strategyPage, forbidden, `StrategyPage must stay on strategy read model and not consume Gold mainline fields: ${forbidden}`);
  assertNotIncludes(reportsPage, forbidden, `ReportsPage must stay render/index focused and not consume Gold mainline fields: ${forbidden}`);
}
for (const forbidden of ["related_news_items", "article_briefs", "useEventFlow", "fetchEventFlow"]) {
  assertNotIncludes(strategyPage, forbidden, `StrategyPage must not directly consume news/EventFlow inputs: ${forbidden}`);
}

for (const required of [
  "<MainlineTagGroup",
  "<TransmissionChainTagGroup",
  "<MixedDriverSplitCard",
  "<ProcessingTraceLink",
]) {
  assertIncludes(eventTrace, required, `EventFlow trace must render ${required}`);
}

console.log("Gold v3 page binding contract OK");
