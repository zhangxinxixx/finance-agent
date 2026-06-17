import { ApiError, fetchJson } from "@/adapters/apiClient";
import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef, DataStatus } from "@/types/common";
import type {
  AgentInspectionViewModel,
  AgentTasksMockFile,
  AgentTasksViewModel,
  ApiReviewItem,
  ApiReviewsResponse,
  ApiTaskArtifactRef,
  ApiTaskRunArtifactsResponse,
  ApiTaskRunLogsResponse,
  ApiTaskRunResponse,
  ApiTaskRunsResponse,
  ApiTaskSourceRef,
  ApiTaskStepResponse,
  TaskLogViewModel,
  TaskReviewViewModel,
  TaskRunSummaryViewModel,
  TaskRunViewModel,
  TaskStepViewModel,
  TaskRunStatus,
} from "@/types/agent-task";
import { formatDateTime } from "@/lib/date";
import { mergeDataStatus, normalizeDataStatus } from "@/lib/status";

const AGENT_RUNS_PATH = "/api/runs";
const REVIEWS_PATH = "/api/reviews";
const AGENT_ANALYSIS_INSPECT_PATH = "/api/agent-analysis/inspect";
const AGENT_TASKS_MOCK_URL = new URL("../mocks/agent-runs.json", import.meta.url);

function taskStatusToDataStatus(status: TaskRunStatus): DataStatus {
  const value = String(status ?? "").toLowerCase();
  if (value === "success") return "available";
  if (value === "failed") return "error";
  if (value === "queued" || value === "cancelled" || value === "skipped") return "unavailable";
  return "partial";
}

function mapSourceRef(source: ApiTaskSourceRef): SourceRef {
  return {
    source_ref: source.source_name || source.source_id,
    label: source.source_name,
    endpoint: source.endpoint,
    artifact_path: source.file_path,
    trade_date: source.data_date,
    dataDate: source.data_date,
    asOf: source.captured_at,
    generated_at: source.captured_at,
    provider: source.source_type,
    source_url: source.url,
    status: normalizeDataStatus(source.status),
  };
}

function mapArtifactRef(artifact: ApiTaskArtifactRef): ArtifactRef {
  return {
    artifact_id: artifact.artifact_id,
    artifact_type: artifact.artifact_type,
    file_path: artifact.file_path,
    path: artifact.file_path,
    asOf: artifact.generated_at,
  };
}

function mapReviewSourceRef(source: ApiTaskSourceRef | SourceRef): SourceRef {
  if ("source_id" in source || "source_name" in source || "source_type" in source) {
    return mapSourceRef(source as ApiTaskSourceRef);
  }

  return {
    source_ref: source.source_ref,
    label: source.label ?? source.source_ref,
    endpoint: source.endpoint ?? null,
    artifact_path: source.artifact_path ?? null,
    snapshot_id: source.snapshot_id ?? null,
    input_snapshot_ids: source.input_snapshot_ids ?? null,
    trade_date: source.trade_date ?? source.dataDate ?? null,
    dataDate: source.dataDate ?? source.trade_date ?? null,
    asOf: source.asOf ?? source.generated_at ?? null,
    run_id: source.run_id ?? null,
    generated_at: source.generated_at ?? source.asOf ?? null,
    provider: source.provider ?? null,
    status: normalizeDataStatus(source.status),
    source_url: source.source_url ?? null,
  };
}

function mapTaskStep(step: ApiTaskStepResponse): TaskStepViewModel {
  const outputRefs = (step.output_refs ?? []).map(mapArtifactRef);
  const artifactRefs = (step.artifact_refs ?? []).map(mapArtifactRef);
  return {
    id: step.step_id,
    label: step.task_name,
    stage: step.stage ?? null,
    task_kind: step.task_kind ?? null,
    status: step.status,
    progress: step.progress ?? null,
    started_at: step.started_at ?? null,
    finished_at: step.ended_at ?? null,
    duration_ms: step.duration_ms ?? null,
    retry_count: step.retry_count ?? 0,
    failure_reason: step.error_message ?? null,
    error_type: step.error_type ?? null,
    logs_available: Boolean(step.error_message || step.started_at || step.ended_at),
    source_refs: (step.source_refs ?? []).map(mapSourceRef),
    artifact_refs: artifactRefs,
    input_refs: (step.input_refs ?? []).map(mapArtifactRef),
    output_refs: outputRefs,
  };
}

function mapTaskLogs(runId: string, logs: ApiTaskStepResponse[]): TaskLogViewModel[] {
  return (logs ?? []).map((step) => {
    const lines = [
      `${step.task_name}${step.stage ? ` · ${step.stage}` : ""} · ${step.status}`,
      step.started_at ? `started_at ${formatDateTime(step.started_at)}` : null,
      step.ended_at ? `ended_at ${formatDateTime(step.ended_at)}` : null,
      step.retry_count ? `retry_count ${step.retry_count}` : null,
      step.error_message ? `error ${step.error_message}` : null,
    ].filter((value): value is string => Boolean(value));

    return {
      task_id: runId,
      step_id: step.step_id,
      lines,
      status: taskStatusToDataStatus(step.status),
    };
  });
}

function mapTaskRunSummary(run: ApiTaskRunResponse): TaskRunSummaryViewModel {
  const runId = run.run_id ?? run.task_id;
  return {
    id: runId,
    run_id: runId,
    task_type: run.task_type,
    status: run.status,
    current_stage: run.current_stage ?? null,
    progress: run.progress ?? null,
    trading_date: run.trading_date ?? null,
    snapshot_id: run.snapshot_id ?? null,
    final_result_id: run.final_result_id ?? null,
    started_at: run.started_at ?? null,
    ended_at: run.ended_at ?? null,
    error_summary: run.error_summary ?? null,
  };
}

function mapTaskRunDetail(
  run: ApiTaskRunResponse,
  artifactsOverride?: ApiTaskRunArtifactsResponse | null,
  logsOverride?: ApiTaskRunLogsResponse | null,
): TaskRunViewModel {
  const runId = run.run_id ?? run.task_id;
  const artifactRefs = artifactsOverride?.artifacts?.length
    ? artifactsOverride.artifacts.map(mapArtifactRef)
    : (run.artifact_refs ?? []).map(mapArtifactRef);
  const steps = (run.steps ?? []).map(mapTaskStep);
  const logs = mapTaskLogs(runId, logsOverride?.logs ?? run.steps ?? []);

  return {
    ...mapTaskRunSummary(run),
    workspace_id: run.workspace_id ?? null,
    total_cost_usd: run.total_cost_usd ?? null,
    token_in: run.token_in ?? null,
    token_out: run.token_out ?? null,
    source_refs: (run.source_refs ?? []).map(mapSourceRef),
    artifact_refs: artifactRefs,
    steps,
    logs,
    asOf: run.ended_at ?? run.started_at ?? null,
    dataDate: run.trading_date ?? null,
  };
}

function mapReview(item: ApiReviewItem): TaskReviewViewModel {
  return {
    review_id: item.review_id,
    run_id: item.run_id ?? null,
    source_module: item.source_module,
    source_step_id: item.source_step_id ?? null,
    agent_output_id: item.agent_output_id ?? null,
    claim_id: item.claim_id ?? null,
    impact_report_ids: item.impact_report_ids ?? [],
    source_refs: (item.source_refs ?? []).map(mapReviewSourceRef),
    severity: item.severity,
    reason: item.reason,
    impact_modules: item.impact_modules ?? [],
    evidence_refs: (item.evidence_refs ?? []).map(mapArtifactRef),
    suggested_action: item.suggested_action ?? null,
    status: item.status,
    resolution_action: item.resolution_action ?? null,
    resolution_note: item.resolution_note ?? null,
    resolution_actor: item.resolution_actor ?? null,
    resolution_request_id: item.resolution_request_id ?? null,
    audit_id: item.audit_id ?? null,
    action_status: item.action_status ?? null,
    next_run_id: item.next_run_id ?? null,
    created_at: item.created_at ?? null,
    updated_at: item.updated_at ?? null,
  };
}

async function fetchMockFile(): Promise<AgentTasksMockFile> {
  const response = await fetch(AGENT_TASKS_MOCK_URL);
  if (!response.ok) {
    throw new Error(`加载 Agent Tasks mock 失败 (${response.status})`);
  }
  return response.json() as Promise<AgentTasksMockFile>;
}

async function fetchOptionalJson<T>(path: string): Promise<T | null> {
  try {
    return await fetchJson<T>(path);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      return null;
    }
    throw cause;
  }
}

async function fetchRunList(): Promise<ApiTaskRunResponse[]> {
  const payload = await fetchJson<ApiTaskRunsResponse>(`${AGENT_RUNS_PATH}?limit=20`);
  return payload.runs ?? [];
}

function hasRefs<T>(items: T[] | null | undefined): boolean {
  return Boolean(items && items.length > 0);
}

function isTraceableStep(step: ApiTaskStepResponse): boolean {
  return Boolean(
    step.snapshot_id ||
      hasRefs(step.source_refs) ||
      hasRefs(step.artifact_refs) ||
      hasRefs(step.input_refs) ||
      hasRefs(step.output_refs),
  );
}

function isTraceableRun(run: ApiTaskRunResponse): boolean {
  return Boolean(
    run.snapshot_id ||
      run.final_result_id ||
      hasRefs(run.source_refs) ||
      hasRefs(run.artifact_refs) ||
      (run.steps ?? []).some(isTraceableStep),
  );
}

async function fetchRunDetail(runId: string): Promise<ApiTaskRunResponse | null> {
  return fetchOptionalJson<ApiTaskRunResponse>(`${AGENT_RUNS_PATH}/${runId}`);
}

async function fetchRunArtifacts(runId: string): Promise<ApiTaskRunArtifactsResponse | null> {
  return fetchOptionalJson<ApiTaskRunArtifactsResponse>(`${AGENT_RUNS_PATH}/${runId}/artifacts`);
}

async function fetchRunLogs(runId: string): Promise<ApiTaskRunLogsResponse | null> {
  return fetchOptionalJson<ApiTaskRunLogsResponse>(`${AGENT_RUNS_PATH}/${runId}/logs`);
}

async function fetchReviews(runId?: string | null): Promise<ApiReviewsResponse | null> {
  const search = new URLSearchParams({ status: "pending", limit: "20" });
  if (runId) {
    search.set("run_id", runId);
  }
  return fetchOptionalJson<ApiReviewsResponse>(`${REVIEWS_PATH}?${search.toString()}`);
}

async function fetchAgentInspection(runId?: string | null): Promise<AgentInspectionViewModel | null> {
  const search = new URLSearchParams();
  if (runId) {
    search.set("run_id", runId);
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  const payload = await fetchOptionalJson<AgentInspectionViewModel>(`${AGENT_ANALYSIS_INSPECT_PATH}${suffix}`);
  if (runId && payload && payload.agents.length === 0) {
    return fetchOptionalJson<AgentInspectionViewModel>(AGENT_ANALYSIS_INSPECT_PATH);
  }
  return payload;
}

export async function fetchReviewCenterReviews(params: {
  status?: string;
  sourceModule?: string;
  runId?: string;
  limit?: number;
} = {}): Promise<{ reviews: TaskReviewViewModel[]; total: number; source: "api" | "unavailable" }> {
  const search = new URLSearchParams({
    limit: String(params.limit ?? 100),
  });
  if (params.status) search.set("status", params.status);
  if (params.sourceModule) search.set("source_module", params.sourceModule);
  if (params.runId) search.set("run_id", params.runId);

  const payload = await fetchJson<ApiReviewsResponse>(`${REVIEWS_PATH}?${search.toString()}`);
  return {
    reviews: (payload.reviews ?? []).map(mapReview),
    total: payload.total ?? 0,
    source: "api",
  };
}

function dedupeSourceRefs(refs: SourceRef[]): SourceRef[] {
  const seen = new Set<string>();
  const output: SourceRef[] = [];
  for (const ref of refs) {
    const key = `${ref.source_ref}|${ref.snapshot_id ?? ""}|${ref.artifact_path ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(ref);
  }
  return output;
}

function buildViewModel({
  source,
  runs,
  selectedRun,
  selectedRunId,
  reviews,
  agentInspection,
  detailError,
}: {
  source: AgentTasksViewModel["source"];
  runs: ApiTaskRunResponse[];
  selectedRun: TaskRunViewModel | null;
  selectedRunId?: string | null;
  reviews: ApiReviewsResponse | null;
  agentInspection?: AgentInspectionViewModel | null;
  detailError?: string | null;
}): AgentTasksViewModel {
  const runSummaries = runs.map(mapTaskRunSummary);
  const pageRefs = dedupeSourceRefs([
    ...runs.flatMap((run) => (run.source_refs ?? []).map(mapSourceRef)),
    ...(selectedRun?.source_refs ?? []),
  ]);
  const pageStatus = source === "unavailable"
    ? "unavailable"
    : mergeDataStatus([
        source === "mock" ? "partial" : "available",
        detailError ? "partial" : "available",
        selectedRun ? taskStatusToDataStatus(selectedRun.status) : runs.length === 0 ? "available" : "partial",
      ]);

  return {
    status: pageStatus,
    source,
    updated_at: new Date().toISOString(),
    runs: runSummaries,
    selected_run_id: selectedRunId ?? null,
    selected_run: selectedRun,
    detail_error: detailError ?? null,
    reviews: (reviews?.reviews ?? []).map(mapReview),
    reviews_total: reviews?.total ?? 0,
    agent_inspection: agentInspection ?? null,
    source_refs: pageRefs,
    has_data: runs.length > 0,
  };
}

export async function fetchAgentTasksView(selectedRunId?: string | null): Promise<AgentTasksViewModel> {
  try {
    const runs = (await fetchRunList()).filter(isTraceableRun);
    const effectiveRunId = selectedRunId && runs.some((run) => (run.run_id ?? run.task_id) === selectedRunId)
      ? selectedRunId
      : (runs[0]?.run_id ?? runs[0]?.task_id ?? null);
    const [reviews, agentInspection] = await Promise.all([
      fetchReviews(effectiveRunId),
      fetchAgentInspection(effectiveRunId),
    ]);

    let selectedRun: TaskRunViewModel | null = null;
    let detailError: string | null = null;

    if (effectiveRunId) {
      const [detail, artifacts, logs] = await Promise.all([
        fetchRunDetail(effectiveRunId),
        fetchRunArtifacts(effectiveRunId),
        fetchRunLogs(effectiveRunId),
      ]);
      const baseRun = detail ?? runs.find((run) => (run.run_id ?? run.task_id) === effectiveRunId) ?? null;
      if (baseRun) {
        selectedRun = mapTaskRunDetail(baseRun, artifacts, logs);
      } else {
        detailError = `run ${effectiveRunId} 不存在`;
      }
    }

    return buildViewModel({
      source: "api",
      runs,
      selectedRun,
      selectedRunId: effectiveRunId,
      reviews,
      agentInspection,
      detailError,
    });
  } catch (cause) {
    const mock = await fetchMockFile();
    const runs = (mock.runs ?? []).filter(isTraceableRun);
    const effectiveRunId = selectedRunId && runs.some((run) => (run.run_id ?? run.task_id) === selectedRunId)
      ? selectedRunId
      : (runs[0]?.run_id ?? runs[0]?.task_id ?? null);
    const baseRun = effectiveRunId
      ? runs.find((run) => (run.run_id ?? run.task_id) === effectiveRunId) ?? null
      : null;
    const selectedRun = baseRun
      ? mapTaskRunDetail(
          baseRun,
          effectiveRunId ? mock.run_artifacts?.[effectiveRunId] ?? null : null,
          effectiveRunId ? mock.run_logs?.[effectiveRunId] ?? null : null,
        )
      : null;

    return buildViewModel({
      source: "mock",
      runs,
      selectedRun,
      selectedRunId: effectiveRunId,
      reviews: mock.reviews ?? { reviews: [], total: 0 },
      agentInspection: null,
      detailError: cause instanceof Error ? cause.message : "Agent Tasks API 不可用，已回退 mock",
    });
  }
}
