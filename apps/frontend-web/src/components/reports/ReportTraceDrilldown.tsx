import type { ReactNode } from "react";
import { SourceTrace } from "@/components/shared/SourceTrace";
import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";

function ArtifactRefList({
  artifactRefs,
  emptyText,
}: {
  artifactRefs: ArtifactRef[];
  emptyText: string;
}) {
  if (artifactRefs.length === 0) {
    return <div className="text-[11px] text-[var(--fg-5)]">{emptyText}</div>;
  }

  return (
    <div className="space-y-2">
      {artifactRefs.map((artifact, index) => (
        <article
          key={`${artifact.artifact_id ?? artifact.path ?? artifact.file_path ?? "artifact"}-${index}`}
          className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card)] p-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] font-semibold text-[var(--fg-2)]">{artifact.artifact_type ?? "unknown"}</div>
            {artifact.is_primary ? (
              <span className="rounded-[var(--radius-md)] border border-[rgba(6,182,212,0.2)] bg-[rgba(6,182,212,0.08)] px-2 py-0.5 text-[10px] text-[var(--brand)]">
                primary
              </span>
            ) : null}
          </div>
          <div className="mt-2 grid gap-1.5 text-[10px] text-[var(--fg-5)]">
            <div className="flex items-start justify-between gap-3">
              <span>artifact_id</span>
              <span className="break-all text-right font-mono text-[var(--fg-4)]">{artifact.artifact_id ?? "-"}</span>
            </div>
            <div className="flex items-start justify-between gap-3">
              <span>path</span>
              <span className="break-all text-right font-mono text-[var(--fg-4)]">{artifact.path ?? artifact.file_path ?? "-"}</span>
            </div>
            <div className="flex items-start justify-between gap-3">
              <span>content_type</span>
              <span className="break-all text-right font-mono text-[var(--fg-4)]">{artifact.content_type ?? "-"}</span>
            </div>
            <div className="flex items-start justify-between gap-3">
              <span>generated_at</span>
              <span className="break-all text-right font-mono text-[var(--fg-4)]">{artifact.asOf ?? "-"}</span>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function JsonPayloadPreview({
  payload,
  emptyText,
}: {
  payload?: Record<string, unknown> | null;
  emptyText: string;
}) {
  if (!payload || Object.keys(payload).length === 0) {
    return <div className="text-[11px] text-[var(--fg-5)]">{emptyText}</div>;
  }

  return (
    <pre className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] p-3 text-[10px] leading-5 text-[var(--fg-3)]">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

function DrilldownSection({
  title,
  countLabel,
  defaultOpen = false,
  children,
}: {
  title: string;
  countLabel?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)]">
      <summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-semibold text-[var(--fg-2)]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span>{title}</span>
          {countLabel ? <span className="text-[10px] font-medium text-[var(--fg-5)]">{countLabel}</span> : null}
        </div>
      </summary>
      <div className="border-t border-[var(--border-faint)] px-3 py-3">{children}</div>
    </details>
  );
}

export function ReportTraceDrilldown({
  sourceRefs,
  artifactRefs,
  payload,
  showPayload = true,
  sourceTitle = "对应数据源",
  artifactTitle = "对应产物",
  payloadTitle = "原始载荷",
  defaultOpen = false,
}: {
  sourceRefs: SourceRef[];
  artifactRefs: ArtifactRef[];
  payload?: Record<string, unknown> | null;
  showPayload?: boolean;
  sourceTitle?: string;
  artifactTitle?: string;
  payloadTitle?: string;
  defaultOpen?: boolean;
}) {
  return (
    <div className="mt-3 space-y-2">
      <DrilldownSection title={sourceTitle} countLabel={`${sourceRefs.length} 条`} defaultOpen={defaultOpen}>
        <SourceTrace compact sourceRefs={sourceRefs} emptyText="当前条目没有 source_refs。" />
      </DrilldownSection>
      <DrilldownSection title={artifactTitle} countLabel={`${artifactRefs.length} 条`}>
        <ArtifactRefList artifactRefs={artifactRefs} emptyText="当前条目没有 artifact_refs。" />
      </DrilldownSection>
      {showPayload ? (
        <DrilldownSection title={payloadTitle}>
          <JsonPayloadPreview payload={payload} emptyText="当前条目没有可展示的 payload。" />
        </DrilldownSection>
      ) : null}
    </div>
  );
}
