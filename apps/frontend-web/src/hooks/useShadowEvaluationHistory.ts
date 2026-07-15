import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/adapters/apiClient";
import { fetchShadowEvaluationHistory } from "@/adapters/shadowEvaluationHistory";
import type { ShadowEvaluationHistoryResponse } from "@/types/shadow-evaluation-history";

interface ShadowEvaluationHistoryState {
  data: ShadowEvaluationHistoryResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  isUnavailable: boolean;
  refetch: () => void;
}
export function useShadowEvaluationHistory(enabled = true): ShadowEvaluationHistoryState {
  const [data, setData] = useState<ShadowEvaluationHistoryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);
  const [isUnavailable, setIsUnavailable] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!enabled) {
      setData(null);
      setIsLoading(false);
      setError(null);
      setIsUnavailable(false);
      return () => { cancelled = true; };
    }
    setIsLoading(true);
    setError(null);
    setIsUnavailable(false);
    void fetchShadowEvaluationHistory()
      .then((nextData) => { if (!cancelled) setData(nextData); })
      .catch((cause) => {
        if (cancelled) return;
        setData(null);
        if (cause instanceof ApiError && cause.status === 404) {
          setIsUnavailable(true);
        } else {
          setError(cause instanceof Error ? cause : new Error("加载影子策略评估历史失败"));
        }
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [enabled, reloadToken]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    isUnavailable,
    refetch: useCallback(() => setReloadToken((value) => value + 1), []),
  };
}
