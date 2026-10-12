import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const root = path.resolve(new URL("../src", import.meta.url).pathname);
const cache = new Map();
const sections = { DashboardCompositeHeader: () => null, DashboardCompositeBody: () => null };
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} }; cache.set(file, module);
  const code = ts.transpileModule(readFileSync(file, "utf8"), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  vm.runInNewContext(code, {module,exports:module.exports,require(name) {
    if (name === "./DashboardCompositeSections") return sections;
    if (name === "@/hooks/useLiveStrategy") return { useLiveStrategy: () => ({ data: null, isLoading: true, error: null, refetch: () => {} }) };
    if (!name.startsWith("@/") && !name.startsWith(".")) return require(name);
    const stem = name.startsWith("@/") ? path.join(root,name.slice(2)) : path.resolve(path.dirname(file),name);
    const target = [stem+".ts",stem+".tsx"].find(existsSync);
    if (!target) throw new Error(name);
    return load(target);
  }}, {filename:file});
  return module.exports;
}
const {DashboardComposite} = load(path.join(root,"components/dashboard/DashboardComposite.tsx"));
const summary = {
  integrated_macro:{trade_date:"2026-09-29",run_id:"research-run",reasoning:"本次研究说明",confidence:null,invalidation:["明确失效条件"],risks:["重要风险不能伪装成失效条件"]},
  source_trace:[], latest_reports:[],agent_summary:null,strategy:{bias:"旧方向"},
  cme_options:{trade_date:"2026-10-02",lower_support_walls:[{strike:4000,score:0}],upper_resistance_walls:[],gamma_zero:null},
};
const viewModel = {strategy_card:{trade_date:"2026-09-06",scenario_summary:"旧策略摘要",confidence:0.99,invalid_conditions:["旧策略失效"],snapshot_id:"old-snapshot"},market_state:{summary:"外部市场说明",confidence:0.98},source_refs:[]};
function bodyOf(element) {return element.props.children.find((child)=>child?.type===sections.DashboardCompositeBody).props;}
let element = DashboardComposite({summary,viewModel});
let body = bodyOf(element);
assert.equal(body.compositeSummary,"本次研究说明");
assert.equal(body.confidencePct,null,"missing research confidence cannot borrow a different strategy's confidence");
assert.equal(body.revision,"明确失效条件");
assert.ok(!body.revision.includes("重要风险") && !body.revision.includes("旧策略"));
assert.ok(body.resonanceItems[0].macro.includes("GC") && body.resonanceItems[0].macro.includes("2026-10-02"));
assert.equal(body.resonanceItems[0].verdict,"结构参考，现货触发未核验");
summary.integrated_macro.reasoning="";summary.integrated_macro.invalidation=[];summary.integrated_macro.confidence=Infinity;
body=bodyOf(DashboardComposite({summary,viewModel}));
assert.equal(body.compositeSummary,"本次研究尚未提供综合分析摘要。");
assert.equal(body.confidencePct,null);
assert.equal(body.revision,"当前未提供明确改判条件。");
summary.integrated_macro.confidence=0;
assert.equal(bodyOf(DashboardComposite({summary,viewModel})).confidencePct,0);
const { DashboardStrategyStatus } = load(path.join(root,"components/dashboard/DashboardStrategyStatus.tsx"));
const dashboardResult = { summary, view_model: viewModel };
const statusCard = DashboardStrategyStatus({ dashboardResult });
assert.equal(statusCard.props.action.props.state.dashboardResult, dashboardResult,
  "navigation must keep the homepage result even before the live strategy request resolves");
assert.equal(statusCard.props.action.props.state.strategySource.tradeDate, "2026-09-29");
assert.equal(statusCard.props.action.props.state.strategySource.sourceResultIdentity, null);
console.log("Dashboard research provenance: no foreign summary/confidence/invalidation OK");
