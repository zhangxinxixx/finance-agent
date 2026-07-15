import type { ReportIndexItem, ReportType } from "@/types/reports";
import { formatDateTime } from "@/lib/date";

export const SUPPORTED_REPORT_TYPES = [
  "final_report",
  "macro_report",
  "weekly_context_revision",
  "options_report",
  "jin10_daily_report",
  "jin10_weekly_report",
  "jin10_positioning_report",
  "jin10_technical_levels_report",
  "jin10_oil_report",
  "jin10_fx_report",
  "jin10_market_observation_report",
] as const satisfies readonly ReportType[];

export type SupportedReportType = (typeof SUPPORTED_REPORT_TYPES)[number];

const SUPPORTED_REPORT_TYPE_SET = new Set<string>(SUPPORTED_REPORT_TYPES);

export const CATEGORY_MAP: Record<string, { label: string; color: string }> = {
  final_report: { label: "综合报告", color: "#60a5fa" },
  macro_report: { label: "宏观流动性报告", color: "#38bdf8" },
  weekly_context_revision: { label: "周报修订", color: "var(--important)" },
  options_report: { label: "期权分析", color: "#a78bfa" },
  jin10_daily_report: { label: "日报", color: "#f59e0b" },
  jin10_weekly_report: { label: "周报", color: "#14b8a6" },
  jin10_positioning_report: { label: "持仓报告", color: "#22c55e" },
  jin10_technical_levels_report: { label: "点位报告", color: "#60a5fa" },
  jin10_oil_report: { label: "原油报告", color: "#f97316" },
  jin10_fx_report: { label: "外汇报告", color: "#8b5cf6" },
  jin10_market_observation_report: { label: "市场观察", color: "#06b6d4" },
};

export const DOT_COLORS: Record<string, string> = {
  final_report: "#60a5fa",
  macro_report: "#38bdf8",
  weekly_context_revision: "var(--important)",
  options_report: "#a78bfa",
  jin10_daily_report: "#f59e0b",
  jin10_weekly_report: "#14b8a6",
  jin10_positioning_report: "#22c55e",
  jin10_technical_levels_report: "#60a5fa",
  jin10_oil_report: "#f97316",
  jin10_fx_report: "#8b5cf6",
  jin10_market_observation_report: "#06b6d4",
};

export const TYPE_DESCRIPTIONS: Record<string, { summary: string; tags: string[] }> = {
  final_report: { summary: "综合报告汇总宏观、期权、风险与事件证据链，输出当前研究判断和数据限制。", tags: ["综合", "证据链"] },
  macro_report: { summary: "宏观流动性报告聚焦流动性、实际利率、美元和黄金阶段判断。", tags: ["宏观", "流动性"] },
  weekly_context_revision: { summary: "周报修订以周报为不可变锚点，按最新价格、利率、期权、持仓和新闻证据逐项微调结论。", tags: ["周报", "上下文修订"] },
  options_report: { summary: "CME 期权结构分析 Markdown 报告，聚焦墙位、Gamma 零点与主导情景。", tags: ["策略卡", "期权"] },
  jin10_daily_report: { summary: "日报三视图报告包，承接原文、视觉版与 Agent 二次分析。", tags: ["看板", "日报"] },
  jin10_weekly_report: { summary: "周报报告包，聚焦周度主线、关键位框架与中短期路径推演。", tags: ["周报", "主线"] },
  jin10_positioning_report: { summary: "持仓报告结构化输入，只作为单源补充证据展示，不生成交易结论。", tags: ["持仓", "补充源"] },
  jin10_technical_levels_report: { summary: "点位报告输入，展示 VAH / VAL / POC、支撑阻力与失效条件。", tags: ["点位", "技术位"] },
  jin10_oil_report: { summary: "原油报告作为能源与通胀链条上下文，需结合 EIA 和行情验证。", tags: ["原油", "通胀"] },
  jin10_fx_report: { summary: "外汇报告作为 DXY、Fed 路径和外汇压力上下文，需结合行情验证。", tags: ["外汇", "美元"] },
  jin10_market_observation_report: { summary: "市场观察承接 VIP 每日市场观察和市场赔率表，只作为辅助决策证据。", tags: ["市场观察", "赔率"] },
};

const XAUUSD_REPORT_TYPES = new Set<string>([
  "final_report",
  "macro_report",
  "weekly_context_revision",
  "jin10_daily_report",
  "jin10_weekly_report",
  "jin10_positioning_report",
  "jin10_technical_levels_report",
  "jin10_fx_report",
  "jin10_market_observation_report",
]);

const OIL_REPORT_TYPES = new Set<string>(["jin10_oil_report"]);
const FX_REPORT_TYPES = new Set<string>(["jin10_fx_report"]);

export function isSupportedReportType(value: string): value is SupportedReportType {
  return SUPPORTED_REPORT_TYPE_SET.has(value);
}

export function shortRunId(value: string | null | undefined): string {
  if (!value) return "-";
  return value.length <= 12 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}

export function formatGeneratedAt(value: string | null | undefined): string {
  if (!value) return "—";
  return formatDateTime(value);
}

export function canOpenReport(item: ReportIndexItem): boolean {
  return item.available && (item.type === "options_report" || Boolean(getReportDetailId(item)));
}

export function getReportDetailId(item: ReportIndexItem): string | null {
  if (item.report_id) return item.report_id;
  if (item.run_id) return item.run_id;
  return null;
}

export function inferAssetLabel(item: ReportIndexItem): string {
  if (item.type === "options_report") return "OG";
  if (item.type === "jin10_oil_report") return "OIL";
  if (item.type === "jin10_fx_report") return "FX";
  if (item.type === "jin10_market_observation_report") return "市场观察";
  return "XAUUSD";
}

export function reportMatchesAsset(item: ReportIndexItem, asset: string | null): boolean {
  if (!asset || asset === "all") return true;
  if (asset === "XAUUSD") return XAUUSD_REPORT_TYPES.has(item.type);
  if (asset === "OG") return item.type === "options_report";
  if (asset === "OIL") return OIL_REPORT_TYPES.has(item.type);
  if (asset === "FX") return FX_REPORT_TYPES.has(item.type);
  return true;
}

export type MarketObservationSubtype = "observation" | "odds";

export function detectMarketObservationSubtype(...values: Array<string | null | undefined>): MarketObservationSubtype | null {
  const text = values.filter(Boolean).join(" ");
  if (/市场赔率数据表|市场赔率表|赔率表|market odds/i.test(text)) return "odds";
  if (/VIP每日市场观察|每日市场观察|市场观察|market observation/i.test(text)) return "observation";
  return null;
}

export function marketObservationSubtypeLabel(value: MarketObservationSubtype): string {
  if (value === "odds") return "市场赔率";
  return "市场观察";
}

export function getMarketObservationSubtype(item: ReportIndexItem): MarketObservationSubtype | null {
  if (item.type !== "jin10_market_observation_report") return null;
  return detectMarketObservationSubtype(item.source_title, item.title) ?? "observation";
}

export function getReportTitle(item: ReportIndexItem): string {
  if (item.title) return item.title;
  const dateLabel = item.trade_date || "-";
  if (item.type === "final_report") return `XAUUSD 综合报告 · ${dateLabel}`;
  if (item.type === "macro_report") return `XAUUSD 宏观流动性报告 · ${dateLabel}`;
  if (item.type === "weekly_context_revision") return `XAUUSD 周报最新上下文修正 · ${dateLabel}`;
  if (item.type === "options_report") return `黄金期权结构报告 · ${dateLabel}`;
  if (item.type === "jin10_weekly_report") return `黄金周报 · ${dateLabel}`;
  if (item.type === "jin10_daily_report") return `黄金日报 · ${dateLabel}`;
  if (item.type === "jin10_positioning_report") return `持仓报告 · ${dateLabel}`;
  if (item.type === "jin10_technical_levels_report") return `点位报告 · ${dateLabel}`;
  if (item.type === "jin10_oil_report") return `原油报告 · ${dateLabel}`;
  if (item.type === "jin10_fx_report") return `外汇报告 · ${dateLabel}`;
  if (item.type === "jin10_market_observation_report") return `市场观察 · ${dateLabel}`;
  return `${CATEGORY_MAP[item.type]?.label ?? item.type} · ${dateLabel}`;
}

export function matchesReportSearch(item: ReportIndexItem, searchQuery: string): boolean {
  if (!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  const cat = CATEGORY_MAP[item.type]?.label ?? item.type;
  return (
    cat.toLowerCase().includes(q) ||
    (item.title ?? "").toLowerCase().includes(q) ||
    (item.source_title ?? "").toLowerCase().includes(q) ||
    item.trade_date.toLowerCase().includes(q) ||
    item.type.toLowerCase().includes(q)
  );
}
