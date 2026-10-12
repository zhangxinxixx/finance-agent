import { findMetric } from "@/components/market-monitor/format";
import type {
  MarketAgentRegimeSummary,
  MarketMonitorMetric,
  MarketMonitorMockFile,
  MarketMonitorSourceTraceItem,
  MarketMonitorStatus,
} from "@/types/market-monitor";

export type MarketMonitorTab = "overview" | "pricing-chain" | "cross-asset" | "calendar" | "odds";

export type MarketMonitorShape = {
  generated_at?: string | null;
  latest_date?: string | null;
  source?: string | null;
  error_reason?: string | null;
  has_data?: boolean | null;
  metrics?: MarketMonitorMetric[] | null;
  market_regimes?: MarketMonitorMockFile["market_regimes"] | null;
  environment_filters?: MarketMonitorMockFile["environment_filters"] | null;
  source_trace?: MarketMonitorSourceTraceItem[] | null;
  realtime_regime?: MarketMonitorMockFile["realtime_regime"] | null;
  primary_driver?: MarketMonitorMockFile["primary_driver"] | null;
  agent_market_regime?: MarketAgentRegimeSummary | null;
};

export function isNonEmptyArray(value: unknown): value is unknown[] {
  return Array.isArray(value) && value.length > 0;
}

export function diagnosisStatus(metrics: MarketMonitorMetric[]): MarketMonitorStatus {
  if (!metrics.length) {
    return "unavailable";
  }

  const xau = findMetric(metrics, "XAUUSD");
  const dxy = findMetric(metrics, "DXY");
  const real = findMetric(metrics, "REAL_10Y");

  if (xau?.status === "error" || dxy?.status === "error" || real?.status === "error") {
    return "error";
  }
  if (metrics.some((metric) => metric.status === "warn")) {
    return "warn";
  }
  if (metrics.some((metric) => metric.status === "ok" && metric.latest_value !== null && metric.latest_value !== undefined)) {
    return "ok";
  }
  return "info";
}

export function diagnosisText(status: MarketMonitorStatus) {
  if (status === "ok") return "观测可用，驱动待确认";
  if (status === "warn") return "部分观测需复核";
  if (status === "error") return "观测读取失败";
  if (status === "unavailable") return "数据不可用";
  return "等待市场观测";
}

export function buildMarketMonitorTabOptions() {
  return [
    { value: "overview", label: "总览" },
    { value: "pricing-chain", label: "定价链" },
    { value: "cross-asset", label: "跨资产" },
    { value: "calendar", label: "日历 / 事件" },
    { value: "odds", label: "市场赔率" },
  ] satisfies Array<{ value: MarketMonitorTab; label: string }>;
}
