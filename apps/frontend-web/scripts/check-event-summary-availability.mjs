import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { createServer } from 'vite';
const server = await createServer({ configFile: false, root: resolve('.'), cacheDir: '/tmp/finance-agent-event-summary-validation', optimizeDeps: { noDiscovery: true, include: [] }, resolve: { alias: { '@': resolve('src') } }, server: { middlewareMode: true }, appType: 'custom' });
const originalFetch = globalThis.fetch;
let summary;
globalThis.fetch = async (url) => {
  assert.equal(String(url), '/api/events/flow/overview', 'isolated test must not call another endpoint');
  return new Response(JSON.stringify({ status: 'available', source: 'isolated_test', events: [], event_impact_summary: summary }), { status: 200, headers: { 'content-type': 'application/json' } });
};
try {
  const { fetchEventFlowOverviewView } = await server.ssrLoadModule('/src/adapters/eventFlow.ts');
  for (const confidence of [undefined, null, NaN, Infinity, '0.9']) {
    summary = { summary: '已有说明', confidence };
    const result = await fetchEventFlowOverviewView();
    assert.equal(result.event_impact_summary.confidence, null, 'missing or invalid confidence is not zero or an invented number');
    assert.equal(result.event_impact_summary.bias, 'unknown', 'missing direction is not neutral');
  }
  for (const confidence of [0, 0.8]) {
    summary = { summary: '已有说明', bias: 'bullish', confidence };
    const result = await fetchEventFlowOverviewView();
    assert.equal(result.event_impact_summary.confidence, confidence, 'real zero and provided model value remain intact');
    assert.equal(result.event_impact_summary.bias, 'bullish');
  }
  console.log('Event summary availability: actual adapter preserves missing confidence/direction and genuine zero; no external calls.');
} finally { globalThis.fetch = originalFetch; await server.close(); }
