import { useEffect, useState } from "react";
import { fetchJin10WebFlashBriefs, type FetchJin10WebFlashBriefsResult } from "@/adapters/jin10WebFlashBriefs";
import type { Jin10WebFlashBriefsResponse } from "@/types/jin10-web-flash";

const REFRESH_INTERVAL_MS = 120_000;

interface UseJin10WebFlashBriefsState {
  data: Jin10WebFlashBriefsResponse | null;
  isLoading: boolean;
  error: string | null;
}

export function useJin10WebFlashBriefs(): UseJin10WebFlashBriefsState {
  const [data, setData] = useState<Jin10WebFlashBriefsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setInterval(() => {
      void load();
    }, REFRESH_INTERVAL_MS);

    async function load() {
      const result: FetchJin10WebFlashBriefsResult = await fetchJin10WebFlashBriefs();
      if (!cancelled) {
        setData(result.data);
        setError(result.error);
        setIsLoading(false);
      }
    }

    void load();

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return { data, isLoading, error };
}
