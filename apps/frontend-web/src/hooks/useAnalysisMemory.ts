import { useCallback, useEffect, useState } from "react";

import { acceptAnalysisMemoryCandidate, fetchAnalysisMemory } from "@/adapters/analysisMemory";
import type { AnalysisMemorySnapshot } from "@/types/analysis-memory";

export function useAnalysisMemory(asset = "XAUUSD") {
  const [data, setData] = useState<AnalysisMemorySnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionCandidateId, setActionCandidateId] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setData(await fetchAnalysisMemory(asset));
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error("Analysis Memory 加载失败"));
    } finally {
      setIsLoading(false);
    }
  }, [asset]);

  useEffect(() => { void refetch(); }, [refetch]);

  return {
    data,
    isLoading,
    error,
    actionCandidateId,
    refetch,
    acceptCandidate: async (params: { candidateId: string; token: string; actor: string; reason: string }) => {
      if (!data) return;
      if (!data.canonical) throw new Error("accepted canonical 不可用，不能推进候选");
      setActionCandidateId(params.candidateId);
      setError(null);
      try {
        await acceptAnalysisMemoryCandidate({
          ...params,
          requestId: crypto.randomUUID(),
          canonicalStateId: data.canonical.state.state_id,
          headVersion: data.canonical.head_version,
        });
        await refetch();
      } catch (cause) {
        setError(cause instanceof Error ? cause : new Error("候选复核失败"));
      } finally {
        setActionCandidateId(null);
      }
    },
  };
}
