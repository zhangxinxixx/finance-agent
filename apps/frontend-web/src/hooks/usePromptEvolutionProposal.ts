import { useEffect, useState } from "react";
import { fetchPromptEvolutionProposal } from "@/adapters/agentRegistry";
import type { PromptEvolutionPreviewResponse } from "@/types/agent-registry";

interface PromptEvolutionProposalState {
  preview: PromptEvolutionPreviewResponse | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function usePromptEvolutionProposal(agentId: string, recentLimit = 10): PromptEvolutionProposalState {
  const [preview, setPreview] = useState<PromptEvolutionPreviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await fetchPromptEvolutionProposal(agentId, recentLimit);
        if (!cancelled) {
          setPreview(payload);
        }
      } catch (cause) {
        if (!cancelled) {
          setPreview(null);
          setError(cause instanceof Error ? cause : new Error("加载 PromptEvolution 提案失败"));
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
  }, [agentId, recentLimit, reloadToken]);

  return {
    preview,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}
