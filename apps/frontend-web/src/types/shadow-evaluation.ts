export type ShadowEvaluationHorizon = "1h" | "4h" | "session" | "24h";

export interface ShadowEvaluationClassificationCounts {
  correct: number;
  incorrect: number;
  neutral: number;
  hold: number;
  invalidated: number;
  blocked: number;
  unscorable: number;
}

export interface ShadowEvaluationMetricSummary {
  total_count: number;
  approved_count: number;
  scored_count: number;
  blocked_count: number;
  unscorable_count: number;
  directional_count: number;
  correct_count: number;
  incorrect_count: number;
  accuracy: number | null;
  mfe_avg: number | null;
  mae_avg: number | null;
  classification_counts: ShadowEvaluationClassificationCounts;
}

export interface ShadowEvaluationMetrics extends ShadowEvaluationMetricSummary {
  schema_version: "shadow_evaluation_metrics.v1";
  by_horizon: Partial<Record<ShadowEvaluationHorizon, ShadowEvaluationMetricSummary>>;
  horizon?: ShadowEvaluationHorizon;
}

export interface ShadowEvaluationMetricsResponse {
  schema_version: "shadow_evaluation_metrics_api.v1";
  account_id: string;
  asset: string;
  trade_date: string;
  metrics: ShadowEvaluationMetrics;
  snapshot_count: number;
  outcome_count: number;
  evaluation_ids: string[];
  artifact_refs: string[];
}

export interface ShadowEvaluationMetricsQuery {
  tradeDate: string;
  accountId?: string;
  asset?: "XAUUSD";
}
