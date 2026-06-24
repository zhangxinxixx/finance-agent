import type { MarketMonitorMetric } from "@/types/market-monitor";
import { findMetric, formatMetricChange } from "./format";
import { getImpactBg, getImpactBorder, getImpactColor, type HeatmapCell as HeatmapCellModel } from "./heatmapModel";

interface HeatmapCellProps {
  cell: HeatmapCellModel;
  metrics: MarketMonitorMetric[];
}

export function HeatmapCell({ cell, metrics }: HeatmapCellProps) {
  const lookupKey = cell.key === "VIX_FULL" ? "VIX" : cell.key;
  const metric = findMetric(metrics, lookupKey);
  const changeVal = metric?.one_week_change ?? null;
  const changeText = formatMetricChange(changeVal, "---");

  return (
    <div
      style={{
        borderRadius: 5,
        padding: "8px 10px",
        background: getImpactBg(changeVal),
        border: getImpactBorder(changeVal),
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
    >
      <div className="flex items-center justify-between">
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontWeight: 500,
            fontSize: 10.5,
            lineHeight: 1,
            color: "var(--fg-2)",
          }}
        >
          {cell.name}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontWeight: 500,
            fontSize: 8,
            lineHeight: 1,
            color: "var(--fg-5)",
          }}
        >
          {cell.symbol}
        </span>
      </div>
      <span
        className="fa-num"
        style={{
          fontSize: 15,
          fontWeight: 700,
          lineHeight: 1,
          letterSpacing: "-0.02em",
          color: getImpactColor(changeVal),
        }}
      >
        {changeText}
      </span>
    </div>
  );
}
