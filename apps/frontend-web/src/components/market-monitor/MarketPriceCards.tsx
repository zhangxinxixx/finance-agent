import type { CSSProperties } from "react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { compactDelta, compactHint, findMetric, formatMetricValue, trendFromChange } from "./format";

interface MarketPriceCardsProps {
  metrics: MarketMonitorMetric[];
}

const FACTOR_KEYS = [
  { key: "XAUUSD", hint: "现货黄金", impact: "bull" as const, impactLabel: "利多" },
  { key: "DXY", hint: "美元指数", impact: "bear" as const, impactLabel: "利空" },
  { key: "US10Y", hint: "10Y 名义利率", impact: "bear" as const, impactLabel: "利空" },
  { key: "REAL_10Y", hint: "10Y 实际利率", impact: "bear" as const, impactLabel: "利空" },
  { key: "T10YIE", hint: "10Y 通胀预期", impact: "bull" as const, impactLabel: "利多" },
  { key: "TGA", hint: "财政现金账户", impact: "mixed" as const, impactLabel: "混合" },
] as const;

type ImpactType = "bull" | "bear" | "mixed";

const IMPACT_STYLES: Record<ImpactType, { accent: string; bg: string; bd: string; fg: string; badgeBg: string }> = {
  bull: {
    accent: "var(--up)",
    bg: "var(--up-soft)",
    bd: "var(--up-border)",
    fg: "var(--up)",
    badgeBg: "var(--up-soft)",
  },
  bear: {
    accent: "var(--down)",
    bg: "var(--down-soft)",
    bd: "var(--down-border)",
    fg: "var(--down)",
    badgeBg: "var(--down-soft)",
  },
  mixed: {
    accent: "var(--fa-important)",
    bg: "var(--fa-important-soft)",
    bd: "var(--fa-important-border)",
    fg: "var(--fa-important)",
    badgeBg: "var(--fa-important-soft)",
  },
};

function trendColor(trend: "up" | "down" | "flat"): string {
  if (trend === "up") return "var(--up)";
  if (trend === "down") return "var(--down)";
  return "var(--fa-text-muted)";
}

function MMBadge({ impact }: { impact: ImpactType }) {
  const style = IMPACT_STYLES[impact];
  return (
    <span
      style={{
        background: style.badgeBg,
        border: `1px solid ${style.accent}33`,
        color: style.fg,
      }}
      className="fa-compact-label inline-flex items-center rounded-[3px] px-1.5 py-[2px] leading-none"
    >
      {impact === "bull" ? "↑" : impact === "bear" ? "↓" : "~"}&nbsp;{FACTOR_KEYS.find((f) => f.impact === impact)?.impactLabel ?? ""}
    </span>
  );
}

export function MarketPriceCards({ metrics }: MarketPriceCardsProps) {
  return (
    <div className="market-monitor-price-strip">
      {FACTOR_KEYS.map(({ key, hint, impact }) => {
        const metric = findMetric(metrics, key);
        const trend = trendFromChange(metric?.one_week_change ?? null);
        const value = metric ? formatMetricValue(metric.latest_value, 4) : "—";
        const delta = compactDelta(metric);
        const hintText = compactHint(metric);
        const color = trendColor(trend);
        const style = IMPACT_STYLES[impact];
        const isUnavailable = metric?.status !== "ok";

        return (
          <article
            key={key}
            style={{
              "--market-card-accent": style.accent,
              "--market-card-bg": style.bg,
              "--market-card-border": style.bd,
              "--market-status-dot":
                metric?.status === "ok"
                  ? "#10b981"
                  : metric?.status === "warn"
                    ? "#f59e0b"
                    : "#64748b",
            } as CSSProperties}
            className="market-monitor-price-card"
          >
            <div className="flex items-start justify-between">
              <div className="min-w-0">
                <div className={`fa-code-label market-monitor-price-symbol ${isUnavailable ? "market-monitor-price-symbol--dim" : ""}`}>
                  {key}
                </div>
                <div className="market-monitor-price-hint">
                  {hint}
                </div>
              </div>
              <MMBadge impact={impact} />
            </div>

            <div className={`fa-price-num fa-price-num--sm market-monitor-price-value ${isUnavailable ? "market-monitor-price-value--dim" : ""}`}>
              {value}
            </div>

            <div className="mt-auto flex items-center justify-between">
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
