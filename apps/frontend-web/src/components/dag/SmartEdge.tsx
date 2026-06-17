// ── SmartEdge Component ──────────────────────────────────────
// 语义化 DAG 边：data_flow / signal_flow / dependency / override

import { memo } from "react";
import {
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";

export type SmartEdgeType = "data_flow" | "signal_flow" | "dependency" | "override";

const EDGE_STYLE: Record<SmartEdgeType, { stroke: string; opacity: number; dash: string }> = {
  data_flow:   { stroke: "var(--up)",       opacity: 0.7, dash: "" },
  signal_flow: { stroke: "var(--warn)",     opacity: 0.9, dash: "4 2" },
  dependency:  { stroke: "var(--brand)",    opacity: 0.5, dash: "2 2" },
  override:    { stroke: "var(--down)",     opacity: 0.6, dash: "6 2" },
};

const EDGE_LABEL: Record<SmartEdgeType, string> = {
  data_flow:   "data",
  signal_flow: "signal",
  dependency:  "dep",
  override:    "override",
};

export const SmartEdge = memo(function SmartEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  style,
  markerEnd,
  selected,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const rawEdgeType: unknown = data?.edge_type;
  const edgeType: SmartEdgeType = (typeof rawEdgeType === "string" && ["data_flow","signal_flow","dependency","override"].includes(rawEdgeType))
    ? rawEdgeType as SmartEdgeType
    : "data_flow";
  const es = EDGE_STYLE[edgeType];

  // Arrow color matches edge stroke
  const coloredMarker = markerEnd
    ? { ...markerEnd as any, color: es.stroke }
    : undefined;

  return (
    <g>
      {/* Base edge */}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: es.stroke,
          strokeWidth: selected ? 3 : 2,
          strokeOpacity: es.opacity,
          strokeDasharray: es.dash,
          animation: selected ? "none" : undefined,
          ...style,
        }}
        markerEnd={coloredMarker}
      />

      {/* Edge type label */}
      <foreignObject
        width={36}
        height={14}
        x={labelX - 18}
        y={labelY - 7}
        className="overflow-visible"
        style={{ pointerEvents: "none" }}
      >
        <div
          className="flex items-center justify-center rounded text-[7px] font-semibold leading-none"
          style={{
            background: "var(--bg-card)",
            border: `1px solid ${es.stroke}`,
            color: es.stroke,
            padding: "1px 4px",
            opacity: es.opacity,
          }}
        >
          {EDGE_LABEL[edgeType]}
        </div>
      </foreignObject>
    </g>
  );
});

export { EDGE_STYLE, EDGE_LABEL };

export default SmartEdge;
