import { useEffect, useState } from "react";
import { fetchJson } from "@/adapters/apiClient";
import type { Jin10QuotesResponse } from "@/types/jin10";

const JIN10_QUOTES_PATH = "/api/jin10/quotes/latest";
const REFRESH_INTERVAL_MS = 30_000;

interface Jin10QuotesState {
  data: Jin10QuotesResponse | null;
  isLoading: boolean;
  isError: boolean;
}

export function useJin10Quotes(): Jin10QuotesState {
  const [data, setData] = useState<Jin10QuotesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval>;

    async function load() {
      try {
        const result = await fetchJson<J10QuotesResponse>(JIN10_QUOTES_PATH);
        if (!cancelled) {
          setData(result);
          setIsError(false);
        }
      } catch {
        if (!cancelled) {
          setIsError(true);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();
    timer = setInterval(() => { void load(); }, REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return { data, isLoading, isError };
}

// Alias to avoid naming collision in the fetch call
type J10QuotesResponse = Jin10QuotesResponse;
