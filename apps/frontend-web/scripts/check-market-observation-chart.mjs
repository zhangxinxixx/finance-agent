import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const root = path.resolve(new URL("../src", import.meta.url).pathname);
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} };
  cache.set(file, module);
  const source = readFileSync(file, "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(code, { module, exports: module.exports, require(name) {
    if (!name.startsWith("@/") && !name.startsWith(".")) return require(name);
    const stem = name.startsWith("@/") ? path.join(root, name.slice(2)) : path.resolve(path.dirname(file), name);
    const target = [stem + ".ts", stem + ".tsx"].find(existsSync);
    if (!target) throw new Error(`Unknown dependency: ${name}`);
    return load(target);
  } }, { filename: file });
  return module.exports;
}
const { historyObservationSegments } = load(path.join(root, "components/market-monitor/historyObservationModel.ts"));
const { HistoryObservationPanel } = load(path.join(root, "components/market-monitor/HistoryObservationPanel.tsx"));
const { CorrelationMatrix } = load(path.join(root, "components/market-monitor/CorrelationMatrix.tsx"));
const { MarketDiagnosisSection } = load(path.join(root, "components/market-monitor/RightPanelSections.tsx"));
const rows = [
  { date: "2026-09-28", DXY: 105 },
  { date: "2026-09-24", DXY: 0 },
  { date: "2026-09-25", DXY: null },
  { date: "2026-09-26", DXY: 102 },
  { date: "2026-09-27", DXY: 103 },
  { date: "not-a-date", DXY: 999 },
];
const segments = historyObservationSegments(rows, "DXY");
assert.deepEqual(JSON.parse(JSON.stringify(segments.map((segment) => segment.map(({date, value}) => ({date, value}))))), [
  [{ date: "2026-09-24", value: 0 }],
  [{ date: "2026-09-26", value: 102 }, { date: "2026-09-27", value: 103 }, { date: "2026-09-28", value: 105 }],
]);
assert.equal(historyObservationSegments(rows, "REAL_10Y").length, 0);
assert.equal(historyObservationSegments([{date:"2026-10-01", DXY: Infinity}], "DXY").length, 0);
const metrics = [{key:"DXY",label:"美元指数",latest_date:"2026-10-02",latest_value:106,unit:"指数点",one_week_change:0,one_month_change:null}];
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
let html = render(HistoryObservationPanel, {history:{series:rows,source_timeframe:"1d",degraded:false},metrics,timeframe:"1W"});
assert.ok(html.includes("请求周期 近1周（1W）") && html.includes("实际返回频率 日线"));
assert.ok(html.includes("2026-09-24") && html.includes("2026-09-28") && html.includes("最新指标观测：2026-10-02"));
assert.equal((html.match(/<polyline/g) ?? []).length, 1, "missing day must break the observed line, never fill it");
assert.equal((html.match(/<circle/g) ?? []).length, 1, "real zero observation is preserved as a single point");
assert.ok(!html.includes("999") && !html.includes("Infinity") && !html.includes("NaN"));
html = render(HistoryObservationPanel, {history:null,metrics,timeframe:"1M"});
assert.ok(html.includes("当前行情值不会补造历史曲线"));
assert.ok(!html.includes("<polyline"));
html = render(CorrelationMatrix, {metrics});
assert.ok(html.includes("同步历史样本的相关性结果"));
assert.ok(html.includes("2026-10-02") && html.includes("指数点"));
assert.ok(html.includes(">+0<") && html.includes(">—<"), "known zero and missing observations remain distinct");
assert.ok(!html.includes("0.55") && !html.includes("1.00"), "no manufactured pair or diagonal correlation");
const regimes = {
  rate_pressure: { status: "unavailable", confidence: 0, description: "" },
  transition_release: { status: "ok", confidence: 0.5, description: "neutral_firm" },
};
html = render(MarketDiagnosisSection, { marketRegimes: regimes, currentRegimeAvailable: false });
assert.ok(html.includes("阶段待确认") && html.includes("当前阶段未核验"));
assert.ok(!html.includes("50%") && !html.includes(">0%<"), "an unavailable current regime must not expose default scores as current analysis");
html = render(MarketDiagnosisSection, { marketRegimes: regimes, currentRegimeAvailable: true });
assert.ok(html.includes("50%") && !html.includes(">0%<"), "unavailable rows stay unverified even when another regime is available");
html = render(MarketDiagnosisSection, { marketRegimes: { transition_release: { ...regimes.transition_release, confidence: 0 } }, currentRegimeAvailable: true });
assert.ok(html.includes(">0%<"), "an explicitly available true zero is preserved");
html = render(MarketDiagnosisSection, { marketRegimes: regimes, currentRegimeAvailable: false, agentMarketRegime: {
  regime: "transition_release", confidence: 0.68, createdAt: "2026-05-30T16:04:00Z", summary: "历史说明",
} });
assert.ok(html.includes("历史模型摘要") && html.includes("68%") && !html.includes("50%"), "historical analysis stays readable with its own provenance");
console.log("Market observation charts: units, dates, gaps and no fabricated correlation OK");
