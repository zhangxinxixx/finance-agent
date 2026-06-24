import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import type { MarketMonitorMetric } from "@/types/market-monitor";

export type ChartSeriesData = {
  key: string;
  color: string;
  label: string;
  values: number[];
  dashed?: boolean;
  synthetic?: boolean;
};

export const TIMEFRAMES: MarketMonitorHistoryTimeframe[] = ["15M", "30M", "1H", "4H", "1D", "1W", "1M", "3M", "6M", "1Y"];

export const CHART_SERIES: Array<{ key: string; color: string; label: string; dashed?: boolean }> = [
  { key: "XAUUSD", color: "#fbbf24", label: "XAUUSD" },
  { key: "DXY", color: "#60a5fa", label: "DXY", dashed: true },
  { key: "REAL_10Y", color: "#f05252", label: "10Y Real" },
  { key: "T10YIE", color: "#34d399", label: "T10YIE" },
];

export const TIMEFRAME_POINTS: Record<MarketMonitorHistoryTimeframe, number> = {
  "15M": 24,
  "30M": 24,
  "1H": 24,
  "4H": 10,
  "1D": 2,
  "1W": 7,
  "1M": 20,
  "3M": 30,
  "6M": 36,
  "1Y": 48,
};

export function timeframeLabel(timeframe: MarketMonitorHistoryTimeframe) {
  if (timeframe === "15M") return "近 15 分钟级别";
  if (timeframe === "30M") return "近 30 分钟级别";
  if (timeframe === "1H") return "近 1 小时级别";
  if (timeframe === "4H") return "近 4 小时级别";
  if (timeframe === "1D") return "近 1 天收盘";
  if (timeframe === "1W") return "近 1 周";
  if (timeframe === "1M") return "近 1 个月";
  if (timeframe === "3M") return "近 3 个月";
  if (timeframe === "6M") return "近 6 个月";
  return "近 1 年";
}

export function visibleHistorySeries(
  history: MarketMonitorHistoryResponse | null | undefined,
  timeframe: MarketMonitorHistoryTimeframe,
) {
  return (history?.series ?? []).slice(-TIMEFRAME_POINTS[timeframe]);
}

export function buildChartSeriesData({
  timeframe,
  historySeries,
  xauMetricValue,
}: {
  timeframe: MarketMonitorHistoryTimeframe;
  historySeries: MarketMonitorHistoryResponse["series"];
  xauMetricValue: number | null;
}): ChartSeriesData[] {
  const points = TIMEFRAME_POINTS[timeframe];
  const raw: ChartSeriesData[] = [];

  for (const series of CHART_SERIES) {
    const historyValues = historySeries
      .map((point) => seriesValue(point as unknown as Record<string, unknown>, series.key))
      .filter((value): value is number => value !== null);
    const values = historyValues.length >= 2 ? historyValues.slice(-points) : [];
    if (values.length < 2) continue;
    raw.push({ key: series.key, color: series.color, label: series.label, dashed: series.dashed, values });
  }

  if (raw.length > 0) {
    return raw;
  }

  const fallback = buildFallbackSeries(xauMetricValue);
  return fallback ? [fallback] : [];
}

export function chartStatusText(history: MarketMonitorHistoryResponse | null | undefined) {
  if (!history) {
    return "history unavailable";
  }

  return `${history.available_points} 个点 · ${history.source_timeframe ?? "unknown"} source${history.degraded ? " · degraded" : ""}${history.coverage_note ? ` · ${history.coverage_note}` : ""}`;
}

export function xauPricePoints(seriesData: ChartSeriesData[]) {
  return (seriesData.find((item) => item.key === "XAUUSD")?.values ?? []).map((value, index, arr) => ({
    label: index === 0 ? "start" : index === arr.length - 1 ? "latest" : "",
    value,
  }));
}

export function xauCandles(historySeries: MarketMonitorHistoryResponse["series"]) {
  return historySeries
    .map((point) => {
      const ohlc = point.xauusd_ohlc;
      if (!ohlc) return null;
      return {
        label: point.date,
        open: ohlc.open,
        high: ohlc.high,
        low: ohlc.low,
        close: ohlc.close,
      };
    })
    .filter((value): value is { label: string; open: number; high: number; low: number; close: number } => value !== null);
}

export function isSyntheticFallback(seriesData: ChartSeriesData[]) {
  return seriesData.length === 1 && Boolean(seriesData[0]?.synthetic);
}

function seriesValue(point: Record<string, unknown>, key: string): number | null {
  const value = point[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function buildFallbackSeries(value: number | null): ChartSeriesData | null {
  if (value === null || !Number.isFinite(value)) return null;
  return {
    key: "XAUUSD",
    color: "#fbbf24",
    label: "XAUUSD",
    values: [value * 0.996, value * 0.999, value * 0.9975, value * 1.0015, value],
    dashed: false,
    synthetic: true,
  };
}

export function activeMetricSummary(metrics: MarketMonitorMetric[], key: string) {
  return metrics.find((metric) => metric.key === key) ?? null;
}
