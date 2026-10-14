import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchReportsDates, fetchReportsIndex } from "@/adapters/reports";
import type {
  ReportDateItem,
  ReportIndexItem,
  ReportsDatesResponse,
  ReportsIndexResponse,
} from "@/types/reports";

interface ReportsState {
  asset: string;
  dates: ReportDateItem[];
  indexItems: ReportIndexItem[];
  finalReportItems: ReportIndexItem[];
  indexLoading: boolean;
  indexError: Error | null;
  indexHasLoaded: boolean;
  indexReadAt: string | null;
  datesLoading: boolean;
  datesError: Error | null;
  datesHasLoaded: boolean;
  datesReadAt: string | null;
  refetch: () => void;
}

function filterFinalReports(reports: ReportIndexItem[]): ReportIndexItem[] {
  return reports.filter((item) => item.type === "final_report");
}

function normalizeAsset(indexData: ReportsIndexResponse | null, datesData: ReportsDatesResponse | null): string {
  return indexData?.asset ?? datesData?.asset ?? "—";
}

interface ReadState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  // Local read completion, never the report's data_as_of or generated_at.
  readAt: string | null;
}

function initialReadState<T>(): ReadState<T> {
  return { data: null, loading: true, error: null, readAt: null };
}

export function useReports(): ReportsState {
  const [index, setIndex] = useState(initialReadState<ReportsIndexResponse>);
  const [dates, setDates] = useState(initialReadState<ReportsDatesResponse>);
  const [reloadToken, setReloadToken] = useState(0);
  const refetch = useCallback(() => setReloadToken((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;

    async function read<T>(load: () => Promise<T>, setState: (update: (previous: ReadState<T>) => ReadState<T>) => void, label: string) {
      setState((previous) => ({ ...previous, loading: true, error: null }));
      try {
        const data = await load();
        if (!cancelled) {
          const readAt = new Date().toISOString();
          setState(() => ({ data, loading: false, error: null, readAt }));
        }
      } catch (cause) {
        if (!cancelled) {
          const error = cause instanceof Error ? cause : new Error(`${label}读取失败`);
          setState((previous) => ({ ...previous, loading: false, error }));
        }
      }
    }

    // Each result is published on arrival. Adapters retain shared in-flight
    // deduplication; cleanup invalidates this subscriber, not other consumers.
    void read(fetchReportsIndex, setIndex, "报告索引");
    void read(fetchReportsDates, setDates, "报告日期");

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const finalReportItems = useMemo(() => filterFinalReports(index.data?.reports ?? []), [index.data?.reports]);
  const asset = normalizeAsset(index.data, dates.data);

  return {
    asset,
    dates: dates.data?.dates ?? [],
    indexItems: index.data?.reports ?? [],
    finalReportItems,
    indexLoading: index.loading,
    indexError: index.error,
    indexHasLoaded: index.data !== null,
    indexReadAt: index.readAt,
    datesLoading: dates.loading,
    datesError: dates.error,
    datesHasLoaded: dates.data !== null,
    datesReadAt: dates.readAt,
    refetch,
  };
}
