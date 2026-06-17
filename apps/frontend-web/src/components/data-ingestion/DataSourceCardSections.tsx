import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { Link2 } from "lucide-react";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { compactId } from "@/lib/format";
import {
  boolTone,
  formatAbsoluteTime,
  formatRelativeTime,
  rawStatusTone,
  relationLabel,
  roleLabel,
  roleTone,
  typeIcon,
} from "./DataSourceCard.helpers";

function StageCell({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">{active ? "已完成" : "未完成"}</div>
        <FAStatusPill tone={boolTone(active)}>{active ? "ready" : "idle"}</FAStatusPill>
      </div>
    </div>
  );
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 font-mono text-[11px] text-[var(--fg-3)]">{value}</div>
    </div>
  );
}

export function DataSourceCardHeader({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 space-y-2">
        <div className="flex items-center gap-2 text-[var(--brand-hover)]">
          {typeIcon(source.type)}
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-4)]">{source.type}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill tone={rawStatusTone(source.raw_status)}>{`raw ${source.raw_status}`}</FAStatusPill>
          <FAStatusPill tone={roleTone(source.role)}>{roleLabel(source.role)}</FAStatusPill>
          {source.endpoint ? (
            <span className="inline-flex max-w-full items-center rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1 font-mono text-[10px] text-[var(--fg-4)]">
              {source.endpoint}
            </span>
          ) : null}
        </div>
      </div>
      <FASourceTraceBadge
        source={source.snapshot_id ? compactId(source.snapshot_id, 12, 4) : "无快照"}
        status="snapshot"
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
      <StageCell label="configured" active={source.configured} />
      <StageCell label="raw_ingested" active={source.raw_ingested} />
      <StageCell label="parsed" active={source.parsed} />
      <StageCell label="analysis_ready" active={source.analysis_ready} />
    </div>
  );
}

export function DataSourceMetricsGrid({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <FAMetricCard
        label="latest_raw_time"
        value={formatRelativeTime(source.latest_raw_time ?? null)}
        hint={formatAbsoluteTime(source.latest_raw_time ?? null)}
        status={source.latest_raw_time ? "raw" : "missing"}
        statusTone={source.latest_raw_time ? "info" : "dim"}
      />
      <FAMetricCard
        label="latest_parsed_time"
        value={formatRelativeTime(source.latest_parsed_time ?? null)}
        hint={formatAbsoluteTime(source.latest_parsed_time ?? null)}
        status={source.latest_parsed_time ? "parsed" : "missing"}
        statusTone={source.latest_parsed_time ? "info" : "dim"}
      />
      <FAMetricCard
        label="row_count"
        value={source.row_count.toLocaleString("en-US")}
        hint="当前只读状态返回行数"
        status={source.raw_status}
        statusTone={rawStatusTone(source.raw_status)}
      />
      <FAMetricCard
        label="next_run_time"
        value={formatRelativeTime(source.next_run_time ?? null)}
        hint={formatAbsoluteTime(source.next_run_time ?? null)}
        status={source.last_run_id ? "scheduled" : "pending"}
        statusTone={source.last_run_id ? "warn" : "dim"}
      />
    </div>
  );
}

export function DataSourceMetadataGrid({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <div className="grid gap-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2">
      <MetadataItem label="last_run_id" value={source.last_run_id ?? "不可用"} />
      <MetadataItem label="fallback_for" value={relationLabel(source.fallback_for)} />
      <MetadataItem label="snapshot_id" value={source.snapshot_id ?? "不可用"} />
      <MetadataItem label="fallback_sources" value={relationLabel(source.fallback_sources)} />
    </div>
  );
}

export function DataSourceWarnings({ source }: { source: DataSourceStatusViewModel }) {
  return (
    <>
      {source.notes ? <FAWarningBanner title="Notes" description={source.notes} tone="info" /> : null}

      {source.status_reason ? (
        <FAWarningBanner
          title={source.raw_status === "error" ? "Status Error" : source.raw_status === "warn" ? "Status Warning" : "Status Detail"}
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
      <span className="truncate">source_refs: {source.source_refs.map((ref) => ref.source_ref).join(" · ") || "—"}</span>
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
