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

const REGIME_ORDER: MarketRegimeKey[] = ["rate_pressure", "transition_release", "trend_tailwind", "liquidity_crunch", "monetary_credit_repricing"];

const REGIME_COLORS: Record<MarketRegimeKey, string> = {
  rate_pressure: "#f05252",
  transition_release: "#f59e0b",
  trend_tailwind: "#10b981",
  liquidity_crunch: "#dc2626",
  monetary_credit_repricing: "#2563eb",
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
    <div className="market-monitor-right-section">
      <ContextPanelSectionHeader icon={Activity} title="市场诊断" iconColor="var(--fg-5)" className="market-monitor-right-section-header" />
      <div className="market-monitor-right-regime-label">
        <span
          className="market-monitor-right-regime-badge"
        >
          {regimeLabel}
        </span>
      </div>
      <div className="market-monitor-right-regime-list">
        {REGIME_ORDER.map((key) => {
          const item = marketRegimes?.[key];
          if (!item) return null;
          const color = REGIME_COLORS[key];

          return (
            <div
              key={key}
              className="market-monitor-right-regime-card"
              style={{ borderLeftColor: color }}
            >
              <div className="flex items-center justify-between">
                <span className="market-monitor-right-regime-title">
                  {item.label}
                </span>
                <span className="market-monitor-right-regime-confidence">
                  {item.confidence <= 1 ? `${(item.confidence * 100).toFixed(0)}%` : `${item.confidence}%`}
                </span>
              </div>
              <div className="market-monitor-right-regime-description">
                {item.description}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
