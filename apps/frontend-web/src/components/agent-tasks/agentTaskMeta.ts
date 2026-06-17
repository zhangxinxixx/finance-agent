import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { TaskRunStatus, TaskRunSummaryViewModel } from "@/types/agent-task";

export type AgentCategoryKey = "macro" | "options" | "news" | "coordinator" | "other";

export const CATEGORY_META: Record<AgentCategoryKey, { label: string; accent: string; description: string }> = {
  macro: { label: "宏观", accent: "#2563eb", description: "看宏观环境与流动性" },
  options: { label: "期权", accent: "#f59e0b", description: "看期权结构与墙位" },
  news: { label: "新闻", accent: "#10b981", description: "看事件整理与提炼" },
  coordinator: { label: "综合", accent: "#8b5cf6", description: "看汇总判断与结论" },
  other: { label: "其他", accent: "#64748b", description: "看未归类任务" },
};

export function taskStatusLabel(status: TaskRunStatus): string {
  return getStatusLabel(status || "unknown", "task");
}

export function taskStatusTone(status: TaskRunStatus): FAStatusTone {
  return getStatusTone(status, "task");
}

export function inferCategory(run: Pick<TaskRunSummaryViewModel, "task_type" | "current_stage">): AgentCategoryKey {
  const raw = `${run.task_type} ${run.current_stage || ""}`.toLowerCase();
  if (raw.includes("macro")) return "macro";
  if (raw.includes("option") || raw.includes("cme")) return "options";
  if (raw.includes("jin10") || raw.includes("news")) return "news";
  if (raw.includes("strategy") || raw.includes("report") || raw.includes("coordinator")) return "coordinator";
  return "other";
}

export function taskTypeLabel(taskType: string): string {
  const raw = taskType.toLowerCase();
  if (raw.includes("macro")) return "宏观分析";
  if (raw.includes("option") || raw.includes("cme")) return "期权分析";
  if (raw.includes("jin10") || raw.includes("news")) return "新闻整理";
  if (raw.includes("strategy")) return "策略汇总";
  if (raw.includes("report")) return "报告生成";
  if (raw.includes("premarket")) return "盘前总览";
  return taskType.replace(/_/g, " ");
}

export function taskTopicSummary(run: Pick<TaskRunSummaryViewModel, "task_type">): string {
  const raw = run.task_type.toLowerCase();
  if (raw.includes("macro")) return "聚焦宏观环境、利率、美元与流动性条件。";
  if (raw.includes("option") || raw.includes("cme")) return "聚焦期权墙位、结构变化和关键价位。";
  if (raw.includes("jin10") || raw.includes("news")) return "聚焦新闻事件、要点提炼和市场影响。";
  if (raw.includes("strategy")) return "聚焦策略方向、情景推演和执行建议。";
  if (raw.includes("report")) return "聚焦报告整理、汇总与最终产出。";
  if (raw.includes("premarket")) return "聚焦盘前全局检查与多模块串联。";
  return "查看该任务的分析过程与结果。";
}

export function taskThemeLabel(run: Pick<TaskRunSummaryViewModel, "task_type">): string {
  const raw = run.task_type.toLowerCase();
  if (raw.includes("macro")) return "宏观主题";
  if (raw.includes("option") || raw.includes("cme")) return "期权主题";
  if (raw.includes("jin10") || raw.includes("news")) return "新闻主题";
  if (raw.includes("strategy")) return "策略主题";
  if (raw.includes("report")) return "报告主题";
  if (raw.includes("premarket")) return "盘前主题";
  return "任务主题";
}

export function isInProgress(status: TaskRunStatus): boolean {
  return ["queued", "running", "retrying"].includes(String(status ?? "").toLowerCase());
}

export function isSuccessful(status: TaskRunStatus): boolean {
  return ["success", "partial_success"].includes(String(status ?? "").toLowerCase());
}
