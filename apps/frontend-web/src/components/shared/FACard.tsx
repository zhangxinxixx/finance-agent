import type { ReactNode } from "react";

interface FACardProps {
  title?: ReactNode;
  eyebrow?: ReactNode;
  action?: ReactNode;
  accent?: "brand" | "up" | "down" | "warn" | "info" | "none";
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  bodyClassName?: string;
}

const accentClass: Record<NonNullable<FACardProps["accent"]>, string> = {
  brand: "bg-[var(--brand)]",
  up: "bg-[var(--up)]",
  down: "bg-[var(--down)]",
  warn: "bg-[var(--warn)]",
  info: "bg-[var(--info)]",
  none: "hidden",
};

export function FACard({
  title,
  eyebrow,
  action,
  accent = "none",
  children,
  className = "",
  headerClassName = "",
  bodyClassName = "",
}: FACardProps) {
  const hasHeader = title || eyebrow || action;

  return (
    <section className={`fa-card border-[var(--border-faint)] ${className}`}>
      {hasHeader ? (
        <header className={`fa-card-header border-b-[var(--border-faint)] ${headerClassName}`}>
          <span className={`h-3.5 w-[2px] rounded-[var(--radius-xs)] ${accentClass[accent]}`} />
          <div className="min-w-0 flex-1">
            {eyebrow ? <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{eyebrow}</div> : null}
            {title ? <div className="truncate text-[11px] font-semibold leading-tight text-[var(--fg-2)]">{title}</div> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div className={`fa-card-body ${bodyClassName}`}>{children}</div>
    </section>
  );
}
