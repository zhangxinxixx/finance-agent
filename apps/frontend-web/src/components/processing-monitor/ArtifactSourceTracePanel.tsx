import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type {
  ArtifactSourceTraceArtifactRef,
  ArtifactSourceTraceResponse,
  ArtifactSourceTraceSnapshotRef,
  ArtifactSourceTraceWarning,
} from "@/types/processing-monitor";

function statusTone(value: string): FAStatusTone {
  if (["live", "available", "success"].includes(value)) return "up";
  if (["partial", "stale", "fallback", "manual_required"].includes(value)) return "warn";
  if (["unavailable", "error", "failed"].includes(value)) return "down";
  return "neutral";
}

function EmptyRows({ description }: { description: string }) {
  return <div className="fa-faint-text">{description}</div>;
}

function ArtifactRows({ refs }: { refs: ArtifactSourceTraceArtifactRef[] }) {
  if (!refs.length) return <EmptyRows description="后端未返回产物引用。" />;
  return (
    <div className="grid gap-2">
      {refs.map((ref) => (
        <div key={ref.artifact_id} className="border-b border-[var(--border-faint)] pb-2 last:border-b-0 last:pb-0">
          <div className="fa-num fa-body-text break-all">{ref.artifact_id}</div>
          <div className="mt-1 fa-muted-text break-all">{ref.file_path || "后端未返回 file_path"}</div>
          <div className="mt-1 flex flex-wrap gap-2 fa-faint-text">
            <span>{ref.artifact_type || "类型未知"}</span>
            {ref.generated_at ? <span>{ref.generated_at}</span> : null}
            {ref.storage_backend ? <span>{ref.storage_backend}</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function SnapshotRows({ snapshots }: { snapshots: ArtifactSourceTraceSnapshotRef[] }) {
  if (!snapshots.length) return <EmptyRows description="后端未返回输入快照。" />;
  return (
    <div className="grid gap-2">
      {snapshots.map((snapshot) => (
        <div key={snapshot.snapshot_id} className="border-b border-[var(--border-faint)] pb-2 last:border-b-0 last:pb-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="fa-num fa-body-text break-all">{snapshot.snapshot_id}</span>
            <FAStatusPill tone={statusTone(snapshot.data_status)} dot={false}>{snapshot.data_status}</FAStatusPill>
          </div>
          <div className="mt-1 fa-muted-text break-all">
            {snapshot.snapshot_type || "类型未知"} · {snapshot.data_date ?? "日期未返回"} · {snapshot.run_id ?? "run 未返回"}
          </div>
          {snapshot.input_snapshot_ids.length ? (
            <div className="mt-1 fa-faint-text break-all">输入: {snapshot.input_snapshot_ids.join(" / ")}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function WarningRows({ warnings, emptyText }: { warnings: ArtifactSourceTraceWarning[]; emptyText: string }) {
  if (!warnings.length) return <EmptyRows description={emptyText} />;
  return (
    <div className="grid gap-2">
      {warnings.map((warning, index) => (
        <div key={`${warning.code}-${index}`} className="border-b border-[var(--border-faint)] pb-2 last:border-b-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="fa-num fa-body-text">{warning.code || "warning"}</span>
            <FAStatusPill tone={statusTone(warning.severity)} dot={false}>{warning.severity}</FAStatusPill>
          </div>
          <div className="mt-1 fa-muted-text break-words">{warning.message || "后端未返回说明。"}</div>
          {warning.field || warning.hint ? <div className="mt-1 fa-faint-text break-words">{[warning.field, warning.hint].filter(Boolean).join(" · ")}</div> : null}
        </div>
      ))}
    </div>
  );
}

export function ArtifactSourceTracePanel({ trace }: { trace: ArtifactSourceTraceResponse }) {
  return (
    <FACard
      title="Artifact Source Trace"
      eyebrow="SourceTraceResponse"
      accent="info"
      action={<FAStatusPill tone={statusTone(trace.data_status)}>{trace.data_status}</FAStatusPill>}
    >
      <div className="grid gap-3">
        <dl className="grid gap-3 sm:grid-cols-3">
          {[
            ["Run ID", trace.run_id],
            ["Snapshot ID", trace.snapshot_id],
            ["Snapshot", trace.snapshot?.snapshot_type ?? "后端未返回快照"],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="fa-label">{label}</dt>
              <dd className="mt-1 fa-num fa-body-text break-all">{value || "—"}</dd>
            </div>
          ))}
        </dl>

        <div className="grid gap-3 xl:grid-cols-2">
          <section>
            <div className="mb-2 fa-card-title">Source Refs</div>
            {trace.source_refs.length ? (
              <div className="grid gap-2">
                {trace.source_refs.map((ref, index) => (
                  <div
                    key={`${ref.source_id}-${ref.source_type}-${ref.file_path ?? ref.url ?? ref.endpoint ?? index}`}
                    className="border-b border-[var(--border-faint)] pb-2 last:border-b-0 last:pb-0"
                  >
                    <div className="fa-body-text break-words">{ref.source_name || ref.source_id}</div>
                    <div className="mt-1 fa-faint-text break-all">{ref.source_id || "后端未返回 source_id"} · {ref.source_type || "类型未知"}</div>
                    <div className="mt-1 fa-muted-text break-all">{ref.url ?? ref.file_path ?? ref.endpoint ?? "后端未返回位置"}</div>
                  </div>
                ))}
              </div>
            ) : <EmptyRows description="后端未返回来源引用。" />}
          </section>
          <section>
            <div className="mb-2 fa-card-title">Artifact Refs</div>
            <ArtifactRows refs={trace.artifact_refs} />
          </section>
          <section>
            <div className="mb-2 fa-card-title">Related Artifacts</div>
            <ArtifactRows refs={trace.related_artifacts} />
          </section>
          <section>
            <div className="mb-2 fa-card-title">Input Snapshots</div>
            <SnapshotRows snapshots={trace.input_snapshots} />
          </section>
          <section>
            <div className="mb-2 fa-card-title">Warnings</div>
            <WarningRows warnings={trace.warnings} emptyText="后端未返回 warnings。" />
          </section>
        </div>
      </div>
    </FACard>
  );
}
