import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, SourceRef } from "@/types/common";

export type GoldAsset = "XAUUSD" | "gold";

export type GoldPricingLayer =
  | "rate_pricing"
  | "currency_pricing"
  | "risk_pricing"
  | "capital_pricing"
  | "regional_demand"
  | "pricing_center"
  | "external_shock"
  | "capital_confirmation"
  | "structural_support"
  | "price_confirmation";

export type GoldMainline =
  | "fed_policy_path"
  | "real_rates_usd"
  | "oil_prices"
  | "geopolitical_war_risk"
  | "gold_technical_levels"
  | "etf_flows"
  | "central_bank_gold"
  | "china_asia_demand"
  | "institutional_sentiment";

export type TransmissionPath =
  | "inflation_to_real_rates"
  | "usd_pressure"
  | "geopolitics_to_oil_to_rates"
  | "haven_bid"
  | "capital_confirmation"
  | "reserve_reallocation"
  | "asia_demand"
  | "technical_confirmation";

export type GoldPhase =
  | "strong_uptrend"
  | "high_level_range"
  | "weak_repair_watch"
  | "correction_escalation"
  | "trend_failure"
  | "unknown";

export type GoldNetBias =
  | "strong_bullish"
  | "bullish"
  | "neutral_bullish"
  | "neutral"
  | "neutral_bearish"
  | "bearish"
  | "strong_bearish"
  | "mixed"
  | "unknown";

export type GoldMainlineTrend = "rising" | "falling" | "stable" | "new" | "unknown";

export type GoldVerificationStatus =
  | "official_confirmed"
  | "multi_source"
  | "report_derived"
  | "single_source"
  | "unverified"
  | "not_applicable"
  | string;

export type GoldMainlineStatus = DataStatus | "stale" | "fallback" | "manual_required";

export interface GoldMainlineRanking {
  mainline_id?: GoldMainline | string | null;
  mainline?: GoldMainline | string | null;
  label: string;
  pricing_layer: GoldPricingLayer;
  rank: number;
  score: number | null;
  theme_score?: number | null;
  direction_score?: number | null;
  impact_score?: number | null;
  confidence_score?: number | null;
  freshness_score?: number | null;
  direction: GoldNetBias;
  confidence: number | null;
  verification_status: GoldVerificationStatus;
  trend: GoldMainlineTrend;
  impact_strength?: "high" | "medium" | "low" | string | null;
  freshness?: GoldMainlineStatus | string | null;
  evidence_count?: number | null;
  missing_data?: string[] | null;
  related_event_ids?: string[];
  dominant?: boolean;
  summary: string;
  bullish_drivers: string[];
  bearish_drivers: string[];
  event_ids: string[];
  source_refs: SourceRef[];
  artifact_refs?: ArtifactRef[];
}

export interface TransmissionChainStep {
  id: string;
  label: string;
  value?: string | number | null;
  status?: GoldMainlineStatus | null;
  source_refs?: SourceRef[];
}

export interface TransmissionChainSummary {
  path_id: TransmissionPath;
  label: string;
  status: GoldMainlineStatus;
  conclusion_code?: "A" | "B" | "C" | "D" | string;
  conclusion_label?: string;
  net_effect: GoldNetBias;
  geopolitical_status?: GoldMainlineStatus | string | null;
  oil_status?: GoldMainlineStatus | string | null;
  inflation_expectation_status?: GoldMainlineStatus | string | null;
  fed_expectation_status?: GoldMainlineStatus | string | null;
  real_rate_status?: GoldMainlineStatus | string | null;
  dollar_status?: GoldMainlineStatus | string | null;
  gold_effect?: GoldNetBias | string | null;
  conclusion?: string | null;
  verification_needed?: string[];
  dominant_driver?: string | null;
  summary: string;
  steps: TransmissionChainStep[];
  source_refs: SourceRef[];
  artifact_refs?: ArtifactRef[];
}

export interface DriverConflict {
  status: "aligned" | "conflicted" | "mixed" | "unknown";
  dominant_driver: string | null;
  bullish_drivers: string[];
  bearish_drivers: string[];
  net_effect: GoldNetBias;
  explanation: string;
  verification_needed: string[];
  source_refs: SourceRef[];
}

export interface VerificationItem {
  id: string;
  label: string;
  status: "confirmed" | "pending" | "failed" | "unavailable" | "not_required" | string;
  mainline_id?: GoldMainline | null;
  event_id?: string | null;
  required_source?: string | null;
  reason?: string | null;
  source_refs: SourceRef[];
}

export interface MainlineRequirement {
  mainline_id: GoldMainline | string;
  label: string;
  pricing_layer: GoldPricingLayer | string;
  asset_principle: string;
  analysis_chain: string[];
  required_sources: string[];
  required_fields: string[];
  developed_sources: string[];
  missing_sources: string[];
  missing_fields: string[];
  readiness_status: "ready" | "partial" | "missing" | string;
  page_targets: string[];
  verification_requirements: string[];
  development_gaps: string[];
}

export interface AnalysisReadiness {
  status: "ready" | "partial" | "missing" | string;
  ready_count: number;
  partial_count: number;
  missing_count: number;
  total_count: number;
  coverage_ratio: number;
  next_gaps: string[];
}

export interface GoldMainlineEventLink {
  event_id: string;
  mainline_ids: GoldMainline[];
  primary_mainline?: GoldMainline | null;
  transmission_path_ids: TransmissionPath[];
  direction_by_asset: Record<string, GoldNetBias | "bullish" | "bearish" | "uncertain" | "neutral" | "mixed">;
  pricing_status?: string | null;
  verification_status?: GoldVerificationStatus | null;
  market_validation_ref?: string | null;
  bullish_drivers?: string[];
  bearish_drivers?: string[];
  dominant_driver?: string | null;
  verification_needed?: string[];
  verification_chain?: Record<string, unknown> | null;
  changed_dominant_theme?: boolean;
  source_refs: SourceRef[];
  artifact_refs?: ArtifactRef[];
}

export interface GoldMainlinesViewModel {
  status: GoldMainlineStatus;
  schema_version: "gold-event-mainlines-v1" | string;
  asset: GoldAsset;
  as_of: string | null;
  mainlines: GoldMainlineRanking[];
  event_links: GoldMainlineEventLink[];
  dominant_forces: GoldMainline[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  warnings: string[];
}

export interface GoldMacroOverview {
  status: GoldMainlineStatus;
  asset: GoldAsset;
  as_of: string | null;
  phase: GoldPhase;
  dominant_mainline: GoldMainline | null;
  priority_regime?: string;
  priority_reason?: string;
  net_bias: GoldNetBias;
  risk_score: number | null;
  one_line_conclusion: string;
  theme_rankings: GoldMainlineRanking[];
  driver_conflict: DriverConflict | null;
  war_oil_rate_chain: TransmissionChainSummary | null;
  verification_matrix: VerificationItem[];
  mainline_requirements?: MainlineRequirement[];
  analysis_readiness?: AnalysisReadiness;
  architecture_gaps?: string[];
  key_events: string[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  warnings?: string[];
}
