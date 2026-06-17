import type { MarketMonitorMetric, MarketMonitorMetricGroup } from "@/types/market-monitor";
import { formatMetricChange, formatMetricValue } from "./format";
import { changeColor, interpretStatus } from "./assetTableFormat";

export interface AssetRow {
  key: string;
  symbol: string;
  name: string;
  group: MarketMonitorMetricGroup;
}

interface AssetTableRowProps {
  row: AssetRow;
  metric?: MarketMonitorMetric;
}

export function AssetTableRow({ row, metric }: AssetTableRowProps) {
  const price = metric ? formatMetricValue(metric.latest_value, 4) : "---";
  const changeVal = metric?.one_week_change ?? null;
  const delta = metric?.one_month_change ?? null;
  const impact = interpretStatus(metric);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "68px 1fr 72px 70px 50px 58px 1fr",
        padding: "5.5px 12px",
        borderBottom: "1px solid var(--border-faint)",
        alignItems: "center",
        minHeight: 28,
      }}
    >
      <span
        className="fa-num"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9.5,
          fontWeight: 700,
          color: "var(--fg-2)",
        }}
      >
        {row.symbol}
      </span>
      <span
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 10,
          color: "var(--fg-3)",
        }}
      >
        {row.name}
      </span>
      <span
        className="fa-num"
        style={{
          fontSize: 11,
          textAlign: "right",
          color: "var(--fg-1)",
        }}
      >
        {price}
      </span>
      <span
        className="fa-num"
        style={{
          fontSize: 10.5,
          fontWeight: 700,
          textAlign: "right",
          color: changeColor(changeVal),
        }}
      >
        {formatMetricChange(changeVal, "---")}
      </span>
      <span
        className="fa-num"
        style={{
          fontSize: 10,
          textAlign: "right",
          color: changeColor(delta),
        }}
      >
        {formatMetricChange(delta, "---")}
      </span>
      <span
        style={{
          fontSize: 9,
          textAlign: "right",
          color: impact === "正常" ? "var(--up)" : impact === "关注" ? "var(--warn)" : "var(--fg-5)",
        }}
      >
        {impact}
      </span>
      <span
        style={{
          fontSize: 9,
          color: "var(--fg-5)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {metric?.interpretation || ""}
      </span>
    </div>
  );
}
