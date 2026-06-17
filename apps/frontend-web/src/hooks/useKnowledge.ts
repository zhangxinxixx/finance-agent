import { useCallback, useEffect, useState } from "react";
import { fetchKnowledgeView, KNOWLEDGE_TOPICS, KNOWLEDGE_STATUSES } from "@/adapters/knowledge";
import type { KnowledgeViewModel, KnowledgeTypeTab } from "@/types/knowledge";

interface UseKnowledgeOptions {
  search?: string;
  topic?: string;
  status?: string;
  typeTab?: KnowledgeTypeTab;
  selectedId?: string | null;
}

interface UseKnowledgeState {
  data: KnowledgeViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
  topics: typeof KNOWLEDGE_TOPICS;
  statuses: typeof KNOWLEDGE_STATUSES;
}

export function useKnowledge(options?: UseKnowledgeOptions): UseKnowledgeState {
  const [data, setData] = useState<KnowledgeViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const nextData = await fetchKnowledgeView({
          search: options?.search,
          topic: options?.topic,
          status: options?.status,
          typeTab: options?.typeTab,
          selectedId: options?.selectedId,
        });
        if (!cancelled) {
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载知识库失败"));
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
  }, [reloadToken, options?.search, options?.topic, options?.status, options?.typeTab, options?.selectedId]);

  const refetch = useCallback(() => setReloadToken((value) => value + 1), []);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch,
    topics: KNOWLEDGE_TOPICS,
    statuses: KNOWLEDGE_STATUSES,
  };
}

export default useKnowledge;
