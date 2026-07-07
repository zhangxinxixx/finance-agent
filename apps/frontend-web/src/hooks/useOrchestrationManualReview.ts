import { useEffect, useState } from "react";
import {
  fetchOrchestrationManualReview,
  submitOrchestrationManualReviewAction,
  type OrchestrationManualReviewAction,
  type OrchestrationManualReviewItem,
} from "@/adapters/orchestration";

interface OrchestrationManualReviewState {
  tradeDate: string;
  items: OrchestrationManualReviewItem[];
  count: number;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  actionDedupeKey: string | null;
  actionError: Error | null;
  submitAction: (item: OrchestrationManualReviewItem, action: OrchestrationManualReviewAction) => Promise<void>;
  refetch: () => void;
}

export function useOrchestrationManualReview(date?: string | null): OrchestrationManualReviewState {
  const [tradeDate, setTradeDate] = useState("");
  const [items, setItems] = useState<OrchestrationManualReviewItem[]>([]);
  const [count, setCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionDedupeKey, setActionDedupeKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await fetchOrchestrationManualReview(date);
        if (!cancelled) {
          setTradeDate(payload.trade_date);
          setItems(payload.items ?? []);
          setCount(payload.count ?? 0);
        }
      } catch (cause) {
        if (!cancelled) {
          setTradeDate("");
          setItems([]);
          setCount(0);
          setError(cause instanceof Error ? cause : new Error("加载自动化复核失败"));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [date, reloadToken]);

  return {
    tradeDate,
    items,
    count,
    isLoading,
    isError: error !== null,
    error,
    actionDedupeKey,
    actionError,
    submitAction: async (item, action) => {
      setActionDedupeKey(item.dedupe_key);
      setActionError(null);
      try {
        await submitOrchestrationManualReviewAction({
          date: tradeDate,
          dedupeKey: item.dedupe_key,
          action,
          actor: "review_center",
          note: item.reason ?? undefined,
        });
        setReloadToken((value) => value + 1);
      } catch (cause) {
        setActionError(cause instanceof Error ? cause : new Error("自动化复核动作失败"));
      } finally {
        setActionDedupeKey(null);
      }
    },
    refetch: () => setReloadToken((value) => value + 1),
  };
}
