import { AgentTaskListCard, getRunReviewCount } from "@/components/agent-tasks/AgentTaskPanels";
import { type AgentTaskStatusFilter } from "@/components/agent-tasks/AgentTasksRail";
import { inferCategory, isInProgress, isSuccessful } from "@/components/agent-tasks/agentTaskMeta";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { TaskRunSummaryViewModel, TaskReviewViewModel } from "@/types/agent-task";

export function FilterChip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "inline-flex h-8 items-center gap-2 rounded-full border px-3 text-[11px] font-semibold transition-colors",
        active
          ? "border-[var(--brand)] bg-[var(--bg-active)] text-[var(--brand-hover)]"
          : "border-[var(--border)] bg-[var(--bg-card)] text-[var(--fg-4)] hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]",
      ].join(" ")}
    >
      <span>{label}</span>
      {typeof count === "number" ? <span className="fa-num text-[10px] text-current/70">{count}</span> : null}
    </button>
  );
}

export function matchesStatus(run: TaskRunSummaryViewModel, status: AgentTaskStatusFilter): boolean {
  if (status === "all") return true;
  if (status === "running") return isInProgress(run.status);
  if (status === "needs_review") return String(run.status).toLowerCase() === "needs_review";
  if (status === "success") return isSuccessful(run.status);
  return ["failed", "degraded"].includes(String(run.status).toLowerCase());
}

export function sortRuns(runs: TaskRunSummaryViewModel[]): TaskRunSummaryViewModel[] {
  return [...runs].sort((left, right) => {
    const rightKey = right.ended_at || right.started_at || right.trading_date || "";
    const leftKey = left.ended_at || left.started_at || left.trading_date || "";
    return rightKey.localeCompare(leftKey);
  });
}

export function RunOverviewCard({
  run,
  reviewCount,
}: {
  run: TaskRunSummaryViewModel;
  reviewCount: number;
}) {
  const category = inferCategory(run);
  const statusLabel = isInProgress(run.status)
    ? "运行中"
    : isSuccessful(run.status)
      ? "已完成"
      : String(run.status).toLowerCase() === "needs_review"
        ? "待复核"
        : "异常";
  const progressText = run.progress != null ? `${Math.round(run.progress * 100)}%` : "—";
  const timeText = run.ended_at || run.started_at || run.trading_date || "—";
  const statusHint = run.error_summary
    ? "存在异常信号，进入详情查看步骤与日志。"
    : reviewCount > 0
      ? "存在待复核项，进入详情查看 review 明细。"
      : "当前运行无额外告警，详情页查看完整输入输出与溯源。";

  return (
    <FACard
      title="当前任务摘要"
      eyebrow="运行概览"
      accent="brand"
      bodyClassName="space-y-3"
      action={<div className="text-[10px] text-[var(--fg-5)]">{run.trading_date || "未标注日期"}</div>}
    >
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <div className="min-w-0 rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[var(--bg-active)] px-2 py-1 text-[10px] font-semibold text-[var(--brand-hover)]">
              {category}
            </span>
            <span className="text-[10px] text-[var(--fg-5)]">{statusLabel}</span>
          </div>
          <div className="mt-2 text-[15px] font-semibold text-[var(--fg-1)]">{run.task_type || "未标注 task_type"}</div>
          <div className="mt-1 text-[11px] text-[var(--fg-4)]">{run.current_stage || "未进入阶段"}</div>
          <div className="mt-3 text-[11px] leading-6 text-[var(--fg-3)]">{statusHint}</div>
        </div>
        <div className="grid gap-2">
          <div className="rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2.5">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">进度</div>
            <div className="mt-1 text-[15px] font-semibold text-[var(--fg-1)]">{progressText}</div>
          </div>
          <div className="rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2.5">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">复核项</div>
            <div className="mt-1 text-[15px] font-semibold text-[var(--fg-1)]">{reviewCount}</div>
          </div>
          <div className="rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2.5">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">时间</div>
            <div className="mt-1 text-[11px] font-medium text-[var(--fg-2)]">{timeText}</div>
          </div>
        </div>
      </div>
    </FACard>
  );
}

export function AgentTasksConsoleCard({
  featuredRun,
  reviews,
  activeDateLabel,
  filteredRunsCount,
  remainingRunCount,
  needsReviewCount,
  query,
}: {
  featuredRun: TaskRunSummaryViewModel | null;
  reviews: TaskReviewViewModel[];
  activeDateLabel: string;
  filteredRunsCount: number;
  remainingRunCount: number;
  needsReviewCount: number;
  query: string;
}) {
  return (
    <FACard
      title="运行队列与详情入口"
      eyebrow="运行入口"
      accent="info"
      bodyClassName="space-y-3"
      action={<div className="text-[10px] text-[var(--fg-5)]">{`${activeDateLabel} · ${filteredRunsCount} 条入口`}</div>}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[11px] text-[var(--fg-4)]">
        <span>主页面只保留运行状态、分类筛选和任务入口；完整步骤、输入输出、日志与溯源进入详情页。</span>
        <span className="text-[10px] text-[var(--fg-5)]">点击卡片进入详情页</span>
      </div>
      {featuredRun ? (
        <>
          <AgentTaskListCard
            key={featuredRun.run_id}
            run={featuredRun}
            reviewCount={getRunReviewCount(reviews, featuredRun.run_id)}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
              <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">剩余入口</div>
              <div className="mt-1 text-[15px] font-semibold text-[var(--fg-1)]">{remainingRunCount}</div>
              <div className="mt-1 text-[10px] text-[var(--fg-4)]">其余任务继续作为详情入口保留在列表结果中</div>
            </div>
            <div className="rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
              <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">待复核</div>
              <div className="mt-1 text-[15px] font-semibold text-[var(--fg-1)]">{needsReviewCount}</div>
              <div className="mt-1 text-[10px] text-[var(--fg-4)]">先用状态筛选锁定待复核运行，再进入详情页处理</div>
            </div>
            <div className="rounded-[12px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
              <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">当前范围</div>
              <div className="mt-1 text-[15px] font-semibold text-[var(--fg-1)]">{query.trim() ? "已过滤" : "全量"}</div>
              <div className="mt-1 text-[10px] text-[var(--fg-4)]">分类、日期、状态和搜索共同决定当前入口范围</div>
            </div>
          </div>
        </>
      ) : (
        <FAEmptyState
          title="没有匹配的任务"
          description="调整左侧分类或状态筛选，或清空搜索关键字后重试。"
          className="p-6"
        />
      )}
    </FACard>
  );
}
