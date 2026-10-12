import assert from "node:assert/strict";

const {
  getDashboardStrategyPresentation,
  getDisplayLiveStrategyStatus,
} = await import("../src/components/strategy/liveStrategyTrust.ts");
const {
  buildDashboardStrategyNavigationState,
  compareStrategySourceIdentity,
  readStrategyNavigationState,
} = await import("../src/components/strategy/strategyNavigation.ts");

function liveResponse(overrides = {}) {
  return {
    status: "available",
    strategy_status: "TRIGGERED",
    feasibility: {
      data_ready: true,
      execution_ready: true,
    },
    live_market: {
      status: "available",
      price: 4000,
    },
    ...overrides,
  };
}

const currentData = liveResponse();
const current = getDashboardStrategyPresentation({
  data: currentData,
  trustState: "current",
  goldBaselineVerified: true,
});
assert.equal(current.ready, true, "a verified available result may be ready on the dashboard");
assert.equal(current.dataGateBlocked, false);
assert.equal(current.displayStatus, "TRIGGERED");

for (const [label, data] of [
  ["partial response", liveResponse({ status: "partial" })],
  ["data_ready=false", liveResponse({ feasibility: { data_ready: false, execution_ready: true } })],
  ["unavailable market", liveResponse({ live_market: { status: "unavailable", price: 4000 } })],
  ["null price", liveResponse({ live_market: { status: "available", price: null } })],
  ["NaN price", liveResponse({ live_market: { status: "available", price: Number.NaN } })],
]) {
  const result = getDashboardStrategyPresentation({ data, trustState: "current", goldBaselineVerified: true });
  assert.equal(result.ready, false, `${label} must not show dashboard execution ready`);
  assert.equal(result.dataGateBlocked, true, `${label} must block the dashboard data gate`);
  assert.equal(result.displayStatus, "SUSPENDED_DATA", `${label} must not expose TRIGGERED`);
}

for (const trustState of ["refreshing", "unavailable"]) {
  const result = getDashboardStrategyPresentation({ data: currentData, trustState, goldBaselineVerified: true });
  assert.equal(result.ready, false, `${trustState} must not show a stale dashboard result as ready`);
  assert.equal(result.displayStatus, "SUSPENDED_DATA");
}

const original = JSON.parse(JSON.stringify(currentData));
getDashboardStrategyPresentation({ data: currentData, trustState: "current", goldBaselineVerified: true });
assert.deepEqual(currentData, original, "dashboard presentation gate must not mutate backend data");
assert.equal(
  getDisplayLiveStrategyStatus({
    status: "TRIGGERED",
    availability: "available",
    dataReady: true,
    market: { status: "unavailable", price: null },
    trustState: "current",
    goldBaselineVerified: true,
  }),
  "SUSPENDED_DATA",
);

const summary = {
  generated_at: "2026-10-04T15:50:43.356961+00:00",
  integrated_macro: {
    report_type: "research_observation_summary",
    trade_date: "2026-09-29",
    run_id: "research-run-1",
    source: "research",
    as_of: "2026-09-29T03:27:20.289466+00:00",
    authority: "observation_only",
    publish_allowed: false,
    source_refs: [{ source_ref: "observation:research-run-1", snapshot_id: null }],
  },
  latest_reports: [{ report_id: "observation-report-1", trade_date: "2026-09-29", run_id: "research-run-1" }],
  source_trace: [{ source_ref: "dashboard-summary", snapshot_id: "dashboard-snapshot-1" }],
  strategy: { run_id: null },
};
const identity = {
  schema_version: "gold_result_identity.v1",
  subject: {
    kind: "gold_policy_daily_report",
    run_id: "strategy-run-1",
    result_id: "strategy-result-1",
  },
  effective_baseline: null,
  relationship: { status: "same_effective_head", reason_code: null },
};
const navigation = buildDashboardStrategyNavigationState({
  summary,
  viewModel: {
    strategy_card: { trade_date: "2026-09-06", run_id: "strategy-run-0906", snapshot_id: "strategy-snapshot-0906" },
  },
  dashboardResult: { summary, view_model: null },
  resultIdentity: identity,
  returnTo: "/dashboard/analysis",
});
assert.equal(navigation.strategySource.tradeDate, "2026-09-29");
assert.equal(navigation.strategySource.runId, "research-run-1");
assert.equal(navigation.strategySource.snapshotId, null, "a StrategyCard snapshot must not be borrowed as the research source snapshot");
assert.equal(navigation.strategySource.reportId, "observation-report-1");
assert.equal(navigation.strategySource.publishAllowed, false);
assert.equal(navigation.strategySource.returnTo, "/dashboard/analysis");
assert.equal(navigation.strategySource.sourceResultIdentity, null, "the target live identity must not be copied into the homepage source");
const explicitSnapshotNavigation = buildDashboardStrategyNavigationState({
  summary: {
    ...summary,
    integrated_macro: {
      ...summary.integrated_macro,
      source_refs: [{ source_ref: "observation:research-run-1", snapshot_id: "research-snapshot-1" }],
    },
  },
});
assert.equal(explicitSnapshotNavigation.strategySource.snapshotId, "research-snapshot-1");
assert.equal(compareStrategySourceIdentity(navigation.strategySource, identity).label, "无法核验", "a date/run-only homepage source cannot be treated as the current strategy identity");
const explicitSourceIdentity = { ...navigation.strategySource, sourceResultIdentity: identity };
assert.equal(compareStrategySourceIdentity(explicitSourceIdentity, identity).label, "身份一致");
assert.equal(
  compareStrategySourceIdentity(explicitSourceIdentity, { ...identity, subject: { ...identity.subject, result_id: "strategy-result-2" } }).label,
  "不同结果",
);
assert.equal(
  compareStrategySourceIdentity(navigation.strategySource, identity).label,
  "无法核验",
  "a date/run-only dashboard source must not be treated as the same result",
);
const restored = readStrategyNavigationState({ ...navigation, dashboardResult: navigation.dashboardResult });
assert.equal(restored?.strategySource.returnTo, "/dashboard/analysis");
assert.equal(restored?.dashboardResult?.summary?.generated_at, summary.generated_at);

console.log("Strategy entry trust behavior OK");
