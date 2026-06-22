import { useEffect, useState } from "react";
import { fetchEventFlowOverviewView, fetchEventFlowReportInputsView } from "@/adapters/eventFlow";
import type { EventFlowViewModel } from "@/types/event-flow";

interface EventFlowState {
  data: EventFlowViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useEventFlow(): EventFlowState {
  const [data, setData] = useState<EventFlowViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const nextData = await fetchEventFlowOverviewView();
        if (!cancelled) {
          setData(nextData);
          setIsLoading(false);
        }

        const enrichedData = await fetchEventFlowReportInputsView(nextData);
        if (!cancelled) {
          setData(enrichedData);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载事件流数据失败"));
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
  }, [reloadToken]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useEventFlow;
