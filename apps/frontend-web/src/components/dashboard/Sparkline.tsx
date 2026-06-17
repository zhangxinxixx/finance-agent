interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
  className?: string;
}

export function Sparkline({
  data,
  width = 56,
  height = 22,
  color = "var(--brand-hover)",
  strokeWidth = 1.5,
  className = "",
}: SparklineProps) {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 2;

  const points = data.map((value, index) => {
    const x = pad + (index / (data.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (value - min) / range) * (height - pad * 2);
    return `${x},${y}`;
  });

  const pathD = `M${points.join(" L")}`;

  const lastPoint = points[points.length - 1].split(",");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path
        d={pathD}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={lastPoint[0]}
        cy={lastPoint[1]}
        r={2}
        fill={color}
      />
    </svg>
  );
}

/** Generate realistic mock sparkline data for financial metrics. */
export function mockSparkline(baseValue: number, volatility = 0.008, points = 8): number[] {
  const result: number[] = [baseValue];
  for (let i = 1; i < points; i++) {
    const delta = result[i - 1] * volatility * (Math.random() * 2 - 1);
    result.push(result[i - 1] + delta);
  }
  return result;
}
