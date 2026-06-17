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
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(6, 1fr)",
        gap: 8,
        padding: "8px 10px",
        borderBottom: "1px solid var(--border)",
        flexShrink: 0,
      }}
    >
      {KPI_METRICS.map((kpi) => (
        <div
          key={kpi.key}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 10px",
            background: "var(--bg-card)",
            border: "1px solid var(--border-faint)",
            borderRadius: "var(--radius-lg)",
          }}
        >
          <div>
            <div
              style={{
                fontSize: 9,
                color: "var(--fg-5)",
                marginBottom: 2,
                lineHeight: 1.3,
              }}
            >
              {kpi.label}
            </div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: kpi.color,
                fontFamily: "var(--font-mono)",
                fontVariantNumeric: "tabular-nums",
                lineHeight: 1.2,
              }}
            >
              {kpi.getValue(reports, availableDates)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
