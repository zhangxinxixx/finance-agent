import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript"), React = require("react"), { renderToStaticMarkup } = require("react-dom/server");
const { StaticRouter } = require("react-router-dom");
const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const calls = [];
let responses = new Map();
const storage = new Map();
const apiClient = { fetchJson: async (url, init = {}) => {
  calls.push({ url, method: init.method ?? "GET" });
  assert.ok(responses.has(url), `Unexpected network request: ${url}`);
  const value = responses.get(url);
  if (value instanceof Error) throw value;
  return typeof value === "function" ? value() : structuredClone(value);
} };
function loader() {
  const cache = new Map();
  function load(name, parent = src) {
    if (name.endsWith(".css")) return {};
    if (name === "@/adapters/apiClient") return apiClient;
    if (!name.startsWith("@/") && !name.startsWith(".")) return require(name);
    const base = name.startsWith("@/") ? resolve(src, name.slice(2)) : resolve(parent, name);
    const file = [base + ".ts", base + ".tsx"].find(existsSync);
    assert.ok(file, name);
    if (cache.has(file)) return cache.get(file).exports;
    const source = readFileSync(file, "utf8").replaceAll("import.meta.env", "({})");
    const code = ts.transpileModule(source, { fileName: file,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const module = { exports: {} }; cache.set(file, module);
    runInNewContext(code, { module, exports: module.exports, require: child => load(child, dirname(file)),
      console, Intl, Date, URL, AbortController, setTimeout, clearTimeout,
      sessionStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    }, { filename: file });
    return module.exports;
  }
  return load;
}
const load = loader(), adapter = load("@/adapters/goldWorkspace");
const id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const identity = { report_id: "observation_report:engineering", run_id: id, snapshot_id: "engineering-snapshot", trade_date: "2026-10-07" };
const plan = { schema_version: "research_trade_plan.v1", ...identity, as_of: "2026-10-07T13:00:00Z", status: "waiting",
  execution_ready: false, is_trade_instruction: false, current_action: "等待确认，暂不开新单", summary: "工程判断：尚需结构确认。", reason: "工程验收原因。",
  entry: null, stop_loss: null, targets: [], attention_points: ["工程验收：结构止损超过20美元则等待。"],
  position_guidance: { flat: "工程空仓条件", long: "工程多仓条件", short: "工程空仓风险" },
  scenarios: [{ name: "工程主路径", macro_conditions: "工程宏观条件", price_conditions: "工程价格条件", invalidation: "工程失效条件" }] };
const fact = { key: "XAUUSD", label: "黄金现货", value: 1234.56, unit: "USD/oz", change: -1.2, change_unit: "%", change_window: "1d",
  observed_at: "2026-10-07T13:00:00Z", source: "engineering-source", frequency: "intraday", status: "fresh", impact: "unconfirmed", interpretation: "工程观测。", source_refs: [] };
const raw = { schema_version: "gold_workspace.v1", generated_at: "2026-10-07T13:00:00Z", status: "partial", price: fact,
  factors: [{ ...fact, key: "US10Y", label: "10Y", value: 4.56, unit: "%", change: 12, change_unit: "bp", change_window: "1w", frequency: "daily", status: "recent", impact: "pressure" }],
  research: { ...identity, status: "current", as_of: plan.as_of, bias: "bearish", summary: plan.summary, narrative: "工程完整正文尾段", authority: "observation_only", publish_allowed: false,
    trade_plan: plan, key_levels: [{ price: 1245, coordinate: "spot", instrument: "XAUUSD", role: "resistance" }, { price: 7777, coordinate: "gc_futures", instrument: "GC" }] },
  comparison: { status: "available", reference_price: 1244.56, reference_time: plan.as_of, price_change: -10, price_change_pct: -.8, note: "工程比较" }, warnings: [] };
const researchIdentity = { schema_version: "research_identity.v1", ...identity, research_version: "revision-7", data_as_of: null, generated_at: raw.generated_at,
  key_level_validity: { status: "expired", data_as_of: null, valid_until: "2020-01-01", reason_codes: ["backend_expired"] } };
raw.research.research_identity = researchIdentity;
const decoded = adapter.normalizeGoldWorkspace(raw);
assert.equal(JSON.stringify(decoded.research.research_identity), JSON.stringify(researchIdentity));
assert.equal(decoded.research.research_identity.data_as_of, null, "workspace generated_at cannot fill unknown research timing");
assert.equal(decoded.price.value, 1234.56);
assert.equal(decoded.factors[0].change, 12);
assert.equal(decoded.factors[0].change_window, "1w");
assert.equal(decoded.research.trade_plan.report_id, identity.report_id);
assert.equal(decoded.research.key_levels.length, 1);
for (const mutation of [{ run_id: "other" }, { execution_ready: true }, { entry: 1234 }, { current_action: "立即买入" }]) {
  assert.equal(adapter.normalizeGoldWorkspace({ ...raw, research: { ...raw.research, trade_plan: { ...plan, ...mutation } } }).research.trade_plan, null);
}
const blocked = adapter.normalizeGoldWorkspace({ ...raw, research: { ...raw.research, status: "unavailable" } });
assert.equal(blocked.research.bias, null); assert.equal(blocked.research.trade_plan, null); assert.equal(blocked.research.narrative, "");
assert.equal(adapter.normalizeGoldWorkspace({ ...raw, research: { ...raw.research, snapshot_id: null } }).research.status, "unavailable");
assert.equal(adapter.normalizeGoldWorkspace({ ...raw, factors: [{ ...raw.factors[0], status: "stale" }] }).factors[0].impact, "unconfirmed");
assert.equal(adapter.normalizeGoldWorkspace({ ...raw, price: { ...fact, value: Infinity } }).price.status, "unavailable");
assert.throws(() => adapter.normalizeGoldWorkspace({}), /不完整/);

const topic = { ...identity, as_of: raw.research.as_of, key: "curve_policy", label: "政策路径与长端资金成本", group: "macro", status: "current",
  basis: "verified_report_topics", judgment: "工程主题判断", facts: "工程主题依据", transmission: "工程传导链", response: "工程价格响应",
  alternatives: "工程竞争解释", falsification: "工程撤回条件", pending: ["工程拍卖缺口"], sections: [], note: "工程验收主题" };
const withTopics = { ...raw, research: { ...raw.research, topics: [topic] } };
const topicsDecoded = adapter.normalizeGoldWorkspace(withTopics);
assert.equal(topicsDecoded.research.topics[0].falsification, "工程撤回条件");
assert.equal(topicsDecoded.research.topics[0].pending[0], "工程拍卖缺口");
for (const field of ["report_id", "run_id", "snapshot_id", "trade_date", "as_of"]) {
  const bad = adapter.normalizeGoldWorkspace({ ...withTopics, research: { ...withTopics.research, topics: [{ ...topic, [field]: "other" }] } }).research.topics[0];
  assert.equal(bad.status, "unavailable"); assert.equal(bad.judgment, ""); assert.equal(bad.facts, ""); assert.equal(bad.falsification, "");
}
assert.equal(adapter.normalizeGoldWorkspace({ ...withTopics, research: { ...withTopics.research, topics: [topic, topic] } }).research.topics.length, 0);
assert.equal(adapter.normalizeGoldWorkspace({ ...withTopics, research: { ...withTopics.research, status: "unavailable" } }).research.topics[0].facts, "");
const GoldResearchTopics = load("@/components/gold-workspace/GoldResearchTopics").GoldResearchTopics;
const topicsMarkup = renderToStaticMarkup(React.createElement(StaticRouter, {}, React.createElement(GoldResearchTopics, { data: topicsDecoded, reviewOnly: false, initialGroup: "macro" })));
for (const value of ["工程主题判断", "工程撤回条件", "展开依据、传导、市场响应与反证"]) assert.ok(topicsMarkup.includes(value), `Topic reading missing: ${value}`);
assert.ok(!topicsMarkup.includes("工程竞争解释"), "Detailed reasoning should wait for deliberate expansion");
for (const key of ["facts", "transmission", "response", "alternatives", "falsification"]) assert.equal(topicsDecoded.research.topics[0][key], topic[key]);

responses = new Map([["/api/gold/workspace", raw]]);
const first = adapter.fetchGoldWorkspace(), second = adapter.fetchGoldWorkspace();
assert.equal(first, second); await Promise.all([first, second]);
assert.equal(calls.filter(call => call.url === "/api/gold/workspace").length, 1);
responses.set("/api/gold/workspace", new Error("engineering GET failure"));
await assert.rejects(adapter.fetchGoldWorkspace(), /failure/);
responses.set("/api/gold/workspace", raw);
assert.equal((await adapter.fetchGoldWorkspace()).price.value, 1234.56);

const preflight = { can_launch: true, force: false, blocking_reasons: [], active_dagster_run: null, active_legacy_task: null, source_readiness_summary: {} };
responses.set("/api/tasks/premarket/preflight", preflight);
responses.set("/api/tasks/premarket", { task_id: id });
const start1 = adapter.startGoldAnalysis(), start2 = adapter.startGoldAnalysis();
assert.equal(start1, start2); assert.equal((await start1).task_id, id);
assert.equal(calls.filter(call => call.method === "POST").length, 1);
assert.ok(calls.every(call => !call.url.includes("force=true")));
adapter.rememberGoldAnalysisTask(null);
responses.set("/api/tasks/premarket/preflight", { ...preflight, can_launch: false, active_dagster_run: { run_id: id, status: "STARTED" } });
assert.equal((await adapter.startGoldAnalysis()).phase, "running");
assert.equal(calls.filter(call => call.method === "POST").length, 1);
adapter.rememberGoldAnalysisTask(null);
responses.set("/api/tasks/premarket/preflight", { ...preflight, can_launch: false, blocking_reasons: ["source_readiness_blocked"] });
assert.equal((await adapter.startGoldAnalysis()).phase, "blocked");
assert.equal(calls.filter(call => call.method === "POST").length, 1);
responses.set("/api/tasks/premarket/preflight", { ...preflight, dagster_check_error: "engineering service unavailable" });
assert.equal((await adapter.startGoldAnalysis()).phase, "blocked");
assert.equal(calls.filter(call => call.method === "POST").length, 1, "Unverified service triggered a write");
responses.set("/api/tasks/premarket/preflight", preflight);
responses.set("/api/tasks/premarket", new Error("engineering POST response lost"));
assert.equal((await adapter.startGoldAnalysis()).phase, "uncertain");
const postCount = calls.filter(call => call.method === "POST").length;
assert.equal((await adapter.startGoldAnalysis()).phase, "uncertain");
assert.equal(calls.filter(call => call.method === "POST").length, postCount, "Uncertain POST was repeated");
responses.set("/api/tasks/premarket/preflight", { ...preflight, can_launch: false, active_dagster_run: { run_id: id, status: "STARTED" } });
assert.equal((await adapter.startGoldAnalysis()).task_id, id);
assert.equal(calls.filter(call => call.method === "POST").length, postCount);
responses.set(`/api/tasks/${id}`, { id, status: "success", steps: [{ name: "macro_collect", status: "success" }] });
assert.equal((await adapter.fetchGoldAnalysisTask(id)).status, "success");
responses.set(`/api/tasks/${id}`, { id: "wrong-task", status: "success" });
await assert.rejects(adapter.fetchGoldAnalysisTask(id), /不一致/);
await assert.rejects(adapter.fetchGoldAnalysisTask("../escape"), /无法核验/);

const { GoldEvidenceMatrix } = load("@/components/gold-workspace/GoldEvidenceMatrix");
const render = (component, props) => renderToStaticMarkup(React.createElement(StaticRouter, { location: "/dashboard" }, React.createElement(component, props)));
let html = render(GoldEvidenceMatrix, { factors: decoded.factors, reviewOnly: false });
for (const expected of ["利空", "长期宏观", "短线影响", "周变动 +12.00 基点", "工程观测"]) assert.ok(html.includes(expected), expected);
assert.ok(!html.includes("2026-10-07"), "Timestamps belong in source details");
html = render(GoldEvidenceMatrix, { factors: decoded.factors, reviewOnly: true });
assert.ok(html.includes("上次观测") && html.includes("影响待确认"));
assert.ok(!/>利空</.test(html));

const opposite = { ...raw.factors[0], key: "US30Y", label: "美国30Y收益率", change: -2, change_window: "1d", impact: "supportive",
  short_term_summary: "收益率日度下降，短线压力缓解。", macro_effect: { impact: "pressure", summary: "收益水平仍有持金成本约束。", basis: "holding_cost_level", window: "1mo", change: -40, unit: "bp" } };
const oppositeData = adapter.normalizeGoldWorkspace({ ...raw, factors: [opposite] });
html = render(GoldEvidenceMatrix, { factors: oppositeData.factors, reviewOnly: false });
assert.ok(html.includes("利好") && html.includes("利空") && html.includes("gold-tone--up") && html.includes("gold-tone--down"));
assert.ok(html.includes("短线影响 · 日度") && html.includes("持金成本约束"));
const staleOpposite = adapter.normalizeGoldWorkspace({ ...raw, factors: [{ ...opposite, status: "stale" }] });
assert.equal(staleOpposite.factors[0].macro_effect.impact, "unconfirmed");
assert.equal(staleOpposite.factors[0].impact, "unconfirmed");
const oils = ["WTI_SPOT", "BRENT_SPOT"].map(key => ({ ...fact, key, label: key, unit: "USD/bbl" }));
const eight = adapter.normalizeGoldWorkspace({ ...raw, factors: [...Array.from({ length: 6 }, (_, i) => ({ ...raw.factors[0], key: `engineering-${i}` })), ...oils] });
html = render(GoldEvidenceMatrix, { factors: eight.factors, reviewOnly: false });
assert.ok(html.includes("WTI_SPOT") && html.includes("BRENT_SPOT"), "Both oil observations must be visible without expansion");

const currentBlocked = adapter.normalizeGoldWorkspace({ ...raw, research: { ...raw.research, latest_status: "unavailable", latest_run_id: "newer-failed-run" } });
assert.equal(currentBlocked.research.status, "historical");
assert.equal(currentBlocked.research.run_id, id);
assert.equal(currentBlocked.research.latest_run_id, "newer-failed-run");
assert.equal(currentBlocked.comparison.status, "unavailable");

const env = { basis: "latest_observation_comparison", note: "工程比较基准，不是反转阈值", conditions: [
  { key: "US30Y", label: "美国30Y收益率", value: opposite.value, unit: "%", observed_at: opposite.observed_at,
    supportive_condition: "低于4.56%并继续回落", pressure_condition: "高于4.56%并继续上升" },
] };
const withEnv = adapter.normalizeGoldWorkspace({ ...raw, factors: [opposite], environment_watch: env });
assert.equal(withEnv.environment_watch.conditions.length, 1);
assert.equal(adapter.normalizeGoldWorkspace({ ...raw, factors: [opposite], environment_watch: { ...env,
  conditions: [{ ...env.conditions[0], value: 999 }] } }).environment_watch.conditions.length, 0);
const { GoldSpotLevels, GoldCmeLevels, GoldEnvironmentWatch } = load("@/components/gold-workspace/GoldKeyLevels");
html = render(GoldEnvironmentWatch, { data: withEnv, reviewOnly: false });
assert.ok(html.includes("4.56") && html.includes("比较基准") && !html.includes("2026-10-07"));
const spotTopic = { ...topic, key: "levels", group: "price", facts: "XAUUSD在1240至1250争夺，1220为下方低点。GC结构7777不可用于现货。",
  falsification: "XAUUSD收复1250后重新评估。GC结构到期后撤回。" };
const withSpot = adapter.normalizeGoldWorkspace({ ...raw, research: { ...raw.research, key_levels: [], topics: [spotTopic] } });
html = render(GoldSpotLevels, { data: withSpot });
assert.ok(html.includes("1240") && html.includes("1220") && html.includes("1250") && !html.includes("7777"));
const cme = { status: "reference", coordinate: "GC futures", trade_date: "2026-10-06", version_type: "PRELIM", reference_price: 4187.5,
  source_refs: [{ name: "engineering CME" }], levels: [{ coordinate: "GC futures", price: 4150, role: "primary_support", label: "主要支撑墙", meaning: "工程GC结构观察", expiry: "NOV26" }] };
const cmeData = adapter.normalizeGoldWorkspace({ ...raw, cme_structure: cme });
assert.equal(cmeData.cme_structure.levels.length, 1);
html = render(GoldCmeLevels, { data: cmeData });
assert.ok(html.includes("4,150.00") && html.includes("GC期货") && html.includes("初步版结构") && !html.includes("2026-10-06"));
assert.equal(adapter.normalizeGoldWorkspace({ ...raw, cme_structure: { ...cme, coordinate: "XAUUSD spot" } }).cme_structure.levels.length, 0);

const passage = (summary, key, status = "current", basis = "report_explicit") => ({ ...identity, as_of: plan.as_of, status, basis, horizon: key,
  summary, sections: [{ title: key, content: `${summary}\n\n工程失效条件完整尾段。` }], note: "工程周期说明" });
const horizonRaw = { ...raw, research: { ...raw.research, horizons: {
  short_term: passage("工程短线结构尚需确认。", "短线分析"), long_term: passage("工程长线背景存在分歧。", "长线分析"),
} } };
const horizonData = adapter.normalizeGoldWorkspace(horizonRaw);
assert.equal(horizonData.research.horizons.short_term.summary, "工程短线结构尚需确认。");
const wrongHorizon = adapter.normalizeGoldWorkspace({ ...horizonRaw, research: { ...horizonRaw.research,
  horizons: { ...horizonRaw.research.horizons, short_term: { ...horizonRaw.research.horizons.short_term, run_id: "wrong" } } } });
assert.equal(wrongHorizon.research.horizons.short_term.status, "unavailable");
assert.equal(wrongHorizon.research.horizons.short_term.summary, "");
assert.equal(decoded.research.horizons.long_term.status, "unavailable", "Old API must remain readable without fabricated horizons");
assert.equal(adapter.normalizeGoldWorkspace({ ...horizonRaw, research: { ...horizonRaw.research, status: "unavailable" } }).research.horizons.long_term.summary, "");
const { GoldAnalysisHorizons } = load("@/components/gold-workspace/GoldAnalysisHorizons");
html = render(GoldAnalysisHorizons, { data: horizonData, reviewOnly: false });
for (const expected of ["短线分析", "长线分析", "日内—未来1至3个交易日", "工程短线结构尚需确认", "工程长线背景存在分歧", "展开短线依据与改判条件"]) assert.ok(html.includes(expected), expected);
assert.ok(!html.includes("完整尾段"), "Long passages should require explicit expansion");
html = render(GoldAnalysisHorizons, { data: horizonData, reviewOnly: true });
assert.ok(html.includes("等待本次核验") && html.includes("需用最新行情重验"));

const { GoldMarketHeadline } = load("@/components/gold-workspace/GoldMarketHeadline");
for (const [change, css, label] of [[1.2, "up", "上涨"], [-1.2, "down", "下跌"], [null, "dim", "日涨跌待补齐"]]) {
  html = render(GoldMarketHeadline, { data: { ...horizonData, price: { ...fact, change, source: "twelvedata_xauusd_5m" } }, reviewOnly: false });
  assert.ok(html.includes(`gold-tone--${css}`) && html.includes(label), `${label} color and text`);
  assert.ok(html.includes("Twelve Data · 5分钟现货K线"));
  assert.ok(!html.includes("最新已采集现货 K 线读数"), "Source detail should not overwhelm the headline");
}
html = render(GoldMarketHeadline, { data: horizonData, reviewOnly: true });
assert.ok(!html.includes("↑ 上涨") && !html.includes("↓ 下跌"), "Failed refresh cannot color old changes as current");
const staleFactors = decoded.factors.map(f => ({ ...f, status: "stale", impact: "pressure" }));
html = render(GoldEvidenceMatrix, { factors: staleFactors, reviewOnly: false });
assert.ok(!/>利空</.test(html) && html.includes("影响待确认"), "Old factors cannot become current pressure");
console.log("Gold workspace behavioral checks passed: decoding, identity, units/windows, GET dedupe/recovery, guarded launch, uncertain write reconciliation and evidence rendering.");
