import { Activity } from "lucide-react";
import { ContextPanelSectionHeader } from "@/components/shared/ContextPanel";
import { formatDateTime } from "@/lib/date";
import { readableWarning } from "@/lib/researchReading";
import type { MarketAgentRegimeSummary, MarketMonitorMockFile, MarketRegimeKey } from "@/types/market-monitor";
export {
  KnowledgeTagsSection,
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
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) return null;
  const value = confidence;
  return value <= 1 ? Math.round(value * 100) : Math.round(value);
}

function formatRegimeDescription(description: string) {
  return AGENT_REGIME_LABELS[description] ?? readableWarning(description);
}

function compactRegimeLabel(
  agentMarketRegime: MarketAgentRegimeSummary | null | undefined,
  fallbackLabel: string,
) {
  const mapped = agentMarketRegime?.regime ? AGENT_REGIME_LABELS[agentMarketRegime.regime] : undefined;
  if (mapped) return mapped;

  const rawLabel = agentMarketRegime?.regimeLabel?.trim();
  if (rawLabel && /[\u3400-\u9fff]/.test(rawLabel)) return rawLabel;
  if (agentMarketRegime) return "历史阶段未提供";
  return fallbackLabel;
}

export function MarketDiagnosisSection({
  marketRegimes,
  agentMarketRegime,
  currentRegimeAvailable = false,
}: {
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime?: MarketAgentRegimeSummary | null;
  currentRegimeAvailable?: boolean;
}) {
  const activeRegime = currentRegimeAvailable ? REGIME_ORDER.find((key) => marketRegimes?.[key]?.status === "ok" || marketRegimes?.[key]?.status === "warn") : undefined;
  const fallbackLabel = activeRegime ? REGIME_DISPLAY_LABELS[activeRegime] : "阶段待确认";
  const regimeLabel = compactRegimeLabel(agentMarketRegime, fallbackLabel);
  const activeConfidence = formatConfidence(agentMarketRegime ? agentMarketRegime.confidence : activeRegime ? marketRegimes?.[activeRegime]?.confidence : null);
  const summary = agentMarketRegime ? agentMarketRegime.summary || agentMarketRegime.regimeLabel : activeRegime ? marketRegimes?.[activeRegime]?.interpretation : "";
  const keyDrivers = agentMarketRegime?.keyDrivers?.filter(Boolean) ?? [];

  return (
    <div className="market-monitor-right-section">
      <ContextPanelSectionHeader
        icon={Activity}
        title="市场诊断"
        meta={agentMarketRegime ? "历史分析参考" : currentRegimeAvailable ? "当前阶段" : "当前阶段未核验"}
        iconColor="var(--brand-hover)"
        className="market-monitor-right-section-header"
      />
      <div className="market-monitor-right-diagnosis-card">
        <div className="market-monitor-right-diagnosis-top">
          <span className="market-monitor-right-regime-badge min-w-0 max-w-full !whitespace-normal break-words">
            {regimeLabel}
          </span>
          <span className="market-monitor-right-confidence-pill">
            {activeConfidence === null ? "未量化" : `${activeConfidence}/100`}
          </span>
        </div>
        <div className="market-monitor-right-confidence-track" aria-hidden="true">
          <span style={{ width: `${activeConfidence === null ? 0 : Math.max(0, Math.min(100, activeConfidence))}%` }} />
        </div>
        {summary ? (
          <div className="market-monitor-right-diagnosis-summary">
            {readableWarning(summary)}
          </div>
        ) : null}
        {agentMarketRegime ? (
          <div className="fa-faint-text mt-1.5 text-[length:var(--type-caption)]">
            历史模型摘要 · 置信度评分非概率 · 生成于 {agentMarketRegime.createdAt ? formatDateTime(agentMarketRegime.createdAt) : "未知"}
          </div>
        ) : null}
        {keyDrivers.length > 0 ? (
          <div className="market-monitor-right-driver-list">
            {keyDrivers.map((driver) => (
              <span key={driver} className="market-monitor-right-driver-chip">
                {AGENT_REGIME_LABELS[driver] ?? readableWarning(driver)}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="market-monitor-right-regime-list">
        <p className="fa-faint-text">{currentRegimeAvailable ? "后端阶段置信度，非胜率。" : "当前阶段未核验；以下阶段评分不用于当前判断。"}</p>
        {REGIME_ORDER.map((key) => {
          const item = marketRegimes?.[key];
          if (!item) return null;
          const color = REGIME_COLORS[key];
          const usable = currentRegimeAvailable && (item.status === "ok" || item.status === "warn" || item.status === "info");
          const confidence = usable ? formatConfidence(item.confidence) : null;

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
                  {!usable ? "未核验" : confidence === null ? "未量化" : `${confidence}%`}
                </span>
              </div>
              <div className="market-monitor-right-regime-description">
                {usable ? formatRegimeDescription(item.description) : "后端未确认此阶段可用"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
