// Offline fixtures and a minimal React hook scheduler. Product modules are
// transpiled unchanged; transport is always replaced before loading them.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
const require = createRequire(import.meta.url);
const ts = require('typescript');
export const React = require('react');
export const { renderToStaticMarkup } = require('react-dom/server');
export const src = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
export function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  function load(name, parent = src) {
    if (Object.hasOwn(mocks, name)) return mocks[name];
    if (name === '@/adapters/apiClient') throw new Error('Unmocked API client: network forbidden');
    if (name.endsWith('.css')) return {};
    if (!name.startsWith('@/') && !name.startsWith('.')) return require(name);
    const base = name.startsWith('@/') ? resolve(src, name.slice(2)) : resolve(parent, name);
    const file = [base + '.ts', base + '.tsx', ...(base.endsWith('.mjs') ? [base] : [])].find(existsSync);
    assert.ok(file, `Missing product module ${name}`);
    if (cache.has(file)) return cache.get(file).exports;
    const code = ts.transpileModule(readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})'), {
      fileName: file.replace(/\.mjs$/, '.ts'), compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
    }).outputText;
    const module = { exports: {} }; cache.set(file, module);
    vm.runInNewContext(code, { module, exports: module.exports, require: child => load(child, dirname(file)),
      console, Error, Date, Intl, URL, AbortController, setTimeout, clearTimeout,
      fetch() { throw new Error('Real network forbidden'); }, ...globals,
    }, { filename: file });
    return module.exports;
  }
  return load;
}
export function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
export async function tick() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
const sameDeps = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
export function hookRunner(file, name, mocks, globals = {}) {
  const slots = []; let cursor = 0, dirty = false, args = [], value, mounted = true, writesAfterUnmount = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [slots[i].value, next => {
        if (!mounted) { writesAfterUnmount++; return; }
        const result = typeof next === 'function' ? next(slots[i].value) : next;
        if (!Object.is(slots[i].value, result)) { slots[i].value = result; dirty = true; }
      }];
    },
    useRef(initial) { const i = cursor++; return (slots[i] ??= { current: initial }); },
    useEffect(effect, deps) {
      const i = cursor++, old = slots[i];
      if (!sameDeps(old?.deps, deps)) slots[i] = { deps, effect, cleanup: old?.cleanup, pending: true };
    },
    useCallback(fn, deps) { const i = cursor++; if (!sameDeps(slots[i]?.deps, deps)) slots[i] = { deps, fn }; return slots[i].fn; },
    useMemo(fn, deps) { const i = cursor++; if (!sameDeps(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() }; return slots[i].value; },
  };
  const load = loader({ ...mocks, react }, { window: { setInterval: () => 1, clearInterval() {} }, ...globals });
  const hook = load(file)[name];
  const render = (...nextArgs) => { args = nextArgs; cursor = 0; dirty = false; value = hook(...args); return value; };
  return {
    render,
    flush() {
      for (let turn = 0; turn < 50; turn++) {
        if (dirty) render(...args);
        const pending = slots.filter(slot => slot?.pending);
        if (!pending.length && !dirty) return value;
        for (const slot of pending) slot.cleanup?.();
        for (const slot of pending) { slot.pending = false; slot.cleanup = slot.effect(); }
      }
      throw new Error('Hook effects did not settle');
    },
    unmount() { mounted = false; for (const slot of slots) slot?.cleanup?.(); },
    get writesAfterUnmount() { return writesAfterUnmount; },
  };
}
export function rawCard(id = 'latest', asset = 'XAUUSD', marker = id) {
  return { asset, status: 'available', trade_date: '2026-10-13', strategy_card_id: id, updated_at: '2026-10-13T04:00:00Z', has_data: true,
    hero: { status: 'available', direction: 'bullish', bias: `模拟日度 ${marker}`, confidence: null, market_regime: 'range',
      trade_date: '2026-10-13', run_id: `run-${id}`, snapshot_id: `snapshot-${id}`, source_refs: [] },
    scenario: { main_scenario: `模拟日度 ${marker}`, trigger_conditions: ['模拟触发条件'], invalidation_conditions: ['模拟失效条件'],
      confirmation_conditions: [], risk_points: ['隔离样本，无交易含义'], key_levels: { support: [], resistance: [] } },
    module_signals: [], playbook_matches: [], source_refs: [], artifact_refs: [] };
}
const modelLoad = loader();
export const { mapStrategyResponse, mapHistoryItem } = modelLoad('@/types/strategy');
export function card(id = 'latest', asset = 'XAUUSD', marker = id) { return mapStrategyResponse(rawCard(id, asset, marker), 'api', asset); }
export function overview(asset = 'XAUUSD') {
  const history = ['latest', 'A', 'B'].map(id => mapHistoryItem({ strategy_card_id: id, asset, trade_date: '2026-10-13',
    run_id: `run-${id}`, snapshot_id: `snapshot-${id}`, bias: `模拟日度 ${id}`, source_refs: [], artifact_refs: [] }));
  return { ...card('latest', asset), history, sample_size: history.length };
}
export function rawTrace(id) {
  return { run_id: `run-${id}`, snapshot_id: `snapshot-${id}`, data_status: 'available', source_refs: [], artifact_refs: [],
    snapshot: { snapshot_id: `snapshot-${id}`, run_id: `run-${id}`, data_status: 'available' }, input_snapshots: [], related_artifacts: [] };
}
export function trace(id) {
  return { target_type: 'strategy', target_id: id, status: 'available', run_id: `run-${id}`, snapshot_id: `snapshot-${id}`,
    source_refs: [{ source_ref: `模拟依据-${id}`, label: `模拟依据-${id}` }], artifact_refs: [], input_snapshots: [], related_artifacts: [] };
}
export function liveRaw(status = 'accepted') {
  const invalid = status === 'invalid', held = status === 'held';
  return { schema_version: 'live_strategy.v1', status: 'available', asset: 'XAUUSD', strategy_id: 'synthetic-live',
    baseline_strategy_id: 'latest', strategy_version: 'test-v1', strategy_status: 'TRIGGERED', updated_at: '2026-10-13T04:00:00Z',
    update_reason: { reason_code: 'test_fixture', message: '隔离模拟，非市场事实' }, baseline: { strategy_card_id: 'latest', version: 'test-v1', bias: 'bullish' },
    live_market: { status: 'available', price: 100, timestamps: { canonical: '2026-10-13T04:00:00Z' }, freshness_seconds: 0 },
    market_state: { key_levels: [], confirmation_15m: { confirmed: true, close: 100 } }, cme_positioning: { status: 'unavailable' },
    active_scenario: 'long', setups: [{ direction: 'long', status: 'triggered', setup_id: 'synthetic-setup', entry_zone: [100, 100.1],
      stop_reference: 99, invalidation_level: 99, trigger_conditions: ['模拟触发条件'], confirmation_conditions: ['模拟确认条件'],
      targets: [], risk_reward: {}, gate: { passed: true, reasons: [] } }], no_trade: { range: null, reasons: ['模拟观察原因'], waiting_conditions: ['模拟等待条件'] },
    feasibility: { data_ready: true, level_ready: true, trigger_ready: true, risk_ready: true, rr_ready: true, execution_ready: true, reasons: {} },
    data_quality: { warnings: ['隔离模拟，非市场事实'], gold_baseline: { status, direction: invalid ? 'none' : 'long',
      authority_ready: !invalid, lineage_verified: !invalid, gold_head_held: held } }, source_refs: [], artifact_refs: [],
    result_identity: { schema_version: 'gold_result_identity.v1', subject: { kind: 'gold_daily_close', run_id: 'synthetic-run', result_id: 'synthetic-result', verification_status: 'verified' },
      effective_baseline: { kind: 'gold_daily_close', run_id: 'synthetic-run', result_id: 'synthetic-result', verification_status: invalid ? 'invalid' : 'verified',
        status, held, authority_ready: !invalid }, relationship: { status: invalid ? 'unverified' : 'same_effective_head' } } };
}
export async function liveModel(raw = liveRaw()) {
  const { fetchLiveStrategy } = loader({ '@/adapters/apiClient': { fetchJson: async () => structuredClone(raw) } })('@/adapters/liveStrategy');
  return fetchLiveStrategy();
}
export async function cases(entries) {
  const filter = process.argv.find(arg => arg.startsWith('--case='))?.slice(7);
  let passed = 0;
  for (const [id, test] of entries) {
    if (filter && id !== filter) continue;
    await test(); passed++; console.log(`${id}: PASS`);
  }
  assert.ok(passed, `No case matched ${filter}`);
  console.log(`${passed} strategy behavior cases passed; real network calls = 0`);
}
