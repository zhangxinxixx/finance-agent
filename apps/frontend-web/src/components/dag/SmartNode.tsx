// ── SmartNode Component ──────────────────────────────────────
// 语义化 DAG 节点：状态灯 + 类型标识 + 延迟 + 进度条 + 血缘高亮

import { memo } from "react";
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

// ═══════════════════════════════════════════════════════════════
//  SmartNode
// ═══════════════════════════════════════════════════════════════

export const SmartNode = memo(function SmartNode({ data }: { data: any }) {
  const spec: DagNodeSpec = data.node_spec;
  const color = STAGE_COLORS_SMART[spec.type] || "#94a3b8";
  const icon = STAGE_ICONS[spec.type] || "●";
  const stageLabel = STAGE_LABELS_SMART[spec.type] || spec.type;
  const st = STATUS_STYLE[spec.status] || STATUS_STYLE.pending;

  // Lineage highlight
  const hl = data.highlighted as string | undefined;
  const borderHl = hl === "selected"
    ? `0 0 0 2px var(--brand-gold), inset 0 0 0 1px var(--brand-gold)`
    : hl === "upstream" || hl === "downstream"
    ? "0 0 0 1px var(--brand-gold)/30"
    : "none";

  // Progress: use execution duration as proxy
  const durationStr = formatDuration(spec.execution.duration_ms);
  const hasDuration = spec.execution.duration_ms != null;

  return (
    <div
      className="rounded-lg border shadow-sm cursor-pointer transition-all duration-200 hover:scale-[1.02]"
      style={{
        background: "var(--bg-card)",
        borderColor: `${color}40`,
        borderLeftWidth: 4,
        borderLeftColor: color,
        minWidth: 190,
        maxWidth: 240,
        boxShadow: borderHl,
      }}
    >
      {/* ── Top: Status + Label ── */}
      <div className="flex items-center gap-2 px-3 pt-2.5">
        {/* Status dot */}
        <div className="relative shrink-0">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: st.dot }}
          />
          {spec.status === "running" && (
            <div
              className="absolute inset-0 rounded-full animate-ping opacity-40"
              style={{ background: st.dot }}
            />
          )}
        </div>
        <span className="text-[10px] font-bold text-[var(--fg-2)] truncate flex-1 leading-tight">
          {spec.label}
        </span>
      </div>

      {/* ── Middle: Type icon + sub_type + latency ── */}
      <div className="flex items-center gap-1.5 px-3 pt-1.5 text-[8px]">
        <span className="text-[10px] leading-none">{icon}</span>
        <span
          className="rounded-sm px-1 py-px font-semibold"
          style={{ background: `${color}15`, color }}
        >
          {stageLabel}
        </span>
        <span className="font-mono text-[var(--fg-5)]">{spec.sub_type}</span>
        {hasDuration && (
          <span className="ml-auto font-mono text-[var(--fg-4)] tabular-nums">
            {durationStr}
          </span>
        )}
      </div>

      {/* ── Bottom: Status bar ── */}
      <div className="px-3 pb-2.5 pt-1.5">
        {/* Progress pill */}
        <div className="flex items-center gap-1.5">
          <div
            className="flex-1 h-1 rounded-full overflow-hidden"
            style={{ background: "var(--bg-card-inner)" }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: spec.status === "success" ? "100%"
                     : spec.status === "running" ? "60%"
                     : spec.status === "failed" ? "100%"
                     : spec.status === "partial" ? "50%"
                     : "20%",
                background: spec.status === "failed" ? "var(--down)"
                          : spec.status === "running" ? color
                          : spec.status === "success" ? "var(--up)"
                          : "var(--fg-5)",
              }}
            />
          </div>
          <span className="text-[7px] font-semibold shrink-0" style={{ color: st.text }}>
            {statusLabel(spec.status)}
          </span>
        </div>
      </div>
    </div>
  );
});

export { STAGE_COLORS_SMART as SMART_NODE_COLORS, STAGE_ICONS, STAGE_LABELS_SMART };

export default SmartNode;
