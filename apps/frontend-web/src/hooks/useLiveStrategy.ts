import { useCallback, useEffect, useState } from "react";
import { fetchLiveStrategy } from "@/adapters/liveStrategy";
import type { LiveStrategyResponse } from "@/types/live-strategy";

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

  useEffect(() => {
    let cancelled = false;
    if (!asset) {
      setData(null);
      setIsLoading(false);
      setError(null);
      return () => { cancelled = true; };
    }
    setIsLoading(true);
    setError(null);

    void fetchLiveStrategy(asset)
      .then((nextData) => { if (!cancelled) setData(nextData); })
      .catch((cause) => {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载实时策略数据失败"));
        }
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });

    return () => { cancelled = true; };
  }, [asset, reloadToken]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: useCallback(() => setReloadToken((value) => value + 1), []),
  };
}
