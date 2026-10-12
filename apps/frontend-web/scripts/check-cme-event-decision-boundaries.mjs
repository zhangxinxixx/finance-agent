import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import ts from "typescript";

const source = (relativePath) => readFileSync(join(process.cwd(), relativePath), "utf8");

function loadTranspiledModule(relativePath, dependencies = {}) {
  const output = ts.transpileModule(source(relativePath), {
    fileName: relativePath,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, {
    module,
    exports: module.exports,
    require: (name) => {
      if (dependencies[name]) return dependencies[name];
      throw new Error(`Unexpected runtime dependency in ${relativePath}: ${name}`);
    },
    console,
    Error,
    Promise,
    Number,
    String,
    Set,
    Map,
  }, { filename: relativePath });
  return module.exports;
}

function mockResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; },
  };
}

const cmeIdentity = loadTranspiledModule("src/components/cme-options/cmeDecisionIdentity.ts");
const eventEvidence = loadTranspiledModule("src/components/event-flow/eventEvidenceFormat.ts");

assert.equal(
  cmeIdentity.resolveCMEDecisionIdentity(["snap-a"], ["snap-b"]).status,
  "mismatch",
  "same trade date with different CME snapshot IDs must stay isolated",
);
assert.equal(
  cmeIdentity.resolveCMEDecisionIdentity(["snap-a"], []).status,
  "unverified",
  "missing decision snapshot ID must not be treated as aligned",
);
assert.equal(
  cmeIdentity.resolveCMEDecisionIdentity(["snap-a"], ["snap-a"]).status,
  "aligned",
  "matching snapshot IDs may share a decision view",
);
assert.equal(
  cmeIdentity.resolveCMEDecisionIdentity(["snap-a"], ["snap-a", "snap-b"]).status,
  "mismatch",
  "a decision carrying any other known revision must stay isolated",
);
assert.equal(
  Array.from(cmeIdentity.collectCMESnapshotIds("snap-b", ["snap-a"], ["snap-a"])).join(","),
  "snap-b",
  "a primary CME snapshot ID must not union historical input/source IDs",
);
assert.equal(
  cmeIdentity.resolveCMEDecisionIdentity(
    cmeIdentity.collectCMESnapshotIds("snap-b", ["snap-a"], []),
    cmeIdentity.collectCMESnapshotIds(null, [], ["snap-a"]),
  ).status,
  "mismatch",
  "a decision referencing historical A must not align with current primary B",
);
assert.equal(cmeIdentity.collectCMESnapshotIds(null, ["snap-a"], ["snap-b"]).length, 0, "multiple non-primary source IDs are not a unique current identity");
assert.equal(
  cmeIdentity.selectCMEPinWall([
    { strike: 4400, wall_type: "Pin Wall", side: null, oi: 1, delta_oi: null, wall_score: 0.1, pnt: null },
    { strike: 4300, wall_type: "Active Wall", side: null, oi: 1, delta_oi: null, wall_score: 0.1, pnt: 0 },
  ]).strike,
  4300,
  "null PNT must not win pin selection when a real zero is available",
);
assert.equal(
  cmeIdentity.selectCMEPinWall([
    { strike: 4400, wall_type: "Pin Wall", side: null, oi: 1, delta_oi: null, wall_score: 0.1, pnt: null },
  ]),
  null,
  "no finite PNT must leave pin selection unavailable",
);
assert.equal(cmeIdentity.resolveCMEExpiryScope(["NOV26"], "DEC26").missing, true, "unknown expiry must be surfaced");
assert.equal(cmeIdentity.resolveCMETradeDateIdentity("2026-10-01", "2026-10-02", "2026-10-02").status, "mismatch", "selected CME date mismatch must stay isolated");
assert.equal(cmeIdentity.resolveCMETradeDateIdentity("2026-10-02", null, "2026-10-02").status, "unverified", "missing CME trade date must remain unverified");
assert.equal(cmeIdentity.resolveCMETradeDateIdentity("2026-10-02", "2026-10-02", "2026-10-02").status, "aligned", "matching CME trade dates may align");

const noWindow = { windows: {} };
assert.equal(eventEvidence.extractObservedEventWindowRows(noWindow).length, 0, "empty windows are not observed samples");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "partial", rawPricingStatus: "已定价", hasObservedWindows: false }), "未核验");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "partial", rawPricingStatus: "已定价", hasObservedWindows: true }), "部分定价");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "available", rawPricingStatus: "已定价", hasObservedWindows: true }), "已定价");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "available", rawPricingStatus: "priced", hasObservedWindows: true }), "已定价");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "validated", rawPricingStatus: "partially_priced", hasObservedWindows: true }), "部分定价");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "unknown", rawPricingStatus: "priced", hasObservedWindows: true }), "未核验", "unknown status must not consume formal priced");
assert.equal(eventEvidence.resolveEventPricingStatus({ status: "available", rawPricingStatus: "priced", hasObservedWindows: true, identity: "unverified" }), "未核验", "missing event ID must keep pricing conservative");
assert.equal(
  eventEvidence.extractObservedEventWindowRows({ windows: { "1h": { XAUUSD: { change_bp: 0, direction: "flat" }, DXY: {} } } }).length,
  1,
  "a real numeric zero is observed while an empty asset object is not",
);
const sevenWindows = { windows: Object.fromEntries(Array.from({ length: 7 }, (_, index) => [`${index + 1}h`, { XAUUSD: { change_bp: index } }])) };
assert.equal(eventEvidence.extractObservedEventWindowRows(sevenWindows).length, 7, "default evidence extraction must not hide additional windows");
assert.equal(eventEvidence.extractObservedEventWindowRows(sevenWindows, 6).length, 6, "an explicit display limit may be applied by a caller");
assert.equal(eventEvidence.resolveEventEvidenceIdentity("evt-a", "evt-b"), "mismatch", "event ID mismatch must be explicit");
assert.equal(eventEvidence.resolveEventEvidenceIdentity("evt-a", null), "unverified", "missing read-model event ID must be unverified");

let nextResponse = async () => mockResponse({});
const injectedFetchJson = async (path) => {
  const response = await nextResponse(path);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
};
class InjectedApiError extends Error {}
const cmeAdapter = loadTranspiledModule("src/adapters/cmeOptions.ts", {
  "@/adapters/apiClient": { ApiError: InjectedApiError, fetchJson: injectedFetchJson },
});

nextResponse = async () => mockResponse({
  trade_date: "2026-10-02",
  snapshot_id: "snap-a",
  data_source: { product: "OG", status: "FINAL", expiries: ["NOV26"], row_count: 2, report_date: "2026-10-03" },
  gex: { netgex_aggregate: { net_gex: 0, net_gex_direction: "neutral", gamma_zero: { price: null, method: "" } }, by_expiry: {} },
  wall_scores: [
    { strike: 4400, wall_type: "Pin Wall", pnt: null },
    { strike: 4300, wall_type: "Active Wall", pnt: 0 },
  ],
  support_resistance: { resistance: [], support: [] },
  intent: { type: "neutral", confidence: null, score: 0.72, evidence: [] },
  calibration: {},
  source_trace: [{ name: "CME", trade_date: "2026-10-02", snapshot_id: "snap-a", status: "ok" }],
  has_data: true,
});
const snapshot = await cmeAdapter.fetchCMEOptionsData("2026-10-02");
assert.equal(snapshot.wall_scores[0].pnt, null, "missing PNT must remain nullable through the adapter");
assert.equal(snapshot.wall_scores[1].pnt, 0, "real PNT zero must remain zero through the adapter");

nextResponse = async () => mockResponse({
  schema_version: "cme_options_decision.v1",
  status: "partial",
  meta: { current_trade_date: "2026-10-02", previous_trade_date: "2026-10-01", product: "OG", lookback_days: 1, comparison_status: "available" },
  source_refs: [{ name: "CME decision", trade_date: "2026-10-02", snapshot_id: "snap-a", status: "ok" }],
});
const decision = await cmeAdapter.fetchCMEOptionsDecision("2026-10-02");
assert.deepEqual(decision.source_refs.map((item) => item.snapshot_id), ["snap-a"], "decision source_refs snapshot ID must reach the view model");

console.log("CME/event decision boundary behavior OK: snapshot identity, nullable PNT, expiry scope, finite windows, partial pricing and event IDs.");
