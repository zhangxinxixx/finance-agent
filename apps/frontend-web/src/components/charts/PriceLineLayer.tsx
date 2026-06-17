import type { LineChartModel } from "@/components/charts/priceLineChartModel";

export function PriceLineLayer({
  chart,
  color,
  gradientStart,
  gradientEnd,
  areaOpacity,
}: {
  chart: LineChartModel;
  color: string;
  gradientStart: string;
  gradientEnd: string;
  areaOpacity: number;
  width: number;
}) {
  return (
    <>
      <defs>
        <linearGradient id="price-line-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={gradientStart} />
          <stop offset="55%" stopColor={color} />
          <stop offset="100%" stopColor={gradientEnd} />
        </linearGradient>
        <linearGradient id="price-area-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity={areaOpacity} />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
        <filter id="price-line-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path d={chart.areaPath} fill="url(#price-area-gradient)" />
      <path
        d={chart.path}
        fill="none"
        stroke="url(#price-line-gradient)"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#price-line-glow)"
      />
      <circle cx={640} cy={chart.lastY} r="4" fill={color} stroke="rgba(15,23,42,0.9)" strokeWidth="1.5" />
    </>
  );
}
