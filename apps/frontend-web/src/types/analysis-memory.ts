export type AnalysisStateKind = "accepted_canonical" | "candidate" | "blocked";

export interface AnalysisTransitionView {
  transition_id: string;
  from_state_id: string | null;
  to_state_id: string;
  run_id: string;
  summary: string;
  changes: Array<Record<string, unknown>>;
  evidence_refs: Array<Record<string, unknown>>;
  content_hash: string;
  created_at: string | null;
}

export interface AnalysisStateLineage {
  run_id: string;
  analysis_snapshot_db_id: string | null;
  final_analysis_result_id: string | null;
  accepted_output_snapshot_id: string | null;
  input_snapshot_ids: Record<string, string>;
  source_refs: Array<Record<string, unknown>>;
  artifact_ids: string[];
}

export interface AnalysisStateView {
  state_id: string;
  state_kind: AnalysisStateKind;
  asset: string;
  as_of: string;
  previous_state_id: string | null;
  quality_gate_action: string;
  publish_allowed: boolean;
  accepted_output_source: string;
  accepted_output_agent_name: string | null;
  content_hash: string;
  payload: Record<string, unknown>;
  lineage: AnalysisStateLineage;
  transition: AnalysisTransitionView | null;
  created_at: string | null;
}

export interface CanonicalStateResponse {
  asset: string;
  head_version: number;
  state: AnalysisStateView;
  canonical_chain: AnalysisStateView[];
}

export interface CandidateStatePage {
  asset: string;
  data: AnalysisStateView[];
  pagination: { page: number; page_size: number; total_items: number; total_pages: number };
}

export interface ContextBlockMetadata {
  name: string;
  utf8_bytes: number;
  estimated_tokens: number;
  trim_reasons: string[];
  retained_evidence_ids: string[];
}

export interface ContextBundleMetadata {
  bundle_id: string;
  content_hash: string;
  asset: string;
  run_id: string;
  canonical_state_id: string;
  cutoff_at: string;
  assembled_at: string;
  budget_tokens: number;
  estimated_tokens: number;
  total_utf8_bytes: number;
  within_budget: boolean;
  blocks: ContextBlockMetadata[];
  source_refs: Array<Record<string, unknown>>;
  artifact_path: string;
}

export interface ContextBundleMetadataPage {
  asset: string;
  data: ContextBundleMetadata[];
  pagination: { page: number; page_size: number; total_items: number; total_pages: number };
}

export interface AnalysisMemorySnapshot {
  canonical: CanonicalStateResponse | null;
  candidates: CandidateStatePage;
  bundles: ContextBundleMetadataPage;
  warnings: string[];
}
