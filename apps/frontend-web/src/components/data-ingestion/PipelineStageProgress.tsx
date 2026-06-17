import type { DataSourceStatusViewModel, PipelineStageKey } from "@/types/data-ingestion";
import { StageNode } from "./StageNode";

interface PipelineStageProgressProps {
  sources: DataSourceStatusViewModel[];
  onStageFilter?: (stageKey: PipelineStageKey | null) => void;
  activeFilter?: PipelineStageKey | null;
}

const STAGES: Array<{ key: PipelineStageKey; label: string }> = [
  { key: "connection",    label: "连接" },
  { key: "collect",       label: "采集" },
  { key: "rawLanding",    label: "Raw" },
  { key: "parse",         label: "解析" },
  { key: "validate",      label: "校验" },
  { key: "snapshot",      label: "快照" },
  { key: "consumerReady", label: "下游" },
];

function countHealthy(sources: DataSourceStatusViewModel[], stageKey: PipelineStageKey): number {
  return sources.filter((s) => {
    const h = s.pipeline_health?.stages[stageKey];
    return h && (h.status === "OK" || h.status === "READY");
  }).length;
}

function aggStatus(sources: DataSourceStatusViewModel[], stageKey: PipelineStageKey): "OK" | "WARN" | "ERROR" | "NO_DATA" {
  const total = sources.length;
  if (total === 0) return "NO_DATA";
  const healthy = countHealthy(sources, stageKey);
  if (healthy === total) return "OK";
  if (healthy === 0) return "ERROR";
  return "WARN";
}

export function PipelineStageProgress({ sources, onStageFilter, activeFilter }: PipelineStageProgressProps) {
  return (
    <div className="flex items-center gap-0 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shrink-0 overflow-x-auto">
      {/* Source count label */}
      <div className="flex flex-col items-center mr-2 shrink-0">
        <span className="fa-num text-[14px] font-bold text-[var(--fg-1)]">{sources.length}</span>
        <span className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">数据源</span>
      </div>

      {STAGES.map(({ key, label }, idx) => {
        const healthy = countHealthy(sources, key);
        const status = aggStatus(sources, key);
        const isActive = activeFilter === key;

        return (
          <div key={key} className="flex items-center">
            {/* Arrow between stages */}
            {idx > 0 && (
              <svg width="16" height="14" viewBox="0 0 16 14" className="shrink-0 mx-0.5">
                <line x1="0" y1="7" x2="10" y2="7" stroke="var(--border)" strokeWidth="1" />
                <path d="M10 4 L14 7 L10 10" fill="none" stroke="var(--border)" strokeWidth="1" strokeLinecap="round" />
              </svg>
            )}

            {/* Stage node with count */}
            <div
              className="flex flex-col items-center gap-0.5 cursor-pointer px-1 py-0.5 rounded transition-colors shrink-0"
              style={{
                background: isActive ? "var(--bg-active)" : undefined,
                outline: isActive ? "1px solid var(--brand)" : undefined,
              }}
              onClick={() => onStageFilter?.(activeFilter === key ? null : key)}
            >
              <StageNode status={status} compact />
              <span className="text-[8px] font-semibold text-[var(--fg-4)] whitespace-nowrap">{label}</span>
              <span className="fa-num text-[9px] font-bold" style={{ color: status === "OK" ? "var(--up)" : status === "WARN" ? "var(--warn)" : "var(--down)" }}>
                {healthy}/{sources.length}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
