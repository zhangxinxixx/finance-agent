import { useEffect, useRef, useState } from "react";
import { fetchDashboardData } from "@/adapters/api";
import type { DashboardDataResponse } from "@/types/dashboard";

interface DashboardState {
  data: DashboardDataResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

const DASHBOARD_AUTO_REFRESH_MS = 60_000;

export function useDashboard(date?: string | null): DashboardState {
  const [data, setData] = useState<DashboardDataResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function loadDashboard() {
      if (!hasLoadedRef.current) setIsLoading(true);
      setError(null);

      try {
        const nextData = await fetchDashboardData(date);

        if (!cancelled) {
          setData(nextData);
          hasLoadedRef.current = true;
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 Dashboard 数据失败"));
          setData(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadDashboard();

    return () => {
      cancelled = true;
    };
  }, [date, reloadToken]);

  useEffect(() => {
    const refresh = () => setReloadToken((value) => value + 1);
    const intervalId = window.setInterval(refresh, DASHBOARD_AUTO_REFRESH_MS);
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };

    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}
