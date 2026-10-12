import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import * as jsxRuntime from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';

function load(file, dependencies = {}, globals = {}) {
  const source = readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, { module, exports: module.exports, require(name) {
    if (name === 'react/jsx-runtime') return jsxRuntime;
    if (name in dependencies) return dependencies[name];
    throw new Error(`Unexpected dependency ${name}`);
  }, Headers, AbortController, Error, setTimeout, clearTimeout, ...globals });
  return module.exports;
}
const normalizer = load('src/adapters/researchIdentity.ts');
const identity = normalizer.normalizeResearchIdentity({ schema_version: 'research_identity.v1', report_id: 'r-1', run_id: 'run-1', snapshot_id: 's-1', trade_date: '2020-01-01', research_version: 'revision-7', generated_at: '2030-01-01', data_as_of: null,
  key_level_validity: { status: 'active', data_as_of: null, valid_until: null, reason_codes: ['backend_verified'] } });
assert.equal(identity.data_as_of, null, 'generation time cannot fill research data time');
assert.equal(identity.key_level_validity.status, 'active', 'old dates cannot override backend validity');
assert.equal(normalizer.normalizeResearchIdentity({ schema_version: 'future' }), null);
assert.equal(normalizer.normalizeResearchIdentity({ schema_version: 'research_identity.v1', key_level_validity: { status: 'future' } }).key_level_validity.status, 'unavailable');
const component = load('src/components/shared/ResearchIdentity.tsx', { '@/components/dashboard/DashboardResearchBriefModel': load('src/components/dashboard/DashboardResearchBriefModel.ts'), './ResearchDetails': { ResearchDetails: ({ children }) => React.createElement('details', null, children) } }).ResearchIdentity;
// Render the real shared component, preserving explicit unknown timing.
const rendered = renderToStaticMarkup(React.createElement(component, { identity }));
assert.match(rendered, /revision-7/);
assert.match(rendered, /研究数据时点：未知/);
assert.match(rendered, /点位状态：有效/);
assert.match(renderToStaticMarkup(React.createElement(component)), /点位状态：未知/);
let calls = 0;
const boundaryDependency = { '@/adapters/pageDataBoundary.mjs': { assertPageRequestAllowed() {} } };
const client = load('src/adapters/apiClient.ts', boundaryDependency, { fetch: async () => { calls++; return new Response('{"ok":true}', { status: 200 }); } });
assert.equal((await client.fetchJson('/success')).ok, true);
const aborted = new AbortController(); aborted.abort();
await assert.rejects(client.fetchJson('/aborted', { signal: aborted.signal }), /已取消/);
assert.equal(calls, 1, 'already cancelled requests must not reach transport');
const hanging = load('src/adapters/apiClient.ts', boundaryDependency, { fetch: () => new Promise(() => {}) });
await assert.rejects(hanging.fetchJson('/slow', undefined, 5), /超时/);
const bodyHanging = load('src/adapters/apiClient.ts', boundaryDependency, { fetch: async () => ({ ok: true, clone() { return this; }, json: () => new Promise(() => {}) }) });
await assert.rejects(bodyHanging.fetchJson('/slow-body', undefined, 5), /超时/);
const failed = load('src/adapters/apiClient.ts', boundaryDependency, { fetch: async () => new Response('unavailable', { status: 503 }) });
await assert.rejects(failed.fetchJson('/failed'), error => error instanceof failed.ApiError && error.status === 503 && error.responseBody === 'unavailable');

function runner(file, name, dependency, fetcher, globals = {}) {
  const slots = [], effects = []; let cursor = 0, effectCursor = 0;
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ??= { current: initial }; },
    useEffect(effect, deps) { const index = effectCursor++; const old = effects[index]; if (!old || deps.some((value, i) => old.deps[i] !== value)) { effects[index] = { effect, deps, cleanup: old?.cleanup, dirty: true }; } },
  };
  const hook = load(file, { react, [dependency]: fetcher }, globals)[name];
  return { render(...args) { cursor = 0; effectCursor = 0; return hook(...args); }, flush() { for (const slot of effects) if (slot.dirty) { slot.cleanup?.(); slot.cleanup = slot.effect(); slot.dirty = false; } }, unmount() { for (const slot of effects) slot.cleanup?.(); } };
}
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const requests = [];
const report = runner('src/hooks/useReportDetail.ts', 'useReportDetail', '@/adapters/reports', { fetchReportDetailView(id) { const pending = deferred(); requests.push({ id, ...pending }); return pending.promise; } });
report.render('old'); report.flush();
assert.equal(report.render('new').data, null); report.flush();
requests[1].resolve({ report_id: 'new' }); await tick();
requests[0].resolve({ report_id: 'old' }); await tick();
let view = report.render('new'); assert.equal(view.data.report_id, 'new', 'late old request cannot overwrite selected report');
view.refetch(); view.refetch(); report.render('new'); report.flush();
assert.equal(requests.length, 3, 'synchronous duplicate clicks launch one refresh');
requests[2].reject(new Error('503')); await tick();
view = report.render('new'); assert.equal(view.data.report_id, 'new'); assert.match(view.error.message, /503/);
view.refetch(); report.render('new'); report.flush(); assert.equal(requests.length, 4, 'failure releases refresh lock');
report.unmount(); requests[3].resolve({ report_id: 'late' }); await tick();
console.log('Research identity and request behavior OK: backend validity, unknown timing, SSR, timeout/body timeout, cancellation, HTTP errors, route race and repeated refresh.');

const dashboardRequests = [];
const dashboard = runner('src/hooks/useDashboard.ts', 'useDashboard', '@/adapters/api', { fetchDashboardData(date) { const pending = deferred(); dashboardRequests.push({ date, ...pending }); return pending.promise; } }, {
  window: { setInterval: () => 1, clearInterval() {}, addEventListener() {}, removeEventListener() {} },
  document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
});
dashboard.render('date-a'); dashboard.flush();
dashboardRequests[0].resolve({ marker: 'a' }); await tick();
assert.equal(dashboard.render('date-a').data.marker, 'a');
assert.equal(dashboard.render('date-b').data, null, 'a new date cannot render the prior research before effect flush'); dashboard.flush();
dashboardRequests[1].resolve({ marker: 'b' }); await tick();
let dashboardView = dashboard.render('date-b'); assert.equal(dashboardView.data.marker, 'b');
dashboardView.refetch(); dashboardView.refetch(); dashboard.render('date-b'); dashboard.flush();
assert.equal(dashboardRequests.length, 3, 'Dashboard repeated clicks coalesce');
dashboard.render('date-c'); dashboard.flush();
dashboardRequests[3].resolve({ marker: 'c' }); await tick(); dashboardRequests[2].resolve({ marker: 'old-b' }); await tick();
assert.equal(dashboard.render('date-c').data.marker, 'c', 'late Dashboard response cannot overwrite newer research');
dashboard.unmount();
console.log('Dashboard hook behavior OK: date isolation, repeated refresh and late response suppression.');
