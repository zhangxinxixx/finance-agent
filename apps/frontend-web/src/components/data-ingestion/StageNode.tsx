import type { PipelineStageStatus } from "@/types/data-ingestion";

interface StageNodeProps {
  status: PipelineStageStatus;
  label?: string;
  message?: string;
  compact?: boolean;
  onClick?: () => void;
}

/** Status → color token mapping */
const STATUS_COLORS: Record<PipelineStageStatus, { bg: string; fg: string; border: string }> = {
  OK:          { bg: "var(--up-soft)",   fg: "var(--up)",   border: "var(--up-border)" },
  READY:       { bg: "var(--up-soft)",   fg: "var(--up)",   border: "var(--up-border)" },
  WARN:        { bg: "var(--warn-soft)", fg: "var(--warn)", border: "var(--warn-border)" },
  PARTIAL:     { bg: "var(--info-soft)", fg: "var(--info)", border: "var(--info-border)" },
  ERROR:       { bg: "var(--down-soft)", fg: "var(--down)", border: "var(--down-border)" },
  BLOCKED:     { bg: "var(--down-soft)", fg: "var(--down)", border: "var(--down-border)" },
  WAITING:     { bg: "var(--bg-card-inner)", fg: "var(--fg-5)", border: "var(--border-faint)" },
  NO_DATA:     { bg: "var(--bg-card-inner)", fg: "var(--fg-5)", border: "var(--border-faint)" },
  NO_SNAPSHOT: { bg: "var(--bg-card-inner)", fg: "var(--fg-5)", border: "var(--border-faint)" },
  SKIPPED:     { bg: "transparent",      fg: "var(--fg-5)", border: "var(--border-faint)" },
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
      className="data-ingestion-stage-node inline-flex items-center justify-center rounded font-semibold transition-all select-none"
      style={{
        background: colors.bg,
        color: colors.fg,
        border: `1px solid ${colors.border}`,
        boxShadow: "none",
        width: compact ? 38 : 56,
        height: compact ? 20 : 28,
        fontSize: compact ? 9.5 : 11,
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
