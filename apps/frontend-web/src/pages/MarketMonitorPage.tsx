import { readableWarning } from "@/lib/researchReading";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { MarketMonitorPageContent } from "@/components/market-monitor/MarketMonitorPageContent";
import {
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
import { marketMonitorSourceLabel, textOrDash } from "@/components/market-monitor/format";
import { formatDateTime } from "@/lib/date";

const MARKET_MONITOR_TABS: MarketMonitorTab[] = ["overview", "pricing-chain", "cross-asset", "calendar"];

function parseMarketMonitorTab(value: string | null): MarketMonitorTab {
  return value && MARKET_MONITOR_TABS.includes(value as MarketMonitorTab)
    ? (value as MarketMonitorTab)
    : "overview";
}

export function MarketMonitorPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = parseMarketMonitorTab(searchParams.get("tab"));
  const {
    data,
    history,
    historyTimeframe,
    setHistoryTimeframe,
    isLoading,
    isRefreshing,
    isError,
    error,
    historyError,
    refetch,
  } = useMarketMonitor();
  const calendar = useJin10Calendar();
  const [activeTab, setActiveTab] = useState<MarketMonitorTab>(requestedTab);
  const snapshot = (data ?? {}) as MarketMonitorShape;
  const metrics = Array.isArray(snapshot.metrics) ? snapshot.metrics : [];
  const marketRegimes = (snapshot.market_regimes ?? {}) as MarketMonitorMockFile["market_regimes"];
  const sourceTrace = Array.isArray(snapshot.source_trace) ? snapshot.source_trace : [];
  const realtimeRegime = snapshot.realtime_regime;
  const primaryDriver = snapshot.primary_driver;
  const agentMarketRegime = snapshot.agent_market_regime ?? null;
  const hasMetrics = isNonEmptyArray(metrics);
  const hasRenderableSnapshot =
    hasMetrics
    || Boolean(history)
    || sourceTrace.length > 0
    || Boolean(agentMarketRegime)
    || Boolean(realtimeRegime)
    || Boolean(primaryDriver);
  const isCalendarTab = activeTab === "calendar";
  const isEmpty = !data || (!hasRenderableSnapshot && !isCalendarTab);
  const sourceLabel = marketMonitorSourceLabel(snapshot.source);
  const pageStatus = isError ? "error" : isLoading ? "info" : isEmpty ? "unavailable" : diagnosisStatus(metrics);
  const pageStatusText = diagnosisText(pageStatus);
  const pageStatusLabel = isRefreshing ? `上次读取：${pageStatusText}` : pageStatusText;
  const overviewSummaryBase = agentMarketRegime?.summary
    ? `历史模型摘要 · 生成于 ${agentMarketRegime.createdAt ? formatDateTime(agentMarketRegime.createdAt) : "时间未知"}：${readableWarning(agentMarketRegime.summary)}`
    : `${diagnosisText(pageStatus)}。部分指标尚无可用的研究解释，影响仍待确认。`;
  const overviewSummary = isRefreshing
    ? `上次读取结果：${overviewSummaryBase} 当前刷新尚未完成，暂不能视为最新判断。`
    : overviewSummaryBase;
  const tabOptions = useMemo(() => buildMarketMonitorTabOptions(), []);

  useEffect(() => {
    setActiveTab((current) => (current === requestedTab ? current : requestedTab));
  }, [requestedTab]);

  function handleTabChange(nextTab: MarketMonitorTab) {
    if (nextTab === "odds") {
      navigate("/market-monitor/odds");
      return;
    }
    setActiveTab(nextTab);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (nextTab === "overview") next.delete("tab");
      else next.set("tab", nextTab);
      return next;
    }, { replace: true });
  }

  const hasExistingResult = Boolean(data || history);

  if (isLoading && !hasExistingResult) {
    return <MarketMonitorPageLoadingState />;
  }

  if (isError && !hasExistingResult) {
    return <MarketMonitorPageErrorState message={error?.message ?? "未知错误"} onRetry={refetch} />;
  }

  if (isEmpty) {
    return <MarketMonitorPageEmptyState />;
  }

  return (
    <MarketMonitorPageContent
      activeTab={activeTab}
      onTabChange={handleTabChange}
      tabOptions={tabOptions}
      pageStatusLabel={pageStatusLabel}
      sourceLabel={sourceLabel}
      errorReason={snapshot.error_reason}
      source={snapshot.source}
      snapshot={snapshot}
      metrics={metrics}
      marketRegimes={marketRegimes}
      sourceTrace={sourceTrace}
      overviewSummary={overviewSummary}
      calendarEvents={calendar.data}
      calendarGeneratedAt={calendar.generatedAt}
      calendarStatus={calendar.status}
      calendarStats={calendar.stats}
      calendarFreshness={calendar.freshness}
      calendarIsLoading={calendar.isLoading}
      calendarIsError={calendar.isError}
      requestError={error?.message ?? null}
      historyError={historyError?.message ?? null}
      isRefreshing={isRefreshing}
      realtimeRegime={realtimeRegime}
      primaryDriver={primaryDriver}
      agentMarketRegime={agentMarketRegime}
      history={history}
      historyTimeframe={historyTimeframe}
      setHistoryTimeframe={setHistoryTimeframe}
      onRefresh={refetch}
    />
  );
}

export default MarketMonitorPage;
