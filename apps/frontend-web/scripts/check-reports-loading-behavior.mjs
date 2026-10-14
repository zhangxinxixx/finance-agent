// Execute the real hook, adapters, and consumer renderers. Only transport and
// the hook scheduler are isolated; these fixtures have no financial meaning.
import assert from 'node:assert/strict';
import { React, renderToStaticMarkup, loader, hookRunner, deferred, tick } from './strategy-test-harness.mjs';
import { reportFixture } from './report-qualification-fixtures.mjs';

const index = id => ({ asset: 'XAUUSD', reports: id ? [reportFixture(id)] : [] });
const dates = day => ({ asset: 'XAUUSD', dates: day ? [{ trade_date: day, modules: [] }] : [], total_dates: day ? 1 : 0 });
const error = part => new Error(`${part} 503`);
function setup() {
  let now = '2030-01-01T00:00:00Z';
  class ClockDate extends Date { constructor(...args) { super(...(args.length ? args : [now])); } }
  const requests = { index: [], dates: [] };
  const adapters = loader({ '@/adapters/apiClient': { fetchJson(path) {
    assert.ok(['/api/reports/index', '/api/reports/dates'].includes(path));
    const request = deferred(); requests[path.endsWith('index') ? 'index' : 'dates'].push(request);
    return request.promise;
  } } })('@/adapters/reports');
  const mount = () => {
    const runner = hookRunner('@/hooks/useReports', 'useReports', { '@/adapters/reports': adapters }, { Date: ClockDate });
    runner.render(); runner.flush(); return runner;
  };
  const runner = mount();
  return { requests, runner, mount, time(value) { now = value; },
    async finish(part, value, fail = false) {
      requests[part].at(-1)[fail ? 'reject' : 'resolve'](value); await tick(); return runner.flush();
    },
    refresh() { runner.flush().refetch(); return runner.flush(); },
  };
}
const ids = state => Array.from(state.indexItems, item => item.report_id);
const hasTime = value => assert.ok(typeof value === 'string' && !Number.isNaN(Date.parse(value)));
const entries = [
  ['index-readable-before-dates-settle', async () => {
    const s = setup(); const state = await s.finish('index', index('A'));
    assert.deepEqual(ids(state), ['A']); assert.equal(state.indexLoading, false);
    assert.equal(state.indexHasLoaded, true); assert.equal(state.datesLoading, true);
    assert.equal(state.datesHasLoaded, false); hasTime(state.indexReadAt); assert.equal(state.datesReadAt, null);
  }],
  ['index-success-dates-failure', async () => {
    const s = setup(); await s.finish('dates', error('dates'), true);
    const state = await s.finish('index', index('A'));
    assert.deepEqual(ids(state), ['A']); assert.equal(state.indexError, null); assert.equal(state.datesError.message, 'dates 503');
  }],
  ['index-failure-dates-success', async () => {
    const s = setup(); await s.finish('index', error('index'), true);
    const state = await s.finish('dates', dates('2026-10-13'));
    assert.deepEqual(ids(state), []); assert.equal(state.indexHasLoaded, false); assert.equal(state.indexReadAt, null);
    assert.equal(state.indexError.message, 'index 503'); assert.equal(state.dates[0].trade_date, '2026-10-13'); hasTime(state.datesReadAt);
  }],
  ['both-success-independent-completion-times', async () => {
    const s = setup(); const first = await s.finish('dates', dates('2026-10-13'));
    assert.equal(first.indexLoading, true); s.time('2030-01-01T00:01:00Z');
    const state = await s.finish('index', index('A'));
    assert.equal(state.indexReadAt, '2030-01-01T00:01:00.000Z'); assert.equal(state.datesReadAt, '2030-01-01T00:00:00.000Z');
    assert.equal(state.indexItems[0].generated_at, '2026-10-13T04:00:00Z');
  }],
  ['both-fail-then-retry', async () => {
    const s = setup(); await s.finish('index', error('index'), true); await s.finish('dates', error('dates'), true);
    s.refresh(); const state = await s.finish('index', index('retry')); await s.finish('dates', dates('2026-10-13'));
    assert.deepEqual(ids(state), ['retry']); assert.equal(state.indexError, null);
    assert.equal(s.requests.index.length, 2); assert.equal(s.requests.dates.length, 2);
  }],
  ['refresh-keeps-data-and-read-times-while-pending', async () => {
    const s = setup(); await s.finish('index', index('A')); await s.finish('dates', dates('2026-10-12'));
    const old = s.runner.flush(); s.time('2030-01-01T01:00:00Z'); const state = s.refresh();
    assert.deepEqual(ids(state), ['A']); assert.equal(state.indexReadAt, old.indexReadAt); assert.equal(state.datesReadAt, old.datesReadAt);
    assert.equal(state.indexLoading, true); assert.equal(state.datesLoading, true);
  }],
  ['refresh-new-index-kept-despite-dates-failure', async () => {
    const s = setup(); await s.finish('index', index('A')); await s.finish('dates', dates('2026-10-12'));
    const before = s.runner.flush(); s.time('2030-01-01T02:00:00Z'); s.refresh();
    const immediate = await s.finish('index', index('B')); assert.deepEqual(ids(immediate), ['B']);
    const state = await s.finish('dates', error('dates'), true);
    assert.deepEqual(ids(state), ['B']); assert.equal(state.dates[0].trade_date, '2026-10-12');
    assert.equal(state.datesReadAt, before.datesReadAt); assert.notEqual(state.indexReadAt, before.indexReadAt);
  }],
  ['refresh-index-failure-keeps-old-index-new-dates', async () => {
    const s = setup(); await s.finish('index', index('A')); await s.finish('dates', dates('2026-10-12'));
    const before = s.runner.flush(); s.time('2030-01-01T03:00:00Z'); s.refresh();
    await s.finish('index', error('index'), true); const state = await s.finish('dates', dates('2026-10-13'));
    assert.deepEqual(ids(state), ['A']); assert.equal(state.indexReadAt, before.indexReadAt);
    assert.notEqual(state.datesReadAt, before.datesReadAt); assert.equal(state.dates[0].trade_date, '2026-10-13');
  }],
  ['successful-empty-is-loaded-without-error', async () => {
    const s = setup(); const state = await s.finish('index', index());
    assert.deepEqual(ids(state), []); assert.equal(state.indexHasLoaded, true); assert.equal(state.indexError, null); hasTime(state.indexReadAt);
  }],
  ['refresh-empty-replaces-old-index', async () => {
    const s = setup(); await s.finish('index', index('A')); await s.finish('dates', dates('2026-10-12')); s.refresh();
    const state = await s.finish('index', index()); assert.deepEqual(ids(state), []);
    assert.deepEqual(Array.from(state.finalReportItems), []); assert.equal(state.indexHasLoaded, true);
  }],
  ['empty-dates-replaces-old-dates', async () => {
    const s = setup(); await s.finish('index', index('A')); await s.finish('dates', dates('2026-10-12')); s.refresh();
    const state = await s.finish('dates', dates()); assert.deepEqual(Array.from(state.dates), []); assert.equal(state.datesHasLoaded, true);
  }],
  ['pending-dates-do-not-block-another-index-refresh', async () => {
    const s = setup(); await s.finish('index', index('A')); s.refresh(); await s.finish('index', index('B'));
    assert.deepEqual(ids(s.runner.flush()), ['B']); assert.equal(s.requests.dates.length, 1);
  }],
  ['rapid-refresh-shares-pending-transport', async () => {
    const s = setup(); s.refresh(); s.refresh(); assert.equal(s.requests.index.length, 1); assert.equal(s.requests.dates.length, 1);
    const state = await s.finish('index', index('A')); assert.deepEqual(ids(state), ['A']);
  }],
  ['obsolete-completion-cannot-change-new-generation-read-time', async () => {
    const s = setup(); s.refresh(); s.time('2030-01-01T04:00:00Z'); await s.finish('index', index('A'));
    s.refresh(); s.time('2030-01-01T05:00:00Z'); await s.finish('index', index('B'));
    const state = s.runner.flush(); assert.deepEqual(ids(state), ['B']); assert.equal(state.indexReadAt, '2030-01-01T05:00:00.000Z');
  }],
  ['unmount-ignores-late-success-and-failure', async () => {
    const s = setup(); s.runner.unmount(); await s.finish('index', index('late')); await s.finish('dates', error('dates'), true);
    assert.equal(s.runner.writesAfterUnmount, 0);
  }],
  ['shared-consumer-unmount-does-not-cancel-another', async () => {
    const s = setup(); const other = s.mount(); s.runner.unmount();
    assert.equal(s.requests.index.length, 1); assert.equal(s.requests.dates.length, 1);
    await s.finish('index', index('shared')); const state = other.flush(); assert.deepEqual(ids(state), ['shared']);
    await s.finish('dates', dates('2026-10-13')); assert.equal(other.flush().dates.length, 1); assert.equal(s.runner.writesAfterUnmount, 0);
  }],
  ...['success', 'failure'].map(outcome => [`obsolete-${outcome}-cannot-overwrite-later-results`, async () => {
    // Deliberately non-coalescing transport to exercise the hook's own guard,
    // independently of the real adapter's in-flight deduplication above.
    const pending = { index: [], dates: [] };
    const request = part => { const item = deferred(); pending[part].push(item); return item.promise; };
    const runner = hookRunner('@/hooks/useReports', 'useReports', { '@/adapters/reports': {
      fetchReportsIndex: () => request('index'), fetchReportsDates: () => request('dates'),
    } });
    runner.render(); runner.flush(); runner.flush().refetch(); runner.flush();
    pending.index[1].resolve(index('new')); pending.dates[1].resolve(dates('2026-10-13')); await tick();
    const newer = runner.flush();
    if (outcome === 'success') { pending.index[0].resolve(index('old')); pending.dates[0].resolve(dates('2026-10-12')); }
    else { pending.index[0].reject(error('old index')); pending.dates[0].reject(error('old dates')); }
    await tick(); const state = runner.flush();
    assert.deepEqual(ids(state), ['new']); assert.equal(state.dates[0].trade_date, '2026-10-13');
    assert.equal(state.indexError, null); assert.equal(state.datesError, null);
    assert.equal(state.indexReadAt, newer.indexReadAt); assert.equal(state.datesReadAt, newer.datesReadAt);
  }]),
];

const filters = { reportTypes: [], asset: null, status: null, dataSource: null, dateRange: null };
const baseState = { asset: 'XAUUSD', dates: [], indexItems: [reportFixture('A')], finalReportItems: [],
  indexLoading: false, indexError: null, indexHasLoaded: true, indexReadAt: '2030-01-01T01:00:00Z',
  datesLoading: false, datesError: null, datesHasLoaded: false, datesReadAt: null, refetch() {} };
function renderPage(state) {
  const load = loader({ '@/hooks/useReports': { useReports: () => state }, 'react-router-dom': {
    useNavigate: () => () => {}, useLocation: () => ({ search: '?q=A' }),
    useSearchParams: () => [new URLSearchParams('q=A'), () => {}],
  } }, { window: { matchMedia: () => ({ matches: true }) } });
  return renderToStaticMarkup(React.createElement(load('@/pages/ReportsPage').ReportsPage));
}
entries.push(
  ['page-dates-error-does-not-hide-list-or-filters', () => {
    const html = renderPage({ ...baseState, datesError: error('dates') });
    assert.match(html, /reports-list-row/); assert.match(html, /报告日期暂不可用/); assert.match(html, /搜索报告/);
    assert.doesNotMatch(html, /报告索引加载失败/); assert.match(html, /筛选导航/);
  }],
  ['page-index-failure-retains-successful-date-fact', () => {
    const html = renderPage({ ...baseState, indexItems: [], indexHasLoaded: false, indexReadAt: null, indexError: error('index'),
      dates: dates('2026-10-13').dates, datesHasLoaded: true, datesReadAt: '2030-01-01T00:00:00Z' });
    assert.match(html, /报告索引加载失败/); assert.match(html, /2026-10-13/); assert.doesNotMatch(html, /reports-list-row/);
  }],
  ['page-successful-empty-retains-scaffold-during-refresh', () => {
    const html = renderPage({ ...baseState, indexItems: [], indexLoading: true, datesLoading: true });
    assert.match(html, /暂无已登记报告/); assert.match(html, /筛选导航/); assert.match(html, /搜索报告/);
    assert.doesNotMatch(html, /aria-busy="true"/);
  }],
  ['page-refresh-error-retains-rows-and-labels-old-read-time', () => {
    const html = renderPage({ ...baseState, indexError: error('index') });
    assert.match(html, /reports-list-row/); assert.match(html, /保留上次报告索引/); assert.match(html, /2030-01-01T01:00:00Z/);
    assert.match(html, /非研究数据时点/);
  }],
  ['page-stale-dates-are-not-labelled-latest', () => {
    const html = renderPage({ ...baseState, dates: dates('2026-10-12').dates, datesHasLoaded: true,
      datesReadAt: '2030-01-01T00:00:00Z', datesError: error('dates') });
    assert.match(html, /上次日期/); assert.doesNotMatch(html, />最新</); assert.match(html, /2030-01-01T00:00:00Z/);
  }],
  ['rail-controls-retained-during-background-read', () => {
    const Rail = loader()('@/components/reports/ReportsRail').ReportsRail;
    const html = renderToStaticMarkup(React.createElement(Rail, { reports: baseState.indexItems, filters, onFilterChange() {},
      railLoading: true, railError: null, indexHasLoaded: true }));
    assert.match(html, /筛选导航/); assert.match(html, /报告类型/);
  }],
  ['rail-controls-retained-after-refresh-error-even-with-empty-result', () => {
    const Rail = loader()('@/components/reports/ReportsRail').ReportsRail;
    const html = renderToStaticMarkup(React.createElement(Rail, { reports: [], filters, onFilterChange() {},
      railLoading: false, railError: error('index'), indexHasLoaded: true }));
    assert.match(html, /筛选导航/); assert.match(html, /报告类型/);
  }],
  ['event-candidates-retained-on-background-read-and-failure', () => {
    const Card = loader({ '@/adapters/eventFlow': {}, '@/adapters/eventFlowEvent': {}, '@/adapters/apiClient': {} })('@/pages/EventFlowDetailPage').EventRelatedReportsCard;
    for (const props of [{ isLoading: true, error: null }, { isLoading: false, error: error('index') }]) {
      const html = renderToStaticMarkup(React.createElement(Card, { reports: baseState.indexItems, indexHasLoaded: true,
        indexReadAt: baseState.indexReadAt, onOpen() {}, onRetry() {}, ...props }));
      assert.match(html, /同日候选 ·/); assert.match(html, /非研究数据时点/);
    }
  }],
  ['event-successful-empty-differs-from-initial-error', () => {
    const Card = loader({ '@/adapters/eventFlow': {}, '@/adapters/eventFlowEvent': {}, '@/adapters/apiClient': {} })('@/pages/EventFlowDetailPage').EventRelatedReportsCard;
    const html = renderToStaticMarkup(React.createElement(Card, { reports: [], indexHasLoaded: true, indexReadAt: baseState.indexReadAt,
      isLoading: false, error: error('index'), onOpen() {}, onRetry() {} }));
    assert.match(html, /暂无同日候选报告/); assert.match(html, /保留上次报告索引/);
  }],
);
const filter = process.argv.find(arg => arg.startsWith('--case='))?.slice(7);
let passed = 0, failed = 0;
for (const [name, test] of entries) {
  if (filter && name !== filter) continue;
  try { await test(); console.log(`${name}: PASS`); passed++; }
  catch (error) { console.error(`${name}: FAIL\n${error.stack}`); failed++; }
}
assert.ok(passed + failed > 0, 'No matching tests');
console.log(JSON.stringify({ passed, failed, realNetworkCalls: 0 }));
process.exitCode = failed ? 1 : 0;
