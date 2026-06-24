import type { ReactNode } from "react";

interface FAConvictionBarProps {
  value: number;
  label?: ReactNode;
  ariaLabel?: string;
  tone?: "up" | "down" | "warn" | "info";
  className?: string;
}

const toneVar: Record<NonNullable<FAConvictionBarProps["tone"]>, string> = {
  up: "var(--up)",
  down: "var(--down)",
  warn: "var(--warn)",
  info: "var(--info)",
};

export function FAConvictionBar({ value, label = "确信度", ariaLabel = "确信度", tone = "info", className = "" }: FAConvictionBarProps) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));

  return (
    <div className={className}>
      <div className="mb-1 flex items-center justify-between gap-2 text-[10px]">
        <span className="font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</span>
        <span className="fa-num font-semibold text-[var(--fg-2)]">{Math.round(clamped)}%</span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-[var(--radius-pill)] bg-[var(--bg-panel)]"
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped)}
      >
        <div className="h-full rounded-[var(--radius-pill)]" style={{ width: `${clamped}%`, background: toneVar[tone] }} />
      </div>
    </div>
  );
}
