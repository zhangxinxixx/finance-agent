import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const root = resolve(scriptDir, "..");

function summary(overrides = {}) {
  return {
    total_count: 0,
    approved_count: 0,
    scored_count: 0,
    verified_scored_count: 0,
    legacy_unverified_count: 0,
    blocked_count: 0,
    unscorable_count: 0,
    directional_count: 0,
    correct_count: 0,
    incorrect_count: 0,
    accuracy: null,
    mfe_avg: null,
    mae_avg: null,
    classification_counts: {
      correct: 0,
      incorrect: 0,
      neutral: 0,
      hold: 0,
      invalidated: 0,
      blocked: 0,
      unscorable: 0,
    },
    lifecycle_counts: null,
    ...overrides,
  };
}

function metricsData(by_horizon) {
  return {
    schema_version: "shadow_evaluation_metrics_api.v1",
    account_id: "ssr-check",
    asset: "XAUUSD",
    trade_date: "2026-10-05",
    metrics: {
      schema_version: "shadow_evaluation_metrics.v1",
      ...summary(),
      by_horizon,
    },
    snapshot_count: 0,
    outcome_count: 0,
    evaluation_ids: [],
    artifact_refs: [],
  };
}

const emptyOutcome = (horizon, lifecycle_status, classification = "hold") => ({
  horizon,
  status: "scored",
  classification,
  verification_status: "verified",
  lifecycle_status,
  setup_id: null,
  fill_price: null,
  fill_time: null,
  target_price: null,
  target_time: null,
  exit_price: null,
  exit_time: null,
  return_abs: null,
  return_pct: null,
  mfe: null,
  mae: null,
  reason_codes: [],
});

const historyData = {
  schema_version: "shadow_evaluation_history.v1",
  account_id: "ssr-check",
  asset: "XAUUSD",
  total: 1,
  truncated: false,
  items: [{
    trade_date: "2026-10-05",
    evaluation_id: "evaluation-ssr-check",
    strategy_status: "WAITING",
    as_of: null,
    publish_allowed: false,
    outcome_count: 2,
    approved_count: 0,
    blocked_count: 0,
    unscorable_count: 0,
    legacy_unverified_count: 0,
    accuracy: null,
    outcomes: [
      emptyOutcome("1h", "never_triggered"),
      emptyOutcome("4h", null),
    ],
    artifact_refs: [],
  }],
};

const vite = await createServer({
  root,
  configFile: resolve(root, "vite.config.ts"),
  appType: "custom",
  logLevel: "error",
  optimizeDeps: { noDiscovery: true },
  server: { middlewareMode: true },
});

try {
  const metricsModule = await vite.ssrLoadModule("/src/components/strategy/ShadowEvaluationPanel.tsx");
  const historyModule = await vite.ssrLoadModule("/src/components/strategy/ShadowEvaluationHistoryPanel.tsx");
  const renderMetrics = (data) => renderToStaticMarkup(React.createElement(metricsModule.ShadowEvaluationPanel, {
    data,
    isLoading: false,
    isUnavailable: false,
    error: null,
  }));
  const renderHistory = (data) => renderToStaticMarkup(React.createElement(historyModule.ShadowEvaluationHistoryPanel, {
    data,
    isLoading: false,
    isUnavailable: false,
    error: null,
  }));

  const absentHorizon = renderMetrics(metricsData({}));
  assert.match(absentHorizon, /1 小时[\s\S]*?暂无样本[\s\S]*?总数[\s\S]*?未提供[\s\S]*?已核验评分[\s\S]*?未提供[\s\S]*?质量阻断[\s\S]*?未提供[\s\S]*?不可评分[\s\S]*?未提供/, "an absent horizon must remain unavailable instead of becoming zero");

  const knownZero = renderMetrics(metricsData({ "1h": summary() }));
  assert.match(knownZero, /1 小时[\s\S]*?总数[\s\S]*?>0<[\s\S]*?已核验评分[\s\S]*?>0<[\s\S]*?质量阻断[\s\S]*?>0<[\s\S]*?不可评分[\s\S]*?>0</, "a backend horizon with real zero counts must keep zero visible");

  const history = renderHistory(historyData);
  assert.match(history, /未触发/, "never_triggered must remain a separate lifecycle label");
  // The shared status pill may present the raw HOLD token as “沿用”; the
  // semantic contract is the visible “观望” classification, kept separate
  // from the lifecycle label “未触发”.
  assert.match(history, /观望（(?:HOLD|沿用)）/, "HOLD classification must use the observation meaning");
  assert.doesNotMatch(history, /持有 \/ 未触发/, "HOLD must not be presented as a position or merged lifecycle");
} finally {
  await vite.close();
}

console.log("Shadow evaluation SSR missing-zero and HOLD behavior OK");
