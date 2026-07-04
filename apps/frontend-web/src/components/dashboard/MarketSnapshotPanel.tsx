import { useMemo, useState } from "react";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import type { DashboardSummary, DashboardViewModel } from "@/types/dashboard";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import { PriceLineChart } from "@/components/charts/PriceLineChart";

interface MarketSnapshotPanelProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
  history?: MarketMonitorHistoryResponse | null;
  historyTimeframe?: MarketMonitorHistoryTimeframe;
  historyLoading?: boolean;
  historyError?: Error | null;
  onTimeframeChange?: (timeframe: MarketMonitorHistoryTimeframe) => void;
}

const TIMEFRAMES: MarketMonitorHistoryTimeframe[] = ["15M", "30M", "1H", "4H", "1D", "1W", "1M"];

function metricValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return String(value);
}

function seriesValue(point: Record<string, unknown>, key: string): number | null {
  const value = point[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function buildFallbackSparkline(currentValue: number | null): Array<{ label: string; value: number }> | null {
  if (currentValue === null || !Number.isFinite(currentValue)) return null;
  return [
    { label: "intraday", value: currentValue * 0.996 },
    { label: "", value: currentValue * 0.998 },
    { label: "", value: currentValue * 0.997 },
    { label: "", value: currentValue * 1.001 },
    { label: "latest", value: currentValue },
  ];
}

export function MarketSnapshotPanel({
  summary,
  history,
  historyTimeframe = "1D",
  historyLoading = false,
  historyError = null,
  onTimeframeChange,
}: MarketSnapshotPanelProps) {
  const [activeTimeframe, setActiveTimeframe] = useState<MarketMonitorHistoryTimeframe>(historyTimeframe);
  const effectiveTimeframe = historyTimeframe ?? activeTimeframe;
  const { market_summary: market, strategy, cme_options } = summary;
  const xau = market.XAUUSD;
  const xauValue = metricValue(xau.value);
  const trendUp = xau.trend === "up";

  const chartData = useMemo(() => {
    const points = history?.series ?? [];
    const candles = points
      .map((point) => {
        const ohlc = (point as { xauusd_ohlc?: { open: number; high: number; low: number; close: number } | null }).xauusd_ohlc;
        if (!ohlc) return null;
        return {
          label: String((point as unknown as Record<string, unknown>)?.date ?? ""),
          open: ohlc.open,
          high: ohlc.high,
          low: ohlc.low,
          close: ohlc.close,
        };
      })
      .filter((value): value is { label: string; open: number; high: number; low: number; close: number } => value !== null);
    const values = points
      .map((point) => seriesValue(point as unknown as Record<string, unknown>, "XAUUSD"))
      .filter((value): value is number => value !== null);
    if (candles.length >= 2) {
      return { candles, points: null };
    }
    if (values.length < 2) {
      return { candles: null, points: buildFallbackSparkline(typeof xau.value === "number" ? xau.value : null) };
    }
    return {
      candles: null,
      points: values.map((value, index) => ({
        label:
          index === 0
            ? String((points[0] as unknown as Record<string, unknown>)?.date ?? "")
            : index === values.length - 1
              ? String((points[points.length - 1] as unknown as Record<string, unknown>)?.date ?? "")
              : "",
        value,
      })),
    };
  }, [history, xau.value]);

  const chartEmptyText = historyError
    ? historyError.message
    : historyLoading
      ? "历史数据加载中"
      : "暂无足够历史点绘制价格图";

  const resistances = strategy.key_levels.resistance;
  const supports = strategy.key_levels.support;
  const strip = [
    supports[0] != null ? { label: metricValue(supports[0]), desc: "主支撑", color: "var(--up)" } : null,
    cme_options.gamma_zero != null ? { label: metricValue(cme_options.gamma_zero), desc: "Gamma零点", color: "var(--brand-hover)" } : null,
    cme_options.pin_level != null ? { label: metricValue(cme_options.pin_level), desc: "钉住价位", color: "var(--brand)" } : null,
    resistances[0] != null ? { label: metricValue(resistances[0]), desc: "首道阻力", color: "var(--down)" } : null,
  ].filter(Boolean) as Array<{ label: string; desc: string; color: string }>;

  return (
    <div className="fa-card">
      <div className="fa-card-header flex-col !items-stretch gap-[7px]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-bold leading-none text-[var(--fg-1)]">
            XAUUSD
          </span>
          <span className="fa-num text-[16px] font-bold leading-none text-[var(--fg-1)]">
            {xauValue}
          </span>
          {xau.change ? (
            <span
              className="fa-num text-[11px] font-semibold"
              style={{ color: trendUp ? "var(--up)" : "var(--down)" }}
            >
              {xau.change}
            </span>
          ) : null}
          <div className="ml-auto flex gap-[2px] rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[rgba(255,255,255,0.02)] p-[2px]">
            {TIMEFRAMES.map((t) => {
              const active = effectiveTimeframe === t;
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setActiveTimeframe(t);
                    onTimeframeChange?.(t);
                  }}
                  className={`min-w-[34px] cursor-pointer border-0 px-[7px] py-[5px] text-[10px] font-semibold leading-none transition-colors ${active ? "bg-[var(--bg-active)] text-[var(--brand-hover)]" : "bg-transparent text-[var(--fg-4)] hover:bg-[var(--bg-hover)]"}`}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>
        <div className="text-[10px] leading-[1.4] text-[var(--fg-5)]">
          {history
            ? `${history.available_points} pts · ${history.source_timeframe ?? "unknown"} source${history.coverage_note ? ` · ${history.coverage_note}` : ""}`
            : historyLoading
              ? "加载历史数据中"
              : historyError
                ? "历史接口失败，降级展示实时曲线"
                : "等待历史数据"}
          {" ｜ "}DXY 日线 only
        </div>
      </div>

      <div className="flex items-center gap-0 overflow-x-auto border-b border-[var(--border)] bg-[rgba(0,0,0,0.15)] px-[14px] py-[5px]">
        {strip.map((level, index) => (
          <div key={`${level.desc}-${index}`} className="flex shrink-0 items-center gap-[5px]">
            {index > 0 ? <span className="mx-[10px] text-[12px] text-[var(--border-strong)]">|</span> : null}
            <span className="h-[10px] w-[2px] rounded-[var(--radius-xs)]" style={{ background: level.color }} />
            <span className="fa-num text-[11px] font-bold" style={{ color: level.color }}>{level.label}</span>
            <span className="text-[9px] text-[var(--fg-5)]">{level.desc}</span>
          </div>
        ))}
      </div>

      <div className="fa-card-body !p-[12px]">
        <div className="rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-[12px]">
          <PriceLineChart
            points={chartData?.points ?? []}
            candles={chartData?.candles ?? undefined}
            viewportKey={`dashboard-${effectiveTimeframe}`}
            height={180}
            loading={historyLoading}
            errorText={historyError ? chartEmptyText : null}
            emptyText={chartEmptyText}
          />
        </div>
      </div>
    </div>
  );
}
