import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { AlertTriangle } from "lucide-react";

interface CriticalAlertBannerProps {
  sources: DataSourceStatusViewModel[];
}

export function CriticalAlertBanner({ sources }: CriticalAlertBannerProps) {
  const blockers = sources.filter((s) => s.status === "error" || s.status === "unavailable");

  if (blockers.length === 0) return null;

  const names = blockers.map((b) => b.label).join(" · ");
  const details = blockers
    .slice(0, 3)
    .map((b) => b.error_message || b.status_reason || "异常")
    .join(" / ");

  return (
    <div
      className="flex items-center gap-2 rounded-[var(--radius-md)] px-3 py-2 shrink-0"
      style={{
        background: "rgba(239,68,68,0.08)",
        border: "1px solid rgba(239,68,68,0.2)",
      }}
    >
      <AlertTriangle size={12} className="text-[var(--down)] shrink-0" />
      <span className="text-[10px] font-semibold text-[var(--down)]">
        {blockers.length} 个关键阻塞:
      </span>
      <span className="text-[10px] text-[var(--fg-3)] truncate flex-1">{names}</span>
      <span className="text-[9px] text-[var(--fg-5)] shrink-0 hidden md:block">{details}</span>
    </div>
  );
}
