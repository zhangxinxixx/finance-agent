import { readableWarning } from "@/lib/researchReading";

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
  dataDate?: string | null;
}

const accentDefaults: Record<string, string> = {
  XAUUSD: "var(--fa-important)",
  "XAUUSD 现货": "var(--fa-important)",
  "GC 期货": "var(--fa-important)",
  DXY: "var(--brand)",
  US10Y: "var(--info)",
  REAL10Y: "var(--warn)",
};

const PRIMARY_KPI_LABELS = new Set(["XAUUSD", "XAUUSD 现货", "GC 期货", "DXY", "US10Y", "REAL 10Y"]);
const compactLabelMap: Record<string, string> = {
  XAUUSD: "黄金现货", "XAUUSD 现货": "黄金现货", "GC 期货": "黄金期货",
  DXY: "美元指数", US02Y: "两年美债收益率", US10Y: "十年美债收益率",
  "REAL 10Y": "十年实际利率", "2Y-3M": "短端期限利差", RESERVES: "银行准备金",
  RRP: "逆回购余额", TGA: "财政账户余额",
};

function compactImpactLabel(impactLabel: NonNullable<CompactKPICardProps["impactLabel"]>) {
  if (impactLabel === "利多黄金") return "↑ 利多";
  if (impactLabel === "利空黄金") return "↓ 利空";
  if (impactLabel === "混合") return "~ 混合";
  if (impactLabel === "中性") return "中性";
  return "—";
}

export interface KpiStatusMeta {
  label: string;
  color: string;
  background: string;
  border: string;
  dot: string;
}

export function resolveKpiDataStatus(dataStatus: string): KpiStatusMeta {
  const normalized = dataStatus.trim().toLowerCase();
  if (normalized.includes("error") || normalized.includes("failed")) {
    return { label: "读取失败", color: "var(--down)", background: "var(--down-soft)", border: "var(--down-border)", dot: "var(--down)" };
  }
  if (normalized.includes("mock") || normalized.includes("fallback")) {
    return { label: "模拟 / 回退", color: "var(--warn)", background: "var(--warn-soft)", border: "var(--warn-border)", dot: "var(--warn)" };
  }
  if (normalized.includes("stale") || normalized.includes("expired")) {
    return { label: "已过期", color: "var(--warn)", background: "var(--warn-soft)", border: "var(--warn-border)", dot: "var(--warn)" };
  }
  if (normalized.includes("unavailable") || normalized.includes("missing")) {
    return { label: "不可用", color: "var(--fg-4)", background: "var(--bg-panel)", border: "var(--border-faint)", dot: "var(--fg-5)" };
  }
  if (normalized.includes("unknown") || !normalized) {
    return { label: "状态未知", color: "var(--fg-4)", background: "var(--bg-panel)", border: "var(--border-faint)", dot: "var(--fg-5)" };
  }
  if (normalized.includes("warn") || normalized.includes("partial") || normalized.includes("degraded")) {
    return { label: "部分可用", color: "var(--warn)", background: "var(--warn-soft)", border: "var(--warn-border)", dot: "var(--warn)" };
  }
  if (normalized.includes("ok") || normalized.includes("available") || normalized.includes("live") || normalized.includes("success")) {
    return { label: "可用", color: "var(--up)", background: "var(--up-soft)", border: "var(--up-border)", dot: "var(--up)" };
  }
  return { label: "状态未知", color: "var(--fg-4)", background: "var(--bg-panel)", border: "var(--border-faint)", dot: "var(--fg-5)" };
}

function statusDotColor(dataStatus: string) {
  return resolveKpiDataStatus(dataStatus).dot;
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
  dataDate,
}: CompactKPICardProps) {
  const impactTone =
    impactLabel === "利多黄金" ? "up"
      : impactLabel === "利空黄金" ? "down"
        : impactLabel === "混合" ? "warn"
          : impactLabel === "数据不足" ? "muted"
            : "neutral";
  const fallbackAccent = accent ?? accentDefaults[label] ?? "var(--brand)";
  const statusMeta = resolveKpiDataStatus(dataStatus);
  const accentColor = impactLabel ? impactAccent(impactTone) : fallbackAccent;
  const borderColor = impactLabel ? impactBorder(impactTone) : `color-mix(in srgb, ${fallbackAccent} 34%, var(--border-faint))`;
  const changeColor =
    trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : "var(--fa-text-muted)";
  const trendColor =
    impactTone === "muted"
      ? "var(--dashboard-rule)"
      : sparkColor ?? (trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : fallbackAccent);
  const displayLabel = compactLabelMap[label] ?? label;
  const displayUnit = unit === "USD/oz" ? "美元/盎司" : unit === "bp" ? "基点" : unit;
  const tooltipText = [
    `${displayLabel} ${value}${displayUnit ? ` ${displayUnit}` : ""}`,
    delta ? `变化 ${delta}` : null,
    subtitle ? readableWarning(subtitle.replace(/\bmacro_latest\b/g, "宏观最新快照")) : null,
    impactLabel ?? null,
    `数据状态 ${statusMeta.label}`,
  ].filter(Boolean).join(" · ");
  const impactText = impactLabel ? compactImpactLabel(impactLabel) : null;
  const priority = PRIMARY_KPI_LABELS.has(label) ? "primary" : "secondary";

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
          <span className="fa-unit dashboard-kpi-unit">{displayUnit}</span>
        ) : null}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span
          className="dashboard-kpi-status"
          style={{
            color: statusMeta.color,
            background: statusMeta.background,
            borderColor: statusMeta.border,
          }}
        >
          {statusMeta.label}
        </span>
        <time className="fa-muted-text min-w-0 break-words" dateTime={dataDate ?? undefined}>
          观测 {dataDate || "时间未知"}
        </time>
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
          {subtitle ? <span className="dashboard-kpi-subtitle">{readableWarning(subtitle.replace(/\bmacro_latest\b/g, "宏观最新快照"))}</span> : null}
        </div>
      </div>
    </article>
  );
}
