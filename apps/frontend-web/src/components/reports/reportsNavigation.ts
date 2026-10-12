import type { ReportFilters } from "./reportsRailOptions";

export type ReportsViewMode = "list" | "grid" | "timeline";

export function readReportsQuery(params: URLSearchParams) {
  const view = params.get("view");
  const rawPage = Number(params.get("page") ?? 1);
  return {
    searchQuery: params.get("q") ?? "",
    viewMode: (view === "grid" || view === "timeline" ? view : "list") as ReportsViewMode,
    currentPage: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    filters: {
      reportTypes: (params.get("types") ?? "").split(",").filter(Boolean),
      asset: params.get("asset"),
      status: params.get("status"),
      dataSource: params.get("source"),
      dateRange: params.get("range"),
    } satisfies ReportFilters,
  };
}

export function reportsReturnTarget(state: unknown): string {
  const target = state && typeof state === "object" && "reportsReturnTo" in state
    ? state.reportsReturnTo : null;
  // Only the report list can be a return target. Reject external URLs and detail loops.
  return typeof target === "string" && /^\/reports(?:\?[^#]*)?$/.test(target)
    ? target : "/reports";
}
