import { ReportCard, ListView, TimelineView } from "@/components/reports/ReportLibraryViews";
import type { ViewMode } from "@/components/reports/ReportsToolbar";
import type { ReportIndexItem } from "@/types/reports";

interface ReportsSummaryBarProps {
  reportSummaryText: string;
  hasFilteredResults: boolean;
  onResetFilters: () => void;
}

export function ReportsSummaryBar({
  reportSummaryText,
  hasFilteredResults,
  onResetFilters,
}: ReportsSummaryBarProps) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 12,
        flexShrink: 0,
      }}
    >
      <div style={{ fontSize: 11, color: "var(--fg-4)" }}>{reportSummaryText}</div>
      {hasFilteredResults ? (
        <button
          type="button"
          onClick={onResetFilters}
          style={{
            fontSize: 10,
            color: "var(--brand-hover)",
            background: "transparent",
            border: "none",
            cursor: "pointer",
          }}
        >
          清除筛选
        </button>
      ) : null}
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
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
        gap: 8,
      }}
    >
      {filteredReports.map((item, idx) => (
        <ReportCard
          key={`${item.type}-${item.trade_date}-${item.run_id ?? idx}`}
          item={item}
          onSelect={() => onSelectReport(item)}
          searchQuery={searchQuery}
        />
      ))}
      {filteredReports.length === 0 ? (
        <div
          style={{
            gridColumn: "1 / -1",
            padding: "40px 20px",
            textAlign: "center",
            color: "var(--fg-5)",
            fontSize: 12,
          }}
        >
          暂无匹配的报告
        </div>
      ) : null}
    </div>
  );
}
