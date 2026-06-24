import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import {
  ReportsRail,
  type ReportFilters,
} from "@/components/reports/ReportsRail";
import { ReportsKpiStrip } from "@/components/reports/ReportsKpiStrip";
import {
  ReportsLibraryContent,
  ReportsPagination,
  ReportsSummaryBar,
} from "@/components/reports/ReportsPageSections";
import {
  ReportsToolbar,
  type ViewMode,
} from "@/components/reports/ReportsToolbar";
import { getReportDetailId, isSupportedReportType } from "@/components/reports/reportListMeta";
import {
  dedupeSupportedReports,
  filterReports,
  listAvailableReportDates,
} from "@/components/reports/reportsPageModel";
import { useReports } from "@/hooks/useReports";
import type { ReportIndexItem } from "@/types/reports";

export function ReportsPage() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [currentPage, setCurrentPage] = useState(1);
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

  const pageSize = useMemo(() => {
    switch (viewMode) {
      case "timeline":
        return 10;
      case "grid":
        return 12;
      case "list":
      default:
        return 14;
    }
  }, [viewMode]);

  const totalPages = Math.max(1, Math.ceil(filteredReports.length / pageSize));
  const pagedReports = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredReports.slice(start, start + pageSize);
  }, [filteredReports, currentPage, pageSize]);

  const availableDates = useMemo(
    () => listAvailableReportDates(dates),
    [dates],
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, filters, viewMode]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

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
    <FAPageScaffold
      className="reports-page-shell"
    >
      <ReportsKpiStrip reports={allReports} availableDates={availableDates} />

      <div className="fa-split-grid fa-split-grid--left reports-page-grid overflow-hidden">
        <ReportsRail
          reports={allReports}
          filters={filters}
          onFilterChange={setFilters}
          railLoading={railLoading}
          railError={railError}
        />

        <main className="fa-scroll-column fa-chrome-band reports-main-panel p-1.5">
          <ReportsToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
          />

          <ReportsSummaryBar
            hasFilteredResults={filteredReports.length !== allReports.length}
            onResetFilters={resetFilters}
          />

          <ReportsLibraryContent
            viewMode={viewMode}
            filteredReports={pagedReports}
            searchQuery={searchQuery}
            onSelectReport={handleCardSelect}
          />

          <ReportsPagination
            currentPage={currentPage}
            totalPages={totalPages}
            totalItems={filteredReports.length}
            pageSize={pageSize}
            onPageChange={setCurrentPage}
          />
        </main>
      </div>
    </FAPageScaffold>
  );
}

export default ReportsPage;
