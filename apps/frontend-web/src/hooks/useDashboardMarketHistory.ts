import { useEffect, useState } from "react";
import { fetchMarketMonitorHistory, type MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";

interface DashboardMarketHistoryState {
  history: MarketMonitorHistoryResponse | null;
  timeframe: MarketMonitorHistoryTimeframe;
  isLoading: boolean;
  error: Error | null;
  setTimeframe: (timeframe: MarketMonitorHistoryTimeframe) => void;
}

export function useDashboardMarketHistory(initialTimeframe: MarketMonitorHistoryTimeframe = "1D"): DashboardMarketHistoryState {
  const [history, setHistory] = useState<MarketMonitorHistoryResponse | null>(null);
  const [timeframe, setTimeframe] = useState<MarketMonitorHistoryTimeframe>(initialTimeframe);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await fetchMarketMonitorHistory(timeframe);
        if (!cancelled) {
          setHistory(payload);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 Dashboard 价格历史失败"));
          setHistory(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [timeframe]);

  return { history, timeframe, isLoading, error, setTimeframe };
}
