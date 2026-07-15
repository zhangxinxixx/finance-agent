import { LineChart, Loader2, RefreshCw } from "lucide-react";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import type { MarketMonitorMockFile, MarketMonitorStatus } from "@/types/market-monitor";

type MarketMonitorTab = "overview" | "pricing-chain" | "cross-asset" | "calendar" | "odds";

export function MarketMonitorLoadingPanel() {
  return (
    <div className="market-monitor-loading-panel">
      <div className="market-monitor-loading-panel-head">
        <Loader2 className="market-monitor-loading-spinner" />
        <div>
          <div className="market-monitor-loading-title">正在加载市场监控数据</div>
          <div className="market-monitor-loading-summary">优先请求 API，失败后回退到 mock / unavailable 外壳。</div>
        </div>
      </div>
      <div className="market-monitor-loading-grid">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={`loading-card-${index}`} className="market-monitor-loading-card animate-pulse" />
        ))}
      </div>
    </div>
  );
}

export function MarketMonitorPageHeader({
  pageStatusLabel,
  sourceLabel,
  latestDate,
  realtimeRegime,
  primaryDriver,
  history,
  activeTab,
  tabOptions,
  onTabChange,
  onRefresh,
}: {
  pageStatusLabel: string;
  sourceLabel: string;
  latestDate: string;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
  history: MarketMonitorHistoryResponse | null;
  activeTab: MarketMonitorTab;
  tabOptions: Array<{ value: MarketMonitorTab; label: string }>;
  onTabChange: (value: MarketMonitorTab) => void;
  onRefresh: () => void;
}) {
  return (
    <FAWorkspaceHeader
      className="market-monitor-workspace-header"
      icon={LineChart}
      title="市场监控"
      value={activeTab}
      onChange={onTabChange}
      ariaLabel="市场监控视图切换"
      tabs={tabOptions}
      actions={(
        <button type="button" onClick={onRefresh} className="fa-workspace-toolbar-button">
          <RefreshCw size={12} />
          刷新
        </button>
      )}
      primaryLabel="市场状态"
      primaryItems={[
        { label: "阶段", value: pageStatusLabel },
        { label: "来源", value: sourceLabel },
        { label: "日期", value: latestDate },
        ...(realtimeRegime?.regime ? [{ label: "实时", value: `${realtimeRegime.regime} ${(realtimeRegime.confidence * 100).toFixed(0)}%` }] : []),
      ]}
      secondaryLabel="摘要"
      secondaryItems={[
        ...(primaryDriver?.driver ? [{ label: "主因", value: primaryDriver.driver, title: primaryDriver.driver }] : []),
        ...(history ? [{ label: "历史", value: `${history.available_points}${history.degraded ? " 降级" : ""}` }] : []),
      ]}
    />
  );
}

export type { MarketMonitorTab, MarketMonitorStatus };
