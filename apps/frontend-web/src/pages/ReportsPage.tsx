import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ReportsRail,
  type ReportFilters,
} from "@/components/reports/ReportsRail";
import { ReportsKpiStrip } from "@/components/reports/ReportsKpiStrip";
import {
  ReportsLibraryContent,
  ReportsSummaryBar,
} from "@/components/reports/ReportsPageSections";
import {
  ReportsToolbar,
  type ViewMode,
} from "@/components/reports/ReportsToolbar";
import { getReportDetailId, isSupportedReportType } from "@/components/reports/reportListMeta";
import {
  buildReportSummaryText,
  dedupeSupportedReports,
  filterReports,
  listAvailableReportDates,
} from "@/components/reports/reportsPageModel";
import { useReports } from "@/hooks/useReports";
import type { ReportIndexItem } from "@/types/reports";

export function ReportsPage() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [filters, setFilters] = useState<ReportFilters>({
    reportTypes: [],
    asset: null,
    status: null,
    dataSource: null,
    dateRange: null,
  });
  const {
    dates,
    indexItems,
    railLoading,
    railError,
  } = useReports();

  const allReports: ReportIndexItem[] = useMemo(() => {
    return dedupeSupportedReports(indexItems);
  }, [indexItems]);

  const filteredReports = useMemo(() => {
    return filterReports(allReports, searchQuery, filters);
  }, [allReports, searchQuery, filters]);

  const availableDates = useMemo(
    () => listAvailableReportDates(dates),
    [dates],
  );

  const reportSummaryText = buildReportSummaryText(filteredReports.length, allReports.length);

  function resetFilters() {
    setFilters({
      reportTypes: [],
      asset: null,
      status: null,
      dataSource: null,
      dateRange: null,
    });
  }

  function handleCardSelect(item: ReportIndexItem) {
    if (!isSupportedReportType(item.type)) return;
    const reportId = getReportDetailId(item);
    if (!reportId) return;
    navigate(`/reports/${encodeURIComponent(reportId)}`);
  }

  return (
    <div className="finance-page-shell" style={{ gap: 8 }}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          flex: 1,
          minHeight: 0,
        }}
      >
        <ReportsKpiStrip reports={allReports} availableDates={availableDates} />

        <ReportsToolbar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
        />

        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          <ReportsRail
            reports={allReports}
            filters={filters}
            onFilterChange={setFilters}
            railLoading={railLoading}
            railError={railError}
          />

          <main
            style={{
              flex: 1,
              overflowY: "auto",
              padding: 6,
              display: "flex",
              flexDirection: "column",
              minWidth: 0,
            }}
          >
            <ReportsSummaryBar
              reportSummaryText={reportSummaryText}
              hasFilteredResults={filteredReports.length !== allReports.length}
              onResetFilters={resetFilters}
            />

            <ReportsLibraryContent
              viewMode={viewMode}
              filteredReports={filteredReports}
              searchQuery={searchQuery}
              onSelectReport={handleCardSelect}
            />
          </main>
        </div>
      </div>
    </div>
  );
}

export default ReportsPage;
