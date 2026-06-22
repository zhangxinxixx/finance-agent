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
  degradedCount: number;
  dataDate?: string | null;
  stalenessDays?: number | null;
  lastRun?: string | null;
  onRefresh?: () => void;
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

export function IngestionSummaryBar({
  summary,
  pipelineStats,
  degradedCount,
  dataDate = null,
  stalenessDays = null,
  lastRun,
  onRefresh,
}: IngestionSummaryBarProps) {
  const total = pipelineStats.total;
  const freshnessColor =
    stalenessDays === null || stalenessDays === undefined
      ? "var(--fg-5)"
      : stalenessDays > 7
        ? "var(--down)"
        : stalenessDays > 2
          ? "var(--warn)"
          : "var(--up)";
  const freshnessLabel =
    stalenessDays === null || stalenessDays === undefined
      ? "未标注"
      : stalenessDays === 0
        ? "今天"
        : stalenessDays === 1
          ? "1天前"
          : `${stalenessDays}天前`;

  return (
    <div className="data-ingestion-summary-bar flex items-center gap-2 shrink-0 flex-wrap">
      <div className="mr-2 min-w-0 flex flex-1 flex-col">
        <span className="text-[14px] font-bold text-[var(--fg-1)]">数据接入运维台</span>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
          <span className="font-semibold text-[var(--fg-3)]">数据接入控制台</span>
          <span className="text-[var(--fg-6)]">/</span>
          <span>{total} 个数据源</span>
          <span className="text-[var(--fg-6)]">/</span>
          <span>{degradedCount} 个待处理项</span>
          {dataDate ? (
            <>
              <span className="text-[var(--fg-6)]">/</span>
              <span>数据日期</span>
              <span className="fa-num font-semibold" style={{ color: freshnessColor }}>{dataDate}</span>
              <span
                className="rounded-full px-1.5 py-px text-[9px] font-semibold"
                style={{ background: `${freshnessColor}18`, color: freshnessColor }}
              >
                {freshnessLabel}
              </span>
            </>
          ) : null}
          {lastRun ? (
            <>
              <span className="text-[var(--fg-6)]">/</span>
              <span>最近运行</span>
              <span className="fa-num text-[var(--fg-3)]">{lastRun}</span>
            </>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {summary && (
          <KpiCard
            label="报告可用度"
            value={summary.available_count}
            total={summary.source_count}
            icon={Activity}
            color={summary.available_count / Math.max(1, summary.source_count) >= 0.8 ? "var(--up)" : "var(--warn)"}
          />
        )}

        {summary && (
          <KpiCard label="可用" value={summary.available_count} icon={CheckCircle2} color="var(--up)" />
        )}

        {summary && (
          <KpiCard label="部分返回" value={summary.partial_count} icon={RefreshCw} color="var(--warn)" />
        )}

        <KpiCard label="原始就绪" value={pipelineStats.rawReady} total={total} icon={Database} color="var(--brand)" />
        <KpiCard label="解析就绪" value={pipelineStats.parseReady} total={total} icon={Layers} color="var(--brand)" />
        <KpiCard label="快照就绪" value={pipelineStats.snapshotReady} total={total} icon={Zap} color="var(--brand-cyan)" />
        <KpiCard label="消费就绪" value={pipelineStats.consumerReady} total={total} icon={CheckCircle2} color="var(--brand-cyan)" />

        {summary && summary.error_count > 0 && (
          <KpiCard label="异常" value={summary.error_count} icon={AlertTriangle} color="var(--down)" />
        )}
      </div>

      {onRefresh ? (
        <button
          type="button"
          onClick={onRefresh}
          className="dashboard-command-button ml-auto"
          title="刷新数据接入状态"
        >
          <RefreshCw size={13} />
          <span>刷新</span>
        </button>
      ) : null}
    </div>
  );
}
