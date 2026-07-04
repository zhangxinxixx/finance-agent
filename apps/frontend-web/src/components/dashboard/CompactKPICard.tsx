interface CompactKPICardProps {
  label: string;
  value: string;
  delta?: string;
  trend?: "up" | "down" | "flat";
  unit?: string;
  sparkColor?: string;
  accent?: string;
  subtitle?: string;
  impactLabel: "利多黄金" | "利空黄金" | "中性" | "混合" | "数据不足";
  dataStatus: string;
}

const accentDefaults: Record<string, string> = {
  XAUUSD: "var(--fa-important)",
  DXY: "var(--brand)",
  US10Y: "var(--info)",
  REAL10Y: "var(--warn)",
};

export function CompactKPICard({
  label,
  value,
  delta,
  trend = "flat",
  unit,
  sparkColor,
  accent,
  impactLabel,
  dataStatus,
}: CompactKPICardProps) {
  const accentColor = accent ?? accentDefaults[label] ?? "var(--brand)";
  const changeColor =
    trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : "var(--fa-text-muted)";

  return (
    <article
      className="dashboard-kpi-card"
      title={`${label} ${value}${delta ? ` ${delta}` : ""} · ${impactLabel} · ${dataStatus}`}
      style={{
        ["--kpi-accent" as string]: accentColor,
        ["--kpi-trend" as string]: sparkColor ?? (trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : accentColor),
      }}
    >
      <div className="dashboard-kpi-label-row">
        <span className="fa-code-label dashboard-kpi-label">{label}</span>
      </div>

      <div className="dashboard-kpi-value-row">
        <span className="fa-price-num fa-price-num--sm dashboard-kpi-value" title={value}>{value}</span>
        {unit ? (
          <span className="fa-unit dashboard-kpi-unit">{unit}</span>
        ) : null}
      </div>

      <div className="dashboard-kpi-meta-row">
        <div className="dashboard-kpi-meta-text">
          {delta ? (
            <span
              className="fa-delta dashboard-kpi-delta"
              style={{
                color: changeColor,
              }}
            >
              {delta}
            </span>
          ) : null}
        </div>
      </div>
    </article>
  );
}
