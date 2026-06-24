import type { CandleChartItem, CandleChartModel, LineChartModel } from "@/components/charts/priceLineChartModel";
import { PriceCandlesLayer } from "@/components/charts/PriceCandlesLayer";
import { PriceLineChartGrid } from "@/components/charts/PriceLineChartGrid";
import { PriceLineLayer } from "@/components/charts/PriceLineLayer";

export function PriceLineChartSvg({
  width,
  height,
  gridRows,
  candlesChart,
  hoveredIndex,
  hoveredCandle,
  activeCandle,
  chart,
  color,
  gradientStart,
  gradientEnd,
  areaOpacity,
  onHoverCandle,
}: {
  width: number;
  height: number;
  gridRows: number;
  candlesChart: CandleChartModel | null;
  hoveredIndex: number | null;
  hoveredCandle: CandleChartItem | null;
  activeCandle: CandleChartItem | null;
  chart: LineChartModel | null;
  color: string;
  gradientStart: string;
  gradientEnd: string;
  areaOpacity: number;
  onHoverCandle: (index: number | null) => void;
}) {
  return (
    <>
      <rect x="0" y="0" width={width} height={height} rx="10" fill="rgba(15, 23, 42, 0.28)" />
      <PriceLineChartGrid width={width} height={height} gridRows={gridRows} />

      {candlesChart ? (
        <PriceCandlesLayer
          width={width}
          height={height}
          gridRows={gridRows}
          candlesChart={candlesChart}
          hoveredIndex={hoveredIndex}
          hoveredCandle={hoveredCandle}
          activeCandle={activeCandle}
          onHoverCandle={onHoverCandle}
        />
      ) : chart ? (
        <PriceLineLayer
          chart={chart}
          color={color}
          gradientStart={gradientStart}
          gradientEnd={gradientEnd}
          areaOpacity={areaOpacity}
          width={width}
        />
      ) : null}
    </>
  );
}
