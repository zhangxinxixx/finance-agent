import { useEffect, useMemo, useState } from "react";
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
  railLoading: boolean;
  railError: Error | null;
  refetch: () => void;
}

function filterFinalReports(reports: ReportIndexItem[]): ReportIndexItem[] {
  return reports.filter((item) => item.type === "final_report");
}

function normalizeAsset(indexData: ReportsIndexResponse | null, datesData: ReportsDatesResponse | null): string {
  return indexData?.asset ?? datesData?.asset ?? "—";
}

export function useReports(): ReportsState {
  const [indexData, setIndexData] = useState<ReportsIndexResponse | null>(null);
  const [datesData, setDatesData] = useState<ReportsDatesResponse | null>(null);
  const [railLoading, setRailLoading] = useState(true);
  const [railError, setRailError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function loadReports() {
      setRailLoading(true);
      setRailError(null);

      const [indexResult, datesResult] = await Promise.allSettled([
          fetchReportsIndex(),
          fetchReportsDates(),
      ]);

      if (cancelled) {
        return;
      }

      if (indexResult.status === "fulfilled" && datesResult.status === "fulfilled") {
        setIndexData(indexResult.value);
        setDatesData(datesResult.value);
        setRailLoading(false);
      } else {
        const cause = indexResult.status === "rejected" ? indexResult.reason : datesResult.status === "rejected" ? datesResult.reason : null;
        const nextError = cause instanceof Error ? cause : new Error("加载报告索引失败");
        setRailError(nextError);
        setRailLoading(false);
      }
    }

    void loadReports();

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const finalReportItems = useMemo(() => filterFinalReports(indexData?.reports ?? []), [indexData?.reports]);
  const asset = normalizeAsset(indexData, datesData);

  return {
    asset,
    dates: datesData?.dates ?? [],
    indexItems: indexData?.reports ?? [],
    finalReportItems,
    railLoading,
    railError,
    refetch: () => setReloadToken((value) => value + 1),
  };
}
