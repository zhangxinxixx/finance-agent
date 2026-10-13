import assert from 'node:assert/strict';
import { React, renderToStaticMarkup, loader, liveRaw, liveModel, overview, cases, hookRunner, deferred, tick } from './strategy-test-harness.mjs';

// Render the actual page and child components. Only data hooks and router
// context are mocked, so missing call-site qualification props stay observable.
function pageMarkup(data, view, request = {}, dailyOverrides = {}) {
  const daily = { data: overview(), isLoading: false, isError: false, error: null, selectedStrategyCardId: 'latest',
    isDetailLoading: false, detailError: null, isTraceLoading: false, traceError: null, assetOptions: [], selectStrategyCard() {}, refetch() {}, ...dailyOverrides };
  const react = { ...React, useState(initial) {
    if (initial === 'XAUUSD') return ['XAUUSD', () => {}];
    if (initial === 'current') return [view, () => {}];
    return React.useState(initial);
  } };
  const load = loader({ react,
    'react-router-dom': { useLocation: () => ({ state: null }) },
    '@/hooks/useLiveStrategy': { useLiveStrategy: () => ({ data, isLoading: false, error: null, refetch() {}, ...request }) },
    '@/hooks/useStrategy': { useStrategy: () => daily },
    '@/hooks/useStrategyPageState': { DEFAULT_STRATEGY_ASSET: 'XAUUSD', STRATEGY_WINDOW_TABS: [{ value: 'all', label: '全部' }], useStrategyPageState: () => ({
      selectedWindow: 'all', setSelectedWindow() {}, setSelectedRegime() {}, assetTabs: [], regimeTabs: [], activeRegime: 'all',
      selectedAssetSummary: null, visibleHistory: daily.data.history, selectedWindowLabel: '全部', selectedRegimeLabel: '全部',
    }) },
    '@/hooks/useShadowEvaluation': { useLatestShadowEvaluation: () => ({ data: null, isLoading: false, isUnavailable: true, error: null, refetch() {} }) },
    '@/hooks/useShadowEvaluationHistory': { useShadowEvaluationHistory: () => ({ data: null, isLoading: false, isUnavailable: true, error: null, refetch() {} }) },
  });
  return renderToStaticMarkup(React.createElement(load('@/pages/StrategyPage').StrategyPage));
}
const text = html => html.replace(/<[^>]*>/g, '');
const noActive = html => {
  assert.equal(/后端标记为当前场景|当前场景：<b>long/.test(html), false, 'unqualified scenarios cannot be marked as current');
  assert.equal(/live-strategy-active-plan/.test(html), false, 'unqualified current view cannot show an active plan');
};
const reasonOf = html => html.match(/aria-label="当前参考资格"[\s\S]*?<p>(.*?)<\/p>/)?.[1];

await cases([
  ['S1-T01', async () => {
    for (const status of ['accepted', 'held']) {
      const data = await liveModel(liveRaw(status));
      const current = pageMarkup(data, 'current'), daily = pageMarkup(data, 'daily');
      assert.match(current, /场景已经触发/); assert.match(current, /live-strategy-active-plan/);
      assert.match(daily, /后端标记为当前场景/); assert.match(daily, /当前场景：<b>long/);
      assert.doesNotMatch(current + daily, /当前：暂停参考/);
      assert.equal(data.strategy_status, 'TRIGGERED'); assert.equal(data.setups[0].status, 'triggered');
    }
  }],
  // Original P0 regression: copied with the harness to ec5dd0b7, this fails
  // because the real daily page passes dataBlocked=false for an invalid head.
  ['S1-T02', async () => {
    const data = await liveModel(liveRaw('invalid'));
    const daily = pageMarkup(data, 'daily');
    noActive(daily);
    for (const view of ['current', 'daily']) {
      const html = pageMarkup(data, view); noActive(html);
      assert.match(text(html), /当前：暂停参考/); assert.match(text(html), /黄金日结基线已失效，核验失败/);
      assert.match(text(html), /响应当时：已触发/);
    }
    assert.equal(data.strategy_status, 'TRIGGERED', 'display must not erase backend history');
  }],
  ['S1-T03', async () => {
    const missing = liveRaw(); delete missing.data_quality.gold_baseline;
    const noLineage = liveRaw(); noLineage.data_quality.gold_baseline.lineage_verified = false;
    const noDirection = liveRaw(); noDirection.data_quality.gold_baseline.direction = 'none';
    for (const raw of [missing, noLineage, noDirection]) {
      const data = await liveModel(raw);
      for (const view of ['current', 'daily']) {
        const html = pageMarkup(data, view); noActive(html);
        assert.match(text(html), /缺失或未核验，等待核验/); assert.doesNotMatch(text(html), /基线已失效/);
      }
    }
  }],
  ['S1-T04', async () => {
    const unavailable = liveRaw(); unavailable.live_market.status = 'unavailable';
    const noPrice = liveRaw(); unavailable.live_market.price = null; noPrice.live_market.price = null;
    const partial = liveRaw(); partial.status = 'partial';
    const noData = liveRaw(); noData.feasibility.data_ready = false;
    const conflict = liveRaw(); conflict.result_identity.relationship.status = 'different_result';
    const unknown = liveRaw(); unknown.result_identity.relationship.status = 'unverified';
    const noIdentity = liveRaw(); delete noIdentity.result_identity;
    for (const raw of [unavailable, noPrice, partial, noData, conflict, unknown, noIdentity]) {
      const data = await liveModel(raw);
      for (const view of ['current', 'daily']) {
        const html = pageMarkup(data, view); noActive(html); assert.match(text(html), /暂停参考/);
        assert.match(text(html), raw === conflict ? /结果身份不匹配/ : raw === unknown || raw === noIdentity ? /结果身份未核验/ : /行情数据不可用/);
      }
    }
  }],
  ['S1-T05', async () => {
    const data = await liveModel();
    for (const request of [{ isLoading: true }, { error: new Error('模拟刷新失败') }]) {
      for (const view of ['current', 'daily']) {
        const html = pageMarkup(data, view, request); noActive(html);
        assert.match(text(html), /上次成功结果供复盘/); assert.match(text(html), /响应当时：已触发/);
        assert.match(text(html), request.isLoading ? /正在刷新/ : /刷新失败/);
      }
    }
  }],
  ['S1-T06', async () => {
    for (const raw of [liveRaw('invalid'), { ...liveRaw(), result_identity: null }]) {
      const data = await liveModel(raw);
      const reasons = ['current', 'daily', 'current', 'daily'].map(view => reasonOf(pageMarkup(data, view)));
      assert.ok(reasons[0]); assert.equal(new Set(reasons).size, 1, 'views must project the same current qualification reason');
    }
  }],
  ['S1-T07', async () => {
    const requests = [];
    const runner = hookRunner('@/hooks/useLiveStrategy', 'useLiveStrategy', { '@/adapters/liveStrategy': { fetchLiveStrategy() {
      const d = deferred(); requests.push(d); return d.promise;
    } } });
    runner.render('XAUUSD'); runner.flush(); requests[0].resolve(await liveModel(liveRaw('invalid'))); await tick();
    let state = runner.flush(); noActive(pageMarkup(state.data, 'daily', state));
    state.refetch(); state = runner.flush(); noActive(pageMarkup(state.data, 'daily', state));
    assert.equal(state.isLoading, true);
    const next = liveRaw('held'); next.strategy_id = 'new-qualified'; next.setups[0].setup_id = 'new-setup'; next.setups[0].entry_zone = [321, 322];
    requests[1].resolve(await liveModel(next)); await tick(); state = runner.flush();
    const html = pageMarkup(state.data, 'daily', state); assert.match(html, /后端标记为当前场景/); assert.match(text(html), /321\.00/);
    assert.doesNotMatch(text(html), /100\.10|暂停参考/); runner.unmount();
  }],
  ['S1-T08', async () => {
    const data = await liveModel(liveRaw('invalid'));
    const history = pageMarkup(data, 'history'); assert.match(text(history), /总样本 3/);
    const evaluation = pageMarkup(data, 'evaluation'); assert.match(text(evaluation), /以下表现不能直接称为当前策略表现/);
    assert.doesNotMatch(evaluation, /live-strategy-active-plan|后端标记为当前场景/);
    for (const view of ['current', 'daily', 'history', 'evaluation', 'evidence']) {
      const html = pageMarkup(data, view);
      for (const label of ['当前策略', '日度研究', '策略历史', '表现评估', '数据证据']) assert.ok(html.includes(label));
    }
  }],
  ['S1-detail-state', async () => {
    const data = await liveModel();
    for (const overrides of [{ isDetailLoading: true }, { detailError: new Error('身份核验失败') }]) {
      const daily = pageMarkup(data, 'daily', {}, overrides), evidence = pageMarkup(data, 'evidence', {}, overrides);
      assert.doesNotMatch(daily, /模拟日度 latest/); assert.doesNotMatch(evidence, /结构化链路详情/);
      assert.match(text(daily), overrides.isDetailLoading ? /正在加载所选策略详情/ : /重试所选记录/);
    }
  }],
]);
