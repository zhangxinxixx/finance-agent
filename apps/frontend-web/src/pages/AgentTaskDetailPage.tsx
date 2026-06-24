import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AgentTaskDetailHero,
  AgentTaskRuntimeContext,
  AgentTaskSourceArtifacts,
} from "@/components/agent-tasks/AgentTaskDetailSections";
import { AgentTaskDetailContent, AgentTaskDetailTabs, type AgentTaskDetailTabKey } from "@/components/agent-tasks/AgentTaskPanels";
import { taskTypeLabel } from "@/components/agent-tasks/agentTaskMeta";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { useAgentTasks } from "@/hooks/useAgentTasks";
import { formatTradeDate } from "@/lib/date";
import { compactId, formatPercent } from "@/lib/format";
import type { TaskRunViewModel } from "@/types/agent-task";

function normalizeMonitorDate(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const ymd = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
  if (ymd) return ymd[1];
  return null;
}

function resolveFeishuMonitorHref(selectedRun: TaskRunViewModel | null): string | null {
  if (!selectedRun) return null;
  const hasFeishuSource = (selectedRun.source_refs ?? []).some((ref: { source_ref?: string | null; label?: string | null }) => {
    const raw = `${ref.source_ref ?? ""} ${ref.label ?? ""}`.toLowerCase();
    return raw.includes("jin10_feishu") || raw.includes("飞书");
  });
  const taskType = String(selectedRun.task_type ?? "").toLowerCase();
  if (!hasFeishuSource && !taskType.includes("daily_analysis_followup") && !taskType.includes("jin10")) {
    return null;
  }
  const date = normalizeMonitorDate(selectedRun.dataDate ?? selectedRun.trading_date ?? null);
  return date ? `/feishu-monitor?date=${encodeURIComponent(date)}` : "/feishu-monitor";
}

export function AgentTaskDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const agentTasks = useAgentTasks(runId);
  const [activeTab, setActiveTab] = useState<AgentTaskDetailTabKey>("summary");

  const selectedRun = agentTasks.data?.selected_run ?? null;
  const reviews = agentTasks.data?.reviews ?? [];
  const metrics = useMemo(
    () => [
      { label: "task_type", value: selectedRun ? taskTypeLabel(selectedRun.task_type) : "—", hint: "任务类型" },
      { label: "trade_date", value: formatTradeDate(selectedRun?.dataDate), hint: "交易日" },
      { label: "current_stage", value: selectedRun?.current_stage || "—", hint: "当前阶段" },
      { label: "progress", value: selectedRun?.progress != null ? formatPercent(selectedRun.progress) : "—", hint: "运行进度" },
      { label: "run_id", value: compactId(selectedRun?.run_id, 10, 4), hint: "运行标识" },
      { label: "snapshot_id", value: compactId(selectedRun?.snapshot_id, 10, 4), hint: "快照标识" },
      { label: "result_id", value: compactId(selectedRun?.final_result_id, 10, 4), hint: "最终结果" },
      { label: "steps", value: selectedRun?.steps.length ?? 0, hint: "步骤数量" },
    ],
    [selectedRun],
  );
  const monitorHref = useMemo(() => resolveFeishuMonitorHref(selectedRun), [selectedRun]);

  useEffect(() => {
    setActiveTab("summary");
  }, [runId]);

  if (agentTasks.isLoading && !agentTasks.data) {
    return (
      <div className="finance-page-shell">
        <LoadingSkeleton variant="page" />
      </div>
    );
  }

  if (agentTasks.isError || !agentTasks.data) {
    return (
      <div className="finance-page-shell">
        <FACard title="任务详情加载失败" eyebrow="任务详情" accent="down">
          <FAWarningBanner
            title="标准详情页当前不可用"
            description={agentTasks.error?.message ?? "未知错误"}
            tone="down"
            action={
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={agentTasks.refetch}
                  className="rounded-[var(--radius-md)] border border-[var(--down-border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--down)]"
                >
                  重试
                </button>
                <Link
                  to="/agent-tasks"
                  className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-3)]"
                >
                  返回任务中心
                </Link>
              </div>
            }
          />
        </FACard>
      </div>
    );
  }

  if (!selectedRun) {
    return (
      <div className="finance-page-shell">
        <FAEmptyState title="未找到任务详情" description="当前 run_id 没有命中可展示的任务，请返回任务列表重新选择。" />
      </div>
    );
  }

  return (
    <div className="finance-page-shell">
      <div className="flex min-h-full flex-col gap-4">
        <AgentTaskDetailHero
          selectedRun={selectedRun}
          source={agentTasks.data.source}
          metrics={metrics}
          onRefresh={agentTasks.refetch}
          monitorHref={monitorHref}
        />

        {selectedRun.error_summary ? <FAWarningBanner title="运行异常" description={selectedRun.error_summary} tone="warn" /> : null}
        {agentTasks.data.detail_error ? <FAWarningBanner title="详情降级" description={agentTasks.data.detail_error} tone="warn" /> : null}

        <div className="grid min-h-0 flex-1 gap-4 2xl:grid-cols-[minmax(0,1.6fr)_340px]">
          <div className="flex min-h-0 flex-col gap-4">
            <FACard
              title="任务详情工作台"
              eyebrow="Task Detail"
              accent="info"
              className="flex min-h-0 flex-col"
              bodyClassName="min-h-0 flex flex-1 flex-col gap-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-[11px] text-[var(--fg-4)]">只读查看步骤、日志、输入输出与来源链路，不在前端推导任何结论。</div>
                <AgentTaskDetailTabs activeTab={activeTab} reviewCount={reviews.length} onChange={setActiveTab} />
              </div>
              <div className="min-h-0 flex-1">
                <AgentTaskDetailContent
                  selectedRun={selectedRun}
                  reviews={reviews}
                  agentInspection={agentTasks.data.agent_inspection ?? null}
                  activeTab={activeTab}
                />
              </div>
            </FACard>
          </div>

          <div className="flex min-h-0 flex-col gap-4">
            <AgentTaskRuntimeContext selectedRun={selectedRun} reviews={reviews} />
            <AgentTaskSourceArtifacts selectedRun={selectedRun} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default AgentTaskDetailPage;
