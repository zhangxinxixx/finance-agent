import type { DashboardMetric, DashboardSummary } from "@/types/dashboard";

export type DashboardGoldImpactLabel = "利多黄金" | "利空黄金" | "中性" | "混合" | "数据不足";

export interface DashboardKpiMetric {
  label: string;
  value: string;
  delta?: string;
  trend: "up" | "down" | "flat";
  unit: string;
  sparkColor?: string;
  accent: string;
  subtitle?: string;
  impactLabel: DashboardGoldImpactLabel;
  dataStatus: string;
}

type RealtimeQuote = {
  price?: number | null;
  value?: number | null;
  change_pct?: number | null;
};

function metricValue(value: DashboardMetric["value"], fractionDigits = 2): string {
  if (typeof value === "number") return value.toLocaleString("en-US", { maximumFractionDigits: fractionDigits });
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function translateUnit(unit: string | null | undefined): string {
  if (unit === "USD/oz") return "美元/盎司";
  return unit ?? "";
}

function translateSubtitle(text: string | null | undefined): string | undefined {
  if (!text) return undefined;
  const map: Record<string, string> = {
    "neutral-bullish": "中性偏多",
    "neutral-bearish": "中性偏空",
    bullish: "偏多",
    bearish: "偏空",
    neutral: "中性",
    mixed: "混合",
    unavailable: "不可用",
    I2_structured_rebalance: "结构再平衡",
    i2_structured_rebalance: "结构再平衡",
  };
  return map[text] ?? text;
}

function metricStatusOf(metric: DashboardMetric | undefined): string {
  return metric?.status ?? "unavailable";
}

function trendOf(metric: DashboardMetric | undefined): "up" | "down" | "flat" {
  return metric?.trend ?? "flat";
}

function realtimeQuote(summary: DashboardSummary, symbol: string): RealtimeQuote | null {
  const quotes = summary.realtime_quotes ?? {};
  const quote = quotes[symbol] ?? quotes[symbol.toLowerCase()];
  return quote ?? null;
}

function realtimeStatusOf(summary: DashboardSummary, symbol: string): string {
  const status = summary.realtime_status;
  const wanted = symbol.toLowerCase();
  const isAvailable = status?.available_symbols.some((item) => item.toLowerCase() === wanted);
  return isAvailable
    ? status?.source || "live"
    : "unavailable";
}

function realtimeTrend(changePct: number | null | undefined): "up" | "down" | "flat" {
  if (typeof changePct !== "number" || changePct === 0) return "flat";
  return changePct > 0 ? "up" : "down";
}

function formatChangePct(changePct: number | null | undefined): string | undefined {
  if (typeof changePct !== "number") return undefined;
  return `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`;
}

const backendImpactMap: Record<string, DashboardGoldImpactLabel> = {
  利多黄金: "利多黄金",
  利多: "利多黄金",
  利空黄金: "利空黄金",
  利空: "利空黄金",
  混合: "混合",
  mixed: "混合",
  "neutral-bullish": "混合",
  "neutral-bearish": "混合",
  中性: "中性",
  neutral: "中性",
};

function impactFromBackendKey(metric: DashboardMetric | undefined, subtitle?: string): DashboardGoldImpactLabel {
  if (metric == null || metric.value === null || metric.value === undefined || metric.value === "") return "数据不足";

  const rawNote = metric.note?.trim();
  const rawSubtitle = subtitle?.trim();
  return backendImpactMap[rawNote ?? ""] ?? backendImpactMap[rawSubtitle ?? ""] ?? "数据不足";
}

export function buildDashboardKpiMetrics(summary: DashboardSummary): DashboardKpiMetric[] {
  const { market_summary: market, cme_options: options } = summary;
  const xauRT = realtimeQuote(summary, "XAUUSD");
  const dxyRT = realtimeQuote(summary, "DXY");

  const xauValue = xauRT?.price ?? xauRT?.value;
  const dxyValue = dxyRT?.price ?? dxyRT?.value;
  const xauTrend = xauRT ? realtimeTrend(xauRT.change_pct) : trendOf(market.XAUUSD);
  const dxyTrend = dxyRT ? realtimeTrend(dxyRT.change_pct) : trendOf(market.DXY);

  const xauSubtitle = translateSubtitle(market.XAUUSD.note) ?? (xauRT?.change_pct != null ? "实时行情" : undefined);
  const dxySubtitle = translateSubtitle(market.DXY.note) ?? (dxyRT?.change_pct != null ? "实时行情" : undefined);
  const us10ySubtitle = translateSubtitle(market.US10Y.note);
  const real10ySubtitle = translateSubtitle(market.REAL_10Y.note);
  const gexSubtitle = translateSubtitle(options.market_regime);
  const pinSubtitle = translateSubtitle(options.intent);

  return [
    {
      label: "XAUUSD",
      value: xauValue != null ? xauValue.toLocaleString("en-US", { maximumFractionDigits: 1 }) : metricValue(market.XAUUSD.value, 1),
      delta: formatChangePct(xauRT?.change_pct) ?? market.XAUUSD.change ?? undefined,
      trend: xauTrend,
      unit: translateUnit(market.XAUUSD.unit),
      accent: "#f59e0b",
      subtitle: xauSubtitle,
      impactLabel: impactFromBackendKey(market.XAUUSD, xauSubtitle),
      dataStatus: xauRT ? realtimeStatusOf(summary, "XAUUSD") : metricStatusOf(market.XAUUSD),
    },
    {
      label: "DXY",
      value: dxyValue != null ? dxyValue.toLocaleString("en-US", { maximumFractionDigits: 2 }) : metricValue(market.DXY.value, 2),
      delta: formatChangePct(dxyRT?.change_pct) ?? market.DXY.change ?? undefined,
      trend: dxyTrend,
      unit: translateUnit(market.DXY.unit),
      accent: "#3b82f6",
      subtitle: dxySubtitle,
      impactLabel: impactFromBackendKey(market.DXY, dxySubtitle),
      dataStatus: dxyRT ? realtimeStatusOf(summary, "DXY") : metricStatusOf(market.DXY),
    },
    {
      label: "US10Y",
      value: metricValue(market.US10Y.value, 2),
      delta: market.US10Y.change ?? undefined,
      trend: trendOf(market.US10Y),
      unit: "%",
      sparkColor: market.US10Y.trend === "up" ? "var(--up)" : market.US10Y.trend === "down" ? "var(--down)" : undefined,
      accent: "#06b6d4",
      subtitle: us10ySubtitle,
      impactLabel: impactFromBackendKey(market.US10Y, us10ySubtitle),
      dataStatus: metricStatusOf(market.US10Y),
    },
    {
      label: "REAL 10Y",
      value: metricValue(market.REAL_10Y.value, 2),
      delta: market.REAL_10Y.change ?? undefined,
      trend: trendOf(market.REAL_10Y),
      unit: "%",
      sparkColor: market.REAL_10Y.trend === "up" ? "var(--up)" : market.REAL_10Y.trend === "down" ? "var(--down)" : undefined,
      accent: "#a78bfa",
      subtitle: real10ySubtitle,
      impactLabel: impactFromBackendKey(market.REAL_10Y, real10ySubtitle),
      dataStatus: metricStatusOf(market.REAL_10Y),
    },
    {
      label: "净GEX",
      value: options.net_gex != null ? options.net_gex.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—",
      trend: "flat",
      unit: "",
      sparkColor: "var(--warn)",
      accent: "#f59e0b",
      subtitle: gexSubtitle,
      impactLabel: impactFromBackendKey({ label: "净GEX", value: options.net_gex, note: options.market_regime }, gexSubtitle),
      dataStatus: options.data_status ?? options.confidence?.data_status ?? "unavailable",
    },
    {
      label: "钉住价位",
      value: options.pin_level != null ? options.pin_level.toLocaleString("en-US", { maximumFractionDigits: 1 }) : "—",
      trend: "flat",
      unit: "",
      sparkColor: "var(--brand-hover)",
      accent: "#3b82f6",
      subtitle: pinSubtitle,
      impactLabel: impactFromBackendKey({ label: "钉住价位", value: options.pin_level, note: options.intent }, pinSubtitle),
      dataStatus: options.data_status ?? options.confidence?.data_status ?? "unavailable",
    },
  ];
}
