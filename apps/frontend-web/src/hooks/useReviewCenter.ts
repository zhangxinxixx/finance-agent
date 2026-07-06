import { useEffect, useState } from "react";
import { fetchReviewCenterReviews, resolveReviewCenterReview, type ReviewActionKind } from "@/adapters/agentTasks";
import type { TaskReviewViewModel } from "@/types/agent-task";

interface ReviewCenterState {
  reviews: TaskReviewViewModel[];
  total: number;
  source: "api" | "unavailable";
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  actionReviewId: string | null;
  actionError: Error | null;
  resolveReview: (review: TaskReviewViewModel, action: ReviewActionKind) => Promise<void>;
  refetch: () => void;
}

export function useReviewCenter(params: { status?: string; sourceModule?: string; runId?: string }): ReviewCenterState {
  const [reviews, setReviews] = useState<TaskReviewViewModel[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState<ReviewCenterState["source"]>("unavailable");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionReviewId, setActionReviewId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
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
    actionReviewId,
    actionError,
    resolveReview: async (review, action) => {
      setActionReviewId(review.review_id);
      setActionError(null);
      try {
        await resolveReviewCenterReview(review.review_id, action, {
          actor: "review_center",
          reason: action === "use-fallback" ? "采用 AgentLoop 备用输出" : action,
          expectedStatus: review.status,
        });
        setReloadToken((value) => value + 1);
      } catch (cause) {
        setActionError(cause instanceof Error ? cause : new Error("复核动作执行失败"));
      } finally {
        setActionReviewId(null);
      }
    },
    refetch: () => setReloadToken((value) => value + 1),
  };
}
