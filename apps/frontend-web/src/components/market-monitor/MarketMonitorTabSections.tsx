import { Activity, Layers3 } from "lucide-react";
import { AssetTable } from "@/components/market-monitor/AssetTable";
import { CorrelationMatrix } from "@/components/market-monitor/CorrelationMatrix";
import { EnvironmentFilterPanel } from "@/components/market-monitor/EnvironmentFilterPanel";
import { Heatmap } from "@/components/market-monitor/Heatmap";
import { MarketPriceCards } from "@/components/market-monitor/MarketPriceCards";
import { MarketRegimePanel } from "@/components/market-monitor/MarketRegimePanel";
import { FactorPanel } from "@/components/market-monitor/FactorPanel";
import { MultiLineChart } from "@/components/market-monitor/MultiLineChart";
import {
  CalendarEventBrief,
  OverviewEntryGrid,
  OverviewHero,
} from "@/components/market-monitor/MarketMonitorOverviewBlocks";
import { RightPanel } from "@/components/market-monitor/RightPanel";
import { SourceTracePanel } from "@/components/market-monitor/SourceTracePanel";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import type { MarketMonitorMetric, MarketMonitorMockFile, MarketMonitorSourceTraceItem } from "@/types/market-monitor";
import type { MarketMonitorTab } from "./MarketMonitorHeaderSections";

export function MarketMonitorOverviewSection({
  metrics,
  history,
  activeTimeframe,
  onTimeframeChange,
  marketRegimes,
  agentMarketRegime,
  overviewTitle,
  sourceLabel,
  latestDate,
  overviewSummary,
  historySummary,
  realtimeRegime,
  primaryDriver,
}: {
  metrics: MarketMonitorMetric[];
  history: MarketMonitorHistoryResponse | null;
  activeTimeframe: MarketMonitorHistoryTimeframe;
  onTimeframeChange: (timeframe: MarketMonitorHistoryTimeframe) => void;
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime: MarketMonitorMockFile["agent_market_regime"] | null | undefined;
  overviewTitle: string;
  sourceLabel: string;
  latestDate: string;
  overviewSummary: string;
  historySummary: string | null;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
}) {
  return (
    <>
      <OverviewHero
        title={overviewTitle}
        meta={`source ${sourceLabel} · latest ${latestDate}`}
        summary={overviewSummary}
      />
      <MarketPriceCards metrics={metrics} />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.9fr) minmax(300px,0.95fr)", gap: 10 }}>
        <MultiLineChart
          metrics={metrics}
          history={history}
        />
        <RightPanel
          marketRegimes={marketRegimes}
          agentMarketRegime={agentMarketRegime}
        />
      </div>
      <OverviewEntryGrid
        latestDate={latestDate}
        historySummary={historySummary}
        sourceLabel={sourceLabel}
        realtimeRegime={realtimeRegime}
        primaryDriver={primaryDriver}
      />
    </>
  );
}

export function MarketMonitorPricingChainSection({
  metrics,
  history,
  marketRegimes,
  environmentFilters,
}: {
  metrics: MarketMonitorMetric[];
  history: MarketMonitorHistoryResponse | null;
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  environmentFilters: MarketMonitorMockFile["environment_filters"];
}) {
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "2px 2px 0",
        }}
      >
        <div className="flex items-center gap-2">
          <Activity size={12} className="text-[var(--brand-hover)]" />
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">黄金定价链</div>
        </div>
        <div className="text-[10px] text-[var(--fg-5)]">
          XAUUSD / DXY / US10Y / REAL_10Y / T10YIE · Jin10 实时
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.9fr) minmax(300px,0.95fr)", gap: 10 }}>
        <MultiLineChart
          metrics={metrics}
          history={history}
        />
        <FactorPanel />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 10 }}>
        <MarketRegimePanel marketRegimes={marketRegimes} />
        <EnvironmentFilterPanel environmentFilters={environmentFilters} />
      </div>
    </>
  );
}

export function MarketMonitorCrossAssetSection({ metrics }: { metrics: MarketMonitorMetric[] }) {
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "2px 2px 0",
        }}
      >
        <div className="flex items-center gap-2">
          <Layers3 size={12} className="text-[var(--brand-hover)]" />
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">跨资产观察</div>
        </div>
        <div className="text-[10px] text-[var(--fg-5)]">资产分组、热力图与联动矩阵</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.7fr) minmax(280px,0.95fr)", gap: 10 }}>
        <AssetTable metrics={metrics} />
        <Heatmap metrics={metrics} />
      </div>
      <CorrelationMatrix metrics={metrics} />
    </>
  );
}

export function MarketMonitorCalendarSection({
  sourceLabel,
  latestDate,
  historySummary,
  realtimeRegime,
  primaryDriver,
  sourceTrace,
  marketRegimes,
  agentMarketRegime,
}: {
  sourceLabel: string;
  latestDate: string;
  historySummary: string | null;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
  sourceTrace: MarketMonitorSourceTraceItem[];
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime: MarketMonitorMockFile["agent_market_regime"] | null | undefined;
}) {
  return (
    <>
      <CalendarEventBrief
        sourceLabel={sourceLabel}
        latestDate={latestDate}
        historySummary={historySummary}
        realtimeRegime={realtimeRegime}
        primaryDriver={primaryDriver}
        sourceTraceCount={sourceTrace.length}
      />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.1fr) minmax(0,0.9fr)", gap: 10 }}>
        <RightPanel
          marketRegimes={marketRegimes}
          agentMarketRegime={agentMarketRegime}
        />
        <SourceTracePanel sourceTrace={sourceTrace} />
      </div>
    </>
  );
}

export type { MarketMonitorTab };
