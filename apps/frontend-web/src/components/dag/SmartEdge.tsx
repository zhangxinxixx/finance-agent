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

const STATUS_EDGE_STYLE: Record<string, { stroke: string; opacity: number; label: string; dash: string }> = {
  success: { stroke: "var(--up)", opacity: 0.82, label: "ok", dash: "" },
  running: { stroke: "var(--warn)", opacity: 0.9, label: "run", dash: "8 6" },
  failed: { stroke: "var(--down)", opacity: 0.92, label: "fail", dash: "5 4" },
  partial: { stroke: "#f59e0b", opacity: 0.86, label: "partial", dash: "8 5" },
  pending: { stroke: "var(--fg-5)", opacity: 0.42, label: "wait", dash: "3 7" },
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
  const rawStatus: unknown = data?.edge_status ?? (data?.data_contract as any)?.status;
  const statusStyle = typeof rawStatus === "string" ? STATUS_EDGE_STYLE[rawStatus] : undefined;
  const rawLineageState: unknown = data?.lineage_state;
  const lineageState = typeof rawLineageState === "string" ? rawLineageState : undefined;
  const lineageActive = lineageState === "upstream" || lineageState === "downstream" || lineageState === "selected";
  const lineageDim = lineageState === "dim";
  const lineageStroke =
    lineageState === "upstream" ? "#38bdf8" :
    lineageState === "downstream" ? "var(--brand-gold)" :
    lineageState === "selected" ? "#f8fafc" :
    null;
  const stroke = lineageStroke ?? statusStyle?.stroke ?? es.stroke;
  const strokeOpacity = lineageDim ? 0.1 : lineageActive ? 0.98 : statusStyle?.opacity ?? es.opacity;
  const strokeDasharray = lineageActive ? (lineageState === "upstream" ? "10 5" : "14 6") : statusStyle?.dash || es.dash;
  const label = lineageState === "upstream" ? "up"
    : lineageState === "downstream" ? "down"
    : lineageState === "selected" ? "focus"
    : statusStyle?.label ?? EDGE_LABEL[edgeType];

  // Arrow color matches edge stroke
  const coloredMarker = markerEnd
    ? { ...markerEnd as any, color: stroke }
    : undefined;

  return (
    <g>
      <path
        d={edgePath}
        fill="none"
        stroke={stroke}
        strokeWidth={lineageActive ? 11 : selected ? 8 : 6}
        strokeOpacity={lineageDim ? 0.02 : lineageActive ? 0.3 : selected ? 0.22 : 0.12}
        strokeLinecap="round"
        filter="url(#dag-edge-glow)"
      />
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke,
          strokeWidth: lineageActive ? 3.8 : selected ? 3.2 : 2.3,
          strokeOpacity,
          strokeDasharray,
          strokeLinecap: "round",
          ...style,
        }}
        markerEnd={coloredMarker}
      />

      <path
        d={edgePath}
        fill="none"
        stroke={lineageActive ? stroke : rawStatus === "pending" ? "rgba(255,255,255,0.38)" : "rgba(255,255,255,0.72)"}
        strokeWidth={lineageActive ? 1.9 : selected ? 1.6 : 1.15}
        strokeOpacity={lineageDim ? 0.08 : lineageActive ? 0.95 : rawStatus === "pending" ? 0.28 : selected ? 0.9 : 0.55}
        strokeLinecap="round"
        strokeDasharray={lineageActive ? "16 18" : rawStatus === "pending" ? "2 18" : edgeType === "data_flow" ? "12 18" : edgeType === "signal_flow" ? "8 16" : "6 20"}
      >
        {!lineageDim && (lineageActive || rawStatus !== "pending") && (
          <animate
            attributeName="stroke-dashoffset"
            from={lineageState === "upstream" ? "0" : "120"}
            to="0"
            dur={lineageActive ? "0.75s" : selected ? "0.9s" : edgeType === "data_flow" ? "1.8s" : "2.4s"}
            repeatCount="indefinite"
          />
        )}
      </path>

      {/* Edge type label */}
      <foreignObject
        width={52}
        height={18}
        x={labelX - 26}
        y={labelY - 9}
        className="overflow-visible"
        style={{ pointerEvents: "none" }}
      >
        <div
          className="flex items-center justify-center rounded-full text-[7px] font-semibold leading-none shadow-sm backdrop-blur-sm"
          style={{
            background: "color-mix(in srgb, var(--bg-card) 92%, transparent)",
            border: `1px solid ${stroke}aa`,
            color: stroke,
            padding: "2px 6px",
            opacity: lineageDim ? 0.08 : lineageActive ? 1 : strokeOpacity,
            boxShadow: `0 0 22px -14px ${stroke}`,
          }}
        >
          {label}
        </div>
      </foreignObject>
    </g>
  );
});

export { EDGE_STYLE, EDGE_LABEL };

export default SmartEdge;
