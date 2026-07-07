import { useEffect, useState } from "react";
import { fetchPromptEvolutionReview, submitPromptEvolutionReleaseAction } from "@/adapters/promptEvolution";
import type { PromptEvolutionReleaseAction, PromptEvolutionReleaseReadiness, PromptEvolutionReviewResponse } from "@/types/prompt-evolution";

interface PromptEvolutionReviewState {
  review: PromptEvolutionReviewResponse | null;
  release_readiness: PromptEvolutionReleaseReadiness | null;
  caseCount: number;
  releaseRecordCount: number;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  actionKind: PromptEvolutionReleaseAction | null;
  actionError: Error | null;
  submitReleaseAction: (
    action: PromptEvolutionReleaseAction,
    params?: {
      rollbackReason?: string | null;
      testResult?: string | null;
    },
  ) => Promise<void>;
  refetch: () => void;
}

export function usePromptEvolutionReview(date?: string | null): PromptEvolutionReviewState {
  const [review, setReview] = useState<PromptEvolutionReviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionKind, setActionKind] = useState<PromptEvolutionReleaseAction | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await fetchPromptEvolutionReview(date);
        if (!cancelled) {
          setReview(payload);
        }
      } catch (cause) {
        if (!cancelled) {
          setReview(null);
          setError(cause instanceof Error ? cause : new Error("加载 PromptEvolution 验证结果失败"));
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
    review,
    release_readiness: review?.release_readiness ?? null,
    caseCount: review?.cases.count ?? 0,
    releaseRecordCount: review?.release_records.count ?? 0,
    isLoading,
    isError: error !== null,
    error,
    actionKind,
    actionError,
    submitReleaseAction: async (action, params) => {
      const validation = review?.validation;
      const tradeDate = review?.trade_date;
      const agentName = validation?.agent_name ?? review?.release_records.items[0]?.agent_name;
      if (!tradeDate) {
        setActionError(new Error("PromptEvolution trade_date 缺失"));
        return;
      }
      if (!agentName) {
        setActionError(new Error("PromptEvolution agent_name 缺失"));
        return;
      }
      const validationArtifact = review?.artifacts.prompt_ab_validation_result;
      if (action === "release_approved" && !validationArtifact) {
        setActionError(new Error("PromptEvolution validation_artifact 缺失"));
        return;
      }
      if (action === "rolled_back" && !params?.rollbackReason) {
        setActionError(new Error("PromptEvolution rollback_reason 缺失"));
        return;
      }

      setActionKind(action);
      setActionError(null);
      try {
        await submitPromptEvolutionReleaseAction({
          tradeDate,
          agentName,
          action,
          activePromptVersionId: promptVersionRef(validation?.active_prompt_result),
          candidatePromptVersionId: promptVersionRef(validation?.candidate_prompt_result),
          validationArtifact,
          reviewApprovedBy: "review_center",
          testResult: params?.testResult ?? validation?.validation_status ?? undefined,
          rollbackReason: params?.rollbackReason,
        });
        setReloadToken((value) => value + 1);
      } catch (cause) {
        setActionError(cause instanceof Error ? cause : new Error("PromptEvolution 发布动作失败"));
      } finally {
        setActionKind(null);
      }
    },
    refetch: () => setReloadToken((value) => value + 1),
  };
}

function promptVersionRef(payload: Record<string, unknown> | undefined): string | null {
  if (!payload) return null;
  const value = payload.id ?? payload.prompt_version_id ?? payload.version;
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return null;
}
