import type { PipelineStageStatus } from "@/types/data-ingestion";

interface StageConnectorProps {
  fromStatus: PipelineStageStatus;
  toStatus: PipelineStageStatus;
  compact?: boolean;
}

const TERMINAL = new Set<PipelineStageStatus>(["ERROR", "BLOCKED", "NO_DATA", "SKIPPED"]);
const DEGRADED = new Set<PipelineStageStatus>(["WARN", "PARTIAL", "NO_SNAPSHOT", "WAITING"]);
const HEALTHY  = new Set<PipelineStageStatus>(["OK", "READY"]);

function pickColor(from: PipelineStageStatus, to: PipelineStageStatus): string {
  if (TERMINAL.has(from)) return "rgba(220,38,38,0.24)";
  if (TERMINAL.has(to))   return "rgba(220,38,38,0.18)";
  if (DEGRADED.has(from) || DEGRADED.has(to)) return "rgba(217,119,6,0.22)";
  if (HEALTHY.has(from) && HEALTHY.has(to))   return "rgba(5,150,105,0.22)";
  return "rgba(148,163,184,0.22)";
}

function pickDash(from: PipelineStageStatus, to: PipelineStageStatus): string | undefined {
  if (TERMINAL.has(from) || TERMINAL.has(to)) return "3 2";
  if (DEGRADED.has(from) && HEALTHY.has(to))  return "4 2";
  return undefined;
}

export function StageConnector({ fromStatus, toStatus, compact = false }: StageConnectorProps) {
  const color = pickColor(fromStatus, toStatus);
  const dash = pickDash(fromStatus, toStatus);
  const width = compact ? 8 : 12;
  const height = compact ? 22 : 26;
  const midY = height / 2;
  const arrowX = compact ? 5.5 : 8;

  return (
    <div className="inline-flex items-center shrink-0" style={{ width, height }}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <line
          x1="0" y1={midY} x2={arrowX} y2={midY}
          stroke={color}
          strokeWidth={1.5}
          strokeDasharray={dash}
        />
        <path
          d={`M${arrowX} ${midY - 3} L${width} ${midY} L${arrowX} ${midY + 3}`}
          fill="none"
          stroke={color}
          strokeWidth={1.2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
