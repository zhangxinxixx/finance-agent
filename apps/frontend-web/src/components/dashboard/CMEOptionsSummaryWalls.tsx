import type { WallLevel } from "@/types/dashboard";

export function CMEOptionsSummaryWalls({
  resistance,
  support,
}: {
  resistance: WallLevel[];
  support: WallLevel[];
}) {
  if (resistance.length === 0 && support.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-2">
      <div
        className="rounded border px-2.5 py-2"
        style={{
          borderColor: "var(--border-faint)",
          background: "var(--bg-card-inner)",
        }}
      >
        <div
          style={{
            fontSize: "8px",
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: "var(--fg-5)",
            textTransform: "uppercase" as const,
            marginBottom: "6px",
          }}
        >
          关键阻力
        </div>
        <div className="space-y-1">
          {resistance.length > 0 ? (
            resistance.map((wall, index) => (
              <div key={`res-${wall.strike}-${index}`} className="flex items-center justify-between gap-2">
                <span className="fa-num" style={{ fontSize: "10px", fontWeight: 700, color: "var(--down)" }}>
                  {wall.strike.toLocaleString("en-US")}
                </span>
                <span style={{ fontSize: "9px", color: "var(--fg-5)" }}>{wall.distance_pct.toFixed(1)}%</span>
              </div>
            ))
          ) : (
            <div style={{ fontSize: "9px", color: "var(--fg-5)" }}>暂无阻力墙</div>
          )}
        </div>
      </div>
      <div
        className="rounded border px-2.5 py-2"
        style={{
          borderColor: "var(--border-faint)",
          background: "var(--bg-card-inner)",
        }}
      >
        <div
          style={{
            fontSize: "8px",
            fontWeight: 600,
            letterSpacing: "0.06em",
            color: "var(--fg-5)",
            textTransform: "uppercase" as const,
            marginBottom: "6px",
          }}
        >
          关键支撑
        </div>
        <div className="space-y-1">
          {support.length > 0 ? (
            support.map((wall, index) => (
              <div key={`sup-${wall.strike}-${index}`} className="flex items-center justify-between gap-2">
                <span className="fa-num" style={{ fontSize: "10px", fontWeight: 700, color: "var(--up)" }}>
                  {wall.strike.toLocaleString("en-US")}
                </span>
                <span style={{ fontSize: "9px", color: "var(--fg-5)" }}>{wall.distance_pct.toFixed(1)}%</span>
              </div>
            ))
          ) : (
            <div style={{ fontSize: "9px", color: "var(--fg-5)" }}>暂无支撑墙</div>
          )}
        </div>
      </div>
    </div>
  );
}
