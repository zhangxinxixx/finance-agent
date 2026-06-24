import { useState, useEffect, useCallback } from "react";
import { fetchJson } from "../adapters/apiClient";
import type { DataStatusSummary } from "../types/dashboard";

const POLL_INTERVAL_MS = 30_000;

const UNAVAILABLE_SUMMARY: DataStatusSummary = {
  overall_status: "UNAVAILABLE",
  latest_run: null,
  snapshot_id: null,
  data_date: null,
  sources: [],
  missing_sources: [],
  stale_sources: [],
};

export interface DataStatusState {
  data: DataStatusSummary;
  isLoading: boolean;
  isError: boolean;
  error?: Error;
  refetch: () => void;
}

export function useDataStatus(): DataStatusState {
  const [data, setData] = useState<DataStatusSummary>(UNAVAILABLE_SUMMARY);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | undefined>(undefined);
  const [reloadToken, setReloadToken] = useState(0);

  const refetch = useCallback(() => setReloadToken((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      try {
        const result = await fetchJson<DataStatusSummary>("/api/data-status/summary");
        if (!cancelled) {
          setData(result);
          setIsError(false);
          setError(undefined);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(UNAVAILABLE_SUMMARY);
          setIsError(true);
          setError(cause instanceof Error ? cause : new Error("数据状态加载失败"));
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [reloadToken]);

  return { data, isLoading, isError, error, refetch };
}
