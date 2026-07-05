interface CompactKPICardProps {
  label: string;
  value: string;
  delta?: string;
  trend?: "up" | "down" | "flat";
  unit?: string;
  sparkColor?: string;
  accent?: string;
  subtitle?: string;
  impactLabel?: "利多黄金" | "利空黄金" | "中性" | "混合" | "数据不足";
  dataStatus: string;
}

const accentDefaults: Record<string, string> = {
  XAUUSD: "var(--fa-important)",
  DXY: "var(--brand)",
  US10Y: "var(--info)",
  REAL10Y: "var(--warn)",
};

const PRIMARY_KPI_LABELS = new Set(["XAUUSD", "DXY", "US10Y", "REAL 10Y"]);
const compactLabelMap: Record<string, string> = {
  XAUUSD: "XAU",
  DXY: "DXY",
  US02Y: "2Y",
  US10Y: "10Y",
  "REAL 10Y": "R10Y",
  "2Y-3M": "2Y3M",
  RESERVES: "RES",
};

function compactImpactLabel(impactLabel: NonNullable<CompactKPICardProps["impactLabel"]>) {
  if (impactLabel === "利多黄金") return "↑ 利多";
  if (impactLabel === "利空黄金") return "↓ 利空";
  if (impactLabel === "混合") return "~ 混合";
  if (impactLabel === "中性") return "中性";
  return "—";
}

function statusDotColor(dataStatus: string) {
  const normalized = dataStatus.toLowerCase();
  if (normalized.includes("unavailable")) return "var(--fg-6)";
  if (normalized.includes("warn")) return "var(--warn)";
  if (normalized.includes("error")) return "var(--down)";
  return "var(--up)";
}

function impactAccent(impactTone: "up" | "down" | "warn" | "muted" | "neutral") {
  if (impactTone === "up") return "var(--up)";
  if (impactTone === "down") return "var(--down)";
  if (impactTone === "warn") return "var(--fa-important)";
  return "var(--fa-text-muted)";
}

function impactBorder(impactTone: "up" | "down" | "warn" | "muted" | "neutral") {
  if (impactTone === "up") return "var(--up-border)";
  if (impactTone === "down") return "var(--down-border)";
  if (impactTone === "warn") return "var(--fa-important-border)";
  return "var(--border-faint)";
}

export function CompactKPICard({
  label,
  value,
  delta,
  trend = "flat",
  unit,
  sparkColor,
  accent,
  subtitle,
  impactLabel,
  dataStatus,
}: CompactKPICardProps) {
  const impactTone =
    impactLabel === "利多黄金" ? "up"
      : impactLabel === "利空黄金" ? "down"
        : impactLabel === "混合" ? "warn"
          : impactLabel === "数据不足" ? "muted"
            : "neutral";
  const fallbackAccent = accent ?? accentDefaults[label] ?? "var(--brand)";
  const accentColor = impactLabel ? impactAccent(impactTone) : fallbackAccent;
  const borderColor = impactLabel ? impactBorder(impactTone) : `color-mix(in srgb, ${fallbackAccent} 34%, var(--border-faint))`;
  const changeColor =
    trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : "var(--fa-text-muted)";
  const trendColor =
    impactTone === "muted"
      ? "var(--dashboard-rule)"
      : sparkColor ?? (trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : fallbackAccent);
  const tooltipText = [
    `${label} ${value}${unit ? ` ${unit}` : ""}`,
    delta ? `变化 ${delta}` : null,
    subtitle ?? null,
    impactLabel ?? null,
    `数据状态 ${dataStatus}`,
  ].filter(Boolean).join(" · ");
  const impactText = impactLabel ? compactImpactLabel(impactLabel) : null;
  const priority = PRIMARY_KPI_LABELS.has(label) ? "primary" : "secondary";
  const displayLabel = compactLabelMap[label] ?? label;

  return (
    <article
      className="dashboard-kpi-card"
      data-trend={trend}
      data-impact={impactTone}
      data-priority={priority}
      title={tooltipText}
      style={{
        ["--kpi-accent" as string]: accentColor,
        ["--kpi-border" as string]: borderColor,
        ["--kpi-trend" as string]: trendColor,
        ["--kpi-status-dot" as string]: statusDotColor(dataStatus),
      }}
    >
      <div className="dashboard-kpi-label-row">
        <span className="fa-code-label dashboard-kpi-label" title={tooltipText}>{displayLabel}</span>
        {impactText ? <span className="fa-compact-label dashboard-kpi-impact">{impactText}</span> : null}
      </div>

      <div className="dashboard-kpi-value-row">
        <span className="fa-price-num fa-price-num--sm dashboard-kpi-value" title={tooltipText}>{value}</span>
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
          {subtitle ? <span className="dashboard-kpi-subtitle" title={tooltipText}>{subtitle}</span> : null}
        </div>
      </div>
    </article>
  );
}
