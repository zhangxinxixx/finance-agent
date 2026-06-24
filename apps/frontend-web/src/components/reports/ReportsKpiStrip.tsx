import type { ReportIndexItem } from "@/types/reports";

const KPI_METRICS = [
  { key: "today", label: "今日报告", color: "#10b981", getValue: (_r: ReportIndexItem[], dates: string[]) => dates.length > 0 ? "1" : "0" },
  { key: "snapshot", label: "Snapshot绑定", color: "#3b82f6", getValue: (r: ReportIndexItem[]) => String(r.filter((i) => i.run_id).length) },
  { key: "review", label: "待人工复核", color: "#a78bfa", getValue: () => "0" },
  { key: "published", label: "已发布", color: "#10b981", getValue: (r: ReportIndexItem[]) => String(r.filter((i) => i.available).length) },
  { key: "exportable", label: "可导出", color: "#06b6d4", getValue: (r: ReportIndexItem[]) => String(r.filter((i) => i.available).length) },
  { key: "latest", label: "最新生成", color: "#f59e0b", getValue: (r: ReportIndexItem[]) => {
    const dates = Array.from(new Set(r.map((i) => i.trade_date).filter(Boolean)));
    return dates.length > 0 ? dates.sort((a, b) => b.localeCompare(a))[0] : "-";
  }},
];

export function ReportsKpiStrip({
  reports,
  availableDates,
}: {
  reports: ReportIndexItem[];
  availableDates: string[];
}) {
  return (
    <div className="mb-1.5 grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--border-faint)] sm:grid-cols-3 xl:grid-cols-6">
      {KPI_METRICS.map((kpi) => (
        <div key={kpi.key} className="bg-[var(--bg-card)] px-3 py-2">
          <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">
            {kpi.label}
          </div>
          <div
            className="mt-1 font-mono text-[12px] font-semibold leading-none"
            style={{
              color: kpi.color,
              fontVariantNumeric: "tabular-nums",
            }}
          >
              {kpi.getValue(reports, availableDates)}
          </div>
        </div>
      ))}
    </div>
  );
}
