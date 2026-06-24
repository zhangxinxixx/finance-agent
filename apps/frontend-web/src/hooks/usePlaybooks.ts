import { useCallback, useEffect, useState } from "react";
import { fetchPlaybookRegistryView } from "@/adapters/playbooks";
import type { PlaybookRegistryViewModel } from "@/types/playbook";

interface UsePlaybooksState {
  data: PlaybookRegistryViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function usePlaybooks(selectedId?: string | null): UsePlaybooksState {
  const [data, setData] = useState<PlaybookRegistryViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const nextData = await fetchPlaybookRegistryView(selectedId);
        if (!cancelled) {
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载 Playbook 失败"));
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
  }, [reloadToken, selectedId]);

  const refetch = useCallback(() => setReloadToken((value) => value + 1), []);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch,
  };
}
