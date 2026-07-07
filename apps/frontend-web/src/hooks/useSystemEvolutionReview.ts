import { useEffect, useState } from "react";
import {
  fetchSystemEvolutionReview,
  submitSystemEvolutionProposalAction,
  type SystemEvolutionProposalAction,
} from "@/adapters/systemEvolution";
import type { SystemEvolutionProposal, SystemEvolutionReviewResponse } from "@/types/system-evolution";

interface SystemEvolutionReviewState {
  review: SystemEvolutionReviewResponse | null;
  findingCount: number;
  proposalCount: number;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  actionProposalId: string | null;
  actionError: Error | null;
  submitProposalAction: (
    proposal: SystemEvolutionProposal,
    action: SystemEvolutionProposalAction,
    params?: {
      issueUrl?: string | null;
      prUrl?: string | null;
      testResult?: string | null;
      manualConfirmation?: string | null;
      rollbackReason?: string | null;
      note?: string | null;
    },
  ) => Promise<void>;
  refetch: () => void;
}

export function useSystemEvolutionReview(date?: string | null): SystemEvolutionReviewState {
  const [review, setReview] = useState<SystemEvolutionReviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionProposalId, setActionProposalId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await fetchSystemEvolutionReview(date);
        if (!cancelled) {
          setReview(payload);
        }
      } catch (cause) {
        if (!cancelled) {
          setReview(null);
          setError(cause instanceof Error ? cause : new Error("加载 SystemEvolution 复核失败"));
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
    findingCount: review?.findings.count ?? 0,
    proposalCount: review?.proposals.count ?? 0,
    isLoading,
    isError: error !== null,
    error,
    actionProposalId,
    actionError,
    submitProposalAction: async (proposal, action, params) => {
      const proposalId = proposal.proposal_id;
      if (!proposalId) {
        setActionError(new Error("SystemEvolution proposal_id 缺失"));
        return;
      }
      const tradeDate = review?.trade_date;
      if (!tradeDate) {
        setActionError(new Error("SystemEvolution trade_date 缺失"));
        return;
      }
      setActionProposalId(proposalId);
      setActionError(null);
      try {
        await submitSystemEvolutionProposalAction({
          date: tradeDate,
          proposalId,
          action,
          actor: "review_center",
          note: params?.note ?? proposal.rationale ?? undefined,
          issueUrl: params?.issueUrl,
          prUrl: params?.prUrl,
          testResult: params?.testResult,
          manualConfirmation: params?.manualConfirmation,
          rollbackReason: params?.rollbackReason,
        });
        setReloadToken((value) => value + 1);
      } catch (cause) {
        setActionError(cause instanceof Error ? cause : new Error("SystemEvolution 提案动作失败"));
      } finally {
        setActionProposalId(null);
      }
    },
    refetch: () => setReloadToken((value) => value + 1),
  };
}
