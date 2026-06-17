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
  net_gex: number;
  net_gex_direction: CMEOptionsNetGEXDirection;
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
  gamma_zero?: number | null;
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
  data_quality?: Record<string, unknown> | null;
  audit?: Record<string, unknown> | null;
}

export interface CMEOptionsMockFile extends CMEOptionsSnapshot {}

export interface CMEOptionsResponse extends CMEOptionsSnapshot {}