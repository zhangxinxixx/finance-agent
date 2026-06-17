import type { ReportIndexItem, ReportType } from "@/types/reports";

export const SUPPORTED_REPORT_TYPES = [
  "options_report",
  "jin10_daily_report",
  "jin10_weekly_report",
] as const satisfies readonly ReportType[];

export type SupportedReportType = (typeof SUPPORTED_REPORT_TYPES)[number];

const SUPPORTED_REPORT_TYPE_SET = new Set<string>(SUPPORTED_REPORT_TYPES);

export const CATEGORY_MAP: Record<string, { label: string; color: string }> = {
  options_report: { label: "期权分析", color: "#a78bfa" },
  jin10_daily_report: { label: "Jin10日报", color: "#f59e0b" },
  jin10_weekly_report: { label: "Jin10周报", color: "#14b8a6" },
};

export const DOT_COLORS: Record<string, string> = {
  options_report: "#a78bfa",
  jin10_daily_report: "#f59e0b",
  jin10_weekly_report: "#14b8a6",
};

export const TYPE_DESCRIPTIONS: Record<string, { summary: string; tags: string[] }> = {
  options_report: { summary: "CME 期权结构分析 Markdown 报告，聚焦墙位、Gamma 零点与主导情景。", tags: ["策略卡", "期权"] },
  jin10_daily_report: { summary: "Jin10 日报三视图报告包，承接原文、视觉版与 Agent 二次分析。", tags: ["Dashboard", "Jin10"] },
  jin10_weekly_report: { summary: "Jin10 周报报告包，聚焦周度主线、关键位框架与中短期路径推演。", tags: ["周报", "Jin10"] },
};

export function isSupportedReportType(value: string): value is SupportedReportType {
  return SUPPORTED_REPORT_TYPE_SET.has(value);
}

export function shortRunId(value: string | null | undefined): string {
  if (!value) return "-";
  return value.length <= 12 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}

export function canOpenReport(item: ReportIndexItem): boolean {
  return item.type === "options_report" || Boolean(item.run_id);
}

export function getReportDetailId(item: ReportIndexItem): string | null {
  if (item.report_id) return item.report_id;
  if (item.run_id) return item.run_id;
  return null;
}

export function inferAssetLabel(item: ReportIndexItem): string {
  if (item.type === "options_report") return "OG";
  return "XAUUSD";
}

export function matchesReportSearch(item: ReportIndexItem, searchQuery: string): boolean {
  if (!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  const cat = CATEGORY_MAP[item.type]?.label ?? item.type;
  return (
    cat.toLowerCase().includes(q) ||
    item.trade_date.toLowerCase().includes(q) ||
    item.type.toLowerCase().includes(q)
  );
}
