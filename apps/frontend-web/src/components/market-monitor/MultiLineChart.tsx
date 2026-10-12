import type { MarketMonitorMetric } from "@/types/market-monitor";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import { TradingViewChart } from "@/components/charts/TradingViewChart";
import { ChartReadingGuide } from "@/components/shared/ChartReadingGuide";
import { MultiLineChartLegend } from "./MultiLineChartLegend";
import { HistoryObservationPanel } from "./HistoryObservationPanel";

interface MultiLineChartProps {
  metrics: MarketMonitorMetric[];
  history?: MarketMonitorHistoryResponse | null;
  className?: string;
  activeTimeframe?: MarketMonitorHistoryTimeframe;
  onTimeframeChange?: (value: MarketMonitorHistoryTimeframe) => void;
}

export function MultiLineChart({ metrics, history, className = "", activeTimeframe = "1D", onTimeframeChange }: MultiLineChartProps) {
  return <div className={className}><div className="market-monitor-chart-shell">
    <TradingViewChart />
    <ChartReadingGuide
      className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] text-[var(--fg-3)]"
      question="现货黄金（XAUUSD）的价格结构与所选周期。"
      reference="主图由 TradingView 提供；下方为系统历史指标。"
      interpretation="高低点只描述外部图表中的价格路径，不单独构成策略触发。"
      limits={["图表与报告可能采用不同数据时点，请以报告标注为准。"]}
    />
    <MultiLineChartLegend metrics={metrics} seriesData={[]} statusText="最新指标观测，与历史序列分别读取" />
    <HistoryObservationPanel history={history} metrics={metrics} timeframe={activeTimeframe} onTimeframeChange={onTimeframeChange} />
  </div></div>;
}

export default MultiLineChart;
