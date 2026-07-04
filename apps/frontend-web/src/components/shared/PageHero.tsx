import type { ReactNode } from "react";
import { FACard } from "./FACard";
import { FAStatusPill } from "./FAStatusPill";

interface PageHeroProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  metrics?: Array<{ label: ReactNode; value: ReactNode; tone?: "brand" | "gold" | "neutral" | "up" | "down" | "warn" | "info" }>;
  className?: string;
}

export function PageHero({ eyebrow, title, description, status, actions, metrics, className = "" }: PageHeroProps) {
  return (
    <FACard className={`page-hero ${className}`} bodyClassName="space-y-4" density="spacious">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow ? <div className="fa-eyebrow">{eyebrow}</div> : null}
          <div className="fa-title mt-1 text-[20px] font-semibold leading-tight">{title}</div>
          {description ? <div className="fa-muted-text mt-2 max-w-3xl leading-6">{description}</div> : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {status}
          {actions}
        </div>
      </div>

      {metrics?.length ? (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div key={String(metric.label)} className="rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
              <div className="fa-compact-label">{metric.label}</div>
              <div className="fa-value mt-1 text-[13px] font-semibold">{metric.value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </FACard>
  );
}
