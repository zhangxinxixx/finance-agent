import type { ReactNode } from "react";

interface FASectionHeaderProps {
  title: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function FASectionHeader({ title, eyebrow, description, action, className = "" }: FASectionHeaderProps) {
  return (
    <div className={`flex min-w-0 items-start justify-between gap-3 ${className}`}>
      <div className="min-w-0">
        {eyebrow ? <div className="text-[9px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-5)]">{eyebrow}</div> : null}
        <h2 className="truncate text-[13px] font-semibold leading-tight text-[var(--fg-1)]">{title}</h2>
        {description ? <p className="mt-1 text-[10px] leading-5 text-[var(--fg-4)]">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
