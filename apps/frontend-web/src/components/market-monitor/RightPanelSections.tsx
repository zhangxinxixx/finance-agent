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

const AGENT_REGIME_LABELS: Record<string, string> = {
  rate_pressure: "利率压力",
  transition_release: "过渡释放",
  trend_tailwind: "趋势顺风",
  liquidity_crunch: "流动性收缩",
  monetary_credit_repricing: "货币信用重估",
  neutral_firm: "中性偏强",
  neutral: "中性震荡",
  unknown: "阶段待确认",
};

const REGIME_DISPLAY_LABELS: Record<MarketRegimeKey, string> = {
  rate_pressure: "利率压力",
  transition_release: "过渡释放",
  trend_tailwind: "趋势顺风",
  liquidity_crunch: "流动性收缩",
  monetary_credit_repricing: "货币信用重估",
};

function formatConfidence(confidence: number | null | undefined) {
  const value = typeof confidence === "number" ? confidence : 0;
  return value <= 1 ? Math.round(value * 100) : Math.round(value);
}

function formatRegimeDescription(description: string) {
  return AGENT_REGIME_LABELS[description] ?? description;
}

function compactRegimeLabel(
  agentMarketRegime: MarketAgentRegimeSummary | null | undefined,
  fallbackLabel: string,
) {
  const mapped = agentMarketRegime?.regime ? AGENT_REGIME_LABELS[agentMarketRegime.regime] : undefined;
  if (mapped) return mapped;

  const rawLabel = agentMarketRegime?.regimeLabel?.trim();
  if (rawLabel && rawLabel.length <= 14) return rawLabel;
  return fallbackLabel;
}

export function MarketDiagnosisSection({
  marketRegimes,
  agentMarketRegime,
}: {
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime?: MarketAgentRegimeSummary | null;
}) {
  const activeRegime = REGIME_ORDER.find((key) => marketRegimes?.[key]?.status === "ok" || marketRegimes?.[key]?.status === "warn");
  const fallbackLabel = activeRegime ? REGIME_DISPLAY_LABELS[activeRegime] : "过渡释放";
  const regimeLabel = compactRegimeLabel(agentMarketRegime, fallbackLabel);
  const activeConfidence = formatConfidence(agentMarketRegime?.confidence ?? (activeRegime ? marketRegimes?.[activeRegime]?.confidence : 0));
  const summary = agentMarketRegime?.summary || agentMarketRegime?.regimeLabel || (activeRegime ? marketRegimes?.[activeRegime]?.interpretation : "");
  const keyDrivers = agentMarketRegime?.keyDrivers?.filter(Boolean).slice(0, 3) ?? [];

  return (
    <div className="market-monitor-right-section">
      <ContextPanelSectionHeader
        icon={Activity}
        title="市场诊断"
        meta={agentMarketRegime?.llmModel ? "agent" : "rules"}
        iconColor="var(--brand-hover)"
        className="market-monitor-right-section-header"
      />
      <div className="market-monitor-right-diagnosis-card">
        <div className="market-monitor-right-diagnosis-top">
          <span className="market-monitor-right-regime-badge">
            {regimeLabel}
          </span>
          <span className="market-monitor-right-confidence-pill">
            {activeConfidence}%
          </span>
        </div>
        <div className="market-monitor-right-confidence-track" aria-hidden="true">
          <span style={{ width: `${Math.max(0, Math.min(100, activeConfidence))}%` }} />
        </div>
        {summary ? (
          <div className="market-monitor-right-diagnosis-summary">
            {summary}
          </div>
        ) : null}
        {keyDrivers.length > 0 ? (
          <div className="market-monitor-right-driver-list">
            {keyDrivers.map((driver) => (
              <span key={driver} className="market-monitor-right-driver-chip">
                {driver}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="market-monitor-right-regime-list">
        {REGIME_ORDER.map((key) => {
          const item = marketRegimes?.[key];
          if (!item) return null;
          const color = REGIME_COLORS[key];
          const confidence = formatConfidence(item.confidence);

          return (
            <div
              key={key}
              className="market-monitor-right-regime-card"
              data-active={key === activeRegime ? "true" : "false"}
              style={{ borderLeftColor: color }}
            >
              <div className="flex items-center justify-between">
                <span className="market-monitor-right-regime-title">
                  {REGIME_DISPLAY_LABELS[key]}
                </span>
                <span className="market-monitor-right-regime-confidence">
                  {confidence}%
                </span>
              </div>
              <div className="market-monitor-right-regime-description">
                {formatRegimeDescription(item.description)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
