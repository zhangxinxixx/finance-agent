import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";

export type ProcessingTraceMode =
  | "processing_trace_id"
  | "event_id"
  | "source_ref"
  | "input_id"
  | "mainline"
  | "transmission_chain"
  | "artifact_id";

export interface ArtifactSourceRef {
  source_id: string;
  source_name: string;
  source_type: string;
  data_date: string | null;
  endpoint: string | null;
  captured_at: string | null;
  file_path: string | null;
  sha256: string | null;
  url: string | null;
  status: string | null;
}

export interface ArtifactSourceTraceArtifactRef {
  artifact_id: string;
  artifact_type: string;
  file_path: string;
  storage_backend: string | null;
  version: string | null;
  generated_at: string | null;
  sha256: string | null;
}

export interface ArtifactSourceTraceSnapshotRef {
  snapshot_id: string;
  snapshot_type: string;
  data_date: string | null;
  run_id: string | null;
  data_status: string;
  created_at: string | null;
  input_snapshot_ids: string[];
}

export interface ArtifactSourceTraceWarning {
  code: string;
  message: string;
  severity: string;
  field: string | null;
  hint: string | null;
}

/** SourceTraceResponse returned by /api/source-trace/by-artifact/{artifact_id}. */
export interface ArtifactSourceTraceResponse {
  run_id: string | null;
  snapshot_id: string | null;
  data_status: string;
  source_refs: ArtifactSourceRef[];
  artifact_refs: ArtifactSourceTraceArtifactRef[];
  snapshot: ArtifactSourceTraceSnapshotRef | null;
  input_snapshots: ArtifactSourceTraceSnapshotRef[];
  related_artifacts: ArtifactSourceTraceArtifactRef[];
  warnings: ArtifactSourceTraceWarning[];
}

export type ArtifactSourceTraceLookup =
  | { status: "matched"; trace: ArtifactSourceTraceResponse }
  | { status: "not_found"; trace: null };

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

export type KnownProcessingTraceEntityType =
  | "news"
  | "report_input"
  | "event"
  | "analysis_signal";

export type ProcessingTraceEntityType = KnownProcessingTraceEntityType | "unknown";

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
  entity_type: ProcessingTraceEntityType;
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
  warnings: string[];
  missing_data: string[];
  agent_artifact_refs: ProcessingAgentArtifactRef[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  scope: "event" | "run" | "unknown";
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
  source_freshness: Record<string, unknown>;
  mainline_impact: Record<string, unknown>;
  can_build_gold_macro_overview: boolean;
  can_emit_strong_conclusion: boolean;
  blocked_mainlines: string[];
  degraded_mainlines: string[];
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
  fallback_tasks: Array<Record<string, unknown>>;
  task_results: ProcessingFallbackTaskResult[];
  reasons: string[];
  review_items: Array<Record<string, unknown>>;
  fallback_quality_gate_decision: Record<string, unknown>;
  no_strong_conclusion: boolean;
  strategy_card_override: Record<string, unknown>;
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
  agent_loop_decision: Record<string, unknown>;
  fallback_review: ProcessingFallbackReview;
  blocking_reasons: string[];
  warnings: string[];
}

export interface ProcessingViewBinding {
  view: string;
  status: "bound" | "missing" | "unknown";
}

export type ProcessingFinalOutputMode = "accepted" | "observe" | "unavailable";

export interface ProcessingAgentArtifactRef {
  agent_name: string;
  status: string;
  file_path: string;
}

export interface ProcessingTraceHeader {
  trace_id: string | null;
  run_id: string | null;
  entity_type: ProcessingTraceEntityType;
  entity_id: string | null;
  status: string;
  review_status: string;
  publish_allowed: boolean | null;
  as_of: string | null;
}

export interface ProcessingPrimaryOutput {
  scope: "event" | "run" | "unknown";
  agent_name: string | null;
  run_id: string | null;
  snapshot_id: string | null;
  status: string;
  file_path: string | null;
  artifact_refs: ArtifactRef[];
}

export interface ProcessingAgentEnvelope {
  scope: "event" | "run" | "unknown";
  agent_name: string;
  run_id: string | null;
  snapshot_id: string | null;
  status: string;
  confidence: number | null;
  created_at: string | null;
  input_snapshot_ids: Record<string, unknown>;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  evidence_refs: Array<Record<string, unknown>>;
  evidence_items: Array<Record<string, unknown>>;
  data_quality: string[];
  file_path: string | null;
}

export interface ProcessingExecutionUsedData {
  input_snapshot_ids: Record<string, unknown>;
  source_refs: SourceRef[];
  agent_artifact_refs: ProcessingAgentArtifactRef[];
}

export interface ProcessingExecutionFinalOutput {
  mode: ProcessingFinalOutputMode;
  publish_allowed: boolean | null;
  review_status: string;
  report_artifact_refs: ArtifactRef[];
  strategy_card_artifact_refs: ArtifactRef[];
}

export interface ProcessingExecutionSummary {
  status: string;
  failed_steps: string[];
  used_data: ProcessingExecutionUsedData;
  final_output: ProcessingExecutionFinalOutput;
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
  execution_summary: ProcessingExecutionSummary;
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
  trace_header: ProcessingTraceHeader;
  trace_path: ProcessingTracePathNode[];
  source_health: ProcessingSourceHealth;
  quality_gate: ProcessingQualityGate;
  read_time_source_health: ProcessingSourceHealth;
  read_time_warnings: string[];
  read_time_generated_at: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  view_bindings: ProcessingViewBinding[];
  primary_output: ProcessingPrimaryOutput | null;
  fallback_outputs: ProcessingFallbackOutput[];
  accepted_output: Record<string, unknown>;
  accepted_output_source: "primary" | "fallback" | "none" | "unknown";
  fallback_review: ProcessingFallbackReview;
  agent_envelopes: ProcessingAgentEnvelope[];
  input_snapshot_ids: Record<string, unknown>;
  evidence_refs: Array<Record<string, unknown>>;
  evidence_items: Array<Record<string, unknown>>;
  affected_views: string[];
}
