import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { MarketMonitorMockFile, MarketRegimeKey } from "@/types/market-monitor";
import { statusTone, textOrDash } from "./format";

interface MarketRegimePanelProps {
  marketRegimes: MarketMonitorMockFile["market_regimes"];
}

const REGIME_ORDER: MarketRegimeKey[] = [
  "rate_pressure",
  "transition_release",
  "trend_tailwind",
  "liquidity_crunch",
  "monetary_credit_repricing",
];

function formatConfidence(confidence: number) {
  if (!Number.isFinite(confidence)) {
    return "—";
  }

  const normalized = confidence <= 1 ? confidence * 100 : confidence;
  return `${normalized.toFixed(normalized % 1 === 0 ? 0 : 1)}%`;
}

function progressTone(status: NonNullable<MarketMonitorMockFile["market_regimes"]>[MarketRegimeKey]["status"]) {
  if (status === "ok") return "bg-[var(--up)]";
  if (status === "warn") return "bg-[var(--warn)]";
  if (status === "error") return "bg-[var(--down)]";
  if (status === "info") return "bg-[var(--info)]";
  return "bg-[var(--fg-5)]";
}

const REGIME_LABELS: Record<MarketRegimeKey, { zh: string; color: string; icon: string }> = {
  rate_pressure: { zh: "利率压力", color: "#f05252", icon: "▼" },
  transition_release: { zh: "过渡释放", color: "#f59e0b", icon: "◆" },
  trend_tailwind: { zh: "趋势顺风", color: "#10b981", icon: "▲" },
  liquidity_crunch: { zh: "流动性踩踏", color: "#dc2626", icon: "✦" },
  monetary_credit_repricing: { zh: "货币信用重估", color: "#2563eb", icon: "●" },
};

export function MarketRegimePanel({ marketRegimes }: MarketRegimePanelProps) {
  return (
    <FACard title="市场阶段诊断" eyebrow="做单环境评估" accent="warn">
      <div className="space-y-2">
        {REGIME_ORDER.map((key) => {
          const item = marketRegimes?.[key];
          const meta = REGIME_LABELS[key];
          const confidenceValue = item ? (item.confidence <= 1 ? item.confidence * 100 : item.confidence) : 0;

          return (
            <div
              key={key}
              style={{
                background: "var(--bg-card-inner)",
                border: "1px solid var(--border-faint)",
                borderLeft: `3px solid ${meta.color}`,
                borderRadius: 8,
                padding: "10px 12px",
                opacity: item?.status === "unavailable" ? 0.5 : 1,
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex items-center gap-2">
                  <span style={{ color: meta.color, fontSize: 11 }}>{meta.icon}</span>
                  <div>
                    <div className="text-[11px] font-semibold text-[var(--fg-2)]">
                      {item?.label ?? meta.zh}
                    </div>
                    <div className="mt-0.5 text-[9px] text-[var(--fg-5)] font-mono">{key}</div>
                  </div>
                </div>
                <FAStatusPill tone={statusTone(item?.status ?? "unavailable")}>
                  {item?.status ?? "—"}
                </FAStatusPill>
              </div>

              {/* 确信度条 */}
              <div className="mt-3 flex items-center gap-2">
                <span className="text-[9px] text-[var(--fg-5)]">确信度</span>
                <div className="flex-1 h-1.5 overflow-hidden rounded-full bg-[var(--bg-terminal)]">
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${Math.max(0, Math.min(100, confidenceValue))}%`,
                      background: meta.color,
                    }}
                  />
                </div>
                <span className="fa-num text-[10px] font-semibold text-[var(--fg-2)]">
                  {formatConfidence(item?.confidence ?? 0)}
                </span>
              </div>

              {item?.description ? (
                <p className="mt-2 text-[10px] leading-5 text-[var(--fg-4)]">{item.description}</p>
              ) : null}
              {item?.interpretation ? (
                <p className="mt-1 text-[10px] leading-5 text-[var(--fg-3)]">{item.interpretation}</p>
              ) : !item ? (
                <p className="mt-2 text-[10px] text-[var(--fg-5)]">暂无诊断数据</p>
              ) : null}

              {item?.drivers && item.drivers.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {item.drivers.map((driver) => (
                    <span
                      key={`${key}-${driver}`}
                      className="rounded-[3px] px-1.5 py-0.5 text-[9px]"
                      style={{
                        background: "var(--bg-terminal)",
                        border: "1px solid var(--border-faint)",
                        color: "var(--fg-4)",
                      }}
                    >
                      {driver}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </FACard>
  );
}
