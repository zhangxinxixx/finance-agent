import { matchesStatus, sortRuns } from "@/components/agent-tasks/AgentTasksPageSections";
import { inferCategory, isInProgress, isSuccessful, type AgentCategoryKey } from "@/components/agent-tasks/agentTaskMeta";
import type { AgentTaskStatusFilter } from "@/components/agent-tasks/AgentTasksRail";
import type { TaskRunSummaryViewModel } from "@/types/agent-task";

export type TaskDateFilter = "latest" | "all" | string;
export interface AgentTasksStatusTab {
  value: AgentTaskStatusFilter;
  label: string;
  count: number;
}

export interface AgentTasksDateTab {
  value: TaskDateFilter;
  label: string;
  count: number;
}

export interface AgentTasksPageModel {
  categoryCount: number;
  availableDates: string[];
  latestDate: string | null;
  filteredRuns: TaskRunSummaryViewModel[];
  featuredRun: TaskRunSummaryViewModel | null;
  remainingRunCount: number;
  statusTabs: AgentTasksStatusTab[];
  dateTabs: AgentTasksDateTab[];
  activeDateLabel: string;
  needsReviewCount: number;
}

export function listAvailableTaskDates(runs: TaskRunSummaryViewModel[]): string[] {
  return Array.from(new Set(runs.map((run) => run.trading_date).filter(Boolean) as string[])).sort((left, right) =>
    right.localeCompare(left),
  );
}

export function filterAgentTaskRuns(
  runs: TaskRunSummaryViewModel[],
  activeCategory: AgentCategoryKey | "all",
  activeStatus: AgentTaskStatusFilter,
  activeDate: TaskDateFilter,
  latestDate: string | null,
  query: string,
): TaskRunSummaryViewModel[] {
  const needle = query.trim().toLowerCase();
  return sortRuns(
    runs.filter((run) => {
      if (activeCategory !== "all" && inferCategory(run) !== activeCategory) return false;
      if (!matchesStatus(run, activeStatus)) return false;
      if (activeDate === "latest" && latestDate && run.trading_date !== latestDate) return false;
      if (activeDate !== "latest" && activeDate !== "all" && run.trading_date !== activeDate) return false;
      if (!needle) return true;

      const haystack = [
        run.run_id,
        run.task_type,
        run.current_stage,
        run.snapshot_id,
        run.final_result_id,
        run.trading_date,
        run.error_summary,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    }),
  );
}

export function buildStatusTabs(runs: TaskRunSummaryViewModel[]): AgentTasksStatusTab[] {
  return [
    { value: "all", label: "全部", count: runs.length },
    { value: "running", label: "执行中", count: runs.filter((run) => isInProgress(run.status)).length },
    { value: "needs_review", label: "待复核", count: runs.filter((run) => String(run.status).toLowerCase() === "needs_review").length },
    { value: "success", label: "已完成", count: runs.filter((run) => isSuccessful(run.status)).length },
    { value: "failed", label: "异常", count: runs.filter((run) => ["failed", "degraded"].includes(String(run.status).toLowerCase())).length },
  ];
}

export function buildDateTabs(
  runs: TaskRunSummaryViewModel[],
  availableDates: string[],
  latestDate: string | null,
): AgentTasksDateTab[] {
  const recentTabs = availableDates.slice(0, 3).map((date) => ({
    value: date,
    label: date === latestDate ? "当日" : date.slice(5),
    count: runs.filter((run) => run.trading_date === date).length,
  }));
  return [
    { value: "latest", label: "当日总任务", count: latestDate ? runs.filter((run) => run.trading_date === latestDate).length : 0 },
    ...recentTabs,
    { value: "all", label: "全部日期", count: runs.length },
  ];
}

export function formatActiveTaskDateLabel(activeDate: TaskDateFilter, latestDate: string | null) {
  if (activeDate === "latest") return latestDate ?? "当日";
  if (activeDate === "all") return "全部日期";
  return activeDate;
}

export function buildAgentTasksPageModel(
  runs: TaskRunSummaryViewModel[],
  activeCategory: AgentCategoryKey | "all",
  activeStatus: AgentTaskStatusFilter,
  activeDate: TaskDateFilter,
  query: string,
): AgentTasksPageModel {
  const categoryCount = new Set(runs.map((run) => inferCategory(run))).size;
  const availableDates = listAvailableTaskDates(runs);
  const latestDate = availableDates[0] ?? null;
  const filteredRuns = filterAgentTaskRuns(runs, activeCategory, activeStatus, activeDate, latestDate, query);
  const featuredRun = filteredRuns[0] ?? null;
  const remainingRunCount = Math.max(filteredRuns.length - 1, 0);
  const statusTabs = buildStatusTabs(runs);
  const dateTabs = buildDateTabs(runs, availableDates, latestDate);

  return {
    categoryCount,
    availableDates,
    latestDate,
    filteredRuns,
    featuredRun,
    remainingRunCount,
    statusTabs,
    dateTabs,
    activeDateLabel: formatActiveTaskDateLabel(activeDate, latestDate),
    needsReviewCount: statusTabs.find((tab) => tab.value === "needs_review")?.count ?? 0,
  };
}
