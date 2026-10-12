import { LineChart, Loader2, RefreshCw } from "lucide-react";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import { formatGoldDriverLabel } from "@/components/shared/goldMainlineFormat";
import type { MarketMonitorMockFile, MarketMonitorStatus } from "@/types/market-monitor";

type MarketMonitorTab = "overview" | "pricing-chain" | "cross-asset" | "calendar" | "odds";

export function MarketMonitorLoadingPanel() {
  return (
    <div className="market-monitor-loading-panel">
      <div className="market-monitor-loading-panel-head">
        <Loader2 className="market-monitor-loading-spinner" />
        <div>
          <div className="market-monitor-loading-title">正在加载市场监控数据</div>
          <div className="market-monitor-loading-summary">正在读取接口结果；若失败会明确显示数据不可用，不把模拟数据当作实时判断。</div>
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
  const realtimeRegimeItem = realtimeRegime
    ? {
      label: "实时阶段",
      value: realtimeRegime.available === true && realtimeRegime.regime
        ? `${formatRealtimeRegimeHeaderLabel(realtimeRegime.regime)} ${typeof realtimeRegime.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "置信度未量化"}`
        : "待确认",
      title: realtimeRegime.available === true
        ? "基于当前实时阶段结果"
        : "实时阶段数据不可用，未形成可确认的阶段判断",
    }
    : null;

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
        ...(realtimeRegimeItem ? [realtimeRegimeItem] : []),
      ]}
      secondaryLabel="摘要"
      secondaryItems={[
        ...(primaryDriver?.driver ? [{
          label: "主因",
          value: formatGoldDriverLabel(primaryDriver.driver === "data_insufficient" ? null : primaryDriver.driver),
          title: primaryDriver.driver === "data_insufficient" ? "主因待确认" : primaryDriver.driver,
        }] : []),
        ...(history ? [{ label: "历史", value: `${history.available_points}${history.degraded ? " 降级" : ""}` }] : []),
      ]}
    />
  );
}

function formatRealtimeRegimeHeaderLabel(value: string): string {
  const labels: Record<string, string> = {
    dovish_gold_friendly: "宽松、黄金偏友好",
    hawkish_gold_pressure: "鹰派、黄金承压",
    neutral_soft: "中性偏宽松",
    neutral_firm: "中性偏紧",
    neutral: "中性阶段",
  };
  return labels[value] ?? "阶段待确认";
}

export type { MarketMonitorTab, MarketMonitorStatus };
