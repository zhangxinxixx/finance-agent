import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/reports/reportsNavigation.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { readReportsQuery, reportsReturnTarget } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

const query = readReportsQuery(new URLSearchParams("q=期权&view=grid&page=3&types=options_report,macro_report&asset=OG&status=review&source=api&range=7d"));
assert.equal(query.searchQuery, "期权");
assert.equal(query.viewMode, "grid");
assert.equal(query.currentPage, 3);
assert.deepEqual(query.filters.reportTypes, ["options_report", "macro_report"]);
assert.equal(query.filters.asset, "OG");
assert.equal(query.filters.dateRange, "7d");
for (const invalid of ["NaN", "-1", "0", "1.5", "Infinity", "9007199254740992"]) {
  assert.equal(readReportsQuery(new URLSearchParams(`page=${invalid}&view=unknown`)).currentPage, 1);
}
assert.equal(reportsReturnTarget({ reportsReturnTo: "/reports?q=%E6%9C%9F%E6%9D%83&page=3" }), "/reports?q=%E6%9C%9F%E6%9D%83&page=3");
for (const invalid of ["https://example.com", "//example.com", "/reports/loop", "/reports#not-list", "/strategy"]) {
  assert.equal(reportsReturnTarget({ reportsReturnTo: invalid }), "/reports");
}
assert.equal(reportsReturnTarget(null), "/reports");
console.log("Reports query restoration and safe return target behavior OK");
