import { Hexagon, Info } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { EventFlowRadarAxis } from "@/types/event-flow";

function radarPoint(idx: number, total: number, pct: number, cx: number, cy: number, maxR: number): [number, number] {
  const angle = (idx / total) * 2 * Math.PI - Math.PI / 2;
  const r = maxR * pct;
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

interface RiskRadarProps {
  radar: EventFlowRadarAxis[];
}

export function RiskRadar({ radar }: RiskRadarProps) {
  if (radar.length === 0) {
    return (
      <FACard title="当前风险雷达" eyebrow="风险雷达" accent="brand">
        <FAEmptyState title="暂无风险数据" description="当前没有风险雷达数据。" className="p-4" />
      </FACard>
    );
  }

  const S = 240;
  const cx = S / 2;
  const cy = S / 2;
  const maxR = S * 0.26;
  const N = radar.length;
  const gridLevels = [0.25, 0.5, 0.75, 1];
  const dataPoints = radar.map((ax, i) => radarPoint(i, N, ax.value / 100, cx, cy, maxR).join(",")).join(" ");

  // Compute average score
  const avgScore = Math.round(radar.reduce((sum, ax) => sum + ax.value, 0) / N);

  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <Hexagon size={12} className="text-[var(--brand-hover)]" />
          <span>当前风险雷达</span>
          <Info size={11} className="text-[var(--fg-6)]" />
        </div>
      }
      eyebrow="风险雷达"
      accent="brand"
      className="flex min-h-0 flex-1 flex-col"
      bodyClassName="flex min-h-0 flex-1 items-center justify-center"
    >
      <div className="flex justify-center">
        <svg width={S} height={S} viewBox={`0 0 ${S} ${S}`}>
          {/* Grid rings */}
          {gridLevels.map((lvl) => {
            const pts = radar.map((_, i) => radarPoint(i, N, lvl, cx, cy, maxR).join(",")).join(" ");
            return <polygon key={lvl} points={pts} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={0.7} />;
          })}

          {/* Axis lines */}
          {radar.map((_, i) => {
            const [ex, ey] = radarPoint(i, N, 1, cx, cy, maxR);
            return <line key={i} x1={cx} y1={cy} x2={ex} y2={ey} stroke="rgba(255,255,255,0.10)" strokeWidth={0.7} />;
          })}

          {/* Data area */}
          <polygon points={dataPoints} fill="rgba(59,130,246,0.28)" stroke="#60a5fa" strokeWidth={1.8} />

          {/* Data points */}
          {radar.map((ax, i) => {
            const [dx, dy] = radarPoint(i, N, ax.value / 100, cx, cy, maxR);
            return <circle key={i} cx={dx} cy={dy} r={3} fill="#60a5fa" />;
          })}

          {/* Labels */}
          {radar.map((ax, i) => {
            const [lx, ly] = radarPoint(i, N, 1.35, cx, cy, maxR);
            const anchor = lx < cx - 8 ? "end" : lx > cx + 8 ? "start" : "middle";
            return (
              <g key={i}>
                <text x={lx} y={ly - 4} textAnchor={anchor} fontSize={8} fill="var(--fg-2)" fontFamily="var(--font-sans)">
                  {ax.label}
                </text>
                <text
                  x={lx}
                  y={ly + 8}
                  textAnchor={anchor}
                  fontSize={10}
                  fill="var(--fg-1)"
                  fontFamily="var(--font-mono)"
                  fontWeight="600"
                >
                  {ax.value}
                </text>
              </g>
            );
          })}

          {/* Center score */}
          <text x={cx} y={cy - 7} textAnchor="middle" fontSize={8} fill="var(--fg-3)" fontFamily="var(--font-sans)">
            风险综合评分
          </text>
          <text x={cx} y={cy + 10} textAnchor="middle" fontSize={18} fill="#f59e0b" fontFamily="var(--font-mono)" fontWeight="700">
            {avgScore}
          </text>
          <text x={cx} y={cy + 21} textAnchor="middle" fontSize={8} fill="var(--fg-4)" fontFamily="var(--font-sans)">
            /100
          </text>
        </svg>
      </div>
    </FACard>
  );
}
