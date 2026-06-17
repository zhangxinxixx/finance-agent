import type { ReactNode } from "react";

interface FAFilterBarProps {
  children?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  className?: string;
}

export function FAFilterBar({ children, left, right, className = "" }: FAFilterBarProps) {
  return (
    <div
      className={`flex flex-col gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 shadow-[var(--shadow-card)] backdrop-blur md:flex-row md:items-end md:justify-between ${className}`}
    >
      <div className="flex min-w-0 flex-wrap items-end gap-2.5">{left ?? children}</div>
      {right ? <div className="flex shrink-0 flex-wrap items-end gap-2">{right}</div> : null}
    </div>
  );
}
