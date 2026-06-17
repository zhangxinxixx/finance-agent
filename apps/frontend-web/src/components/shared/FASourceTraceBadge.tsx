import type { ReactNode } from "react";
import { GitBranch } from "lucide-react";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";
import { getStatusMeta } from "./statusMeta";

interface FASourceTraceBadgeProps {
  source: ReactNode;
  status?: ReactNode;
  tone?: FAStatusTone;
  snapshotId?: string | null;
  className?: string;
}

function displayTraceText(value: ReactNode): ReactNode {
  if (typeof value !== "string" && typeof value !== "number") return value;
  const text = String(value).trim();
  const exact: Record<string, string> = {
    api: "真实接口",
    macro_latest: "宏观最新快照",
    source_api: "来源接口",
  };
  const lower = text.toLowerCase();
  if (exact[lower]) return exact[lower];

  const dataSourceMatch = text.match(/^Data source ([^:]+):\s*(.+)$/i);
  if (dataSourceMatch) {
    const sourceMap: Record<string, string> = {
      bls_calendar: "BLS 日历",
      openbb_macro: "OpenBB 宏观",
    };
    const statusMeta = getStatusMeta(dataSourceMatch[2], { domain: "source" });
    return `${sourceMap[dataSourceMatch[1]] ?? dataSourceMatch[1]}：${statusMeta.label}`;
  }

  if (/^CME data source:\s*PRELIM/i.test(text)) {
    return "CME 数据：初步数据（建议使用最终数据）";
  }

  return text;
}

export function FASourceTraceBadge({ source, status = "trace", tone, snapshotId, className = "" }: FASourceTraceBadgeProps) {
  const statusMeta = typeof status === "string" || typeof status === "number" ? getStatusMeta(String(status), { domain: "source" }) : null;
  const resolvedTone = tone ?? statusMeta?.tone ?? "info";
  const displaySource = displayTraceText(source);

  return (
    <span
      className={`inline-flex min-w-0 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1 text-[10px] text-[var(--fg-4)] ${className}`}
      title={snapshotId ?? undefined}
    >
      <GitBranch size={11} className="shrink-0 text-[var(--brand-hover)]" />
      <span className="truncate">{displaySource}</span>
      <FAStatusPill tone={resolvedTone} dot={false}>
        {statusMeta?.label ?? status}
      </FAStatusPill>
    </span>
  );
}
