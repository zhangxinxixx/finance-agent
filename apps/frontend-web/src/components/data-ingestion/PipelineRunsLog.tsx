import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { formatDateTime } from "@/lib/date";

interface PipelineRunsLogProps {
  sources: DataSourceStatusViewModel[];
}

export function PipelineRunsLog({ sources }: PipelineRunsLogProps) {
  const entries = sources
    .filter((s) => s.latest_raw_time)
    .sort((a, b) => new Date(b.latest_raw_time!).getTime() - new Date(a.latest_raw_time!).getTime())
    .slice(0, 10)
    .map((s) => ({
      time: s.latest_raw_time!,
      label: s.label,
      ok: s.raw_status === "ok",
      detail: s.raw_status === "ok"
        ? `${s.row_count.toLocaleString()} rows`
        : s.error_message ?? s.status_reason ?? s.raw_status,
    }));

  return (
    <div className="flex flex-col rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
        <span className="text-[12px] font-semibold text-[var(--fg-1)]">
          Pipeline 日志
        </span>
        <span className="text-[11px] text-[var(--fg-4)]">最近运行</span>
      </div>
      <div className="flex flex-col">
        {entries.length === 0 ? (
          <div className="px-3 py-6 text-center text-[10px] text-[var(--fg-5)]">暂无运行记录</div>
        ) : (
          entries.map((entry, idx) => (
            <div
              key={`${entry.label}-${idx}`}
              className="flex items-start gap-2 border-b border-[var(--border-faint)] px-3 py-2"
            >
              <div
                className="mt-1 h-[5px] w-[5px] shrink-0 rounded-full"
                style={{ background: entry.ok ? "var(--up)" : "var(--down)" }}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[12px] font-semibold text-[var(--fg-2)]" title={entry.label}>{entry.label}</span>
                  <span className="shrink-0 font-mono text-[10px] text-[var(--fg-5)]">
                    {formatDateTime(entry.time)}
                  </span>
                </div>
                <div className="mt-1 text-[11px] text-[var(--fg-4)]">{entry.detail}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
