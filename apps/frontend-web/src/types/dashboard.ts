import type { DataStatus, ModuleStatus, ReportMeta, SourceRef } from "@/types/common";

export type PipelineStageStatus = "done" | "running" | "pending" | "unavailable";

export type TrendDirection = "up" | "down" | "flat";

export type SignalDirection = "bullish" | "bearish" | "neutral";

export type DataOverallStatus = "LIVE" | "PARTIAL" | "MOCK" | "UNAVAILABLE";

export interface DataStatusSource {
  name: string;
  status: DataOverallStatus;
  source: "api" | "mock" | "unavailable";
  label: string;
}

export interface DataStatusSummary {
  overall_status: DataOverallStatus;
  latest_run: {
    run_id: string;
    status: string;
    created_at: string | null;
    trade_date: string | null;
  } | null;
  snapshot_id: string | null;
  data_date: string | null;
  sources: DataStatusSource[];
  missing_sources: string[];
}

export interface UnifiedDate {
  trade_date: string;
  modules: string[];
  latest_run_id: string | null;
  has_final_report: boolean;
  has_strategy_card: boolean;
}

export interface PipelineStatus {
  raw: PipelineStageStatus;
  parsed: PipelineStageStatus;
  features: PipelineStageStatus;
  agent: PipelineStageStatus;
  report: PipelineStageStatus;
  knowledge: PipelineStageStatus;
}

export interface DashboardMetric {
  label: string;
  value: number | string | null;
  unit?: string;
  change?: string | null;
  trend?: TrendDirection;
  status?: "ok" | "warn" | "error" | "unavailable" | "info";
  note?: string;
}

export interface WallLevel {
  strike: number;
  score: number;
  distance_pct: number;
}

export interface OptionsSummary {
  trade_date: string;
  product: string;
  expiries: string[];
  summary_text?: string;
  data_status?: string;
  intent: string;
  intent_score: number;
  confidence?: {
    score: number;
    level: string;
    trade_date: string | null;
    age_days: number | null;
    data_status: string;
    reasons: string[];
  };
  gamma_zero: number | null;
  pin_level: number | null;
  net_gex: number | null;
  wall_score: number | null;
  market_regime: string;
  upper_resistance_walls: WallLevel[];
  lower_support_walls: WallLevel[];
}

export interface MacroSummary {
  indicators: Record<string, DashboardMetric>;
}

export interface StrategyCardData {
  bias: string;
  direction: SignalDirection;
  confidence: number;
  macro_phase: string;
  key_levels: { resistance: number[]; support: number[] };
  triggers: string[];
  invalid_conditions: string[];
  risk_points: string[];
  run_id?: string;
  snapshot_id?: string;
  evidence_refs?: { source?: string; ref?: string; description?: string }[];
  data_quality?: string[];
  data_category_summary?: {
    confirmed_data?: number;
    external_opinion?: number;
    system_inference?: number;
    total?: number;
  };
}

export interface DashboardAgentCompactSummary {
  agentName?: string | null;
  status?: string | null;
  bias: string;
  confidence: number;
  summary: string;
  summaryRaw?: string;
  factReviewStatus: string | null;
  keyFindings: string[];
  riskPoints: string[];
  invalidConditions: string[];
  watchlist: string[];
  claimCount: number;
  createdAt: string | null;
}

export interface DashboardAgentSummary {
  coordinator: DashboardAgentCompactSummary | null;
  synthesis: DashboardAgentCompactSummary | null;
}

export interface RiskItem {
  label: string;
  value: string;
  status: "ok" | "warn" | "error" | "unavailable" | "info";
  note?: string;
}

export interface SourceTraceItem {
  name: string;
  trade_date: string;
  file: string;
  snapshot_id: string | null;
  source_ref: string;
  endpoint?: string | null;
  latest_raw_time?: string | null;
  latest_parsed_time?: string | null;
  model_version?: string | null;
  status: "ok" | "warn" | "error" | "unavailable";
}

export type DashboardReportStatus = "ready" | "pending" | "missing" | "degraded";

export interface ReportItem {
  title: string;
  trade_date: string;
  run_id: string | null;
  url?: string | null;
  status: DashboardReportStatus;
  quality_audit?: {
    status?: string | null;
    reason_codes?: string[];
  } | null;
}

export interface DashboardCompositeAnalysisStatus {
  status: "available" | "partial" | "stale" | "missing" | string;
  trade_date: string | null;
  strategy_trade_date: string | null;
  final_report_trade_date: string | null;
  latest_report_date: string | null;
  latest_eligible_context_date: string | null;
  degraded_newer_reports: Array<{
    type?: string | null;
    trade_date?: string | null;
    run_id?: string | null;
    title?: string | null;
    quality_status?: string | null;
  }>;
  warnings: string[];
}

export interface TaskItem {
  title: string;
  status: "done" | "running" | "pending" | "failed";
  detail?: string;
}

export interface DataSourceBrief {
  label: string;
  status: "ok" | "warn" | "error" | "unavailable";
  updated_at: string | null;
}

export interface DashboardSummary {
  generated_at: string;
  realtime_status?: {
    source: string;
    generated_at: string | null;
    available_symbols: string[];
    message?: string;
  };
  realtime_quotes?: Record<string, {
    price?: number | null;
    value?: number | null;
    change?: number | null;
    change_pct?: number | null;
    unit?: string | null;
    time?: string | null;
    source?: string | null;
    name?: string | null;
  }>;
  conclusion: {
    bias: string;
    direction: SignalDirection;
    confidence: number;
    macro_phase: string;
    options_summary: string;
    pin_level: number | null;
    resistance_levels: number[];
    support_levels: number[];
    wall_score: number | null;
    net_gex: number | null;
  };
  market_summary: {
    XAUUSD: DashboardMetric;
    DXY: DashboardMetric;
    US10Y: DashboardMetric;
    US02Y: DashboardMetric;
    T10YIE: DashboardMetric;
    REAL_10Y: DashboardMetric;
  };
  macro_liquidity: {
    RRP: DashboardMetric;
    TGA: DashboardMetric;
    BANK_RESERVES: DashboardMetric;
    SOFR: DashboardMetric;
    IORB: DashboardMetric;
  };
  cme_options: OptionsSummary;
  strategy: StrategyCardData;
  risk: {
    items: RiskItem[];
    alerts: string[];
  };
  pipeline: PipelineStatus;
  warnings: string[];
  risk_alerts: string[];
  agent_summary?: DashboardAgentSummary;
  composite_analysis?: DashboardCompositeAnalysisStatus;
  latest_reports: ReportItem[];
  recent_tasks: TaskItem[];
  data_source_status: Record<string, DataSourceBrief>;
  source_trace: SourceTraceItem[];
}

export interface DashboardViewModel {
  status: DataStatus;
  trade_date: string | null;
  run_id?: string | null;
  generated_at: string | null;
  market_state: DashboardMarketStateViewModel;
  key_drivers: DashboardDriverItem[];
  strategy_card: DashboardStrategyCardViewModel | null;
  cme_summary: DashboardCMEOptionsSummaryViewModel | null;
  macro_summary: DashboardMacroSummaryViewModel | null;
  risk_alerts: DashboardRiskItemView[];
  data_status: ModuleStatus[];
  latest_reports: ReportMeta[];
  modules: ModuleStatus[];
  source_refs: SourceRef[];
}

export interface DashboardMarketStateViewModel {
  label: string;
  bias: SignalDirection | "unknown";
  confidence: number | null;
  status: DataStatus;
  summary: string;
  updated_at?: string | null;
  source_refs: SourceRef[];
}

export interface DashboardDriverItem {
  id: string;
  label: string;
  summary: string;
  status: DataStatus;
  source_refs: SourceRef[];
}

export interface DashboardRiskItemView {
  id: string;
  label: string;
  detail: string;
  severity: "info" | "success" | "warning" | "danger" | "muted";
  status: DataStatus;
  source_refs: SourceRef[];
}

export interface DashboardStrategyCardViewModel {
  status: DataStatus;
  bias: string;
  direction: SignalDirection | "unknown";
  confidence: number | null;
  scenario_summary?: string;
  trigger_conditions: string[];
  invalid_conditions: string[];
  risk_points: string[];
  watchlist: string[];
  is_trade_instruction: boolean;
  run_id?: string | null;
  snapshot_id?: string | null;
  evidence_refs?: StrategyCardData["evidence_refs"];
  data_quality?: StrategyCardData["data_quality"];
  data_category_summary?: StrategyCardData["data_category_summary"];
  source_refs: SourceRef[];
}

export interface DashboardCMEOptionsSummaryViewModel {
  status: DataStatus;
  trade_date: string | null;
  product: string;
  intent: string;
  confidence: number | null;
  gamma_zero: number | null;
  pin_level: number | null;
  resistance_levels: number[];
  support_levels: number[];
  source_refs: SourceRef[];
}

export interface DashboardMacroSummaryViewModel {
  status: DataStatus;
  phase: string;
  metrics: DashboardMetric[];
  source_refs: SourceRef[];
}

export interface DashboardDateSnapshot extends UnifiedDate {
  summary: DashboardSummary | null;
}

export interface DashboardMockFile {
  default_date: string;
  dates: UnifiedDate[];
  summaries: Record<string, DashboardSummary>;
}

export interface DashboardDataResponse {
  dates: UnifiedDate[];
  selected_date: string | null;
  summary: DashboardSummary | null;
  has_data: boolean;
  source: "api" | "mock" | "unavailable";
  status: DataStatus;
  source_refs: SourceRef[];
  modules: ModuleStatus[];
  view_model: DashboardViewModel | null;
}
