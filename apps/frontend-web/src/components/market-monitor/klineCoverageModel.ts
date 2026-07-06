export type KlineTimeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1D";

export interface Jin10KlineCandleLike {
  time: string;
}

export interface MarketCandleCoverage {
  returned: number;
  first_time: string | null;
  last_time: string | null;
  expected_interval_seconds: number;
  gap_count: number;
  max_gap_seconds: number | null;
  gap_ranges?: Array<{ from: string; to: string; gap_seconds: number }>;
  degraded: boolean;
  reason?: string | null;
}

export type MarketCandleAvailabilityStatus = "available" | "degraded" | "unavailable" | "loading";

export interface MarketCandleTimeframeAvailability {
  timeframe: KlineTimeframe;
  status: MarketCandleAvailabilityStatus;
  label: string;
  reason: string;
  returned: number;
  sourceTimeframe?: string | null;
}

export const KLINE_TIMEFRAMES: Array<{ key: KlineTimeframe; label: string }> = [
  { key: "1m", label: "1分" },
  { key: "5m", label: "5分" },
  { key: "15m", label: "15分" },
  { key: "30m", label: "30分" },
  { key: "1h", label: "1时" },
  { key: "4h", label: "4时" },
  { key: "1D", label: "日" },
];

const TIMEFRAME_LABELS = new Map(KLINE_TIMEFRAMES.map((item) => [item.key, item.label]));

export function timeframeShortLabel(timeframe: KlineTimeframe): string {
  return TIMEFRAME_LABELS.get(timeframe) ?? timeframe;
}

export function mergeKlineCandles<T extends Jin10KlineCandleLike>(
  previous: T[],
  incoming: T[],
  limit: number,
  replace = false,
): T[] {
  if (replace || previous.length === 0) {
    return incoming.slice(-limit);
  }

  const byTime = new Map(previous.map((candle) => [candle.time, candle]));
  for (const candle of incoming) {
    byTime.set(candle.time, candle);
  }

  return Array.from(byTime.values())
    .sort((a, b) => Date.parse(a.time) - Date.parse(b.time))
    .slice(-limit);
}

export function classifyMarketCandleCoverage({
  timeframe,
  coverage,
  error,
  sourceTimeframe,
}: {
  timeframe: KlineTimeframe;
  coverage?: MarketCandleCoverage | null;
  error?: string | null;
  sourceTimeframe?: string | null;
}): MarketCandleTimeframeAvailability {
  if (error) {
    return {
      timeframe,
      status: "unavailable",
      label: "不可用",
      reason: error,
      returned: 0,
      sourceTimeframe,
    };
  }

  if (!coverage || coverage.returned < 2) {
    return {
      timeframe,
      status: "unavailable",
      label: "不可用",
      reason: coverage?.reason ?? "本地样本不足",
      returned: coverage?.returned ?? 0,
      sourceTimeframe,
    };
  }

  if (coverage.degraded || coverage.gap_count > 0) {
    return {
      timeframe,
      status: "degraded",
      label: "降级",
      reason: coverage.reason ?? "存在 K 线缺口",
      returned: coverage.returned,
      sourceTimeframe,
    };
  }

  return {
    timeframe,
    status: "available",
    label: "可用",
    reason: "本地 K 线覆盖正常",
    returned: coverage.returned,
    sourceTimeframe,
  };
}

export function availabilitySummary(
  availability: Partial<Record<KlineTimeframe, MarketCandleTimeframeAvailability>>,
): string {
  const items = Object.values(availability);
  if (items.length === 0) return "coverage probing";

  const available = items.filter((item) => item.status === "available").length;
  const degraded = items.filter((item) => item.status === "degraded").length;
  const unavailable = items.filter((item) => item.status === "unavailable").length;
  return `${available} 可用 · ${degraded} 降级 · ${unavailable} 不可用`;
}
