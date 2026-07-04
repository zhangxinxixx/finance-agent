import type { ReactNode } from "react";

export type DataMode = "live" | "partial" | "fallback" | "mock" | "unavailable" | "manual_required";

interface DataModeBannerProps {
  mode: DataMode;
  reason?: ReactNode;
  className?: string;
}

const modeLabel: Record<DataMode, string> = {
  live: "LIVE",
  partial: "PARTIAL",
  fallback: "FALLBACK",
  mock: "MOCK",
  unavailable: "UNAVAILABLE",
  manual_required: "MANUAL REQUIRED",
};

export function DataModeBanner({ mode, reason, className = "" }: DataModeBannerProps) {
  if (mode === "live") return null;

  return (
    <div className={`data-mode-banner data-mode-banner--${mode} ${className}`}>
      <strong>{modeLabel[mode]}</strong>
      <span>{reason ?? "当前页面包含降级、模拟或不可用数据，请勿视为完整实时结论。"}</span>
    </div>
  );
}
