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
  { key: "options", label: "期权分析", color: "#a78bfa", matchType: "options_report" },
  { key: "jin10_daily", label: "Jin10日报", color: "#f59e0b", matchType: "jin10_daily_report" },
  { key: "jin10_weekly", label: "Jin10周报", color: "#14b8a6", matchType: "jin10_weekly_report" },
];

export const ASSET_OPTIONS = [
  { key: "all", label: "全部", color: "var(--brand)" },
  { key: "XAUUSD", label: "XAUUSD", color: "#f59e0b" },
  { key: "OG", label: "OG (Gold)", color: "#10b981" },
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
  width: 190,
  flexShrink: 0,
  borderRight: "1px solid var(--border)",
  background: "var(--bg-panel)",
  overflowY: "auto",
  overflowX: "hidden",
  padding: "10px",
  maxHeight: "calc(100vh - 180px)",
  minHeight: 0,
} as const;
