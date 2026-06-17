import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { findMetric, formatMetricChange, formatMetricValue } from "./format";

export interface LiquidityPricePanelProps {
  metrics: MarketMonitorMetric[];
}

const TARGET_KEYS = ["TGA", "RRP", "SOFR", "EFFR", "IORB"] as const;

export function LiquidityPricePanel({ metrics = [] }: LiquidityPricePanelProps) {
  return (
    <FACard
      title="跨资产联动表"
      eyebrow="Cross-Asset Matrix"
      accent="info"
      bodyClassName="p-0"
    >
      <table className="fa-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Latest</th>
            <th>1W</th>
            <th>1M</th>
            <th>Status</th>
            <th>Impact</th>
          </tr>
        </thead>
        <tbody>
          {TARGET_KEYS.map((key) => {
            const metric = findMetric(metrics, key);

            return (
              <tr key={key}>
                <td>
                  <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-[var(--fg-2)]">{metric?.label ?? key}</span>
                    <span className="font-mono text-[10px] text-[var(--fg-5)]">{metric?.latest_date ?? "unavailable"}</span>
                  </div>
                </td>
                <td className="font-mono text-[var(--fg-2)]">
                  {metric ? formatMetricValue(metric.latest_value, 4) : "—"}
                  {metric?.unit ? <span className="ml-1 text-[10px] text-[var(--fg-5)]">{metric.unit}</span> : null}
                </td>
                <td className="font-mono">{metric ? formatMetricChange(metric.one_week_change) : "—"}</td>
                <td className="font-mono">{metric ? formatMetricChange(metric.one_month_change) : "—"}</td>
                <td>
                  <FAStatusPill
                    tone={
                      metric?.status === "ok"
                        ? "up"
                        : metric?.status === "warn"
                          ? "warn"
                          : metric?.status === "error"
                            ? "down"
                            : "neutral"
                    }
                  >
                    {metric?.status ?? "unavailable"}
                  </FAStatusPill>
                </td>
                <td className="max-w-[18rem]">
                  <span className="line-clamp-2 text-[10px] leading-5 text-[var(--fg-4)]">
                    {metric?.interpretation?.trim() || "当前快照未提供读数说明。"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </FACard>
  );
}

export default LiquidityPricePanel;
