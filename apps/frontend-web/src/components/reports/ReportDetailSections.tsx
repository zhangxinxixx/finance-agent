import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { SourceTrace } from "@/components/shared/SourceTrace";
import type { ArtifactRef } from "@/types/artifact";
import { reportFamilyLabel, shortId, statusTone } from "@/components/reports/reportDetailMeta";
import { getDataStatusLabel } from "@/lib/status";
import type { SourceRef } from "@/types/common";
import type { ReportDetailView } from "@/types/reports";

function InlineMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="inline-flex min-w-0 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1">
      <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</span>
      <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{value}</span>
    </div>
  );
}

function ArtifactSummaryList({ items }: { items: ArtifactRef[] }) {
  if (items.length === 0) {
    return <div className="text-[11px] text-[var(--fg-5)]">当前报告未返回 artifact_refs。</div>;
  }

  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div
          key={`${item.artifact_id ?? item.path ?? item.file_path ?? "artifact"}-${index}`}
          className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] font-semibold text-[var(--fg-2)]">{item.artifact_type ?? "unknown"}</div>
            <div className="text-[10px] text-[var(--fg-5)]">{item.asOf ?? "-"}</div>
          </div>
          <div className="mt-2 break-all font-mono text-[10px] leading-5 text-[var(--fg-4)]">{item.path ?? item.file_path ?? "-"}</div>
        </div>
      ))}
    </div>
  );
}

export function ReportDetailHero({
  data,
  sourceRefs,
  metrics,
  onRefresh,
}: {
  data: ReportDetailView;
  sourceRefs: SourceRef[];
  metrics: Array<{ label: string; value: string }>;
  onRefresh: () => void;
}) {
  return (
    <FACard
      title="报告详情"
      eyebrow="报告详情"
      accent="brand"
      headerClassName="py-2"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to="/reports"
            className="rounded-[var(--radius-md)] border border-[var(--border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-3)]"
          >
            返回列表
          </Link>
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-2)]"
          >
            刷新
          </button>
        </div>
      }
      bodyClassName="space-y-3"
    >
      <div className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-[10px]">
              <Link to="/reports" className="text-[var(--brand-hover)] hover:text-[var(--brand)]">
                报告中心
              </Link>
              <span className="text-[var(--fg-5)]">/</span>
              <span className="text-[var(--fg-4)]">{reportFamilyLabel(data.meta.family)}</span>
            </div>
            <div className="mt-1 text-[13px] font-semibold leading-tight text-[var(--fg-1)]">{data.meta.title}</div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone={statusTone(data.data_status)} className="text-[8px]">
              {getDataStatusLabel(data.data_status)}
            </FAStatusPill>
            <FAStatusPill tone="neutral" className="text-[8px]">
              {data.meta.lifecycle_status}
            </FAStatusPill>
            {data.meta.review_status ? (
              <FAStatusPill tone="info" className="text-[8px]">
                {data.meta.review_status}
              </FAStatusPill>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap gap-1">
          {metrics.map((metric) => (
            <InlineMetaItem key={metric.label} label={metric.label} value={metric.value} />
          ))}
          <FASourceTraceBadge
            source={shortId(data.report_id)}
            status="report_id"
            tone="info"
            snapshotId={data.meta.snapshot_id ?? null}
            className="max-w-[180px]"
          />
          {sourceRefs.slice(0, 2).map((source, index) => (
            <FASourceTraceBadge
              key={`${source.source_ref}-${source.snapshot_id ?? index}`}
              source={source.label ?? source.source_ref}
              status={source.status ?? "trace"}
              tone="dim"
              snapshotId={source.snapshot_id ?? null}
              className="max-w-[180px]"
            />
          ))}
          {sourceRefs.length > 2 ? (
            <span className="inline-flex items-center rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1 text-[9px] text-[var(--fg-5)]">
              另 {sourceRefs.length - 2} 条
            </span>
          ) : null}
        </div>
      </div>
    </FACard>
  );
}

export function ReportDetailSourceSidebar({
  data,
  sourceRefs,
}: {
  data: ReportDetailView;
  sourceRefs: SourceRef[];
}) {
  return (
    <>
      <FACard title="数据溯源" eyebrow="数据血缘" accent="warn">
        <div className="mb-3 text-[11px] text-[var(--fg-4)]">保留来源链路、快照、截至时间和数据日期的只读展示。</div>
        <div className="max-h-[360px] overflow-y-auto pr-1">
          <SourceTrace sourceRefs={sourceRefs} emptyText="当前报告未返回来源引用" />
        </div>
      </FACard>

      <FACard title="报告产物索引" eyebrow="artifact_refs" accent="info">
        <div className="mb-3 text-[11px] text-[var(--fg-4)]">这里展示报告级产物索引，便于和“分析输入”页签里的每条输入/输出产物对照。</div>
        <div className="max-h-[320px] overflow-y-auto pr-1">
          <ArtifactSummaryList items={data.artifact_refs} />
        </div>
      </FACard>

      {data.source_trace?.snapshot_id || data.source_trace?.run_id ? (
        <FACard title="溯源信封" eyebrow="快照上下文" accent="brand">
          <div className="grid gap-3">
            <FAMetricCard label="运行编号" value={shortId(data.source_trace?.run_id ?? undefined)} hint="关联运行" />
            <FAMetricCard label="快照编号" value={shortId(data.source_trace?.snapshot_id ?? undefined)} hint="关联快照" />
            <FAMetricCard label="数据日期" value={data.source_trace?.dataDate ?? "-"} hint="数据日期" />
            <FAMetricCard label="产出时间" value={data.source_trace?.asOf ?? "-"} hint="产出时间" />
          </div>
        </FACard>
      ) : null}
    </>
  );
}
