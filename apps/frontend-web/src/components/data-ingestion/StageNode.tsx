import type { PipelineStageStatus } from "@/types/data-ingestion";

interface StageNodeProps {
  status: PipelineStageStatus;
  label?: string;
  message?: string;
  compact?: boolean;
  onClick?: () => void;
}

/** Status → color token mapping */
const STATUS_COLORS: Record<PipelineStageStatus, { bg: string; fg: string; glow?: string; border: string }> = {
  OK:          { bg: "rgba(16,185,129,0.15)",  fg: "#10b981", glow: "0 0 8px rgba(16,185,129,0.25)", border: "rgba(16,185,129,0.3)" },
  READY:       { bg: "rgba(16,185,129,0.20)",  fg: "#34d399", glow: "0 0 10px rgba(16,185,129,0.35)", border: "rgba(52,211,153,0.4)" },
  WARN:        { bg: "rgba(245,158,11,0.12)",  fg: "#f59e0b", border: "rgba(245,158,11,0.25)" },
  PARTIAL:     { bg: "rgba(167,139,250,0.12)", fg: "#a78bfa", border: "rgba(167,139,250,0.25)" },
  ERROR:       { bg: "rgba(239,68,68,0.12)",   fg: "#ef4444", border: "rgba(239,68,68,0.28)" },
  BLOCKED:     { bg: "rgba(127,29,29,0.15)",   fg: "#dc2626", border: "rgba(220,38,38,0.3)" },
  WAITING:     { bg: "rgba(74,85,128,0.12)",   fg: "#90a6c4", border: "rgba(144,166,196,0.2)" },
  NO_DATA:     { bg: "rgba(156,163,175,0.08)", fg: "#9ca3af", border: "rgba(156,163,175,0.15)" },
  NO_SNAPSHOT: { bg: "rgba(107,114,128,0.08)", fg: "#6b7280", border: "rgba(107,114,128,0.15)" },
  SKIPPED:     { bg: "transparent",             fg: "#374151", border: "rgba(55,65,81,0.15)" },
};

/** Short label for the node */
const STATUS_SHORT: Record<PipelineStageStatus, string> = {
  OK: "OK",
  READY: "RDY",
  WARN: "WARN",
  PARTIAL: "PRTL",
  ERROR: "ERR",
  BLOCKED: "BLK",
  WAITING: "WAIT",
  NO_DATA: "N/A",
  NO_SNAPSHOT: "—",
  SKIPPED: "SKIP",
};

export function StageNode({ status, label, message, compact = false, onClick }: StageNodeProps) {
  const colors = STATUS_COLORS[status] ?? STATUS_COLORS.NO_DATA;
  const short = STATUS_SHORT[status] ?? "?";
  const tip = [label, message, status].filter(Boolean).join(" · ");

  return (
    <div
      className="inline-flex items-center justify-center rounded font-semibold transition-all select-none"
      style={{
        background: colors.bg,
        color: colors.fg,
        border: `1px solid ${colors.border}`,
        boxShadow: colors.glow ?? "none",
        width: compact ? 32 : 48,
        height: compact ? 18 : 26,
        fontSize: compact ? 8 : 9,
        letterSpacing: "0.04em",
        cursor: onClick ? "pointer" : "default",
      }}
      title={tip}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {short}
    </div>
  );
}
