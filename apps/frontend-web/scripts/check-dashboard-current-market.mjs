import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { posix } from "node:path";
import ts from "typescript";

const cache = new Map();
function load(name) {
  if (cache.has(name)) return cache.get(name);
  if (name === "@/adapters/apiClient") return { fetchJson: () => { throw new Error("Unexpected network request"); } };
  const path = fileURLToPath(new URL(`../src/${name.slice(2)}.ts`, import.meta.url));
  const source = readFileSync(path, "utf8").replaceAll("import.meta.env", "({})");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const requireModule = (dependency) => load(dependency.startsWith(".")
    ? posix.join(posix.dirname(name), dependency) : dependency);
  vm.runInNewContext(code, { exports, require: requireModule, console, setTimeout, clearTimeout });
  cache.set(name, exports);
  return exports;
}

const { normalizeDashboardWithCurrentMarket: normalize } = load("@/adapters/api");
const frozen = {
  generated_at: "2026-09-28T15:00:00Z",
  macro: { indicators: { REAL_10Y: { value: 2.68, date: "2026-09-16" } } },
  options: { trade_date: "2026-09-17", walls: { support: [{ strike: 4000 }] } },
  integrated_macro: { source: "registered_research_snapshot", reasoning: "Frozen research", publish_allowed: false },
};
const current = {
  macro: { indicators: { REAL_10Y: { value: 2.85, date: "2026-09-24" } } },
  options: { trade_date: "2026-09-25", walls: { support: [{ strike: 4100 }] } },
  realtime_quotes: { xauusd: { price: 4125, source: "twelvedata", time: "2026-09-28T15:00:00Z" } },
};
for (const raw of [frozen, { ...frozen, macro: null, options: null, integrated_macro: {
  source: "unavailable", reasoning: "Research verification failed", publish_allowed: false,
} }]) {
  const before = normalize(raw);
  const result = normalize({ ...raw, current_market: current });
  assert.equal(result.market_summary.REAL_10Y.value, 2.85);
  assert.equal(result.market_summary.REAL_10Y.data_date, "2026-09-24");
  assert.equal(result.market_summary.XAUUSD.value, 4125);
  assert.equal(result.market_summary.XAUUSD.instrument_kind, "spot");
  assert.equal(result.cme_options.trade_date, "2026-09-25");
  for (const key of ["strategy", "conclusion", "integrated_macro", "composite_analysis"]) {
    assert.deepEqual(result[key], before[key], `${key} must retain frozen research semantics`);
  }
}
assert.equal(normalize(frozen).market_summary.REAL_10Y.value, 2.68, "Legacy responses remain supported");
assert.equal(normalize({ ...frozen, current_market: { macro: null, options: null, realtime_quotes: {} } }).market_summary.REAL_10Y.value, null,
  "Missing current facts must not silently fall back to historical research");
console.log("Dashboard current market behavior OK");

const aliases = {
  REAL10Y: { value: 2.91, date: "2026-10-06", source: "Treasury", unit: "%", daily_change: -0.04 },
  BREAKEVEN_10Y: { value: 2.36, date: "2026-10-06", source: "FRED", unit: "%" },
};
const aliased = normalize({ macro: { indicators: aliases } });
assert.equal(aliased.market_summary.REAL_10Y.value, 2.91);
assert.equal(aliased.market_summary.REAL_10Y.data_date, "2026-10-06");
assert.equal(aliased.market_summary.REAL_10Y.source, "Treasury");
assert.equal(aliased.market_summary.T10YIE.value, 2.36);
for (const canonical of [null, { value: null, date: "2026-10-07" }, { value: 2.5, date: "2026-10-05" }]) {
  const result = normalize({ macro: { indicators: { ...aliases, REAL_10Y: canonical, T10YIE: canonical } } });
  assert.equal(result.market_summary.REAL_10Y.value, canonical?.value ?? null);
  assert.equal(result.market_summary.T10YIE.value, canonical?.value ?? null);
}
assert.equal(normalize({ ...frozen, current_market: { macro: { indicators: aliases } } }).market_summary.REAL_10Y.value, 2.91);
assert.equal(aliases.REAL10Y.value, 2.91, "Read-only aliases preserve source input");
const sourced = normalize({ macro: { indicators: { US02Y: { value: 4.79, date: "2026-10-06" } }, source_refs: [
  { symbol: "DGS2", source: "treasury_rates", observation_date: "2026-10-05" },
  { symbol: "DGS2", source: "treasury_rates", observation_date: "2026-10-06" },
] } });
assert.equal(sourced.market_summary.US02Y.source, "treasury_rates");
assert.equal(normalize({ macro: { indicators: { US02Y: { value: 4.79, date: "2026-10-06" } },
  source_refs: [{ symbol: "DGS2", source: "treasury_rates", observation_date: "2026-10-05" }] } }).market_summary.US02Y.source, null);

const { getWallStrength } = load("@/components/dashboard/CMEOptionsSummaryFormat");
assert.equal(getWallStrength(.12).label, "墙位强度 0.12");
assert.equal(getWallStrength(.69).color, getWallStrength(.12).color);
assert.equal(normalize({ options: { wall_score: .69, walls: { support: [{ strike: 4100, score: .12 }] } } }).cme_options.wall_score, .69);
assert.equal(normalize({ options: { walls: { support: [{ strike: 4100, score: .12 }] } } }).cme_options.wall_score, null);
