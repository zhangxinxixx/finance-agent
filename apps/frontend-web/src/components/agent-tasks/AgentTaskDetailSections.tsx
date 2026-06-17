import { Link } from "react-router-dom";
import { taskStatusLabel, taskStatusTone, taskTypeLabel, taskTopicSummary } from "@/components/agent-tasks/agentTaskMeta";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { formatDateTime } from "@/lib/date";
import { compactId, formatNumber } from "@/lib/format";
import type { TaskReviewViewModel, TaskRunViewModel } from "@/types/agent-task";

export function AgentTaskDetailHero({
  selectedRun,
  source,
  metrics,
  onRefresh,
}: {
  selectedRun: TaskRunViewModel;
  source: string;
  metrics: Array<{ label: string; value: string | number; hint: string }>;
  onRefresh: () => void;
}) {
  return (
    <FACard
      title={taskTypeLabel(selectedRun.task_type)}
      eyebrow="任务详情"
      accent="brand"
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
            <span className="font-mono text-[var(--fg-4)]">{compactId(selectedRun.run_id, 12, 4)}</span>
          </div>
        }
        description={taskTopicSummary(selectedRun)}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <FAStatusPill tone={taskStatusTone(selectedRun.status)}>{taskStatusLabel(selectedRun.status)}</FAStatusPill>
            {selectedRun.current_stage ? <FAStatusPill tone="info">{selectedRun.current_stage}</FAStatusPill> : null}
            <FAStatusPill tone="dim">{source}</FAStatusPill>
          </div>
        }
      />

      <div className="flex flex-wrap gap-2">
        <FASourceTraceBadge source={compactId(selectedRun.run_id, 12, 4)} status="run_id" tone="info" snapshotId={selectedRun.snapshot_id ?? null} />
        {selectedRun.snapshot_id ? <FASourceTraceBadge source={compactId(selectedRun.snapshot_id, 12, 4)} status="snapshot_id" tone="dim" /> : null}
        {selectedRun.final_result_id ? <FASourceTraceBadge source={compactId(selectedRun.final_result_id, 12, 4)} status="final_result" tone="dim" /> : null}
      </div>

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
    <FACard title="运行上下文" eyebrow="Runtime Context" accent="warn">
      <div className="grid gap-3">
        <FAMetricCard label="started_at" value={formatDateTime(selectedRun.started_at)} hint="开始时间" />
        <FAMetricCard label="ended_at" value={formatDateTime(selectedRun.ended_at)} hint="结束时间" />
        <FAMetricCard label="token_in" value={formatNumber(selectedRun.token_in, 0)} hint="输入 token" />
        <FAMetricCard label="token_out" value={formatNumber(selectedRun.token_out, 0)} hint="输出 token" />
        <FAMetricCard label="cost_usd" value={formatNumber(selectedRun.total_cost_usd, 4)} hint="总成本 USD" />
        <FAMetricCard label="reviews" value={reviews.length} hint="关联复核项" />
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
      <FACard title="数据溯源" eyebrow="Source Trace" accent="brand">
        <div className="mb-3 text-[11px] text-[var(--fg-4)]">保留 source refs 与 artifact refs 的只读展示，便于回查 raw / parsed / output 位置。</div>
        <div className="max-h-[360px] overflow-y-auto pr-1">
          <SourceTrace sourceRefs={selectedRun.source_refs} emptyText="当前任务未返回来源引用" />
        </div>
      </FACard>

      {selectedRun.artifact_refs.length > 0 ? (
        <FACard title="关联产物" eyebrow="Artifacts" accent="none">
          <div className="max-h-[220px] overflow-y-auto pr-1">
            <div className="flex flex-wrap gap-2">
              {selectedRun.artifact_refs.map((artifact) => (
                <FASourceTraceBadge
                  key={`${artifact.artifact_id}-${artifact.file_path}`}
                  source={artifact.artifact_type || "artifact"}
                  status={artifact.file_path || artifact.path || "—"}
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
