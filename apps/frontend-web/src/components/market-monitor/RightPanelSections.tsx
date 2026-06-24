import { Activity } from "lucide-react";
import { ContextPanelSectionHeader } from "@/components/shared/ContextPanel";
import type { MarketAgentRegimeSummary, MarketMonitorMockFile, MarketRegimeKey } from "@/types/market-monitor";
export {
  CalendarSection,
  EventDynamicsSection,
  KnowledgeTagsSection,
  ReportLinksSection,
  ReportsKnowledgeSection,
} from "./RightPanelStaticSections";

const REGIME_ORDER: MarketRegimeKey[] = ["rate_pressure", "transition_release", "trend_tailwind"];

const REGIME_COLORS: Record<MarketRegimeKey, string> = {
  rate_pressure: "#f05252",
  transition_release: "#f59e0b",
  trend_tailwind: "#10b981",
};

export function MarketDiagnosisSection({
  marketRegimes,
  agentMarketRegime,
}: {
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime?: MarketAgentRegimeSummary | null;
}) {
  const activeRegime = REGIME_ORDER.find((key) => marketRegimes?.[key]?.status === "ok" || marketRegimes?.[key]?.status === "warn");
  const regimeLabel = agentMarketRegime?.regimeLabel
    || (activeRegime && marketRegimes?.[activeRegime] ? marketRegimes[activeRegime].label : "过渡释放态");

  return (
    <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border-faint)" }}>
      <ContextPanelSectionHeader icon={Activity} title="市场诊断" iconColor="var(--fg-5)" className="mb-2" />
      <div style={{ marginBottom: 8 }}>
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontWeight: 500,
            fontSize: 9,
            lineHeight: 1,
            padding: "3px 8px",
            borderRadius: 3,
            background: "rgba(245,158,11,0.08)",
            border: "1px solid rgba(245,158,11,0.22)",
            color: "#f59e0b",
            display: "inline-block",
          }}
        >
          {regimeLabel}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {REGIME_ORDER.map((key) => {
          const item = marketRegimes?.[key];
          if (!item) return null;
          const color = REGIME_COLORS[key];

          return (
            <div
              key={key}
              style={{
                padding: "6px 8px",
                background: "var(--bg-card-inner)",
                border: "1px solid var(--border-faint)",
                borderRadius: 3,
                borderLeft: `2px solid ${color}`,
              }}
            >
              <div className="flex items-center justify-between">
                <span style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 9.5, color: "var(--fg-2)" }}>
                  {item.label}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--fg-5)" }}>
                  {item.confidence <= 1 ? `${(item.confidence * 100).toFixed(0)}%` : `${item.confidence}%`}
                </span>
              </div>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 9, lineHeight: 1.5, color: "var(--fg-4)", marginTop: 4 }}>
                {item.description}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
