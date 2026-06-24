import type { MarketMonitorMetric } from "@/types/market-monitor";
import { formatMetricChange, formatMetricValue } from "./format";
import { activeMetricSummary, CHART_SERIES, type ChartSeriesData } from "@/components/market-monitor/marketMonitorChart";

interface MultiLineChartLegendProps {
  metrics: MarketMonitorMetric[];
  seriesData: ChartSeriesData[];
  statusText: string;
}

export function MultiLineChartLegend({ metrics, seriesData, statusText }: MultiLineChartLegendProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: 16,
        flexWrap: "wrap",
        padding: "4px 12px 6px",
        fontFamily: "var(--font-sans)",
        fontWeight: 500,
        fontSize: 9,
        lineHeight: 1,
        color: "var(--fg-4)",
      }}
    >
      {seriesData.map((series) => (
        <div key={series.key} className="flex items-center gap-1.5">
          <span
            style={{
              width: 12,
              height: 2,
              background: series.color,
              borderRadius: 1,
              display: "inline-block",
              ...(series.dashed
                ? { background: `repeating-linear-gradient(90deg, ${series.color} 0 4px, transparent 4px 6.5px)` }
                : {}),
            }}
          />
          <span>{series.label}</span>
        </div>
      ))}
      <div className="flex items-center gap-1 text-[var(--fg-5)]">
        <span>{statusText}</span>
      </div>
      {CHART_SERIES.map((series) => {
        const metric = activeMetricSummary(metrics, series.key);
        return (
          <div key={`${series.key}-meta`} className="flex items-center gap-1 text-[var(--fg-5)]">
            <span>{series.label}</span>
            <span className="fa-num text-[var(--fg-3)]">{metric ? formatMetricValue(metric.latest_value, 2) : "—"}</span>
            <span>{metric?.unit ?? ""}</span>
            <span className="fa-num">{formatMetricChange(metric?.one_week_change ?? null, "—")}</span>
          </div>
        );
      })}
    </div>
  );
}
