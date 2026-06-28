import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, ReportFormat, ReportMeta, SourceRef } from "@/types/common";
import type { SourceTracePayload } from "@/types/source-trace";

export type ReportType = "final_report" | "strategy_card" | "options_report" | "macro_report" | string;
export type ReportFamily = "cme_options_visual" | "final_report_markdown" | "options_report_markdown" | "jin10_daily_visual" | "jin10_weekly_visual";

export interface ReportIndexItem {
  type: ReportType;
  trade_date: string;
  run_id: string | null;
  generated_at?: string | null;
  report_id?: string | null;
  family?: string | null;
  title?: string | null;
  format: string;
  available: boolean;
}

export interface ReportsIndexResponse {
  asset: string;
  reports: ReportIndexItem[];
}

export interface ReportDateItem {
  trade_date: string;
  modules: string[];
  latest_run_id: string | null;
  has_final_report: boolean;
  has_strategy_card: boolean;
}

export interface ReportsDatesResponse {
  asset: string;
  dates: ReportDateItem[];
  total_dates: number;
}

export interface FinalReportResponse {
  asset: string;
  trade_date: string;
  run_id: string;
  content: string;
  format?: string;
}

export interface VisualReportResponse {
  article_id?: string;
  asset?: string;
  trade_date: string;
  run_id: string;
  title?: string;
  content: string;
  format: string;
  path?: string;
  source_url?: string;
}

export interface ReportSelection {
  type?: ReportType;
  family?: ReportFamily;
  date?: string | null;
  run_id?: string | null;
}

export interface FinalReportView extends FinalReportResponse {
  report_type: ReportType;
  source_endpoint: string;
  content_length: number;
  warning_count: number;
}

export interface VisualReportView extends VisualReportResponse {
  report_family: ReportFamily;
  source_endpoint: string;
}

export type Jin10Subview = "agent_analysis" | "daily_visual" | "raw_article";

export interface Jin10ArtifactView {
  kind: "markdown" | "html";
  available: boolean;
  content?: string;
  path?: string;
  asset_base_url?: string;
}

export interface Jin10QualityAuditReason {
  code: string;
  message?: string;
}

export interface Jin10QualityAudit {
  status: "accepted" | "needs_review" | "rejected" | string;
  checked_at?: string | null;
  reasons: Jin10QualityAuditReason[];
  reason_codes: string[];
}

export interface Jin10ReportBundleResponse {
  asset: string;
  trade_date: string;
  run_id: string;
  article_id?: string;
  title?: string;
  source_url?: string;
  default_view: Jin10Subview;
  views: Record<Jin10Subview, Jin10ArtifactView>;
  quality_audit?: Jin10QualityAudit | null;
}

export interface Jin10ReportBundleView extends Jin10ReportBundleResponse {
  report_family: "jin10_daily_visual";
  source_endpoint: string;
}

/** Jin10 周报 API 返回结构 (/api/jin10/weekly-report/*) */
export interface Jin10WeeklyReportResponse {
  article_id: string;
  date: string;
  title: string;
  report_type: string;
  category: string;
  source_url: string;
  image_count?: number;
  content: string;
  format: string;
}

export interface Jin10WeeklyReportView extends Jin10WeeklyReportResponse {
  report_family: "jin10_weekly_visual";
  source_endpoint: string;
}

export interface ReportWarningItem {
  code: string;
  message: string;
  severity?: string;
  field?: string | null;
  hint?: string | null;
}

export interface BackendSourceRef {
  source_id: string;
  source_name: string;
  source_type: string;
  data_date?: string | null;
  endpoint?: string | null;
  captured_at?: string | null;
  file_path?: string | null;
  sha256?: string | null;
  url?: string | null;
  status?: string | null;
}

export interface BackendArtifactRef {
  artifact_id: string;
  artifact_type: string;
  file_path: string;
  version?: string | null;
  generated_at?: string | null;
  sha256?: string | null;
}

export interface ReportArtifactResponse extends BackendArtifactRef {
  label?: string | null;
  content_type?: string | null;
  report_id?: string | null;
  is_primary?: boolean;
}

export interface BackendSnapshotRef {
  snapshot_id: string;
  snapshot_type: string;
  data_date?: string | null;
  run_id?: string | null;
  data_status?: string | null;
  created_at?: string | null;
  input_snapshot_ids?: string[];
}

export interface ReportDeterministicInputResponse {
  input_id: string;
  input_type: string;
  title: string;
  data_status: string;
  snapshot?: BackendSnapshotRef | null;
  sections: string[];
  source_refs: BackendSourceRef[];
  artifact_refs: BackendArtifactRef[];
  payload?: Record<string, unknown> | null;
}

export interface ReportAnalysisAgentOutputResponse {
  agent_output_id: string;
  registry_id?: string | null;
  agent_name: string;
  display_name: string;
  role: string;
  module: string;
  version: string;
  run_id?: string | null;
  snapshot_id?: string | null;
  status: string;
  bias: string;
  confidence: number;
  summary: string;
  summary_zh: string;
  key_findings: string[];
  risk_points: string[];
  watchlist: string[];
  invalid_conditions: string[];
  source_refs: BackendSourceRef[];
  artifact_refs: BackendArtifactRef[];
  claim_count: number;
  fact_review_status?: string | null;
  prompt_version?: string | null;
  generated_by?: string | null;
  llm_model?: string | null;
  created_at?: string | null;
}

export interface ReportAnalysisInputsResponse {
  report_id: string;
  family?: string | null;
  title?: string | null;
  asset?: string | null;
  trade_date?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  data_status: string;
  source_refs: BackendSourceRef[];
  artifact_refs: BackendArtifactRef[];
  warnings: ReportWarningItem[];
  deterministic_inputs: ReportDeterministicInputResponse[];
  agent_outputs: ReportAnalysisAgentOutputResponse[];
  fact_reviews: ReportAnalysisAgentOutputResponse[];
  synthesis_outputs: ReportAnalysisAgentOutputResponse[];
}

export interface ReportDetailResponse {
  run_id?: string | null;
  snapshot_id?: string | null;
  data_status: string;
  source_refs: BackendSourceRef[];
  artifact_refs: BackendArtifactRef[];
  warnings: ReportWarningItem[];
  report_id: string;
  family: string;
  title: string;
  asset?: string | null;
  trade_date?: string | null;
  lifecycle_status: string;
  review_status?: string;
  generated_at?: string | null;
  artifacts: ReportArtifactResponse[];
  input_snapshot_ids: string[];
  review_items: Array<Record<string, unknown>>;
  structured_payload?: Record<string, unknown> | null;
}

export interface ReportArtifactPayloadResponse {
  report_id: string;
  artifact_id: string;
  artifact_type: string;
  content_type?: string | null;
  path?: string | null;
  asset_base_url?: string | null;
  content: unknown;
}

export type ReportArtifactTabKey = "analysis" | "source" | "visual" | "evidence";
export type ReportDetailTabKey = ReportArtifactTabKey | "inputs";

export interface ReportArtifactContentView {
  key: ReportArtifactTabKey;
  label: string;
  available: boolean;
  artifact_type?: string | null;
  content_type?: string | null;
  format: ReportFormat;
  content: string;
  path?: string | null;
  asset_base_url?: string | null;
  source_endpoint: string;
}

export interface ReportDetailMeta extends ReportMeta {
  report_id: string;
  family: string;
  title: string;
  lifecycle_status: string;
  review_status?: string;
  input_snapshot_ids: string[];
  warning_count: number;
  artifact_count: number;
}

export interface ReportAnalysisInputItemView {
  input_id: string;
  input_type: string;
  title: string;
  data_status: DataStatus;
  snapshot_id?: string | null;
  run_id?: string | null;
  snapshot_type?: string | null;
  trade_date?: string | null;
  created_at?: string | null;
  input_snapshot_ids: string[];
  sections: string[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  payload?: Record<string, unknown> | null;
}

export interface ReportAnalysisAgentOutputView {
  agent_output_id: string;
  registry_id?: string | null;
  agent_name: string;
  display_name: string;
  role: string;
  module: string;
  version: string;
  run_id?: string | null;
  snapshot_id?: string | null;
  status: DataStatus;
  bias: string;
  confidence: number;
  summary: string;
  summary_zh: string;
  key_findings: string[];
  risk_points: string[];
  watchlist: string[];
  invalid_conditions: string[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  claim_count: number;
  fact_review_status?: string | null;
  prompt_version?: string | null;
  generated_by?: string | null;
  llm_model?: string | null;
  created_at?: string | null;
}

export interface ReportAnalysisInputsView {
  report_id: string;
  family?: string | null;
  title?: string | null;
  asset?: string | null;
  trade_date?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  source_endpoint?: string;
  data_status: DataStatus;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  warnings: ReportWarningItem[];
  deterministic_inputs: ReportAnalysisInputItemView[];
  agent_outputs: ReportAnalysisAgentOutputView[];
  fact_reviews: ReportAnalysisAgentOutputView[];
  synthesis_outputs: ReportAnalysisAgentOutputView[];
}

export interface ReportDetailView {
  report_id: string;
  meta: ReportDetailMeta;
  data_status: DataStatus;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  warnings: ReportWarningItem[];
  source_trace: SourceTracePayload | null;
  analysis_inputs: ReportAnalysisInputsView | null;
  tabs: Partial<Record<ReportArtifactTabKey, ReportArtifactContentView>>;
  available_tabs: ReportDetailTabKey[];
  structured_payload?: Record<string, unknown> | null;
}
