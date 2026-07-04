import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, RefreshCw } from "lucide-react";
import type { FATabOption } from "@/components/shared/FATabBar";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import {
  ReportsRail,
  type ReportFilters,
} from "@/components/reports/ReportsRail";
import {
  ReportsLibraryContent,
  ReportsPagination,
  ReportsSummaryBar,
} from "@/components/reports/ReportsPageSections";
import {
  ReportsToolbar,
  type ViewMode,
} from "@/components/reports/ReportsToolbar";
import {
  CATEGORY_MAP,
  SUPPORTED_REPORT_TYPES,
  getReportDetailId,
  isSupportedReportType,
  type SupportedReportType,
} from "@/components/reports/reportListMeta";
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
    asset,
    dates,
    indexItems,
    railLoading,
    railError,
    refetch,
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
  const activeReportTab: SupportedReportType | "all" =
    filters.reportTypes.length === 1 && isSupportedReportType(filters.reportTypes[0])
      ? filters.reportTypes[0]
      : "all";
  const reportTabs = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of allReports) {
      counts.set(item.type, (counts.get(item.type) ?? 0) + 1);
    }

    return [
      { value: "all", label: "全部", count: allReports.length },
      ...SUPPORTED_REPORT_TYPES.map((type) => ({
        value: type,
        label: CATEGORY_MAP[type]?.label ?? type,
        count: counts.get(type) ?? 0,
      })),
    ] satisfies Array<FATabOption<SupportedReportType | "all">>;
  }, [allReports]);

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

  function handleReportTabChange(next: SupportedReportType | "all") {
    setFilters((current) => ({
      ...current,
      reportTypes: next === "all" ? [] : [next],
    }));
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
      toolbar={(
        <FAWorkspaceHeader
          className="reports-workspace-header"
          icon={FileText}
          title="报告中心"
          tabs={reportTabs}
          value={activeReportTab}
          onChange={handleReportTabChange}
          ariaLabel="报告类型切换"
          actions={(
            <button type="button" onClick={refetch} className="fa-workspace-toolbar-button">
              <RefreshCw size={12} />
              刷新
            </button>
          )}
          primaryLabel="报告状态"
          primaryItems={[
            { label: "全部", value: allReports.length },
            { label: "筛后", value: filteredReports.length },
            { label: "可读", value: allReports.filter((item) => item.available).length },
            { label: "资产", value: asset },
          ]}
          secondaryLabel="时间"
          secondaryItems={[
            { label: "最新", value: availableDates[0] ?? "—" },
            { label: "页数", value: totalPages },
          ]}
        />
      )}
    >
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
