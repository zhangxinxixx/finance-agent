import type { ReportIndexItem, ReportType } from "@/types/reports";
import { formatDateTime } from "@/lib/date";

export const SUPPORTED_REPORT_TYPES = [
  "gold_policy_daily",
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
  "observation_report",
  "observation_strategy_card",
] as const satisfies readonly ReportType[];

export type SupportedReportType = (typeof SUPPORTED_REPORT_TYPES)[number];

const SUPPORTED_REPORT_TYPE_SET = new Set<string>(SUPPORTED_REPORT_TYPES);

export const CATEGORY_MAP: Record<string, { label: string; color: string; softColor?: string; borderColor?: string }> = {
  gold_policy_daily: { label: "黄金日结报告", color: "var(--important)" },
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
  observation_report: { label: "研究观察", color: "var(--warn)", softColor: "var(--warn-soft)", borderColor: "var(--warn-border)" },
  observation_strategy_card: { label: "观察策略卡", color: "var(--important)", softColor: "var(--important-soft)", borderColor: "var(--important-border)" },
};

export const DOT_COLORS: Record<string, string> = {
  gold_policy_daily: "var(--important)",
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
  observation_report: "var(--warn)",
  observation_strategy_card: "var(--important)",
};

export const TYPE_DESCRIPTIONS: Record<string, { summary: string; tags: string[] }> = {
  gold_policy_daily: { summary: "黄金日结报告汇总 Gold Policy 研究结果；发布记录、数据限制和当前有效性按各版本独立展示。", tags: ["黄金日结", "Gold Policy"] },
  final_report: { summary: "综合报告汇总宏观、期权、风险与事件证据链，输出当前研究判断和数据限制。", tags: ["综合", "证据链"] },
  macro_report: { summary: "宏观流动性报告聚焦流动性、实际利率、美元和黄金阶段判断。", tags: ["宏观", "流动性"] },
  weekly_context_revision: { summary: "周报修订以周报为不可变锚点，按最新价格、利率、期权、持仓和新闻证据逐项微调结论。", tags: ["周报", "上下文修订"] },
  options_report: { summary: "CME 期权结构分析 Markdown 报告，聚焦墙位、Gamma 零点与主导情景。", tags: ["策略卡", "期权"] },
  jin10_daily_report: { summary: "日报三视图报告包，承接原文、视觉版与智能体二次分析。", tags: ["看板", "日报"] },
  jin10_weekly_report: { summary: "周报报告包，聚焦周度主线、关键位框架与中短期路径推演。", tags: ["周报", "主线"] },
  jin10_positioning_report: { summary: "持仓报告结构化输入，只作为单源补充证据展示，不生成交易结论。", tags: ["持仓", "补充源"] },
  jin10_technical_levels_report: { summary: "点位报告输入，展示 VAH / VAL / POC、支撑阻力与失效条件。", tags: ["点位", "技术位"] },
  jin10_oil_report: { summary: "原油报告作为能源与通胀链条上下文，需结合 EIA 和行情验证。", tags: ["原油", "通胀"] },
  jin10_fx_report: { summary: "外汇报告作为 DXY、Fed 路径和外汇压力上下文，需结合行情验证。", tags: ["外汇", "美元"] },
  jin10_market_observation_report: { summary: "市场观察承接 VIP 每日市场观察和市场赔率表，只作为辅助决策证据。", tags: ["市场观察", "赔率"] },
  observation_report: { summary: "研究观察报告展示本轮快照和分析证据，需复核后才能进入正式发布链。", tags: ["研究观察", "待复核"] },
  observation_strategy_card: { summary: "观察策略卡承接本轮研究观察的策略加工结果，保持观察态，不代表正式策略。", tags: ["观察策略", "只读参考"] },
};

const XAUUSD_REPORT_TYPES = new Set<string>([
  "gold_policy_daily",
  "final_report",
  "macro_report",
  "weekly_context_revision",
  "jin10_daily_report",
  "jin10_weekly_report",
  "jin10_positioning_report",
  "jin10_technical_levels_report",
  "jin10_fx_report",
  "jin10_market_observation_report",
  "observation_report",
  "observation_strategy_card",
]);

const OIL_REPORT_TYPES = new Set<string>(["jin10_oil_report"]);
const FX_REPORT_TYPES = new Set<string>(["jin10_fx_report"]);

export function isSupportedReportType(value: string): value is SupportedReportType {
  return SUPPORTED_REPORT_TYPE_SET.has(value);
}

export function reportTypeLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  return CATEGORY_MAP[normalized]?.label ?? (normalized ? "其他报告" : "未提供报告类型");
}

export function reportAssetLabel(value: string | null | undefined): string {
  if (value === "OG") return "黄金期权（OG）";
  if (value === "OIL") return "原油（OIL）";
  if (value === "FX") return "美元 / 外汇（FX）";
  if (value === "XAUUSD") return "黄金现货（XAUUSD）";
  return value ? `未解释资产（${value}）` : "未提供资产";
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

export type ReportListStatusKey = "published" | "review" | "draft" | "archived" | "unknown";

export interface ReportListStatusMeta {
  key: ReportListStatusKey;
  label: string;
  color: string;
  softColor?: string;
  borderColor?: string;
  description: string;
  referenceOnly: boolean;
}

export function isObservationReport(item: Partial<ReportIndexItem>): boolean {
  return (
    item.type === "observation_report" ||
    item.type === "observation_strategy_card" ||
    item.family === "observation_report_markdown" ||
    item.family === "observation_strategy_card" ||
    item.authority === "observation_only" || item.output_mode === "observe" ||
    item.report_identity?.authority === "observation_only" || item.report_identity?.output_mode === "observe" ||
    item.publication_status === "observe" || item.report_identity?.publication_status === "observe"
  );
}

/** Presentation of backend facts only; this grants no publication or trading permission. */
export function getReportListStatus(item: Partial<ReportIndexItem>): ReportListStatusMeta {
  const identity = item.report_identity;
  const text = (value: unknown) => typeof value === "string" && value.trim() ? value.trim().toLowerCase() : null;
  const bool = (value: unknown) => typeof value === "boolean" ? value : null;
  const topPermission = bool(item.publish_allowed), identityPermission = bool(identity?.publish_allowed);
  const permission = topPermission ?? identityPermission;
  const authority = text(identity?.authority) ?? text(item.authority);
  const mode = text(identity?.output_mode) ?? text(item.output_mode);
  const review = text(identity?.review_status) ?? text(item.review_status);
  const lifecycle = text(item.lifecycle_status);
  const publicationStatus = text(identity?.publication_status) ?? text(item.publication_status);
  const observation = isObservationReport(item) || authority === "observation_only" || mode === "observe";
  const research = item.research_identity;
  const validity = research?.key_level_validity?.status;
  const historical = authority === "historical_only" || mode === "historical" || lifecycle === "archived" || validity === "historical";
  const published = lifecycle === "published";
  const notPublished = lifecycle === "draft" || lifecycle === "generated" || lifecycle === "snapshot_bound";
  const conflicts = [
    item.qualification_conflict === true,
    topPermission !== null && identityPermission !== null && topPermission !== identityPermission,
    ...(["authority", "output_mode", "review_status", "publication_status"] as const).map(key =>
      text(item[key]) !== null && text(identity?.[key]) !== null && text(item[key]) !== text(identity?.[key])),
    observation && (published || permission === true),
    ...(["report_id", "run_id", "snapshot_id", "trade_date"] as const).map(key =>
      Boolean(item[key] && research?.[key] && item[key] !== research[key])),
  ];
  const conflict = conflicts.some(Boolean);
  const unknownEnum = [
    lifecycle !== null && !["draft", "generated", "snapshot_bound", "needs_review", "published", "exported", "archived"].includes(lifecycle),
    review !== null && !["not_required", "pending", "approved", "rejected", "rerun", "blocked", "needs_review"].includes(review),
    authority !== null && !["observation_only", "historical_only"].includes(authority),
    mode !== null && !["observe", "historical", "accepted"].includes(mode),
    publicationStatus !== null && !["accepted", "observe", "degraded"].includes(publicationStatus),
  ].some(Boolean);
  const restrictedData = ["partial", "unavailable", "degraded"].includes(text(item.data_status ?? item.status) ?? "");
  const needsReview = restrictedData || publicationStatus === "degraded" || lifecycle === "needs_review"
    || ["blocked", "needs_review", "pending", "rejected", "rerun"].includes(review ?? "");
  const permissionLabel = conflict ? "许可待核验（资格字段冲突）" : permission === true ? "获准发布" : permission === false ? "不可发布" : "许可未知";
  const publicationLabel = observation && published ? "发布状态冲突，待核验" : published ? "已发布" : notPublished && !historical ? "尚未发布" : "发布记录未知";
  const validityLabel = conflict ? "当前有效性待核验" : historical ? "仅供历史参考" : observation ? "观察稿，不代表当前信号"
    : validity === "active" ? "当前价位有效，不代表交易触发" : validity === "expired" ? "当前价位已失效" : "当前有效性未知";
  const description = [item.available === true ? "可读" : "内容未确认可读", permissionLabel, publicationLabel, validityLabel,
    unknownEnum ? "存在未解释资格状态" : null, restrictedData ? "报告数据需复核" : null].filter((value): value is string => value !== null).join(" · ");
  const referenceOnly = item.available !== true || conflict || unknownEnum || observation || historical || needsReview || permission !== true || !published || validity !== "active";
  const status = (key: ReportListStatusKey, label: string, color = "var(--warn)"): ReportListStatusMeta => ({
    key, label, color, description, referenceOnly,
  });
  if (conflict) return status("unknown", "资格冲突 · 待核验");
  if (historical) return status("archived", published ? "历史已发布" : "历史参考");
  if (observation) return status("review", permission === false ? "待复核 · 不可发布" : "研究观察 · 许可待核验");
  if (unknownEnum) return status("unknown", "资格未知");
  if (permission === false || needsReview) return status("review", published ? "已发布 · 当前需复核" : permission === false ? "不可发布" : "待复核");
  if (published) return status("published", "已发布", "var(--up)");
  if (lifecycle === "draft") return status("draft", "草稿");
  return status("unknown", permission === true ? "获准发布 · 尚无发布记录" : "资格未知", "var(--fg-4)");
}

export function getReportDetailId(item: ReportIndexItem): string | null {
  if (item.report_id) return item.report_id;
  if (item.run_id) return item.run_id;
  return null;
}

export function getReportItemKey(item: ReportIndexItem, index: number): string {
  if (item.type === "gold_policy_daily") {
    if (item.report_id) return JSON.stringify([item.type, "report", item.report_id]);
    if (item.run_id) return JSON.stringify([item.type, "run", item.trade_date, item.run_id]);
    // Without an identity, two rows cannot be confirmed as the same report.
    return JSON.stringify([item.type, "unidentified", index]);
  }
  return `${item.type}-${item.trade_date}-${item.run_id ?? index}`;
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
  if (item.type === "gold_policy_daily") return `黄金现货（XAUUSD）黄金日结报告 · ${dateLabel}`;
  if (item.type === "final_report") return `黄金现货（XAUUSD）综合报告 · ${dateLabel}`;
  if (item.type === "macro_report") return `黄金现货（XAUUSD）宏观流动性报告 · ${dateLabel}`;
  if (item.type === "weekly_context_revision") return `黄金现货（XAUUSD）周报最新上下文修正 · ${dateLabel}`;
  if (item.type === "options_report") return `黄金期权结构报告 · ${dateLabel}`;
  if (item.type === "jin10_weekly_report") return `黄金周报 · ${dateLabel}`;
  if (item.type === "jin10_daily_report") return `黄金日报 · ${dateLabel}`;
  if (item.type === "jin10_positioning_report") return `持仓报告 · ${dateLabel}`;
  if (item.type === "jin10_technical_levels_report") return `点位报告 · ${dateLabel}`;
  if (item.type === "jin10_oil_report") return `原油报告 · ${dateLabel}`;
  if (item.type === "jin10_fx_report") return `外汇报告 · ${dateLabel}`;
  if (item.type === "jin10_market_observation_report") return `市场观察 · ${dateLabel}`;
  if (item.type === "observation_report") return `研究观察报告 · ${dateLabel}`;
  if (item.type === "observation_strategy_card") return `观察策略卡 · ${dateLabel}`;
  return `${reportTypeLabel(item.type)} · ${dateLabel}`;
}

/**
 * Build the human-readable search surface used by both the report rail and
 * the main list.  Search must follow what a reader sees (for example
 * "黄金"), while retaining the raw type as a compatibility term for links
 * and existing bookmarks.
 */
export function reportSearchText(item: ReportIndexItem): string {
  return [
    reportTypeLabel(item.type),
    reportAssetLabel(inferAssetLabel(item)),
    getReportTitle(item),
    item.title ?? "",
    item.source_title ?? "",
    item.trade_date,
    item.type,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function matchesReportSearch(item: ReportIndexItem, searchQuery: string): boolean {
  const q = searchQuery.trim().toLowerCase();
  return !q || reportSearchText(item).includes(q);
}
