import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, SourceRef } from "@/types/common";
import type { GoldMainline, TransmissionChain, TransmissionPath } from "@/generated/gold-contract";
import type { ProcessingTrace } from "@/types/processing-monitor";

export type { GoldMainline, TransmissionChain, TransmissionPath } from "@/generated/gold-contract";

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
  | "mixed_bullish"
  | "mixed_bearish"
  | "unknown";

export type GoldMainlineTrend = "rising" | "falling" | "stable" | "new" | "unknown";

export type KnownGoldVerificationStatus =
  | "official_confirmed"
  | "multi_source"
  | "report_derived"
  | "single_source"
  | "unverified"
  | "needs_verification"
  | "not_applicable";

export type GoldVerificationStatus = KnownGoldVerificationStatus | "unknown";

export type GoldMainlineStatus = DataStatus | "stale" | "fallback" | "manual_required" | "blocked" | "unknown";
export type GoldImpactStrength = "high" | "medium" | "low" | "weak" | "strong" | "unknown";
export type GoldChainConclusionCode = "A" | "B" | "C" | "D" | "unknown";
export type GoldReadinessStatus = "ready" | "partial" | "missing" | "unknown";
export type GoldSchemaVersion = "gold-event-mainlines-v1" | "unknown";

export interface GoldMainlineRanking {
  mainline_id?: GoldMainline | null;
  mainline?: GoldMainline | null;
  label: string;
  pricing_layer: GoldPricingLayer | "unknown";
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
  impact_strength?: GoldImpactStrength | null;
  freshness?: GoldMainlineStatus | null;
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
  conclusion_code?: GoldChainConclusionCode;
  conclusion_label?: string;
  net_effect: GoldNetBias;
  geopolitical_status?: GoldMainlineStatus | null;
  oil_status?: GoldMainlineStatus | null;
  inflation_expectation_status?: GoldMainlineStatus | null;
  fed_expectation_status?: GoldMainlineStatus | null;
  real_rate_status?: GoldMainlineStatus | null;
  dollar_status?: GoldMainlineStatus | null;
  gold_effect?: GoldNetBias | null;
  conclusion?: string | null;
  verification_needed?: string[];
  dominant_driver?: string | null;
  summary: string;
  steps: TransmissionChainStep[];
  source_refs: SourceRef[];
  artifact_refs?: ArtifactRef[];
}

export type WarOilRateChain = TransmissionChainSummary;

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

export type DriverDecomposition = DriverConflict;

export interface VerificationItem {
  id: string;
  label: string;
  status: "confirmed" | "pending" | "failed" | "unavailable" | "not_required" | "unknown";
  mainline_id?: GoldMainline | null;
  event_id?: string | null;
  required_source?: string | null;
  reason?: string | null;
  source_refs: SourceRef[];
}

export interface MainlineRequirement {
  mainline_id: GoldMainline | null;
  label: string;
  pricing_layer: GoldPricingLayer | "unknown";
  asset_principle: string;
  analysis_chain: string[];
  required_sources: string[];
  required_fields: string[];
  developed_sources: string[];
  missing_sources: string[];
  missing_fields: string[];
  readiness_status: GoldReadinessStatus;
  page_targets: string[];
  verification_requirements: string[];
  development_gaps: string[];
}

export interface AnalysisReadiness {
  status: GoldReadinessStatus;
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
  schema_version: GoldSchemaVersion;
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
  processing_traces?: ProcessingTrace[];
  warnings?: string[];
}
