import assert from 'node:assert/strict';
import { loader, React, renderToStaticMarkup, cases } from './strategy-test-harness.mjs';
import { reportFixture } from './report-qualification-fixtures.mjs';
import { goldPolicyFixture, goldPolicyMatrix, detailFixture, reportArtifact } from './gold-policy-report-fixtures.mjs';

const noNetwork = { ApiError: class extends Error {}, fetchJson() { throw new Error('Real network forbidden'); } };
const load = loader({ '@/adapters/apiClient': noNetwork });
const meta = load('@/components/reports/reportListMeta');
const model = load('@/components/reports/reportsPageModel');
const detailMeta = load('@/components/reports/reportDetailMeta');
const filters = { reportTypes: [], asset: null, status: null, dataSource: null, dateRange: null };
const html = (component, props) => renderToStaticMarkup(React.createElement(load('react-router-dom').StaticRouter,
  { location: '/reports' }, React.createElement(component, props)));
const ids = items => Array.from(items, item => item.report_id);

await cases([
  ['backend-index-gold-policy-is-discoverable', async () => {
    const item = goldPolicyFixture();
    const adapter = loader({ '@/adapters/apiClient': { ...noNetwork, fetchJson: async () => ({ asset: 'XAUUSD', reports: [item] }) } })('@/adapters/reports');
    const index = await adapter.fetchReportsIndex();
    assert.deepEqual(ids(model.dedupeSupportedReports(index.reports)), [item.report_id], 'A registered gold_policy_daily report must survive frontend filtering');
    assert.equal(meta.canOpenReport(index.reports[0]), true);
    assert.equal(meta.getReportDetailId(index.reports[0]), item.report_id);
  }],
  ['gold-policy-classification-search-and-counts', () => {
    const item = goldPolicyFixture('titleless', { title: null });
    assert.equal(meta.reportTypeLabel(item.type), '黄金日结报告');
    assert.match(meta.getReportTitle(item), /黄金现货（XAUUSD）黄金日结报告.*2026-10-13/);
    assert.equal(meta.inferAssetLabel(item), 'XAUUSD');
    assert.equal(meta.reportMatchesAsset(item, 'XAUUSD'), true);
    assert.equal(meta.reportMatchesAsset(item, 'OG'), false);
    assert.ok(meta.DOT_COLORS[item.type]);
    assert.ok(meta.TYPE_DESCRIPTIONS[item.type]);
    for (const query of ['黄金日结报告', 'gold_policy_daily', 'XAUUSD', '2026-10-13']) {
      assert.deepEqual(ids(model.filterReports([item], query, { ...filters, asset: 'XAUUSD', reportTypes: [item.type] })), [item.report_id]);
    }
    const reports = model.dedupeSupportedReports([...goldPolicyMatrix(), reportFixture('legacy')]);
    const rail = html(load('@/components/reports/ReportsRail').ReportsRail,
      { reports, filters, onFilterChange() {}, railLoading: false, railError: null });
    assert.match(rail, /黄金日结报告/);
    assert.equal(load('@/components/reports/reportsRailOptions').CATEGORY_CONFIGS.find(cat => cat.matchType === item.type).label, '黄金日结报告');
    assert.equal(model.filterReports(reports, '', { ...filters, reportTypes: [item.type] }).length, 7);
  }],
  ['same-day-versions-dedupe-only-the-same-report', () => {
    const original = goldPolicyFixture('A', { run_id: 'shared-run', publish_allowed: false });
    const revision = goldPolicyFixture('B', { run_id: original.run_id });
    const duplicate = { ...original, generated_at: '2026-10-13T06:00:00Z', title: '同一报告较新索引', lifecycle_status: 'needs_review', research_identity: null };
    const all = model.dedupeSupportedReports([original, revision, duplicate]);
    assert.deepEqual(ids(all), [original.report_id, revision.report_id], 'Different report IDs in the same run/day must remain separate');
    assert.equal(all[0], duplicate, 'Keep the complete freshest record; do not merge qualification/identity from another row');
    assert.equal(all[0].publish_allowed, false);
    assert.equal(all[0].research_identity, null);
    const runOnly = ['first', 'second'].map(run_id => goldPolicyFixture(run_id, { report_id: null, run_id }));
    assert.equal(model.dedupeSupportedReports([...runOnly, { ...runOnly[0] }]).length, 2);
    const unknown = goldPolicyFixture('no-identity', { report_id: null, run_id: null });
    assert.equal(model.dedupeSupportedReports([unknown, { ...unknown }]).length, 2, 'Unknown identities must not be treated as proven duplicates');
    assert.notEqual(meta.getReportItemKey(original, 0), meta.getReportItemKey(revision, 1));
  }],
  ['qualification-and-readability-remain-independent', () => {
    const adapter = load('@/adapters/reports');
    const expected = ['published', 'published', 'review', 'review', 'archived', 'review', 'unknown'];
    goldPolicyMatrix().forEach((item, index) => {
      const state = meta.getReportListStatus(item);
      assert.equal(state.key, expected[index]);
      assert.equal(meta.canOpenReport(item), true);
      const data = adapter.normalizeReportDetail(detailFixture(item), { analysis: {
        key: 'analysis', label: '分析稿', available: true, format: 'markdown', content: reportArtifact(item).content,
      } });
      assert.equal(detailMeta.getReportDetailStatus(data).description, state.description);
      assert.equal(data.tabs.analysis.content, reportArtifact(item).content);
      assert.equal(detailMeta.reportNeedsReadingWarning(data), index >= 2);
      for (const [name, props] of [
        ['ReportCard', { item, onSelect() {}, searchQuery: '' }],
        ['ReportsListView', { items: [item], onSelect() {}, searchQuery: '' }],
        ['ReportsTimelineView', { items: [item], onSelect() {}, searchQuery: '' }],
      ]) {
        const component = load(`@/components/reports/${name}`)[name === 'ReportsListView' ? 'ListView' : name === 'ReportsTimelineView' ? 'TimelineView' : name];
        assert.match(html(component, props), new RegExp(state.description.replace(/[()]/g, '\\$&')));
      }
      if (index >= 2) assert.equal(state.referenceOnly, true);
    });
  }],
  ['selected-report-content-and-missing-parts-do-not-borrow-latest', async () => {
    const a = goldPolicyFixture('A'), b = goldPolicyFixture('B');
    for (const item of [a, b]) {
      const requests = [];
      const adapter = loader({ '@/adapters/apiClient': { ...noNetwork, fetchJson: async path => {
        requests.push(path);
        assert.ok(path.startsWith(`/api/reports/${item.report_id}`));
        return path.endsWith('/analysis') ? reportArtifact(item) : detailFixture(item);
      } } })('@/adapters/reports');
      const data = await adapter.fetchReportDetailView(item.report_id);
      assert.equal(data.report_id, item.report_id);
      assert.equal(data.meta.run_id, item.run_id);
      assert.equal(data.research_identity.snapshot_id, item.snapshot_id);
      assert.equal(data.tabs.analysis.content, reportArtifact(item).content);
      assert.equal(requests.length, 2);
      assert.equal(detailMeta.reportSelectionDifference(item, data), null);
      assert.match(detailMeta.reportSelectionDifference(item === a ? b : a, data), /身份或版本不一致/);
    }
    const wrong = loader({ '@/adapters/apiClient': { ...noNetwork, fetchJson: async () => detailFixture(b) } })('@/adapters/reports');
    await assert.rejects(() => wrong.fetchReportDetailView(a.report_id), /身份/);
    const partial = loader({ '@/adapters/apiClient': { ...noNetwork, fetchJson: async path => path.endsWith('/analysis') ? reportArtifact(b) : detailFixture(a) } })('@/adapters/reports');
    const data = await partial.fetchReportDetailView(a.report_id);
    assert.equal(data.tabs.analysis, undefined);
    assert.ok(data.warnings.length > 0);
    assert.equal(data.report_id, a.report_id);
  }],
  ['legacy-dedupe-filters-and-return-query-unchanged', () => {
    for (const type of meta.SUPPORTED_REPORT_TYPES.filter(type => type !== 'gold_policy_daily')) {
      const old = reportFixture(`${type}-A`, { type, generated_at: '2026-10-13T01:00:00Z' });
      const newer = reportFixture(`${type}-B`, { type, generated_at: '2026-10-13T02:00:00Z' });
      const result = model.dedupeSupportedReports([old, newer]);
      assert.equal(result.length, ['final_report', 'jin10_market_observation_report'].includes(type) ? 2 : 1);
      if (result.length === 1) assert.equal(result[0], newer);
    }
    const navigation = load('@/components/reports/reportsNavigation');
    const target = '/reports?types=gold_policy_daily&asset=XAUUSD&q=%E9%BB%84%E9%87%91&page=2&view=grid';
    assert.equal(navigation.reportsReturnTarget({ reportsReturnTo: target }), target);
    const query = navigation.readReportsQuery(new URLSearchParams(target.split('?')[1]));
    assert.equal(query.currentPage, 2);
    assert.equal(query.filters.reportTypes[0], 'gold_policy_daily');
    assert.equal(query.filters.asset, 'XAUUSD');
    const unregistered = goldPolicyFixture('unknown-type', { type: 'unregistered_type' });
    assert.equal(model.dedupeSupportedReports([unregistered]).length, 0);
  }],
]);
