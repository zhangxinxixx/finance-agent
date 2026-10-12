import { useEffect, useRef, useState } from "react";
import { fetchMarketMonitorData, fetchMarketMonitorHistory, type MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorResponse } from "@/types/market-monitor";

export type MarketMonitorHistoryTimeframe = "15M" | "30M" | "1H" | "4H" | "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";

interface MarketMonitorState {
  data: MarketMonitorResponse | null;
  history: MarketMonitorHistoryResponse | null;
  historyTimeframe: MarketMonitorHistoryTimeframe;
  isLoading: boolean;
  isRefreshing: boolean;
  isError: boolean;
  error: Error | null;
  historyError: Error | null;
  refetch: () => void;
  setHistoryTimeframe: (timeframe: MarketMonitorHistoryTimeframe) => void;
}

export function useMarketMonitor(): MarketMonitorState {
  const [data, setData] = useState<MarketMonitorResponse | null>(null);
  const [history, setHistory] = useState<MarketMonitorHistoryResponse | null>(null);
  const [historyTimeframe, setHistoryTimeframe] = useState<MarketMonitorHistoryTimeframe>("1D");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [historyError, setHistoryError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const dataRef = useRef<MarketMonitorResponse | null>(null);
  const historyRef = useRef<MarketMonitorHistoryResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadMarketMonitor() {
      const hasExistingResult = dataRef.current !== null || historyRef.current !== null;
      setIsLoading(!hasExistingResult);
      setIsRefreshing(hasExistingResult);
      // A retry starts a new observation window. Do not keep the previous
      // failure banner visible while that window is still pending.
      setError(null);
      if (hasExistingResult) {
        // Do not let a new timeframe label sit above the previous window while
        // the request is pending. The chart can return as an explicit partial
        // state after the new window succeeds.
        historyRef.current = null;
        setHistory(null);
        setHistoryError(null);
      }

      try {
        const [dataResult, historyResult] = await Promise.allSettled([
          fetchMarketMonitorData(),
          fetchMarketMonitorHistory(historyTimeframe),
        ]);

        if (dataResult.status === "rejected") {
          throw dataResult.reason;
        }

        if (!cancelled) {
          dataRef.current = dataResult.value;
          setData(dataResult.value);
          if (historyResult.status === "fulfilled") {
            historyRef.current = historyResult.value;
            setHistory(historyResult.value);
            setHistoryError(null);
          } else {
            setHistoryError(historyResult.reason instanceof Error ? historyResult.reason : new Error("历史窗口加载失败"));
          }
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 Market Monitor 数据失败"));
          // Keep the last successful result visible, but let the page mark it
          // as stale because the current refresh did not complete.
          if (!dataRef.current && !historyRef.current) {
            setData(null);
          }
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    void loadMarketMonitor();

    return () => {
      cancelled = true;
    };
  }, [historyTimeframe, reloadToken]);

  return {
    data,
    history,
    historyTimeframe,
    isLoading,
    isRefreshing,
    isError: error !== null,
    error,
    historyError,
    refetch: () => setReloadToken((value) => value + 1),
    setHistoryTimeframe,
  };
}
