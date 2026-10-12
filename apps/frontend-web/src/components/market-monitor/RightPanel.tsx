import { ContextPanelShell } from "@/components/shared/ContextPanel";
import type { MarketAgentRegimeSummary, MarketMonitorMockFile } from "@/types/market-monitor";
import {
  MarketDiagnosisSection,
  ReportsKnowledgeSection,
} from "@/components/market-monitor/RightPanelSections";

interface RightPanelProps {
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime?: MarketAgentRegimeSummary | null;
  currentRegimeAvailable?: boolean;
}

export function RightPanel({ marketRegimes, agentMarketRegime, currentRegimeAvailable = false }: RightPanelProps) {
  return (
    <ContextPanelShell padded={false} className="market-monitor-side-panel">
      <MarketDiagnosisSection marketRegimes={marketRegimes} agentMarketRegime={agentMarketRegime} currentRegimeAvailable={currentRegimeAvailable} />
      <ReportsKnowledgeSection />
    </ContextPanelShell>
  );
}

export default RightPanel;
