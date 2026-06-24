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
    accent: "#10b981",
    bg: "linear-gradient(135deg, rgba(16,185,129,0.06) 0%, rgba(16,185,129,0.01) 100%)",
    bd: "rgba(16,185,129,0.18)",
    fg: "#10b981",
    badgeBg: "rgba(16,185,129,0.12)",
  },
  bear: {
    accent: "#f05252",
    bg: "linear-gradient(135deg, rgba(240,82,82,0.06) 0%, rgba(240,82,82,0.01) 100%)",
    bd: "rgba(240,82,82,0.18)",
    fg: "#f05252",
    badgeBg: "rgba(240,82,82,0.12)",
  },
  mixed: {
    accent: "#f59e0b",
    bg: "linear-gradient(135deg, rgba(245,158,11,0.05) 0%, rgba(245,158,11,0.01) 100%)",
    bd: "rgba(245,158,11,0.16)",
    fg: "#f59e0b",
    badgeBg: "rgba(245,158,11,0.10)",
  },
};

function trendColor(trend: "up" | "down" | "flat"): string {
  if (trend === "up") return "#10b981";
  if (trend === "down") return "#f05252";
  return "var(--fg-5)";
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
      className="inline-flex items-center rounded-[3px] px-1.5 py-[1px] text-[8px] font-medium leading-none"
    >
      {impact === "bull" ? "↑" : impact === "bear" ? "↓" : "~"}&nbsp;{FACTOR_KEYS.find((f) => f.impact === impact)?.impactLabel ?? ""}
    </span>
  );
}

export function MarketPriceCards({ metrics }: MarketPriceCardsProps) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6,minmax(0,1fr))", gap: 8 }}>
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
              background: style.bg,
              border: `1px solid ${style.bd}`,
              borderLeft: `3px solid ${style.accent}`,
              borderRadius: 10,
              padding: "10px 12px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
              minHeight: 100,
              position: "relative",
              overflow: "hidden",
              backdropFilter: "blur(4px)",
              transition: "border-color 0.2s, box-shadow 0.2s",
            }}
            className="hover:border-[var(--border)]"
          >
            {/* Top row */}
            <div className="flex items-start justify-between">
              <div className="min-w-0">
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: 11,
                    lineHeight: 1,
                    letterSpacing: "0.02em",
                    color: isUnavailable ? "var(--fg-5)" : "var(--fg-2)",
                  }}
                >
                  {key}
                </div>
                <div style={{ marginTop: 2, fontSize: 8, color: "var(--fg-5)", opacity: 0.7 }}>
                  {hint}
                </div>
              </div>
              <MMBadge impact={impact} />
            </div>

            {/* Value */}
            <div
              className="fa-num"
              style={{
                fontSize: 18,
                fontWeight: 800,
                lineHeight: 1,
                color: isUnavailable ? "var(--fg-5)" : "var(--fg-1)",
                letterSpacing: "-0.02em",
              }}
            >
              {value}
            </div>

            {/* Change stats */}
            <div className="mt-auto flex items-center justify-between">
              <span style={{ fontSize: 10, fontWeight: 600, color }}>
                {delta}
              </span>
              <span style={{ fontSize: 9, color: "var(--fg-5)" }}>
                {hintText}
              </span>
            </div>

            {/* Status dot */}
            <div
              style={{
                position: "absolute",
                top: 10,
                right: 10,
                width: 4,
                height: 4,
                borderRadius: "50%",
                background:
                  metric?.status === "ok"
                    ? "#10b981"
                    : metric?.status === "warn"
                      ? "#f59e0b"
                      : "#64748b",
                opacity: 0.6,
              }}
            />
          </article>
        );
      })}
    </div>
  );
}

export default MarketPriceCards;
