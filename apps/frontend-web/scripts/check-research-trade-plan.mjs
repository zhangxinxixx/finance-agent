import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';

const require = createRequire(import.meta.url);
const ts = require('typescript'), React = require('react');
const router = require('react-router-dom');
const { renderToStaticMarkup } = require('react-dom/server');
const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const apiResponses = new Map();
const apiClient = {
  ApiError: class extends Error {},
  fetchJson(url) {
    assert.ok(apiResponses.has(url), `Unexpected request (network forbidden): ${url}`);
    const value = apiResponses.get(url);
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
  },
};
function loader(overrides = new Map()) {
  const cache = new Map();
  function load(name, parent = src) {
    if (overrides.has(name)) return overrides.get(name);
    if (name === '@/adapters/apiClient') return apiClient;
    if (name === '@/adapters/pageDataBoundary.mjs') return { summarizeEvidenceRecord: value => value };
    if (!name.startsWith('.') && !name.startsWith('@/')) return require(name);
    const base = name.startsWith('@/') ? resolve(src, name.slice(2)) : resolve(parent, name);
    const filename = [base + '.tsx', base + '.ts'].find(existsSync);
    assert.ok(filename, `Missing module ${name}`);
    if (cache.has(filename)) return cache.get(filename).exports;
    const source = readFileSync(filename, 'utf8').replaceAll('import.meta.env', '({})');
    const compiled = ts.transpileModule(source, {
      fileName: filename, reportDiagnostics: true,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    });
    assert.equal(compiled.diagnostics?.length ?? 0, 0, filename);
    const module = { exports: {} }; cache.set(filename, module);
    runInNewContext(compiled.outputText, {
      module, exports: module.exports, require: child => load(child, dirname(filename)),
      Intl, Date, URL, URLSearchParams, console, setTimeout, clearTimeout, AbortController,
    }, { filename });
    return module.exports;
  }
  return load;
}
const load = loader();
const decoder = load('@/adapters/researchTradePlan');
const { normalizeReportDetail, fetchReportDetailView, sanitizeReportAnalysisMarkdown } = load('@/adapters/reports');
const { normalizeDashboardWithCurrentMarket } = load('@/adapters/api');
const { ResearchTradePlanCard } = load('@/components/shared/ResearchTradePlanCard');
const { DashboardResearchBrief } = load('@/components/dashboard/DashboardResearchBrief');
const render = (component, props) => renderToStaticMarkup(React.createElement(router.StaticRouter, { location: '/dashboard' }, React.createElement(component, props)));

const plan = {
  schema_version: 'research_trade_plan.v1', report_id: 'observation_report:selected', run_id: 'selected', snapshot_id: 'snapshot-A',
  trade_date: '2026-10-06', as_of: '2026-10-06T17:30:00Z', status: 'waiting', execution_ready: false, is_trade_instruction: false,
  current_action: '等待确认，暂不开新单', summary: '后端原判断：宏观与价格尚未共振，继续观察。', reason: '冻结原因：真实缺口未补齐。',
  scenarios: [
    { name: '主路径原名', macro_conditions: '实际利率与美元同向确认后再评估。', price_conditions: '4098.37 不是目标，回踩并完成15m确认才复核。', invalidation: '跌回4023.19则路径失效。' },
    { name: '上行路径（做多条件）', macro_conditions: ['美元回落但实际利率仍须确认。'], price_conditions: ['越过4127.83后等待结构回踩。', '真实缺口未闭合则继续等待。'], invalidation: ['重新跌回4098.37取消该观察路径。'] },
    { name: '下行路径（做空条件）', macro_conditions: '美元与实际利率共同走强。', price_conditions: '跌破3991.61且反抽失败才评估。', invalidation: '重新站回4023.19则失效。' },
  ],
  position_guidance: { flat: '空仓等待结构核验。', long: '已有多仓核对原风险预算。', short: '已有空仓核对失效条件。' },
  entry: null, stop_loss: null, targets: [],
  attention_points: ['4H/1H过滤，15m确认。', '真实缺口仍待补齐。', '事件不追第一根。', '结构止损超过20美元/盎司等待或跳过。', 'GC/XAU坐标边界不可混用。'],
};
const identity = { report_id: plan.report_id, run_id: plan.run_id, snapshot_id: plan.snapshot_id, trade_date: plan.trade_date };
const decoded = decoder.normalizeResearchTradePlan(plan, identity);
assert.equal(JSON.stringify(decoded), JSON.stringify(plan));
assert.notEqual(decoded, plan);
assert.notEqual(decoded.scenarios, plan.scenarios);
for (const mutation of [
  { schema_version: 'research_trade_plan.v2' }, { report_id: 'CME-unrelated' }, { run_id: 'other' }, { snapshot_id: 'other' }, { trade_date: '2026-10-07' },
  { execution_ready: true }, { execution_ready: 'false' }, { is_trade_instruction: true }, { status: 'ready' },
  { current_action: '立即买入' }, { entry: 4098.37 }, { stop_loss: 4023.19 }, { targets: [4127.83] },
  { attention_points: Array(33).fill('too many') }, { summary: 'x'.repeat(12001) },
  { as_of: '2026-10-06T17:30:00' }, { position_guidance: 'invalid' },
]) assert.equal(decoder.normalizeResearchTradePlan({ ...plan, ...mutation }, identity), null, JSON.stringify(mutation));
for (const bad of [undefined, null, [], 'text', {}]) assert.equal(decoder.normalizeResearchTradePlan(bad, identity), null);
assert.equal(decoded.entry, null); assert.equal(decoded.stop_loss, null); assert.equal(decoded.targets.length, 0);
const partial = decoder.normalizeResearchTradePlan({ ...plan, scenarios: [], summary: '', reason: null,
  position_guidance: { flat: null, long: null, short: null } }, identity);
assert.ok(partial, 'Verified waiting action and cautions survive missing optional path/guidance');
const partialHtml = render(ResearchTradePlanCard, { plan: partial });
assert.ok(partialHtml.includes(plan.current_action) && partialHtml.includes('该报告未提供完整的条件路径'));
assert.ok(!partialHtml.includes('4098.37'));

const body = '# 报告全文\n\n' + '完整依据段落，宏观与结构须分别核查。'.repeat(420) + '\n\n## 最后依据\n\n全文末段必须保留，原价位 4876.43。\n\n## 数据来源\n\n原始来源尾段不得删除。';
assert.ok(body.length > 6000);
const researchIdentity = { schema_version: "research_identity.v1", ...identity, research_version: "v7", data_as_of: plan.as_of, generated_at: "2099-01-01T00:00:00Z", key_level_validity: { status: "historical", data_as_of: plan.as_of, valid_until: null, reason_codes: [] } };
const research = {
  research_identity: researchIdentity,
  run_id: plan.run_id, trade_date: plan.trade_date, as_of: plan.as_of, authority: 'observation_only', publish_allowed: false,
  reasoning: body, source_refs: [{ source_ref: plan.report_id, trade_date: plan.trade_date }], final_trade_plan: plan,
};
const rawDashboard = {
  integrated_macro: research, latest_reports: [{ report_id: 'CME-unrelated', run_id: 'other', trade_date: '2026-10-07', type: 'options', title: 'CME', status: 'ready' }],
  current_market: { realtime_quotes: { XAUUSD: { price: 5678.91, price_time: '2026-10-07T00:02:03Z', source: 'Independent feed' } } },
};
let summary = normalizeDashboardWithCurrentMarket(rawDashboard);
assert.equal(summary.integrated_macro.final_trade_plan.report_id, plan.report_id);
let html = render(DashboardResearchBrief, { dashboardResult: { summary }, today: '2026-10-07' });
for (const value of [plan.current_action, ...plan.attention_points, '历史条件，需更新', '历史做单条件', '研究观察稿', '2026-10-07 01:30:00 北京时间', '2026-10-07 08:02:03 北京时间', '5678.91', '原始来源尾段不得删除']) assert.ok(html.includes(value), value);
assert.ok(html.indexOf('做单注意点') < html.indexOf('报告全文'));
assert.ok(html.indexOf('主路径原名') < html.indexOf('报告全文'));
assert.ok(html.includes(`/reports/${encodeURIComponent(plan.report_id)}`));
assert.ok(!html.includes('/reports/CME-unrelated'));
for (const scenario of plan.scenarios) {
  for (const value of [scenario.name, ...[scenario.macro_conditions, scenario.price_conditions, scenario.invalidation].flat()]) assert.ok(html.includes(value), value);
}
for (const value of ['入场待核验', '止损待核验', '目标未形成', '不等于执行许可']) assert.ok(html.includes(value));
for (const forbidden of ['已触发', '立即买入', '立即卖出', 'Accepted', '概率']) assert.ok(!html.includes(forbidden), forbidden);
for (const mutation of [
  { run_id: 'other' }, { trade_date: '2026-10-07' }, { source_refs: [] },
  { source_refs: [{ source_ref: 'CME-unrelated', trade_date: plan.trade_date }] },
  { source_refs: [{ source_ref: plan.report_id, trade_date: '2026-10-07' }] },
  { source_refs: [{ source_ref: plan.report_id, trade_date: plan.trade_date, snapshot_id: 'wrong-snapshot' }] },
  { final_trade_plan: { ...plan, execution_ready: true } }, { final_trade_plan: { ...plan, schema_version: 'unknown' } },
]) {
  const result = normalizeDashboardWithCurrentMarket({ ...rawDashboard, integrated_macro: { ...research, ...mutation } });
  assert.equal(result.integrated_macro.final_trade_plan, null);
  const refused = render(DashboardResearchBrief, { dashboardResult: { summary: result } });
  assert.ok(refused.includes('完整策略未提供') && refused.includes('等待核验'));
  assert.ok(!refused.includes('4098.37'));
  assert.ok(refused.includes('全文末段必须保留'));
}
assert.ok(decoder.normalizeDashboardTradePlan(plan, { ...research, source_refs: [{ report_id: plan.report_id, trade_date: plan.trade_date }] }));
assert.equal(decoder.normalizeDashboardTradePlan(plan, { ...research, source_refs: [{ report_id: 'conflicting', source_ref: plan.report_id, trade_date: plan.trade_date }] }), null);
const competingReport = normalizeDashboardWithCurrentMarket({ ...rawDashboard, latest_reports: [{ report_id: 'another-final', run_id: plan.run_id, trade_date: plan.trade_date, type: 'final_report', title: 'Another final', status: 'ready' }] });
const sameReportHtml = render(DashboardResearchBrief, { dashboardResult: { summary: competingReport } });
assert.ok(sameReportHtml.includes(`/reports/${encodeURIComponent(plan.report_id)}`) && !sameReportHtml.includes('/reports/another-final'));
html = render(ResearchTradePlanCard, { plan: decoded, identity: { ...researchIdentity, key_level_validity: { ...researchIdentity.key_level_validity, status: 'active' } }, today: '2026-10-06' });
assert.ok(html.includes('当前做单策略：等待确认，暂不开新单'));
assert.ok(!html.includes('历史条件'));
html = render(ResearchTradePlanCard, { plan: null, identity: researchIdentity, tradeDate: plan.trade_date, today: '2026-10-07' });
assert.ok(html.includes('等待核验') && html.includes('目标未形成') && !html.includes('各路径分别等什么'));

const rawDetail = {
  ...identity, family: 'final_report', title: '同一研究报告', asset: 'XAUUSD', generated_at: plan.as_of,
  lifecycle_status: 'reviewed', data_status: 'available', artifacts: [], source_refs: [], artifact_refs: [], warnings: [], input_snapshot_ids: [], review_items: [],
  research_identity: researchIdentity,
  current_context: { relationship: 'current_context_only', context_as_of: '2030-01-01T00:00:00Z', market_odds: { independent_context: '当前背景样本' } },
  structured_payload: { _reader_trade_plan: plan },
};
const tab = { tab: 'analysis', label: '分析稿', available: true, format: 'markdown', content: body };
const parts = { analysis: tab, source: { ...tab, tab: 'source', content: '来源稿标记' }, evidence: { ...tab, tab: 'evidence', content: '证据稿标记' } };
let detail = normalizeReportDetail(rawDetail, parts);
assert.equal(detail.final_trade_plan.report_id, plan.report_id);
assert.equal(detail.tabs.analysis.content, body);
assert.equal(detail.meta.asOf, researchIdentity.data_as_of);
assert.equal(detail.current_context.market_odds.independent_context, "当前背景样本");
assert.equal(detail.structured_payload._reader_trade_plan.summary, plan.summary);
assert.equal(normalizeReportDetail({ ...rawDetail, research_identity: null }, parts).meta.asOf, undefined, "generation time cannot substitute for unknown research data time");
for (const key of ['report_id', 'run_id', 'snapshot_id', 'trade_date']) {
  const bad = normalizeReportDetail({ ...rawDetail, [key]: 'mismatch' }, parts);
  assert.equal(bad.final_trade_plan, null, key);
}
for (const mutation of [{ execution_ready: true }, { schema_version: 'v2' }, { status: 'ready' }]) {
  assert.equal(normalizeReportDetail({ ...rawDetail, structured_payload: { _reader_trade_plan: { ...plan, ...mutation } } }, parts).final_trade_plan, null);
}
assert.equal(normalizeReportDetail({ ...rawDetail, structured_payload: null }, parts).final_trade_plan, null);
assert.equal(sanitizeReportAnalysisMarkdown(body), body);
// Real fetch adapter against isolated in-memory responses, never backend storage.
apiResponses.set(`/api/reports/${plan.report_id}`, rawDetail);
apiResponses.set(`/api/reports/${plan.report_id}/analysis-inputs`, null);
assert.equal((await fetchReportDetailView(plan.report_id)).final_trade_plan.report_id, plan.report_id);
apiResponses.set(`/api/reports/${plan.report_id}`, { ...rawDetail, artifacts: [
  { artifact_type: 'analysis_md', artifact_id: 'analysis-A' }, { artifact_type: 'structured_json', artifact_id: 'evidence-A' },
] });
apiResponses.set(`/api/reports/${plan.report_id}/analysis`, { report_id: plan.report_id, artifact_type: 'analysis_md', content_type: 'text/markdown', path: '/isolated-test/analysis', content: body });
apiResponses.set(`/api/reports/${plan.report_id}/evidence`, new Error('Isolated evidence read failure'));
const fetched = await fetchReportDetailView(plan.report_id);
assert.equal(fetched.final_trade_plan.report_id, plan.report_id);
assert.equal(fetched.tabs.analysis.content, body, 'Optional evidence failure preserves the complete body');
assert.ok(fetched.warnings.some(warning => warning.field === 'evidence'));
assert.equal(fetched.meta.lifecycle_status, rawDetail.lifecycle_status);

// Execute the actual page with controlled hooks and click the real hero tab callback.
let route = plan.report_id, states = [], cursor = 0, hero;
const hooks = { ...React,
  useState(initial) { const i = cursor++; if (!(i in states)) states[i] = initial; return [states[i], value => { states[i] = value; }]; },
  useMemo(fn) { return fn(); }, useEffect() {},
};
const stub = () => null;
const pageLoad = loader(new Map([
  ['react', hooks],
  ['react-router-dom', { ...router, useParams: () => ({ reportId: route }), useLocation: () => ({ state: null }) }],
  ['@/hooks/useReportDetail', { useReportDetail: () => ({ data: detail, isLoading: false, isRefreshing: false, refetch() {} }) }],
  ['@/components/reports/ReportDetailSections', { ReportDetailHero: props => { hero = props; return null; }, ReportGenerationTraceCard: stub, ReportMarketObservationCard: stub, ReportGoldMacroOverviewCard: load("@/components/reports/ReportDetailSections").ReportGoldMacroOverviewCard }],
  ['@/components/reports/ReportMarketOddsMatrix', { ReportMarketOddsMatrix: stub }],
  ['@/components/shared/ResearchDetails', { ResearchDetails: ({ label, children }) => React.createElement('section', null, label, children) }],
  ['@/components/shared/ResultIdentityBar', { ResultIdentityBar: stub }],
]));
const { ReportDetailPage } = pageLoad('@/pages/ReportDetailPage');
const page = () => { cursor = 0; return render(ReportDetailPage, {}); };
html = page();
assert.ok(html.includes("查看当前背景（独立于原始研究）") && html.includes("当前背景样本"));
assert.ok(html.indexOf('做单注意点') < html.indexOf('报告全文'));
assert.ok(html.includes('全文末段必须保留') && html.includes('原始来源尾段不得删除'));
for (const value of [plan.current_action, ...plan.attention_points]) assert.ok(html.includes(value));
for (const target of ['source', 'evidence', 'inputs']) {
  hero.onTabChange(target); html = page();
  assert.ok(!html.includes('做单注意点') && !html.includes(plan.current_action), target);
}
hero.onTabChange('analysis');
detail = normalizeReportDetail({ ...rawDetail, data_status: 'unavailable', lifecycle_status: 'needs_review' }, parts);
html = page();
assert.ok(html.includes('报告未通过质量审核') && html.includes('本次报告不可用'));
assert.ok(!html.includes('做单注意点') && !html.includes('报告全文'));
assert.equal(hero.tabs.length, 0);
detail = normalizeReportDetail({ ...rawDetail, structured_payload: null }, parts);
html = page(); assert.ok(html.includes('等待核验') && html.includes('全文末段必须保留'));
// A new route must never display the old report's plan even if the hook returns stale data.
detail = normalizeReportDetail(rawDetail, parts); route = 'new-report';
html = page(); assert.ok(!html.includes('做单注意点') && !html.includes(plan.current_action));
detail = normalizeReportDetail({ ...rawDetail, report_id: route, structured_payload: null }, parts);
html = page(); assert.ok(html.includes('等待核验') && !html.includes('4098.37'));
assert.equal(hero.activeTab, 'analysis');
console.log('PASS research trade plan: bounded adapter/version/flags/identities; dynamic condition prose; no execution prices; actual Dashboard and Report Page SSR; independent Beijing clocks/history/observation; absent/blocked/tabs/route isolation; complete >6000 character body and tail.');

// Keep the existing full-reading regression runnable on its own as well.
await import('./check-full-report-reading.mjs');
