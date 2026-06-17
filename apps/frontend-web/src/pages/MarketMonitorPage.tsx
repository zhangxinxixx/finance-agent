import { useMemo, useState } from "react";
import { MarketMonitorPageContent } from "@/components/market-monitor/MarketMonitorPageContent";
import {
  MarketMonitorPageChrome,
  MarketMonitorPageEmptyState,
  MarketMonitorPageErrorState,
  MarketMonitorPageLoadingState,
} from "@/components/market-monitor/MarketMonitorPageStates";
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

export function MarketMonitorPage() {
  const { data, history, historyTimeframe, setHistoryTimeframe, isLoading, isError, error, refetch } = useMarketMonitor();
  const [activeTab, setActiveTab] = useState<MarketMonitorTab>("overview");
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

  return (
    <div className="finance-page-shell">
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          minWidth: 0,
        }}
      >
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
              onTabChange={setActiveTab}
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
