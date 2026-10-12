import { useEffect, useRef, useState } from "react";
import { fetchGoldMainlinesLatest, type GoldMainlinesResponse } from "@/adapters/goldMainlines";

interface GoldMainlinesState {
  data: GoldMainlinesResponse | null;
  isLoading: boolean;
  isRefreshing: boolean;
  isError: boolean;
  error: Error | null;
  lastSuccessfulAt: string | null;
  refetch: () => void;
}

export function resolveGoldRefreshFailure(
  previous: GoldMainlinesResponse | null,
  cause: unknown,
): { data: GoldMainlinesResponse | null; error: Error } {
  return {
    // A refresh failure must leave the last accepted DTO in place so the
    // reader can still audit the result that was actually loaded.
    data: previous,
    error: cause instanceof Error ? cause : new Error("加载黄金主线失败"),
  };
}

export function useGoldMainlines(): GoldMainlinesState {
  const [data, setData] = useState<GoldMainlinesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const dataRef = useRef<GoldMainlinesResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const hasExistingResult = dataRef.current !== null;
      setIsLoading(!hasExistingResult);
      setIsRefreshing(hasExistingResult);
      setError(null);
      try {
        const nextData = await fetchGoldMainlinesLatest();
        if (!cancelled) {
          dataRef.current = nextData;
          setData(nextData);
          setLastSuccessfulAt(new Date().toISOString());
        }
      } catch (cause) {
        if (!cancelled) {
          const failure = resolveGoldRefreshFailure(dataRef.current, cause);
          setData(failure.data);
          setError(failure.error);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  return {
    data,
    isLoading,
    isRefreshing,
    isError: error !== null,
    error,
    lastSuccessfulAt,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useGoldMainlines;
