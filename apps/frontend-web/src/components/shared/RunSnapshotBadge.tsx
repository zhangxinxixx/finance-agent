import type { ReactNode } from "react";

interface RunSnapshotBadgeProps {
  label: ReactNode;
  value: string | null | undefined;
  emptyLabel?: ReactNode;
  className?: string;
}

export function RunSnapshotBadge({ label, value, emptyLabel = "未绑定", className = "" }: RunSnapshotBadgeProps) {
  return (
    <span className={`run-snapshot-badge ${className}`} title={value ?? undefined}>
      <span>{label}</span>
      <code>{value || emptyLabel}</code>
    </span>
  );
}
