import { useDataStatus } from "../../hooks/useDataStatus";
import type { DataOverallStatus } from "../../types/dashboard";
import { FAStatusPill } from "./FAStatusPill";
import { getStatusMeta } from "./statusMeta";

const SOURCE_SHORT: Record<string, string> = {
  CME: "CME",
  FRED: "FRED",
  Treasury: "美债",
  Fed: "美联储",
};

export function DataStatusBar() {
  const { data, isError, refetch } = useDataStatus();
  const overallStatus = isError ? "UNAVAILABLE" : data.overall_status;
  const overallMeta = getStatusMeta(overallStatus);
  const pulse = overallStatus === "MOCK";

  const sources = data.sources.filter((s) => s.status === "LIVE" || s.status === "PARTIAL").slice(0, 4);

  return (
    <div className="status-bar">
      <div className="statusbar-group">
        <FAStatusPill
          status={overallStatus}
          tone={overallMeta.tone}
          className={`statusbar-trigger statusbar-source ${pulse ? "animate-pulse" : ""}`}
        >
          {overallMeta.label}
        </FAStatusPill>
      </div>

      <div className="statusbar-sep" />

      <div className="statusbar-group">
        {sources.map((src) => (
          <div key={src.name} className="flex items-center gap-1.5 rounded-full border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1">
            <div className={`h-1.5 w-1.5 rounded-full ${getStatusMeta(src.status).tone === "up" ? "bg-finance-bullish" : "bg-finance-warning"}`} />
            <span className="text-[10px]">{SOURCE_SHORT[src.name] || src.name.slice(0, 4)}</span>
          </div>
        ))}
      </div>

      <div className="flex-1" />

      {isError && (
        <button type="button" className="statusbar-trigger statusbar-queue text-finance-accent-soft hover:text-finance-accent" onClick={refetch}>
          重试
        </button>
      )}
    </div>
  );
}
