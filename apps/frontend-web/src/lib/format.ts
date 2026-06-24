import type { MetricValue } from "@/types/common";

const EMPTY = "—";

export function formatNumber(value: number | string | null | undefined, precision = 2): string {
  if (value === null || value === undefined || value === "") return EMPTY;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return numeric.toLocaleString("zh-CN", {
    maximumFractionDigits: precision,
    minimumFractionDigits: 0,
  });
}

export function formatPercent(value: number | string | null | undefined, precision = 1): string {
  if (value === null || value === undefined || value === "") return EMPTY;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  const pct = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${pct.toLocaleString("zh-CN", { maximumFractionDigits: precision })}%`;
}

export function formatMetricValue(value: number | string | MetricValue | null | undefined, precision = 2): string {
  if (value === null || value === undefined) return EMPTY;
  if (typeof value === "object") return value.display || formatMetricValue(value.value, value.precision ?? precision);
  return formatNumber(value, precision);
}

export function missingValue(label = EMPTY): string {
  return label;
}

export function compactId(value: string | null | undefined, head = 8, tail = 0): string {
  if (!value) return EMPTY;
  if (tail <= 0) return value.length > head ? value.slice(0, head) : value;
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
