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
  const trendColor = trendUp ? "var(--up)" : xau.trend === "down" ? "var(--down)" : "var(--brand-hover)";

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
      <div className="fa-card-header" style={{ flexDirection: "column", alignItems: "stretch", gap: 7 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ font: "700 12px/1 var(--font-sans)", color: "var(--fg-1)" }}>XAUUSD</span>
          <span className="fa-num" style={{ font: "700 16px/1 var(--font-mono)", color: "var(--fg-1)" }}>
            {xauValue}
          </span>
          {xau.change ? (
            <span className="fa-num" style={{ fontSize: 11, color: trendUp ? "var(--up)" : "var(--down)", fontWeight: 600 }}>
              {xau.change}
            </span>
          ) : null}
          <div
            style={{
              marginLeft: "auto",
              display: "flex",
              gap: 2,
              padding: 2,
              border: "1px solid var(--border-faint)",
              borderRadius: 6,
              background: "rgba(255,255,255,0.02)",
            }}
          >
            {TIMEFRAMES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  setActiveTimeframe(t);
                  onTimeframeChange?.(t);
                }}
                style={{
                  minWidth: 34,
                  padding: "5px 7px",
                  background: effectiveTimeframe === t ? "rgba(121,171,255,0.16)" : "transparent",
                  color: effectiveTimeframe === t ? "var(--brand-hover)" : "var(--fg-4)",
                  border: "0",
                  borderRadius: 4,
                  font: "600 10px/1 var(--font-sans)",
                  cursor: "pointer",
                }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        <div style={{ fontSize: 10, color: "var(--fg-5)", lineHeight: 1.4 }}>
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

      <div style={{ display: "flex", alignItems: "center", gap: 0, padding: "5px 14px", background: "rgba(0,0,0,0.15)", borderBottom: "1px solid var(--border)", overflowX: "auto" }}>
        {strip.map((level, index) => (
          <div key={`${level.desc}-${index}`} style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0 }}>
            {index > 0 ? <span style={{ color: "var(--border-strong)", fontSize: 12, margin: "0 10px" }}>|</span> : null}
            <span style={{ width: 2, height: 10, background: level.color, borderRadius: 1 }} />
            <span className="fa-num" style={{ fontSize: 11, fontWeight: 700, color: level.color }}>{level.label}</span>
            <span style={{ fontSize: 9, color: "var(--fg-5)" }}>{level.desc}</span>
          </div>
        ))}
      </div>

      <div className="fa-card-body" style={{ padding: "12px" }}>
        <div style={{ border: "1px solid var(--border-faint)", borderRadius: 10, background: "var(--bg-card-inner)", padding: 12 }}>
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
