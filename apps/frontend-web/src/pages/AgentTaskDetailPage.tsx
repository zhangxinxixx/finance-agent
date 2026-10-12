import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  AgentTaskDetailHero,
  AgentTaskRuntimeContext,
} from "@/components/agent-tasks/AgentTaskDetailSections";
import { AgentTaskDetailContent, AgentTaskDetailTabs, type AgentTaskDetailTabKey } from "@/components/agent-tasks/AgentTaskPanels";
import { taskTypeLabel } from "@/components/agent-tasks/agentTaskMeta";
import { FACard } from "@/components/shared/FACard";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { useAgentTasks } from "@/hooks/useAgentTasks";
import { formatTradeDate } from "@/lib/date";
import { formatPercent } from "@/lib/format";
import type { TaskRunViewModel } from "@/types/agent-task";
import { operationStageLabel } from "@/components/operations/operationsLabels";

export function AgentTaskDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const agentTasks = useAgentTasks(runId);
  const [activeTab, setActiveTab] = useState<AgentTaskDetailTabKey>("summary");

  const selectedRun = agentTasks.data?.selected_run ?? null;
  const reviews = agentTasks.data?.reviews ?? [];
  const metrics = useMemo(
    () => [
      { label: "任务类型", value: selectedRun ? taskTypeLabel(selectedRun.task_type) : "—", hint: "任务类型" },
      { label: "交易日", value: formatTradeDate(selectedRun?.dataDate), hint: "交易日" },
      { label: "当前阶段", value: operationStageLabel(selectedRun?.current_stage), hint: "当前阶段" },
      { label: "运行进度", value: selectedRun?.progress != null ? formatPercent(selectedRun.progress) : "—", hint: "运行进度" },
      { label: "运行标识", value: selectedRun?.run_id ? "已登记" : "未提供", hint: "可从任务证据入口复制" },
      { label: "快照标识", value: selectedRun?.snapshot_id ? "已登记" : "未提供", hint: "可从任务证据入口复制" },
      { label: "结果标识", value: selectedRun?.final_result_id ? "已登记" : "未提供", hint: "可从任务证据入口复制" },
      { label: "步骤数", value: selectedRun?.steps.length ?? 0, hint: "已返回的执行步骤" },
    ],
    [selectedRun],
  );

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
            description="任务运行接口暂时无法读取，当前详情不可用；请稍后重试。"
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
          <div className="mt-3">
            <EvidenceRecordActions
              record={agentTasks.error ? { error: agentTasks.error.message, state: "unavailable" } : null}
              label="读取失败记录"
            />
          </div>
        </FACard>
      </div>
    );
  }

  if (!selectedRun) {
    return (
      <div className="finance-page-shell">
        <FAEmptyState title="未找到任务详情" description="当前运行标识没有命中可展示的任务，请返回任务列表重新选择。" />
      </div>
    );
  }

  return (
    <div className="finance-page-shell">
      <div className="flex min-h-full flex-col gap-4">
        <AgentTaskDetailHero
          className="shrink-0"
          selectedRun={selectedRun}
          source={agentTasks.data.source}
          metrics={metrics}
          onRefresh={agentTasks.refetch}
        />

        {selectedRun.error_summary ? <FAWarningBanner title="运行异常" description={selectedRun.error_summary} tone="warn" /> : null}
        {agentTasks.data.detail_error ? <FAWarningBanner title="详情降级" description={agentTasks.data.detail_error} tone="warn" /> : null}

        <div className="grid flex-none gap-4 2xl:grid-cols-[minmax(0,1.6fr)_340px]">
          <div className="flex min-h-0 flex-col gap-4">
            <FACard
              title="任务详情工作台"
              eyebrow="Task Detail"
              accent="info"
              className="flex min-h-0 flex-col"
              bodyClassName="min-h-0 flex flex-1 flex-col gap-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-[11px] text-[var(--fg-4)]">只读查看 ADS 运行摘要、步骤状态与复核结果，不展示输入输出、日志正文或产物文件。</div>
                <AgentTaskDetailTabs activeTab={activeTab} reviewCount={reviews.length} onChange={setActiveTab} />
              </div>
              <div className="min-h-0 flex-1">
                <AgentTaskDetailContent
                  selectedRun={selectedRun}
                  reviews={reviews}
                  activeTab={activeTab}
                />
              </div>
            </FACard>
          </div>

          <div className="flex min-h-0 flex-col gap-4">
            <AgentTaskRuntimeContext selectedRun={selectedRun} reviews={reviews} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default AgentTaskDetailPage;
