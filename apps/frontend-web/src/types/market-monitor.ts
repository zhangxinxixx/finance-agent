import type { SourceTraceItem } from "@/types/dashboard";

export type MarketMonitorStatus = "ok" | "warn" | "error" | "unavailable" | "info";

export type MarketMonitorMetricGroup = "metals" | "dollar" | "rates" | "liquidity" | "funding";

export type MarketMonitorChange = string | number | null;

export type MarketRegimeKey = "rate_pressure" | "transition_release" | "trend_tailwind";

export type MarketEnvironmentFilterKey = "us10y" | "dxy" | "us02y" | "xauusd_price_reaction";

export interface MarketMonitorMetric {
  key: string;
  label: string;
  group: MarketMonitorMetricGroup;
  latest_date: string;
  latest_value: number | string | null;
  unit: string;
  one_week_change: MarketMonitorChange;
  one_month_change: MarketMonitorChange;
  status: MarketMonitorStatus;
  interpretation: string;
  source_refs?: string[];
  snapshot_id?: string | null;
  source_trace?: SourceTraceItem[];
}

export interface MarketRegime {
  label: string;
  status: MarketMonitorStatus;
  confidence: number;
  description: string;
  interpretation: string;
  drivers: string[];
}

export interface MarketAgentRegimeSummary {
  agentName?: string | null;
  regime: string;
  regimeLabel: string;
  confidence: number;
  summary: string;
  keyDrivers: string[];
  llmModel: string | null;
  llmElapsedSeconds: number | null;
}

export interface MarketEnvironmentFilter {
  label: string;
  status: MarketMonitorStatus;
  latest_value: number | string | null;
  one_week_change: MarketMonitorChange;
  one_month_change: MarketMonitorChange;
  interpretation: string;
  unit?: string;
}

export interface MarketMonitorSourceTraceItem extends SourceTraceItem {}

export interface MarketMonitorMockFile {
  generated_at: string;
  latest_date: string;
  has_data: boolean;
  source: "api" | "mock" | "unavailable";
  metrics: MarketMonitorMetric[];
  market_regimes: Record<MarketRegimeKey, MarketRegime>;
  environment_filters: Record<MarketEnvironmentFilterKey, MarketEnvironmentFilter>;
  source_trace: MarketMonitorSourceTraceItem[];
  error_reason?: string | null;
  realtime_regime?: {
    regime: string;
    confidence: number;
    available: boolean;
  } | null;
  primary_driver?: {
    driver: string;
    secondary?: string | null;
    confidence: number;
  } | null;
  agent_market_regime?: MarketAgentRegimeSummary | null;
}

export interface MarketMonitorResponse extends MarketMonitorMockFile {}
