import type { CandleChartItem, CandleChartModel } from "@/components/charts/priceLineChartModel";

const CANDLE_UP_COLOR = "#34d399";
const CANDLE_DOWN_COLOR = "#f87171";
const HOVER_OVERLAY_FILL = "rgba(148,163,184,0.08)";
const PRICE_LABEL_FILL = "rgba(148,163,184,0.72)";
const CROSSHAIR_VERTICAL_STROKE = "rgba(226,232,240,0.28)";
const CROSSHAIR_HORIZONTAL_STROKE = "rgba(226,232,240,0.18)";
const TICK_LABEL_FILL = "rgba(148,163,184,0.82)";
const TOOLTIP_FILL = "rgba(15,23,42,0.88)";
const TOOLTIP_STROKE = "rgba(148,163,184,0.18)";
const TOOLTIP_TEXT_FILL = "rgba(226,232,240,0.92)";
const CLOSE_MARKER_UP_LINE = "rgba(52,211,153,0.35)";
const CLOSE_MARKER_DOWN_LINE = "rgba(248,113,113,0.35)";
const CLOSE_MARKER_UP_FILL = "rgba(6,95,70,0.92)";
const CLOSE_MARKER_DOWN_FILL = "rgba(127,29,29,0.92)";
const CLOSE_MARKER_UP_STROKE = "rgba(52,211,153,0.45)";
const CLOSE_MARKER_DOWN_STROKE = "rgba(248,113,113,0.4)";
const CLOSE_MARKER_TEXT_FILL = "rgba(255,255,255,0.96)";

export function PriceCandlePriceLabels({
  width,
  height,
  gridRows,
  candlesChart,
}: {
  width: number;
  height: number;
  gridRows: number;
  candlesChart: CandleChartModel;
}) {
  return (
    <>
      {Array.from({ length: gridRows }, (_, index) => {
        const value = candlesChart.max - (candlesChart.range / (gridRows - 1 || 1)) * index;
        const y = candlesChart.mapY(value);
        return (
          <text
            key={`price-${index}`}
            x={width - 4}
            y={Math.max(10, Math.min(height - 6, y - 4))}
            textAnchor="end"
            fill={PRICE_LABEL_FILL}
            fontSize="8.5"
          >
            {value.toFixed(1)}
          </text>
        );
      })}
    </>
  );
}

export function PriceCandleSeries({
  height,
  candlesChart,
  hoveredIndex,
  onHoverCandle,
}: {
  height: number;
  candlesChart: CandleChartModel;
  hoveredIndex: number | null;
  onHoverCandle: (index: number | null) => void;
}) {
  return (
    <>
      {candlesChart.items.map((candle, index) => {
        const bodyTop = Math.min(candle.openY, candle.closeY);
        const bodyHeight = Math.max(2, Math.abs(candle.closeY - candle.openY));
        const bodyColor = candle.up ? CANDLE_UP_COLOR : CANDLE_DOWN_COLOR;
        const isHovered = hoveredIndex === index;
        return (
          <g key={`${candle.label}-${candle.x}`}>
            <rect
              x={candle.x - candlesChart.step / 2}
              y={0}
              width={candlesChart.step}
              height={height}
              fill={isHovered ? HOVER_OVERLAY_FILL : "transparent"}
              onMouseEnter={() => onHoverCandle(index)}
            />
            <line
              x1={candle.x}
              x2={candle.x}
              y1={candle.highY}
              y2={candle.lowY}
              stroke={bodyColor}
              strokeWidth={isHovered ? "1.8" : "1.4"}
              opacity={isHovered ? "1" : "0.95"}
            />
            <rect
              x={candle.x - candlesChart.candleWidth / 2}
              y={bodyTop}
              width={candlesChart.candleWidth}
              height={bodyHeight}
              rx="1.5"
              fill={bodyColor}
              opacity={isHovered ? "1" : "0.92"}
            />
          </g>
        );
      })}
    </>
  );
}

export function PriceCandleHoverCrosshair({
  width,
  height,
  hoveredCandle,
}: {
  width: number;
  height: number;
  hoveredCandle: CandleChartItem | null;
}) {
  if (!hoveredCandle) return null;

  return (
    <>
      <line
        x1={hoveredCandle.x}
        x2={hoveredCandle.x}
        y1={0}
        y2={height}
        stroke={CROSSHAIR_VERTICAL_STROKE}
        strokeDasharray="4,4"
        strokeWidth="1"
      />
      <line
        x1={0}
        x2={width}
        y1={hoveredCandle.closeY}
        y2={hoveredCandle.closeY}
        stroke={CROSSHAIR_HORIZONTAL_STROKE}
        strokeDasharray="4,4"
        strokeWidth="1"
      />
    </>
  );
}

export function PriceCandleTicks({
  height,
  candles,
}: {
  height: number;
  candles: CandleChartItem[];
}) {
  return (
    <>
      {candles
        .filter((_, index) => shouldRenderTick(index, candles.length))
        .map((candle) => (
          <text
            key={`tick-${candle.label}-${candle.x}`}
            x={candle.x}
            y={height - 6}
            textAnchor="middle"
            fill={TICK_LABEL_FILL}
            fontSize="8.5"
          >
            {candle.label}
          </text>
        ))}
    </>
  );
}

export function PriceCandleTooltip({ activeCandle }: { activeCandle: CandleChartItem | null }) {
  if (!activeCandle) return null;

  return (
    <>
      <rect x={8} y={8} width={292} height={22} rx="8" fill={TOOLTIP_FILL} stroke={TOOLTIP_STROKE} />
      <text x={16} y={23} fill={TOOLTIP_TEXT_FILL} fontSize="9.5">
        {activeCandle.label}  O {activeCandle.open.toFixed(1)}  H {activeCandle.high.toFixed(1)}  L{" "}
        {activeCandle.low.toFixed(1)}  C {activeCandle.close.toFixed(1)}
      </text>
    </>
  );
}

export function PriceCandleCloseMarker({
  width,
  activeCandle,
}: {
  width: number;
  activeCandle: CandleChartItem | null;
}) {
  if (!activeCandle) return null;

  const closeLineStroke = activeCandle.up ? CLOSE_MARKER_UP_LINE : CLOSE_MARKER_DOWN_LINE;
  const closeBadgeFill = activeCandle.up ? CLOSE_MARKER_UP_FILL : CLOSE_MARKER_DOWN_FILL;
  const closeBadgeStroke = activeCandle.up ? CLOSE_MARKER_UP_STROKE : CLOSE_MARKER_DOWN_STROKE;

  return (
    <>
      <line
        x1={activeCandle.x}
        x2={width}
        y1={activeCandle.closeY}
        y2={activeCandle.closeY}
        stroke={closeLineStroke}
        strokeDasharray="3,4"
        strokeWidth="1"
      />
      <rect
        x={width - 56}
        y={activeCandle.closeY - 9}
        width={52}
        height={18}
        rx="5"
        fill={closeBadgeFill}
        stroke={closeBadgeStroke}
      />
      <text
        x={width - 30}
        y={activeCandle.closeY + 3}
        textAnchor="middle"
        fill={CLOSE_MARKER_TEXT_FILL}
        fontSize="9"
      >
        {activeCandle.close.toFixed(1)}
      </text>
    </>
  );
}

export function shouldRenderTick(index: number, length: number) {
  const last = length - 1;
  const mid = Math.floor(last / 2);
  const quarter = Math.floor(last / 4);
  const threeQuarter = Math.floor((last * 3) / 4);
  return index === 0 || index === quarter || index === mid || index === threeQuarter || index === last;
}
