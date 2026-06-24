import { useEffect, useState } from "react";
import { fetchMarketMonitorData, fetchMarketMonitorHistory, type MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorResponse } from "@/types/market-monitor";

export type MarketMonitorHistoryTimeframe = "15M" | "30M" | "1H" | "4H" | "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";

interface MarketMonitorState {
  data: MarketMonitorResponse | null;
  history: MarketMonitorHistoryResponse | null;
  historyTimeframe: MarketMonitorHistoryTimeframe;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
  setHistoryTimeframe: (timeframe: MarketMonitorHistoryTimeframe) => void;
}

export function useMarketMonitor(): MarketMonitorState {
  const [data, setData] = useState<MarketMonitorResponse | null>(null);
  const [history, setHistory] = useState<MarketMonitorHistoryResponse | null>(null);
  const [historyTimeframe, setHistoryTimeframe] = useState<MarketMonitorHistoryTimeframe>("1D");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadMarketMonitor() {
      setIsLoading(true);
      setError(null);

      try {
        const [dataResult, historyResult] = await Promise.allSettled([
          fetchMarketMonitorData(),
          fetchMarketMonitorHistory(historyTimeframe),
        ]);

        if (dataResult.status === "rejected") {
          throw dataResult.reason;
        }

        if (!cancelled) {
          setData(dataResult.value);
          setHistory(historyResult.status === "fulfilled" ? historyResult.value : null);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 Market Monitor 数据失败"));
          setData(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
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
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
    setHistoryTimeframe,
  };
}
