export function PriceLineChartGrid({
  width,
  height,
  gridRows,
}: {
  width: number;
  height: number;
  gridRows: number;
}) {
  return (
    <>
      {Array.from({ length: gridRows + 1 }, (_, index) => {
        const y = (height / gridRows) * index;
        return (
          <line
            key={`grid-${index}`}
            x1="0"
            y1={y}
            x2={width}
            y2={y}
            stroke={index === gridRows ? "rgba(148,163,184,0.18)" : "rgba(148,163,184,0.08)"}
            strokeWidth={index === gridRows ? 1 : 0.8}
          />
        );
      })}
    </>
  );
}
