import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/adapters/apiClient";
import {
  fetchLatestShadowEvaluationMetrics,
  fetchShadowEvaluationMetrics,
} from "@/adapters/shadowEvaluation";
import type { ShadowEvaluationMetricsResponse } from "@/types/shadow-evaluation";

interface ShadowEvaluationState {
  data: ShadowEvaluationMetricsResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  isUnavailable: boolean;
  refetch: () => void;
}

export function useShadowEvaluation(tradeDate: string | null, enabled = true): ShadowEvaluationState {
  return useShadowEvaluationRequest(tradeDate, enabled);
}

export function useLatestShadowEvaluation(enabled = true): ShadowEvaluationState {
  return useShadowEvaluationRequest("latest", enabled);
}

function useShadowEvaluationRequest(tradeDate: string | "latest" | null, enabled: boolean): ShadowEvaluationState {
  const [data, setData] = useState<ShadowEvaluationMetricsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [isUnavailable, setIsUnavailable] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    if (!enabled || !tradeDate) {
      setData(null);
      setIsLoading(false);
      setError(null);
      setIsUnavailable(false);
      return () => {
        cancelled = true;
      };
    }

    setData(null);
    setIsLoading(true);
    setError(null);
    setIsUnavailable(false);

    const request = tradeDate === "latest"
      ? fetchLatestShadowEvaluationMetrics()
      : fetchShadowEvaluationMetrics(tradeDate);

    void request
      .then((nextData) => {
        if (!cancelled) {
          setData(nextData);
        }
      })
      .catch((cause) => {
        if (cancelled) {
          return;
        }

        setData(null);
        if (cause instanceof ApiError && cause.status === 404) {
          setIsUnavailable(true);
          return;
        }

        setError(cause instanceof Error ? cause : new Error("加载影子策略评估数据失败"));
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [enabled, reloadToken, tradeDate]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    isUnavailable,
    refetch: useCallback(() => setReloadToken((value) => value + 1), []),
  };
}
