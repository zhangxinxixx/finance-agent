import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { FileText, RefreshCw } from "lucide-react";
import type { FATabOption } from "@/components/shared/FATabBar";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
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
  SUPPORTED_REPORT_TYPES,
  getReportDetailId,
  isSupportedReportType,
  reportTypeLabel,
  reportAssetLabel,
  type SupportedReportType,
} from "@/components/reports/reportListMeta";
import {
  dedupeSupportedReports,
  filterReports,
  getLatestReportTradeDate,
} from "@/components/reports/reportsPageModel";
import { useReports } from "@/hooks/useReports";
import type { ReportIndexItem } from "@/types/reports";
import { readReportsQuery } from "@/components/reports/reportsNavigation";
import { readingErrorMessage } from "@/components/reading/readingFormat";
import { ReportsReadStatus } from "@/components/reports/ReportsReadStatus";

export function ReportsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const { searchQuery, viewMode, currentPage, filters } = readReportsQuery(params);
  const panelRef = useRef<HTMLElement>(null);
  const preservedScrollTopRef = useRef<number | null>(null);
  const preserveScrollDuringRefreshRef = useRef(false);
  const previousScrollKeyRef = useRef<string>(`finance-reports-scroll:${location.search}`);
  const [filtersOpen, setFiltersOpen] = useState(() => window.matchMedia("(min-width: 900px)").matches);
  const scrollKey = `finance-reports-scroll:${location.search}`;
  function updateQuery(values: Record<string, string | null>, resetPage = true) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(values)) {
        if (value) next.set(key, value); else next.delete(key);
      }
      if (resetPage) next.delete("page");
      return next;
    }, { replace: true });
  }
  const setSearchQuery = (q: string) => updateQuery({ q });
  const setViewMode = (view: ViewMode) => updateQuery({ view });
  const setCurrentPage = (page: number) => updateQuery({ page: String(page) }, false);
  function setFilters(next: ReportFilters | ((current: ReportFilters) => ReportFilters)) {
    const value = typeof next === "function" ? next(filters) : next;
    updateQuery({ types: value.reportTypes.join(","), asset: value.asset, status: value.status, source: value.dataSource, range: value.dateRange });
  }
  const {
    asset,
    indexItems,
    indexLoading,
    indexError,
    indexHasLoaded,
    indexReadAt,
    datesLoading,
    datesError,
    datesHasLoaded,
    datesReadAt,
    refetch,
  } = useReports();

  function rememberScrollPosition(value: number) {
    if (!Number.isFinite(value)) return;
    preservedScrollTopRef.current = value;
    try { sessionStorage.setItem(scrollKey, String(value)); } catch { /* Optional restoration. */ }
  }

  function handleReportsRefresh() {
    // Capture directly from the panel as well as from onScroll. This covers
    // programmatic scroll restoration and the refresh click happening before
    // a synthetic scroll event reaches React.
    preserveScrollDuringRefreshRef.current = true;
    if (panelRef.current) rememberScrollPosition(panelRef.current.scrollTop);
    refetch();
  }

  useEffect(() => {
    const media = window.matchMedia("(min-width: 900px)");
    const resize = () => setFiltersOpen(media.matches);
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);

  const allReports: ReportIndexItem[] = useMemo(() => {
    return dedupeSupportedReports(indexItems);
  }, [indexItems]);

  const filteredReports = useMemo(() => {
    return filterReports(allReports, searchQuery, filters);
  }, [allReports, searchQuery, filters]);

  const latestReportTradeDate = useMemo(() => getLatestReportTradeDate(allReports), [allReports]);
  const indexRetainsPreviousResult = indexHasLoaded && (indexLoading || Boolean(indexError));
  const reportDateSummaryLabel = indexRetainsPreviousResult ? "上次索引内最新报告交易日" : "索引内最新报告交易日";
  const reportDateSummaryValue = !indexHasLoaded
    ? (indexLoading ? "读取中" : "未取得")
    : (latestReportTradeDate ?? "未知");

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
        label: reportTypeLabel(type),
        count: counts.get(type) ?? 0,
      })),
    ] satisfies Array<FATabOption<SupportedReportType | "all">>;
  }, [allReports]);

  useEffect(() => {
    if (indexHasLoaded && !indexLoading && !indexError && currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages, indexHasLoaded, indexLoading, indexError]);

  useEffect(() => {
    if (previousScrollKeyRef.current !== scrollKey) {
      preservedScrollTopRef.current = null;
      preserveScrollDuringRefreshRef.current = false;
      previousScrollKeyRef.current = scrollKey;
    }
  }, [scrollKey]);

  useEffect(() => {
    if (!indexHasLoaded || indexLoading) return;
    const frame = requestAnimationFrame(() => {
      try {
        const saved = preservedScrollTopRef.current ?? Number(sessionStorage.getItem(scrollKey) ?? 0);
        if (panelRef.current) panelRef.current.scrollTop = Number.isFinite(saved) ? saved : 0;
        if (preserveScrollDuringRefreshRef.current) {
          requestAnimationFrame(() => {
            preserveScrollDuringRefreshRef.current = false;
          });
        }
      } catch { /* Session storage may be disabled; the list is still usable. */ }
    });
    return () => cancelAnimationFrame(frame);
  }, [scrollKey, indexHasLoaded, indexLoading]);

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
    navigate(`/reports/${encodeURIComponent(reportId)}`, { state: { reportsReturnTo: `/reports${location.search}`, reportSelection: item } });
  }

  const datesStatus = <ReportsReadStatus kind="dates" loading={datesLoading} error={datesError} hasLoaded={datesHasLoaded} readAt={datesReadAt} />;

  if (!indexHasLoaded && indexLoading) {
    return (
      <div className="finance-page-shell" aria-busy="true">
        <p role="status" className="fa-muted-text">正在加载报告索引…</p>
        {datesStatus}
        <LoadingSkeleton variant="page" />
      </div>
    );
  }

  if (!indexHasLoaded && indexError) {
    return (
      <div className="finance-page-shell">
        <ErrorState title="报告索引加载失败" message={readingErrorMessage(indexError, "报告索引加载失败，请稍后重试。")} onRetry={refetch} />
        {datesStatus}
      </div>
    );
  }

  return (
    <FAPageScaffold
      className="reports-page-shell"
      toolbar={(
        <>
        <FAWorkspaceHeader
          className="reports-workspace-header"
          icon={FileText}
          title="报告中心"
          tabs={reportTabs}
          value={activeReportTab}
          onChange={handleReportTabChange}
          ariaLabel="报告类型切换"
          actions={(
            <button type="button" onClick={handleReportsRefresh} className="fa-workspace-toolbar-button">
              <RefreshCw size={12} />
              刷新
            </button>
          )}
          primaryLabel="报告状态"
          primaryItems={[
            { label: "全部", value: allReports.length },
            { label: "筛后", value: filteredReports.length },
            { label: "可读", value: allReports.filter((item) => item.available).length },
            { label: "资产", value: reportAssetLabel(asset) },
          ]}
          secondaryLabel="时间"
          secondaryItems={[
            { label: reportDateSummaryLabel, value: reportDateSummaryValue },
            { label: "页数", value: totalPages },
          ]}
        />
        <div className="fa-chrome-band px-1.5">{datesStatus}</div>
        </>
      )}
    >
      <div className="fa-split-grid fa-split-grid--left reports-page-grid overflow-hidden">
        <details open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)} className="reports-filter-disclosure">
          <summary className="fa-label">筛选报告</summary>
          <ReportsRail
          reports={allReports}
          filters={filters}
          onFilterChange={setFilters}
          railLoading={indexLoading}
          railError={indexError}
          indexHasLoaded={indexHasLoaded}
          />
        </details>

        <main ref={panelRef} className="fa-scroll-column fa-chrome-band reports-main-panel p-1.5" onScroll={(event) => {
          if (preserveScrollDuringRefreshRef.current) return;
          rememberScrollPosition(event.currentTarget.scrollTop);
        }}>
          <ReportsReadStatus kind="index" loading={indexLoading} error={indexError} hasLoaded={indexHasLoaded} readAt={indexReadAt} />
          <ReportsToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
          />

          <div className="mb-1.5 border-b border-[var(--border-faint)] px-1 pb-1.5 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
            报告列表展示索引信息；请进入报告详情查看正式结果身份与当前有效的黄金研究基线。
          </div>

          <ReportsSummaryBar
            hasFilteredResults={filteredReports.length !== allReports.length}
            onResetFilters={resetFilters}
          />

          {filteredReports.length === 0 ? (
            <EmptyState
              title={allReports.length === 0 ? "暂无已登记报告" : "没有匹配的报告"}
              description={allReports.length === 0 ? "报告索引已加载，当前尚无可展示的报告。" : "请调整搜索内容或清除筛选条件。"}
            />
          ) : (
            <ReportsLibraryContent
              viewMode={viewMode}
              filteredReports={pagedReports}
              searchQuery={searchQuery}
              onSelectReport={handleCardSelect}
            />
          )}

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
