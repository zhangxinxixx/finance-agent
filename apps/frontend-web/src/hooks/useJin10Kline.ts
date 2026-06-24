import { useState, useEffect, useCallback, useRef } from "react";

export interface Jin10KlineCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Jin10KlineResponse {
  symbol: string;
  timeframe: string;
  count: number;
  candles: Jin10KlineCandle[];
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
  const prevTimeframeRef = useRef<KlineTimeframe>(timeframe);

  const fetchKline = useCallback(async (replace: boolean = false) => {
    try {
      const url = `/api/jin10/kline?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`;
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
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "获取 K 线失败");
    }
  }, [symbol, timeframe, limit]);

  // 首次加载
  useEffect(() => {
    setLoading(true);
    fetchKline(true).finally(() => setLoading(false));
  }, [timeframe]); // 切换周期时重新加载

  // 定时轮询
  useEffect(() => {
    const timer = setInterval(() => {
      fetchKline();
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchKline]);

  return { candles, loading, error, refetch: () => fetchKline(true) };
}
