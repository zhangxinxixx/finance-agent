import { useCallback, useEffect, useState } from "react";

import { acceptAnalysisMemoryCandidate, fetchAnalysisMemory } from "@/adapters/analysisMemory";
import type { AnalysisMemorySnapshot, AnalysisStateScope } from "@/types/analysis-memory";

export function useAnalysisMemory(stateScope: AnalysisStateScope, asset = "XAUUSD") {
  const [data, setData] = useState<AnalysisMemorySnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionCandidateId, setActionCandidateId] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setData(await fetchAnalysisMemory(stateScope, asset));
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error("Analysis Memory 加载失败"));
    } finally {
      setIsLoading(false);
    }
  }, [asset, stateScope]);

  useEffect(() => {
    setData(null);
    void refetch();
  }, [refetch]);

  const scopedData = data
    && data.candidates.state_scope === stateScope
    && data.bundles.state_scope === stateScope
    && (!data.canonical || data.canonical.state_scope === stateScope)
    ? data
    : null;

  return {
    data: scopedData,
    isLoading: isLoading || (data !== null && scopedData === null),
    error,
    actionCandidateId,
    refetch,
    acceptCandidate: async (params: { candidateId: string; token: string; actor: string; reason: string }) => {
      if (!scopedData) return;
      if (!scopedData.canonical) throw new Error("accepted canonical 不可用，不能推进候选");
      setActionCandidateId(params.candidateId);
      setError(null);
      try {
        await acceptAnalysisMemoryCandidate({
          ...params,
          requestId: crypto.randomUUID(),
          canonicalStateId: scopedData.canonical.state.state_id,
          headVersion: scopedData.canonical.head_version,
          stateScope,
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
