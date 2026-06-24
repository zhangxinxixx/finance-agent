import { useEffect, useState } from "react";
import { fetchCMEOptionsData } from "@/adapters/cmeOptions";
import type { CMEOptionsResponse } from "@/types/cme-options";

interface CMEOptionsState {
  data: CMEOptionsResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useCMEOptions(date?: string, enabled = true): CMEOptionsState {
  const [data, setData] = useState<CMEOptionsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadCMEOptions() {
      if (!enabled) {
        setIsLoading(true);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const nextData = await fetchCMEOptionsData(date);

        if (!cancelled) {
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause : new Error("加载 CME Options 数据失败"));
          setData(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadCMEOptions();

    return () => {
      cancelled = true;
    };
  }, [date, enabled, reloadToken]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}
