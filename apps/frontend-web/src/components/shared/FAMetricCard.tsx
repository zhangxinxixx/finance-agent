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
  flat: "text-[var(--fg-5)]",
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
    <article className={`fa-card bg-[var(--bg-card-inner)] px-3.5 py-3 ${className}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">{label}</div>
          <div className="mt-1.5 flex min-w-0 items-baseline gap-1.5">
            <span className="fa-num truncate text-[19px] font-bold leading-none text-[var(--fg-1)]">{value}</span>
            {unit ? <span className="text-[10px] font-semibold text-[var(--fg-4)]">{unit}</span> : null}
          </div>
        </div>
        {status ? <FAStatusPill tone={statusTone}>{status}</FAStatusPill> : null}
      </div>
      <div className="mt-2.5 flex min-h-[14px] items-center justify-between gap-2 text-[10px]">
        {delta ? <span className={`font-semibold ${trendClass[trend]}`}>{delta}</span> : <span />}
        {hint ? <span className="truncate text-[var(--fg-5)]">{hint}</span> : null}
      </div>
    </article>
  );
}
