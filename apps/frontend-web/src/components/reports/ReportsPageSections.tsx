import { ReportCard, ListView, TimelineView } from "@/components/reports/ReportLibraryViews";
import type { ViewMode } from "@/components/reports/ReportsToolbar";
import type { ReportIndexItem } from "@/types/reports";

interface ReportsSummaryBarProps {
  hasFilteredResults: boolean;
  onResetFilters: () => void;
}

export function ReportsSummaryBar({
  hasFilteredResults,
  onResetFilters,
}: ReportsSummaryBarProps) {
  return (
    <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-faint)] pb-2">
      <div />
      <div className="flex items-center gap-2">
        {hasFilteredResults ? (
          <button
            type="button"
            onClick={onResetFilters}
            className="text-[10px] font-semibold text-[var(--brand-hover)] transition-colors hover:text-[var(--brand)]"
          >
            清除筛选
          </button>
        ) : null}
      </div>
    </div>
  );
}

interface ReportsPaginationProps {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export function ReportsPagination({
  currentPage,
  totalPages,
  totalItems,
  pageSize,
  onPageChange,
}: ReportsPaginationProps) {
  if (totalPages <= 1) return null;

  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(totalItems, currentPage * pageSize);
  const pages = Array.from({ length: totalPages }, (_, index) => index + 1).filter((page) => {
    return page === 1 || page === totalPages || Math.abs(page - currentPage) <= 1;
  });

  const visiblePages: Array<number | "ellipsis"> = [];
  pages.forEach((page, index) => {
    visiblePages.push(page);
    const next = pages[index + 1];
    if (next && next - page > 1) {
      visiblePages.push("ellipsis");
    }
  });

  return (
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-3 py-2">
      <div className="text-[10px] text-[var(--fg-4)]">
        显示 <span className="fa-num text-[var(--fg-2)]">{start}-{end}</span> / <span className="fa-num text-[var(--fg-2)]">{totalItems}</span>
      </div>
      <div className="flex items-center gap-1 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-1">
        <button
          type="button"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          className="inline-flex h-7 min-w-7 items-center justify-center rounded-[var(--radius-sm)] px-2 text-[10px] text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-panel)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          上一页
        </button>
        {visiblePages.map((page, index) => (
          page === "ellipsis" ? (
            <span key={`ellipsis-${index}`} className="px-1 text-[10px] text-[var(--fg-5)]">…</span>
          ) : (
            <button
              key={page}
              type="button"
              onClick={() => onPageChange(page)}
              className={`inline-flex h-7 min-w-7 items-center justify-center rounded-[var(--radius-sm)] px-2 text-[10px] ${
                currentPage === page
                  ? "bg-[var(--brand-soft)] text-[var(--brand-hover)]"
                  : "text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-panel)]"
              }`}
            >
              {page}
            </button>
          )
        ))}
        <button
          type="button"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          className="inline-flex h-7 min-w-7 items-center justify-center rounded-[var(--radius-sm)] px-2 text-[10px] text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-panel)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

interface ReportsLibraryContentProps {
  viewMode: ViewMode;
  filteredReports: ReportIndexItem[];
  searchQuery: string;
  onSelectReport: (item: ReportIndexItem) => void;
}

export function ReportsLibraryContent({
  viewMode,
  filteredReports,
  searchQuery,
  onSelectReport,
}: ReportsLibraryContentProps) {
  if (viewMode === "list") {
    return (
      <ListView
        items={filteredReports}
        onSelect={onSelectReport}
        searchQuery={searchQuery}
      />
    );
  }

  if (viewMode === "timeline") {
    return (
      <TimelineView
        items={filteredReports}
        onSelect={onSelectReport}
        searchQuery={searchQuery}
      />
    );
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-2">
      {filteredReports.map((item, idx) => (
        <ReportCard
          key={`${item.type}-${item.trade_date}-${item.run_id ?? idx}`}
          item={item}
          onSelect={() => onSelectReport(item)}
          searchQuery={searchQuery}
        />
      ))}
      {filteredReports.length === 0 ? (
        <div className="col-[1/-1] rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] bg-[var(--bg-card)] px-5 py-10 text-center text-[12px] text-[var(--fg-5)]">
          暂无匹配的报告
        </div>
      ) : null}
    </div>
  );
}
