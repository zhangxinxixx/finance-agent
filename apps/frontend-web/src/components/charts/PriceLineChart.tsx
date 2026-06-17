import { useEffect, useMemo, useRef, useState } from "react";
import {
  buildCandlesChart,
  buildLineChart,
  candleMaxOffset,
  clamp,
  MIN_WINDOW_SIZE,
  normalizedWindowSize,
  type PriceCandlePoint,
  type PriceLineChartPoint,
  visibleCandlesWindow,
} from "@/components/charts/priceLineChartModel";
import {
  PriceLineChartControls,
  PriceLineChartEdgeLabels,
  PriceLineChartEmptyState,
} from "@/components/charts/PriceLineChartControls";
import { PriceLineChartSvg } from "@/components/charts/PriceLineChartSvg";

interface PriceLineChartProps {
  points: PriceLineChartPoint[];
  candles?: PriceCandlePoint[];
  viewportKey?: string;
  height?: number;
  color?: string;
  gradientStart?: string;
  gradientEnd?: string;
  areaOpacity?: number;
  loading?: boolean;
  errorText?: string | null;
  emptyText?: string;
}

export function PriceLineChart({
  points,
  candles,
  viewportKey,
  height = 220,
  color = "#fbbf24",
  gradientStart = "#f59e0b",
  gradientEnd = "#fde68a",
  areaOpacity = 0.18,
  loading = false,
  errorText = null,
  emptyText = "暂无足够历史点绘制价格图",
}: PriceLineChartProps) {
  const width = 640;
  const gridRows = 5;
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [windowSize, setWindowSize] = useState(24);
  const [windowOffset, setWindowOffset] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isPointerInside, setIsPointerInside] = useState(false);
  const dragStartX = useRef<number | null>(null);
  const dragStartOffset = useRef<number>(0);
  const totalCandles = candles?.length ?? 0;
  const activeWindowSize = normalizedWindowSize(totalCandles, windowSize);
  const visibleCandles = useMemo(() => {
    return visibleCandlesWindow(candles, activeWindowSize, windowOffset);
  }, [activeWindowSize, candles, windowOffset]);
  const candlesChart = useMemo(() => {
    return buildCandlesChart(visibleCandles, width, height);
  }, [height, visibleCandles]);
  const hoveredCandle = hoveredIndex !== null && candlesChart ? candlesChart.items[hoveredIndex] : null;
  const activeCandle = hoveredCandle ?? candlesChart?.items[candlesChart.items.length - 1] ?? null;
  const maxOffset = useMemo(
    () => candleMaxOffset(candles, activeWindowSize),
    [activeWindowSize, candles],
  );
  useEffect(() => {
    setHoveredIndex(null);
    setWindowOffset(0);
    setWindowSize(24);
    setIsDragging(false);
    dragStartX.current = null;
    dragStartOffset.current = 0;
  }, [viewportKey, candles?.length]);
  const chart = useMemo(() => {
    return buildLineChart(points, width, height);
  }, [height, points]);

  if (!chart && !candlesChart) {
    return <PriceLineChartEmptyState height={height} loading={loading} errorText={errorText} emptyText={emptyText} />;
  }

  return (
    <>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height, cursor: candlesChart ? (isDragging ? "grabbing" : "crosshair") : "default" }}
        onMouseLeave={() => {
          setHoveredIndex(null);
          setIsDragging(false);
          setIsPointerInside(false);
          dragStartX.current = null;
        }}
        onMouseEnter={() => setIsPointerInside(true)}
        onWheel={(event) => {
          if (!candles || candles.length <= MIN_WINDOW_SIZE) return;
          if (!isPointerInside) return;
          if (!event.ctrlKey && !event.metaKey && !event.shiftKey) return;
          event.preventDefault();
          const delta = event.deltaY;
          setWindowSize((current) => {
            const next = delta > 0
              ? Math.min(candles.length, current + 2)
              : Math.max(Math.min(MIN_WINDOW_SIZE, candles.length), current - 2);
            return next;
          });
          setWindowOffset((current) => clamp(current, 0, Math.max(0, candles.length - activeWindowSize)));
        }}
        onMouseDown={(event) => {
          if (!candlesChart) return;
          setIsDragging(true);
          setIsPointerInside(true);
          dragStartX.current = event.clientX;
          dragStartOffset.current = windowOffset;
        }}
        onMouseMove={(event) => {
          if (!candlesChart || !isDragging || dragStartX.current === null) return;
          const deltaX = event.clientX - dragStartX.current;
          const moved = Math.round(deltaX / 14);
          const nextOffset = clamp(dragStartOffset.current + moved, 0, maxOffset);
          setWindowOffset(nextOffset);
        }}
        onMouseUp={() => {
          setIsDragging(false);
          dragStartX.current = null;
        }}
      >
        <PriceLineChartSvg
          width={width}
          height={height}
          gridRows={gridRows}
          candlesChart={candlesChart}
          hoveredIndex={hoveredIndex}
          hoveredCandle={hoveredCandle}
          activeCandle={activeCandle}
          chart={chart}
          color={color}
          gradientStart={gradientStart}
          gradientEnd={gradientEnd}
          areaOpacity={areaOpacity}
          onHoverCandle={setHoveredIndex}
        />
      </svg>
      <PriceLineChartControls
        candles={candles ?? []}
        normalizedWindowSize={activeWindowSize}
        windowOffset={windowOffset}
        onWindowSizeChange={setWindowSize}
        onWindowOffsetChange={setWindowOffset}
      />
      <PriceLineChartEdgeLabels
        firstLabel={visibleCandles?.[0]?.label ?? candles?.[0]?.label ?? chart?.firstLabel ?? ""}
        lastLabel={visibleCandles?.[visibleCandles.length - 1]?.label ?? candles?.[candles.length - 1]?.label ?? chart?.lastLabel ?? ""}
      />
    </>
  );
}

export type { PriceCandlePoint, PriceLineChartPoint };
