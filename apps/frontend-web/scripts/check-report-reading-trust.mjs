import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(new URL("../src/components/reports/reportDetailMeta.ts", import.meta.url), "utf8");
const module = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, {
  module, exports: module.exports,
  require(name) {
    if (name === "@/components/shared/statusMeta") return { getStatusLabel: value => value };
    if (name === "@/lib/status") return { getDataStatusTone: () => "warning" };
    throw new Error(`Unexpected dependency: ${name}`);
  },
});
const { reportNeedsReadingWarning, reportLifecycleLabel, reviewStatusLabel, reportFamilyLabel } = module.exports;
assert.equal(reportFamilyLabel("gold_policy_daily_report"), "黄金日结报告");
for (const data_status of ["partial", "unavailable", "error"]) {
  assert.equal(reportNeedsReadingWarning({ data_status, meta: { lifecycle_status: "reviewed" } }), true,
    "readable/registered evidence does not remove a partial-data warning");
}
for (const lifecycle_status of ["needs_review", "NEEDS_REVIEW"]) {
  assert.equal(reportNeedsReadingWarning({ data_status: "available", meta: { lifecycle_status } }), true);
  assert.equal(reportLifecycleLabel(lifecycle_status), "待质量复核");
}
assert.equal(reportNeedsReadingWarning({ data_status: "available", meta: { lifecycle_status: "reviewed" } }), false);
assert.equal(reviewStatusLabel("not_required"), "未要求人工审查",
  "a manual review requirement must not imply analysis reliability");
console.log("Report reading trust: data availability, quality review and manual-review requirements stay distinct");
