import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { StaticRouter } = require("react-router-dom");
const root = path.resolve(new URL("../src", import.meta.url).pathname);
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} }; cache.set(file, module);
  const compiled = ts.transpileModule(readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } });
  vm.runInNewContext(compiled.outputText, { module, exports: module.exports, require(name) {
    if (!name.startsWith("@/") && !name.startsWith(".")) return require(name);
    const stem = name.startsWith("@/") ? path.join(root, name.slice(2)) : path.resolve(path.dirname(file), name);
    const target = [stem + ".ts", stem + ".tsx"].find(existsSync);
    assert.ok(target, name); return load(target);
  } }, { filename: file });
  return module.exports;
}
const component = (file, name) => load(path.join(root, file))[name];
const render = (Component, props) => renderToStaticMarkup(React.createElement(StaticRouter, { location: "/" }, React.createElement(Component, props)));
const { buildIntegratedMacroSummary, dashboardResearchDate, dashboardResearchAsOf, buildOptionsEvidenceSummary } = load(path.join(root, "components/dashboard/DashboardIntegratedMacroModel.ts"));
const summary = {
  integrated_macro: { trade_date: "2026-09-29", run_id: "research-run", confidence: null, direction: null, reasoning: "", invalidation: [], risks: ["研究风险自身"], missing_inputs: ["研究缺失自身"], source_refs: [], trigger_upgrade: [], trigger_downgrade: [] },
  agent_summary: { synthesis: { bias: "旧代理方向", confidence: 0.99, summary: "旧代理摘要", riskPoints: ["旧代理风险"], invalidConditions: ["旧代理失效"], createdAt: "2026-10-02" } },
  strategy: { bias: "旧策略方向", direction: "bullish", confidence: 0.99, macro_phase: "旧宏观阶段", invalid_conditions: ["旧策略失效"], key_levels: { resistance: [9999], support: [8888] } },
  market_summary: {}, macro_liquidity: {}, cme_options: { intent: "unknown", wall_score: null, upper_resistance_walls: [], lower_support_walls: [] },
  conclusion: { resistance_levels: [7777], support_levels: [6666] }, risk: { alerts: ["其它风险"] }, risk_alerts: ["其它风险"],
  source_trace: [{ name: "unrelated", source_ref: "OTHER-SOURCE", status: "ok" }],
  latest_reports: [{ status: "ready", trade_date: "2026-10-02", run_id: "other-run", report_id: "foreign-report", url: "/reports/foreign-report" }],
};
const viewModel = { strategy_card: { bias: "旧视图方向", direction: "bearish", confidence: 0.98, scenario_summary: "旧视图摘要", trigger_conditions: ["旧策略触发"], invalid_conditions: ["旧视图失效"], risk_points: ["旧视图风险"], source_refs: [{ source_ref: "OTHER-VIEW-SOURCE" }] }, source_refs: [], macro_summary: { phase: "旧视图阶段" } };
let result = buildIntegratedMacroSummary(summary, viewModel);
assert.ok(result.macroExplanation.includes("本次研究未提供宏观影响解释"));
assert.ok(result.optionsAlignment.includes("本次研究未提供期权配合度"));
assert.equal(result.direction, "unknown"); assert.equal(result.confidence, null);
assert.equal(result.overallBias, "方向未提供");
for (const key of ["macroExplanation", "researchMemo", "decisionSummary", "macroRegime"]) assert.doesNotMatch(result[key], /旧/);
assert.equal(result.macroLevels.resistance.length, 0); assert.equal(result.macroLevels.support.length, 0);
assert.ok(result.invalidation[0].includes("尚未提供失效条件"));
assert.equal(result.riskNote, "研究风险自身");
summary.integrated_macro.trade_date = "";
assert.equal(dashboardResearchDate(summary), "未提供"); assert.equal(dashboardResearchAsOf(summary), null);
summary.integrated_macro.trade_date = "2026-09-29";
for (const value of [Infinity, NaN]) { summary.integrated_macro.confidence = value; assert.equal(buildIntegratedMacroSummary(summary).confidence, null); }
summary.integrated_macro.confidence = 0; assert.equal(buildIntegratedMacroSummary(summary).confidence, 0);
assert.equal(buildOptionsEvidenceSummary(summary).sourceRefs.length, 0, "options cannot borrow arbitrary non-options sources");
const Panel = component("components/dashboard/DashboardAnalysisPanel.tsx", "DashboardAnalysisPanel");
let html = render(Panel, { summary, viewModel });
assert.ok(html.includes("核验状态未提供")); assert.ok(html.includes("研究风险自身") && html.includes("研究缺失自身"));
assert.doesNotMatch(html, /已校验|旧代理|旧策略触发|旧视图|OTHER-SOURCE|OTHER-VIEW-SOURCE|foreign-report/);
assert.ok(html.includes("查找报告")); assert.ok(html.includes("本次研究未提供来源引用"));
summary.integrated_macro.invalidation = ["自身失效"];
summary.integrated_macro.reasoning = "自身说明";
summary.latest_reports.push({ status: "ready", trade_date: "2026-09-29", run_id: "research-run", report_id: "own-report", url: "/reports/own-report" });
html = render(Panel, { summary, viewModel }); assert.ok(html.includes("/reports/own-report") && html.includes("本次报告"));
assert.ok(html.includes("自身失效"));
const { scoreFormulaLabel } = load(path.join(root, "components/gold-mainlines/goldMainlineCoverage.ts"));
assert.equal(scoreFormulaLabel({}), "未提供 / 未提供 / 未提供 / 未提供");
assert.equal(scoreFormulaLabel({ direction_score: 0, impact_score: NaN, confidence_score: Infinity, freshness_score: 1 }), "0 / 未提供 / 未提供 / 1");
const overview = {
  verification_matrix: Array.from({ length: 9 }, (_, i) => ({ id: `v${i}`, label: `验证项目${i}`, status: i === 8 ? "failed" : "confirmed", source_refs: [] })),
  driver_conflict: null, war_oil_rate_chain: null,
  source_refs: Array.from({ length: 9 }, (_, i) => ({ source_ref: `SOURCE-${i}`, status: "partial" })),
  mainline_requirements: [{ mainline_id: "fed_policy_path", pricing_layer: "direct", readiness_status: "partial", label: "政策", asset_principle: "已有原理", analysis_chain: ["一", "二", "三", "四", "五", "第六传导"], required_sources: ["一", "二", "三", "四", "第五输入"], missing_sources: ["第五输入"], missing_fields: ["一", "二", "三", "四", "第五缺失字段"], development_gaps: ["开发限制"], developed_sources: [] }],
  architecture_gaps: ["一", "二", "三", "四", "五", "第六能力缺口"],
};
html = render(component("components/gold-mainlines/MainlineDetailDrawer.tsx", "MainlineDetailDrawer"), { overview, rows: [] });
assert.ok(html.includes("验证项目8"), "ninth failed verification must remain visible");
assert.doesNotMatch(html, /truncate/);
html = render(component("components/gold-mainlines/GoldMainlineRequirementArchitecturePanel.tsx", "GoldMainlineRequirementArchitecturePanel"), { overview });
for (const label of ["第五输入", "第五缺失字段", "第六能力缺口", "第六传导"]) assert.ok(html.includes(label));
assert.ok(html.includes("未提供")); assert.doesNotMatch(html, />0<|>0%<|line-clamp|truncate/);
const beforeDetails = html.split("<details>")[0]; assert.ok(beforeDetails.includes("第五输入") && beforeDetails.includes("第六能力缺口"), "decision limitations remain outside technical disclosure");
overview.analysis_readiness = { status: "missing", ready_count: 0, partial_count: 0, missing_count: 1, total_count: 1, coverage_ratio: 0 };
html = render(component("components/gold-mainlines/GoldMainlineRequirementArchitecturePanel.tsx", "GoldMainlineRequirementArchitecturePanel"), { overview });
assert.ok(html.includes(">0<") && html.includes(">0%<"), "genuine zero remains zero");
html = render(component("components/gold-mainlines/MainlineEvidenceList.tsx", "MainlineEvidenceList"), { overview, rows: [{ id: "fed_policy_path", status: "pending", eventIds: ["event:1", "event:2", "event:3", "event:4", "event:5"] }] });
assert.ok(html.includes("event%3A5")); assert.ok(html.includes("查看事件证据"));
assert.ok(html.includes("查看主线依据记录"));
assert.doesNotMatch(html, /SOURCE-\d/, "raw source identifiers are not ordinary reading content");
// Open the actual disclosure component and verify every source keeps its copy action.
const originalUseState = React.useState;
try {
  React.useState = (initial) => [new Error().stack.includes("ResearchDetails (") ? true : initial, () => {}];
  html = render(component("components/gold-mainlines/MainlineEvidenceList.tsx", "MainlineEvidenceList"), { overview, rows: [] });
  assert.equal((html.match(/>复制依据记录<\/button>/g) ?? []).length, 9, "all nine source records remain accessible after disclosure");
  assert.doesNotMatch(html, /SOURCE-\d/, "expanded reading also keeps technical identifiers out of visible content");
} finally { React.useState = originalUseState; }
const Diagnosis = component("components/market-monitor/RightPanelSections.tsx", "MarketDiagnosisSection");
html = render(Diagnosis, { currentRegimeAvailable: true, marketRegimes: { rate_pressure: { status: "ok", confidence: 0.99 } }, agentMarketRegime: { regime: "custom", regimeLabel: "一个长度超过十四字的真实历史阶段标签", confidence: null, keyDrivers: ["甲", "乙", "丙", "第四驱动"], summary: "历史摘要" } });
assert.ok(html.includes("一个长度超过十四字的真实历史阶段标签") && html.includes("第四驱动"));
assert.ok(html.includes("未量化")); assert.doesNotMatch(html.split('market-monitor-right-regime-list')[0], /99/);
const EventTrace = component("components/event-flow/EventGoldMainlineTrace.tsx", "EventGoldMainlineTrace");
const event = { id: "event:isolated", verification_chain: { source_count: null, official_source_count: null, independent_source_count: null, missing_confirmations: ["第一缺口", "第二缺口", "第三缺口", "第四缺口", "第五缺口", "第六关键缺口"] } };
html = render(EventTrace, { event });
assert.ok(html.includes("第六关键缺口"), "every blocking verification item must remain readable");
assert.doesNotMatch(html, /来源 0|独立源 0|官方源 0/, "missing source counts cannot become zero");
event.verification_chain.source_count = 0;
html = render(EventTrace, { event });
assert.ok(html.includes("来源 0"), "a provided zero source count remains zero");
console.log("Decision reading integrity: selected result ownership, full limitations, event links, missing factors, historical confidence OK");
