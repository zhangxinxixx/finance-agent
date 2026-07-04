import type { ReactNode } from "react";

export interface SummaryStripItem {
  label: ReactNode;
  value: ReactNode;
  delta?: ReactNode;
  tone?: "neutral" | "gold" | "up" | "down" | "blue" | "warn" | "muted";
  meta?: ReactNode;
}

interface SummaryStripProps {
  items: SummaryStripItem[];
  className?: string;
}

export function SummaryStrip({ items, className = "" }: SummaryStripProps) {
  return (
    <div className={`summary-strip ${className}`}>
      {items.map((item, index) => (
        <div className={`summary-strip__item summary-strip__item--${item.tone ?? "neutral"}`} key={`${item.label}-${index}`}>
          <div className="summary-strip__label">{item.label}</div>
          <div className="summary-strip__value-row">
            <span className="summary-strip__value fa-num">{item.value}</span>
            {item.delta ? <span className="summary-strip__delta fa-num">{item.delta}</span> : null}
          </div>
          {item.meta ? <div className="summary-strip__meta">{item.meta}</div> : null}
        </div>
      ))}
    </div>
  );
}
