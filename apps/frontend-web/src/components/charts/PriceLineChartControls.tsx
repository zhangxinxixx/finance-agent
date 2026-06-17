import { MIN_WINDOW_SIZE, clamp, type PriceCandlePoint } from "@/components/charts/priceLineChartModel";

export function PriceLineChartControls({
  candles,
  normalizedWindowSize,
  windowOffset,
  onWindowSizeChange,
  onWindowOffsetChange,
}: {
  candles: PriceCandlePoint[];
  normalizedWindowSize: number;
  windowOffset: number;
  onWindowSizeChange: (next: number) => void;
  onWindowOffsetChange: (next: number) => void;
}) {
  if (candles.length <= MIN_WINDOW_SIZE) {
    return null;
  }

  return (
    <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 9, color: "var(--fg-5)" }}>
        <span>滚轮缩放 · 拖拽平移</span>
        <span>窗口 {Math.min(normalizedWindowSize, candles.length)} / {candles.length}</span>
      </div>
      <input
        className="fa-chart-range"
        type="range"
        min={Math.min(MIN_WINDOW_SIZE, candles.length)}
        max={Math.max(Math.min(MIN_WINDOW_SIZE, candles.length), candles.length)}
        value={Math.min(normalizedWindowSize, candles.length)}
        onChange={(event) => {
          const next = Number(event.target.value);
          onWindowSizeChange(next);
          onWindowOffsetChange(clamp(windowOffset, 0, Math.max(0, candles.length - next)));
        }}
      />
      {candles.length > normalizedWindowSize ? (
        <input
          className="fa-chart-range"
          type="range"
          min={0}
          max={Math.max(0, candles.length - normalizedWindowSize)}
          value={windowOffset}
          onChange={(event) => onWindowOffsetChange(clamp(Number(event.target.value), 0, Math.max(0, candles.length - normalizedWindowSize)))}
        />
      ) : null}
    </div>
  );
}

export function PriceLineChartEdgeLabels({
  firstLabel,
  lastLabel,
}: {
  firstLabel: string;
  lastLabel: string;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 9, color: "var(--fg-5)" }}>
      <span>{firstLabel}</span>
      <span>{lastLabel}</span>
    </div>
  );
}

export function PriceLineChartEmptyState({
  height,
  loading,
  errorText,
  emptyText,
}: {
  height: number;
  loading: boolean;
  errorText: string | null;
  emptyText: string;
}) {
  return (
    <div style={{ padding: "28px 12px", textAlign: "center", fontSize: 11, color: "var(--fg-4)", minHeight: height }}>
      {loading ? "历史数据加载中" : errorText ?? emptyText}
    </div>
  );
}
