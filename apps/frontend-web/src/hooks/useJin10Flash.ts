import { useEffect, useState } from "react";
import { fetchJson } from "@/adapters/apiClient";

export interface Jin10FlashItem {
  id: string;
  time: string;
  content: string;
  url?: string;
  channel?: string[];
  is_key_event?: boolean;
  importance?: "high" | "medium" | "normal" | string;
  signal_tags?: string[];
  filter_reason?: string;
  classification_provider?: string;
  classification_model?: string;
  classification_confidence?: number;
}

interface Jin10FlashResponse {
  generated_at?: string;
  items: Jin10FlashItem[];
  status?: string;
}

interface UseJin10FlashState {
  data: Jin10FlashItem[];
  isLoading: boolean;
  isError: boolean;
}

export function useJin10Flash(limit = 10, pollIntervalMs = 60_000): UseJin10FlashState {
  const [data, setData] = useState<Jin10FlashItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    async function load({ initial = false }: { initial?: boolean } = {}) {
      if (initial) {
        setIsLoading(true);
      }
      try {
        const result = await fetchJson<Jin10FlashResponse>("/api/jin10/flash");
        if (!cancelled) {
          setData((result.items ?? []).slice(0, limit));
          setIsError(false);
        }
      } catch {
        if (!cancelled) setIsError(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void load({ initial: true });
    if (pollIntervalMs > 0) {
      timer = setInterval(() => {
        void load();
      }, pollIntervalMs);
    }
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [limit, pollIntervalMs]);

  return { data, isLoading, isError };
}
