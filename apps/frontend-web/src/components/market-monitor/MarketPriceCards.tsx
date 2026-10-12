import type { CSSProperties } from "react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { compactDelta, compactHint, findMetric, formatMetricValue, marketMonitorUnitLabel, textOrDash, trendFromChange } from "./format";

interface MarketPriceCardsProps {
  metrics: MarketMonitorMetric[];
}

type PriceFactor = {
  key: string;
  symbol?: string;
  hint: string;
  priority: "primary" | "secondary";
  showStatus?: boolean;
  tone?: "neutral" | "gold";
};

const FACTOR_KEYS: PriceFactor[] = [
  { key: "XAUUSD", symbol: "现货黄金（XAUUSD）", hint: "美元/盎司", priority: "primary", tone: "gold" },
  { key: "DXY", symbol: "美元指数（DXY）", hint: "指数点", priority: "primary" },
  { key: "US10Y", symbol: "10年名义利率（US10Y）", hint: "利率百分比", priority: "primary" },
  { key: "REAL_10Y", symbol: "10年实际利率（REAL_10Y）", hint: "利率百分比", priority: "primary" },
  { key: "T10YIE", symbol: "10年通胀预期（T10YIE）", hint: "利率百分比", priority: "secondary" },
  { key: "YIELD_SPREAD_2Y_3M", symbol: "2年-3个月利差（2Y3M）", hint: "基点", priority: "secondary" },
  { key: "TGA", symbol: "财政账户（TGA）", hint: "金额", priority: "secondary" },
  { key: "RRP", symbol: "隔夜逆回购（RRP）", hint: "金额", priority: "secondary" },
  { key: "COT_GOLD_NET", symbol: "管理基金净多（COT）", hint: "张数", priority: "secondary" },
  { key: "GLD_HOLDINGS", symbol: "黄金 ETF 持仓（GLD）", hint: "吨", priority: "secondary" },
] as const;

type MetricStatus = MarketMonitorMetric["status"] | "missing";

const STATUS_STYLES: Record<MetricStatus, { fg: string; bg: string; bd: string; dot: string }> = {
  ok: { fg: "var(--up)", bg: "var(--up-soft)", bd: "var(--up-border)", dot: "var(--up)" },
  warn: { fg: "var(--warn)", bg: "var(--warn-soft)", bd: "var(--warn-border)", dot: "var(--warn)" },
  error: { fg: "var(--down)", bg: "var(--down-soft)", bd: "var(--down-border)", dot: "var(--down)" },
  unavailable: { fg: "var(--fg-4)", bg: "var(--bg-panel)", bd: "var(--border-faint)", dot: "var(--fg-5)" },
  info: { fg: "var(--info)", bg: "var(--info-soft)", bd: "var(--info-border)", dot: "var(--info)" },
  missing: { fg: "var(--fg-4)", bg: "var(--bg-panel)", bd: "var(--border-faint)", dot: "var(--fg-5)" },
};

const GOLD_CARD_STYLE = {
  accent: "var(--brand-gold)",
  bg: "var(--brand-gold-dim)",
  bd: "color-mix(in srgb, var(--brand-gold) 42%, transparent)",
};

const NEUTRAL_CARD_STYLE = {
  accent: "var(--border-strong)",
  bg: "var(--bg-card)",
  bd: "var(--border)",
};

function trendColor(trend: "up" | "down" | "flat"): string {
  if (trend === "up") return "var(--up)";
  if (trend === "down") return "var(--down)";
  return "var(--fa-text-muted)";
}

function metricStatusLabel(status: MetricStatus): string {
  if (status === "ok") return "已观测";
  if (status === "warn") return "近期值";
  if (status === "error") return "读取失败";
  if (status === "info") return "待核验";
  return "无观测";
}

function MMBadge({ status }: { status: MetricStatus }) {
  const style = STATUS_STYLES[status];
  return (
    <span
      style={{
        background: style.bg,
        border: `1px solid ${style.bd}`,
        color: style.fg,
      }}
      className="market-monitor-price-status inline-flex items-center rounded-[3px]"
    >
      {metricStatusLabel(status)}
    </span>
  );
}

export function MarketPriceCards({ metrics }: MarketPriceCardsProps) {
  return (
    <div className="market-monitor-price-strip">
      {FACTOR_KEYS.map(({ key, symbol, hint, priority, showStatus = true, tone = "neutral" }) => {
        const metric = findMetric(metrics, key);
        const trend = trendFromChange(metric?.one_week_change ?? null);
        const value = metric ? formatMetricValue(metric.latest_value, 4) : "—";
        const delta = compactDelta(metric);
        const hintText = compactHint(metric);
        const color = trendColor(trend);
        const hasValue = metric?.latest_value !== null && metric?.latest_value !== undefined && metric?.latest_value !== "";
        const metricStatus: MetricStatus = hasValue ? (metric?.status ?? "missing") : "missing";
        const style = tone === "gold" ? GOLD_CARD_STYLE : NEUTRAL_CARD_STYLE;
        const isUnavailable = metricStatus !== "ok";
        const observationDate = textOrDash(metric?.latest_date);
        const unit = metric?.unit ? ` · ${marketMonitorUnitLabel(metric.unit)}` : "";

        return (
          <article
            key={key}
            style={{
              "--market-card-accent": style.accent,
              "--market-card-bg": style.bg,
              "--market-card-border": style.bd,
              "--market-status-dot":
                STATUS_STYLES[metricStatus].dot,
            } as CSSProperties}
            data-priority={priority}
            className="market-monitor-price-card"
            title={metric?.interpretation || undefined}
          >
            <div className="flex items-start justify-between">
              <div className="min-w-0">
                <div className={`fa-code-label market-monitor-price-symbol ${isUnavailable ? "market-monitor-price-symbol--dim" : ""}`}>
                  {symbol ?? key}
                </div>
                <div className="market-monitor-price-hint">
                  {hint}{unit}
                </div>
              </div>
              {showStatus ? <MMBadge status={metricStatus} /> : null}
            </div>

            <div className={`fa-price-num fa-price-num--sm market-monitor-price-value ${isUnavailable ? "market-monitor-price-value--dim" : ""}`}>
              {value}
            </div>

            <div className="fa-compact-meta" data-testid={`market-observation-date-${key}`}>
              观测 {observationDate}
            </div>

            <div className="market-monitor-price-footer">
              <span className="fa-delta" style={{ color }}>
                {delta}
              </span>
              <span className="fa-compact-meta">
                {hintText}
              </span>
            </div>

            <div className="market-monitor-status-dot" />
          </article>
        );
      })}
    </div>
  );
}

export default MarketPriceCards;
