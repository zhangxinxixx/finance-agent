import type { DataStatusSummaryViewModel } from "@/types/data-ingestion";
import { Activity, AlertTriangle, CheckCircle2, Database, Layers, RefreshCw, Zap } from "lucide-react";

interface IngestionSummaryBarProps {
  summary: DataStatusSummaryViewModel | null;
  pipelineStats: {
    rawReady: number;
    parseReady: number;
    snapshotReady: number;
    consumerReady: number;
    total: number;
  };
  lastRun?: string | null;
}

/** A single compact KPI card */
function KpiCard({
  label,
  value,
  total,
  icon: Icon,
  color,
}: {
  label: string;
  value: number;
  total?: number;
  icon: typeof Database;
  color: string;
}) {
  const ratio = total && total > 0 ? value / total : 0;
  const barColor = ratio >= 0.8 ? "var(--up)" : ratio >= 0.5 ? "var(--warn)" : "var(--down)";

  return (
    <div
      className="flex flex-col gap-1 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] px-2.5 py-2 min-w-[90px]"
    >
      <div className="flex items-center gap-1.5">
        <Icon size={10} style={{ color }} />
        <span className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">{label}</span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="fa-num text-[16px] font-bold" style={{ color }}>{value}</span>
        {total !== undefined && (
          <span className="fa-num text-[10px] text-[var(--fg-5)]">/ {total}</span>
        )}
      </div>
      {total !== undefined && total > 0 && (
        <div className="w-full h-[3px] rounded-[1.5px] bg-[var(--bg-terminal)] overflow-hidden">
          <div
            className="h-full rounded-[1.5px] transition-[width] duration-500"
            style={{ width: `${Math.min(100, ratio * 100)}%`, background: barColor }}
          />
        </div>
      )}
    </div>
  );
}

export function IngestionSummaryBar({ summary, pipelineStats, lastRun }: IngestionSummaryBarProps) {
  const total = pipelineStats.total;

  return (
    <div className="flex items-center gap-2 shrink-0 flex-wrap">
      {/* Title */}
      <div className="flex flex-col mr-2">
        <span className="text-[14px] font-bold text-[var(--fg-1)]">数据接入运维台</span>
        <span className="text-[9px] text-[var(--fg-5)]">
          Data Ingestion Console · {total} sources
          {lastRun ? ` · as of ${lastRun}` : ""}
        </span>
      </div>

      {/* KPI cards */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {/* Report availability */}
        {summary && (
          <KpiCard
            label="报告可用度"
            value={summary.available_count}
            total={summary.source_count}
            icon={Activity}
            color={summary.available_count / Math.max(1, summary.source_count) >= 0.8 ? "var(--up)" : "var(--warn)"}
          />
        )}

        {/* LIVE */}
        {summary && (
          <KpiCard label="LIVE" value={summary.available_count} icon={CheckCircle2} color="var(--up)" />
        )}

        {/* PARTIAL */}
        {summary && (
          <KpiCard label="PARTIAL" value={summary.partial_count} icon={RefreshCw} color="var(--warn)" />
        )}

        {/* Pipeline KPIs */}
        <KpiCard label="Raw Ready" value={pipelineStats.rawReady} total={total} icon={Database} color="var(--brand)" />
        <KpiCard label="Parse Ready" value={pipelineStats.parseReady} total={total} icon={Layers} color="var(--brand)" />
        <KpiCard label="Snapshot" value={pipelineStats.snapshotReady} total={total} icon={Zap} color="var(--brand-cyan)" />
        <KpiCard label="Consumer" value={pipelineStats.consumerReady} total={total} icon={CheckCircle2} color="var(--brand-cyan)" />

        {/* Critical */}
        {summary && summary.error_count > 0 && (
          <KpiCard label="CRITICAL" value={summary.error_count} icon={AlertTriangle} color="var(--down)" />
        )}
      </div>

      {/* Last run */}
      {lastRun && (
        <div className="ml-auto flex flex-col items-end shrink-0">
          <span className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">Last Run</span>
          <span className="fa-num text-[11px] font-bold text-[var(--fg-3)]">{lastRun}</span>
        </div>
      )}
    </div>
  );
}
