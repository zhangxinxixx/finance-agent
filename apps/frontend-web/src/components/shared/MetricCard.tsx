import type { DashboardMetric, TrendDirection } from "@/types/dashboard";
import { FAStatusPill } from "./FAStatusPill";
import { getStatusMeta } from "./statusMeta";

const trendStyles: Record<TrendDirection, string> = {
  up: "text-finance-bullish",
  down: "text-finance-bearish",
  flat: "text-finance-text-muted",
};

interface MetricCardProps {
  metric: DashboardMetric;
}

function formatValue(value: DashboardMetric["value"], unit?: string) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "number") {
    const formatted = Number.isInteger(value) ? value.toLocaleString("en-US") : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return unit ? `${formatted}${unit}` : formatted;
  }

  return unit ? `${value}${unit}` : value;
}

function MetricStatusPill({ status }: { status: NonNullable<DashboardMetric["status"]> }) {
  const meta = getStatusMeta(status);

  return (
    <FAStatusPill status={status} tone={meta.tone} label={meta.label} className="whitespace-nowrap px-2 py-1">
      {meta.label}
    </FAStatusPill>
  );
}

export function MetricCard({ metric }: MetricCardProps) {
  const trend = metric.trend ?? "flat";

  return (
    <article className="finance-panel group min-w-0 p-2.5 transition-colors duration-200 hover:border-finance-accent/25 hover:bg-[var(--bg-card-inner)]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="finance-metric-label">{metric.label}</div>
          <div className="mt-1 font-mono text-[17px] font-bold leading-none text-finance-text-primary">
            {formatValue(metric.value, metric.unit)}
          </div>
        </div>
        {metric.status ? <MetricStatusPill status={metric.status} /> : null}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px]">
        <span className={`font-semibold ${trendStyles[trend]}`}>{metric.change ?? "—"}</span>
        {metric.note ? <span className="truncate text-finance-text-muted">{metric.note}</span> : null}
      </div>
    </article>
  );
}
