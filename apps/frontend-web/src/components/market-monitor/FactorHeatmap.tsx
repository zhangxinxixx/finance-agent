import { Fragment, useMemo } from "react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { FACard } from "@/components/shared/FACard";
import { findMetric, formatMetricChange } from "./format";

interface FactorHeatmapProps {
  metrics: MarketMonitorMetric[];
}

const FACTOR_KEYS = ["XAUUSD", "DXY", "US10Y", "REAL_10Y", "T10YIE", "TGA"] as const;

function changeToNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const cleaned = value.replace(/[+%]/g, "").trim();
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function heatmapBg(value: number): string {
  if (value > 0) {
    const intensity = Math.min(Math.abs(value) / 5, 1);
    return `rgba(16, 185, 129, ${0.15 + intensity * 0.45})`;
  }
  if (value < 0) {
    const intensity = Math.min(Math.abs(value) / 5, 1);
    return `rgba(240, 82, 82, ${0.15 + intensity * 0.45})`;
  }
  return "var(--bg-card-inner)";
}

function heatmapFg(value: number): string {
  if (value > 0) return "var(--up)";
  if (value < 0) return "var(--down)";
  return "var(--fg-4)";
}

interface CellData {
  key: string;
  label: string;
  period: string;
  change: string;
  numericValue: number;
}

export function FactorHeatmap({ metrics }: FactorHeatmapProps) {
  const cells: CellData[][] = useMemo(() => {
    const periods = ["1W", "1M"] as const;
    return periods.map((period) =>
      FACTOR_KEYS.map((key) => {
        const metric = findMetric(metrics, key);
        const changeValue = period === "1W" ? (metric?.one_week_change ?? null) : (metric?.one_month_change ?? null);
        return {
          key: `${key}-${period}`,
          label: metric?.label ?? key,
          period,
          change: formatMetricChange(changeValue),
          numericValue: changeToNumber(changeValue),
        };
      }),
    );
  }, [metrics]);

  return (
    <FACard title="因子热力图" eyebrow="Factor Heatmap" accent="warn" bodyClassName="p-0">
      <div className="p-3">
        <div className="grid gap-1" style={{ gridTemplateColumns: `100px repeat(${FACTOR_KEYS.length}, 1fr)` }}>
          {/* Header row */}
          <div />
          {FACTOR_KEYS.map((key) => (
            <div key={key} className="px-1 py-1 text-center text-[9px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-5)]">
              {key}
            </div>
          ))}

          {/* Data rows */}
          {cells.map((row, ri) => (
            <Fragment key={`row-${ri}`}>
              <div className="flex items-center pr-2 text-[9px] font-semibold text-[var(--fg-5)]">
                {row[0].period}
              </div>
              {row.map((cell) => (
                <div
                  key={cell.key}
                  className="flex flex-col items-center justify-center rounded-[var(--radius-sm)] px-1 py-2 text-center font-mono"
                  style={{
                    backgroundColor: heatmapBg(cell.numericValue),
                    color: heatmapFg(cell.numericValue),
                  }}
                >
                  <span className="text-[12px] font-bold leading-none">{cell.change}</span>
                </div>
              ))}
            </Fragment>
          ))}
        </div>
      </div>
    </FACard>
  );
}

export default FactorHeatmap;
