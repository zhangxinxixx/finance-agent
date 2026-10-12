import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import type { MarketMonitorChange, MarketMonitorMetric, MarketMonitorStatus } from "@/types/market-monitor";

const MARKET_MONITOR_SOURCE_LABELS: Record<string, string> = {
  api: "接口归一化结果",
  mock: "模拟数据",
  unavailable: "数据不可用",
  jin10_mcp_realtime: "金十实时行情",
  canonical_xauusd: "规范化行情源",
  canonical_xauusd_mixed: "混合来源（已规范化）",
  market_candles: "本地行情记录",
};

const MARKET_MONITOR_METRIC_LABELS: Record<string, string> = {
  XAUUSD: "现货黄金（XAUUSD）",
  XAGUSD: "现货白银（XAGUSD）",
  DXY: "美元指数（DXY）",
  USDX: "名义美元指数（USDX）",
  US10Y: "10年名义利率（US10Y）",
  US02Y: "2年名义利率（US02Y）",
  REAL_10Y: "10年实际利率（REAL_10Y）",
  T10YIE: "10年通胀预期（T10YIE）",
  YIELD_SPREAD_2Y_3M: "2年-3个月利差（2Y-3M）",
  TGA: "财政账户（TGA）",
  RRP: "隔夜逆回购（RRP）",
  REPO: "逆回购（REPO）",
  SOFR: "担保隔夜融资利率（SOFR）",
  EFFR: "有效联邦基金利率（EFFR）",
  IORB: "准备金利率（IORB）",
  FED_BS: "联储资产负债表（FedBS）",
  COT_GOLD_NET: "管理基金净多（COT）",
  GLD_HOLDINGS: "黄金 ETF 持仓（GLD）",
  SPX: "标普500（SPX）",
  VIX: "波动率指数（VIX）",
  BTC: "比特币（BTC）",
};

export function findMetric(metrics: MarketMonitorMetric[], key: string) {
  return metrics.find((metric) => metric.key === key);
}

export function textOrDash(value: string | number | null | undefined, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  return String(value);
}

export function marketMonitorSourceLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "未提供";
  return MARKET_MONITOR_SOURCE_LABELS[normalized] ?? "来源待核验";
}

export function marketMonitorMetricLabel(key: string, label?: string | null): string {
  if (MARKET_MONITOR_METRIC_LABELS[key]) return MARKET_MONITOR_METRIC_LABELS[key];
  const candidate = String(label ?? "").trim();
  return candidate && /[\u3400-\u9fff]/.test(candidate) ? candidate : "指标待确认";
}

export function marketMonitorStatusLabel(status: MarketMonitorStatus | string | null | undefined): string {
  if (status === "ok") return "正常";
  if (status === "warn") return "需关注";
  if (status === "error") return "读取失败";
  if (status === "info") return "待核验";
  if (status === "unavailable") return "不可用";
  return "未提供";
}

export function marketMonitorUnitLabel(unit: string | null | undefined): string {
  const normalized = String(unit ?? "").trim();
  if (!normalized) return "单位未提供";
  const labels: Record<string, string> = {
    "USD/oz": "美元/盎司",
    index: "指数点",
    contracts: "张",
    tonnes: "吨",
    percent: "%",
    pct: "%",
    bp: "基点",
  };
  if (labels[normalized]) return labels[normalized];
  if (/[\u3400-\u9fff]/.test(normalized) || normalized === "%") return normalized;
  return "单位待确认";
}

export function formatMetricValue(value: MarketMonitorMetric["latest_value"], maxFractionDigits = 2) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "number") {
    return value.toLocaleString("zh-CN", {
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
      maximumFractionDigits: maxFractionDigits,
    });
  }

  return value;
}

export function formatMetricChange(value: MarketMonitorChange, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  if (typeof value === "number") {
    return value.toLocaleString("zh-CN", {
      signDisplay: "always",
      maximumFractionDigits: 2,
    });
  }

  return value;
}

export function compactDelta(metric?: MarketMonitorMetric) {
  if (!metric) {
    return "1W —";
  }

  return `1W ${formatMetricChange(metric.one_week_change)}`;
}

export function compactHint(metric?: MarketMonitorMetric) {
  if (!metric) {
    return "1M —";
  }

  return `1M ${formatMetricChange(metric.one_month_change)}`;
}

function numericDirection(value: MarketMonitorChange): number | null {
  if (typeof value === "number") {
    return value;
  }

  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  if (normalized.startsWith("+")) return 1;
  if (normalized.startsWith("-")) return -1;
  return 0;
}

export function trendFromChange(value: MarketMonitorChange): "up" | "down" | "flat" {
  const direction = numericDirection(value);
  if (direction === null || direction === 0) return "flat";
  return direction > 0 ? "up" : "down";
}

export function statusTone(status: MarketMonitorStatus): FAStatusTone {
  if (status === "ok") return "up";
  if (status === "warn") return "warn";
  if (status === "error") return "down";
  if (status === "info") return "info";
  return "dim";
}

const SOURCE_TIMEFRAME_LABELS: Record<string, string> = {
  "1M": "1分钟",
  "5M": "5分钟",
  "15M": "15分钟",
  "30M": "30分钟",
  "1H": "1小时",
  "4H": "4小时",
  "1D": "日线",
  "1DAY": "日线",
  D: "日线",
};

export function formatHistoryTimeframe(value: string | null | undefined): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "未提供";
  return SOURCE_TIMEFRAME_LABELS[raw.toUpperCase()] ?? `周期标识：${raw}`;
}
