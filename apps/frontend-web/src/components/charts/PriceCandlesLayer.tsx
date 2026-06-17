import type { CandleChartItem, CandleChartModel } from "@/components/charts/priceLineChartModel";
import {
  PriceCandleCloseMarker,
  PriceCandleHoverCrosshair,
  PriceCandlePriceLabels,
  PriceCandleSeries,
  PriceCandleTicks,
  PriceCandleTooltip,
  shouldRenderTick,
} from "@/components/charts/PriceCandlesLayerParts";

export function PriceCandlesLayer({
  width,
  height,
  gridRows,
  candlesChart,
  hoveredIndex,
  hoveredCandle,
  activeCandle,
  onHoverCandle,
}: {
  width: number;
  height: number;
  gridRows: number;
  candlesChart: CandleChartModel;
  hoveredIndex: number | null;
  hoveredCandle: CandleChartItem | null;
  activeCandle: CandleChartItem | null;
  onHoverCandle: (index: number | null) => void;
}) {
  return (
    <>
      <PriceCandlePriceLabels width={width} height={height} gridRows={gridRows} candlesChart={candlesChart} />
      <PriceCandleSeries
        height={height}
        candlesChart={candlesChart}
        hoveredIndex={hoveredIndex}
        onHoverCandle={onHoverCandle}
      />
      <PriceCandleHoverCrosshair width={width} height={height} hoveredCandle={hoveredCandle} />
      <PriceCandleTicks height={height} candles={candlesChart.items} />
      <PriceCandleTooltip activeCandle={activeCandle} />
      <PriceCandleCloseMarker width={width} activeCandle={activeCandle} />
    </>
  );
}
export { shouldRenderTick };
