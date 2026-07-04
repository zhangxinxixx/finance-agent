import type { ReactNode } from "react";

export type StatusChipTone = "neutral" | "blue" | "gold" | "up" | "down" | "warn" | "muted";

interface StatusChipProps {
  children: ReactNode;
  tone?: StatusChipTone;
  className?: string;
  title?: string;
}

export function StatusChip({ children, tone = "neutral", className = "", title }: StatusChipProps) {
  return (
    <span className={`status-chip status-chip--${tone} ${className}`} title={title}>
      {children}
    </span>
  );
}
