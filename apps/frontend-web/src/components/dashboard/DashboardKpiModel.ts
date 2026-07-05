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
  impactLabel?: DashboardGoldImpactLabel;
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
  if (!unit) return "";
  if (unit === "USD/oz") return "";
  if (unit === "%") return "%";
  return unit.length > 4 ? "" : unit;
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

function fixedImpact(value: unknown, impact: Exclude<DashboardGoldImpactLabel, "数据不足">): DashboardGoldImpactLabel {
  if (value === null || value === undefined || value === "") return "数据不足";
  return impact;
}

export function buildDashboardKpiMetrics(summary: DashboardSummary): DashboardKpiMetric[] {
  const { market_summary: market, macro_liquidity: liquidity } = summary;
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
  const shortCurve = market.YIELD_SPREAD_2Y_3M;
  const shortCurveSubtitle = translateSubtitle(shortCurve?.note) ?? "短端政策拐点";
  const rrpSubtitle = translateSubtitle(liquidity.RRP.note);
  const tgaSubtitle = translateSubtitle(liquidity.TGA.note);
  const bankReservesSubtitle = translateSubtitle(liquidity.BANK_RESERVES.note);

  function shortCurveImpact(metric: DashboardMetric | undefined): DashboardGoldImpactLabel {
    if (metric == null || metric.value === null || metric.value === undefined || metric.value === "") return "数据不足";
    if (metric.trend === "up") return "利多黄金";
    if (metric.trend === "down") return "利空黄金";
    return metric.status === "ok" ? "中性" : "数据不足";
  }

  return [
    {
      label: "XAUUSD",
      value: xauValue != null ? xauValue.toLocaleString("en-US", { maximumFractionDigits: 1 }) : metricValue(market.XAUUSD.value, 1),
      delta: formatChangePct(xauRT?.change_pct) ?? market.XAUUSD.change ?? undefined,
      trend: xauTrend,
      unit: translateUnit(market.XAUUSD.unit),
      sparkColor: market.XAUUSD.trend === "up" ? "var(--up)" : market.XAUUSD.trend === "down" ? "var(--down)" : undefined,
      accent: "#d4af37",
      subtitle: xauSubtitle,
      dataStatus: xauRT ? realtimeStatusOf(summary, "XAUUSD") : metricStatusOf(market.XAUUSD),
    },
    {
      label: "DXY",
      value: dxyValue != null ? dxyValue.toLocaleString("en-US", { maximumFractionDigits: 2 }) : metricValue(market.DXY.value, 2),
      delta: formatChangePct(dxyRT?.change_pct) ?? market.DXY.change ?? undefined,
      trend: dxyTrend,
      unit: translateUnit(market.DXY.unit),
      sparkColor: market.DXY.trend === "up" ? "var(--up)" : market.DXY.trend === "down" ? "var(--down)" : undefined,
      accent: "#2563eb",
      subtitle: dxySubtitle,
      impactLabel: fixedImpact(dxyValue ?? market.DXY.value, "利空黄金"),
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
      impactLabel: fixedImpact(market.US10Y.value, "利空黄金"),
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
      impactLabel: fixedImpact(market.REAL_10Y.value, "利空黄金"),
      dataStatus: metricStatusOf(market.REAL_10Y),
    },
    {
      label: "2Y-3M",
      value: metricValue(shortCurve?.value ?? null, 2),
      delta: shortCurve?.change ?? undefined,
      trend: trendOf(shortCurve),
      unit: "%",
      sparkColor: shortCurve?.trend === "up" ? "var(--up)" : shortCurve?.trend === "down" ? "var(--down)" : undefined,
      accent: "#22c55e",
      subtitle: shortCurveSubtitle,
      impactLabel: shortCurveImpact(shortCurve),
      dataStatus: metricStatusOf(shortCurve),
    },
    {
      label: "RRP",
      value: metricValue(liquidity.RRP.value, 2),
      delta: liquidity.RRP.change ?? undefined,
      trend: trendOf(liquidity.RRP),
      unit: translateUnit(liquidity.RRP.unit),
      sparkColor: liquidity.RRP.trend === "up" ? "var(--up)" : liquidity.RRP.trend === "down" ? "var(--down)" : undefined,
      accent: "#14b8a6",
      subtitle: rrpSubtitle,
      impactLabel: fixedImpact(liquidity.RRP.value, "混合"),
      dataStatus: metricStatusOf(liquidity.RRP),
    },
    {
      label: "TGA",
      value: metricValue(liquidity.TGA.value, 2),
      delta: liquidity.TGA.change ?? undefined,
      trend: trendOf(liquidity.TGA),
      unit: translateUnit(liquidity.TGA.unit),
      sparkColor: liquidity.TGA.trend === "up" ? "var(--up)" : liquidity.TGA.trend === "down" ? "var(--down)" : undefined,
      accent: "#0ea5e9",
      subtitle: tgaSubtitle,
      impactLabel: fixedImpact(liquidity.TGA.value, "混合"),
      dataStatus: metricStatusOf(liquidity.TGA),
    },
    {
      label: "RESERVES",
      value: metricValue(liquidity.BANK_RESERVES.value, 2),
      delta: liquidity.BANK_RESERVES.change ?? undefined,
      trend: trendOf(liquidity.BANK_RESERVES),
      unit: translateUnit(liquidity.BANK_RESERVES.unit),
      sparkColor: liquidity.BANK_RESERVES.trend === "up" ? "var(--up)" : liquidity.BANK_RESERVES.trend === "down" ? "var(--down)" : undefined,
      accent: "#64748b",
      subtitle: bankReservesSubtitle,
      impactLabel: fixedImpact(liquidity.BANK_RESERVES.value, "混合"),
      dataStatus: metricStatusOf(liquidity.BANK_RESERVES),
    },
  ];
}
