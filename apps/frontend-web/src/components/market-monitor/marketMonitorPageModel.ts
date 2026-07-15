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
  const xau = findMetric(metrics, "XAUUSD");
  const dxy = findMetric(metrics, "DXY");
  const real = findMetric(metrics, "REAL_10Y");

  if (xau?.status === "error" || dxy?.status === "error" || real?.status === "error") {
    return "error";
  }
  if (real && typeof real.one_week_change === "number" && real.one_week_change > 0) {
    return "warn";
  }
  if (xau && dxy && xau.status === "ok" && dxy.status === "ok") {
    return "ok";
  }
  return "info";
}

export function diagnosisText(status: MarketMonitorStatus) {
  if (status === "ok") return "美元走弱驱动";
  if (status === "warn") return "过渡释放态";
  if (status === "error") return "高噪声风险";
  if (status === "unavailable") return "数据不可用";
  return "混合观察";
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
