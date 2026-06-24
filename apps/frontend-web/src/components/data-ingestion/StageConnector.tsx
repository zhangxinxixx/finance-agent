import type { PipelineStageStatus } from "@/types/data-ingestion";

interface StageConnectorProps {
  fromStatus: PipelineStageStatus;
  toStatus: PipelineStageStatus;
}

const TERMINAL = new Set<PipelineStageStatus>(["ERROR", "BLOCKED", "NO_DATA", "SKIPPED"]);
const DEGRADED = new Set<PipelineStageStatus>(["WARN", "PARTIAL", "NO_SNAPSHOT", "WAITING"]);
const HEALTHY  = new Set<PipelineStageStatus>(["OK", "READY"]);

function pickColor(from: PipelineStageStatus, to: PipelineStageStatus): string {
  if (TERMINAL.has(from)) return "rgba(239,68,68,0.4)";
  if (TERMINAL.has(to))   return "rgba(239,68,68,0.25)";
  if (DEGRADED.has(from) || DEGRADED.has(to)) return "rgba(245,158,11,0.35)";
  if (HEALTHY.has(from) && HEALTHY.has(to))   return "rgba(16,185,129,0.4)";
  return "rgba(144,166,196,0.2)";
}

function pickDash(from: PipelineStageStatus, to: PipelineStageStatus): string | undefined {
  if (TERMINAL.has(from) || TERMINAL.has(to)) return "3 2";
  if (DEGRADED.has(from) && HEALTHY.has(to))  return "4 2";
  return undefined;
}

export function StageConnector({ fromStatus, toStatus }: StageConnectorProps) {
  const color = pickColor(fromStatus, toStatus);
  const dash = pickDash(fromStatus, toStatus);

  return (
    <div className="inline-flex items-center shrink-0" style={{ width: 12, height: 26 }}>
      <svg width="12" height="26" viewBox="0 0 12 26">
        <line
          x1="0" y1="13" x2="8" y2="13"
          stroke={color}
          strokeWidth={1.5}
          strokeDasharray={dash}
        />
        <path
          d="M8 9 L12 13 L8 17"
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
