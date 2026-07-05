import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import {
  MarketMonitorCalendarSection,
  MarketMonitorCrossAssetSection,
  MarketMonitorOverviewSection,
  MarketMonitorPageHeader,
  MarketMonitorPricingChainSection,
} from "@/components/market-monitor/MarketMonitorSections";
import { textOrDash } from "@/components/market-monitor/format";
import type { Jin10CalendarEvent, Jin10CalendarFreshness, Jin10CalendarStats } from "@/hooks/useJin10Calendar";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { MarketMonitorPageChrome } from "@/components/market-monitor/MarketMonitorPageStates";
import type { MarketMonitorMockFile, MarketMonitorSourceTraceItem } from "@/types/market-monitor";
import type { MarketMonitorShape, MarketMonitorTab } from "./marketMonitorPageModel";

interface MarketMonitorPageContentProps {
  activeTab: MarketMonitorTab;
  onTabChange: (tab: MarketMonitorTab) => void;
  tabOptions: Array<{ value: MarketMonitorTab; label: string }>;
  pageStatusLabel: string;
  sourceLabel: string;
  errorReason: string | null | undefined;
  source: string | null | undefined;
  snapshot: MarketMonitorShape;
  metrics: MarketMonitorShape["metrics"] extends infer T ? Extract<T, any[]> : never;
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  sourceTrace: MarketMonitorSourceTraceItem[];
  overviewSummary: string;
  calendarEvents: Jin10CalendarEvent[];
  calendarGeneratedAt: string | null;
  calendarStatus: string;
  calendarStats: Jin10CalendarStats | null;
  calendarFreshness: Jin10CalendarFreshness | null;
  calendarIsLoading: boolean;
  calendarIsError: boolean;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"];
  primaryDriver: MarketMonitorMockFile["primary_driver"];
  agentMarketRegime: MarketMonitorMockFile["agent_market_regime"] | null;
  history: MarketMonitorHistoryResponse | null;
  historyTimeframe: MarketMonitorHistoryTimeframe;
  setHistoryTimeframe: (timeframe: MarketMonitorHistoryTimeframe) => void;
  onRefresh: () => void;
}

export function MarketMonitorPageContent({
  activeTab,
  onTabChange,
  tabOptions,
  pageStatusLabel,
  sourceLabel,
  errorReason,
  source,
  snapshot,
  metrics,
  marketRegimes,
  sourceTrace,
  overviewSummary,
  calendarEvents,
  calendarGeneratedAt,
  calendarStatus,
  calendarStats,
  calendarFreshness,
  calendarIsLoading,
  calendarIsError,
  realtimeRegime,
  primaryDriver,
  agentMarketRegime,
  history,
  historyTimeframe,
  setHistoryTimeframe,
  onRefresh,
}: MarketMonitorPageContentProps) {
  return (
    <FAPageScaffold
      className="market-monitor-page-shell"
      toolbar={(
        <MarketMonitorPageHeader
          pageStatusLabel={pageStatusLabel}
          sourceLabel={sourceLabel}
          latestDate={textOrDash(snapshot.latest_date)}
          realtimeRegime={realtimeRegime}
          primaryDriver={primaryDriver}
          history={history}
          activeTab={activeTab}
          tabOptions={tabOptions}
          onTabChange={onTabChange}
          onRefresh={onRefresh}
        />
      )}
      bodyClassName="fa-page-stack"
    >
      <MarketMonitorPageChrome errorReason={errorReason} source={source} />

      {activeTab === "overview" ? (
        <MarketMonitorOverviewSection
          metrics={metrics}
          history={history}
          activeTimeframe={historyTimeframe}
          onTimeframeChange={setHistoryTimeframe}
          marketRegimes={marketRegimes}
          agentMarketRegime={agentMarketRegime}
          overviewTitle={pageStatusLabel}
          sourceLabel={sourceLabel}
          latestDate={textOrDash(snapshot.latest_date)}
          overviewSummary={overviewSummary}
        />
      ) : null}

      {activeTab === "pricing-chain" ? (
        <MarketMonitorPricingChainSection
          metrics={metrics}
          history={history}
        />
      ) : null}

      {activeTab === "cross-asset" ? <MarketMonitorCrossAssetSection metrics={metrics} /> : null}

      {activeTab === "calendar" ? (
        <MarketMonitorCalendarSection
          sourceLabel={sourceLabel}
          latestDate={textOrDash(snapshot.latest_date)}
          events={calendarEvents}
          generatedAt={calendarGeneratedAt}
          calendarStatus={calendarStatus}
          calendarStats={calendarStats}
          calendarFreshness={calendarFreshness}
          eventsIsLoading={calendarIsLoading}
          eventsIsError={calendarIsError}
          realtimeRegime={realtimeRegime}
          primaryDriver={primaryDriver}
          sourceTrace={sourceTrace}
          marketRegimes={marketRegimes}
          agentMarketRegime={agentMarketRegime}
        />
      ) : null}
    </FAPageScaffold>
  );
}
