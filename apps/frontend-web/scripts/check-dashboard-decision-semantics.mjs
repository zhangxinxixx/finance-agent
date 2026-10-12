import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const modules = new Map();
let response = {};
function load(file) {
  if (file === '@/adapters/apiClient') return { fetchJson: async () => response };
  if (modules.has(file)) return modules.get(file);
  const source = fs.readFileSync(file, 'utf8').replace(/import\.meta\.env\.VITE_ENABLE_DASHBOARD_MOCK_FALLBACK/g, 'undefined');
  const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const module = { exports: {} };
  modules.set(file, module.exports);
  vm.runInNewContext(output, {
    module, exports: module.exports, console, URL, Map, Set, Error, Promise,
    window: { setTimeout, clearTimeout },
    require(name) {
      if (name === '@/adapters/apiClient') return load(name);
      const target = name.startsWith('@/') ? path.join(root, name.slice(2)) : path.resolve(path.dirname(file), name);
      return load(target + '.ts');
    },
  }, { filename: file });
  return module.exports;
}
const adapter = load(path.join(root, 'adapters/api.ts'));
const model = load(path.join(root, 'components/dashboard/DashboardIntegratedMacroModel.ts'));
const missing = adapter.normalizeDashboardWithCurrentMarket({ warnings: ['源缺失'], risk_alerts: ['风险已登记'] });
assert.equal(missing.strategy.confidence, null);
assert.equal(missing.cme_options.intent_score, null);
assert.equal(missing.cme_options.confidence.score, null);
assert.equal(missing.strategy.triggers.length, 0, 'warnings are not trigger conditions');
assert.equal(missing.strategy.invalid_conditions.length, 0, 'risk notes are not invalidation rules');
assert.equal(model.dashboardResearchAsOf(missing, { generated_at: '2026-10-04T00:00:00Z', trade_date: '2026-10-04' }), null, 'UI read time is not analysis time');
assert.equal(model.dashboardResearchDate(missing, { trade_date: '2026-10-04' }), '未提供', 'unbound selected date is not research identity');

response = { options: { intent_score: 82, intent: 'bullish' }, strategy: {}, integrated_macro: { trade_date: '2026-09-28', as_of: '2026-09-28T20:00:00Z' } };
const result = await adapter.fetchDashboardData();
assert.equal(result.view_model.cme_summary.confidence, null, 'intent score must not become confidence');
assert.equal(model.buildOptionsEvidenceSummary(result.summary).confidencePct, '未量化');
assert.equal(model.dashboardResearchAsOf(result.summary), '2026-09-28T20:00:00Z');
assert.equal(model.dashboardResearchDate(result.summary), '2026-09-28');

const scoring = adapter.normalizeDashboardWithCurrentMarket({ options: { intent_score: 82, confidence: { score: 0.13, is_probability: false } } });
assert.match(model.buildOptionsEvidenceSummary(scoring).confidencePct, /13\/100/);
assert.doesNotMatch(model.buildOptionsEvidenceSummary(scoring).confidencePct, /13%/);
const invalid = adapter.normalizeDashboardWithCurrentMarket({ options: { intent_score: Infinity }, strategy: { confidence: NaN }, integrated_macro: { confidence: Infinity } });
assert.equal(invalid.strategy.confidence, null);
assert.equal(invalid.integrated_macro.confidence, null);
assert.equal(invalid.cme_options.intent_score, null);
console.log('Dashboard decision semantics OK: missing values, scoring, conditions and research identity');
