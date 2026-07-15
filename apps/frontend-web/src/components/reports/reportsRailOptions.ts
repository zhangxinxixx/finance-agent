export interface ReportFilters {
  reportTypes: string[];
  asset: string | null;
  status: string | null;
  dataSource: string | null;
  dateRange: string | null;
}

export interface CategoryConfig {
  key: string;
  label: string;
  color: string;
  matchType: string;
}

export const CATEGORY_CONFIGS: CategoryConfig[] = [
  { key: "final", label: "综合报告", color: "#60a5fa", matchType: "final_report" },
  { key: "macro", label: "宏观数据", color: "#38bdf8", matchType: "macro_report" },
  { key: "options", label: "期权分析", color: "#a78bfa", matchType: "options_report" },
  { key: "jin10_daily", label: "日报", color: "#f59e0b", matchType: "jin10_daily_report" },
  { key: "jin10_weekly", label: "周报", color: "#14b8a6", matchType: "jin10_weekly_report" },
  { key: "jin10_positioning", label: "持仓", color: "#22c55e", matchType: "jin10_positioning_report" },
  { key: "jin10_levels", label: "点位", color: "#60a5fa", matchType: "jin10_technical_levels_report" },
  { key: "jin10_oil", label: "原油", color: "#f97316", matchType: "jin10_oil_report" },
  { key: "jin10_fx", label: "外汇", color: "#8b5cf6", matchType: "jin10_fx_report" },
  { key: "jin10_market_observation", label: "市场观察", color: "#06b6d4", matchType: "jin10_market_observation_report" },
];

export const ASSET_OPTIONS = [
  { key: "all", label: "全部", color: "var(--brand)" },
  { key: "XAUUSD", label: "XAUUSD", color: "#f59e0b" },
  { key: "OG", label: "OG (Gold)", color: "#10b981" },
  { key: "OIL", label: "原油", color: "#f97316" },
  { key: "FX", label: "外汇", color: "#8b5cf6" },
];

export const STATUS_OPTIONS = [
  { key: "published", label: "已发布" },
  { key: "draft", label: "草稿" },
  { key: "review", label: "待复核" },
  { key: "archived", label: "已归档" },
];

export const DATA_SOURCE_OPTIONS = [
  { key: "agent", label: "Agent" },
  { key: "manual", label: "人工" },
  { key: "api", label: "API" },
];

export const DATE_RANGE_OPTIONS: [string, string][] = [
  ["1d", "今日"],
  ["7d", "近 7 天"],
  ["30d", "近 30 天"],
  ["all", "全部"],
];

export const REPORTS_RAIL_PANEL_STYLE = {
  width: 184,
  flexShrink: 0,
  borderRight: "1px solid var(--border)",
  background: "var(--bg-panel)",
  overflow: "hidden",
  padding: "10px",
  maxHeight: "none",
  minHeight: 0,
} as const;
