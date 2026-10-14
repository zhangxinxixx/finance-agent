import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import vm from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript'), React = require('react');
const { renderToStaticMarkup } = require('react-dom/server'), router = require('react-router-dom');
const root = path.resolve(new URL('../src', import.meta.url).pathname), cache = new Map();
let goldRequest, locationState = null;
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} }; cache.set(file, module);
  const code = ts.transpileModule(readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(code, { module, exports: module.exports, Intl, Date, console, require(name) {
    if (/useJin10Calendar|useEventFlowLiveFlash/.test(name)) throw new Error(`Forbidden homepage dependency: ${name}`);
    if (name === '@/adapters/apiClient') return { fetchJson() { throw new Error('Unexpected network request'); } };
    if (name === '@/hooks/useGoldWorkspace') return { useGoldWorkspace: () => goldRequest };
    if (name === '@/hooks/useGoldAnalysisRefresh') return { useGoldAnalysisRefresh: () => ({ phase: 'idle', message: '', task: null, start() {} }) };
    // Chart coverage has its own behavioral tests; this suite checks research and page states.
    if (name === './GoldPriceChart') return { GoldPriceChart: () => null };
    if (name.endsWith('.css')) return {};
    if (name === 'react-router-dom') return { ...router, useLocation: () => ({ state: locationState }), useOutletContext: () => null };
    if (!name.startsWith('@/') && !name.startsWith('.')) return require(name);
    const stem = name.startsWith('@/') ? path.join(root, name.slice(2)) : path.resolve(path.dirname(file), name);
    const target = [stem + '.ts', stem + '.tsx', ...(stem.endsWith('.mjs') ? [stem] : [])].find(existsSync);
    if (!target) throw new Error(name);
    return load(target);
  } }, { filename: file });
  return module.exports;
}
const { DashboardResearchBrief: Brief } = load(path.join(root, 'components/dashboard/DashboardResearchBrief.tsx'));
const model = load(path.join(root, 'components/dashboard/DashboardResearchBriefModel.ts'));
const { DashboardPage } = load(path.join(root, 'components/dashboard/DashboardPage.tsx'));
const metric = (value, data_date, source, extra = {}) => ({ value, data_date, source, ...extra });
const summary = {
  generated_at: '2099-01-01T12:00:00Z',
  integrated_macro: { research_identity: { schema_version: 'research_identity.v1', report_id: null, run_id: 'selected-run', snapshot_id: 'selected-snapshot', trade_date: '2026-10-06', research_version: 'fixture-v1', data_as_of: '2026-10-06T17:30:00Z', generated_at: '2026-10-06T18:00:00Z', key_level_validity: { status: 'historical', data_as_of: '2026-10-06T17:30:00Z', valid_until: null, reason_codes: [] } }, trade_date: '2026-10-06', run_id: 'selected-run', as_of: '2026-10-06T17:30:00Z', authority: 'observation_only', publish_allowed: false,
    reasoning: '# 完整解释\n\n黄金 4023.75，美债 4.123%，源日期 2026-10-05。利率上升压制持有黄金的相对收益。\n\n## 最后依据\n\n全文末段：突破 4098.25 后才核查条件，不能据此认定趋势。',
    dominant_driver: ['真实后端驱动'], trade_implication: '后端交易含义', trigger_upgrade: ['升级条件 4098.25'], trigger_downgrade: [], invalidation: ['后端失效条件'], risks: ['后端风险'],
    source_refs: [{ name: '同一观察稿', trade_date: '2026-10-06', source_ref: 'observation_report:selected-run' }] },
  market_summary: { XAUUSD: metric(4999, '2026-10-07', 'GC proxy', { instrument_kind: 'futures' }), DXY: metric(101.23, '2026-10-05', 'FRED'), US02Y: metric(3.95, '2026-10-04', 'Treasury'), US10Y: metric(4.123, '2026-10-03', 'Treasury'), REAL_10Y: metric(1.82, '2026-10-02', 'FRED') },
  realtime_quotes: { GC: { price: 5001 }, DXY: { price: 102.345, price_time: '2026-10-07T00:02:03Z', source: 'DXY feed' } },
  latest_reports: [{ title: '更新期权报告', type: 'options', trade_date: '2026-10-07', run_id: 'other-run', report_id: 'unrelated', status: 'ready' }], source_trace: [], latest_supplemental_report: null,
};
const result = { summary, has_data: true, view_model: null };
const render = element => renderToStaticMarkup(React.createElement(router.StaticRouter, { location: "/dashboard" }, element));
const brief = () => render(React.createElement(Brief, { dashboardResult: result, today: '2026-10-07' }));
let html = brief();
for (const text of ['4023.75', '4.123', '2026-10-05', '全文末段', '4098.25', '真实后端驱动', '后端失效条件', '后端风险', '研究观察稿', '今天尚无更新', '2026-10-07 01:30:00 北京时间', '未取得可验证现价', '102.345', '2026-10-07 08:02:03 北京时间', 'DXY feed', '2026-10-04', '2026-10-03', '2026-10-02']) assert.ok(html.includes(text), text);
for (const text of ['4999', '5001', '2099', 'Accepted', '中性', '/reports/unrelated', '降级条件']) assert.ok(!html.includes(text), `must not render ${text}`);
assert.ok(html.includes('/reports/observation_report%3Aselected-run'));
for (const disclosure of html.matchAll(/<details[^>]*>[\s\S]*?<\/details>/g)) assert.ok(!disclosure[0].includes('全文末段'), 'research narrative remains outside technical disclosures');
const tree = Brief({ dashboardResult: result, today: '2026-10-07' });
const footer = tree.props.children.find(child => child?.type === 'footer');
assert.equal(footer.props.children[0].props.state.dashboardResult, result);
assert.equal(footer.props.children[1].props.state.dashboardResult, result);
assert.equal(model.beijingToday(new Date('2026-10-06T16:01:00Z')), '2026-10-07');
assert.equal(model.beijingToday(new Date('2026-10-06T15:59:00Z')), '2026-10-06');
assert.equal(model.buildDashboardResearchBrief(summary, '2026-10-06').stale, false);
assert.equal(model.buildDashboardResearchBrief(summary, '2026-10-07').stale, true);
assert.ok(model.beijingTime('2026-10-07T08:00:00').includes('时区未提供'));
summary.realtime_quotes.XAUUSD = { price: 4028.12, trade_date: '2026-10-07', source: 'Spot feed' };
html = brief(); assert.ok(html.includes('4028.12')); assert.ok(html.includes('观测日期：2026-10-07（非即时行情）'));
assert.ok(!html.includes('未取得可验证现价'));
summary.realtime_quotes.XAUUSD.price_time = '2026-10-07T02:00:00Z';
assert.ok(brief().includes('行情时点：2026-10-07 10:00:00 北京时间'));
summary.realtime_quotes.XAUUSD.price_time = null;
summary.realtime_quotes.XAUUSD.time = '2026-10-07T17:05:00+08:00';
summary.realtime_quotes.XAUUSD.source = 'twelvedata_xauusd_5m';
assert.ok(brief().includes('5分钟K线时点：2026-10-07 17:05:00 北京时间'));
assert.ok(brief().includes('5分钟K线读数，非逐笔现价。'));
// The actual brief footer carries the same result into the report and detail routes.
assert.equal(footer.props.children[0].props.to, model.researchReportTarget(summary));
summary.integrated_macro.source_refs = [];
assert.equal(model.researchReportTarget(summary), null, 'never create report identity from run');
summary.latest_reports.push({ title: '同一研究', type: 'final_report', trade_date: '2026-10-06', run_id: 'selected-run', report_id: 'registered-id', status: 'ready' });
assert.equal(model.researchReportTarget(summary), '/reports/registered-id');
summary.latest_reports.at(-1).status = 'pending';
assert.equal(model.researchReportTarget(summary), null, 'pending report is not a readable full report');
summary.latest_reports.at(-1).status = 'ready';
summary.latest_reports.at(-1).trade_date = '2026-10-07';
assert.equal(model.researchReportTarget(summary), null, 'run and date must both match');
summary.integrated_macro.reasoning = ''; assert.ok(brief().includes('选中研究未提供分析正文'));
summary.integrated_macro.reasoning = '全文末段保留 4023.75';
const { normalizeGoldWorkspace } = load(path.join(root, 'adapters/goldWorkspace.ts'));
const current = normalizeGoldWorkspace({ schema_version: 'gold_workspace.v1', generated_at: '2026-10-07T13:00:00Z', price: { key: 'XAUUSD', status: 'unavailable' }, factors: [], research: { status: 'historical', report_id: 'fixture-report', run_id: 'selected-run', snapshot_id: 'selected-snapshot', trade_date: '2026-10-06', narrative: summary.integrated_macro.reasoning, summary: summary.integrated_macro.reasoning, research_identity: summary.integrated_macro.research_identity } });
goldRequest = { data: current, loading: false, error: new Error('refresh failed'), refetch() {} };
html = render(React.createElement(DashboardPage));
assert.ok(html.includes('读取失败') && html.includes('全文末段保留 4023.75'));
assert.ok(html.includes('等待本次核验') && html.includes('原判断需用最新行情重验'));
goldRequest.loading = true;
html = render(React.createElement(DashboardPage));
assert.ok(html.includes('全文末段保留 4023.75') && html.includes('等待本次核验'));
locationState = { dashboardResult: result };
html = render(React.createElement(DashboardPage));
assert.ok(html.includes('已返回同一研究结果') && html.includes('全文末段保留 4023.75'));
assert.ok(!html.includes('读取失败') && html.includes('返回最新黄金工作台'));
locationState = { dashboardResult: { has_data: false, summary: null } };
assert.ok(render(React.createElement(DashboardPage)).includes('所选研究结果不可用'));
locationState = null;
goldRequest = { data: null, loading: false, error: new Error('initial failed'), refetch() {} };
html = render(React.createElement(DashboardPage));
assert.ok(html.includes('读取失败') && html.includes('读取最新观测'));
assert.ok(!html.includes('全文末段保留 4023.75'));
goldRequest.error = null;
assert.ok(render(React.createElement(DashboardPage)).includes('黄金观测尚未可用'));
goldRequest.loading = true;
html = render(React.createElement(DashboardPage));
assert.ok(html.includes('正在读取黄金行情') && !html.includes('当前研究判断'));
console.log('Dashboard research brief: real current-page SSR, full text/numbers, independent clocks, Beijing dates, same report/navigation, frozen/error/loading/empty and no Jin10/event flash imports passed.');
