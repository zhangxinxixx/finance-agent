export type CMEOptionsDataSourceStatus = "FINAL" | "PRELIM";

export type CMEOptionsNetGEXDirection = "positive" | "negative" | "neutral";

export type CMEOptionsWallType = "Call Wall" | "Put Wall" | "Balanced Wall" | "Active Wall" | "Pin Wall" | "Static Wall" | "Turnover Wall" | "New Wall" | "Resistance Wall" | "Support Wall";

export type CMEOptionsSourceStatus = "ok" | "warn" | "error" | "unavailable" | "info";

export interface CMEOptionsWallScore {
  strike: number;
  wall_type: CMEOptionsWallType;
  side?: "CALL" | "PUT" | null;
  oi: number;
  delta_oi: number | null;
  wall_score: number;
  pnt: number;
}

export interface CMEOptionsLevelItem {
  strike: number;
  wall_score: number;
  distance_pct: number;
}

export interface CMEOptionsSupportResistance {
  resistance: CMEOptionsLevelItem[];
  support: CMEOptionsLevelItem[];
}

export interface CMEOptionsGammaZero {
  price: number;
  method: string;
}

export interface CMEOptionsNetGEXAggregate {
  net_gex: number | null;
  net_gex_direction: CMEOptionsNetGEXDirection | null;
  gamma_zero: CMEOptionsGammaZero;
}

// ── Per-expiry detail (P2-11) ──

export interface CMEOptionsGEXTopItem {
  strike: number;
  call_gex: number;
  put_gex: number;
  net_gex: number;
  total_gex: number;
}

export interface CMEOptionsExpirySummary {
  forward_price?: number | null;
  f_value?: number | null;
  gamma_zero?: number | null;
  gamma_zero_method?: string | null;
  net_gex?: number | null;
  call_gex?: number | null;
  put_gex?: number | null;
  total_gex?: number | null;
  atm_iv?: number | null;
  time_to_expiry?: number | null;
  structure?: string | null;
}

export interface CMEOptionsIVSkew {
  atm_iv?: number | null;
  call_25d_iv?: number | null;
  put_25d_iv?: number | null;
  skew_25d?: number | null;
  call_10d_iv?: number | null;
  put_10d_iv?: number | null;
  skew_10d?: number | null;
  tail_skew_10d?: number | null;
  interpretation?: string | null;
}

export interface CMEOptionsGEXByExpiry {
  gex_top: CMEOptionsGEXTopItem[];
  summary: CMEOptionsExpirySummary;
  iv_skew: CMEOptionsIVSkew;
}

export interface CMEOptionsGEX {
  netgex_aggregate: CMEOptionsNetGEXAggregate;
  by_expiry: Record<string, CMEOptionsGEXByExpiry>;
}

// ── Exposure (P2-11) ──

export interface CMEOptionsExpiryExposure {
  net_delta_exposure?: number | null;
  total_vega?: number | null;
  total_theta?: number | null;
  call_delta_exposure?: number | null;
  put_delta_exposure?: number | null;
}

export interface CMEOptionsExposure {
  [expiry: string]: CMEOptionsExpiryExposure;
}

// ── Roll signals ──

export interface CMEOptionsRollSignal {
  roll_type?: string | null;
  near_expiry: string;
  far_expiry: string;
  evidence: string[];
  confidence: number;
}

// ── Intent ──

export interface CMEOptionsIntent {
  type: string;
  confidence: number;
  score?: number;
  evidence?: string[];
}

// ── Calibration ──

export interface CMEOptionsCalibration {
  calculation_method?: string | null;
  wall_map?: Record<string, unknown> | null;
  wall_score_delta_1d?: Record<string, number> | null;
  wall_score_delta_1w?: Record<string, number> | null;
  oi_change_by_strike?: Record<string, number[]> | null;
  expiry_roll_signal?: CMEOptionsRollSignal[];
  near_month_vs_next_month?: {
    near_total_oi?: number | null;
    near_total_volume?: number | null;
    next_total_oi?: number | null;
    next_total_volume?: number | null;
    oi_ratio?: number | null;
    volume_ratio?: number | null;
  } | null;
  calibration_warnings?: string[];
  source_refs?: string[];
}

export interface CMEOptionsDataQuality {
  categories?: Record<string, number | null | undefined>;
  warnings?: string[];
}

export interface CMEOptionsDataSource {
  product: string;
  status: CMEOptionsDataSourceStatus;
  expiries: string[];
  row_count: number;
  report_date?: string | null;
  source_url?: string | null;
  input_snapshot_ids?: string[];
}

export interface CMEOptionsSourceTraceItem {
  name: string;
  trade_date: string;
  file: string;
  snapshot_id: string | null;
  source_ref: string;
  status: CMEOptionsSourceStatus;
  endpoint?: string | null;
  latest_raw_time?: string | null;
  latest_parsed_time?: string | null;
  model_version?: string | null;
}

export interface CMEOptionsDataLevelItem {
  field: string;
  description: string;
  count?: number;
}

export interface CMEOptionsDataLevel {
  label: string;
  items: CMEOptionsDataLevelItem[];
}

export interface CMEOptionsDataLevels {
  level_1_confirmed: CMEOptionsDataLevel;
  level_2_computed: CMEOptionsDataLevel;
  level_3_interpretive: CMEOptionsDataLevel;
}

export interface CMEOptionsClaimReview {
  claim_id: string;
  verdict: string;
  reason: string;
}

export interface CMEOptionsAnalysisAgentSummary {
  agent_output_id: string;
  agent_name: string;
  display_name: string;
  status: string;
  bias: string;
  confidence: number;
  summary: string;
  fact_review_status?: string | null;
  synthesis_status?: string | null;
  key_findings: string[];
  risk_points: string[];
  watchlist: string[];
  invalid_conditions: string[];
  claim_count: number;
  claim_reviews: CMEOptionsClaimReview[];
  warning_count?: number;
  warnings?: Array<{ code: string; message: string }>;
  reading_order?: string[];
  consensus_points?: string[];
  divergent_points?: string[];
  excluded_claim_ids?: string[];
  review_item_ids?: string[];
}

export interface CMEOptionsPendingReview {
  review_id: string;
  claim_id: string | null;
  source_module: string;
  severity: string;
  reason: string;
  suggested_action: string | null;
}

export interface CMEOptionsAnalysis {
  snapshot_id: string | null;
  run_id: string | null;
  fact_review_status: string | null;
  cme_options_agent: CMEOptionsAnalysisAgentSummary | null;
  fact_review: CMEOptionsAnalysisAgentSummary | null;
  synthesis: CMEOptionsAnalysisAgentSummary | null;
  pending_review_count: number;
  pending_reviews: CMEOptionsPendingReview[];
}

export interface CMEOptionsParameters {
  f_value?: number | null;
  r_value?: number | null;
  p0?: number | null;
  p0_source?: string | null;
  report_p0?: number | null;
  report_p0_source?: string | null;
  live_p0?: number | null;
  live_p0_source?: string | null;
  price_anchor_rule?: string | null;
  model?: string | null;
  used_real_gex?: boolean | null;
  netgex_scope?: string | null;
  analysis_range?: {
    strike_min?: number | null;
    strike_max?: number | null;
    source?: string | null;
  } | null;
}

export interface CMEOptionsSnapshot {
  trade_date: string;
  data_source: CMEOptionsDataSource;
  parameters: CMEOptionsParameters;
  gex: CMEOptionsGEX;
  wall_scores: CMEOptionsWallScore[];
  support_resistance: CMEOptionsSupportResistance;
  intent: CMEOptionsIntent;
  calibration: CMEOptionsCalibration;
  source_trace: CMEOptionsSourceTraceItem[];
  has_data: boolean;
  source: "api" | "mock" | "unavailable";
  error_reason?: string | null;
  data_levels?: CMEOptionsDataLevels;
  run_id?: string | null;
  snapshot_id?: string | null;
  analysis?: CMEOptionsAnalysis | null;
  exposure?: CMEOptionsExposure | null;
  roll_signals?: CMEOptionsRollSignal[];
  normalization?: Record<string, unknown> | null;
  data_quality?: CMEOptionsDataQuality | null;
  audit?: Record<string, unknown> | null;
}

export interface CMEOptionsMockFile extends CMEOptionsSnapshot {}

export interface CMEOptionsResponse extends CMEOptionsSnapshot {}

// ── Decision ViewModel ──

export type CMEOptionsDecisionStatus = "available" | "partial" | "unavailable";

export interface CMEOptionsDecisionMetric {
  current: number | null;
  previous: number | null;
  delta: number | null;
  pct_change: number | null;
}

export interface CMEOptionsDecisionOIByExpiry {
  expiry: string;
  expiry_scope: string;
  comparison_status: "available" | "unavailable";
  total: CMEOptionsDecisionMetric;
  call: CMEOptionsDecisionMetric;
  put: CMEOptionsDecisionMetric;
}

export interface CMEOptionsDecisionGammaSummary {
  regime: string;
  net_gex: number | null;
  gamma_zero: number | null;
  method: string | null;
  flip_band: { lower: number; upper: number; step: number } | null;
  live_price: number | null;
}

export interface CMEOptionsDecisionKeyLevel {
  strike: number | null;
  band: { lower: number; upper: number; step?: number | null } | null;
  role: string;
  strength: number | string | null;
  trend: string | null;
  evidence: string[];
  invalidation: string[];
  expiry_scope: string;
  distance_pct: number | null;
  structural_role_at_report: string;
  current_relation: "below_price" | "above_price" | "at_price" | null;
  dynamic_role: string;
}

export interface CMEOptionsDecisionRoll {
  near_expiry: string;
  far_expiry: string;
  near_oi_delta: number | null;
  far_oi_delta: number | null;
  far_put_delta: number | null;
  far_call_delta: number | null;
  labels: string[];
}

export interface CMEOptionsDecisionSetup {
  triggers: string[];
  targets: number[];
  invalidation: string[];
}

export interface CMEOptionsDecisionStrategy {
  status: CMEOptionsDecisionStatus;
  horizon?: string;
  reason?: string;
  regime?: string;
  bias?: string;
  summary?: string;
  no_trade_zone?: number[];
  long_setup?: CMEOptionsDecisionSetup | null;
  short_setup?: CMEOptionsDecisionSetup | null;
  confirmation?: string[];
  invalidation?: string[];
  targets?: number[];
  structure_bias?: string;
  oi_trend?: string;
  sample_count?: number;
  required_sample_count?: number;
  sample_window?: { from: string; to: string } | null;
  call_oi_change?: number | null;
  put_oi_change?: number | null;
  confidence?: number | null;
  risk_notes: string[];
}

export interface CMEOptionsDecisionLargeOiLevel {
  expiry: string;
  strike: number | null;
  call_oi: number | null;
  put_oi: number | null;
  total_oi: number | null;
  total_oi_change: number | null;
  volume: number | null;
  distance_pct: number | null;
  dominant_side: string;
}

export interface CMEOptionsDecisionOiChange {
  expiry: string;
  strike: number | null;
  option_type: string;
  current_oi: number | null;
  previous_oi: number | null;
  delta: number | null;
  volume: number | null;
  block: number | null;
  pnt: number | null;
}

export interface CMEOptionsDecisionScenarioPath {
  path_id: string;
  label: string;
  status: string;
  triggers: string[];
  targets: number[];
  invalidation: string[];
}

export interface CMEOptionsDecisionActivityTotals {
  call: number | null;
  put: number | null;
  total: number | null;
}

export interface CMEOptionsDecisionResponse {
  schema_version: "cme_options_decision.v1";
  status: CMEOptionsDecisionStatus;
  meta: {
    current_trade_date: string | null;
    previous_trade_date: string | null;
    product: string;
    lookback_days: number;
    comparison_status: "available" | "unavailable";
  };
  executive_summary: {
    oi_delta: number | null;
    gamma_regime: string;
    roll_status: CMEOptionsDecisionStatus;
    intraday_status: CMEOptionsDecisionStatus;
  };
  price_context: {
    report_p0: number | null;
    report_p0_source: string | null;
    report_p0_timestamp: string | null;
    live_p0: number | null;
    live_p0_source: string | null;
    live_p0_timestamp: string | null;
    live_price_status: "fresh" | "stale" | "future" | "unavailable";
    live_price_freshness_seconds: number | null;
    live_price_coverage_status: "complete" | "degraded" | "unavailable";
    model_f: Record<string, number>;
    price_anchor_rule: string | null;
  };
  oi_summary: {
    comparison_status: "available" | "unavailable";
    total: CMEOptionsDecisionMetric;
    call: CMEOptionsDecisionMetric;
    put: CMEOptionsDecisionMetric;
  };
  oi_by_expiry: CMEOptionsDecisionOIByExpiry[];
  large_oi_levels: CMEOptionsDecisionLargeOiLevel[];
  nearby_large_oi_levels: CMEOptionsDecisionLargeOiLevel[];
  oi_change_rankings: {
    comparison_status: "available" | "unavailable";
    largest_increases: CMEOptionsDecisionOiChange[];
    largest_decreases: CMEOptionsDecisionOiChange[];
  };
  pnt_summary: {
    status: CMEOptionsDecisionStatus;
    totals: CMEOptionsDecisionActivityTotals;
    pnt_totals: CMEOptionsDecisionActivityTotals;
    block_totals: CMEOptionsDecisionActivityTotals;
    block_coverage_status: "observed" | "not_verified" | "unavailable";
    warnings: string[];
    top_activity: Array<Record<string, unknown>>;
  };
  gamma_summary: CMEOptionsDecisionGammaSummary;
  gamma_profile: { price_grid: number[]; net_gex_values: number[]; scope: string };
  key_levels: CMEOptionsDecisionKeyLevel[];
  roll_summary: { status: CMEOptionsDecisionStatus; reason?: string; items: CMEOptionsDecisionRoll[] };
  intent_summary: {
    type: string | null;
    score: number | null;
    confidence: number | null;
    wording: string | null;
    scores: Record<string, number | null>;
    evidence: string[];
  };
  structure_summary: {
    state: string;
    label: string;
    summary: string;
    reference_price: number | null;
    gamma_zero: number | null;
    below_gamma_zero: boolean;
    net_gex: number | null;
    net_gex_change: number | null;
    repair_detected: boolean;
    trend_launch_watch: boolean;
    trend_confirmed: boolean;
  };
  scenario_paths: CMEOptionsDecisionScenarioPath[];
  intraday_strategy: CMEOptionsDecisionStrategy;
  swing_strategy: CMEOptionsDecisionStrategy;
  data_quality: { cme_status: string | string[] | null; warnings: string[]; [key: string]: unknown };
}
