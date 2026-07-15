import { useState, useEffect, useCallback } from "react";
import {
  KLINE_TIMEFRAMES,
  classifyMarketCandleCoverage,
  mergeKlineCandles,
  type KlineTimeframe,
  type MarketCandleCoverage,
  type MarketCandleTimeframeAvailability,
} from "@/components/market-monitor/klineCoverageModel";

export interface Jin10KlineCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  source?: string;
  partial?: boolean;
}

export type { KlineTimeframe, MarketCandleCoverage, MarketCandleTimeframeAvailability };

export interface MarketCandleSourceTrace {
  primary_source: string;
  fallback_source?: string | null;
  latest_raw_path?: string | null;
  latest_update_time?: string | null;
}

export interface Jin10KlineResponse {
  asset?: string;
  symbol?: string;
  timeframe: string;
  requested_limit?: number;
  count?: number;
  source_timeframe?: string;
  provider?: string;
  candles: Jin10KlineCandle[];
  coverage?: MarketCandleCoverage;
  source_trace?: MarketCandleSourceTrace;
  error?: string;
}

const POLL_INTERVAL = 10_000; // 10s

/**
 * 轮询 Jin10 实时 K 线数据。
 * 切换周期时自动清空旧缓存并重新拉取。
 */
export function useJin10Kline(
  symbol: string = "XAUUSD",
  timeframe: KlineTimeframe = "5m",
  limit: number = 200,
) {
  const [candles, setCandles] = useState<Jin10KlineCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<MarketCandleCoverage | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [sourceTimeframe, setSourceTimeframe] = useState<string | null>(null);
  const [sourceTrace, setSourceTrace] = useState<MarketCandleSourceTrace | null>(null);

  const fetchKline = useCallback(async (replace: boolean = false) => {
    try {
      const url = `/api/market/candles?asset=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`;
      const resp = await fetch(url);
      const data: Jin10KlineResponse = await resp.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setCandles((prev) => mergeKlineCandles(prev, data.candles, limit, replace));
      setCoverage(data.coverage ?? null);
      setProvider(data.provider ?? null);
      setSourceTimeframe(data.source_timeframe ?? data.timeframe ?? null);
      setSourceTrace(data.source_trace ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "获取 K 线失败");
    }
  }, [symbol, timeframe, limit]);

  // 首次加载
  useEffect(() => {
    setLoading(true);
    setCoverage(null);
    fetchKline(true).finally(() => setLoading(false));
  }, [fetchKline]); // 切换标的、周期或数量时重新加载

  // 定时轮询
  useEffect(() => {
    const timer = setInterval(() => {
      fetchKline();
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchKline]);

  return {
    candles,
    loading,
    error,
    coverage,
    provider,
    sourceTimeframe,
    sourceTrace,
    refetch: () => fetchKline(true),
  };
}

export function useMarketCandleTimeframeAvailability(
  symbol: string = "XAUUSD",
  limit: number = 200,
) {
  const [availability, setAvailability] = useState<Partial<Record<KlineTimeframe, MarketCandleTimeframeAvailability>>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setAvailability(Object.fromEntries(
      KLINE_TIMEFRAMES.map(({ key }) => [
        key,
        {
          timeframe: key,
          status: "loading",
          label: "检测中",
          reason: "正在检测本地 K 线覆盖",
          returned: 0,
        },
      ]),
    ) as Partial<Record<KlineTimeframe, MarketCandleTimeframeAvailability>>);

    Promise.all(KLINE_TIMEFRAMES.map(async ({ key }) => {
      try {
        const url = `/api/market/candles?asset=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(key)}&limit=${limit}`;
        const resp = await fetch(url);
        const data: Jin10KlineResponse = await resp.json();
        return classifyMarketCandleCoverage({
          timeframe: key,
          coverage: data.coverage ?? null,
          error: data.error ?? (!resp.ok ? `HTTP ${resp.status}` : null),
          sourceTimeframe: data.source_timeframe ?? data.timeframe ?? null,
        });
      } catch (error) {
        return classifyMarketCandleCoverage({
          timeframe: key,
          error: error instanceof Error ? error.message : "覆盖检测失败",
        });
      }
    })).then((items) => {
      if (cancelled) return;
      setAvailability(Object.fromEntries(items.map((item) => [item.timeframe, item])) as Partial<Record<KlineTimeframe, MarketCandleTimeframeAvailability>>);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [symbol, limit]);

  return { availability, loading };
}
