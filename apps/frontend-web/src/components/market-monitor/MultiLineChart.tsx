import { useMemo, useState } from "react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import { useJin10Kline, useMarketCandleTimeframeAvailability, type KlineTimeframe } from "@/hooks/useJin10Kline";
import { KLineChart, type KLineCandle, type KLineSeries } from "@/components/charts/KLineChart";
import { TradingViewChart } from "@/components/charts/TradingViewChart";
import {
  buildChartSeriesData,
  chartStatusText,
  visibleHistorySeries,
  type ChartSeriesData,
} from "@/components/market-monitor/marketMonitorChart";
import { availabilitySummary } from "@/components/market-monitor/klineCoverageModel";
import { MultiLineChartLegend } from "./MultiLineChartLegend";

interface MultiLineChartProps {
  metrics: MarketMonitorMetric[];
  history?: MarketMonitorHistoryResponse | null;
  className?: string;
}

export function MultiLineChart({
  metrics,
  history,
  className = "",
}: MultiLineChartProps) {
  // ── Jin10 实时 K 线（图表内部管理时间周期）──
  const [chartTimeframe, setChartTimeframe] = useState<KlineTimeframe>("5m");
  const {
    candles: jin10Candles,
    loading: jin10Loading,
    coverage: klineCoverage,
    provider: klineProvider,
    sourceTimeframe,
  } = useJin10Kline("XAUUSD", chartTimeframe, 200);
  const {
    availability: timeframeAvailability,
    loading: availabilityLoading,
  } = useMarketCandleTimeframeAvailability("XAUUSD", 200);

  // Jin10 实时 K 线数据
  const liveCandles: KLineCandle[] = useMemo(
    () =>
      jin10Candles.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        volume: c.volume ?? 0,
      })),
    [jin10Candles],
  );

  // 叠加折线（从 history 日线数据构建 DXY/REAL_10Y/T10YIE）
  const visibleCandles = useMemo(
    () => visibleHistorySeries(history, "1D"),
    [history],
  );

  const seriesData: ChartSeriesData[] = useMemo(() => {
    return buildChartSeriesData({
      timeframe: "1D",
      historySeries: visibleCandles,
      xauMetricValue: null,
    });
  }, [visibleCandles]);

  const lineSeries: KLineSeries[] = useMemo(() => {
    const candleDates = visibleCandles.map((p) => p.date);
    return seriesData
      .filter((s) => s.key !== "XAUUSD")
      .map((s) => ({
        key: s.key,
        label: s.label,
        color: s.color,
        dashed: s.dashed,
        values: s.values.map((v, i) => ({ time: candleDates[i] ?? "", value: v })),
      }));
  }, [seriesData, visibleCandles]);

  const statusText = chartStatusText(history);
  const klineStatus = klineCoverage?.degraded ? "降级" : klineCoverage ? "正常" : "待同步";
  const klineStatusTone = klineCoverage?.degraded ? "warn" : klineCoverage ? "ok" : "pending";
  const klineMeta = [
    klineProvider ?? "market_candles",
    sourceTimeframe ? `${sourceTimeframe} source` : null,
    klineCoverage ? `${klineCoverage.returned} bars` : null,
    klineCoverage?.gap_count ? `gap ${klineCoverage.gap_count}` : null,
    availabilityLoading ? "checking periods" : availabilitySummary(timeframeAvailability),
  ].filter(Boolean).join(" · ");

  return (
    <div className={className}>
      <div className="market-monitor-chart-shell">
        <details className="market-monitor-local-kline-diagnostic">
          <summary>
            <span>本地 K 线诊断</span>
            <span className="market-monitor-local-kline-summary">
              <span className="market-monitor-local-kline-chip" data-tone={klineStatusTone}>{klineStatus}</span>
              <span className="fa-compact-meta">{klineMeta || `market_candles · ${chartTimeframe}`}</span>
            </span>
          </summary>
          <div className="market-monitor-local-kline-body">
            <div className="market-monitor-local-kline-coverage">
              <span>{klineCoverage?.reason ?? "统一 K 线接口返回 coverage / source_trace；主图继续使用 TradingView。"}</span>
              {klineCoverage?.max_gap_seconds ? <span>max gap {klineCoverage.max_gap_seconds}s</span> : null}
            </div>
            <KLineChart
              candles={liveCandles}
              lineSeries={lineSeries}
              height={260}
              loading={jin10Loading}
              emptyText="Jin10 实时 K 线数据加载中..."
              timeframe={chartTimeframe}
              onTimeframeChange={setChartTimeframe}
              timeframeAvailability={timeframeAvailability}
            />
          </div>
        </details>
        <TradingViewChart symbol="OANDA:XAUUSD" interval="15" theme="dark" height={400} />
        <MultiLineChartLegend metrics={metrics} seriesData={seriesData} statusText={statusText} />
      </div>
    </div>
  );
}

export default MultiLineChart;
