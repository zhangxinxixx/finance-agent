import { ContextPanelShell } from "@/components/shared/ContextPanel";
import type { MarketAgentRegimeSummary, MarketMonitorMockFile } from "@/types/market-monitor";
import {
  CalendarSection,
  EventDynamicsSection,
  MarketDiagnosisSection,
  ReportsKnowledgeSection,
} from "@/components/market-monitor/RightPanelSections";

interface RightPanelProps {
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime?: MarketAgentRegimeSummary | null;
}

export function RightPanel({ marketRegimes, agentMarketRegime }: RightPanelProps) {
  return (
    <ContextPanelShell padded={false} className="market-monitor-side-panel" style={{ background: "var(--bg-card)" }}>
      <MarketDiagnosisSection marketRegimes={marketRegimes} agentMarketRegime={agentMarketRegime} />
      <CalendarSection />
      <EventDynamicsSection />
      <ReportsKnowledgeSection />
    </ContextPanelShell>
  );
}

export default RightPanel;
