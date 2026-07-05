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

function compactDateLabel(value: string): string {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[2]}-${match[3]}` : value;
}

/** Compute overall status from pipeline_health for the status dot */
function overallDotColor(health: SourcePipelineHealth): string {
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
      className="data-ingestion-source-row data-ingestion-matrix-row group px-2 py-1.5 transition-colors cursor-pointer"
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
        style={{ width: 6, height: 6, background: dotColor }}
      />

      {/* Source name + type */}
      <div className="flex min-w-0 flex-col">
        <span className="text-[12px] font-semibold text-[var(--fg-2)] truncate leading-tight" title={source.label}>
          {source.label}
        </span>
        <div className="flex items-center gap-1 mt-0.5">
          <span
            className="inline-block text-[10px] font-semibold uppercase tracking-[0] px-1.5 py-px rounded"
            style={{
              background: `${domainColor}15`,
              color: domainColor,
              border: `1px solid ${domainColor}30`,
            }}
          >
            {source.type}
          </span>
          <span className="text-[10px] text-[var(--fg-5)]">{PRIORITY_LABELS[source.role as SourcePriority] ?? source.role}</span>
        </div>
      </div>

      {/* Latest data date badge */}
      <div className="flex min-w-0 flex-col items-center">
        {health.latestDataDate ? (
          <>
          <span className="fa-num text-[10px] text-[var(--fg-4)]" title={health.latestDataDate}>
            {compactDateLabel(health.latestDataDate)}
          </span>
          {health.stalenessDays !== null && health.stalenessDays !== undefined && (
            <span
              className="text-[10px] font-semibold px-1.5 rounded"
              style={{
                color: health.stalenessDays <= 1 ? "var(--up)" : health.stalenessDays <= 3 ? "var(--warn)" : "var(--down)",
                background: health.stalenessDays <= 1 ? "var(--up-soft)" : health.stalenessDays <= 3 ? "var(--warn-soft)" : "var(--down-soft)",
              }}
            >
              {health.stalenessDays === 0 ? "今天" : `${health.stalenessDays}d`}
            </span>
          )}
          </>
        ) : (
          <span className="text-[10px] text-[var(--fg-6)]">—</span>
        )}
      </div>

      {/* 7-stage pipeline chain */}
      <div className="data-ingestion-stage-chain">
        {STAGE_KEYS.map((key, idx) => {
          const stage = health.stages[key];
          return (
            <div key={key} className="flex items-center">
              <StageNode
                status={stage.status}
                label={STAGE_LABELS[key]}
                message={stage.message}
                compact
                onClick={() => onStageClick?.(source.id, key)}
              />
              {idx < STAGE_KEYS.length - 1 && (
                <StageConnector
                  fromStatus={stage.status}
                  toStatus={health.stages[STAGE_KEYS[idx + 1]].status}
                  compact
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Affected modules */}
      <div className="data-ingestion-module-cell">
        {health.affectedModules.slice(0, 3).map((mod) => (
          <span
            key={mod}
            className="text-[10px] font-medium px-1.5 py-px rounded"
            title={mod}
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
    </div>
  );
}
