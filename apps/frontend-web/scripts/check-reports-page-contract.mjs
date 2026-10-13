import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function source(relativePath) {
  return readFileSync(join(__dirname, "..", relativePath), "utf8");
}

const meta = source("src/components/reports/reportListMeta.ts");
const model = source("src/components/reports/reportsPageModel.ts");
const rail = source("src/components/reports/reportsRailOptions.ts");
const list = source("src/components/reports/ReportsListView.tsx");
const card = source("src/components/reports/ReportCard.tsx");
const detail = source("src/components/reports/ReportDetailSections.tsx");
const types = source("src/types/reports.ts");
const adapter = source("src/adapters/reports.ts");

for (const reportType of ["observation_report", "observation_strategy_card"]) {
  assert.match(meta, new RegExp(`"${reportType}"`), `${reportType} must be supported by the report center`);
  assert.match(rail, new RegExp(`matchType: "${reportType}"`), `${reportType} must be filterable from the report rail`);
}

assert.match(meta, /function isObservationReport/, "observation reports need an explicit observation classifier");
assert.match(meta, /待复核 · 不可发布/, "observation reports must remain visibly non-publishable");
assert.match(model, /getReportListStatus\(item\)\.key/, "status filtering must distinguish observation from published reports");
assert.match(list, /getReportListStatus\(item\)/, "list view must render the report lifecycle status");
assert.match(card, /getReportListStatus\(item\)/, "card view must render the report lifecycle status");
assert.match(detail, /authority === "observation_only"/, "detail view must preserve observation-only authority");
assert.match(detail, /getReportDetailStatus\(data\)/, "detail view must project publication permission with the shared report semantics");
assert.match(detail, /qualification\.description/, "detail view must retain the explicit permission and reference restrictions");
assert.match(types, /publish_allowed\?: boolean \| null/, "report index type must retain publication authority");
assert.match(types, /report_identity\?: ReportIdentityView/, "report detail type must retain observation identity");
assert.match(adapter, /report_identity: detail\.report_identity/, "report detail adapter must retain observation identity");

console.log("Reports page observation/version contract OK");
