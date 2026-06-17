import { Grid3x3 } from "lucide-react";
import type { MarketMonitorMetric } from "@/types/market-monitor";
import { HeatmapCell } from "./HeatmapCell";
import { HEATMAP_GRID } from "./heatmapModel";

interface HeatmapProps {
  metrics: MarketMonitorMetric[];
}

export function Heatmap({ metrics }: HeatmapProps) {
  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-faint)",
        borderRadius: "var(--radius-lg)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div className="flex items-center gap-2">
          <Grid3x3 size={13} style={{ color: "var(--brand-hover)" }} />
          <div>
            <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 10, color: "var(--fg-2)", lineHeight: 1 }}>
              跨资产联动热力图
            </div>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--fg-5)", marginTop: 2 }}>
              日度涨跌幅
            </div>
          </div>
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            padding: "2px 6px",
            borderRadius: 3,
            border: "1px solid var(--border-faint)",
            color: "var(--fg-5)",
            background: "var(--bg-card-inner)",
          }}
        >
          1W
        </span>
      </div>

      {/* Grid */}
      <div style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
        {HEATMAP_GRID.map((row, rowIdx) => {
          const isLastRow = rowIdx === HEATMAP_GRID.length - 1;
          return (
            <div
              key={`row-${rowIdx}`}
              style={{
                display: "grid",
                gridTemplateColumns: isLastRow ? "1fr 1fr" : "repeat(4,1fr)",
                gap: 6,
              }}
            >
              {row.map((cell) => <HeatmapCell key={cell.key} cell={cell} metrics={metrics} />)}
            </div>
          );
        })}
      </div>

      {/* Legend bar */}
      <div
        style={{
          padding: "6px 12px 8px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderTop: "1px solid var(--border-faint)",
        }}
      >
        <div className="flex items-center gap-1.5">
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(240,82,82,0.25)", display: "inline-block" }} />
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 8.5, color: "var(--fg-5)" }}>&lt;-1%</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(240,82,82,0.12)", display: "inline-block" }} />
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 8.5, color: "var(--fg-5)" }}>-1~0%</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(16,185,129,0.12)", display: "inline-block" }} />
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 8.5, color: "var(--fg-5)" }}>0~1%</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(16,185,129,0.25)", display: "inline-block" }} />
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 8.5, color: "var(--fg-5)" }}>&gt;1%</span>
        </div>
      </div>
    </div>
  );
}

export default Heatmap;
