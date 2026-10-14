import { getReportItemKey, getReportListStatus, isSupportedReportType, reportMatchesAsset, reportSearchText } from "@/components/reports/reportListMeta";
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
  for (const [index, item] of indexItems.entries()) {
    if (!isSupportedReportType(item.type)) continue;
    const key =
      item.type === "gold_policy_daily"
        ? getReportItemKey(item, index)
        : item.type === "jin10_market_observation_report" || item.type === "final_report"
        ? `${item.type}|${item.trade_date}|${item.run_id ?? item.report_id ?? ""}`
        : `${item.type}|${item.trade_date}`;
    const existing = seen.get(key);
    if (!existing || compareReportFreshness(item, existing) > 0) {
      seen.set(key, item);
    }
  }
  return Array.from(seen.values()).sort((a, b) => {
    const left = typeof a.trade_date === "string" ? a.trade_date : "";
    const right = typeof b.trade_date === "string" ? b.trade_date : "";
    return right.localeCompare(left);
  });
}

/**
 * The report index can contain incomplete or malformed records. A header date
 * is useful only when the record supplies a real calendar day, not a timestamp
 * or a date string that JavaScript happens to coerce.
 */
export function isValidReportTradeDate(value: string | null | undefined): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (year < 1) return false;

  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/** Latest valid trade day across the already displayable report index. */
export function getLatestReportTradeDate(allReports: ReportIndexItem[]): string | null {
  let latestDate: string | null = null;
  for (const report of allReports) {
    if (isValidReportTradeDate(report.trade_date) && (!latestDate || report.trade_date > latestDate)) {
      latestDate = report.trade_date;
    }
  }
  return latestDate;
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
      const matchesSearch = reportSearchText(item).includes(searchNeedle);
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
      if (getReportListStatus(item).key !== filters.status) return false;
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
