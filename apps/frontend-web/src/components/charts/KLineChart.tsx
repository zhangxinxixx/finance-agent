import { useEffect, useRef, useCallback, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import {
  KLINE_TIMEFRAMES,
  type KlineTimeframe,
  type MarketCandleTimeframeAvailability,
} from "@/components/market-monitor/klineCoverageModel";

// ═══════════════════════════════════════
// Types
// ═══════════════════════════════════════

export interface KLineCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface KLineSeries {
  key: string;
  label: string;
  color: string;
  values: { time: string; value: number }[];
  dashed?: boolean;
}

export type KLineTimeframe = KlineTimeframe;

// ── Convert ISO string → Unix timestamp (seconds) ──
function toChartTime(iso: string): Time {
  const ms = Date.parse(iso);
  if (!Number.isNaN(ms)) return (ms / 1000) as Time;
  return iso as Time; // fallback
}

// ═══════════════════════════════════════
// Light workstation theme
// ═══════════════════════════════════════

const CHART_BG = "#f8fafc";
const GRID_COLOR = "rgba(15, 23, 42, 0.07)";
const TEXT_COLOR = "rgba(15, 23, 42, 0.58)";
const VALUE_TEXT_COLOR = "#0f172a";
const CROSSHAIR_COLOR = "rgba(15, 23, 42, 0.18)";
const CROSSHAIR_LABEL_BG = "rgba(15, 23, 42, 0.82)";
const TOOLTIP_BG = "rgba(255, 255, 255, 0.96)";
const TOOLTIP_BORDER = "rgba(148, 163, 184, 0.35)";

// ═══════════════════════════════════════
// Component
// ═══════════════════════════════════════

interface KLineChartProps {
  candles: KLineCandle[];
  lineSeries?: KLineSeries[];
  height?: number;
  loading?: boolean;
  emptyText?: string;
  timeframe?: KLineTimeframe;
  onTimeframeChange?: (tf: KLineTimeframe) => void;
  timeframeAvailability?: Partial<Record<KLineTimeframe, MarketCandleTimeframeAvailability>>;
}

export function KLineChart({
  candles,
  lineSeries = [],
  height = 500,
  loading = false,
  emptyText = "暂无 K 线数据",
  timeframe = "5m",
  onTimeframeChange,
  timeframeAvailability,
}: KLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lineSeriesRefs = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const tooltipRef = useRef<HTMLDivElement>(null);

  // ── Init chart ──
  useEffect(() => {
    if (!containerRef.current) return;
    if (chartRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: CHART_BG },
        textColor: TEXT_COLOR,
      },
      grid: {
        vertLines: { color: GRID_COLOR },
        horzLines: { color: GRID_COLOR },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: CROSSHAIR_COLOR,
          width: 1,
          style: 2, // dashed
          labelBackgroundColor: CROSSHAIR_LABEL_BG,
          labelVisible: true,
        },
        horzLine: {
          color: CROSSHAIR_COLOR,
          width: 1,
          style: 2,
          labelBackgroundColor: CROSSHAIR_LABEL_BG,
          labelVisible: true,
        },
      },
      rightPriceScale: {
        borderColor: GRID_COLOR,
        scaleMargins: { top: 0.05, bottom: 0.25 },
        autoScale: true,
      },
      timeScale: {
        borderColor: GRID_COLOR,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: Time) => {
          const d = new Date((time as number) * 1000);
          const hh = String(d.getHours()).padStart(2, "0");
          const mm = String(d.getMinutes()).padStart(2, "0");
          return `${hh}:${mm}`;
        },
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, mouseWheel: true, pinch: true },
    });

    // K 线系列
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f05252",
      borderUpColor: "#10b981",
      borderDownColor: "#f05252",
      wickUpColor: "#10b981",
      wickDownColor: "#f05252",
    });

    // 成交量系列
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(16,185,129,0.3)",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
      visible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Resize
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.resize(entry.contentRect.width, entry.contentRect.height);
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      lineSeriesRefs.current.clear();
    };
  }, []);

  // ── Resize when height changes ──
  useEffect(() => {
    if (chartRef.current && containerRef.current) {
      chartRef.current.resize(containerRef.current.clientWidth, height);
    }
  }, [height]);

  // ── Update candle data ──
  const candleData: CandlestickData[] = useMemo(() => {
    return candles
      .filter((c) => c.open != null && c.high != null && c.low != null && c.close != null)
      .map((c) => ({
        time: toChartTime(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
  }, [candles]);

  useEffect(() => {
    if (candleSeriesRef.current && candleData.length > 0) {
      candleSeriesRef.current.setData(candleData);
    }
  }, [candleData]);

  // ── Update volume ──
  const volumeData: HistogramData[] = useMemo(() => {
    return candles
      .filter((c) => c.volume != null)
      .map((c) => ({
        time: toChartTime(c.time),
        value: c.volume!,
        color: (c.close ?? 0) >= (c.open ?? 0) ? "rgba(16,185,129,0.3)" : "rgba(240,82,82,0.3)",
      }));
  }, [candles]);

  useEffect(() => {
    if (volumeSeriesRef.current) {
      volumeSeriesRef.current.setData(volumeData);
    }
  }, [volumeData]);

  // ── Update line series ──
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const existing = new Set(lineSeriesRefs.current.keys());
    const wanted = new Set(lineSeries.map((s) => s.key));

    // Remove stale
    for (const key of existing) {
      if (!wanted.has(key)) {
        const ls = lineSeriesRefs.current.get(key);
        if (ls) chart.removeSeries(ls);
        lineSeriesRefs.current.delete(key);
      }
    }

    // Add/update
    for (const series of lineSeries) {
      const lineData: LineData[] = series.values
        .filter((v) => v.value != null)
        .map((v) => ({ time: toChartTime(v.time), value: v.value }));

      if (lineSeriesRefs.current.has(series.key)) {
        lineSeriesRefs.current.get(series.key)!.setData(lineData);
      } else {
        const ls = chart.addSeries(LineSeries, {
          color: series.color,
          lineWidth: 1 as const,
          lineStyle: series.dashed ? 2 : 0,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
        });
        ls.setData(lineData);
        lineSeriesRefs.current.set(series.key, ls);
      }
    }
  }, [lineSeries]);

  // ── OHLC tooltip ──
  const updateTooltip = useCallback((param: any) => {
    const tooltip = tooltipRef.current;
    const chart = chartRef.current;
    if (!tooltip || !chart) {
      return;
    }
    if (!param || !param.time || param.point === undefined) {
      tooltip.style.display = "none";
      return;
    }
    const data = param.seriesData.get(candleSeriesRef.current!);
    if (!data || data.open == null) {
      tooltip.style.display = "none";
      return;
    }

    const { open, high, low, close } = data;
    const y = param.point.y;
    const isUp = close >= open;
    const color = isUp ? "#10b981" : "#f05252";
    const change = close - open;
    const changePct = open > 0 ? ((change / open) * 100).toFixed(2) : "0.00";
    const sign = change >= 0 ? "+" : "";

    const d = typeof param.time === "number" ? new Date(param.time * 1000) : new Date(param.time as string);
    const timeStr =
      timeframe === "1D"
        ? d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" })
        : `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

    let html = `<div style="font-size:11px;color:${TEXT_COLOR};margin-bottom:4px">${timeStr}</div>`;
    html += `<div style="display:flex;gap:12px;font-size:12px;font-family:var(--font-mono)">`;
    html += `<div><span style="color:${TEXT_COLOR}">O </span><span style="color:${VALUE_TEXT_COLOR}">${open.toFixed(2)}</span></div>`;
    html += `<div><span style="color:${TEXT_COLOR}">H </span><span style="color:${color}">${high.toFixed(2)}</span></div>`;
    html += `<div><span style="color:${TEXT_COLOR}">L </span><span style="color:${color}">${low.toFixed(2)}</span></div>`;
    html += `<div><span style="color:${TEXT_COLOR}">C </span><span style="color:${color}">${close.toFixed(2)}</span></div>`;
    html += `</div>`;
    html += `<div style="margin-top:4px;font-size:11px;font-family:var(--font-mono);color:${color}">${sign}${change.toFixed(2)} (${sign}${changePct}%)</div>`;

    // Check volume
    const volData = param.seriesData.get(volumeSeriesRef.current!);
    if (volData && volData.value != null) {
      html += `<div style="margin-top:3px;font-size:10px;color:${TEXT_COLOR}">Vol ${volData.value}</div>`;
    }

    tooltip.innerHTML = html;
    tooltip.style.display = "block";

    // Position tooltip
    const containerWidth = containerRef.current?.clientWidth ?? 600;
    const left = param.point.x > containerWidth / 2 ? param.point.x - 170 : param.point.x + 20;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(10, y - 80)}px`;
  }, [timeframe]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.subscribeCrosshairMove(updateTooltip);
    return () => chart.unsubscribeCrosshairMove(updateTooltip);
  }, [updateTooltip]);

  // ── Auto-fit on data change ──
  useEffect(() => {
    if (candleData.length > 0 && chartRef.current) {
      chartRef.current.timeScale().fitContent();
    }
  }, [candleData.length]);

  // ── Render ──
  return (
    <div style={{ position: "relative", height, display: "flex", flexDirection: "column" }}>
      {/* Timeframe switcher */}
      <div
        style={{
          position: "absolute",
          top: 8,
          left: 8,
          zIndex: 10,
          display: "flex",
          gap: 2,
          background: "rgba(255,255,255,0.92)",
          border: "1px solid var(--border-faint)",
          borderRadius: "var(--radius-sm)",
          padding: 2,
          boxShadow: "var(--shadow-card)",
        }}
      >
        {KLINE_TIMEFRAMES.map((tf) => {
          const active = tf.key === timeframe;
          const availability = timeframeAvailability?.[tf.key];
          const status = availability?.status ?? "available";
          const disabled = status === "unavailable";
          const statusLabel = status === "degraded" ? "降" : status === "unavailable" ? "停" : status === "loading" ? "…" : "";
          return (
            <button
              key={tf.key}
              onClick={() => {
                if (!disabled) onTimeframeChange?.(tf.key);
              }}
              disabled={disabled}
              aria-label={`${tf.label} ${availability?.label ?? "可用"}`}
              title={availability ? `${tf.label}：${availability.label} · ${availability.reason}` : tf.label}
              data-coverage-status={status}
              style={{
                display: "inline-flex",
                minWidth: 34,
                alignItems: "center",
                justifyContent: "center",
                gap: 3,
                background: active ? "var(--brand-dim)" : status === "degraded" ? "var(--warn-soft)" : "transparent",
                color: disabled ? "var(--fg-6)" : active ? "var(--brand-hover)" : status === "degraded" ? "var(--warn)" : TEXT_COLOR,
                border: "none",
                borderRadius: "var(--radius-sm)",
                padding: "2px 7px",
                fontSize: "var(--type-caption)",
                fontWeight: active ? 600 : 400,
                cursor: disabled ? "not-allowed" : "pointer",
                fontFamily: "inherit",
                opacity: disabled ? 0.58 : 1,
                transition: "all 0.15s",
              }}
            >
              <span>{tf.label}</span>
              {statusLabel ? (
                <span
                  aria-hidden="true"
                  style={{
                    fontSize: "var(--text-10)",
                    fontWeight: 700,
                    lineHeight: 1,
                  }}
                >
                  {statusLabel}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {/* Loading */}
      {loading && (
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            color: TEXT_COLOR,
            fontSize: 12,
            zIndex: 10,
          }}
        >
          加载中...
        </div>
      )}

      {/* Empty */}
      {!loading && candleData.length < 2 && (
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            color: TEXT_COLOR,
            fontSize: 12,
            zIndex: 10,
          }}
        >
          {emptyText}
        </div>
      )}

      {/* OHLC Tooltip */}
      <div
        ref={tooltipRef}
        style={{
          position: "absolute",
          zIndex: 20,
          display: "none",
          background: TOOLTIP_BG,
          borderRadius: "var(--radius-md)",
          padding: "8px 10px",
          pointerEvents: "none",
          minWidth: 150,
          border: `1px solid ${TOOLTIP_BORDER}`,
          boxShadow: "var(--shadow-popover)",
        }}
      />

      {/* Chart container */}
      <div ref={containerRef} style={{ flex: 1, minHeight: 0 }} />
    </div>
  );
}
