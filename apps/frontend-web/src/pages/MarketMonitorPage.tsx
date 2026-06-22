import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MarketMonitorPageContent } from "@/components/market-monitor/MarketMonitorPageContent";
import {
  MarketMonitorPageChrome,
  MarketMonitorPageEmptyState,
  MarketMonitorPageErrorState,
  MarketMonitorPageLoadingState,
} from "@/components/market-monitor/MarketMonitorPageStates";
import { useJin10Calendar } from "@/hooks/useJin10Calendar";
import { useMarketMonitor } from "@/hooks/useMarketMonitor";
import type {
  MarketMonitorMetric,
  MarketMonitorMockFile,
  MarketMonitorSourceTraceItem,
} from "@/types/market-monitor";
import {
  buildMarketMonitorTabOptions,
  diagnosisStatus,
  diagnosisText,
  isNonEmptyArray,
  type MarketMonitorShape,
  type MarketMonitorTab,
} from "@/components/market-monitor/marketMonitorPageModel";
import { textOrDash } from "@/components/market-monitor/format";

const MARKET_MONITOR_TABS: MarketMonitorTab[] = ["overview", "pricing-chain", "cross-asset", "calendar"];

function parseMarketMonitorTab(value: string | null): MarketMonitorTab {
  return value && MARKET_MONITOR_TABS.includes(value as MarketMonitorTab)
    ? (value as MarketMonitorTab)
    : "overview";
}

export function MarketMonitorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = parseMarketMonitorTab(searchParams.get("tab"));
  const { data, history, historyTimeframe, setHistoryTimeframe, isLoading, isError, error, refetch } = useMarketMonitor();
  const calendar = useJin10Calendar();
  const [activeTab, setActiveTab] = useState<MarketMonitorTab>(requestedTab);
  const snapshot = (data ?? {}) as MarketMonitorShape;
  const metrics = Array.isArray(snapshot.metrics) ? snapshot.metrics : [];
  const marketRegimes = (snapshot.market_regimes ?? {}) as MarketMonitorMockFile["market_regimes"];
  const environmentFilters = (snapshot.environment_filters ?? {}) as MarketMonitorMockFile["environment_filters"];
  const sourceTrace = Array.isArray(snapshot.source_trace) ? snapshot.source_trace : [];
  const realtimeRegime = snapshot.realtime_regime;
  const primaryDriver = snapshot.primary_driver;
  const agentMarketRegime = snapshot.agent_market_regime ?? null;
  const hasData = Boolean(snapshot.has_data);
  const isEmpty = !data || !hasData || !isNonEmptyArray(metrics);
  const sourceLabel = textOrDash(snapshot.source ?? "mock");
  const historySummary = history
    ? `${history.available_points} pts / ${history.source_timeframe ?? "unknown"}${history.degraded ? " degraded" : ""}`
    : null;
  const pageStatus = isError ? "error" : isLoading ? "info" : isEmpty ? "unavailable" : diagnosisStatus(metrics);
  const overviewSummary = agentMarketRegime?.summary
    ?? `${diagnosisText(pageStatus)}。主页面只保留黄金核心定价链、市场阶段和关键过滤器，详细联动拆到下方分区。`;
  const tabOptions = useMemo(() => buildMarketMonitorTabOptions(), []);

  useEffect(() => {
    setActiveTab((current) => (current === requestedTab ? current : requestedTab));
  }, [requestedTab]);

  function handleTabChange(nextTab: MarketMonitorTab) {
    setActiveTab(nextTab);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (nextTab === "overview") next.delete("tab");
      else next.set("tab", nextTab);
      return next;
    }, { replace: true });
  }

  return (
    <div className="finance-page-shell">
      <div className="fa-layout-fill overflow-y-auto">
        {isLoading ? (
          <MarketMonitorPageLoadingState />
        ) : isError ? (
          <MarketMonitorPageErrorState message={error?.message ?? "未知错误"} onRetry={refetch} />
        ) : isEmpty ? (
          <MarketMonitorPageEmptyState />
        ) : (
          <>
            <MarketMonitorPageChrome errorReason={snapshot.error_reason} source={snapshot.source} />
            <MarketMonitorPageContent
              activeTab={activeTab}
              onTabChange={handleTabChange}
              tabOptions={tabOptions}
              pageStatusLabel={diagnosisText(pageStatus)}
              sourceLabel={sourceLabel}
              snapshot={snapshot}
              metrics={metrics}
              marketRegimes={marketRegimes}
              environmentFilters={environmentFilters}
              sourceTrace={sourceTrace}
              overviewSummary={overviewSummary}
              historySummary={historySummary}
              calendarEvents={calendar.data}
              calendarGeneratedAt={calendar.generatedAt}
              calendarStatus={calendar.status}
              calendarStats={calendar.stats}
              calendarFreshness={calendar.freshness}
              calendarIsLoading={calendar.isLoading}
              calendarIsError={calendar.isError}
              realtimeRegime={realtimeRegime}
              primaryDriver={primaryDriver}
              agentMarketRegime={agentMarketRegime}
              history={history}
              historyTimeframe={historyTimeframe}
              setHistoryTimeframe={setHistoryTimeframe}
            />
          </>
        )}
      </div>
    </div>
  );
}

export default MarketMonitorPage;
