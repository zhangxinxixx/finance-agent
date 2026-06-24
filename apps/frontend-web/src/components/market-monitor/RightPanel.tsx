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
    <ContextPanelShell padded={false} style={{ minWidth: 0, alignSelf: "start" }}>
      <MarketDiagnosisSection marketRegimes={marketRegimes} agentMarketRegime={agentMarketRegime} />
      <CalendarSection />
      <EventDynamicsSection />
      <ReportsKnowledgeSection />
    </ContextPanelShell>
  );
}

export default RightPanel;
