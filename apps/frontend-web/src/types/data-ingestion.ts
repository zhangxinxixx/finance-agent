import type { DataStatus, SourceRef } from "@/types/common";
import type { ArtifactRef } from "@/types/artifact";
import type { DataOverallStatus } from "@/types/dashboard";

export type DataIngestionStatus = "ok" | "warn" | "error" | "unavailable";

/* ── 7-stage pipeline health matrix ────────────────────────────────── */

export type PipelineStageKey =
  | "connection"
  | "collect"
  | "rawLanding"
  | "parse"
  | "validate"
  | "snapshot"
  | "consumerReady";

export type PipelineStageStatus =
  | "OK"
  | "WARN"
  | "ERROR"
  | "BLOCKED"
  | "WAITING"
  | "NO_DATA"
  | "PARTIAL"
  | "READY"
  | "NO_SNAPSHOT"
  | "SKIPPED";

export interface StageHealth {
  status: PipelineStageStatus;
  message?: string;
  updatedAt?: string;
  durationMs?: number;
  errorCode?: string;
  inputRef?: string;
  outputRef?: string;
}

export type SourceDomain = "macro" | "liquidity" | "market" | "cme" | "news" | "positioning" | "report";

export type SourcePriority = "PRIMARY" | "FALLBACK" | "DERIVED" | "SUPPLEMENTAL";

export type DownstreamStatus = "READY" | "DEGRADED" | "BLOCKED";

export interface SourcePipelineHealth {
  sourceId: string;
  sourceName: string;
  sourceType: DataSourceAccessType;
  domain: SourceDomain;
  priority: SourcePriority;
  stages: Record<PipelineStageKey, StageHealth>;
  latestRunId?: string;
  snapshotId?: string;
  rawArtifactRef?: string;
  factTable?: string;
  affectedModules: string[];
  downstreamStatus: DownstreamStatus;
  /** Latest date string (YYYY-MM-DD) from raw or parsed timestamps */
  latestDataDate?: string;
  /** Days since latest data (null if no data) */
  stalenessDays?: number | null;
}

export type DataSourceType = "api" | "pdf" | "scrape" | "scraper" | "structured" | "webhook";
export type DataSourceAccessType = DataSourceType | "rss" | "calendar";

export type DataSourceProviderRole = "official_primary" | "fallback" | "supplemental" | "derived" | string;

export interface DataSourceMetadata {
  provider_role: DataSourceProviderRole;
  fallback_for: string[];
  fallback_sources: string[];
  frontend_label?: string;
  notes?: string;
  latest_raw_ref?: DataSourceRawRef | null;
  latest_raw_url?: string | null;
  database_tables?: string[];
  artifact_layers?: string[];
  polling_strategy?: DataSourcePollingStrategy | null;
  pressure_profile?: DataSourcePressureProfile | null;
  [key: string]: unknown;
}

export interface DataSourceRawRef {
  label?: string | null;
  url?: string | null;
  raw_path?: string | null;
  parsed_path?: string | null;
  source_ref?: string | null;
  published_at?: string | null;
}

export interface DataSourcePollingStrategy {
  mode?: string | null;
  cadence?: string | null;
  query?: string | null;
  cache_ttl_seconds?: number | null;
}

export interface DataSourcePressureProfile {
  level?: string | null;
  upgrade_required?: boolean;
  recommendation?: string | null;
}

export interface NewsFeatureSummaryViewModel {
  latest_feature_date?: string | null;
  latest_feature_run_id?: string | null;
  market_mainline_headline?: string | null;
  confirmed_event_count: number;
  candidate_event_count: number;
  unconfirmed_risk_count: number;
  calendar_event_count: number;
  event_candidate_count?: number | null;
  brief_artifact_path?: string | null;
  event_candidates_artifact_path?: string | null;
  impact_assessments_artifact_path?: string | null;
  market_reactions_artifact_path?: string | null;
  report_events_artifact_path?: string | null;
}

export interface NewsSourceRuntimeViewModel {
  collection_diagnostics_artifact_path?: string | null;
  cache_artifact_path?: string | null;
  latest_collection_status?: string | null;
  latest_source_ref_count?: number | null;
  latest_source_ref_statuses: string[];
  latest_reason_codes: string[];
  latest_collection_warnings: string[];
  priority_level?: string | null;
  event_layer?: string | null;
  settings_gate?: string | null;
  generated_at?: string | null;
  classification_model?: string | null;
  classification_version?: string | null;
  classification_provider?: string | null;
  latest_collector_runtime?: {
    collector?: string;
    status?: string;
    items?: number;
    unavailable_feeds?: number;
    warnings: string[];
    error?: string;
  } | null;
}

export type DataSourceArtifactLayer = "raw" | "parsed" | "features" | "analysis";

export interface DataSourceArtifactItem {
  key: string;
  label: string;
  layer: DataSourceArtifactLayer;
  path: string;
}

export interface DataSourceArtifactEvidence {
  preferred_artifact_path?: string | null;
  collector_raw_artifact_path?: string | null;
  collector_parsed_artifact_path?: string | null;
  latest_raw_url?: string | null;
  raw_artifacts: DataSourceArtifactItem[];
  parsed_artifacts: DataSourceArtifactItem[];
  feature_artifacts: DataSourceArtifactItem[];
  analysis_artifacts: DataSourceArtifactItem[];
  news_feature_summary?: NewsFeatureSummaryViewModel | null;
}

export interface DataSourceItem {
  source_key: string;
  source_name: string;
  source_group: string;
  source_type: DataSourceAccessType;
  endpoint: string | null;
  configured: boolean;
  raw_ingested: boolean;
  parsed: boolean;
  analysis_ready: boolean;
  latest_raw_time: string | null;
  latest_parsed_time: string | null;
  latest_update_time?: string | null;
  freshness_status?: string | null;
  freshness_reason?: string | null;
  row_count: number;
  status: DataIngestionStatus;
  error_message: string | null;
  source_refs: string[];
  snapshot_id: string | null;
  last_run_id?: string | null;
  next_run_time?: string | null;
  metadata: DataSourceMetadata;
  affected_modules: string[];
  artifact_evidence?: DataSourceArtifactEvidence | null;
  pipeline_health?: SourcePipelineHealth | null;
}

export interface DataSourceStatuses {
  generated_at: string;
  last_refresh_at: string | null;
  sources: DataSourceItem[];
}

export interface DataIngestionPipelineStage {
  key: "configured" | "raw_ingested" | "parsed" | "analysis_ready";
  label: string;
  status: "done" | "running" | "pending" | "unavailable";
  description: string;
}

export interface DataIngestionSummary {
  generated_at: string;
  source_count: number;
  configured_count: number;
  raw_ingested_count: number;
  parsed_count: number;
  analysis_ready_count: number;
  status_counts: Record<DataIngestionStatus, number>;
  source_groups: Array<{
    group: string;
    count: number;
  }>;
  pipeline: {
    configured: "done" | "running" | "pending" | "unavailable";
    raw_ingested: "done" | "running" | "pending" | "unavailable";
    parsed: "done" | "running" | "pending" | "unavailable";
    analysis_ready: "done" | "running" | "pending" | "unavailable";
  };
  source_trace: Array<{
    name: string;
    trade_date: string;
    file: string;
    snapshot_id: string | null;
    source_ref: string;
    endpoint?: string | null;
    latest_raw_time?: string | null;
    latest_parsed_time?: string | null;
    model_version?: string | null;
    status: "ok" | "warn" | "error" | "unavailable";
  }>;
}

export interface DataIngestionMockFile {
  default_source_group: string;
  summary: DataIngestionSummary;
  statuses: DataSourceStatuses;
}

export type DataIngestionResponseSource = "api" | "mock" | "unavailable";

export interface DataIngestionResponse {
  summary: DataIngestionSummary;
  statuses: DataSourceStatuses;
  has_data: boolean;
  source: DataIngestionResponseSource;
  error_reason?: string | null;
  view_model: DataIngestionViewModel;
}

export interface DataStatusSummaryViewModel {
  status: DataStatus;
  label: string;
  source_count: number;
  generated_at: string;
  available_count: number;
  partial_count: number;
  unavailable_count: number;
  error_count: number;
  updated_at?: string | null;
  source_refs: SourceRef[];
  source_groups: Array<{
    group: string;
    count: number;
  }>;
}

export interface DataSourceStatusViewModel {
  id: string;
  label: string;
  group: string;
  type: DataSourceAccessType;
  role: DataSourceProviderRole;
  status: DataStatus;
  raw_status: DataIngestionStatus;
  endpoint?: string | null;
  configured: boolean;
  raw_ingested: boolean;
  parsed: boolean;
  analysis_ready: boolean;
  latest_raw_time?: string | null;
  latest_parsed_time?: string | null;
  latest_update_time?: string | null;
  freshness_status?: string | null;
  freshness_reason?: string | null;
  row_count: number;
  error_message?: string | null;
  status_reason?: string | null;
  snapshot_id?: string | null;
  last_run_id?: string | null;
  next_run_time?: string | null;
  fallback_for: string[];
  fallback_sources: string[];
  notes?: string;
  latest_raw_ref?: DataSourceRawRef | null;
  latest_raw_url?: string | null;
  database_tables: string[];
  artifact_layers: string[];
  polling_strategy?: DataSourcePollingStrategy | null;
  pressure_profile?: DataSourcePressureProfile | null;
  artifact_evidence: DataSourceArtifactEvidence | null;
  news_runtime?: NewsSourceRuntimeViewModel | null;
  source_refs: SourceRef[];
  /** 7-stage pipeline health for the health matrix view */
  pipeline_health: SourcePipelineHealth;
}

type RequireDataSourceReadModelFields<T extends {
  artifact_evidence: DataSourceArtifactEvidence | null;
  pipeline_health: SourcePipelineHealth;
}> = T;

type _DataSourceStatusViewModelReadModelContract = RequireDataSourceReadModelFields<DataSourceStatusViewModel>;

export interface PipelineLayerStatus {
  id: "configured" | "raw_ingested" | "parsed" | "analysis_ready";
  label: string;
  status: DataStatus;
  completed_count: number;
  total_count: number;
  source_refs: SourceRef[];
}

export interface DataIngestionSystemStatusViewModel {
  overall_status: DataOverallStatus;
  latest_run_id: string | null;
  latest_run_status: string | null;
  latest_run_created_at: string | null;
  latest_run_trade_date: string | null;
  snapshot_id: string | null;
  data_date: string | null;
  missing_sources: string[];
  stale_sources: string[];
}

export interface DataIngestionViewModel {
  status: DataStatus;
  updated_at?: string | null;
  summary: DataStatusSummaryViewModel | null;
  system_status: DataIngestionSystemStatusViewModel | null;
  sources: DataSourceStatusViewModel[];
  layers: PipelineLayerStatus[];
  source_refs: SourceRef[];
}

export interface DataSourceActionRequest {
  actor?: string;
  reason?: string;
  request_id?: string;
}

export interface DataSourceActionResponse {
  status: "accepted" | "success" | "partial" | "manual_required" | "queued_not_implemented" | "error" | string;
  action: string;
  source_key: string;
  run_id?: string | null;
  audit_id?: string | null;
  data_status?: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
}

export interface DataSourceTestRequest extends DataSourceActionRequest {
  limit?: number;
}

export interface DataSourceTestResponse {
  status: "ok" | "schema_changed" | "manual_required" | "login_required" | "no_latest_artifact" | "failed" | string;
  action: "test" | string;
  source_key: string;
  run_id?: string | null;
  audit_id?: string | null;
  duration_ms: number;
  data_status?: string | null;
  summary: Record<string, unknown>;
  preview: Array<Record<string, unknown>>;
  artifacts: {
    raw_path?: string | null;
    parsed_path?: string | null;
    [key: string]: string | null | undefined;
  };
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
}
