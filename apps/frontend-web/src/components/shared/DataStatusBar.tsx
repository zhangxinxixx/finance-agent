import { useMemo } from "react";
import { useDataStatus } from "../../hooks/useDataStatus";
import { FAStatusPill } from "./FAStatusPill";
import { getStatusMeta } from "./statusMeta";

const SOURCE_SHORT: Record<string, string> = {
  CME: "CME",
  cme: "CME",
  FRED: "FRED",
  fred: "FRED",
  Treasury: "美债",
  treasury: "美债",
  Fed: "美联储",
  fed: "美联储",
  OpenBB: "宏观",
  openbb_macro: "宏观",
  open: "宏观",
};

export function DataStatusBar() {
  const { data, isError, refetch } = useDataStatus();
  const overallStatus = isError ? "UNAVAILABLE" : data.overall_status;
  const overallMeta = getStatusMeta(overallStatus);
  const pulse = overallStatus === "MOCK";
  const sources = data.sources.filter((s) => s.status === "LIVE" || s.status === "PARTIAL").slice(0, 3);
  const sourceSummary = useMemo(() => {
    if (sources.length === 0) return null;
    return sources.map((src) => SOURCE_SHORT[src.name] || src.name).join(" / ");
  }, [sources]);


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

      {sourceSummary ? (
        <>
          <div className="statusbar-sep" />
          <div className="statusbar-group text-[10px] text-[var(--fg-4)]">
            <span className="text-[var(--fg-5)]">数据源</span>
            <span className="truncate">{sourceSummary}</span>
          </div>
        </>
      ) : null}

      <div className="flex-1" />

      {isError && (
        <button type="button" className="statusbar-trigger statusbar-queue text-finance-accent-soft hover:text-finance-accent" onClick={refetch}>
          重试
        </button>
      )}
    </div>
  );
}
