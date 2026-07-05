import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";

export type ProcessingTraceMode =
  | "processing_trace_id"
  | "event_id"
  | "source_ref"
  | "input_id"
  | "mainline"
  | "transmission_chain";

export type ProcessingCoverageStatus = "covered" | "degraded" | "missing" | "stale" | "pass" | "needs_review" | "blocked" | string;

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

export interface ProcessingViewBinding {
  view: string;
  status: "bound" | "missing" | string;
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
  view_bindings: ProcessingViewBinding[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  warnings: string[];
}

export interface ProcessingTraceResponse {
  status: "matched" | "not_found" | string;
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
