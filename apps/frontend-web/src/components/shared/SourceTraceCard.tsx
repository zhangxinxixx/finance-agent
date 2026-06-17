import type { ReactNode } from "react";
import { FACard } from "./FACard";
import { FAEmptyState } from "./FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";
import { SourceTrace, type LegacySourceTraceRecord } from "./SourceTrace";
import type { SourceRef } from "@/types/common";

interface SourceTraceCardProps {
  title: ReactNode;
  eyebrow?: ReactNode;
  accent?: "brand" | "up" | "down" | "warn" | "info" | "none";
  sources?: LegacySourceTraceRecord[];
  sourceRefs?: SourceRef[];
  compact?: boolean;
  description?: ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyClassName?: string;
  countTone?: FAStatusTone;
  action?: ReactNode;
  children?: ReactNode;
}

export function SourceTraceCard({
  title,
  eyebrow = "Source Trace",
  accent = "info",
  sources = [],
  sourceRefs = [],
  compact = false,
  description,
  emptyTitle = "暂无溯源数据",
  emptyDescription = "当前视图没有可展示的 source trace 或 source refs。",
  emptyClassName,
  countTone,
  action,
  children,
}: SourceTraceCardProps) {
  const refCount = sources.length + sourceRefs.length;
  const hasTrace = refCount > 0;
  const resolvedAction = action ?? (
    <FAStatusPill tone={countTone ?? (hasTrace ? "info" : "dim")} dot={false}>
      {`${refCount} refs`}
    </FAStatusPill>
  );

  return (
    <FACard title={title} eyebrow={eyebrow} accent={accent} action={resolvedAction} bodyClassName="space-y-3">
      {description ? <div className="text-[11px] leading-5 text-[var(--fg-4)]">{description}</div> : null}
      {children}
      {hasTrace ? (
        <SourceTrace compact={compact} sources={sources} sourceRefs={sourceRefs} emptyText={emptyTitle} />
      ) : (
        <FAEmptyState title={emptyTitle} description={emptyDescription} className={emptyClassName ?? (compact ? "py-4" : "py-6")} />
      )}
    </FACard>
  );
}
