import type { ReactNode } from "react";
import { InspectorRail } from "./InspectorRail";

export interface EvidenceRailItem {
  label: ReactNode;
  value: ReactNode;
  meta?: ReactNode;
}

interface EvidenceRailProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  items: EvidenceRailItem[];
  footer?: ReactNode;
  className?: string;
}

export function EvidenceRail({ title = "Evidence", subtitle, items, footer, className = "" }: EvidenceRailProps) {
  return (
    <InspectorRail title={title} subtitle={subtitle} className={className}>
      <div className="evidence-rail-list">
        {items.map((item, index) => (
          <div className="evidence-rail-row" key={`${item.label}-${index}`}>
            <div className="evidence-rail-row__label">{item.label}</div>
            <div className="evidence-rail-row__value">{item.value}</div>
            {item.meta ? <div className="evidence-rail-row__meta">{item.meta}</div> : null}
          </div>
        ))}
      </div>
      {footer ? <div className="evidence-rail-footer">{footer}</div> : null}
    </InspectorRail>
  );
}
