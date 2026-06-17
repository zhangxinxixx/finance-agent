import type {
  DataSourceStatusViewModel,
  PipelineStageKey,
  SourcePipelineHealth,
  SourceDomain,
  SourcePriority,
} from "@/types/data-ingestion";
import { StageNode } from "./StageNode";
import { StageConnector } from "./StageConnector";

interface SourcePipelineRowProps {
  source: DataSourceStatusViewModel;
  selected?: boolean;
  onSelect?: (sourceId: string) => void;
  onStageClick?: (sourceId: string, stageKey: PipelineStageKey) => void;
}

const STAGE_KEYS: PipelineStageKey[] = [
  "connection",
  "collect",
  "rawLanding",
  "parse",
  "validate",
  "snapshot",
  "consumerReady",
];

const STAGE_LABELS: Record<PipelineStageKey, string> = {
  connection: "连接",
  collect: "采集",
  rawLanding: "Raw落地",
  parse: "解析",
  validate: "校验",
  snapshot: "快照",
  consumerReady: "下游可用",
};

/** Domain → color for the left indicator */
const DOMAIN_COLORS: Record<SourceDomain, string> = {
  macro: "#3b82f6",
  liquidity: "#3b82f6",
  cme: "#a78bfa",
  market: "#f59e0b",
  positioning: "#06b6d4",
  news: "#10b981",
  report: "#6b7280",
};

/** Priority → label */
const PRIORITY_LABELS: Record<SourcePriority, string> = {
  PRIMARY: "主源",
  FALLBACK: "备用",
  DERIVED: "派生",
  SUPPLEMENTAL: "补充",
};

/** Compute overall status from pipeline_health for the status dot */
function overallDotColor(health: SourcePipelineHealth | undefined): string {
  if (!health) return "var(--fg-6)";
  const { stages } = health;
  if (stages.connection.status === "ERROR") return "var(--down)";
  if (stages.collect.status === "ERROR" || stages.parse.status === "ERROR") return "var(--down)";
  if (health.downstreamStatus === "BLOCKED") return "var(--down)";
  if (health.downstreamStatus === "DEGRADED") return "var(--warn)";
  return "var(--up)";
}

export function SourcePipelineRow({ source, selected, onSelect, onStageClick }: SourcePipelineRowProps) {
  const health = source.pipeline_health;
  const dotColor = overallDotColor(health);
  const domainColor = DOMAIN_COLORS[source.group as SourceDomain] ?? "var(--fg-6)";

  return (
    <div
      className="group flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)] transition-colors cursor-pointer"
      style={{
        background: selected ? "var(--bg-active)" : undefined,
        borderLeft: selected ? `2px solid var(--brand)` : "2px solid transparent",
      }}
      onClick={() => onSelect?.(source.id)}
      onMouseEnter={(e) => {
        if (!selected) e.currentTarget.style.background = "var(--bg-hover)";
      }}
      onMouseLeave={(e) => {
        if (!selected) e.currentTarget.style.background = "";
      }}
    >
      {/* Status dot */}
      <div
        className="shrink-0 rounded-full"
        style={{ width: 6, height: 6, background: dotColor, boxShadow: `0 0 6px ${dotColor}` }}
      />

      {/* Source name + type */}
      <div className="flex flex-col min-w-[130px] max-w-[150px] shrink-0">
        <span className="text-[10px] font-semibold text-[var(--fg-2)] truncate leading-tight">
          {source.label}
        </span>
        <div className="flex items-center gap-1 mt-0.5">
          <span
            className="inline-block text-[7px] font-semibold uppercase tracking-wider px-1 py-px rounded"
            style={{
              background: `${domainColor}15`,
              color: domainColor,
              border: `1px solid ${domainColor}30`,
            }}
          >
            {source.type}
          </span>
          <span className="text-[7px] text-[var(--fg-6)]">{PRIORITY_LABELS[source.role as SourcePriority] ?? source.role}</span>
        </div>
      </div>

      {/* Latest data date badge */}
      {health?.latestDataDate && (
        <div className="shrink-0 flex flex-col items-center" style={{ minWidth: 50 }}>
          <span className="fa-num text-[8px] text-[var(--fg-5)]">{health.latestDataDate}</span>
          {health.stalenessDays !== null && health.stalenessDays !== undefined && (
            <span
              className="text-[7px] font-semibold px-1 rounded"
              style={{
                color: health.stalenessDays <= 1 ? "var(--up)" : health.stalenessDays <= 3 ? "var(--warn)" : "var(--down)",
                background: health.stalenessDays <= 1 ? "var(--up-soft)" : health.stalenessDays <= 3 ? "var(--warn-soft)" : "var(--down-soft)",
              }}
            >
              {health.stalenessDays === 0 ? "今天" : `${health.stalenessDays}d`}
            </span>
          )}
        </div>
      )}

      {/* 7-stage pipeline chain */}
      <div className="flex items-center gap-0 flex-1 min-w-0">
        {health ? (
          STAGE_KEYS.map((key, idx) => {
            const stage = health.stages[key];
            return (
              <div key={key} className="flex items-center">
                <StageNode
                  status={stage.status}
                  label={STAGE_LABELS[key]}
                  message={stage.message}
                  onClick={() => onStageClick?.(source.id, key)}
                />
                {idx < STAGE_KEYS.length - 1 && (
                  <StageConnector
                    fromStatus={stage.status}
                    toStatus={health.stages[STAGE_KEYS[idx + 1]].status}
                  />
                )}
              </div>
            );
          })
        ) : (
          /* Fallback: show boolean flags as simple indicators */
          <div className="flex items-center gap-1 text-[8px]">
            {source.configured ? <span className="text-[var(--up)]">●</span> : <span className="text-[var(--down)]">●</span>}
            <span className="text-[var(--fg-6)]">配置</span>
            {source.raw_ingested ? <span className="text-[var(--up)]">●</span> : <span className="text-[var(--down)]">●</span>}
            <span className="text-[var(--fg-6)]">采集</span>
            {source.parsed ? <span className="text-[var(--up)]">●</span> : <span className="text-[var(--down)]">●</span>}
            <span className="text-[var(--fg-6)]">解析</span>
            {source.analysis_ready ? <span className="text-[var(--up)]">●</span> : <span className="text-[var(--down)]">●</span>}
            <span className="text-[var(--fg-6)]">就绪</span>
          </div>
        )}
      </div>

      {/* Affected modules */}
      {health && (
        <div className="hidden xl:flex items-center gap-1 shrink-0 max-w-[140px]">
          {health.affectedModules.slice(0, 3).map((mod) => (
            <span
              key={mod}
              className="text-[7px] font-medium px-1 py-px rounded"
              style={{
                background: "var(--bg-card-inner)",
                color: "var(--fg-5)",
                border: "1px solid var(--border-faint)",
              }}
            >
              {mod}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
