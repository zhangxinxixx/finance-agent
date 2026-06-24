import { useEffect, useState } from "react";
import { fetchReviewCenterReviews } from "@/adapters/agentTasks";
import type { TaskReviewViewModel } from "@/types/agent-task";

interface ReviewCenterState {
  reviews: TaskReviewViewModel[];
  total: number;
  source: "api" | "unavailable";
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useReviewCenter(params: { status?: string; sourceModule?: string; runId?: string }): ReviewCenterState {
  const [reviews, setReviews] = useState<TaskReviewViewModel[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState<ReviewCenterState["source"]>("unavailable");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await fetchReviewCenterReviews(params);
        if (!cancelled) {
          setReviews(payload.reviews);
          setTotal(payload.total);
          setSource(payload.source);
        }
      } catch (cause) {
        if (!cancelled) {
          setReviews([]);
          setTotal(0);
          setSource("unavailable");
          setError(cause instanceof Error ? cause : new Error("加载 Review Center 失败"));
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
  }, [params.runId, params.sourceModule, params.status, reloadToken]);

  return {
    reviews,
    total,
    source,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}
