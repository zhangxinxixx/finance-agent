import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";

const src = fileURLToPath(new URL("../src/", import.meta.url));
const nativeRequire = createRequire(import.meta.url);
const cache = new Map();
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const js = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const require = (name) => {
    if (!name.startsWith("@/")) return nativeRequire(name);
    const base = resolve(src, name.slice(2));
    return load(existsSync(`${base}.ts`) ? `${base}.ts` : `${base}.tsx`);
  };
  new Function("require", "module", "exports", js)(require, module, module.exports);
  return module.exports;
}

const { getReportListStatus, canOpenReport } = load(resolve(src, "components/reports/reportListMeta.ts"));
const { dedupeSupportedReports, filterReports } = load(resolve(src, "components/reports/reportsPageModel.ts"));
const history = {
  type: "final_report", trade_date: "2026-09-05", run_id: "run-a", report_id: "registered-a",
  format: "markdown", available: true, authority: "historical_only", output_mode: "historical",
  publish_allowed: false, lifecycle_status: "needs_review", review_status: "needs_review",
  generated_at: "2026-09-05T09:00:00Z",
};
assert.equal(getReportListStatus(history).key, "archived");
assert.equal(getReportListStatus(history).label, "历史报告 · 未通过当前校验");
assert.equal(canOpenReport(history), true, "historical authority must not block reading");
const second = { ...history, run_id: "run-b", report_id: "registered-b", generated_at: "2026-09-05T10:00:00Z" };
const reports = dedupeSupportedReports([history, second, { ...history }]);
assert.equal(reports.length, 2, "same-day composite versions remain distinct, identical versions deduplicate");
const filters = { reportTypes: ["final_report"], asset: null, status: null, dataSource: null, dateRange: null };
assert.equal(filterReports(reports, "", filters).length, 2);
assert.equal(filterReports(reports, "", { ...filters, status: "archived" }).length, 2);
assert.equal(filterReports(reports, "", { ...filters, status: "published" }).length, 0);
assert.equal(getReportListStatus({ ...history, authority: undefined, output_mode: undefined,
  publish_allowed: true, lifecycle_status: "published", review_status: "accepted" }).key, "published");
assert.equal(getReportListStatus({ ...history, type: "observation_report", authority: "observation_only", output_mode: "observe" }).key, "review");
console.log("Historical report reading, status filters and same-day versions OK");
