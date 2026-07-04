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
        {eyebrow ? <div className="fa-eyebrow">{eyebrow}</div> : null}
        <h2 className="fa-module-title truncate text-[14px] font-semibold leading-tight">{title}</h2>
        {description ? <p className="fa-muted-text mt-1.5">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
