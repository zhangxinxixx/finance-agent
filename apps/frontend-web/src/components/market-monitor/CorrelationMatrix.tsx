import { useMemo } from "react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { FACard } from "@/components/shared/FACard";
import { findMetric, formatMetricValue } from "./format";

interface CorrelationMatrixProps {
  metrics: MarketMonitorMetric[];
}

const ASSET_KEYS = ["XAUUSD", "DXY", "US10Y", "REAL_10Y", "T10YIE", "TGA"] as const;

function toNumeric(value: string | number | null | undefined): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value.replace(/[%+,]/g, ""));
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function metricSignal(metric: MarketMonitorMetric | undefined): number {
  if (!metric) return 0;
  const week = toNumeric(metric.one_week_change);
  const month = toNumeric(metric.one_month_change);
  return week * 0.7 + month * 0.3;
}

function pairCorrelation(a: MarketMonitorMetric | undefined, b: MarketMonitorMetric | undefined): number {
  if (!a || !b) return 0;
  const weekA = toNumeric(a.one_week_change);
  const weekB = toNumeric(b.one_week_change);
  const monthA = toNumeric(a.one_month_change);
  const monthB = toNumeric(b.one_month_change);
  const directional = weekA === 0 || weekB === 0 ? 0 : Math.sign(weekA) === Math.sign(weekB) ? 0.55 : -0.55;
  const monthDirectional = monthA === 0 || monthB === 0 ? 0 : Math.sign(monthA) === Math.sign(monthB) ? 0.25 : -0.25;
  const magnitudePenalty = Math.min(Math.abs(Math.abs(weekA) - Math.abs(weekB)) / 10, 0.2);
  return Math.max(-1, Math.min(1, Number((directional + monthDirectional - magnitudePenalty).toFixed(2))));
}

function correlationColor(value: number): string {
  if (value > 0.3) return "var(--up)";
  if (value < -0.3) return "var(--down)";
  return "var(--fg-4)";
}

function correlationBg(value: number): string {
  const abs = Math.abs(value);
  if (value > 0) return `rgba(16, 185, 129, ${abs * 0.2})`;
  if (value < 0) return `rgba(240, 82, 82, ${abs * 0.2})`;
  return "transparent";
}

export function CorrelationMatrix({ metrics }: CorrelationMatrixProps) {
  const rows = useMemo(() => {
    return ASSET_KEYS.map((rowKey) => {
      const rowMetric = findMetric(metrics, rowKey);
      return {
        key: rowKey,
        label: rowMetric?.label ?? rowKey,
        latest: rowMetric ? formatMetricValue(rowMetric.latest_value, 4) : "—",
        signal: metricSignal(rowMetric),
        values: ASSET_KEYS.map((colKey) => {
          if (rowKey === colKey) return 1;
          return pairCorrelation(rowMetric, findMetric(metrics, colKey));
        }),
      };
    });
  }, [metrics]);

  return (
    <FACard title="跨资产联动表" eyebrow="Cross-Asset Matrix" accent="info" bodyClassName="p-0 overflow-x-auto">
      <table className="fa-table">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--bg-panel)]">Asset</th>
            {ASSET_KEYS.map((key) => (
              <th key={key} className="text-center font-mono">
                {key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td className="sticky left-0 z-10 bg-[var(--bg-card)]">
                <div className="flex flex-col">
                  <span className="font-semibold text-[var(--fg-2)]">{row.label}</span>
                  <span className="font-mono text-[10px] text-[var(--fg-5)]">{row.latest} / {row.signal.toFixed(2)}</span>
                </div>
              </td>
              {row.values.map((val, i) => (
                <td
                  key={ASSET_KEYS[i]}
                  className="text-center font-mono text-[10px]"
                  style={{
                    color: correlationColor(val),
                    backgroundColor: correlationBg(val),
                  }}
                >
                  {val === 1 ? "1.00" : val.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </FACard>
  );
}

export default CorrelationMatrix;
