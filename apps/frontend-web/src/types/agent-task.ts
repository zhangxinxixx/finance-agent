import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, SourceRef } from "@/types/common";

export type TaskRunStatus =
  | "queued"
  | "running"
  | "success"
  | "partial_success"
  | "failed"
  | "retrying"
  | "skipped"
  | "degraded"
  | "needs_review"
  | "cancelled"
  | string;

export interface ApiTaskArtifactRef {
  artifact_id: string;
  artifact_type: string;
  file_path: string;
  version?: string | null;
  generated_at?: string | null;
  sha256?: string | null;
}

export interface ApiTaskSourceRef {
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

export interface ApiTaskStepResponse {
  run_id?: string | null;
  snapshot_id?: string | null;
  data_status?: string;
  source_refs: ApiTaskSourceRef[];
  artifact_refs: ApiTaskArtifactRef[];
  warnings?: Array<Record<string, unknown>>;
  step_id: string;
  task_name: string;
  stage?: string | null;
  task_kind?: string | null;
  status: TaskRunStatus;
  progress?: number | null;
  input_refs: ApiTaskArtifactRef[];
  output_refs: ApiTaskArtifactRef[];
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;
  retry_count?: number;
  error_type?: string | null;
  error_message?: string | null;
}

export interface ApiTaskRunResponse {
  run_id?: string | null;
  snapshot_id?: string | null;
  data_status?: string;
  source_refs: ApiTaskSourceRef[];
  artifact_refs: ApiTaskArtifactRef[];
  warnings?: Array<Record<string, unknown>>;
  task_id: string;
  task_type: string;
  workspace_id?: string | null;
  trading_date?: string | null;
  status: TaskRunStatus;
  current_stage?: string | null;
  progress?: number | null;
  started_at?: string | null;
  ended_at?: string | null;
  total_cost_usd?: number | null;
  token_in?: number | null;
  token_out?: number | null;
  final_result_id?: string | null;
  error_summary?: string | null;
  steps: ApiTaskStepResponse[];
}

export interface ApiTaskRunsResponse {
  runs: ApiTaskRunResponse[];
}

export interface ApiTaskRunArtifactsResponse {
  run_id: string;
  artifacts: ApiTaskArtifactRef[];
}

export interface ApiTaskRunLogsResponse {
  run_id: string;
  logs: ApiTaskStepResponse[];
}

export interface ApiTaskRunEventResponse {
  id: string;
  run_id: string;
  task_id?: string | null;
  event_type: string;
  payload?: Record<string, unknown>;
  created_at?: string | null;
}

export interface ApiTaskRunEventsResponse {
  run_id: string;
  events: ApiTaskRunEventResponse[];
}

export interface ApiReviewItem {
  review_id: string;
  run_id?: string | null;
  source_module: string;
  source_step_id?: string | null;
  agent_output_id?: string | null;
  claim_id?: string | null;
  impact_report_ids?: string[];
  source_refs?: Array<ApiTaskSourceRef | SourceRef>;
  severity: string;
  reason: string;
  impact_modules: string[];
  evidence_refs: ApiTaskArtifactRef[];
  suggested_action?: string | null;
  status: string;
  resolution_action?: string | null;
  resolution_note?: string | null;
  resolution_actor?: string | null;
  resolution_request_id?: string | null;
  audit_id?: string | null;
  action_status?: string | null;
  next_run_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  resolved_at?: string | null;
}

export interface ApiReviewsResponse {
  reviews: ApiReviewItem[];
  total: number;
}

export interface TaskLogViewModel {
  task_id: string;
  step_id?: string;
  lines: string[];
  status: DataStatus;
}

export interface TaskRunEventViewModel {
  id: string;
  created_at?: string | null;
  event_type: string;
  task_id?: string | null;
  payload: Record<string, unknown>;
}

export interface TaskStepViewModel {
  id: string;
  label: string;
  stage?: string | null;
  task_kind?: string | null;
  status: TaskRunStatus;
  progress?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  retry_count: number;
  failure_reason?: string | null;
  error_type?: string | null;
  logs_available: boolean;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  input_refs: ArtifactRef[];
  output_refs: ArtifactRef[];
}

export interface TaskRunSummaryViewModel {
  id: string;
  run_id: string;
  task_type: string;
  status: TaskRunStatus;
  current_stage?: string | null;
  progress?: number | null;
  trading_date?: string | null;
  snapshot_id?: string | null;
  final_result_id?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  error_summary?: string | null;
}

export interface TaskRunViewModel extends TaskRunSummaryViewModel {
  workspace_id?: string | null;
  total_cost_usd?: number | null;
  token_in?: number | null;
  token_out?: number | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  steps: TaskStepViewModel[];
  events: TaskRunEventViewModel[];
  logs: TaskLogViewModel[];
  asOf?: string | null;
  dataDate?: string | null;
}

export interface TaskReviewViewModel {
  review_id: string;
  run_id?: string | null;
  source_module: string;
  source_step_id?: string | null;
  agent_output_id?: string | null;
  claim_id?: string | null;
  impact_report_ids: string[];
  source_refs: SourceRef[];
  severity: string;
  reason: string;
  impact_modules: string[];
  evidence_refs: ArtifactRef[];
  suggested_action?: string | null;
  status: string;
  resolution_action?: string | null;
  resolution_note?: string | null;
  resolution_actor?: string | null;
  resolution_request_id?: string | null;
  audit_id?: string | null;
  action_status?: string | null;
  next_run_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AgentInspectionPrompt {
  kind: "llm" | "rule" | string;
  prompt_id?: string | null;
  version?: string | null;
  checksum?: string | null;
  source_file?: string | null;
  available: boolean;
  messages: Array<{ role: string; content: string }>;
  note?: string | null;
}

export interface AgentInspectionItem {
  agent_output_id?: string | null;
  agent_name: string;
  display_name?: string;
  registry_id?: string | null;
  role?: string;
  module: string;
  version: string;
  run_id: string;
  snapshot_id: string;
  status: string;
  bias: string;
  confidence: number;
  prompt_version_id?: string | null;
  created_at?: string | null;
  prompt: AgentInspectionPrompt;
  input: {
    input_snapshot_ids: Record<string, unknown>;
    source_refs: Array<Record<string, unknown>>;
    payload: unknown;
  };
  output: {
    summary: string;
    summary_zh?: string;
    key_findings: string[];
    risk_points: string[];
    watchlist: string[];
    invalid_conditions: string[];
    prompt_id?: string | null;
    prompt_version?: string | null;
    prompt_checksum?: string | null;
    prompt_source_file?: string | null;
    payload: unknown;
    llm_raw_output?: string | null;
  };
  llm: {
    model?: string | null;
    usage?: Record<string, unknown> | null;
    elapsed_seconds?: number | null;
  };
}

export interface AgentInspectionViewModel {
  trade_date?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  agents: AgentInspectionItem[];
  source: string;
}

export interface AgentTasksViewModel {
  status: DataStatus;
  source: "api" | "mock" | "unavailable";
  updated_at: string;
  runs: TaskRunSummaryViewModel[];
  selected_run_id?: string | null;
  selected_run: TaskRunViewModel | null;
  detail_error?: string | null;
  reviews: TaskReviewViewModel[];
  reviews_total: number;
  agent_inspection?: AgentInspectionViewModel | null;
  source_refs: SourceRef[];
  has_data: boolean;
}

export interface AgentTasksMockFile {
  runs: ApiTaskRunResponse[];
  run_artifacts?: Record<string, ApiTaskRunArtifactsResponse>;
  run_logs?: Record<string, ApiTaskRunLogsResponse>;
  run_events?: Record<string, ApiTaskRunEventsResponse>;
  reviews?: ApiReviewsResponse;
}
