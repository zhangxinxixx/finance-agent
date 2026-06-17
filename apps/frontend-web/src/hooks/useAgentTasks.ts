import { useEffect, useState } from "react";
import { fetchAgentTasksView } from "@/adapters/agentTasks";
import type { AgentTasksViewModel } from "@/types/agent-task";

interface AgentTasksState {
  data: AgentTasksViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useAgentTasks(selectedRunId?: string | null): AgentTasksState {
  const [data, setData] = useState<AgentTasksViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const nextData = await fetchAgentTasksView(selectedRunId);
        if (!cancelled) {
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载 Agent Tasks 失败"));
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
  }, [reloadToken, selectedRunId]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useAgentTasks;
