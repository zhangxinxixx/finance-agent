import type { ReactNode } from "react";

interface FACardProps {
  title?: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  accent?: "brand" | "up" | "down" | "warn" | "info" | "emphasis" | "none";
  density?: "compact" | "normal" | "spacious";
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
  emphasis: "fa-important-bg",
  none: "hidden",
};

const densityClass: Record<NonNullable<FACardProps["density"]>, string> = {
  compact: "fa-card-body--compact",
  normal: "",
  spacious: "fa-card-body--spacious",
};

export function FACard({
  title,
  eyebrow,
  description,
  action,
  accent = "none",
  density = "normal",
  children,
  className = "",
  headerClassName = "",
  bodyClassName = "",
}: FACardProps) {
  const hasHeader = title || eyebrow || description || action;

  return (
    <section className={`fa-card ${className}`}>
      {hasHeader ? (
        <header className={`fa-card-header ${headerClassName}`}>
          <span className={`h-3.5 w-[2px] rounded-[var(--radius-xs)] ${accentClass[accent]}`} />
          <div className="min-w-0 flex-1">
            {eyebrow ? <div className="fa-eyebrow">{eyebrow}</div> : null}
            {title ? <div className="fa-module-title break-words text-[14px] font-semibold leading-tight">{title}</div> : null}
            {description ? <div className="fa-card-description mt-1">{description}</div> : null}
          </div>
          {action ? <div className="flex max-w-full shrink-0 flex-wrap items-center justify-end gap-2">{action}</div> : null}
        </header>
      ) : null}
      <div className={`fa-card-body ${densityClass[density]} ${bodyClassName}`}>{children}</div>
    </section>
  );
}
