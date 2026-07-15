import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";

export type LiveStrategyAvailability = "available" | "partial" | "unavailable";
export type LiveStrategyStatus = "WAITING" | "WATCHING" | "ARMED" | "TRIGGERED" | "SUSPENDED_DATA";
export type LiveStrategyScenarioDirection = "long" | "short";
export type LiveStrategyScenarioStatus = "watching" | "armed" | "triggered" | "blocked_data" | "blocked_rr" | "unavailable";
export type LiveStrategyPriceEventType = "approach" | "touch" | "intrabar_breach" | "accepted_break" | "failed_break" | "retest" | "reclaim";

export interface LiveStrategyBaseline {
  strategy_card_id: string | null;
  version: string | null;
  bias: string | null;
  market_regime: string | null;
  confidence: number | null;
}

export interface LiveStrategyMarket {
  price: number | null;
  bid: number | null;
  ask: number | null;
  change_pct: number | null;
  provider: string | null;
  timestamps: Record<string, string | null>;
  freshness_seconds: number | null;
  status: string | null;
  session: string | null;
}

export interface LiveStrategyNearestLevel {
  role: string | null;
  value: number | null;
  distance: number | null;
  distance_pct: number | null;
  strength: number | string | null;
}

export interface LiveStrategyMarketState {
  gamma_regime: string | null;
  nearest_level: LiveStrategyNearestLevel | null;
  atr14: number | null;
  level_event: string | null;
  key_levels: Array<Record<string, unknown>>;
  latest_price_event: LiveStrategyPriceEvent | null;
  confirmation_15m: LiveStrategyFifteenMinuteConfirmation | null;
  break_buffer: number | null;
  retest_threshold: number | null;
}

export interface LiveStrategyCmeOiLevel {
  expiry: string | null;
  strike: number | null;
  call_oi: number | null;
  put_oi: number | null;
  total_oi: number | null;
  total_oi_change: number | null;
  volume: number | null;
  distance_pct: number | null;
  dominant_side: string | null;
}

export interface LiveStrategyCmeOiChange {
  expiry: string | null;
  strike: number | null;
  option_type: string | null;
  current_oi: number | null;
  previous_oi: number | null;
  delta: number | null;
  volume: number | null;
  block: number | null;
  pnt: number | null;
}

export interface LiveStrategyCmeScenarioPath {
  path_id: string;
  label: string;
  status: string;
  triggers: string[];
  targets: number[];
  invalidation: string[];
}

export interface LiveStrategyCmePositioning {
  status: LiveStrategyAvailability;
  trade_date: string | null;
  previous_trade_date: string | null;
  baseline_trade_date: string | null;
  aligned_with_baseline: boolean | null;
  source_status: string | null;
  comparison_status: string | null;
  total_oi: {
    current: number | null;
    previous: number | null;
    delta: number | null;
    pct_change: number | null;
  };
  large_oi_levels: LiveStrategyCmeOiLevel[];
  large_oi_scope: "nearby_6pct" | "full_chain" | string;
  largest_increases: LiveStrategyCmeOiChange[];
  largest_decreases: LiveStrategyCmeOiChange[];
  pnt_summary: Record<string, unknown>;
  intent_summary: {
    type: string | null;
    score: number | null;
    confidence: number | null;
    wording: string | null;
    scores: Record<string, number | null>;
    evidence: string[];
  };
  structure_summary: {
    state: string | null;
    label: string | null;
    summary: string | null;
    repair_detected: boolean;
    trend_launch_watch: boolean;
    trend_confirmed: boolean;
  };
  scenario_paths: LiveStrategyCmeScenarioPath[];
}

export interface LiveStrategyPriceEventConfirmation {
  five_minute_closes: number[];
  fifteen_minute_close: number | null;
}

export interface LiveStrategyPriceEvent {
  event_type: LiveStrategyPriceEventType | null;
  direction: "above" | "below" | null;
  confirmed: boolean;
  detected_at: string | null;
  price: number | null;
  related_level: LiveStrategyNearestLevel | null;
  break_buffer: number | null;
  confirmation: LiveStrategyPriceEventConfirmation;
  evidence: Array<string | Record<string, unknown>>;
  source_refs: SourceRef[];
}

export interface LiveStrategyFifteenMinuteConfirmation {
  confirmed: boolean;
  close: number | null;
  timestamp: string | null;
}

export interface LiveStrategyTarget {
  label: string | null;
  price: number | null;
  source_role: string | null;
}

export interface LiveStrategyRiskReward {
  tp1: number | null;
  tp2: number | null;
  tp3: number | null;
}

export interface LiveStrategyScenarioGate {
  passed: boolean;
  reasons: string[];
}

export interface LiveStrategyScenarioCalculation {
  ruleset: string | null;
  inputs: Record<string, unknown>;
}

export interface LiveStrategySetup {
  setup_id: string | null;
  direction: LiveStrategyScenarioDirection;
  status: LiveStrategyScenarioStatus;
  reference_level: LiveStrategyNearestLevel | null;
  entry_zone: [number, number] | null;
  trigger_conditions: string[];
  confirmation_conditions: string[];
  invalidation_level: number | null;
  stop_reference: number | null;
  volatility_buffer: number | null;
  spread_buffer: number | null;
  targets: LiveStrategyTarget[];
  risk_reward: LiveStrategyRiskReward;
  gate: LiveStrategyScenarioGate;
  calculation: LiveStrategyScenarioCalculation;
}

export interface LiveStrategyNoTrade {
  range: [number, number] | null;
  reasons: string[];
  waiting_conditions: string[];
}

export interface LiveStrategyFeasibility {
  data_ready: boolean;
  level_ready: boolean;
  trigger_ready: boolean;
  risk_ready: boolean;
  rr_ready: boolean;
  execution_ready: boolean;
  reasons: Record<string, string[]>;
}

export interface LiveStrategyUpdateReason {
  reason_code: string | null;
  message: string | null;
  related_level: LiveStrategyNearestLevel | null;
}

export interface LiveStrategyDataQuality {
  warnings: string[];
  [key: string]: unknown;
}

export interface LiveStrategyResponse {
  schema_version: "live_strategy.v1";
  status: LiveStrategyAvailability;
  strategy_id: string | null;
  baseline_strategy_id: string | null;
  strategy_version: string | null;
  asset: string;
  strategy_status: LiveStrategyStatus;
  updated_at: string | null;
  update_reason: LiveStrategyUpdateReason;
  baseline: LiveStrategyBaseline;
  live_market: LiveStrategyMarket;
  market_state: LiveStrategyMarketState;
  cme_positioning: LiveStrategyCmePositioning;
  active_scenario: LiveStrategyScenarioDirection | "no_trade" | null;
  setups: LiveStrategySetup[];
  no_trade: LiveStrategyNoTrade;
  feasibility: LiveStrategyFeasibility;
  source_refs: SourceRef[];
  artifact_refs: Array<ArtifactRef | string>;
  data_quality: LiveStrategyDataQuality;
}
