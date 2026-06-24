// ── SmartNode Component ──────────────────────────────────────
// 语义化 DAG 节点：状态灯 + 类型标识 + 延迟 + 进度条 + 血缘高亮

import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { DagNodeSpec, DagNodeType } from "@/types/pipeline-dag";

// ── Stage config ──
const STAGE_ICONS: Record<DagNodeType, string> = {
  collector: "📡",
  parser:    "🔧",
  features:  "📊",
  analysis:  "🧠",
  output:    "📄",
};

const STAGE_COLORS_SMART: Record<DagNodeType, string> = {
  collector: "#3b82f6",
  parser:    "#f59e0b",
  features:  "#8b5cf6",
  analysis:  "#10b981",
  output:    "#06b6d4",
};

const STAGE_LABELS_SMART: Record<DagNodeType, string> = {
  collector: "采集",
  parser:    "解析",
  features:  "特征",
  analysis:  "分析",
  output:    "输出",
};

const STATUS_STYLE: Record<string, { dot: string; text: string; bg: string }> = {
  success:  { dot: "var(--up)",      text: "var(--up)",      bg: "var(--color-up-subtle)" },
  running:  { dot: "var(--warn)",    text: "var(--warn)",    bg: "var(--color-warn-subtle)" },
  failed:   { dot: "var(--down)",    text: "var(--down)",    bg: "var(--color-down-subtle)" },
  pending:  { dot: "var(--fg-5)",    text: "var(--fg-4)",    bg: "var(--bg-card-inner)" },
  partial:  { dot: "#f59e0b",        text: "#d97706",        bg: "#fef3c7" },
};

// ── Helper ──
function statusLabel(s: string): string {
  const m: Record<string, string> = {
    success: "成功", running: "运行中", failed: "失败", pending: "等待", partial: "部分",
  };
  return m[s] || s;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function hexToRgba(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  if (value.length !== 6) return `rgba(148,163,184,${alpha})`;
  const int = Number.parseInt(value, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ═══════════════════════════════════════════════════════════════
//  SmartNode
// ═══════════════════════════════════════════════════════════════

export const SmartNode = memo(function SmartNode({ data }: { data: any }) {
  const spec: DagNodeSpec = data.node_spec;
  const sequenceIndex = typeof data.sequence_index === "number" ? data.sequence_index as number : null;
  const color = STAGE_COLORS_SMART[spec.type] || "#94a3b8";
  const icon = STAGE_ICONS[spec.type] || "●";
  const stageLabel = STAGE_LABELS_SMART[spec.type] || spec.type;
  const st = STATUS_STYLE[spec.status] || STATUS_STYLE.pending;
  const upstreamCount = spec.upstream_ids?.length ?? 0;
  const downstreamCount = spec.downstream_ids?.length ?? 0;
  const matchedCount = Number(spec.output.fields.task_count ?? spec.output.fields.op_count ?? spec.input.fields.task_count ?? spec.input.fields.op_count ?? 0);
  const summary = spec.output.summary || spec.input.summary;

  // Lineage highlight
  const hl = data.highlighted as string | undefined;
  const borderHl = hl === "selected"
    ? `0 0 0 1px rgba(240, 200, 80, 0.95), 0 0 28px rgba(240, 200, 80, 0.28), inset 0 0 0 1px rgba(240, 200, 80, 0.85)`
    : hl === "upstream" || hl === "downstream"
    ? "0 0 0 1px rgba(240, 200, 80, 0.35), 0 0 18px rgba(240, 200, 80, 0.12)"
    : `0 18px 34px -26px ${color}88`;

  // Progress: use execution duration as proxy
  const durationStr = formatDuration(spec.execution.duration_ms);
  const hasDuration = spec.execution.duration_ms != null;
  const progressWidth = spec.status === "success" ? "100%"
    : spec.status === "running" ? "72%"
    : spec.status === "failed" ? "100%"
    : spec.status === "partial" ? "50%"
    : "22%";
  const progressColor = spec.status === "failed" ? "var(--down)"
    : spec.status === "running" ? color
    : spec.status === "success" ? "var(--up)"
    : "var(--fg-5)";

  return (
    <div
      className="group relative overflow-visible rounded-[16px] border cursor-pointer transition-all duration-300 hover:-translate-y-1 hover:scale-[1.015]"
      style={{
        background: `linear-gradient(165deg, ${hexToRgba(color, 0.14)} 0%, var(--bg-card) 42%, ${hexToRgba(color, 0.08)} 100%)`,
        borderColor: `${color}55`,
        minWidth: 196,
        maxWidth: 206,
        boxShadow: borderHl,
        backdropFilter: "blur(14px)",
        opacity: hl === "dim" ? 0.36 : 1,
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!left-[-5px] !h-3 !w-3 !border !border-white/20 !bg-[rgba(8,12,20,0.92)]"
        style={{ boxShadow: `0 0 14px ${color}88` }}
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!right-[-5px] !h-3 !w-3 !border !border-white/20 !bg-[rgba(8,12,20,0.92)]"
        style={{ boxShadow: `0 0 14px ${color}88` }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-80"
        style={{
          background: `radial-gradient(circle at 14% 16%, ${color}30, transparent 34%), radial-gradient(circle at 86% 0%, rgba(255,255,255,0.1), transparent 28%)`,
        }}
      />
      <div className="pointer-events-none absolute inset-x-4 top-0 h-px bg-white/20" />
      <div className="pointer-events-none absolute -right-8 top-4 h-16 w-16 rounded-full blur-2xl opacity-45" style={{ background: color }} />

      {/* ── Top: Status + Label ── */}
      <div className="relative flex items-start gap-2.5 px-3 pt-3">
        <div
          className="shrink-0 rounded-[10px] border px-2 py-1.5 text-[13px] leading-none shadow-sm"
          style={{
            background: `${color}18`,
            borderColor: `${color}4d`,
            boxShadow: `inset 0 1px 0 rgba(255,255,255,0.12), 0 10px 18px -18px ${color}`,
          }}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {sequenceIndex != null && (
              <span className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] font-mono text-[var(--brand-gold)]">
                {String(sequenceIndex).padStart(2, "0")}
              </span>
            )}
            <div className="relative shrink-0">
              <div
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: st.dot, boxShadow: `0 0 14px ${st.dot}` }}
              />
              {spec.status === "running" && (
                <div
                  className="absolute inset-0 rounded-full animate-ping opacity-40"
                  style={{ background: st.dot }}
                />
              )}
            </div>
            <span className="text-[11px] font-semibold uppercase" style={{ color }}>
              {stageLabel}
            </span>
            <span
              className="ml-auto rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase"
              style={{ background: st.bg, color: st.text, borderColor: `${st.text}22` }}
            >
              {statusLabel(spec.status)}
            </span>
          </div>
          <div className="mt-2 text-[14px] font-bold leading-tight text-[var(--fg-1)]">
            {spec.label}
          </div>
          {hasDuration && (
            <div className="mt-1 text-[10px] font-mono tabular-nums text-[var(--fg-4)]">
              {durationStr}
            </div>
          )}
        </div>
      </div>

      <div className="relative px-3 pt-2.5">
        <div className="min-h-[34px] rounded-[10px] border border-white/8 bg-black/10 px-2.5 py-1.5">
          <div
            className="text-[10.5px] font-medium leading-snug text-[var(--fg-3)]"
            style={{
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {summary}
          </div>
        </div>
      </div>

      <div className="relative px-3 pb-3 pt-2.5">
        <div className="flex items-center gap-2">
          <div
            className="relative h-2.5 flex-1 overflow-hidden rounded-full"
            style={{ background: "rgba(255,255,255,0.07)" }}
          >
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: progressWidth,
                background: progressColor,
                boxShadow: `0 0 16px ${progressColor}`,
              }}
            />
            {spec.status === "running" && (
              <div
                className="absolute inset-y-0 left-0 w-16 opacity-80 dag-node-progress-sheen"
                style={{ background: `linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.0) 10%, rgba(255,255,255,0.6) 45%, transparent 100%)` }}
              />
            )}
          </div>
          <span className="shrink-0 text-[10px] font-semibold uppercase tabular-nums" style={{ color: st.text }}>
            {matchedCount > 0 ? `${matchedCount} run` : "idle"}
          </span>
        </div>
        <div className="mt-2 flex items-center justify-between text-[9px] font-mono uppercase text-[var(--fg-5)]">
          <span>in {upstreamCount}</span>
          <span style={{ color }}>{spec.module}</span>
          <span>out {downstreamCount}</span>
        </div>
      </div>
    </div>
  );
});

export { STAGE_COLORS_SMART as SMART_NODE_COLORS, STAGE_ICONS, STAGE_LABELS_SMART };

export default SmartNode;
