import { useCallback, useEffect, useRef, useState } from "react";
import { fetchLiveStrategy } from "@/adapters/liveStrategy";
import type { LiveStrategyResponse } from "@/types/live-strategy";

const LIVE_STRATEGY_REFRESH_MS = 15 * 60_000;

interface LiveStrategyState {
  data: LiveStrategyResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useLiveStrategy(asset: "XAUUSD" | null = "XAUUSD"): LiveStrategyState {
  const [data, setData] = useState<LiveStrategyResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const dataRef = useRef<LiveStrategyResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!asset) {
      dataRef.current = null;
      setData(null);
      setIsLoading(false);
      setError(null);
      return () => { cancelled = true; };
    }
    setIsLoading(true);
    setError(null);

    void fetchLiveStrategy(asset)
      .then((nextData) => {
        if (!cancelled) {
          dataRef.current = nextData;
          setData(nextData);
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          if (!dataRef.current) setData(null);
          setError(cause instanceof Error ? cause : new Error("加载实时策略数据失败"));
        }
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });

    return () => { cancelled = true; };
  }, [asset, reloadToken]);

  useEffect(() => {
    if (!asset) return;
    const intervalId = window.setInterval(() => {
      setReloadToken((value) => value + 1);
    }, LIVE_STRATEGY_REFRESH_MS);
    return () => window.clearInterval(intervalId);
  }, [asset]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: useCallback(() => setReloadToken((value) => value + 1), []),
  };
}
