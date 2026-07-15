import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  ShadowEvaluationClassificationCounts,
  ShadowEvaluationHorizon,
  ShadowEvaluationLifecycleCounts,
  ShadowEvaluationMetrics,
  ShadowEvaluationMetricsQuery,
  ShadowEvaluationMetricsResponse,
  ShadowEvaluationMetricSummary,
} from "@/types/shadow-evaluation";

const SHADOW_EVALUATION_METRICS_PATH = "/api/shadow-evaluation/metrics";
const SHADOW_EVALUATION_LATEST_PATH = "/api/shadow-evaluation/metrics/latest";
const DEFAULT_ACCOUNT_ID = "codex-xauusd-shadow";
const HORIZONS: ShadowEvaluationHorizon[] = ["1h", "4h", "session", "24h"];
const CLASSIFICATIONS: Array<keyof ShadowEvaluationClassificationCounts> = [
  "correct",
  "incorrect",
  "neutral",
  "hold",
  "invalidated",
  "blocked",
  "unscorable",
];
const LIFECYCLES: Array<keyof ShadowEvaluationLifecycleCounts> = [
  "legacy_unverified",
  "never_triggered",
  "invalidated_before_entry",
  "triggered",
  "triggered_then_invalidated",
  "target_reached",
  "same_bar_ambiguous",
  "insufficient_market_path",
  "insufficient_strategy_contract",
  "blocked",
];

function fail(message: string, url: string): never {
  throw new ApiError(`Shadow evaluation API ${message}`, { url });
}

function asRecord(value: unknown, field: string, url: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return fail(`${field} 必须是对象`, url);
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, field: string, url: string): string {
  if (typeof value !== "string" || !value.trim()) {
    return fail(`${field} 必须是非空字符串`, url);
  }
  return value;
}

function asCount(value: unknown, field: string, url: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return fail(`${field} 必须是非负整数`, url);
  }
  return value;
}

function asNullableNumber(value: unknown, field: string, url: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fail(`${field} 必须是有限数值或 null`, url);
  }
  return value;
}

function asStringArray(value: unknown, field: string, url: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item.trim())) {
    return fail(`${field} 必须是非空字符串数组`, url);
  }
  return [...value];
}

function normalizeClassificationCounts(
  value: unknown,
  field: string,
  url: string,
): ShadowEvaluationClassificationCounts {
  const raw = asRecord(value, field, url);
  return Object.fromEntries(
    CLASSIFICATIONS.map((classification) => [
      classification,
      asCount(raw[classification], `${field}.${classification}`, url),
    ]),
  ) as unknown as ShadowEvaluationClassificationCounts;
}

function normalizeLifecycleCounts(
  value: unknown,
  field: string,
  url: string,
): ShadowEvaluationLifecycleCounts | null {
  if (value === undefined || value === null) return null;
  const raw = asRecord(value, field, url);
  return Object.fromEntries(
    LIFECYCLES.map((lifecycle) => [
      lifecycle,
      asCount(raw[lifecycle], `${field}.${lifecycle}`, url),
    ]),
  ) as unknown as ShadowEvaluationLifecycleCounts;
}

function normalizeSummary(value: unknown, field: string, url: string): ShadowEvaluationMetricSummary {
  const raw = asRecord(value, field, url);
  const accuracy = asNullableNumber(raw.accuracy, `${field}.accuracy`, url);
  if (accuracy !== null && (accuracy < 0 || accuracy > 1)) {
    fail(`${field}.accuracy 必须介于 0 和 1 之间`, url);
  }
  return {
    total_count: asCount(raw.total_count, `${field}.total_count`, url),
    approved_count: asCount(raw.approved_count, `${field}.approved_count`, url),
    scored_count: asCount(raw.scored_count, `${field}.scored_count`, url),
    verified_scored_count: asCount(raw.verified_scored_count, `${field}.verified_scored_count`, url),
    legacy_unverified_count: asCount(raw.legacy_unverified_count, `${field}.legacy_unverified_count`, url),
    blocked_count: asCount(raw.blocked_count, `${field}.blocked_count`, url),
    unscorable_count: asCount(raw.unscorable_count, `${field}.unscorable_count`, url),
    directional_count: asCount(raw.directional_count, `${field}.directional_count`, url),
    correct_count: asCount(raw.correct_count, `${field}.correct_count`, url),
    incorrect_count: asCount(raw.incorrect_count, `${field}.incorrect_count`, url),
    accuracy,
    mfe_avg: asNullableNumber(raw.mfe_avg, `${field}.mfe_avg`, url),
    mae_avg: asNullableNumber(raw.mae_avg, `${field}.mae_avg`, url),
    classification_counts: normalizeClassificationCounts(
      raw.classification_counts,
      `${field}.classification_counts`,
      url,
    ),
    lifecycle_counts: normalizeLifecycleCounts(
      raw.lifecycle_counts,
      `${field}.lifecycle_counts`,
      url,
    ),
  };
}

function normalizeMetrics(value: unknown, url: string): ShadowEvaluationMetrics {
  const raw = asRecord(value, "metrics", url);
  if (raw.schema_version !== "shadow_evaluation_metrics.v1") {
    fail("metrics schema 不兼容", url);
  }
  const byHorizonRaw = asRecord(raw.by_horizon, "metrics.by_horizon", url);
  const unknownHorizons = Object.keys(byHorizonRaw).filter(
    (key) => !HORIZONS.includes(key as ShadowEvaluationHorizon),
  );
  if (unknownHorizons.length > 0) {
    fail(`metrics.by_horizon 包含未知周期: ${unknownHorizons.join(", ")}`, url);
  }
  const byHorizon: ShadowEvaluationMetrics["by_horizon"] = {};
  HORIZONS.forEach((horizon) => {
    if (byHorizonRaw[horizon] !== undefined) {
      byHorizon[horizon] = normalizeSummary(byHorizonRaw[horizon], `metrics.by_horizon.${horizon}`, url);
    }
  });
  const summary = normalizeSummary(raw, "metrics", url);
  const normalized: ShadowEvaluationMetrics = {
    schema_version: "shadow_evaluation_metrics.v1",
    ...summary,
    by_horizon: byHorizon,
  };
  if (raw.horizon !== undefined) {
    if (typeof raw.horizon !== "string" || !HORIZONS.includes(raw.horizon as ShadowEvaluationHorizon)) {
      fail("metrics.horizon 不兼容", url);
    }
    normalized.horizon = raw.horizon as ShadowEvaluationHorizon;
  }
  return normalized;
}

function normalizeResponse(payload: unknown, url: string): ShadowEvaluationMetricsResponse {
  const raw = asRecord(payload, "响应", url);
  if (raw.schema_version !== "shadow_evaluation_metrics_api.v1") {
    fail("schema 不兼容", url);
  }
  return {
    schema_version: "shadow_evaluation_metrics_api.v1",
    account_id: asString(raw.account_id, "account_id", url),
    asset: asString(raw.asset, "asset", url),
    trade_date: asString(raw.trade_date, "trade_date", url),
    metrics: normalizeMetrics(raw.metrics, url),
    snapshot_count: asCount(raw.snapshot_count, "snapshot_count", url),
    outcome_count: asCount(raw.outcome_count, "outcome_count", url),
    evaluation_ids: asStringArray(raw.evaluation_ids, "evaluation_ids", url),
    artifact_refs: asStringArray(raw.artifact_refs, "artifact_refs", url),
  };
}

export function fetchShadowEvaluationMetrics(tradeDate: string): Promise<ShadowEvaluationMetricsResponse>;
export function fetchShadowEvaluationMetrics(query: ShadowEvaluationMetricsQuery): Promise<ShadowEvaluationMetricsResponse>;
export async function fetchShadowEvaluationMetrics(
  query: string | ShadowEvaluationMetricsQuery,
): Promise<ShadowEvaluationMetricsResponse> {
  const {
    tradeDate,
    accountId = DEFAULT_ACCOUNT_ID,
    asset = "XAUUSD",
  } = typeof query === "string" ? { tradeDate: query } : query;
  const search = new URLSearchParams({
    account_id: accountId,
    asset,
    trade_date: tradeDate,
  });
  const path = `${SHADOW_EVALUATION_METRICS_PATH}?${search.toString()}`;
  const payload = await fetchJson<unknown>(path);
  return normalizeResponse(payload, path);
}

export async function fetchLatestShadowEvaluationMetrics(
  accountId = DEFAULT_ACCOUNT_ID,
  asset: "XAUUSD" = "XAUUSD",
): Promise<ShadowEvaluationMetricsResponse> {
  const search = new URLSearchParams({ account_id: accountId, asset });
  const path = `${SHADOW_EVALUATION_LATEST_PATH}?${search.toString()}`;
  const payload = await fetchJson<unknown>(path);
  return normalizeResponse(payload, path);
}
