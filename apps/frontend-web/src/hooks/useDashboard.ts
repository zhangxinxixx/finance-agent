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

export function useDashboard(date?: string | null, enabled = true): DashboardState {
  const [data, setData] = useState<DashboardDataResponse | null>(null);
  const [loadedDate, setLoadedDate] = useState(date);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const pending = useRef(enabled);
  const refresh = () => {
    if (!enabled || pending.current) return;
    pending.current = true;
    setReloadToken(value => value + 1);
  };

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function loadDashboard() {
      pending.current = true;
      setIsLoading(true);
      setError(null);

      try {
        const nextData = await fetchDashboardData(date);

        if (!cancelled) {
          setLoadedDate(date);
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 Dashboard 数据失败"));
        }
      } finally {
        if (!cancelled) {
          pending.current = false;
          setIsLoading(false);
        }
      }
    }

    void loadDashboard();

    return () => {
      cancelled = true;
      pending.current = false;
    };
  }, [date, reloadToken, enabled]);

  useEffect(() => {
    if (!enabled) return;
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
  }, [enabled]);

  return {
    data: loadedDate === date ? data : null,
    isLoading: enabled && (isLoading || (error === null && loadedDate !== date)),
    isError: error !== null,
    error,
    refetch: refresh,
  };
}
