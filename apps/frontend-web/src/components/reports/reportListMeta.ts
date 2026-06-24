import type { ReportIndexItem, ReportType } from "@/types/reports";

export const SUPPORTED_REPORT_TYPES = [
  "final_report",
  "macro_report",
  "options_report",
  "jin10_daily_report",
  "jin10_weekly_report",
] as const satisfies readonly ReportType[];

export type SupportedReportType = (typeof SUPPORTED_REPORT_TYPES)[number];

const SUPPORTED_REPORT_TYPE_SET = new Set<string>(SUPPORTED_REPORT_TYPES);

export const CATEGORY_MAP: Record<string, { label: string; color: string }> = {
  final_report: { label: "综合报告", color: "#60a5fa" },
  macro_report: { label: "宏观数据报告", color: "#38bdf8" },
  options_report: { label: "期权分析", color: "#a78bfa" },
  jin10_daily_report: { label: "金十日报", color: "#f59e0b" },
  jin10_weekly_report: { label: "金十周报", color: "#14b8a6" },
};

export const DOT_COLORS: Record<string, string> = {
  final_report: "#60a5fa",
  macro_report: "#38bdf8",
  options_report: "#a78bfa",
  jin10_daily_report: "#f59e0b",
  jin10_weekly_report: "#14b8a6",
};

export const TYPE_DESCRIPTIONS: Record<string, { summary: string; tags: string[] }> = {
  final_report: { summary: "综合报告汇总宏观、期权、风险与事件证据链，输出当前研究判断和数据限制。", tags: ["综合", "证据链"] },
  macro_report: { summary: "宏观数据报告聚焦利率、美元、流动性和黄金机会成本，只呈现数据状态与限制。", tags: ["宏观", "数据"] },
  options_report: { summary: "CME 期权结构分析 Markdown 报告，聚焦墙位、Gamma 零点与主导情景。", tags: ["策略卡", "期权"] },
  jin10_daily_report: { summary: "金十日报三视图报告包，承接原文、视觉版与 Agent 二次分析。", tags: ["看板", "金十"] },
  jin10_weekly_report: { summary: "金十周报报告包，聚焦周度主线、关键位框架与中短期路径推演。", tags: ["周报", "金十"] },
};

export function isSupportedReportType(value: string): value is SupportedReportType {
  return SUPPORTED_REPORT_TYPE_SET.has(value);
}

export function shortRunId(value: string | null | undefined): string {
  if (!value) return "-";
  return value.length <= 12 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}

export function canOpenReport(item: ReportIndexItem): boolean {
  return item.type === "options_report" || Boolean(getReportDetailId(item));
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

export function getReportTitle(item: ReportIndexItem): string {
  if (item.title) return item.title;
  const dateLabel = item.trade_date || "-";
  if (item.type === "final_report") return `XAUUSD 综合报告 · ${dateLabel}`;
  if (item.type === "macro_report") return `XAUUSD 宏观数据报告 · ${dateLabel}`;
  if (item.type === "options_report") return `黄金期权结构报告 · ${dateLabel}`;
  if (item.type === "jin10_weekly_report") return `Jin10 黄金周报 · ${dateLabel}`;
  if (item.type === "jin10_daily_report") return `Jin10 黄金日报 · ${dateLabel}`;
  return `${CATEGORY_MAP[item.type]?.label ?? item.type} · ${dateLabel}`;
}

export function matchesReportSearch(item: ReportIndexItem, searchQuery: string): boolean {
  if (!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  const cat = CATEGORY_MAP[item.type]?.label ?? item.type;
  return (
    cat.toLowerCase().includes(q) ||
    (item.title ?? "").toLowerCase().includes(q) ||
    item.trade_date.toLowerCase().includes(q) ||
    item.type.toLowerCase().includes(q)
  );
}
