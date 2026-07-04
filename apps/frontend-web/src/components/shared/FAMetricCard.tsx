import type { ReactNode } from "react";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";

interface FAMetricCardProps {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  hint?: ReactNode;
  delta?: ReactNode;
  trend?: "up" | "down" | "flat";
  status?: ReactNode;
  statusTone?: FAStatusTone;
  className?: string;
}

const trendClass: Record<NonNullable<FAMetricCardProps["trend"]>, string> = {
  up: "text-[var(--up)]",
  down: "text-[var(--down)]",
  flat: "text-[var(--fa-text-label)]",
};

export function FAMetricCard({
  label,
  value,
  unit,
  hint,
  delta,
  trend = "flat",
  status,
  statusTone = "neutral",
  className = "",
}: FAMetricCardProps) {
  return (
    <article className={`fa-card bg-[var(--bg-card-inner)] px-4 py-3.5 ${className}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="fa-code-label truncate">{label}</div>
          <div className="mt-2 flex min-w-0 items-baseline gap-2">
            <span className="fa-price-num truncate">{value}</span>
            {unit ? <span className="fa-unit">{unit}</span> : null}
          </div>
        </div>
        {status ? <FAStatusPill tone={statusTone}>{status}</FAStatusPill> : null}
      </div>
      <div className="mt-3 flex min-h-[16px] items-center justify-between gap-2 text-[11px]">
        {delta ? <span className={`font-semibold ${trendClass[trend]}`}>{delta}</span> : <span />}
        {hint ? <span className="truncate text-[var(--fa-text-label)]">{hint}</span> : null}
      </div>
    </article>
  );
}
