import { Link } from "react-router-dom";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FATabBar } from "@/components/shared/FATabBar";
import { formatDateTime, formatTradeDate } from "@/lib/date";
import { compactId, formatPercent } from "@/lib/format";
import type {
  AgentInspectionViewModel,
  TaskReviewViewModel,
  TaskRunSummaryViewModel,
  TaskRunViewModel,
} from "@/types/agent-task";
import { IOGrid } from "./AgentTaskIOPanels";
import { EventTimelinePanel, LogPanel, StepSummaryCards, SummaryPanel } from "./AgentTaskSummaryPanels";
import { ReviewPanel, TracePanel } from "./AgentTaskTraceReviewPanels";
import {
  CATEGORY_META,
  inferCategory,
  isInProgress,
  isSuccessful,
  taskStatusLabel,
  taskStatusTone,
  taskThemeLabel,
  taskTopicSummary,
  taskTypeLabel,
} from "./agentTaskMeta";

export type AgentTaskDetailTabKey = "summary" | "io" | "trace" | "review";

export function getRunReviewCount(reviews: TaskReviewViewModel[], runId: string): number {
  return reviews.filter((review) => review.run_id === runId).length;
}

export function AgentTasksKpiStrip({
  runs,
  reviewsTotal,
  categoryCount,
  filteredCount,
}: {
  runs: TaskRunSummaryViewModel[];
  reviewsTotal: number;
  categoryCount: number;
  filteredCount: number;
}) {
  const runningCount = runs.filter((run) => isInProgress(run.status)).length;
  const successCount = runs.filter((run) => isSuccessful(run.status)).length;

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <FAMetricCard label="总任务数" value={runs.length} hint="当前列表载入的运行总量" />
      <FAMetricCard label="执行中" value={runningCount} status={runningCount > 0 ? "active" : "idle"} statusTone={runningCount > 0 ? "info" : "dim"} hint="排队 / 运行 / 重试中的任务" />
      <FAMetricCard label="待复核" value={reviewsTotal} status={reviewsTotal > 0 ? "review" : "clear"} statusTone={reviewsTotal > 0 ? "warn" : "up"} hint="待人工确认的 ReviewItem" />
      <FAMetricCard label="当前结果" value={filteredCount} unit={`/ ${runs.length}`} hint={`Agent 分类 ${categoryCount} 组`} delta={successCount > 0 ? `${successCount} 已完成` : "暂无已完成任务"} trend="flat" />
    </div>
  );
}

export function AgentTaskListCard({
  run,
  reviewCount,
}: {
  run: TaskRunSummaryViewModel;
  reviewCount: number;
}) {
  const category = inferCategory(run);
  const meta = CATEGORY_META[category];

  return (
    <Link
      to={`/agent-tasks/${encodeURIComponent(run.run_id)}`}
      className="group block cursor-pointer rounded-[14px] border border-[var(--border)] bg-[linear-gradient(180deg,rgba(18,33,58,0.96),rgba(13,26,46,0.96))] p-3 transition-all hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] hover:shadow-[0_14px_32px_rgba(0,0,0,0.18)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-2.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full px-2 py-1 text-[10px] font-semibold" style={{ color: meta.accent, background: `${meta.accent}18` }}>
              {meta.label}
            </span>
            <span className="text-[10px] text-[var(--fg-5)]">{formatTradeDate(run.trading_date)}</span>
          </div>
          <div className="mt-2 text-[16px] font-semibold tracking-[-0.02em] text-[var(--fg-1)] group-hover:text-[var(--brand-hover)]">
            {taskTypeLabel(run.task_type)}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--fg-4)]">
            <span>{taskThemeLabel(run)}</span>
            <span>{run.current_stage || "未进入阶段"}</span>
            <span>{run.progress != null ? formatPercent(run.progress) : "无进度"}</span>
          </div>
          <p className="mt-2 max-w-3xl text-[11px] leading-relaxed text-[var(--fg-3)]">{taskTopicSummary(run)}</p>
          <div className="mt-2 text-[10px] text-[var(--fg-5)]">
            {run.ended_at ? `结束于 ${formatDateTime(run.ended_at)}` : run.started_at ? `开始于 ${formatDateTime(run.started_at)}` : "等待时间戳"}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {reviewCount > 0 ? <FAStatusPill tone="warn">{`复核 ${reviewCount}`}</FAStatusPill> : null}
          <FAStatusPill tone={taskStatusTone(run.status)}>{taskStatusLabel(run.status)}</FAStatusPill>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2.5 border-t border-[var(--border-faint)] pt-2.5">
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
          <span className="font-mono">{compactId(run.run_id, 12, 4)}</span>
          {run.snapshot_id ? <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5">snapshot</span> : null}
          {run.final_result_id ? <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5">result</span> : null}
        </div>
        {run.error_summary ? <span className="text-[10px] text-[var(--warn)]">存在异常，详情页查看</span> : <span className="text-[10px] text-[var(--fg-5)]">进入详情查看步骤与日志</span>}
      </div>
    </Link>
  );
}

export function AgentTaskDetailTabs({
  activeTab,
  reviewCount,
  onChange,
}: {
  activeTab: AgentTaskDetailTabKey;
  reviewCount: number;
  onChange: (tab: AgentTaskDetailTabKey) => void;
}) {
  return (
    <FATabBar
      ariaLabel="任务详情切换"
      value={activeTab}
      onChange={onChange}
      tabs={[
        { value: "summary", label: "分析内容" },
        { value: "io", label: "输入输出" },
        { value: "trace", label: "数据来源" },
        { value: "review", label: "待复核", count: reviewCount },
      ]}
    />
  );
}

export function AgentTaskDetailContent({
  selectedRun,
  reviews,
  agentInspection,
  activeTab,
}: {
  selectedRun: TaskRunViewModel;
  reviews: TaskReviewViewModel[];
  agentInspection?: AgentInspectionViewModel | null;
  activeTab: AgentTaskDetailTabKey;
}) {
  if (activeTab === "summary") {
    return (
      <div className="space-y-4">
        <SummaryPanel selectedRun={selectedRun} />
        <StepSummaryCards steps={selectedRun.steps} />
        <EventTimelinePanel events={selectedRun.events} />
        <LogPanel logs={selectedRun.logs} />
      </div>
    );
  }

  if (activeTab === "io") {
    return <IOGrid steps={selectedRun.steps} agentInspection={agentInspection} />;
  }

  if (activeTab === "trace") {
    return <TracePanel selectedRun={selectedRun} />;
  }

  return <ReviewPanel reviews={reviews} />;
}
