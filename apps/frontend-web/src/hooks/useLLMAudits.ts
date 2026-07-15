import { useEffect, useState } from "react";
import { fetchLLMAudits, type LLMAuditFilters } from "@/adapters/llmAudit";
import type { LLMAuditListResponse } from "@/types/llm-audit";

export function useLLMAudits(filters: LLMAuditFilters) {
  const [data, setData] = useState<LLMAuditListResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    void fetchLLMAudits(filters)
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause : new Error("加载 LLM 审计失败"));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters.caller, filters.model, filters.provider, filters.reportId, filters.runId, filters.status, filters.tradeDate, reloadToken]);

  return { data, error, isLoading, refetch: () => setReloadToken((value) => value + 1) };
}
