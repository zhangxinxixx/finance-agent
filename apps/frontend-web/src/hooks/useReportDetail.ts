import { useEffect, useState } from "react";
import { fetchReportDetailView } from "@/adapters/reports";
import type { ReportDetailView } from "@/types/reports";

interface ReportDetailState {
  data: ReportDetailView | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useReportDetail(reportId: string | undefined): ReportDetailState {
  const [data, setData] = useState<ReportDetailView | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      if (!reportId) {
        setData(null);
        setError(new Error("缺少 reportId"));
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);
      try {
        const nextData = await fetchReportDetailView(reportId, controller.signal);
        if (!cancelled) {
          setData(nextData);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setError(cause instanceof Error ? cause : new Error("加载报告详情失败"));
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
      controller.abort();
    };
  }, [reportId, reloadToken]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useReportDetail;
