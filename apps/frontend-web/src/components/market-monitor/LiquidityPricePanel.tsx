import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { findMetric, formatMetricChange, formatMetricValue, marketMonitorMetricLabel, marketMonitorStatusLabel, marketMonitorUnitLabel } from "./format";

export interface LiquidityPricePanelProps {
  metrics: MarketMonitorMetric[];
}

const TARGET_KEYS = ["TGA", "RRP", "SOFR", "EFFR", "IORB"] as const;

export function LiquidityPricePanel({ metrics = [] }: LiquidityPricePanelProps) {
  return (
    <FACard
      title="跨资产联动表"
      eyebrow="跨资产读数"
      accent="info"
      bodyClassName="p-0"
    >
      <table className="fa-table">
        <thead>
          <tr>
            <th>指标</th>
            <th>最新值</th>
            <th>周变化</th>
            <th>月变化</th>
            <th>状态</th>
            <th>解释</th>
          </tr>
        </thead>
        <tbody>
          {TARGET_KEYS.map((key) => {
            const metric = findMetric(metrics, key);

            return (
              <tr key={key}>
                <td>
                  <div className="flex flex-col gap-0.5">
                    <span className="font-semibold text-[var(--fg-2)]">{marketMonitorMetricLabel(key, metric?.label)}</span>
                    <span className="font-mono text-[10px] text-[var(--fg-5)]">{metric?.latest_date ?? "未提供"}</span>
                  </div>
                </td>
                <td className="font-mono text-[var(--fg-2)]">
                  {metric ? formatMetricValue(metric.latest_value, 4) : "—"}
                  {metric?.unit ? <span className="ml-1 text-[10px] text-[var(--fg-5)]">{marketMonitorUnitLabel(metric.unit)}</span> : null}
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
                    {marketMonitorStatusLabel(metric?.status)}
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
