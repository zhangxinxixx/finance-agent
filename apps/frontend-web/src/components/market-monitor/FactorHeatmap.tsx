import { Fragment, useMemo } from "react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { FACard } from "@/components/shared/FACard";
import { findMetric, formatMetricChange, marketMonitorMetricLabel } from "./format";

interface FactorHeatmapProps {
  metrics: MarketMonitorMetric[];
}

const FACTOR_KEYS = ["XAUUSD", "DXY", "US10Y", "REAL_10Y", "T10YIE", "YIELD_SPREAD_2Y_3M", "TGA"] as const;
const FACTOR_LABELS: Record<string, string> = {
  XAUUSD: "现货黄金（XAUUSD）",
  DXY: "美元指数（DXY）",
  US10Y: "10年利率",
  REAL_10Y: "10年实际利率",
  T10YIE: "10年通胀预期",
  YIELD_SPREAD_2Y_3M: "2年-3个月利差",
  TGA: "财政账户（TGA）",
};

function changeToNumber(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const cleaned = value.replace(/[+%]/g, "").trim();
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function heatmapBg(value: number | null): string {
  if (value === null) return "var(--bg-card-inner)";
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

function heatmapFg(value: number | null): string {
  if (value === null) return "var(--fg-4)";
  if (value > 0) return "var(--up)";
  if (value < 0) return "var(--down)";
  return "var(--fg-4)";
}

interface CellData {
  key: string;
  label: string;
  period: string;
  change: string;
  numericValue: number | null;
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
          label: marketMonitorMetricLabel(key, FACTOR_LABELS[key] ?? metric?.label),
          period: period === "1W" ? "周变化" : "月变化",
          change: formatMetricChange(changeValue),
          numericValue: changeToNumber(changeValue),
        };
      }),
    );
  }, [metrics]);

  return (
    <FACard title="因子热力图" eyebrow="因子变化对照" accent="warn" bodyClassName="p-0">
      <div className="p-3">
        <div className="grid gap-1" style={{ gridTemplateColumns: `100px repeat(${FACTOR_KEYS.length}, 1fr)` }}>
          {/* Header row */}
          <div />
          {FACTOR_KEYS.map((key) => (
            <div key={key} className="px-1 py-1 text-center text-[length:var(--type-caption)] font-semibold tracking-[0.06em] text-[var(--fg-5)]">
              {marketMonitorMetricLabel(key, FACTOR_LABELS[key])}
            </div>
          ))}

          {/* Data rows */}
          {cells.map((row, ri) => (
            <Fragment key={`row-${ri}`}>
              <div className="flex items-center pr-2 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">
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
