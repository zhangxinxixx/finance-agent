import { Loader2 } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { getDataStatusLabel } from "@/lib/status";
import type { SnapshotRef } from "@/types/snapshot";
import type { StrategyViewModel } from "@/types/strategy";
import { ArtifactRefList, SourceRefList } from "./StrategySourceRefs";

function TraceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5">
      <div className="text-[8px] font-medium uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{value}</div>
    </div>
  );
}

function SnapshotSummary({ title, snapshot }: { title: string; snapshot: SnapshotRef | null | undefined }) {
  if (!snapshot?.snapshot_id) {
    return (
      <div className="rounded-[var(--radius-md)] border border-dashed border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3 text-[11px] text-[var(--fg-5)]">
        {title} 暂无结构化快照。
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-semibold text-[var(--fg-3)]">{title}</div>
        {snapshot.status ? (
          <FAStatusPill tone="info" dot={false}>
            {getDataStatusLabel(snapshot.status)}
          </FAStatusPill>
        ) : null}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <TraceMetric label="snapshot" value={snapshot.snapshot_id} />
        <TraceMetric label="run" value={snapshot.run_id ?? "未绑定"} />
        <TraceMetric label="data date" value={snapshot.dataDate ?? "未知"} />
        <TraceMetric label="inputs" value={String(snapshot.input_snapshot_ids?.length ?? 0)} />
      </div>
    </div>
  );
}

function InputSnapshotList({ snapshots }: { snapshots: SnapshotRef[] }) {
  if (snapshots.length === 0) {
    return (
      <div className="rounded-[var(--radius-md)] border border-dashed border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3 text-[11px] text-[var(--fg-5)]">
        当前策略卡没有返回上游 input snapshots。
      </div>
    );
  }

  return (
    <div className="grid gap-2 md:grid-cols-2">
      {snapshots.map((snapshot) => (
        <div
          key={`${snapshot.snapshot_id ?? "snapshot"}-${snapshot.run_id ?? "run"}`}
          className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="truncate text-[10px] font-semibold text-[var(--fg-2)]">{snapshot.snapshot_id ?? "未知快照"}</div>
            {snapshot.status ? (
              <FAStatusPill tone="info" dot={false}>
                {getDataStatusLabel(snapshot.status)}
              </FAStatusPill>
            ) : null}
          </div>
          <div className="mt-2 space-y-1 text-[10px] text-[var(--fg-4)]">
            <div>run: {snapshot.run_id ?? "未绑定"}</div>
            <div>data date: {snapshot.dataDate ?? "未知"}</div>
            <div>inputs: {snapshot.input_snapshot_ids?.length ?? 0}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function StrategyDataTraceSection({
  data,
  isTraceLoading = false,
  traceError = null,
}: {
  data: StrategyViewModel;
  isTraceLoading?: boolean;
  traceError?: Error | null;
}) {
  const trace = data.source_trace ?? null;

  return (
    <FACard title="数据溯源" eyebrow="Trace" bodyClassName="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">来源引用</div>
          <SourceRefList refs={data.source_refs} />
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">产物引用</div>
          <ArtifactRefList refs={data.artifact_refs} />
        </div>
      </div>

      <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[10px] font-semibold text-[var(--fg-2)]">结构化 trace drilldown</div>
            <div className="mt-1 text-[11px] leading-5 text-[var(--fg-5)]">
              直接消费 `/api/source-trace/by-strategy/{'{'}strategy_card_id{'}'}`，补足 snapshot、上游 inputs 与关联产物链路。
            </div>
          </div>
          {trace ? (
            <FAStatusPill tone="info" dot={false}>
              {getDataStatusLabel(trace.status)}
            </FAStatusPill>
          ) : null}
        </div>

        {isTraceLoading ? (
          <div className="mt-3 flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[11px] text-[var(--fg-4)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--brand)]" />
            <span>正在加载结构化 trace…</span>
          </div>
        ) : null}

        {traceError ? (
          <div className="mt-3 rounded-[var(--radius-md)] border border-[rgba(239,68,68,0.18)] bg-[rgba(239,68,68,0.08)] px-3 py-2 text-[11px] text-[var(--down)]">
            结构化 trace 拉取失败：{traceError.message}
          </div>
        ) : null}

        {trace ? (
          <div className="mt-3 space-y-3">
            <SnapshotSummary title="当前快照" snapshot={trace.snapshot} />

            <div className="grid gap-2 sm:grid-cols-4">
              <TraceMetric label="sources" value={String(trace.source_refs.length)} />
              <TraceMetric label="artifacts" value={String(trace.artifact_refs.length)} />
              <TraceMetric label="inputs" value={String(trace.input_snapshots?.length ?? 0)} />
              <TraceMetric label="related" value={String(trace.related_artifacts?.length ?? 0)} />
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
                <div className="mb-2 text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">结构化来源</div>
                <SourceTrace compact sourceRefs={trace.source_refs} emptyText="结构化 trace 暂无来源记录。" />
              </div>
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
                <div className="mb-2 text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">结构化产物</div>
                <ArtifactRefList refs={trace.artifact_refs} />
                {trace.related_artifacts && trace.related_artifacts.length > 0 ? (
                  <div className="mt-3 border-t border-[var(--border-faint)] pt-3">
                    <div className="mb-2 text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">关联产物</div>
                    <ArtifactRefList refs={trace.related_artifacts} />
                  </div>
                ) : null}
              </div>
            </div>

            <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
              <div className="mb-2 text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">上游输入快照</div>
              <InputSnapshotList snapshots={trace.input_snapshots ?? []} />
            </div>
          </div>
        ) : !isTraceLoading && !traceError ? (
          <FAEmptyState
            title="暂无结构化 trace"
            description="当前策略卡还没有独立的 source-trace 结果，页面继续保留 strategy card 自带的 source refs / artifact refs。"
            className="mt-3 py-5"
          />
        ) : null}
      </div>
    </FACard>
  );
}
