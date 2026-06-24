import type { MarketMonitorMetric } from "@/types/market-monitor";

export function changeColor(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "var(--fg-4)";
  const num = typeof val === "number" ? val : parseFloat(String(val).replace(/[+,]/g, ""));
  if (!Number.isFinite(num)) return "var(--fg-4)";
  if (num > 0) return "#10b981";
  if (num < 0) return "#f05252";
  return "var(--fg-4)";
}

export function interpretStatus(metric: MarketMonitorMetric | undefined): string {
  if (!metric) return "---";
  if (metric.status === "error") return "数据异常";
  if (metric.status === "warn") return "关注";
  if (metric.status === "ok") return "正常";
  return metric.interpretation || "---";
}
