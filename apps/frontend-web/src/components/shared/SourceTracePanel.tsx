import type { ReactNode } from "react";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";

export interface SourceTracePanelItem {
  label: ReactNode;
  value: ReactNode;
  status?: ReactNode;
  tone?: FAStatusTone;
  detail?: ReactNode;
}

interface SourceTracePanelProps {
  title?: ReactNode;
  description?: ReactNode;
  items: SourceTracePanelItem[];
  emptyLabel?: ReactNode;
  className?: string;
}

export function SourceTracePanel({
  title,
  description,
  items,
  emptyLabel = "暂无 SourceTrace",
  className = "",
}: SourceTracePanelProps) {
  return (
    <div className={`source-trace-panel ${className}`}>
      {title || description ? (
        <div className="min-w-0">
          {title ? <div className="text-[13px] font-semibold text-[var(--fg-1)]">{title}</div> : null}
          {description ? <div className="mt-1 text-[11px] leading-snug text-[var(--fg-5)]">{description}</div> : null}
        </div>
      ) : null}

      {items.length > 0 ? (
        items.map((item, index) => (
          <div key={`${String(item.label)}-${index}`} className="source-trace-row">
            <div className="min-w-0">
              <div className="source-trace-label">{item.label}</div>
              <div className="source-trace-value">{item.value}</div>
              {item.detail ? <div className="mt-1 text-[11px] leading-snug text-[var(--fg-5)]">{item.detail}</div> : null}
            </div>
            {item.status ? (
              <div className="shrink-0">
                <FAStatusPill tone={item.tone ?? "info"} dot={false}>
                  {item.status}
                </FAStatusPill>
              </div>
            ) : null}
          </div>
        ))
      ) : (
        <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--border-faint)] px-3 py-2 text-[12px] text-[var(--fg-5)]">
          {emptyLabel}
        </div>
      )}
    </div>
  );
}
