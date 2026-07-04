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
      className={`fa-chrome-band flex flex-col gap-2.5 px-4 py-3 md:flex-row md:items-end md:justify-between ${className}`}
    >
      <div className="flex min-w-0 flex-wrap items-end gap-3">{left ?? children}</div>
      {right ? <div className="flex shrink-0 flex-wrap items-end gap-2.5">{right}</div> : null}
    </div>
  );
}
