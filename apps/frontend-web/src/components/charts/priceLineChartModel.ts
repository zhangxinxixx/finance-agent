export interface PriceLineChartPoint {
  label: string;
  value: number;
}

export interface PriceCandlePoint {
  label: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface CandleChartItem extends PriceCandlePoint {
  x: number;
  openY: number;
  closeY: number;
  highY: number;
  lowY: number;
  up: boolean;
}

export interface CandleChartModel {
  min: number;
  max: number;
  range: number;
  step: number;
  candleWidth: number;
  mapY: (value: number) => number;
  items: CandleChartItem[];
}

export interface LineChartModel {
  min: number;
  max: number;
  range: number;
  path: string;
  areaPath: string;
  firstLabel: string;
  lastLabel: string;
  lastY: number;
}

export const MIN_WINDOW_SIZE = 12;

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function normalizedWindowSize(totalCandles: number, windowSize: number) {
  return totalCandles > 0 ? clamp(windowSize, Math.min(MIN_WINDOW_SIZE, totalCandles), totalCandles) : windowSize;
}

export function visibleCandlesWindow(
  candles: PriceCandlePoint[] | undefined,
  windowSize: number,
  windowOffset: number,
) {
  if (!candles || candles.length <= windowSize) return candles ?? [];
  const maxOffset = Math.max(0, candles.length - windowSize);
  const safeOffset = clamp(windowOffset, 0, maxOffset);
  const start = maxOffset - safeOffset;
  return candles.slice(start, start + windowSize);
}

export function candleMaxOffset(candles: PriceCandlePoint[] | undefined, windowSize: number) {
  return candles && candles.length > windowSize ? candles.length - windowSize : 0;
}

export function buildCandlesChart(
  candles: PriceCandlePoint[],
  width: number,
  height: number,
): CandleChartModel | null {
  if (candles.length < 2) return null;
  const lows = candles.map((candle) => candle.low);
  const highs = candles.map((candle) => candle.high);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const range = max - min || 1;
  const step = width / candles.length;
  const candleWidth = Math.max(6, Math.min(18, step * 0.56));
  const mapY = (value: number) => height - ((value - min) / range) * height;

  return {
    min,
    max,
    range,
    step,
    candleWidth,
    mapY,
    items: candles.map((candle, index) => ({
      ...candle,
      x: step * index + step / 2,
      openY: mapY(candle.open),
      closeY: mapY(candle.close),
      highY: mapY(candle.high),
      lowY: mapY(candle.low),
      up: candle.close >= candle.open,
    })),
  };
}

export function buildLineChart(
  points: PriceLineChartPoint[],
  width: number,
  height: number,
): LineChartModel | null {
  if (points.length < 2) return null;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const path = values
    .map((value, index) => {
      const x = index * step;
      const y = height - ((value - min) / range) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return {
    min,
    max,
    range,
    path,
    areaPath: `${path} L${width.toFixed(1)},${height.toFixed(1)} L0,${height.toFixed(1)} Z`,
    firstLabel: points[0]?.label ?? "",
    lastLabel: points[points.length - 1]?.label ?? "",
    lastY: height - ((values[values.length - 1] - min) / range) * height,
  };
}
