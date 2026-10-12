import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const src = path.resolve(new URL('../src', import.meta.url).pathname);
const source = fs.readFileSync(path.join(src, 'components/charts/TradingViewChart.tsx'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
function load(code, imports, globals = {}) {
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, URLSearchParams, ...globals, require: name => imports[name] ?? require(name) });
  return module.exports;
}
// Exercise the real component functions with isolated state, effect and timer lifecycles.
function lifecycle() {
  let state = [], effects = [];
  const instances = new Map(), timers = new Map();
  let cursor = 0, nextTimer = 0;
  const hooks = {
    useState(initial) { const id = cursor++; if (!(id in state)) state[id] = initial; return [state[id], value => state[id] = typeof value === 'function' ? value(state[id]) : value]; },
    useEffect(callback) { const id = cursor++; if (!effects[id]) effects[id] = { callback }; },
  };
  const components = load(compiled, { react: hooks }, { window: {
    setTimeout(callback, delay) { assert.equal(delay, 20_000); timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
  } });
  return {
    Chart: components.TradingViewChart, timers,
    render(Component, props = {}) {
      if (!instances.has(Component)) instances.set(Component, { state: [], effects: [] });
      ({ state, effects } = instances.get(Component));
      cursor = 0; return Component(props);
    },
    mount() { for (const effect of effects.filter(Boolean)) effect.cleanup = effect.callback(); },
    cleanup() { for (const effect of effects.filter(Boolean)) effect.cleanup?.(); },
    expire() { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(callback => callback()); },
  };
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...[tree.props?.children].flat(Infinity).flatMap(nodes)];
}
function find(tree, type) { return nodes(tree).find(node => node.type === type); }
function text(tree) { return [tree?.props?.children].flat(Infinity).filter(value => typeof value === 'string').join(''); }
const chart = lifecycle();
let tree = chart.render(chart.Chart);
const frameNode = nodes(tree).find(node => typeof node.type === 'function');
assert.equal(frameNode.key, '15m');
assert.equal(frameNode.props.period, '15m');
const frame = lifecycle();
// Functions close over their own module's hooks; use the frame type from this lifecycle.
const ownFrame = nodes(frame.render(frame.Chart)).find(node => typeof node.type === 'function').type;
let view = frame.render(ownFrame, { period: '15m', height: 400 });
frame.mount();
assert.equal(frame.timers.size, 1);
frame.cleanup(); frame.mount(); // React StrictMode effect setup -> cleanup -> setup.
assert.equal(frame.timers.size, 1, 'StrictMode must leave only one timeout');
assert.equal(nodes(view).filter(node => node.type === 'iframe').length, 1);
assert.match(text(find(view, 'p')), /正在加载/);
find(view, 'iframe').props.onLoad();
view = frame.render(ownFrame, { period: '15m', height: 400 });
assert.equal(find(view, 'p'), undefined, 'loaded frame must clear its loading hint without certifying price quality');
frame.expire();
view = frame.render(ownFrame, { period: '15m', height: 400 });
assert.doesNotMatch(text(find(view, 'p')), /超时/);
for (const [period, interval] of [['15m', '15'], ['1h', '60'], ['4h', '240']]) {
  const button = nodes(tree).find(node => node.type === 'button' && node.props.children === period);
  button.props.onClick(); tree = chart.render(chart.Chart);
  const selected = nodes(tree).find(node => typeof node.type === 'function');
  assert.equal(selected.key, period, 'period changes must replace the frame identity');
  assert.equal(nodes(tree).filter(node => typeof node.type === 'function').length, 1);
  const current = lifecycle();
  const Type = nodes(current.render(current.Chart)).find(node => typeof node.type === 'function').type;
  let currentView = current.render(Type, selected.props); current.mount();
  const url = new URL(find(currentView, 'iframe').props.src);
  assert.equal(url.origin, 'https://www.tradingview.com');
  assert.equal(url.pathname, '/widgetembed/');
  assert.equal(url.searchParams.get('symbol'), 'OANDA:XAUUSD');
  assert.equal(url.searchParams.get('interval'), interval);
  assert.equal(url.searchParams.get('theme'), 'light');
  const link = find(tree, 'a');
  assert.equal(new URL(link.props.href).origin, 'https://www.tradingview.com');
  assert.equal(new URL(link.props.href).searchParams.get('interval'), interval);
  assert.equal(link.props.target, '_blank');
  assert.equal(link.props.rel, 'noopener noreferrer');
  current.expire(); currentView = current.render(Type, selected.props);
  assert.match(text(find(currentView, 'p')), /加载较慢/);
  find(currentView, 'iframe').props.onLoad(); currentView = current.render(Type, selected.props);
  assert.equal(find(currentView, 'p'), undefined, 'late frame load clears the delay hint without creating a market-quality claim');
  current.cleanup(); assert.equal(current.timers.size, 0);
}
const failed = lifecycle();
const FailType = nodes(failed.render(failed.Chart)).find(node => typeof node.type === 'function').type;
let failedView = failed.render(FailType, { period: '15m', height: 350 }); failed.mount();
find(failedView, 'iframe').props.onError(); failedView = failed.render(FailType, { period: '15m', height: 350 });
assert.match(text(find(failedView, 'p')), /暂时无法加载/);
failed.cleanup(); assert.equal(failed.timers.size, 0, 'unmount must cancel the pending timeout');
const realChart = load(compiled, {}).TradingViewChart;
for (const file of ['components/gold-workspace/GoldPriceChart.tsx', 'components/market-monitor/MultiLineChart.tsx']) {
  const wrapperSource = fs.readFileSync(path.join(src, file), 'utf8');
  assert.doesNotMatch(wrapperSource, /useJin10Kline|useMarketCandleTimeframeAvailability|KLineChart|klineCoverage/);
  const code = ts.transpileModule(wrapperSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const wrapper = load(code, {
    '@/components/charts/TradingViewChart': { TradingViewChart: realChart },
    '@/components/shared/ChartReadingGuide': { ChartReadingGuide: () => null },
    './MultiLineChartLegend': { MultiLineChartLegend: () => React.createElement('div', {}, 'history legend') },
    './HistoryObservationPanel': { HistoryObservationPanel: () => React.createElement('div', {}, 'history indicators') },
  });
  const html = renderToStaticMarkup(React.createElement(wrapper.GoldPriceChart ?? wrapper.MultiLineChart, { metrics: [] }));
  assert.equal((html.match(/<iframe/g) ?? []).length, 1);
  assert.ok(html.includes('OANDA%3AXAUUSD'));
  assert.ok(html.includes('在 TradingView 新窗口查看'));
  if (wrapper.MultiLineChart) assert.ok(html.includes('history legend') && html.includes('history indicators'));
}
function scan(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) scan(file);
    else if (/\.(tsx?|mjs)$/.test(file)) {
      const content = fs.readFileSync(file, 'utf8');
      if (!file.endsWith('pageDataBoundary.mjs')) assert.doesNotMatch(content, /\/api\/market\/candles/, 'UI must not request local candles');
      if (file.endsWith('.tsx') && /<iframe\b[^>]*\bsrc=/.test(content)) assert.equal(file, path.join(src, 'components/charts/TradingViewChart.tsx'), 'external frame exception belongs only to the isolated chart');
    }
  }
}
scan(src);
assert.doesNotMatch(source, /\bfetch\s*\(|postMessage|addEventListener|<script/);
console.log('TradingView component checks passed: fixed origin/symbol, periods, lifecycle, timeout/error, links, both wrappers, no local candles requests. Browser reconciliation and external network remain Core acceptance.');
