import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import type { MarketMonitorChange, MarketMonitorMetric, MarketMonitorStatus } from "@/types/market-monitor";

export function findMetric(metrics: MarketMonitorMetric[], key: string) {
  return metrics.find((metric) => metric.key === key);
}

export function textOrDash(value: string | number | null | undefined, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  return String(value);
}

export function formatMetricValue(value: MarketMonitorMetric["latest_value"], maxFractionDigits = 2) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "number") {
    return value.toLocaleString("zh-CN", {
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
      maximumFractionDigits: maxFractionDigits,
    });
  }

  return value;
}

export function formatMetricChange(value: MarketMonitorChange, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  if (typeof value === "number") {
    return value.toLocaleString("zh-CN", {
      signDisplay: "always",
      maximumFractionDigits: 2,
    });
  }

  return value;
}

export function compactDelta(metric?: MarketMonitorMetric) {
  if (!metric) {
    return "1W —";
  }

  return `1W ${formatMetricChange(metric.one_week_change)}`;
}

export function compactHint(metric?: MarketMonitorMetric) {
  if (!metric) {
    return "1M —";
  }

  return `1M ${formatMetricChange(metric.one_month_change)}`;
}

function numericDirection(value: MarketMonitorChange): number | null {
  if (typeof value === "number") {
    return value;
  }

  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  if (normalized.startsWith("+")) return 1;
  if (normalized.startsWith("-")) return -1;
  return 0;
}

export function trendFromChange(value: MarketMonitorChange): "up" | "down" | "flat" {
  const direction = numericDirection(value);
  if (direction === null || direction === 0) return "flat";
  return direction > 0 ? "up" : "down";
}

export function statusTone(status: MarketMonitorStatus): FAStatusTone {
  if (status === "ok") return "up";
  if (status === "warn") return "warn";
  if (status === "error") return "down";
  if (status === "info") return "info";
  return "dim";
}
