import { ApiError, fetchJson } from "@/adapters/apiClient";
import { formatDateTime } from "@/lib/date";

// ── Types ──

export interface SchedulerDailySummary {
  date: string;
  total: number;
  success: number;
  failed: number;
  running: number;
}

export interface SchedulerCategoryStat {
  label: string;
  color: string;
  description: string;
  total: number;
  success: number;
  failed: number;
}

export interface SchedulerTaskRun {
  run_id: string;
  task_name: string;
  task_type: string;
  category: string;
  status: string;
  current_stage: string | null;
  trade_date: string | null;
  started_at: string | null;
  ended_at: string | null;
  error_summary: string | null;
  progress: number | null;
  step_count: number;
  snapshot_id: string | null;
}

export interface SchedulerCronJob {
  job_id: string;
  name: string;
  schedule: { kind: string; expr: string; display: string };
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  next_run_at: string | null;
}

export interface SchedulerOutputItem {
  path: string;
  name: string;
  updated_at: string;
  size: number;
}

export interface SchedulerOverviewResponse {
  generated_at: string;
  period_days: number;
  summary: {
    total_runs: number;
    today_runs: number;
    success_count: number;
    failed_count: number;
    running_count: number;
    pending_count: number;
    data_sources_ok: number;
    data_sources_total: number;
    artifacts_today: number;
  };
  task_runs: SchedulerTaskRun[];
  category_stats: Record<string, SchedulerCategoryStat>;
  daily_summary: SchedulerDailySummary[];
  data_source_status: {
    ok: number;
    error: number;
    not_connected: number;
    total: number;
  };
  cron_jobs: SchedulerCronJob[];
  artifacts_summary: {
    today_count: number;
    recent_outputs: SchedulerOutputItem[];
  };
}

// ── API ──

const OVERVIEW_PATH = "/api/scheduler/overview";

export async function fetchSchedulerOverview(
  days: number = 7,
): Promise<SchedulerOverviewResponse> {
  const params = new URLSearchParams({ days: String(Math.min(days, 90)), limit: "100" });
  return fetchJson<SchedulerOverviewResponse>(`${OVERVIEW_PATH}?${params.toString()}`);
}

// ── Helpers ──

export const CATEGORY_LABELS: Record<string, string> = {
  data_collection: "数据采集",
  data_parsing: "数据解析",
  analysis: "分析任务",
  report: "报告生成",
  governance: "治理任务",
  other: "其他",
};

export const CATEGORY_COLORS: Record<string, string> = {
  data_collection: "#3b82f6",
  data_parsing: "#8b5cf6",
  analysis: "#f59e0b",
  report: "#10b981",
  governance: "#64748b",
  other: "#94a3b8",
};

export const STATUS_LABELS: Record<string, string> = {
  success: "成功",
  partial_success: "部分成功",
  failed: "失败",
  running: "运行中",
  pending: "等待中",
  queued: "排队中",
  blocked: "阻塞",
  cancelled: "已取消",
  stale: "过期",
  degraded: "降级",
};

export const STATUS_TONES: Record<string, "up" | "warn" | "down" | "dim"> = {
  success: "up",
  partial_success: "warn",
  failed: "down",
  running: "warn",
  pending: "dim",
  queued: "dim",
  blocked: "down",
  cancelled: "dim",
  stale: "down",
  degraded: "warn",
};

export function formatStatus(status: string): string {
  return STATUS_LABELS[status.toLowerCase()] ?? status;
}

export function getStatusTone(status: string): "up" | "warn" | "down" | "dim" {
  return STATUS_TONES[status.toLowerCase()] ?? "dim";
}

export async function triggerRunAllCollectors(): Promise<{ status: string; message: string }> {
  return fetchJson<{ status: string; message: string }>("/api/scheduler/run-all-collectors", {
    method: "POST",
  });
}

// ── Task Detail ──

export interface RunStep {
  step_id: string;
  name: string;
  stage: string | null;
  status: string;
  step_order: number;
  error: string | null;
  input_refs: unknown[] | null;
  output_refs: unknown[] | null;
  source_refs: unknown[] | null;
  artifact_refs: unknown[] | null;
  started_at: string | null;
  finished_at: string | null;
  input_json: Record<string, unknown> | null;
  output_json: Record<string, unknown> | null;
  error_json: Record<string, unknown> | null;
  duration_ms: number | null;
  retry_count: number;
}

export interface RunDetail {
  run_id: string;
  name: string;
  task_type: string;
  status: string;
  trade_date: string | null;
  progress: number | null;
  error: string | null;
  error_summary: string | null;
  started_at: string | null;
  ended_at: string | null;
  steps: RunStep[];
}

export async function fetchRunDetail(runId: string): Promise<RunDetail> {
  // 并行拉取 detail + steps + artifacts
  const [detail, stepsRes, artifacts] = await Promise.all([
    fetchJson<any>(`/api/runs/${runId}`),
    fetchJson<any>(`/api/runs/${runId}/steps`).catch(() => ({ steps: [] })),
    fetchJson<any>(`/api/runs/${runId}/artifacts`).catch(() => ({ artifacts: [] })),
  ]);
  return {
    run_id: detail.run_id ?? runId,
    name: detail.name ?? detail.task_name ?? "",
    task_type: detail.task_type ?? "",
    status: detail.status ?? "",
    trade_date: detail.trade_date ?? null,
    progress: detail.progress ?? null,
    error: detail.error ?? null,
    error_summary: detail.error_summary ?? null,
    started_at: detail.started_at ?? null,
    ended_at: detail.ended_at ?? null,
    steps: (stepsRes.steps || []).map((s: any) => ({
      ...s,
      artifact_refs: s.artifact_refs ?? artifacts.artifacts ?? null,
      input_json: s.input_json ?? null,
      output_json: s.output_json ?? null,
      error_json: s.error_json ?? null,
      duration_ms: s.duration_ms ?? null,
      retry_count: s.retry_count ?? 0,
    })),
  };
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1048576).toFixed(1)}MB`;
}

// ── Agent Analysis ──

export interface AgentAnalysisItem {
  agent_output_id: string;
  agent_name: string;
  display_name: string;
  registry_id: string;
  module: string;
  status: string;
  snapshot_id: string | null;
  trade_date: string | null;
  run_id: string | null;
  summary: string | null;
  summary_zh: string | null;
}

export interface AgentAnalysisResponse {
  trade_date: string;
  agent_outputs: AgentAnalysisItem[];
}

/** 将 agent analysis 产出映射为 SchedulerTaskRun 兼容对象，混入管线网格 */
export function agentAnalysisToTaskRun(a: AgentAnalysisItem): SchedulerTaskRun {
  const statusMap: Record<string, string> = { success: "success", partial: "partial_success", failed: "failed", running: "running" };
  return {
    run_id: a.agent_output_id,
    task_name: a.display_name || a.agent_name,
    task_type: a.agent_name,
    category: a.module || "analysis",
    status: statusMap[a.status] || a.status,
    current_stage: null,
    trade_date: a.trade_date || null,
    started_at: null,
    ended_at: null,
    error_summary: null,
    progress: null,
    step_count: 1,
    snapshot_id: a.snapshot_id,
  };
}

/** 拉取指定日期的 Agent Analysis 数据 */
export async function fetchAgentAnalysis(tradeDate: string): Promise<AgentAnalysisItem[]> {
  try {
    const data = await fetchJson<AgentAnalysisResponse>(
      `/api/agent-analysis?limit=500`
    );
    // API returns trade_date at top level, inject into each item
    const topDate = data.trade_date;
    return (data.agent_outputs || []).map(a => ({ ...a, trade_date: a.trade_date || topDate }));
  } catch {
    return [];
  }
}
