import type { ReactNode } from "react";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";

interface FinanceMetricCardProps {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  description?: ReactNode;
  delta?: ReactNode;
  trend?: "up" | "down" | "flat";
  status?: ReactNode;
  statusTone?: FAStatusTone;
  tone?: "neutral" | "brand" | "gold" | "up" | "down" | "warn" | "info";
  className?: string;
}

const trendClass: Record<NonNullable<FinanceMetricCardProps["trend"]>, string> = {
  up: "text-[var(--up)]",
  down: "text-[var(--down)]",
  flat: "text-[var(--fa-text-label)]",
};

const toneClass: Record<NonNullable<FinanceMetricCardProps["tone"]>, string> = {
  neutral: "",
  brand: "finance-metric-card--brand",
  gold: "finance-metric-card--gold",
  up: "finance-metric-card--up",
  down: "finance-metric-card--down",
  warn: "finance-metric-card--warn",
  info: "finance-metric-card--info",
};

export function FinanceMetricCard({
  label,
  value,
  unit,
  description,
  delta,
  trend = "flat",
  status,
  statusTone = "neutral",
  tone = "neutral",
  className = "",
}: FinanceMetricCardProps) {
  return (
    <article className={`finance-metric-card ${toneClass[tone]} ${className}`}>
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="fa-code-label truncate">{label}</div>
          <div className="mt-2 flex min-w-0 items-baseline gap-2">
            <span className="fa-price-num min-w-0 truncate">{value}</span>
            {unit ? <span className="fa-unit shrink-0">{unit}</span> : null}
          </div>
        </div>
        {status ? <FAStatusPill tone={statusTone}>{status}</FAStatusPill> : null}
      </div>

      {description || delta ? (
        <div className="mt-3 flex min-h-[18px] min-w-0 items-center justify-between gap-3 text-[12px]">
          {delta ? <span className={`shrink-0 font-semibold ${trendClass[trend]}`}>{delta}</span> : null}
          {description ? <span className="min-w-0 truncate text-[var(--fa-text-label)]">{description}</span> : null}
        </div>
      ) : null}
    </article>
  );
}
