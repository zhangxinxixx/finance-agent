import { useState, useEffect, useCallback, useRef } from "react";

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

export type KlineTimeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1D";

const POLL_INTERVAL = 10_000; // 10s

/**
 * 轮询 Jin10 实时 K 线数据。
 * 切换周期时自动清空旧缓存并重新拉取。
 */
export function useJin10Kline(
  symbol: string = "XAUUSD",
  timeframe: KlineTimeframe = "1m",
  limit: number = 200,
) {
  const [candles, setCandles] = useState<Jin10KlineCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<MarketCandleCoverage | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [sourceTimeframe, setSourceTimeframe] = useState<string | null>(null);
  const [sourceTrace, setSourceTrace] = useState<MarketCandleSourceTrace | null>(null);
  const prevTimeframeRef = useRef<KlineTimeframe>(timeframe);

  const fetchKline = useCallback(async (replace: boolean = false) => {
    try {
      const url = `/api/market/candles?asset=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`;
      const resp = await fetch(url);
      const data: Jin10KlineResponse = await resp.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      setCandles((prev) => {
        if (replace || prev.length === 0) return data.candles;

        // 增量合并
        const existingTimes = new Set(prev.map((c) => c.time));
        const newCandles = data.candles.filter((c) => !existingTimes.has(c.time));
        if (newCandles.length === 0) return prev;

        // 更新最后一根（可能还在变动中）
        const merged = [...prev, ...newCandles];
        if (merged.length > 0) {
          const lastNew = data.candles[data.candles.length - 1];
          const lastMerged = merged[merged.length - 1];
          if (lastNew && lastMerged.time === lastNew.time) {
            merged[merged.length - 1] = lastNew;
          }
        }

        return merged.slice(-limit);
      });
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
  }, [timeframe]); // 切换周期时重新加载

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
