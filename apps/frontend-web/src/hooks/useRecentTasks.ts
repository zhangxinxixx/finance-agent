import { useEffect, useState } from "react";
import { fetchJson } from "@/adapters/apiClient";

export interface TaskRun {
  id: string;
  name: string;
  status: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  step_count: number;
}

interface TasksResponse {
  tasks: TaskRun[];
  total: number;
}

interface UseRecentTasksState {
  data: TaskRun[];
  isLoading: boolean;
  isError: boolean;
}

export function useRecentTasks(limit = 5): UseRecentTasksState {
  const [data, setData] = useState<TaskRun[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const result = await fetchJson<TasksResponse>(`/api/tasks?limit=${limit}`);
        if (!cancelled) {
          setData(result.tasks ?? []);
          setIsError(false);
        }
      } catch {
        if (!cancelled) setIsError(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [limit]);

  return { data, isLoading, isError };
}
