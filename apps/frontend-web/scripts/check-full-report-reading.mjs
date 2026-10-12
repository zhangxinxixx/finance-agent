import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
// Execute real components and local dependencies, without network or live data.
function loader(overrides = new Map()) {
  const cache = new Map();
  function load(name, parent = src) {
    if (overrides.has(name)) return overrides.get(name);
    if (!name.startsWith('.') && !name.startsWith('@/')) return require(name);
    const base = name.startsWith('@/') ? resolve(src, name.slice(2)) : resolve(parent, name);
    const filename = [base, `${base}.tsx`, `${base}.ts`].find(existsSync);
    assert.ok(filename, `Missing module ${name}`);
    if (cache.has(filename)) return cache.get(filename).exports;
    const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), {
      fileName: filename, reportDiagnostics: true,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    });
    assert.equal(compiled.diagnostics?.length ?? 0, 0, `Transpile diagnostics: ${filename}`);
    const module = { exports: {} };
    cache.set(filename, module);
    runInNewContext(compiled.outputText, { module, exports: module.exports, require: child => load(child, dirname(filename)), URL }, { filename });
    return module.exports;
  }
  return load;
}
const load = loader(new Map([
  ['@/adapters/pageDataBoundary.mjs', { summarizeEvidenceRecord: value => value }],
]));
const { MarkdownViewer } = load('@/components/reports/MarkdownViewer');
const { ReportArtifactPanel } = load('@/components/reports/ReportArtifactPanel');
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const long = '实际利率上升压制黄金，但避险需求仍可能抵消部分压力，需结合美元与资金流判断。'.repeat(210);
const repeated = '同一收益率2.10%在宏观与情景中分别作为依据。';
const content = [
  '# 完整黄金宏观日报', '**一句话结论：黄金保持观察，等待实际利率与美元共振确认。**',
  '## 一、宏观依据', repeated, long,
  '实际利率↑ → 持有黄金机会成本↑；[美联储依据](https://www.federalreserve.gov/monetarypolicy.htm)。',
  '## 二、统一数据表',
  '| 指标 | 当前值 | 来源 |\n| :--- | ---: | --- |\n| **实际利率** | 2.10% | [FRED](https://fred.stlouisfed.org/) |\n| 关系 | 黄金↑ \\| 美元↓ | 保留空单元 |\n| 缺口 | | 未核实 |',
  '图表前一段。\n![Gold Price and its Recurring Support/Resistance Zones](figures/gold.png)\n图表后一段。',
  '内嵌图像![内嵌黄金](figures/inline.png)保留前后正文；**[加粗来源](https://fred.stlouisfed.org/)**。',
  '## 三、情景推演', repeated, '### **情景与触发**', '#### 次级条件', '##### 细分依据', '###### 末级依据', '`![行内代码不是图片](inline-code.png)`',
  '```text\n#### 代码中的标题\n![代码不是图片](code.png)\n```',
  '<script>alert("原文只展示")</script> 与 <img src=x onerror=alert(1)>',
  '[不安全链接](javascript:evil) [数据链接](data:text/html,evil) [本地链接](file:///tmp/private)',
  '![不安全图片](javascript:evil)\n![数据图片](data:text/html,evil)\n![混淆图片](java\tscript:evil)',
  '## 四、末尾风险与失效', '末尾风险：若数据仍不完整，不能据此确认交易参考条件。', '最后来源：[财政部](https://home.treasury.gov/)。',
].join('\n\n');
assert.ok(content.length > 6000);
const full = render(MarkdownViewer, { content, readingMode: 'full', assetBaseUrl: 'https://reports.example/assets/', assetVersion: 'report-A' });
assert.ok(full.includes(long), 'Long paragraph must remain complete');
assert.equal(full.split(repeated).length - 1, 2, 'Meaningful repeated evidence stays');
let previous = -1;
for (const heading of ['完整黄金宏观日报', '一、宏观依据', '二、统一数据表', '三、情景推演', '次级条件', '细分依据', '末级依据', '四、末尾风险与失效']) {
  const position = full.indexOf(heading); assert.ok(position > previous, `Heading order: ${heading}`); previous = position;
}
assert.match(full, /<strong><span>一句话结论/);
assert.match(full, /<h3[^>]*><strong><span>情景与触发<\/span><\/strong><\/h3>/);
assert.match(full, /<h4[^>]*><span>次级条件/);
assert.match(full, /实际利率↑ → 持有黄金机会成本↑/);
assert.match(full, /href="https:\/\/www.federalreserve.gov\/monetarypolicy.htm" target="_blank" rel="noreferrer"/);
assert.match(full, /<td[^>]*><strong><span>实际利率<\/span><\/strong><\/td>/);
assert.match(full, /<td[^>]*><span>黄金↑ \| 美元↓<\/span><\/td>/);
assert.match(full, /<td[^>]*><\/td>/);
assert.match(full, /class="report-table-scroll"/);
assert.match(full, /src="https:\/\/reports.example\/assets\/figures\/gold.png\?v=report-A"/);
assert.match(full, /alt="Gold Price and its Recurring Support\/Resistance Zones"/);
assert.match(full, /<strong><a[^>]*href="https:\/\/fred.stlouisfed.org\/"/);
assert.match(full, /alt="内嵌黄金"/);
assert.equal((full.match(/<img\b/g) ?? []).length, 2, 'Unsafe and fenced images never mount');
assert.ok(full.indexOf('图表前一段') < full.indexOf('<figure') && full.indexOf('<figure') < full.indexOf('图表后一段'));
assert.match(full, /&lt;script&gt;alert\(&quot;原文只展示&quot;\)&lt;\/script&gt;/);
assert.doesNotMatch(full, /<script\b|onerror=\"|(?:href|src)="(?:javascript:|data:|file:)/);
assert.ok(full.includes('末尾风险：若数据仍不完整') && full.includes('最后来源：'));
assert.doesNotMatch(full, /<details\b|展开其余研究正文/);
assert.match(render(MarkdownViewer, { content: ' \n\t', readingMode: 'full' }), /本报告正文为空，暂不可阅读/);
const compact = render(MarkdownViewer, { content });
assert.equal(compact, render(MarkdownViewer, { content, readingMode: 'concise' }));
assert.ok(compact.length < full.length / 2 && !compact.includes(long));
assert.match(compact, /展开其余研究正文/);
const tab = { available: true, format: 'markdown', content, asset_base_url: 'https://reports.example/assets/', path: 'report-A' };
const panel = render(ReportArtifactPanel, { tab });
assert.ok(panel.includes(long) && panel.includes('末尾风险：若数据仍不完整'));
assert.doesNotMatch(panel, /展开其余研究正文/);
assert.match(panel, /查看原始报告/);
assert.ok(!render(ReportArtifactPanel, { tab: { ...tab, available: false } }).includes(long));
const json = render(ReportArtifactPanel, { tab: { ...tab, format: 'json', content: JSON.stringify({ source_ref: '/private/record', content }) } });
assert.ok(!json.includes(long) && !json.includes('/private/record'));
const html = render(ReportArtifactPanel, { tab: { ...tab, format: 'html', content: '<script>evil()</script><p>报告</p>' } });
assert.doesNotMatch(html, /<script\b|<iframe\b/);
// Controlled hooks execute the real page; supplementary cards use sentinels.
let route = 'A';
let data = { report_id: 'A', available_tabs: ['analysis', 'source'], tabs: { analysis: tab, source: { ...tab, content: '来源稿标记' } },
  data_status: 'available', meta: { lifecycle_status: 'reviewed', asset: 'XAUUSD' }, warnings: [], llm_audits: [] };
let states = [], cursor = 0, heroProps;
const effects = [];
const stub = label => props => React.createElement('section', null, label, props.children);
const hooks = { ...React,
  useState(initial) { const i = cursor++; if (!(i in states)) states[i] = initial; return [states[i], value => { states[i] = value; }]; },
  useMemo(fn) { return fn(); }, useEffect(fn) { effects.push(fn); },
};
const pageLoad = loader(new Map([
  ['react', hooks],
  ['@/adapters/pageDataBoundary.mjs', { summarizeEvidenceRecord: value => value }],
  ['@/components/reports/ReportAnalysisInputsPanel', { ReportAnalysisInputsPanel: stub('分析输入标记') }],
  ['react-router-dom', { useParams: () => ({ reportId: route }), useLocation: () => ({ state: null }), Link: stub('返回链接') }],
  ['@/hooks/useReportDetail', { useReportDetail: () => ({ data, isLoading: false, isRefreshing: false, error: null, refetch() {} }) }],
  ['@/components/reports/ReportDetailSections', { ReportDetailHero: props => { heroProps = props; return React.createElement('header', null, '报告身份'); }, ReportGenerationTraceCard: stub('审计记录'), ReportMarketObservationCard: stub('市场观察标记') }],
  ['@/components/reports/ReportMarketOddsMatrix', { ReportMarketOddsMatrix: stub('市场比较标记') }],
  ['@/components/shared/ResultIdentityBar', { ResultIdentityBar: stub('身份条') }],
  ['@/components/shared/FAWarningBanner', { FAWarningBanner: props => React.createElement('aside', null, props.title, props.description) }],
]));
const { ReportDetailPage } = pageLoad('@/pages/ReportDetailPage');
function page() { cursor = 0; return render(ReportDetailPage, {}); }
const first = page();
assert.ok(first.includes(long));
assert.ok(first.indexOf('查看市场比较与观察') > first.indexOf('末尾风险'));
assert.ok(!first.includes('市场比较标记'), 'Supplementary cards require deliberate expansion');
heroProps.onTabChange('source'); assert.match(page(), /来源稿标记/);
route = 'B'; data = { ...data, report_id: 'B' };
assert.ok(page().includes(long), 'Route change opens analysis before effects run');
assert.equal(heroProps.activeTab, 'analysis');
// Discard superseded render effects, then run the latest committed render effects.
effects.splice(0, effects.length - 1); effects.shift()();
assert.ok(page().includes(long));
data = { ...data, available_tabs: ['source'], tabs: { source: data.tabs.source } };
page(); effects.splice(0, effects.length - 1); effects.shift()();
assert.match(page(), /来源稿标记/, 'No analysis falls back to available tab');
data = { ...data, market_odds_evidence: { interpretation: { notice: '外部赔率不独立决定策略方向。' }, analysis_context: { quality_status: 'partial' } } };
assert.match(page(), /市场观察仅作单源辅助证据/);
assert.match(page(), /部分分析，需复核/);
data = { ...data, data_status: 'unavailable', meta: { ...data.meta, lifecycle_status: 'needs_review' } };
const refused = page();
assert.match(refused, /报告未通过质量审核/); assert.match(refused, /本次报告不可用/);
assert.ok(!refused.includes('来源稿标记') && !refused.includes('查看市场比较与观察'));
assert.equal(heroProps.tabs.length, 0);
// Preserve the API artifact body before it reaches the full reader. Keep the
// existing refusal for the legacy macro report whose entire data table is missing.
const adapterExports = {};
const adapterCode = ts.transpileModule(readFileSync(resolve(src, 'adapters/reports.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
runInNewContext(adapterCode, {
  exports: adapterExports,
  require(name) {
    if (name === '@/adapters/apiClient') return { ApiError: class extends Error {}, fetchJson() { throw new Error('No network in adapter regression'); } };
    if (name === '@/lib/status') return { normalizeDataStatus: value => value };
    if (name === '@/adapters/resultIdentity') return { normalizeResultIdentity: value => value };
    if (name === './inFlightRequest') return { createInFlightRequest: fn => fn };
    if (name === '@/adapters/researchTradePlan' || name === '@/adapters/researchIdentity') return load(name);
    throw new Error(`Unexpected adapter import: ${name}`);
  },
});
const withSources = content + '\r\n\r\n## 数据来源\r\n[原始来源](https://example.test/source)\r\n\r\n### 证据条件\r\n不要删除本段。\r\n';
assert.equal(adapterExports.sanitizeReportAnalysisMarkdown(withSources), withSources);
const legacyTitle = '# XAUUSD 宏观 / 流动性更新（工程样本）\n\n## 流动性与利率统一数据表\n';
const tableHead = '| 指标 | 当前值 | 日期 | 变化 | 来源 |\n| --- | --- | --- | --- | --- |\n';
const missing = legacyTitle + tableHead + '| 明确缺失 | 明确缺失 | 明确缺失 | 明确缺失 | 明确缺失 |\n\n## 数据来源\n来源缺口。';
assert.match(adapterExports.sanitizeReportAnalysisMarkdown(missing), /本次报告不可用/);
const valid = legacyTitle + tableHead + '| 工程指标 | 2.10 | 工程日期 | 待确认 | 已记录 |\n\n## 数据来源\n可追溯来源。';
assert.equal(adapterExports.sanitizeReportAnalysisMarkdown(valid), valid);
console.log('PASS: React SSR/component regression; full >6000-char narrative, order/repeats/formatting/sources/images/escaping/unsafe URLs, panel modes, concise default, JSON/HTML boundaries, page order/route tabs/quality refusal.');
