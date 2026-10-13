import assert from 'node:assert/strict';
import { loader, hookRunner, deferred, tick, card, overview, trace, rawCard, rawTrace, cases } from './strategy-test-harness.mjs';

async function setup(traceEnabled = false) {
  const details = [], traces = [], overviews = [];
  const runner = hookRunner('@/hooks/useStrategy', 'useStrategy', { '@/adapters/strategy': {
    fetchStrategyCardsOverview(asset) { const d = deferred(); overviews.push({ asset, ...d }); return d.promise; },
    fetchStrategyAssetSummaries: async () => [],
    fetchStrategyCardById(id, asset, identity) { const d = deferred(); details.push({ id, asset, identity, ...d }); return d.promise; },
    fetchStrategySourceTraceByCardId(id, identity) { const d = deferred(); traces.push({ id, identity, ...d }); return d.promise; },
  } });
  let asset = 'XAUUSD', enabled = traceEnabled;
  runner.render(asset, enabled); runner.flush(); overviews[0].resolve(overview(asset)); await tick(); runner.flush();
  return {
    runner, details, traces, overviews,
    state: () => runner.render(asset, enabled),
    select(id) { runner.render(asset, enabled).selectStrategyCard(id); return runner.flush(); },
    render(nextAsset = asset, nextEnabled = enabled) { asset = nextAsset; enabled = nextEnabled; return runner.render(asset, enabled); },
    async settle() { await tick(); return runner.flush(); },
  };
}
const assertBody = (state, id, marker = id) => {
  assert.equal(state.selectedStrategyCardId, id);
  assert.equal(state.data.selected_strategy_card_id, id);
  assert.equal(state.data.hero.run_id, `run-${id}`);
  assert.equal(state.data.hero.snapshot_id, `snapshot-${id}`);
  assert.equal(state.data.scenario.main_scenario, `模拟日度 ${marker}`);
  assert.equal(state.data.sample_size, 3, 'detail must preserve history denominator');
  assert.equal(state.data.history.length, 3);
};

await cases([
  // Original P0 regression: the old hook accepts A after B and rewrites B's
  // body/ID. This case uses the same actual hook on old and repaired sources.
  ['S2-T01', async () => {
    const s = await setup(); s.select('A'); s.select('B');
    s.details[1].resolve(card('B')); let state = await s.settle();
    assert.equal(state.selectedStrategyCardId, 'B'); assert.equal(state.data.scenario.main_scenario, '模拟日度 B');
    s.render('XAUUSD', true); s.runner.flush(); const bTrace = s.traces.at(-1); assert.equal(bTrace.id, 'B');
    bTrace.resolve(trace('B')); await s.settle();
    s.details[0].resolve(card('A')); state = await s.settle(); assertBody(state, 'B');
    assert.equal(state.data.source_trace.target_id, 'B'); assert.equal(state.data.source_trace.source_refs[0].source_ref, '模拟依据-B');
    s.runner.unmount();
  }],
  ['S2-T02', async () => {
    const s = await setup(); s.select('A'); s.select('B'); s.details[1].resolve(card('B')); await s.settle();
    s.details[0].reject(new Error('过时 Alpha 失败')); const state = await s.settle(); assertBody(state, 'B');
    assert.equal(state.detailError, null); assert.equal(state.error, null); s.runner.unmount();
  }],
  ['S2-T03', async () => {
    const s = await setup(); s.select('A'); let state = s.select('B');
    assert.equal(state.data.scenario, null, 'new selection must immediately remove old body');
    assert.equal(state.data.hero.run_id, null); assert.equal(state.data.source_trace ?? null, null);
    s.details[0].resolve(card('A')); state = await s.settle();
    assert.equal(state.isDetailLoading, true, 'old finally cannot end Beta loading');
    assert.equal(state.data.scenario, null); assert.equal(state.selectedStrategyCardId, 'B');
    s.details[1].resolve(card('B')); assertBody(await s.settle(), 'B'); s.runner.unmount();
  }],
  ['S2-T04', async () => {
    const s = await setup(); s.select('A'); s.select('B'); s.select('A');
    s.details[2].resolve(card('A', 'XAUUSD', 'new Alpha')); await s.settle();
    s.details[0].resolve(card('A', 'XAUUSD', 'old Alpha')); s.details[1].reject(new Error('旧 Beta'));
    const state = await s.settle(); assertBody(state, 'A', 'new Alpha'); assert.equal(state.detailError, null); s.runner.unmount();
  }],
  ['S2-T05', async () => {
    const s = await setup(true); const oldTrace = s.traces[0]; s.select('A');
    assert.equal(s.render('DXY').data, null, 'asset change must mask old detail before effects'); s.runner.flush();
    s.overviews[1].resolve(overview('DXY')); await s.settle(); s.select('B'); s.details[1].resolve(card('B', 'DXY')); await s.settle();
    s.details[0].resolve(card('A')); oldTrace.reject(new Error('旧资产证据')); let state = await s.settle();
    assertBody(state, 'B'); assert.equal(state.data.asset, 'DXY'); assert.equal(state.traceError, null);
    s.render('XAUUSD'); s.runner.flush(); s.overviews[2].resolve(overview()); state = await s.settle();
    assert.equal(state.selectedStrategyCardId, 'latest'); assert.equal(state.data.asset, 'XAUUSD'); s.runner.unmount();
  }],
  ['S2-T06', async () => {
    const s = await setup(true); s.select('A'); s.state().refetch(); s.runner.flush(); s.runner.unmount();
    s.details[0].resolve(card('A')); s.traces[0].reject(new Error('离页旧依据')); s.overviews[1].resolve(overview()); await tick();
    assert.equal(s.runner.writesAfterUnmount, 0, 'success/error/finally must not write after unmount');
    const next = await setup(); assertBody(next.state(), 'latest'); next.runner.unmount();
  }],
  ['S2-T07', async () => {
    const s = await setup(); s.select('B'); s.details[0].resolve(card('A')); let state = await s.settle();
    assert.equal(state.data.scenario, null); assert.equal(state.selectedStrategyCardId, 'B'); assert.match(state.detailError.message, /身份核验失败/);
    s.select('B'); assert.equal(s.details.length, 2, 'failed selected item supports retry');
    s.details[1].resolve(card('B')); state = await s.settle(); assertBody(state, 'B'); assert.equal(state.detailError, null); s.runner.unmount();
  }],
  ['S2-T08', async () => {
    const s = await setup(true); s.traces[0].resolve(trace('latest')); await s.settle();
    s.select('B'); s.details[0].resolve(card('B')); await s.settle(); const bTrace = s.traces.at(-1); assert.equal(bTrace.id, 'B');
    bTrace.reject(new Error('Beta 依据失败')); const state = await s.settle(); assertBody(state, 'B');
    assert.match(state.traceError.message, /Beta/); assert.equal(state.data.source_trace, null); assert.equal(state.error, null);
    assert.equal(state.detailError, null); assert.equal(state.isTraceLoading, false); s.runner.unmount();
  }],
  ['S2-T09', async () => {
    // The mocked transport ignores cancellation entirely. No timers or abort
    // behavior can make this race pass; the request identity must do the work.
    const s = await setup(true); const latestTrace = s.traces[0];
    s.select('A'); s.details[0].resolve(card('A')); await s.settle(); const aTrace = s.traces.at(-1);
    s.select('B'); s.details[1].resolve(card('B')); await s.settle(); const bTrace = s.traces.at(-1);
    aTrace.reject(new Error('旧 Alpha 依据')); latestTrace.resolve(trace('latest')); let state = await s.settle();
    assertBody(state, 'B'); assert.equal(state.isTraceLoading, true, 'old trace finally cannot end Beta trace loading');
    assert.equal(state.traceError, null); assert.equal(state.data.source_trace, null);
    bTrace.resolve(trace('B')); state = await s.settle(); assert.equal(state.data.source_trace.target_id, 'B'); s.runner.unmount();
  }],
  ['S2-T10', async () => {
    const s = await setup(); s.select('A'); s.details[0].resolve(card('A')); await s.settle();
    s.state().refetch(); s.runner.flush(); const refreshed = overview(); refreshed.history = refreshed.history.slice(0, 2); refreshed.sample_size = 2;
    s.overviews[1].resolve(refreshed); let state = await s.settle();
    assert.equal(state.data.scenario.main_scenario, '模拟日度 A'); assert.equal(state.selectedStrategyCardId, 'A'); assert.equal(state.data.sample_size, 2);
    s.select('B'); s.details[1].resolve(card('B')); await s.settle(); s.select('A'); s.details[2].resolve(card('A', 'XAUUSD', 'reselected')); await s.settle();
    s.select('latest'); s.details[3].resolve(card('latest')); await s.settle();
    s.state().refetch(); s.runner.flush(); const newLatest = overview(); newLatest.scenario.main_scenario = '最新刷新'; s.overviews[2].resolve(newLatest);
    state = await s.settle(); assert.equal(state.data.scenario.main_scenario, '最新刷新'); assert.equal(state.selectedStrategyCardId, 'latest'); s.runner.unmount();
  }],
  ['S2-overview-in-flight', async () => {
    const s = await setup(); s.state().refetch(); s.runner.flush(); s.select('A');
    s.overviews[1].resolve(overview()); let state = await s.settle(); assert.equal(state.isDetailLoading, true); assert.equal(state.data.scenario, null);
    s.details[0].resolve(card('A')); assertBody(await s.settle(), 'A');
    s.select('latest'); s.state().refetch(); s.runner.flush(); s.overviews[2].resolve(overview()); state = await s.settle();
    assert.equal(state.isDetailLoading, true, 'overview cannot clear pending latest-selection loading'); assert.equal(state.data.scenario, null);
    s.details[1].reject(new Error('选中最新失败')); state = await s.settle(); assert.match(state.detailError.message, /失败/);
    s.state().refetch(); s.runner.flush(); s.overviews[3].resolve(overview()); state = await s.settle();
    assert.match(state.detailError.message, /失败/); assert.equal(state.data.scenario, null); s.runner.unmount();
  }],
  ['S2-trace-generation', async () => {
    const s = await setup(true); s.select('A'); s.details[0].resolve(card('A')); await s.settle(); const firstA = s.traces.at(-1);
    s.select('B'); s.details[1].resolve(card('B')); await s.settle(); const bTrace = s.traces.at(-1);
    s.select('A'); s.details[2].resolve(card('A', 'XAUUSD', 'new')); await s.settle(); const newA = s.traces.at(-1);
    newA.resolve({ ...trace('A'), source_refs: [{ source_ref: '新 Alpha 依据' }] }); await s.settle();
    firstA.resolve({ ...trace('A'), source_refs: [{ source_ref: '旧 Alpha 依据' }] }); bTrace.reject(new Error('旧 Beta 依据'));
    let state = await s.settle(); assertBody(state, 'A', 'new'); assert.equal(state.data.source_trace.source_refs[0].source_ref, '新 Alpha 依据');
    assert.equal(state.traceError, null);
    s.render('XAUUSD', false); state = s.runner.flush(); assert.equal(state.data.source_trace, null); assert.equal(state.isTraceLoading, false);
    s.render('XAUUSD', true); s.runner.flush(); s.traces.at(-1).resolve(trace('B')); state = await s.settle();
    assert.match(state.traceError.message, /身份核验失败/); assert.equal(state.data.source_trace, null); s.runner.unmount();
  }],
  ['S2-adapter-identity', async () => {
    const expected = { run_id: 'run-B', snapshot_id: 'snapshot-B' };
    async function fetchCard(raw) {
      return loader({ '@/adapters/apiClient': { fetchJson: async () => raw } })('@/adapters/strategy').fetchStrategyCardById('B', 'XAUUSD', expected);
    }
    for (const mutate of [raw => { raw.strategy_card_id = 'A'; }, raw => { raw.asset = 'DXY'; }, raw => { raw.hero.run_id = 'run-A'; },
      raw => { raw.hero.snapshot_id = 'snapshot-A'; }, raw => { raw.run_id = 'run-A'; }, raw => { raw.snapshot_id = 'snapshot-A'; }]) {
      const raw = rawCard('B'); mutate(raw); await assert.rejects(fetchCard(raw), /身份核验失败/);
    }
    const legacy = rawCard('B'); delete legacy.strategy_card_id; legacy.run_id = 'run-B'; legacy.snapshot_id = 'snapshot-B';
    const detail = await fetchCard(legacy); assert.equal(detail.selected_strategy_card_id, 'run-B', 'legacy fallback must remain distinct from explicit card ID');
    assert.equal(detail.hero.run_id, 'run-B'); assert.equal(detail.scenario.main_scenario, '模拟日度 B');
    const noIdentity = rawCard('B'); delete noIdentity.strategy_card_id; delete noIdentity.hero.run_id; delete noIdentity.hero.snapshot_id;
    await assert.rejects(fetchCard(noIdentity), /身份未核验/);
    const network = loader({ '@/adapters/apiClient': { fetchJson: async () => { throw new Error('503 模拟'); } } })('@/adapters/strategy');
    await assert.rejects(network.fetchStrategyCardById('B'), /503/);
    assert.equal((await network.fetchStrategyCardsOverview()).status, 'unavailable', 'overview still degrades independently');
    for (const field of ['run_id', 'snapshot_id', 'nested_run', 'nested_snapshot']) {
      const raw = rawTrace('B'); if (field === 'nested_run') raw.snapshot.run_id = 'run-A';
      else if (field === 'nested_snapshot') raw.snapshot.snapshot_id = 'snapshot-A'; else raw[field] = `wrong-${field}`;
      const adapter = loader({ '@/adapters/apiClient': { fetchJson: async () => raw } })('@/adapters/strategy');
      await assert.rejects(adapter.fetchStrategySourceTraceByCardId('B', expected), /身份核验失败/);
    }
    // Missing optional trace run/snapshot fields are not invented requirements.
    const optional = loader({ '@/adapters/apiClient': { fetchJson: async () => ({ data_status: 'partial', source_refs: [] }) } })('@/adapters/strategy');
    assert.equal((await optional.fetchStrategySourceTraceByCardId('B', expected)).status, 'partial');
  }],
  ['S2-null-and-legacy-detail', async () => {
    const s = await setup(); s.select('B'); s.details[0].resolve(null); let state = await s.settle();
    assert.match(state.detailError.message, /读取失败/); assert.equal(state.data.scenario, null);
    s.select('B'); const legacy = card('B'); legacy.selected_strategy_card_id = 'run-B'; s.details[1].resolve(legacy); state = await s.settle();
    assertBody(state, 'B'); assert.equal(state.detailError, null);
    s.select('A'); const heroOnly = card('A'); heroOnly.selected_strategy_card_id = null; s.details[2].resolve(heroOnly);
    assertBody(await s.settle(), 'A'); s.runner.unmount();
  }],
  ['S2-overview-failure', async () => {
    const s = await setup(); s.select('B'); s.details[0].resolve(card('B')); await s.settle();
    s.state().refetch(); s.runner.flush(); s.overviews[1].reject(new Error('模拟 overview 刷新失败'));
    assertBody(await s.settle(), 'B'); s.runner.unmount();
    const first = hookRunner('@/hooks/useStrategy', 'useStrategy', { '@/adapters/strategy': {
      fetchStrategyCardsOverview: async () => { throw new Error('模拟首次失败'); }, fetchStrategyAssetSummaries: async () => [],
    } });
    first.render('XAUUSD', false); first.flush(); await tick(); const state = first.flush();
    assert.equal(state.isLoading, false); assert.equal(state.isError, true); assert.equal(state.data, null); first.unmount();
  }],
  ['S2-disable-trace-before-effects', async () => {
    const s = await setup(true); const previous = s.traces[0]; s.render('XAUUSD', false);
    previous.reject(new Error('离开证据后的旧失败')); await tick();
    const state = s.state(); assert.equal(state.traceError, null, 'disabled evidence cannot acquire a stale error before effect cleanup');
    s.runner.flush(); s.runner.unmount();
  }],
]);
