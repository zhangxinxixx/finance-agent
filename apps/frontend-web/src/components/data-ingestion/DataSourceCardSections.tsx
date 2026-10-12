import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { Link2 } from "lucide-react";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { operationFieldLabel, operationSourceTypeLabel, operationStatusLabel } from "@/components/operations/operationsLabels";
import {
  boolTone,
  formatAbsoluteTime,
  formatRelativeTime,
  rawStatusTone,
  roleLabel,
  roleTone,
  typeIcon,
} from "./DataSourceCard.helpers";

function StageCell({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-2">
        <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">{active ? "已完成" : "未完成"}</div>
        <FAStatusPill tone={boolTone(active)}>{active ? "已完成" : "未完成"}</FAStatusPill>
      </div>
    </div>
  );
}

function MetadataItem({ label, value, record }: { label: string; value: string; record?: unknown }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 font-mono text-[11px] text-[var(--fg-3)]">{value}</div>
      {record !== undefined ? <div className="mt-2"><EvidenceRecordActions record={record} label={`${label}依据`} /></div> : null}
    </div>
  );
}

export function DataSourceCardHeader({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 space-y-2">
        <div className="flex items-center gap-2 text-[var(--brand-hover)]">
          {typeIcon(source.type)}
          <span className="text-[11px] font-semibold tracking-[0.08em] text-[var(--fg-4)]">{operationSourceTypeLabel(source.type)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill tone={rawStatusTone(source.raw_status)}>{`原始数据：${operationStatusLabel(source.raw_status)}`}</FAStatusPill>
          <FAStatusPill tone={roleTone(source.role)}>{roleLabel(source.role)}</FAStatusPill>
          {source.endpoint ? (
            <EvidenceRecordActions record={{ endpoint: source.endpoint }} url={source.endpoint} label="来源接口依据" />
          ) : null}
        </div>
      </div>
      <FASourceTraceBadge
        source={source.snapshot_id ? "输入快照已登记" : "无快照"}
        status="输入快照"
        tone={source.snapshot_id ? "info" : "dim"}
        snapshotId={source.snapshot_id}
        className="max-w-[150px]"
      />
    </div>
  );
}

export function DataSourceStageGrid({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <StageCell label={operationFieldLabel("configured")} active={source.configured} />
      <StageCell label={operationFieldLabel("raw_ingested")} active={source.raw_ingested} />
      <StageCell label={operationFieldLabel("parsed")} active={source.parsed} />
      <StageCell label={operationFieldLabel("analysis_ready")} active={source.analysis_ready} />
    </div>
  );
}

export function DataSourceMetricsGrid({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <FAMetricCard
        label={operationFieldLabel("latest_raw_time")}
        value={formatRelativeTime(source.latest_raw_time ?? null)}
        hint={formatAbsoluteTime(source.latest_raw_time ?? null)}
        status={source.latest_raw_time ? "已接收" : "缺失"}
        statusTone={source.latest_raw_time ? "info" : "dim"}
      />
      <FAMetricCard
        label={operationFieldLabel("latest_parsed_time")}
        value={formatRelativeTime(source.latest_parsed_time ?? null)}
        hint={formatAbsoluteTime(source.latest_parsed_time ?? null)}
        status={source.latest_parsed_time ? "已解析" : "缺失"}
        statusTone={source.latest_parsed_time ? "info" : "dim"}
      />
      <FAMetricCard
        label={operationFieldLabel("row_count")}
        value={source.row_count == null ? "未返回" : source.row_count.toLocaleString("en-US")}
        hint="当前只读状态返回行数"
        status={operationStatusLabel(source.raw_status)}
        statusTone={rawStatusTone(source.raw_status)}
      />
      <FAMetricCard
        label={operationFieldLabel("next_run_time")}
        value={formatRelativeTime(source.next_run_time ?? null)}
        hint={formatAbsoluteTime(source.next_run_time ?? null)}
        status={source.last_run_id ? "已登记" : "待安排"}
        statusTone={source.last_run_id ? "warn" : "dim"}
      />
    </div>
  );
}

export function DataSourceMetadataGrid({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="grid gap-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2">
      <MetadataItem
        label={operationFieldLabel("last_run_id")}
        value={source.last_run_id ? "已登记" : "未提供"}
        record={source.last_run_id ? { last_run_id: source.last_run_id } : undefined}
      />
      <MetadataItem
        label={operationFieldLabel("fallback_for")}
        value={source.fallback_for.length ? `${source.fallback_for.length} 个来源` : "—"}
        record={source.fallback_for.length ? { fallback_for: source.fallback_for } : undefined}
      />
      <MetadataItem
        label={operationFieldLabel("snapshot_id")}
        value={source.snapshot_id ? "已登记" : "未提供"}
        record={source.snapshot_id ? { snapshot_id: source.snapshot_id } : undefined}
      />
      <MetadataItem
        label={operationFieldLabel("fallback_sources")}
        value={source.fallback_sources.length ? `${source.fallback_sources.length} 个来源` : "—"}
        record={source.fallback_sources.length ? { fallback_sources: source.fallback_sources } : undefined}
      />
    </div>
  );
}

export function DataSourceWarnings({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <>
      {source.notes ? <FAWarningBanner title="补充说明" description={source.notes} tone="info" /> : null}

      {source.status_reason ? (
        <FAWarningBanner
          title={source.raw_status === "error" ? "状态错误" : source.raw_status === "warn" ? "状态需关注" : "状态说明"}
          description={source.status_reason}
          tone={source.raw_status === "error" ? "down" : source.raw_status === "warn" ? "warn" : "info"}
        />
      ) : null}
    </>
  );
}

export function DataSourceRefsFooter({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="flex items-center gap-2 text-[10px] text-[var(--fg-4)]">
      <Link2 size={11} className="text-[var(--brand-hover)]" />
      <span className="truncate">来源引用：{source.source_refs.length ? `${source.source_refs.length} 条，详情中可回查` : "暂无"}</span>
    </div>
  );
}

export function DataSourceTraceFooter({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="border-t border-[var(--border)] pt-4">
      <div className="max-h-[280px] overflow-y-auto pr-1">
        <SourceTrace sourceRefs={source.source_refs} />
      </div>
    </div>
  );
}
