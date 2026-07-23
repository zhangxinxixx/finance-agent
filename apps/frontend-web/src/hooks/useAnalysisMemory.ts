import { useCallback, useEffect, useRef, useState } from "react";

import { acceptAnalysisMemoryCandidate, fetchAnalysisMemory } from "@/adapters/analysisMemory";
import type { AnalysisMemorySnapshot, AnalysisStateScope } from "@/types/analysis-memory";

export function useAnalysisMemory(stateScope: AnalysisStateScope, asset = "XAUUSD") {
  const [data, setData] = useState<AnalysisMemorySnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [actionCandidateId, setActionCandidateId] = useState<string | null>(null);
  const requestGenerationRef = useRef(0);
  const currentScopeRef = useRef(stateScope);
  const currentAssetRef = useRef(asset);
  currentScopeRef.current = stateScope;
  currentAssetRef.current = asset;

  const refetch = useCallback(async () => {
    const requestedScope = stateScope;
    const requestedAsset = asset;
    if (currentScopeRef.current !== requestedScope || currentAssetRef.current !== requestedAsset) return;
    const requestGeneration = ++requestGenerationRef.current;
    const isCurrentRequest = () => (
      requestGenerationRef.current === requestGeneration
      && currentScopeRef.current === requestedScope
      && currentAssetRef.current === requestedAsset
    );
    setIsLoading(true);
    setError(null);
    try {
      const nextData = await fetchAnalysisMemory(requestedScope, requestedAsset);
      if (!isCurrentRequest()) return;
      setData(nextData);
    } catch (cause) {
      if (!isCurrentRequest()) return;
      setError(cause instanceof Error ? cause : new Error("Analysis Memory 加载失败"));
    } finally {
      if (isCurrentRequest()) setIsLoading(false);
    }
  }, [asset, stateScope]);

  useEffect(() => {
    setData(null);
    setActionCandidateId(null);
    void refetch();
    return () => {
      requestGenerationRef.current += 1;
    };
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
      if (currentScopeRef.current !== stateScope || currentAssetRef.current !== asset) return;
      if (!scopedData) return;
      if (!scopedData.canonical) throw new Error("accepted canonical 不可用，不能推进候选");
      const acceptScope = stateScope;
      const acceptAsset = asset;
      setActionCandidateId(params.candidateId);
      setError(null);
      try {
        await acceptAnalysisMemoryCandidate({
          ...params,
          requestId: crypto.randomUUID(),
          canonicalStateId: scopedData.canonical.state.state_id,
          headVersion: scopedData.canonical.head_version,
          stateScope: acceptScope,
        });
        if (currentScopeRef.current === acceptScope && currentAssetRef.current === acceptAsset) {
          await refetch();
        }
      } catch (cause) {
        if (currentScopeRef.current === acceptScope && currentAssetRef.current === acceptAsset) {
          setError(cause instanceof Error ? cause : new Error("候选复核失败"));
        }
      } finally {
        if (currentScopeRef.current === acceptScope && currentAssetRef.current === acceptAsset) {
          setActionCandidateId(null);
        }
      }
    },
  };
}
