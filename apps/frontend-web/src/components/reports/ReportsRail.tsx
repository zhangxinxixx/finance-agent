import type { ReportIndexItem } from "@/types/reports";
import type { ReportFilters } from "./reportsRailOptions";
import { REPORTS_RAIL_PANEL_STYLE } from "./reportsRailOptions";
import {
  ReportsRailAssetSection,
  ReportsRailDataSourceSection,
  ReportsRailDateRangeSection,
  ReportsRailErrorState,
  ReportsRailFooter,
  ReportsRailHeader,
  ReportsRailLoadingState,
  ReportsRailReportTypeSection,
  ReportsRailStatusSection,
} from "./ReportsRailSections";

interface ReportsRailProps {
  reports: ReportIndexItem[];
  filters: ReportFilters;
  onFilterChange: (filters: ReportFilters) => void;
  railLoading: boolean;
  railError: Error | null;
}

export function ReportsRail({ reports, filters, onFilterChange, railLoading, railError }: ReportsRailProps) {
  const totalCount = reports.length;

  function countByType(matchType: string): number {
    return reports.filter((item) => item.type === matchType).length;
  }

  function toggleReportType(type: string) {
    const current = filters.reportTypes;
    const next = current.includes(type) ? current.filter((t) => t !== type) : [...current, type];
    onFilterChange({ ...filters, reportTypes: next });
  }

  function handleReset() {
    onFilterChange({ reportTypes: [], asset: null, status: null, dataSource: null, dateRange: null });
  }

  const hasActiveFilters =
    filters.reportTypes.length > 0 ||
    filters.asset !== null ||
    filters.status !== null ||
    filters.dataSource !== null ||
    filters.dateRange !== null;

  const filteredCount = reports.filter((item) => {
    if (filters.reportTypes.length > 0 && !filters.reportTypes.includes(item.type)) return false;
    if (filters.asset && filters.asset !== "all") {
      if (filters.asset === "XAUUSD" && !["jin10_daily_report", "jin10_weekly_report"].includes(item.type)) return false;
      if (filters.asset === "OG" && item.type !== "options_report") return false;
    }
    if (filters.status) {
      if (filters.status === "published" && !item.available) return false;
      if (filters.status === "draft" && item.available) return false;
    }
    if (filters.dateRange && filters.dateRange !== "all") {
      const now = new Date();
      const days = filters.dateRange === "1d" ? 1 : filters.dateRange === "7d" ? 7 : 30;
      const cutoff = new Date(now.getTime() - days * 86400000).toISOString().slice(0, 10);
      if (item.trade_date < cutoff) return false;
    }
    return true;
  }).length;

  if (railLoading) {
    return <ReportsRailLoadingState />;
  }

  if (railError) {
    return <ReportsRailErrorState message={railError.message} />;
  }

  return (
    <aside className="reports-rail" style={REPORTS_RAIL_PANEL_STYLE}>
      <ReportsRailHeader hasActiveFilters={hasActiveFilters} onReset={handleReset} />
      <ReportsRailReportTypeSection filters={filters} onToggle={toggleReportType} countByType={countByType} />
      <ReportsRailAssetSection filters={filters} onFilterChange={onFilterChange} />
      <ReportsRailStatusSection filters={filters} onFilterChange={onFilterChange} />
      <ReportsRailDataSourceSection filters={filters} onFilterChange={onFilterChange} />
      <ReportsRailDateRangeSection filters={filters} onFilterChange={onFilterChange} />
      <ReportsRailFooter filteredCount={filteredCount} totalCount={totalCount} />
    </aside>
  );
}

export type { ReportFilters } from "./reportsRailOptions";

export default ReportsRail;
