import { useEffect, useRef, useState } from "react";
import { fetchReportDetailView } from "@/adapters/reports";
import type { ReportDetailView } from "@/types/reports";

interface ReportDetailState {
  data: ReportDetailView | null;
  isLoading: boolean;
  isRefreshing: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useReportDetail(reportId: string | undefined): ReportDetailState {
  const [result, setResult] = useState<{ reportId: string; data: ReportDetailView } | null>(null);
  const resultRef = useRef<typeof result>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const pending = useRef<string | null>(reportId ?? null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      if (!reportId) {
        setResult(null);
        resultRef.current = null;
        setError(new Error("缺少 reportId"));
        setIsLoading(false);
        return;
      }

      pending.current = reportId;
      setIsLoading(true);
      setError(null);
      try {
        const nextData = await fetchReportDetailView(reportId, controller.signal);
        if (!cancelled) {
          const nextResult = { reportId, data: nextData };
          resultRef.current = nextResult;
          setResult(nextResult);
        }
      } catch (cause) {
        if (!cancelled) {
          if (resultRef.current?.reportId !== reportId) setResult(null);
          setError(cause instanceof Error ? cause : new Error("加载报告详情失败"));
        }
      } finally {
        if (!cancelled) {
          pending.current = null;
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
      controller.abort();
      pending.current = null;
    };
  }, [reportId, reloadToken]);

  return {
    // A route change must never expose the previous report under a new ID,
    // even in the render before the loading effect starts.
    data: result && result.reportId === reportId ? result.data : null,
    isLoading: isLoading || (error === null && result?.reportId !== reportId),
    isRefreshing: isLoading && result !== null && result.reportId === reportId,
    isError: error !== null,
    error,
    refetch: () => {
      if (!reportId || pending.current === reportId) return;
      pending.current = reportId;
      setReloadToken((value) => value + 1);
    },
  };
}

export default useReportDetail;
