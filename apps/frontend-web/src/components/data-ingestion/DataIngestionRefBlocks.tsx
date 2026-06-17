import { Link } from "react-router-dom";
import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { EvidencePathRow } from "./DataIngestionDetailBlocks.shared";

export function SourceArtifactEvidenceBlock({
  preferred,
  collectorRaw,
  collectorParsed,
}: {
  preferred: string | null | undefined;
  collectorRaw: string | null | undefined;
  collectorParsed: string | null | undefined;
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">产出物路径</div>
      <div className="mt-1 flex flex-col gap-1.5">
        {preferred ? <EvidencePathRow label="首选产出" value={preferred} /> : null}
        {collectorRaw ? <EvidencePathRow label="采集原始" value={collectorRaw} /> : null}
        {collectorParsed ? <EvidencePathRow label="采集解析" value={collectorParsed} /> : null}
        {!preferred && !collectorRaw && !collectorParsed ? <div className="text-[9px] text-[var(--fg-5)]">暂无产出物路径。</div> : null}
      </div>
    </div>
  );
}

export function SourceDrilldownBlock({ lastRunId }: { lastRunId: string | null | undefined }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">下钻入口</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {lastRunId ? (
          <Link
            to={`/agent-tasks/${encodeURIComponent(lastRunId)}`}
            className="rounded-full border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-1 text-[9px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-1)]"
          >
            任务详情 · {lastRunId}
          </Link>
        ) : (
          <span className="text-[9px] text-[var(--fg-5)]">暂无运行记录，无法跳转到任务详情。</span>
        )}
      </div>
    </div>
  );
}

export function SourceRawAndStageRefsBlock({
  rawArtifactRef,
  stageRefs,
}: {
  rawArtifactRef: string | null | undefined;
  stageRefs: Array<{ key: string; label: string; value: string }>;
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">原始数据 / 阶段引用</div>
      <div className="mt-1 flex flex-col gap-1">
        {rawArtifactRef ? (
          <div className="truncate font-mono text-[8px] text-[var(--fg-4)]" title={rawArtifactRef}>
            原始 · {rawArtifactRef}
          </div>
        ) : null}
        {stageRefs.map((ref) => (
          <div key={ref.key} className="truncate font-mono text-[8px] text-[var(--fg-5)]" title={ref.value}>
            {ref.label} · {ref.value}
          </div>
        ))}
        {!rawArtifactRef && stageRefs.length === 0 ? <div className="text-[9px] text-[var(--fg-5)]">暂无原始数据或阶段引用。</div> : null}
      </div>
    </div>
  );
}

export function SourceRefsBlock({ sourceRefs }: { sourceRefs: DataSourceStatusViewModel["source_refs"] }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">数据引用</div>
      <div className="mt-1 flex flex-col gap-1">
        {sourceRefs.length === 0 ? (
          <div className="text-[9px] text-[var(--fg-5)]">暂无数据引用记录。</div>
        ) : (
          sourceRefs.map((ref) => (
            <div key={`${ref.source_ref}-${ref.snapshot_id ?? ""}`} className="truncate font-mono text-[8px] text-[var(--fg-5)]">
              {ref.source_ref}
              {ref.endpoint ? ` · ${ref.endpoint}` : ""}
              {ref.artifact_path ? ` · ${ref.artifact_path}` : ""}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
