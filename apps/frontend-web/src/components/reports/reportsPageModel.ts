import { CATEGORY_MAP, isSupportedReportType, reportMatchesAsset } from "@/components/reports/reportListMeta";
import type { ReportFilters } from "@/components/reports/reportsRailOptions";
import type { ReportDateItem, ReportIndexItem } from "@/types/reports";

function getDateRangeCutoff(dateRange: string | null): string | null {
  if (!dateRange || dateRange === "all") return null;
  const now = new Date();
  const days = dateRange === "1d" ? 1 : dateRange === "7d" ? 7 : 30;
  return new Date(now.getTime() - days * 86400000).toISOString().slice(0, 10);
}

export function dedupeSupportedReports(indexItems: ReportIndexItem[]): ReportIndexItem[] {
  const seen = new Map<string, ReportIndexItem>();
  for (const item of indexItems) {
    if (!isSupportedReportType(item.type)) continue;
    const key =
      item.type === "jin10_market_observation_report"
        ? `${item.type}|${item.trade_date}|${item.run_id ?? item.report_id ?? ""}`
        : `${item.type}|${item.trade_date}`;
    const existing = seen.get(key);
    if (!existing || compareReportFreshness(item, existing) > 0) {
      seen.set(key, item);
    }
  }
  return Array.from(seen.values()).sort((a, b) => b.trade_date.localeCompare(a.trade_date));
}

function compareReportFreshness(next: ReportIndexItem, current: ReportIndexItem): number {
  const nextGeneratedAt = Date.parse(next.generated_at ?? "");
  const currentGeneratedAt = Date.parse(current.generated_at ?? "");
  const hasNextGeneratedAt = Number.isFinite(nextGeneratedAt);
  const hasCurrentGeneratedAt = Number.isFinite(currentGeneratedAt);
  if (hasNextGeneratedAt || hasCurrentGeneratedAt) {
    return (hasNextGeneratedAt ? nextGeneratedAt : 0) - (hasCurrentGeneratedAt ? currentGeneratedAt : 0);
  }
  return (next.run_id ?? "").localeCompare(current.run_id ?? "");
}

export function filterReports(
  allReports: ReportIndexItem[],
  searchQuery: string,
  filters: ReportFilters,
): ReportIndexItem[] {
  const searchNeedle = searchQuery.trim().toLowerCase();
  const dateCutoff = getDateRangeCutoff(filters.dateRange);

  return allReports.filter((item) => {
    if (searchNeedle) {
      const categoryLabel = CATEGORY_MAP[item.type]?.label ?? item.type;
      const matchesSearch =
        categoryLabel.toLowerCase().includes(searchNeedle) ||
        (item.title ?? "").toLowerCase().includes(searchNeedle) ||
        item.trade_date.toLowerCase().includes(searchNeedle) ||
        item.type.toLowerCase().includes(searchNeedle);
      if (!matchesSearch) return false;
    }

    if (filters.reportTypes.length > 0 && !filters.reportTypes.includes(item.type)) {
      return false;
    }

    if (filters.asset && filters.asset !== "all") {
      if (!reportMatchesAsset(item, filters.asset)) {
        return false;
      }
    }

    if (filters.status) {
      if (filters.status === "published" && !item.available) return false;
      if (filters.status === "draft" && item.available) return false;
    }

    if (dateCutoff && item.trade_date < dateCutoff) {
      return false;
    }

    return true;
  });
}

export function listAvailableReportDates(dates: ReportDateItem[]): string[] {
  return dates
    .map((item) => item.trade_date)
    .filter(Boolean)
    .sort((a, b) => b.localeCompare(a));
}

export function buildReportSummaryText(filteredCount: number, totalCount: number): string {
  return filteredCount === totalCount ? `共 ${filteredCount} 篇报告` : `共 ${filteredCount} / ${totalCount} 篇报告`;
}
