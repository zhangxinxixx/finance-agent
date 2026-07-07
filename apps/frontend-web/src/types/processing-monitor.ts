import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";

export type ProcessingTraceMode =
  | "processing_trace_id"
  | "event_id"
  | "source_ref"
  | "input_id"
  | "mainline"
  | "transmission_chain";

export type KnownProcessingCoverageStatus =
  | "covered"
  | "degraded"
  | "missing"
  | "stale"
  | "pass"
  | "needs_review"
  | "blocked";

export type ProcessingCoverageStatus = KnownProcessingCoverageStatus | "unknown";

export type KnownProcessingStageStatus =
  | "raw"
  | "parsed"
  | "normalized"
  | "attributed"
  | "validated"
  | "projected"
  | "rendered";

export type ProcessingStageStatus = KnownProcessingStageStatus | "unknown";

export interface ProcessingStage {
  stage_id: string;
  status: ProcessingStageStatus;
  started_at?: string | null;
  finished_at?: string | null;
  source_refs?: SourceRef[];
  artifact_refs?: ArtifactRef[];
  warnings?: string[];
}

export interface ProcessingTrace {
  trace_id: string;
  entity_type: "news" | "report_input" | "event" | "analysis_signal" | string;
  entity_id: string;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  stages: ProcessingStage[];
  current_status: ProcessingStageStatus;
  warnings: string[];
}

export interface ProcessingTracePathNode {
  node_id: string;
  label: string;
  stage: string;
  status: ProcessingCoverageStatus;
  source_ref_count: number;
  artifact_ref_count: number;
}

export interface ProcessingInputCoverage {
  news_input_count: number;
  report_input_count: number;
  followup_count: number;
  article_brief_count: number;
  source_ref_count: number;
  artifact_ref_count: number;
  without_source_ref_count: number;
}

export interface ProcessingMainlineCoverage {
  mainline_id: string;
  status: ProcessingCoverageStatus;
  event_count: number;
  source_ref_count: number;
  missing_data: string[];
}

export interface ProcessingTransmissionChainCoverage {
  chain_id: string;
  status: ProcessingCoverageStatus;
  verification_needed: string[];
}

export interface ProcessingMixedHealth {
  status: ProcessingCoverageStatus;
  mixed_events_total: number;
  mixed_without_bullish_drivers: number;
  mixed_without_bearish_drivers: number;
  mixed_without_dominant_driver: number;
  mixed_without_verification_needed: number;
}

export interface ProcessingSourceFreshness {
  source_freshness: string;
  feature_freshness: string;
  analysis_freshness: string;
  frontend_freshness: string;
}

export interface ProcessingSourceHealth {
  overall_status: string;
  as_of: string | null;
  p0_missing: string[];
  p1_missing: string[];
  p2_missing: string[];
  stale_sources: string[];
  fresh_sources: string[];
  can_build_gold_macro_overview: boolean;
  blocking_reasons: string[];
  warnings: string[];
}

export interface ProcessingFallbackOutput {
  agent_name: string;
  snapshot_id: string | null;
  bias: string | null;
  confidence: number | null;
  summary: string | null;
}

export interface ProcessingFallbackTaskResult {
  task_type: string;
  reason: string;
  status: string;
  fallback_output_agent: string | null;
  fallback_of: string | null;
}

export interface ProcessingFallbackReview {
  status: string;
  fallback_used: boolean;
  accepted_output: string | null;
  manual_review_required: boolean;
  primary_outputs: string[];
  fallback_outputs: ProcessingFallbackOutput[];
  accepted_outputs: Record<string, unknown>;
  task_results: ProcessingFallbackTaskResult[];
  reasons: string[];
  review_items: Array<Record<string, unknown>>;
}

export interface ProcessingQualityGate {
  status: string;
  review_status: string;
  quality_gate_action: string | null;
  publish_allowed: boolean | null;
  manual_review_required: boolean | null;
  fallback_recommended: boolean | null;
  retry_recommended: boolean | null;
  fallback_actions: string[];
  fallback_reasons: string[];
  fallback_review: ProcessingFallbackReview;
  blocking_reasons: string[];
  warnings: string[];
}

export interface ProcessingViewBinding {
  view: string;
  status: "bound" | "missing" | "unknown";
}

export interface ProcessingMatchedEvent {
  event_id: string | null;
  input_id: string | null;
  primary_mainline: string | null;
  processing_trace_id: string | null;
}

export interface ProcessingTraceQuery {
  processing_trace_id?: string;
  event_id?: string;
  input_id?: string;
  source_ref?: string;
  mainline?: string;
  transmission_chain?: string;
}

export interface ProcessingOverviewResponse {
  status: string;
  date: string | null;
  run_id: string | null;
  asset: string;
  generated_from: string | null;
  trace_modes: ProcessingTraceMode[];
  trace_path: ProcessingTracePathNode[];
  input_coverage: ProcessingInputCoverage;
  mainline_coverage: ProcessingMainlineCoverage[];
  transmission_chain_coverage: ProcessingTransmissionChainCoverage[];
  mixed_health: ProcessingMixedHealth;
  source_freshness: ProcessingSourceFreshness;
  source_health: ProcessingSourceHealth;
  quality_gate: ProcessingQualityGate;
  view_bindings: ProcessingViewBinding[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  warnings: string[];
}

export interface ProcessingTraceResponse {
  status: "matched" | "not_found" | "unknown";
  date: string | null;
  run_id: string | null;
  asset: string;
  query: ProcessingTraceQuery;
  matched_event: ProcessingMatchedEvent | null;
  mainlines: string[];
  transmission_chains: string[];
  trace_path: ProcessingTracePathNode[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  view_bindings: ProcessingViewBinding[];
}
