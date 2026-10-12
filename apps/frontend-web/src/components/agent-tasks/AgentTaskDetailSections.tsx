import { Link } from "react-router-dom";
import { taskStatusLabel, taskStatusTone, taskTypeLabel, taskTopicSummary } from "@/components/agent-tasks/agentTaskMeta";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import { formatNumber } from "@/lib/format";
import type { TaskReviewViewModel, TaskRunViewModel } from "@/types/agent-task";
import { operationFieldLabel, operationReadableLabel, operationStageLabel } from "@/components/operations/operationsLabels";

export function AgentTaskDetailHero({
  selectedRun,
  source,
  metrics,
  onRefresh,
  className = "",
}: {
  selectedRun: TaskRunViewModel;
  source: string;
  metrics: Array<{ label: string; value: string | number; hint: string }>;
  onRefresh: () => void;
  className?: string;
}) {
  return (
    <FACard
      title={taskTypeLabel(selectedRun.task_type)}
      eyebrow="任务详情"
      accent="brand"
      className={className}
      action={
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to="/agent-tasks"
            className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-3)]"
          >
            返回列表
          </Link>
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]"
          >
            刷新
          </button>
        </div>
      }
      bodyClassName="space-y-4"
    >
      <FASectionHeader
        title={taskTypeLabel(selectedRun.task_type)}
        eyebrow={
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <Link to="/agent-tasks" className="text-[var(--brand-hover)] hover:text-[var(--brand)]">
              智能体任务
            </Link>
            <span className="text-[var(--fg-5)]">/</span>
            <span className="text-[var(--fg-4)]">{selectedRun.run_id ? "运行记录已登记" : "运行标识未提供"}</span>
          </div>
        }
        description={taskTopicSummary(selectedRun)}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <FAStatusPill tone={taskStatusTone(selectedRun.status)}>{taskStatusLabel(selectedRun.status)}</FAStatusPill>
            {selectedRun.current_stage ? <FAStatusPill tone="info">{operationStageLabel(selectedRun.current_stage)}</FAStatusPill> : null}
            <FAStatusPill tone="dim">{source === "api" ? "真实接口" : source === "fixture" ? "模拟记录" : operationReadableLabel(source, "来源状态待确认")}</FAStatusPill>
          </div>
        }
      />

      <div className="flex flex-wrap gap-2">
        <FASourceTraceBadge source={selectedRun.run_id ? "运行记录已登记" : "运行标识未提供"} status="运行标识" tone="info" snapshotId={selectedRun.snapshot_id ?? null} />
        {selectedRun.snapshot_id ? <FASourceTraceBadge source="输入快照已登记" status="快照标识" tone="dim" /> : null}
        {selectedRun.final_result_id ? <FASourceTraceBadge source="分析结果已登记" status="结果标识" tone="dim" /> : null}
      </div>
      <EvidenceRecordActions
        record={{ run_id: selectedRun.run_id, snapshot_id: selectedRun.snapshot_id, final_result_id: selectedRun.final_result_id }}
        label="任务标识依据"
      />

      <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-4">
        {metrics.map((metric) => (
          <FAMetricCard key={metric.label} label={metric.label} value={metric.value} hint={metric.hint} />
        ))}
      </div>
    </FACard>
  );
}

export function AgentTaskRuntimeContext({
  selectedRun,
  reviews,
}: {
  selectedRun: TaskRunViewModel;
  reviews: TaskReviewViewModel[];
}) {
  return (
    <FACard title="运行上下文" eyebrow="时间与资源" accent="warn">
      <div className="grid gap-3">
        <FAMetricCard label={operationFieldLabel("started_at")} value={formatDateTime(selectedRun.started_at)} hint="任务开始时间" />
        <FAMetricCard label={operationFieldLabel("ended_at")} value={formatDateTime(selectedRun.ended_at)} hint="任务结束时间" />
        <FAMetricCard label={operationFieldLabel("token_in")} value={formatNumber(selectedRun.token_in, 0)} hint="输入资源量" />
        <FAMetricCard label={operationFieldLabel("token_out")} value={formatNumber(selectedRun.token_out, 0)} hint="输出资源量" />
        <FAMetricCard label={operationFieldLabel("cost_usd")} value={formatNumber(selectedRun.total_cost_usd, 4)} hint="记录的总成本" />
        <FAMetricCard label="关联复核项" value={reviews.length} hint="需要人工关注的条目" />
      </div>
    </FACard>
  );
}

export function AgentTaskSourceArtifacts({
  selectedRun,
}: {
  selectedRun: TaskRunViewModel;
}) {
  return (
    <>
      <FACard title="数据溯源" eyebrow="来源链路" accent="brand">
        <div className="mb-3 text-[11px] text-[var(--fg-4)]">保留来源引用和产物引用，便于回查原始数据、解析结果与最终输出。</div>
        <div className="max-h-[360px] overflow-y-auto pr-1">
          {selectedRun.source_refs.length > 0 ? (
            <div className="space-y-2">
              <div className="text-[11px] text-[var(--fg-4)]">{selectedRun.source_refs.length} 条来源记录已登记，详情可复制核对。</div>
              <EvidenceRecordActions record={selectedRun.source_refs} label="来源引用依据" />
            </div>
          ) : <div className="text-[11px] text-[var(--fg-5)]">当前任务未返回来源引用</div>}
        </div>
      </FACard>

      {selectedRun.artifact_refs.length > 0 ? (
        <FACard title="关联产物" eyebrow="产物引用" accent="none">
          <div className="max-h-[220px] overflow-y-auto pr-1">
            <div className="flex flex-wrap gap-2">
              {selectedRun.artifact_refs.map((artifact) => (
                <FASourceTraceBadge
                  key={`${artifact.artifact_id}-${artifact.file_path}`}
                  source={operationFieldLabel(artifact.artifact_type || "artifact_type")}
                  status="已登记"
                  tone="dim"
                />
              ))}
            </div>
          </div>
        </FACard>
      ) : null}
    </>
  );
}
