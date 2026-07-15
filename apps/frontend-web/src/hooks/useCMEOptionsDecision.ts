import { useEffect, useState } from "react";
import { fetchCMEOptionsDecision } from "@/adapters/cmeOptions";
import type { CMEOptionsDecisionResponse } from "@/types/cme-options";

interface CMEOptionsDecisionState {
  data: CMEOptionsDecisionResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useCMEOptionsDecision(date?: string, enabled = true): CMEOptionsDecisionState {
  const [data, setData] = useState<CMEOptionsDecisionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!enabled) {
      setIsLoading(false);
      setData(null);
      return () => { cancelled = true; };
    }
    setIsLoading(true);
    setError(null);
    void fetchCMEOptionsDecision(date)
      .then((nextData) => { if (!cancelled) setData(nextData); })
      .catch((cause) => {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载 CME Options 决策数据失败"));
        }
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [date, enabled, reloadToken]);

  return { data, isLoading, isError: error !== null, error, refetch: () => setReloadToken((value) => value + 1) };
}
